"""A spike: the U47 -> V76 with every gap of the chains we could name, through repeated passes
(2026-11-14; scripts/chain_passes.py's experiment; the user away, every call below is mine).

    uv run --extra fast --extra listen python scripts/chain_spike.py [--calibrate-only]
        [--variants all ...] [--workers N]

Mechanisms (each switchable; every value has its source next to it):

- `noise`: B5's noise (resistors, windings, the tubes' shot and flicker noise, the capsule's
  acoustic resistances), a seed per stem and pass.
- `mismatch`: the unit's tolerance draws (passive_spread 1: every part and tube uniform across its
  class's band, seed MISMATCH_SEED): one real unit instead of the nominal one.
- `hum`: three paths. The NG's ripple on the U47's supply (100 Hz and harmonics; calibrated to
  RIPPLE_TARGET_V at the U47's output). The V76's heaters into its cathodes (heater-cathode
  capacitance and leakage; V1 on its own winding and 250 ohm hum pot, V2-V4 on a winding with one
  end grounded in the drawing's silence, taken balanced: see CATHODES). T90's stray field into
  T85 (50 Hz and odd harmonics; calibrated so the V76 meets
  its noise spec, -120 dB re 0.775 V unweighted, with V76_MARGIN_DB to spare, from a 200 ohm
  source).
- `excess`: carbon-film resistors' current noise, 1/f, from each resistor's DC.
- `capsule`: the K47's electrostatic second order. A membrane isn't a piston: at constant charge
  the parabolic deflection over the backplate gives a term in (x / h)^2.
- `microphonics`: the VF14's electrodes ringing in the sound field. Three modes at a level that
  is invented (MICRO_*): a "selected" tube, no source.

What isn't in the solved circuit enters it as control inputs: the ripple, the heater voltages,
the stray field, the excess noise, the capsule's second-order term and the microphonic grid
voltage. Each is a series EMF (a 1 ohm resistor fed by a VCCS) or a Norton source. The capsule's
term and the microphonic voltage are computed from the linear capsule. The capsule's electrical
back-reaction is negligible (varimu/devices/capsule.py), so this is a first-order perturbation.

Variants (VARIANTS): `all` and `all_but_microphonics` at 100 dB SPL with the V76 at 24 dB;
`quiet_all` at 80 dB SPL with the V76 at 46 dB (a quiet source, more gain: noise counts more);
and each mechanism alone on pass 1 against the nominal, noiseless pass 1 (scripts/chain_passes.py's
cache). Reports in reports/chain_spike/ (README.md), cache in cache/chain_spike/.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chain_passes as cp  # noqa: E402

from varimu.circuit import builder  # noqa: E402
from varimu.circuit.ir import (  # noqa: E402
    Capacitor,
    Control,
    NoiseCurrent,
    Resistor,
    Section,
    TubeNoise,
    Vccs,
    VoltageProbe,
)
from varimu.config import REPO_ROOT  # noqa: E402
from varimu.devices import capsule as cap  # noqa: E402
from varimu.devices.library import component_data  # noqa: E402
from varimu.sim import fast  # noqa: E402

VERSION = "spike-2"
CHAIN = "u47_v76"
CACHE = REPO_ROOT / "cache" / "chain_spike"
OUT = REPO_ROOT / "reports" / "chain_spike"
MECHS = ("noise", "mismatch", "hum", "excess", "capsule", "microphonics")
VARIANTS = {
    "all": {"mechs": MECHS, "spl_db": 100.0, "gain_db": 24, "passes": 8},
    "all_but_microphonics": {
        "mechs": tuple(m for m in MECHS if m != "microphonics"),
        "spl_db": 100.0,
        "gain_db": 24,
        "passes": 8,
    },  # fmt: skip
    "quiet_all": {"mechs": MECHS, "spl_db": 80.0, "gain_db": 46, "passes": 8},
}
FADE_IN_S = 0.02

# --- mismatch -------------------------------------------------------------------------------
MISMATCH_SEED = 1  # numerical: which unit
MISMATCH = {"passive_spread_v76": 1.0, "passive_seed_v76": MISMATCH_SEED}
# (the chain's one tolerance block: R 5 %, film 10 %, electrolytics -20 / +50 %, tubes' emission
# 10 % and mu 3 %; provisional classes from the circuit files, u47_v76.yaml)

# --- hum ------------------------------------------------------------------------------------
MAINS_HZ = 50.0  # the chain's mains_hz_v76 (West German mains)
# The NG's ripple: full-wave, through its RC sections (each ~1/f), so the harmonics fall fast.
RIPPLE_HARMONICS = ((100.0, 1.0), (200.0, 0.25), (300.0, 0.1))  # provisional: model knowledge
RIPPLE_TARGET_V = 3.0e-6  # rms at the U47's output, 20 Hz-20 kHz
RIPPLE_SOURCE = (
    "provisional: inside the NG's 'Fremdspannung (hum and noise at the output) about 5 uV' (ds58, "
    "data/schematics/neumann_u47/README.md); the hum's share of it unknown, 3 uV chosen"
)
# T90's leakage field: the magnetizing current's odd harmonics.
STRAY_HARMONICS = ((50.0, 1.0), (150.0, 0.3), (250.0, 0.1))  # provisional: model knowledge
V76_SPEC_DB = -120.0  # bb: noise <= -120 dB unweighted re 0.775 V at the input, 76-52 dB gain
V76_MARGIN_DB = 1.0  # provisional: a unit 1 dB inside its acceptance limit
SOURCE_200_V2 = 4 * 1.380649e-23 * 290.0 * 200.0 * (20000.0 - 20.0)  # the spec's 200 ohm source
# Heaters (README: 6.3 V, V1 on its own winding with a 250 ohm hum pot).
HEATER_V_RMS = 6.3
HUM_POT_IMBALANCE = 0.02  # provisional: the pot 2 % off its null
C_HK_F = 5.0e-12  # provisional: model knowledge (heater-cathode capacitance of a small pentode)
R_HK_OHM = 100.0e6  # provisional: model knowledge (heater-cathode leakage, typical, not the limit)
# V2-V4's winding: the drawing shows no hum pot for it. With one end grounded, typical C_HK / R_HK
# alone put the V76 at -120.7 dB (spike-1's calibration), past its -120 dB acceptance limit, so a
# unit that passed had it balanced: a centre tap, taken as the same 2 % off.
CATHODES = ("k1_v76", "k2_v76", "k3_v76", "k4_v76")

# --- excess noise ----------------------------------------------------------------------------
# Carbon film (German 1950s parts: Kohleschicht), noise index rising with value.
EXCESS_SOURCE = (
    "provisional: model knowledge (carbon film noise index ~-20 dB at 1 kOhm rising ~5 dB per "
    "decade, as in Vishay's / Beyschlag's application notes on current noise; IEC 60195 method)"
)


def noise_index_db(r_ohm: float) -> float:
    return float(np.clip(-20.0 + 5.0 * math.log10(max(r_ohm, 1.0) / 1e3), -25.0, 0.0))


WIREWOUND = {"R4_u47"}  # the manual: the heater's dropper is wire-wound (no excess noise)

# --- capsule ---------------------------------------------------------------------------------
CAPSULE = "K47@3"
E0_V = 63.0  # neumann_u47.yaml polarization_v

# --- microphonics ----------------------------------------------------------------------------
MICRO_MODES = ((2200.0, 40.0), (5100.0, 60.0), (8700.0, 80.0))  # provisional: invented (Hz, Q)
MICRO_PEAK_DB = (
    -50.0
)  # provisional: invented; each mode's peak re the capsule's grid signal at 1 kHz


# ---------------------------------------------------------------------------------------------


def fade_in(n: int, fs: int) -> np.ndarray:
    m = min(n, int(FADE_IN_S * fs))
    w = np.ones(n)
    w[:m] = 0.5 - 0.5 * np.cos(np.pi * np.arange(m) / m)
    return w


def one_over_f(n: int, k_v2: float, fs: int, rng: np.random.Generator) -> np.ndarray:
    """Gaussian noise of one-sided density k_v2 / f (V^2/Hz), flat below 1 Hz."""
    m = 1 << int(np.ceil(np.log2(n)))
    x = rng.standard_normal(m)
    f = np.fft.rfftfreq(m, 1 / fs)
    g = np.sqrt(k_v2 * fs / (2.0 * np.maximum(f, 1.0)))
    g[0] = 0.0
    return np.fft.irfft(np.fft.rfft(x) * g, m)[:n]


def tones(n: int, fs: int, harmonics, amp: float, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n) / fs
    return amp * sum(a * np.sin(2 * np.pi * f * t + 2 * np.pi * rng.random()) for f, a in harmonics)


def lowpass_resonator(f0: float, q: float, fs: int) -> np.ndarray:
    """RBJ's low-pass biquad (unity at DC, ~q at f0) as one sos row."""
    w0 = 2 * np.pi * f0 / fs
    al = np.sin(w0) / (2 * q)
    c = np.cos(w0)
    b = np.array([(1 - c) / 2, 1 - c, (1 - c) / 2])
    a = np.array([1 + al, -2 * c, 1 - al])
    return np.concatenate([b / a[0], a / a[0]])[None, :]


