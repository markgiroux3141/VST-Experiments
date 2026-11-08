"""The Novachord's keys compiled for the live tier (docs/NOVACHORD_PLAN.md, NV4; circuitsim's
novachord.rs is the medium that plays them).

The reference is the literal instrument, config/circuits/novachord.yaml. The compile takes
from it:

  - **the dividers' waveforms**: the reference rendered with every key up and the vibrato
    off (`record`), each oscillator's coil tap and its five dividers' cathodes; per note the
    cathodes binned over 32 cycles of the tap's upward zero crossings (`tables`), the
    locked waveforms the medium reads at the oscillator's live phase. The bins are averaged
    over the recording's frames of 32 cycles; `lock_rms_v` says how far a frame strays
    from the table (a divider that slipped would show here);
  - **the oscillators** (`oscillator_curves`, `tap_tables`): each one's frequency against
    its vibrato triode's grid per vibrato switch state, the reed line held at DC over a
    sweep (the reference's oscillator alone, its first divider and top key's grid on it);
    its tap over a cycle from the recording;
  - **each key's values** (`key_values`): its grid network, cathode and playing key's
    parts, read off the reference's IR at MELLOW (so CN30 and the top octave's RN8 are
    there), its cut-off tap from its spring 1's contact, the control tube's model and the
    screen's rail.

Saved as a component version of kind `nova_keys` (`save`): config/components/
novachord_keys/<N>.yaml naming its data <N>.keys.json by sha256, which the builders check
(`ir_data`). `scripts/compile_novachord_keys.py` runs it.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np

from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.devices import versions

COMPONENT = "NOVACHORD_KEYS"
KIND = "nova_keys"
DATA_SUFFIX = ".keys.json"
CIRCUIT = CONFIG_DIR / "circuits" / "novachord.yaml"
CACHE = REPO_ROOT / "cache" / "novachord"
NAMES = ("F", "Fs", "G", "Gs", "A", "As", "B", "C", "Cs", "D", "Ds", "E")
CYCLES = 32
POINTS_PER_CYCLE = 128
RECORD_S = 0.6


def _script(name: str):
    sp = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def record_probes() -> list[str]:
    """Per note its coil's tap and its five dividers' cathodes (channels 1-5)."""
    out = []
    for n in NAMES:
        low = n.lower()
        out.append(f"{low}o_t1")
        out += [f"{low}d{ch}_k" for ch in range(1, 6)]
    return out


def _record_key(quality: str, seconds: float) -> str:
    h = hashlib.sha256()
    h.update(CIRCUIT.read_bytes())
    h.update(f"{quality} {seconds} {CYCLES} v1".encode())
    return h.hexdigest()[:16]


def record(quality: str = "draft", seconds: float = RECORD_S, progress=print) -> dict:
    """The reference with every key up and the vibrato off, settled (the renderer's
    settling), then `seconds` recorded at the sample rate: {probe: array, "fs": rate}.
    Cached in cache/novachord/ by the circuit file, the quality and the length."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"reference_{_record_key(quality, seconds)}.npz"
    if path.exists():
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    nr = _script("novachord_render")
    probes = tuple(record_probes())
    if progress:
        progress(f"recording the reference ({quality}, {seconds} s, every key up) ...")
    v, el, _ = nr.render([], seconds, quality, {"amp": 0}, threads=4, probes=probes, progress=None)
    out = {p: np.asarray(v[p], dtype=np.float64) for p in probes}
    out["fs"] = np.array(96000.0)
    np.savez(path, **out)
    if progress:
        progress(f"  {el:.0f} s ({el / seconds:.0f}x real time) -> {path}")
    return out


def crossings(t1: np.ndarray) -> np.ndarray:
    """Upward zero crossings of the tap, interpolated (sample positions)."""
    i = np.nonzero((t1[:-1] < 0.0) & (t1[1:] >= 0.0))[0] + 1
    a, b = t1[i - 1], t1[i]
    return (i - 1) + a / (a - b)