def capsule_constants() -> dict:
    d = component_data(CAPSULE)
    c = cap.dual_capsule_from_data(d, CAPSULE)
    g = d["geometry"]
    beta = g["backplate"]["radius_m"] / g["diaphragm"]["radius_m"]
    return {
        "cd": c.c_diaphragm_at(E0_V),
        "dpv": c.displacement_per_volume,
        "h": c.gap_m,
        "beta": beta,
        # constant charge on w = w0 (1 - r^2 / a^2) over the backplate r < b: V = E0 (1 - <w>/h -
        # var(w)/h^2), var = w0^2 beta^4 / 12, <w> = w0 (1 - beta^2 / 2)
        "shape": beta**4 / (12.0 * (1.0 - beta**2 / 2.0) ** 2),
    }


class Spike:
    """The chain with a set of mechanisms, at an SPL and a V76 gain."""

    def __init__(self, mechs, spl_db: float, gain_db: int, cal: dict | None):
        self.mechs = frozenset(mechs)
        self.spl_db = spl_db
        self.over = {"gain_db_v76": gain_db} | (MISMATCH if "mismatch" in self.mechs else {})
        self.base = cp.Chain(CHAIN, False, self.over)  # noiseless, undisturbed: H and the DC point
        self.fs = self.base.fs
        self.s = self.base.s
        self.cal = cal or {}
        self._dc: dict | None = None
        self.cc = capsule_constants()
        self.micro_peak_db = MICRO_PEAK_DB  # scripts/chain_study.py bends it

    # -- the circuit's DC point (each resistor's voltage, for the excess noise) --------------
    def dc(self) -> dict:
        if self._dc is None:
            ir = self.base.ir
            ir = replace(ir, probes=tuple(VoltageProbe(n) for n in ir.nodes()))
            front, ctl = self.base.entries(np.zeros(int(0.3 * self.fs)))
            r = fast.run_transient(ir, front, settings=self.s, controls=ctl or None)
            self._dc = {n: float(np.asarray(v)[-1]) for n, v in
                        ((k[2:-1], v) for k, v in r.vectors.items())}  # fmt: skip
            self._dc["0"] = 0.0
        return self._dc

    # -- the linear capsule alone (its displacement, the grid's signal) -----------------------
    def capsule_run(self, p: np.ndarray) -> dict:
        ir = self.base.ir
        secs = tuple(
            s
            for s in ir.sections
            if s.title.startswith(("Neumann U47: supply", "Neumann U47: capsule"))
        )
        mini = replace(
            ir,
            sections=secs,
            probes=(
                VoltageProbe("kk47c_u47_f1"),
                VoltageProbe("kk47c_u47_fg"),
                VoltageProbe("g_u47"),
            ),
            models=(),
        )
        front, ctl = self.base.entries(p)
        r = fast.run_transient(mini, front, settings=self.s, controls=ctl or None)
        v = {k[2:-1]: np.asarray(x, float) for k, x in r.vectors.items()}
        xbar = self.cc["dpv"] * self.cc["cd"] * (v["kk47c_u47_f1"] - v["kk47c_u47_fg"])
        return {"x": xbar, "g": v["g_u47"]}

    # -- the circuit with the mechanisms -------------------------------------------------------
    def circuit(self, p: np.ndarray, seed: int | None, only: set | None = None):
        """(IR, controls) for free-field pressure `p`, noise seed `seed`; `only`: the hum paths
        or other parts to keep (calibration), None: all of this spike's."""
        mechs = (
            self.mechs
            if only is None
            else self.mechs & only | (only & {"stray", "ripple", "heaters"})
        )
        noise = seed if ("noise" in mechs and seed is not None) else False
        ir = builder.build(self.base.c, self.over, noise=noise).ir
        front, sig = self.base.entries(p)
        n, fs = len(front), self.fs
        fade = fade_in(n, fs)
        rng = np.random.default_rng([seed or 0, zlib.crc32(b"spike")])
        els = {e.name: e for e in ir.elements()}
        repl: dict[str, object] = {}
        extra: list = []
        controls: list[Control] = []

        def control(name: str, x: np.ndarray) -> str:
            controls.append(Control(name, name))
            extra.append(
                Resistor(f"RCTL_{name}", name, "0", 1e9)
            )  # numerical: the IR's two-element rule
            sig[name] = x
            return name

        def series_emf(el_name: str, field: str, name: str, x: np.ndarray) -> None:
            e = repl.get(el_name, els[el_name])
            old = getattr(e, field)
            new = f"{old}__{name}"
            repl[el_name] = replace(e, **{field: new})
            ctl = control(name, x)
            extra.extend(
                [
                    Resistor(f"REMF_{name}", new, old, 1.0),
                    Vccs(f"GEMF_{name}", old, new, ctl, "0", 1.0),
                ]
            )

        hum = "hum" in mechs
        if hum or "ripple" in mechs:
            r = tones(n, fs, RIPPLE_HARMONICS, self.cal.get("ripple_v", 0.0), rng) * fade
            series_emf("VNG_u47", "pos", "hum_ng", r)
        if hum or "stray" in mechs:
            s = tones(n, fs, STRAY_HARMONICS, self.cal.get("stray_v", 0.0), rng) * fade
            series_emf("LT85_V76_s", "b", "hum_t85", s)
        if hum or "heaters" in mechs:
            t = np.arange(n) / fs
            hm = (
                HEATER_V_RMS
                * math.sqrt(2)
                * np.sin(2 * np.pi * MAINS_HZ * t + 2 * np.pi * rng.random())
                * fade
            )
            a = control("htr_a", +(1 + HUM_POT_IMBALANCE) * hm / 2)
            b = control("htr_b", -(1 - HUM_POT_IMBALANCE) * hm / 2)
            for k in CATHODES:  # half the heater's coupling to each end
                for h in (a, b):
                    extra += [
                        Capacitor(f"CHK_{h}_{k}", h, k, C_HK_F / 2),
                        Resistor(f"RHK_{h}_{k}", h, k, 2 * R_HK_OHM),
                    ]
        if "excess" in mechs:
            dc = self.dc()
            only_v76 = only is not None and "v76_only" in only
            for e in ir.elements():
                if not (isinstance(e, Resistor) and _numbered(e.name)) or e.name in WIREWOUND:
                    continue
                if only_v76 and not e.name.endswith("_v76"):
                    continue
                v = dc.get(e.a, 0.0) - dc.get(e.b, 0.0)
                if abs(v) < 0.05:
                    continue
                k = (10 ** (noise_index_db(e.r_ohm) / 20) * 1e-6) ** 2 / math.log(10) * v * v
                g = np.random.default_rng([seed or 0, zlib.crc32(e.name.encode())])
                x = one_over_f(n, k, fs, g) * fade
                extra.append(
                    Vccs(
                        f"GXS_{e.name}",
                        e.a,
                        e.b,
                        control(f"xs_{e.name.lower()}", x),
                        "0",
                        1.0 / e.r_ohm,
                    )
                )
        if "capsule" in mechs or "microphonics" in mechs:
            cr = self.capsule_run(p)
            if "capsule" in mechs:
                cc = self.cc
                d = cc["shape"] * E0_V * (cr["x"] / cc["h"]) ** 2
                xf = els["GKK47C_U47_xf"]
                extra.append(
                    Vccs(
                        "GCAPNL",
                        xf.pos,
                        xf.neg,
                        control("cap_nl", d * fade),
                        "0",
                        1.0 / cap.READOUT_OHM,
                    )
                )
            if "microphonics" in mechs:
                from scipy.signal import sosfilt

                sg = self.cal["grid_v_per_pa_1k"]
                a0 = 10 ** (self.micro_peak_db / 20) * sg
                v = sum(a0 / q * sosfilt(lowpass_resonator(f0, q, fs), p) for f0, q in MICRO_MODES)
                series_emf("VSC_u47", "neg", "micro", v * fade)

        strip = only is not None and "v76_only" in only  # the U47's own noise out (calibration)
        secs = []
        for sec in ir.sections:
            es = tuple(
                repl.get(e.name, e)
                for e in sec.elements
                if not (
                    strip and isinstance(e, NoiseCurrent | TubeNoise) and "U47" in e.name.upper()
                )
            )
            secs.append(replace(sec, elements=es))
        if extra:
            secs.append(Section("spike", tuple(extra)))
        ir = replace(ir, sections=tuple(secs), controls=tuple(ir.controls) + tuple(controls))
        return ir, front, sig

    def run(
        self, p: np.ndarray, seed: int | None, only: set | None = None, probes=("out",)
    ) -> dict:
        ir, front, sig = self.circuit(p, seed, only)
        ir = replace(ir, probes=tuple(VoltageProbe(x) for x in probes))
        r = fast.run_transient(ir, front, settings=self.s, controls=sig or None)
        return {k[2:-1]: np.asarray(v, float) for k, v in r.vectors.items()}

    def out(self, p: np.ndarray, seed: int | None) -> np.ndarray:
        return self.run(p, seed)["out"] / self.base.out_fs


def _numbered(name: str) -> bool:
    """A schematic resistor (R<n>_u47 / R<n>_v76), not a lumped or numerical one."""
    head, _, tail = name.partition("_")
    return head[:1] == "R" and head[1:].isdigit() and tail in ("u47", "v76")


# --- calibration -----------------------------------------------------------------------------


def band_rms(v: np.ndarray, fs: int, skip_s: float = 0.3) -> float:
    y = cp.band(v - np.mean(v), fs)[int(skip_s * fs) : -int(0.1 * fs)]
    return float(np.sqrt(np.mean(y**2)))


def calibrate() -> dict:
    f = CACHE / f"calibration_{VERSION}.json"
    if f.exists():
        return json.loads(f.read_text())
    t0 = time.perf_counter()
    nom = Spike(set(MECHS) - {"mismatch"}, 100.0, 52, {"ripple_v": 1e-3, "stray_v": 1e-3})
    fs = nom.fs
    sil = np.zeros(int(2.0 * fs))
    # the V76's gain from its input terminals (ia_v76) at 52 dB, a 1 kHz tone at 0.05 Pa rms
    t = np.arange(int(0.6 * fs)) / fs
    tone = 0.05 * math.sqrt(2) * np.sin(2 * np.pi * 1000 * t)
    r = nom.run(tone, None, only=set(), probes=("out", "ia_v76"))
    g52 = band_rms(r["out"], fs) / band_rms(r["ia_v76"], fs)
    # the capsule's grid signal at 1 kHz per Pa (peak per peak), the linear capsule
    sg = float(np.max(np.abs(nom.capsule_run(tone)["g"][int(0.3 * fs) :]))) / (0.05 * math.sqrt(2))
    # the V76 alone (the U47's noise stripped), noise + excess + heaters: its input-referred floor
    r = nom.run(sil, 1, only={"noise", "excess", "heaters", "v76_only"}, probes=("out",))
    ein_a = band_rms(r["out"], fs) / g52
    # T90's stray field, unit amplitude (1 mV at 50 Hz in T85's secondary), noiseless
    r = nom.run(sil, 2, only={"stray"}, probes=("out",))
    ein_h1 = band_rms(r["out"], fs) / g52
    target = 0.775 * 10 ** ((V76_SPEC_DB - V76_MARGIN_DB) / 20)
    p_h = target**2 - ein_a**2 - SOURCE_200_V2
    stray_v = 1e-3 * math.sqrt(max(p_h, 0.0)) / ein_h1
    # the NG's ripple, unit amplitude (1 mV at 100 Hz on the NG's output), at the U47's output
    r = nom.run(sil, 3, only={"ripple"}, probes=("ia_v76",))
    ripple_v = 1e-3 * RIPPLE_TARGET_V / band_rms(r["ia_v76"], fs)

    def db(v):
        return round(20 * math.log10(v / 0.775), 2)

    cal = {
        "version": VERSION,
        "v76_gain_52_measured_db": round(20 * math.log10(g52), 2),
        "grid_v_per_pa_1k": sg,
        "v76_ein_noise_excess_heaters_db": db(ein_a),
        "v76_ein_with_200_ohm_source_db": db(math.sqrt(ein_a**2 + SOURCE_200_V2)),
        "v76_target_db": V76_SPEC_DB - V76_MARGIN_DB,
        "stray_v": stray_v,
        "stray_ein_db": db(ein_h1 * stray_v / 1e-3) if stray_v > 0 else None,
        "ripple_v": ripple_v,
        "capsule": capsule_constants(),
        "seconds": round(time.perf_counter() - t0, 1),
    }
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cal, indent=1))
    return cal