def tables(rec: dict) -> tuple[list[dict], dict]:
    """Per note its frequency and its five dividers' tables over CYCLES cycles; and the
    lock check (each frame's rms distance from the table, worst per note and channel)."""
    fs = float(rec["fs"])
    notes, lock = [], {}
    n_bins = CYCLES * POINTS_PER_CYCLE
    for n in NAMES:
        low = n.lower()
        tc = crossings(rec[f"{low}o_t1"])
        if len(tc) < 2 * CYCLES + 2:
            raise RuntimeError(f"note {n}: {len(tc)} crossings, too few to tabulate")
        f0 = (len(tc) - 1) / (tc[-1] - tc[0]) * fs
        # every sample between the first and last crossing: its phase in cycles
        i = np.arange(int(np.ceil(tc[0])), int(np.floor(tc[-1])))
        c = np.searchsorted(tc, i, side="right") - 1
        phi = c + (i - tc[c]) / (tc[c + 1] - tc[c])
        pos = (phi % CYCLES) * POINTS_PER_CYCLE
        j0 = np.floor(pos).astype(int) % n_bins
        w = pos - np.floor(pos)
        j1 = (j0 + 1) % n_bins
        weight = np.bincount(j0, 1.0 - w, n_bins) + np.bincount(j1, w, n_bins)
        chans = []
        worst = []
        for ch in range(1, 6):
            y = rec[f"{low}d{ch}_k"][i]
            acc = np.bincount(j0, (1.0 - w) * y, n_bins) + np.bincount(j1, w * y, n_bins)
            ok = weight > 0
            t = np.zeros(n_bins)
            t[ok] = acc[ok] / weight[ok]
            if not ok.all():
                x = np.arange(n_bins)
                t[~ok] = np.interp(x[~ok], x[ok], t[ok], period=n_bins)
            # the lock check: each whole frame against the table at its phases
            frame = (phi // CYCLES).astype(int)
            ref = t[j0] * (1.0 - w) + t[j1] * w
            dev = [
                float(np.sqrt(np.mean((y[frame == f] - ref[frame == f]) ** 2)))
                for f in range(frame.min() + 1, frame.max())
            ]
            worst.append(round(max(dev), 6) if dev else None)
            chans.append([round(float(x), 7) for x in t])
        notes.append({"name": n.replace("s", "#"), "f0_hz": float(f0), "tables": chans})
        lock[n] = {"f0_hz": round(float(f0), 4), "worst_frame_rms_v": worst}
    return notes, lock


def tap_tables(rec: dict) -> list[list[float]]:
    """Per note its coil's tap over one cycle (POINTS_PER_CYCLE points from an upward
    zero crossing), averaged over the recording: the top octave's grid drive."""
    out = []
    for n in NAMES:
        t1 = rec[f"{n.lower()}o_t1"]
        tc = crossings(t1)
        i = np.arange(int(np.ceil(tc[0])), int(np.floor(tc[-1])))
        c = np.searchsorted(tc, i, side="right") - 1
        pos = ((i - tc[c]) / (tc[c + 1] - tc[c])) * POINTS_PER_CYCLE
        j0 = np.floor(pos).astype(int) % POINTS_PER_CYCLE
        w = pos - np.floor(pos)
        j1 = (j0 + 1) % POINTS_PER_CYCLE
        y = t1[i]
        acc = np.bincount(j0, (1 - w) * y, POINTS_PER_CYCLE) + np.bincount(
            j1, w * y, POINTS_PER_CYCLE
        )
        wt = np.bincount(j0, 1 - w, POINTS_PER_CYCLE) + np.bincount(j1, w, POINTS_PER_CYCLE)
        out.append([round(float(x), 7) for x in acc / wt])
    return out


#: The vibrato switches' states, in the curves' order: (NORMAL, SMALL).
VIB_STATES = ((0, 0), (0, 1), (1, 0), (1, 1))
#: The reed line's voltage swept (its open and grounded extremes with a margin; the line
#: sits between ground and the bias network's divide, ~-23 V at SMALL off).
SWEEP_VP = tuple(float(x) for x in np.linspace(-28.0, 2.0, 11))
OSC_SETTLE_S, OSC_MEASURE_S = 0.6, 0.25


def _osc_circuit(note: int) -> Path:
    """The reference's oscillator for note index `note` alone, as novachord.yaml has it: its
    section, its first divider (its plate's load; the next divider's coupling left out),
    the top key's grid divider on its tap, the supplies and the vibrato's bias network, its
    reed line an ideal source `vp_test_v`. Written to cache/novachord/."""
    import yaml

    d = yaml.safe_load(CIRCUIT.read_text(encoding="utf-8"))
    name = ("F", "F#", "G", "G#", "A", "A#", "B", "C", "C#", "D", "D#", "E")[note]
    n = NAMES[note]
    key = 61 + note
    keep = {"supply", "vibrato bias", f"oscillator {name}", f"divider {name} channel 5"}
    secs = []
    for s in d["sections"]:
        if s["title"] in keep:
            parts = dict(s["parts"])
            if s["title"].startswith("divider"):
                parts.pop(f"CN{n}D51")
            secs.append({"title": s["title"], "parts": parts})
        elif s["title"].startswith(f"key {key} "):
            p = s["parts"]
            secs.append(
                {
                    "title": "top key's grid",
                    "parts": {k: p[k] for k in (f"RNK{key}_19", f"RNK{key}_2", f"SWK{key}_M")},
                }
            )
    secs.append(
        {
            "title": "test",
            "parts": {
                "RIN": {"R": ["in", "0"], "r": "r_in_ohm"},
                "VTEST": {"V": [f"vib_p{note // 2}", "0"], "v": "vp_test_v"},
            },
        }
    )
    d["sections"] = secs
    d["values"]["vp_test_v"] = {
        "value": 0.0,
        "source": "numerical: the reed line held for the sweep",
    }
    used: set = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            used.add(x)

    walk(secs)
    d["devices"] = {k: v for k, v in d["devices"].items() if k in used}
    d["controls"] = {
        k: v for k, v in d["controls"].items() if not (k[0] in "ks" and k[1:].isdigit())
    }
    low = n.lower()
    d["probes"] = [f"{low}o_t1", f"{low}o_g2"]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"osc_{low}.yaml"
    path.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    return path


def oscillator_curves(quality: str = "draft", progress=print) -> dict:
    """Per note and vibrato state (VIB_STATES), the oscillator's frequency against its
    vibrato triode's grid (o_g2's mean), the reed line swept over SWEEP_VP: {"v": [...],
    "f_hz": [...]} ascending in v. The grid moves at the reed's 7 Hz through ~1 ms of RC,
    the tank answers within cycles: quasi-static. Cached in cache/novachord/."""
    import dataclasses

    import circuitsim

    from varimu.circuit import builder, spec
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    h = hashlib.sha256(CIRCUIT.read_bytes())
    h.update(f"{quality} {SWEEP_VP} {VIB_STATES} {OSC_SETTLE_S} {OSC_MEASURE_S} v1".encode())
    path = CACHE / f"oscillators_{h.hexdigest()[:16]}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    fast.check_build()
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    fs = st.sim_rate
    n_settle, n_meas = int(OSC_SETTLE_S * fs), int(OSC_MEASURE_S * fs)
    out: dict = {}
    for note, n in enumerate(NAMES):
        s = spec.load_circuit(_osc_circuit(note))
        low = n.lower()
        curves = []
        for normal, small in VIB_STATES:
            vs, fs_hz = [], []
            for vp in SWEEP_VP:
                p = spec.resolve(
                    s, {"normal_vibrato": normal, "small_vibrato": small, "vp_test_v": vp}
                )
                ir = builder.build_ir(s, p)
                o = circuitsim.simulate(
                    ir.to_json(), np.zeros(n_settle + n_meas), 1.0 / fs, st.method,
                    solver=st.solver, reltol=st.newton_reltol, vntol=st.newton_vntol,
                    input_order=st.input_order, newton_reuse=st.newton_reuse,
                    tube_tables=st.tube_tables, error_abstol=st.error_abstol,
                    error_reltol=st.error_reltol, step_selection=st.step_selection,
                    error_norm=st.error_norm,
                )  # fmt: skip
                t1 = np.asarray(o[f"v({low}o_t1)"])[n_settle:]
                g2 = np.asarray(o[f"v({low}o_g2)"])[n_settle:]
                tc = crossings(t1)
                vs.append(float(np.mean(g2)))
                fs_hz.append(float((len(tc) - 1) / (tc[-1] - tc[0]) * fs))
            order = np.argsort(vs)
            curves.append(
                {"v": [round(vs[i], 6) for i in order], "f_hz": [round(fs_hz[i], 6) for i in order]}
            )
        out[n] = curves
        if progress:
            spans = [f"{1200 * np.log2(max(c['f_hz']) / min(c['f_hz'])):.1f}" for c in curves]
            progress(f"  {n}: f {curves[0]['f_hz'][0]:.2f} Hz; span over the sweep (cents) {spans}")
    path.write_text(json.dumps(out), encoding="utf-8")
    del dataclasses
    return out


def key_values(mellow_ir) -> tuple[list[dict], dict, float]:
    """Each key's values off the reference's IR built at MELLOW; the control tube's model
    (IR JSON) and the screen's rail."""
    from varimu.circuit.ir import Capacitor, Device, Resistor, VoltageSource, model_to_dict

    els = {e.name: e for e in mellow_ir.elements()}

    def r(name):
        e = els.get(name)
        if e is None:
            return 0.0
        assert isinstance(e, Resistor), name
        return float(e.r_ohm)

    def c(name):
        e = els.get(name)
        if e is None:
            return 0.0
        assert isinstance(e, Capacitor), name
        return float(e.c_f)

    taps = {"cut_y": 0, "cut_o": 1, "cut_r": 2, "keyp": 3}
    keys = []
    models = set()
    for k in range(1, 73):
        t = f"K{k}_"
        dev = els[f"X{t}"]
        assert isinstance(dev, Device)
        models.add(dev.model)
        spring1 = els[f"RS{t}1"]
        tap_node = spring1.a if spring1.a in taps else spring1.b
        keys.append(
            {
                "key": k,
                "group": (k - 1) // 4,
                "note": (k - 1) % 12,
                "ch": (k - 1) // 12 + 1,
                "rn1_ohm": r(f"RN{t}1"),
                "cn5_f": c(f"CN{t}5"),
                "rn19_ohm": r(f"RN{t}19"),
                "rn2_ohm": r(f"RN{t}2"),
                "cn29_f": c(f"CN{t}29"),
                "cn30_f": c(f"CN{t}30"),
                "rn8_ohm": r(f"RN{t}8"),
                "cn15_f": c(f"CN{t}15"),
                "rn7_ohm": r(f"RN{t}7"),
                "cn7_f": c(f"CN{t}7"),
                "rn10_ohm": r(f"RN{t}10"),
                "rn12_ohm": r(f"RN{t}12"),
                "cn8_f": c(f"CN{t}8"),
                "rn11_ohm": r(f"RN{t}11"),
                "tap": taps[tap_node],
            }
        )
    tube_models = [m for m in mellow_ir.models if m.name in models]
    first = {k: v for k, v in model_to_dict(tube_models[0]).items() if k not in ("kind", "name")}
    for m in tube_models[1:]:
        d = {k: v for k, v in model_to_dict(m).items() if k not in ("kind", "name")}
        if d != first:
            raise ValueError(f"the control tubes differ ({m.name}): a spread isn't compiled")
    tube = {"name": "6W7G_control", **first}
    vb34 = els["VB34"]
    assert isinstance(vb34, VoltageSource)
    return keys, tube, float(vb34.dc_v)


def compile_keys(quality: str = "draft", progress=print) -> dict[str, Any]:
    """The compiled keys (the data file's content)."""
    from varimu.circuit import builder, spec

    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {"mellow": 1, "amp": 0}))
    keys, tube, screen_v = key_values(ir)
    rec = record(quality, progress=progress)
    notes, lock = tables(rec)
    curves = oscillator_curves(quality, progress=progress)
    for nd, n, tap in zip(notes, NAMES, tap_tables(rec), strict=True):
        nd["tap"] = tap
        nd["vibrato"] = curves[n]
    return {
        "format": 1,
        "cycles": CYCLES,
        "points_per_cycle": POINTS_PER_CYCLE,
        "screen_v": screen_v,
        "tube": tube,
        "notes": notes,
        "keys": keys,
        "provenance": {
            "circuit": "config/circuits/novachord.yaml",
            "circuit_sha256": hashlib.sha256(CIRCUIT.read_bytes()).hexdigest(),
            "quality": quality,
            "recorded_s": RECORD_S,
            "lock": lock,
        },
    }