# --- passes ----------------------------------------------------------------------------------


def run_passes(sp: Spike, variant: str, stem: str, x: np.ndarray, n: int) -> list[np.ndarray]:
    """cp.passes' staging with the spike's circuit (a seed per stem and pass)."""
    d = CACHE / variant / stem
    d.mkdir(parents=True, exist_ok=True)
    key = cp._key(CHAIN, stem, sp.spl_db, VERSION, sp.over, sorted(sp.mechs), sp.cal)
    f_ms, h_ms = cp.measure_h(sp.base, sp.spl_db, "production")

    def predicted_peak(p):
        return float(np.max(np.abs(cp.apply_power(p, f_ms, h_ms, 1, sp.fs))))

    out, cur, ref = [], x, None
    for i in range(1, n + 1):
        f = d / f"p{i}_{key}.npy"
        p = cp.to_spl(cur, sp.spl_db, sp.fs)
        if ref is not None:
            p = p * min(1.0, ref[0] / (predicted_peak(p) * ref[1]))
        if f.exists():
            y = np.load(f).astype(float)
        else:
            t0 = time.perf_counter()
            y = sp.out(p, cp.pass_seed(stem, i))
            np.save(f, y.astype(np.float32))
            rt = (time.perf_counter() - t0) / (len(y) / sp.fs)
            pk = 20 * np.log10(np.max(np.abs(y)) + 1e-12)
            print(
                f"  {variant:22s} {stem:10s} pass {i}: {rt:.1f}x real time, peak {pk:+.1f} dBFS",
                flush=True,
            )
        if ref is None:
            ref = (float(np.max(np.abs(y))), float(np.max(np.abs(y))) / predicted_peak(p))
        out.append(y)
        cur = y
    return out