def _dump(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=False) + "\n"


def _yaml(name: str, data_file: str, sha: str, prov: dict) -> str:
    return (
        f"# Generated by varimu/novachord/compile.py (scripts/compile_novachord_keys.py) on"
        f" {_dt.date.today().isoformat()}.\n"
        "# Don't edit by hand: change the reference circuit (scripts/make_novachord.py) and\n"
        "# recompile.\n"
        f"name: {name}\n"
        f"kind: {KIND}\n"
        "source: \"the Hammond Novachord's 72 keys for the live tier (docs/NOVACHORD_PLAN.md\n"
        "  NV4), compiled from the reference circuit config/circuits/novachord.yaml\n"
        "  (scripts/make_novachord.py; its sources in data/schematics/hammond_novachord/): each\n"
        "  key's grid network, control tube and playing key off its IR, the dividers'\n"
        "  cathodes recorded with every key up and tabulated over 32 cycles of their\n"
        f'  oscillator ({prov["quality"]} quality)"\n'
        "circuit:\n"
        f"  file: {prov['circuit']}\n"
        f"  sha256: {prov['circuit_sha256']}\n"
        "data:\n"
        f"  file: {data_file}\n"
        f"  sha256: {sha}\n"
    )


def save(data: dict[str, Any], name: str = COMPONENT) -> versions.Ref | None:
    """Save as component `name`'s next version, unless the latest one's data is the same
    (None then)."""
    text = _dump(data)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    have = versions.versions(name)
    if have:
        _, _, d = files(f"{name}@{have[-1]}")
        if d["data"]["sha256"] == sha:
            return None
    n = (have or [0])[-1] + 1
    folder = versions.COMPONENT_DIR / name.lower()
    folder.mkdir(parents=True, exist_ok=True)
    df = f"{n}{DATA_SUFFIX}"
    (folder / df).write_text(text, encoding="utf-8", newline="\n")
    ref = versions.save(name, _yaml(name, df, sha, data["provenance"]))
    if ref.version != n:
        raise RuntimeError(f"saved {ref}, expected version {n}")
    return ref


def files(ref: str) -> tuple[Path, str, dict[str, Any]]:
    """(the data's path, its sha256, the version's YAML) of keys version `ref`, the data
    checked against the sha256 the version names."""
    import yaml

    r, text = versions.read_text(ref)
    d = yaml.safe_load(text)
    if d.get("kind") != KIND:
        raise ValueError(f"{r} is not the Novachord's keys (kind {d.get('kind')!r})")
    p = versions.COMPONENT_DIR / r.folder / d["data"]["file"]
    raw = p.read_text(encoding="utf-8").replace("\r\n", "\n")
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if sha != d["data"]["sha256"]:
        raise versions.VersionError(f"{r}'s data {p.name} doesn't match its sha256")
    return p, sha, d


_CHECKED: dict[tuple[str, int, int], str] = {}


def ir_data(ref: str) -> tuple[str, str]:
    """(the data's path relative to the repository's root, forward slashes; its sha256) of
    keys version `ref`, as the IR's nova_keys element names them (checked once per process
    while the file's size and time are unchanged)."""
    import yaml

    r, text = versions.read_text(ref)
    d = yaml.safe_load(text)
    if d.get("kind") != KIND:
        raise ValueError(f"{r} is not the Novachord's keys (kind {d.get('kind')!r})")
    p = versions.COMPONENT_DIR / r.folder / d["data"]["file"]
    st = p.stat()
    key = (str(p), st.st_size, st.st_mtime_ns)
    sha = d["data"]["sha256"]
    if _CHECKED.get(key) != sha:
        files(ref)
        _CHECKED[key] = sha
    return p.resolve().relative_to(REPO_ROOT.resolve()).as_posix(), sha


def load(ref: str) -> dict[str, Any]:
    p, _, _ = files(ref)
    return json.loads(p.read_text(encoding="utf-8"))