def idle_spectra(cal: dict) -> dict:
    """3 s of silence through the chain at 24 dB: nominal noiseless, B5's noise, all."""
    f = CACHE / f"idle_{VERSION}.npz"
    if f.exists():
        z = np.load(f)
        return {k: z[k] for k in z.files}
    sil = np.zeros(int(3.0 * cp_fs()))
    res = {}
    for name, mechs in (("noise", {"noise"}), ("all", set(MECHS))):
        sp = Spike(mechs, 100.0, 24, cal)
        res[name] = sp.out(sil, 11)
    np.savez(f, **res)
    return res


def cp_fs() -> int:
    return cp._settings(False).sample_rate


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--calibrate-only", action="store_true")
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS))
    ap.add_argument("--no-singles", action="store_true", help="skip each mechanism alone on pass 1")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()
    cal = calibrate()
    print(json.dumps(cal, indent=1), flush=True)
    if args.calibrate_only:
        return
    fs = cp_fs()
    stems = sorted(p.stem for p in cp.STEM_DIR.glob("*.wav"))
    dry = {s: cp.load_stem(s, fs) for s in stems}
    t0 = time.perf_counter()
    with ThreadPoolExecutor(args.workers) as ex:
        sps = {
            v: Spike(VARIANTS[v]["mechs"], VARIANTS[v]["spl_db"], VARIANTS[v]["gain_db"], cal)
            for v in args.variants
        }
        hs = {v: ex.submit(cp.measure_h, sp.base, sp.spl_db, "production") for v, sp in sps.items()}
        hs = {v: f.result() for v, f in hs.items()}
        for sp in sps.values():  # the DC point once per configuration, before the threads share it
            if "excess" in sp.mechs:
                sp.dc()
        jobs = {(v, s): ex.submit(run_passes, sp, v, s, dry[s], VARIANTS[v]["passes"])
                for v, sp in sps.items() for s in stems}  # fmt: skip
        base = cp.Chain(CHAIN, False)
        bjobs = {s: ex.submit(cp.passes, base, s, dry[s], 1, 100.0, "production") for s in stems}
        singles = {}
        if not args.no_singles:
            for m in MECHS:
                sp = Spike({m}, 100.0, 24, cal)
                if m == "excess":
                    sp.dc()
                for s in stems:
                    singles[(m, s)] = ex.submit(run_passes, sp, f"single_{m}", s, dry[s], 1)
        jobs = {k: f.result() for k, f in jobs.items()}
        bp1 = {s: f.result()[0] for s, f in bjobs.items()}
        singles = {k: f.result()[0] for k, f in singles.items()}
        idle = ex.submit(idle_spectra, cal).result()
    print(f"renders done in {(time.perf_counter() - t0) / 60:.1f} min", flush=True)
    report(cal, sps, hs, jobs, bp1, singles, idle, dry, stems, fs)


ADDED_RMS_DBFS = -30.0


def write_rms(path: Path, x: np.ndarray, fs: int) -> None:
    """A difference signal at ADDED_RMS_DBFS rms in the audible band (most sit below loudness
    metering's -70 LUFS gate, so cp.write's match can't level them); its true level is in the
    summary."""
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    y = cp.band(x - np.mean(x), fs)
    r = float(np.sqrt(np.mean(y**2)))
    y = y * (10 ** (ADDED_RMS_DBFS / 20) / r) if r > 0 else y
    pk = float(np.max(np.abs(y)))
    if pk > 0.99:
        y = y * 0.99 / pk
    sf.write(path, y.astype(np.float32), fs, subtype="FLOAT")


def level_db(d: np.ndarray, ref: np.ndarray, fs: int) -> float:
    e = int(cp.EDGE_S * fs)
    a, b = cp.band(d, fs)[e:-e], cp.band(ref, fs)[e:-e]
    return round(float(10 * np.log10(np.mean(a**2) / np.mean(b**2))), 2)


def report(cal, sps, hs, jobs, bp1, singles, idle, dry, stems, fs) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cp.OUT = OUT  # cp.write's log paths
    summary: dict = {"calibration": cal, "variants": {}, "singles": {}}
    for s in stems:
        cp.write(OUT / s / "dry.wav", dry[s], fs)
        cp.write(OUT / s / "nominal_p1.wav", bp1[s], fs)
    for (m, s), y in singles.items():
        b = bp1[s]
        n = min(len(y), len(b))
        d = y[:n] - b[:n]
        write_rms(OUT / s / "alone" / f"{m}_added.wav", d, fs)  # its nature, not its level
        summary["singles"].setdefault(m, {})[s] = {"added_db_re_signal": level_db(d, b[:n], fs),
                                                  "vs_nominal": cp.char_db(b, y, fs)}  # fmt: skip
    for v, sp in sps.items():
        f_ms, h_ms = hs[v]
        rows = {}
        for s in stems:
            ys = jobs[(v, s)]
            d = OUT / v / s
            for k in cp.SHOWN:
                if k > len(ys):
                    continue
                yk = ys[k - 1]
                cp.write(d / f"p{k}.wav", yk, fs)
                row = cp.residuals(ys, dry[s], sp.spl_db, f_ms, h_ms, k, fs)
                row["vs_dry"] = cp.char_db(cp.to_spl(dry[s], 94.0, fs), yk, fs)
                if k > 1:
                    eq = cp.apply_power(yk, f_ms, h_ms, -(k - 1), fs)
                    tone = cp.apply_power(ys[0], f_ms, h_ms, k - 1, fs)
                    cp.write(d / f"p{k}_eqnull.wav", eq, fs)
                    cp.write(d / f"p{k}_tone.wav", tone, fs)
                    row["eqnull_vs_p1"] = cp.char_db(ys[0], eq, fs)
                rows.setdefault(s, {})[f"p{k}"] = row
        summary["variants"][v] = {
            "mechs": sorted(sp.mechs), "spl_db": sp.spl_db, "set": sp.over,
            "pass_peaks_dbfs": {s: [cp.peak_dbfs(y) for y in jobs[(v, s)]] for s in stems},
            "stems": rows,
        }  # fmt: skip
    # the idle floor at 24 dB (out re full scale, 20 Hz-20 kHz) and its spectrum
    summary["idle_dbfs"] = {
        k: round(20 * math.log10(band_rms(y, fs) + 1e-30), 1) for k, y in idle.items()
    }
    for k, y in idle.items():
        write_rms(OUT / f"idle_{k}.wav", y[int(0.3 * fs) :], fs)
    plot_idle(idle, fs, OUT / "idle_spectrum.png")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("singles", "idle_dbfs")}, indent=1))


def plot_idle(idle: dict, fs: int, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.signal import welch

    fig, ax = plt.subplots(figsize=(8, 3.5))
    for k, y in idle.items():
        f, pxx = welch(y[int(0.5 * fs) :], fs, nperseg=1 << 16)
        ax.semilogx(f, 10 * np.log10(pxx + 1e-30), label=k, lw=0.8)
    ax.set_xlim(10, 40000)
    ax.set_xlabel("Hz")
    ax.set_ylabel("dB re FS^2/Hz")
    ax.set_title("U47 -> V76 at 24 dB, idle")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()
