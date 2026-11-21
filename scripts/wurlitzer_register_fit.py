"""WZ3: the 200A's registers fitted to the Pie-finger set through the AUX output, and the
keyboard checked through the circuit (docs/WURLITZER_PLAN.md, WZ3).

    uv run --extra fast --extra listen python scripts/wurlitzer_register_fit.py
        [--measure] [--fit] [--check] [--quality production|draft-1x]

- `--measure`: the short notes' dampers. Per note, the key's release (the knee of a two-line
  fit to the fundamental's band envelope) and the damped decay after it; per octave the
  median; the keys whose notes ring on at every layer -> reports/wurlitzer/registers/
  damper.json (the config's `damper` block takes them by hand, with their source).
- `--fit`: at each of `registers.anchor_keys` (the recorded octaves' ends: a 200A is voiced
  reed by reed) the voicing and the slot's overlap along the reed (the level, leaving the
  bark; C4's held at the config's), the hammer's mass at each of
  `registers.hammer_anchor_keys` (the octaves' centres: a construction value; octave 4's held
  at 1 g, the recording's absolute level being unknown), and one hammer speed per layer;
  a reed that leaves the field map (where it is held flat: an artifact) costs `OFF_MAP_DB`
  per strike times the fraction of the time it is off. Decays aren't fitted: the reed's Q
  is the recording's, and the check compares the fundamental's decay over 0.2-1.15 s on both
  sides (a bass reed deep in the pickup's nonlinearity gets its fundamental back from the
  bark as it decays: it blooms, in the recording too). Least squares (soft L1 at 6 dB) on
  six keys per recorded octave (`FIT_KEYS`): harmonics 2-5 re the fundamental (where the
  recording holds them above -60 dB), each layer's
  fundamental re the middle layer's, and each key's middle layer re octave 4's; the reeds'
  input filtered by the circuit's measured small-signal transfer to the AUX jack
  (`circuit.transfer`: within 0.1 dB of the circuit on these harmonics) -> fit.json (the
  config takes the values by hand, with their source).
- `--check` (the default when neither of the others is named): the 36 recorded keys x 3
  layers played by MIDI velocity (the layers' velocities, the config's velocity law) through
  the keyboard (`keyboard.render`) and the full circuit; the same measures on model and
  recording; the damper on each key's mid-velocity short note (the reeds' input: the AUX path
  is linear); A/B files of three keys per octave (the recording, then the model, each loudness
  matched to -23 LUFS) -> summary.json, README.md, audio/.

The recording's measures (`note_stats`) are the same function on both sides: the
fundamental's level and harmonics 2-5 from 0.15 to 0.65 s after the onset.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

import numpy as np
import soundfile as sf
from scipy import optimize, signal

from varimu.config import REPO_ROOT
from varimu.listen.matching import integrated_lufs
from varimu.rhodes.midi import Event
from varimu.wurlitzer import circuit, keyboard
from varimu.wurlitzer import key as ky
from varimu.wurlitzer import spec as sp

SAMPLES = (
    REPO_ROOT
    / "real instrument samples"
    / "Pie-finger Wurlitzer 200A sample set"
    / "Pie-finger Wurlitzer 200A sample set"
)
OUT = REPO_ROOT / "reports" / "wurlitzer" / "registers"
LAYERS = ("low", "mid", "high")
NOTE = {n: i for i, n in enumerate("C C# D D# E F F# G G# A A# B".split())}
OCTAVES = {2: (4, 15), 4: (28, 39), 6: (52, 63)}
# six keys per octave: its ends (the anchors) and four between
FIT_KEYS = tuple(a + d for a, _ in OCTAVES.values() for d in (0, 2, 4, 7, 9, 11))
AB_KEYS = (4, 10, 15, 28, 34, 39, 52, 58, 63)  # C2 F#2 B2, C4 F#4 B4, C6 F#6 B6
FLOOR_DB = -60.0
MID_MASS_KG = 1.0e-3
OFF_MAP_DB = 100.0  # the penalty per strike for the fraction of time a slice is off the map
WORKERS = 6  # 14 ran Windows out of commit memory (WZ1)

# the fit's strikes: 0.7 s at 48 kHz, the map at 2x (harmonics to 5 x 2 kHz are measured),
# the contact at 8x
FIT_FS = 48000.0
FIT_OVERSAMPLE = 2
FIT_STEP_OVERSAMPLE = 8
FIT_DUR_S = 0.7
DECAY_END_S = 1.15  # the check's decays: the fundamental's over 0.2 s to this, both sides

# the check's notes
CHECK_HOLD_S = 1.2
CHECK_SPACING_S = 1.7


def octave_of(n: int) -> int:
    return next(o for o, (a, b) in OCTAVES.items() if a <= n <= b)


def note_name(n: int) -> str:
    """Key n's note as the set's file names spell it (key 4 = C2)."""
    midi = n + keyboard.MIDI_KEY_OFFSET
    return f"{list(NOTE)[midi % 12]}{midi // 12 - 1}"


# --- measures (the recording and the model alike) ---------------------------------------


def note_stats(y: np.ndarray, fs: float, f0: float, a_s: float = 0.15, b_s: float = 0.65) -> dict:
    """The fundamental's frequency and level (dB, a sine's peak) and harmonics 2-5 (dB re
    the fundamental) over a_s..b_s after the onset."""
    a, b = int(a_s * fs), int(b_s * fs)
    win = np.hanning(b - a)
    nfft = 1 << 21
    s = np.abs(np.fft.rfft(y[a:b] * win, nfft)) * 2 / win.sum()
    fr = np.fft.rfftfreq(nfft, 1 / fs)

    def peak(f: float, w: float) -> tuple[float, float]:
        lo, hi = np.searchsorted(fr, [f * (1 - w), f * (1 + w)])
        k = lo + int(np.argmax(s[lo:hi]))
        y0, y1, y2 = np.log(s[k - 1 : k + 2] + 1e-30)
        d = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
        return fr[k] + d * (fr[1] - fr[0]), float(np.exp(y1 - 0.25 * (y0 - y2) * d))

    f1, a1 = peak(f0, 0.05)
    hs = [20 * np.log10(peak(h * f1, 0.01)[1] / a1) for h in range(2, 6)]
    return {"f0_hz": float(f1), "a1_db": float(20 * np.log10(a1)), "harmonics_db": hs}


def band_envelope_db(y: np.ndarray, fs: float, f0: float, blk_s: float) -> np.ndarray:
    sos = signal.butter(4, [f0 * 0.8, f0 * 1.2], "bandpass", fs=fs, output="sos")
    z = signal.sosfiltfilt(sos, y)
    b = int(blk_s * fs)
    m = z.size // b
    return 20 * np.log10(np.sqrt(np.mean(z[: m * b].reshape(m, b) ** 2, axis=1)) + 1e-30)


def decay_db_s(y: np.ndarray, fs: float, f0: float, t_end_s: float | None = None) -> float | None:
    """The fundamental's decay from 0.2 s over up to 40 dB: to the recording's tail (6 dB
    over its last 0.2 s), or to t_end_s if given (a held note cut before its tail)."""
    env = band_envelope_db(y, fs, f0, 0.05)
    t = (np.arange(env.size) + 0.5) * 0.05
    sel = (t > 0.2) & (env > env.max() - 40)
    if t_end_s is not None:
        sel &= t < t_end_s
    else:
        sel &= env > env[-4:].mean() + 6
    if sel.sum() < 5:
        return None
    return float(np.polyfit(t[sel], env[sel], 1)[0])


def damped_decay(y: np.ndarray, fs: float, f0: float) -> dict:
    """A short note: the release (the knee of two lines through the fundamental's band
    envelope, from 30 ms to 45 dB under its peak) and the slopes before and after it."""
    blk = 0.005
    env = band_envelope_db(y, fs, f0, blk)
    t = (np.arange(env.size) + 0.5) * blk
    i0 = int(np.searchsorted(t, 0.03))
    e0 = env[i0:].max()
    below = np.flatnonzero(env[i0:] < e0 - 45)
    i1 = i0 + (int(below[0]) if below.size else env.size - i0)
    best = None
    for j in range(i0 + 4, i1 - 4):
        a1 = np.polyfit(t[i0:j], env[i0:j], 1)
        a2 = np.polyfit(t[j:i1], env[j:i1], 1)
        err = float(
            np.sum((np.polyval(a1, t[i0:j]) - env[i0:j]) ** 2)
            + np.sum((np.polyval(a2, t[j:i1]) - env[j:i1]) ** 2)
        )
        if best is None or err < best[0]:
            best = (err, float(t[j]), float(a1[0]), float(a2[0]))
    if best is None:
        return {"knee_s": None, "before_db_s": None, "damped_db_s": None}
    return {"knee_s": best[1], "before_db_s": best[2], "damped_db_s": best[3]}


def _load(p) -> tuple[int, np.ndarray, float]:
    m = re.search(r"-([A-G]#?)(\d)\.wav$", p.name)
    n = 12 * (int(m.group(2)) + 1) + NOTE[m.group(1)] - keyboard.MIDI_KEY_OFFSET
    y, fs = sf.read(p)
    on = int(np.argmax(np.abs(y) > 0.1 * np.max(np.abs(y))))
    return n, y[on:], float(fs)


def reference() -> dict:
    """The long notes: per (key, layer) the note's stats and the fundamental's decay."""
    out = {}
    for layer in LAYERS:
        for p in sorted((SAMPLES / "Long notes" / f"{layer.capitalize()} vel").glob("*.wav")):
            n, y, fs = _load(p)
            st = note_stats(y, fs, sp.note_hz(n) * 2 ** (5 / 1200))
            st["decay_db_s"] = decay_db_s(y, fs, st["f0_hz"])
            st["decay_hold_db_s"] = decay_db_s(y, fs, st["f0_hz"], t_end_s=DECAY_END_S)
            out[f"{n}:{layer}"] = {"key": n, "layer": layer} | st
    return out


def reference_short() -> dict:
    out = {}
    for layer in LAYERS:
        for p in sorted((SAMPLES / "Short notes" / f"{layer.capitalize()} vel").glob("*.wav")):
            n, y, fs = _load(p)
            d = damped_decay(y, fs, sp.note_hz(n) * 2 ** (5 / 1200))
            out[f"{n}:{layer}"] = {"key": n, "layer": layer, "length_s": y.size / fs} | d
    return out


def measure() -> dict:
    """The dampers per octave and the keys that ring on."""
    short = reference_short()
    rings_on = sorted(
        n
        for n in {v["key"] for v in short.values()}
        if all(
            short[f"{n}:{lay}"]["length_s"] > 0.7
            and (short[f"{n}:{lay}"]["damped_db_s"] or 0) > -400
            for lay in LAYERS
            if f"{n}:{lay}" in short  # the set misses a few (key 56 low)
        )
    )
    per_octave = {}
    for o, (a, b) in OCTAVES.items():
        d = [
            v["damped_db_s"]
            for v in short.values()
            if a <= v["key"] <= b and v["key"] not in rings_on and v["damped_db_s"] is not None
        ]
        k = [
            v["knee_s"]
            for v in short.values()
            if a <= v["key"] <= b and v["key"] not in rings_on and v["knee_s"] is not None
        ]
        per_octave[o] = {
            "damped_db_s_median": float(np.median(d)),
            "damped_db_s_quartiles": [float(np.percentile(d, 25)), float(np.percentile(d, 75))],
            "knee_s_median": float(np.median(k)),
            "notes": len(d),
        }
    res = {"per_octave": per_octave, "rings_on": rings_on, "notes": short}
    for o, v in per_octave.items():
        print(
            f"  octave {o}: damped {v['damped_db_s_median']:.0f} dB/s (quartiles "
            f"{v['damped_db_s_quartiles'][0]:.0f} / {v['damped_db_s_quartiles'][1]:.0f}), "
            f"release {v['knee_s_median'] * 1e3:.0f} ms after the onset, {v['notes']} notes"
        )
    print(f"  ring on (undamped): keys {rings_on}")
    return res


# --- the fit -------------------------------------------------------------------------------


def _key(n: int, mass_kg: float | None = None) -> sp.Key:
    k = sp.key(n)
    if mass_kg is not None:
        k = replace(k, hammer=replace(k.hammer, mass_kg=mass_kg))
    return k


def _motion_job(job: tuple[int, float, float]) -> tuple[np.ndarray, float, float]:
    """A strike from rest: the modal displacements (float32), the contact, the tip's swing."""
    n, mass, speed = job
    mo = ky.motion(
        _key(n, mass), speed, FIT_DUR_S, FIT_FS, FIT_OVERSAMPLE, FIT_STEP_OVERSAMPLE, modal=True
    )
    return mo.slices_m.astype(np.float32), mo.contact_s, float(np.max(np.abs(mo.tip_m)))


class Model:
    """Fit-key strikes into the AUX jack through the measured transfer. Motions are cached by
    (key, hammer mass, speed) as modal displacements: a voicing or a slot alone needs no new
    strike."""

    def __init__(self, pool: ProcessPoolExecutor):
        self.pool = pool
        self.motions: dict = {}
        self.tr = circuit.transfer()
        self.c_reeds = circuit.c_reeds_f()
        self.systems = {n: ky.System(sp.key(n)) for n in FIT_KEYS}

    def ensure(self, jobs: list[tuple[int, float, float]]) -> None:
        todo = sorted({j for j in jobs if j not in self.motions})
        for j, r in zip(todo, self.pool.map(_motion_job, todo), strict=True):
            self.motions[j] = r

    def aux(
        self, job: tuple[int, float, float], voicing_m: float, overlap_m: float
    ) -> tuple[np.ndarray, float]:
        """The AUX jack's volts and the fraction of the time any slice is off the map."""
        n = job[0]
        k, sysm = sp.key(n), self.systems[n]
        _, w, rows = sysm.slot_rows(*sp.slot_m(k.reed, overlap_m, sp.load()))
        zz = voicing_m + rows @ self.motions[job][0].astype(float)
        fmap = sp.field(k)
        lo, hi = fmap.z_range_m
        off = float(np.mean(np.any((zz < lo) | (zz > hi), axis=0)))
        c = w @ fmap(zz)
        x = -circuit.plate_v0() * (c - c[0]) / self.c_reeds  # circuit.plate_input_v
        x = signal.resample_poly(x, 1, FIT_OVERSAMPLE)
        pad = np.concatenate([x, np.zeros(int(0.3 * FIT_FS))])
        return self.tr.apply(pad, FIT_FS)[: x.size], off


def _anchors() -> tuple[int, int, int, int]:
    """(the voicing's anchors, the hammer's, the reference among the voicing's (its slot
    held at the config's) and among the hammer's (held at 1 g): each the anchor nearest
    octave 4's centre)."""
    reg = sp.load()["registers"]
    va = np.array(reg["anchor_keys"], dtype=float)
    hm = np.array(reg.get("hammer_anchor_keys", reg["anchor_keys"]), dtype=float)
    c4 = 0.5 * sum(OCTAVES[4])
    return va.size, hm.size, int(np.argmin(np.abs(va - c4))), int(np.argmin(np.abs(hm - c4)))


def unpack(p: np.ndarray) -> tuple[list[float], list[float], list[float], list[float]]:
    """p: each voicing anchor's voicing (mm), each voicing anchor's slot overlap but the
    reference's (log of the ratio to it), each hammer anchor's mass but the reference's (log
    of the ratio to 1 g), the three layers' speeds (log m/s)."""
    nv, nm, rv, rm = _anchors()
    ov_ref = sp.load()["pickup"]["overlap_m"]
    ov_ref = ov_ref[rv] if isinstance(ov_ref, list) else ov_ref
    voic = [float(v) * 1e-3 for v in p[:nv]]
    logo = list(p[nv : 2 * nv - 1])
    logo.insert(rv, 0.0)
    overlap = [ov_ref * float(np.exp(v)) for v in logo]
    i = 2 * nv - 1
    logm = list(p[i : i + nm - 1])
    logm.insert(rm, 0.0)
    mass = [MID_MASS_KG * float(np.exp(v)) for v in logm]
    speeds = [float(v) for v in np.exp(p[i + nm - 1 : i + nm + 2])]
    return voic, overlap, mass, speeds


def fit_residuals(model: Model, ref: dict, p: np.ndarray, detail: bool = False):
    cfg = sp.load()
    voic, overlap, mass, speeds = unpack(p)
    cfg_m = {**cfg, "hammer": {**cfg["hammer"], "mass_kg": mass}}
    jobs = {}
    for n in FIT_KEYS:
        m = round(sp.hammer_mass_kg(n, cfg_m), 12)
        for layer, spd in zip(LAYERS, speeds, strict=True):
            jobs[(n, layer)] = (n, m, round(spd, 9))
    model.ensure(list(jobs.values()))
    st = {}
    for (n, layer), job in jobs.items():
        y, off = model.aux(job, sp.by_register(n, voic, cfg), sp.by_register(n, overlap, cfg))
        st[(n, layer)] = note_stats(y, FIT_FS, sp.note_hz(n)) | {
            "swing_m": model.motions[job][2],
            "off_map": off,
        }
    harm, lay, reg, offm = [], [], [], []
    oct4 = np.mean([st[(n, "mid")]["a1_db"] for n in FIT_KEYS if octave_of(n) == 4])
    oct4_r = np.mean([ref[f"{n}:mid"]["a1_db"] for n in FIT_KEYS if octave_of(n) == 4])
    for n in FIT_KEYS:
        for layer in LAYERS:
            r, m = ref[f"{n}:{layer}"], st[(n, layer)]
            harm += [
                a - b
                for a, b in zip(m["harmonics_db"], r["harmonics_db"], strict=True)
                if b > FLOOR_DB
            ]
            if layer != "mid":
                lay.append(
                    (m["a1_db"] - st[(n, "mid")]["a1_db"]) - (r["a1_db"] - ref[f"{n}:mid"]["a1_db"])
                )
            offm.append(OFF_MAP_DB * m["off_map"])
        reg.append((st[(n, "mid")]["a1_db"] - oct4) - (ref[f"{n}:mid"]["a1_db"] - oct4_r))
    e = np.array(harm + lay + reg + offm)
    if detail:
        return (
            e,
            st,
            {
                "harmonics": harm,
                "layers": lay,
                "registers": reg,
                "off_map": offm,
            },
        )
    return e


def fit(ref: dict) -> dict:
    sp.plate_f()  # every blank's field map solved here first, not once per worker
    cfg = sp.load()
    nv, nm, rv, rm = _anchors()
    ov = cfg["pickup"]["overlap_m"]
    ov = ov if isinstance(ov, list) else [ov] * nv
    logo = [float(np.log(o / ov[rv])) for i, o in enumerate(ov) if i != rv]
    m_ref = cfg["hammer"]["mass_kg"][rm]
    logm = [float(np.log(m / m_ref)) for i, m in enumerate(cfg["hammer"]["mass_kg"]) if i != rm]
    p0 = np.array(
        [v * 1e3 for v in cfg["pickup"]["voicing_m"]]
        + logo
        + logm
        + [float(np.log(v)) for v in cfg["velocity"]["layer_speeds_m_s"]]
    )
    lo = [0.05] * nv + [np.log(0.15)] * (nv - 1) + [np.log(0.25)] * (nm - 1) + [np.log(0.3)] * 3
    hi = [3.5] * nv + [np.log(4.0)] * (nv - 1) + [np.log(4.0)] * (nm - 1) + [np.log(8.0)] * 3
    p0 = np.clip(p0, np.array(lo) + 1e-6, np.array(hi) - 1e-6)
    with ProcessPoolExecutor(WORKERS) as pool:
        model = Model(pool)
        t0 = time.perf_counter()

        def resid(p: np.ndarray) -> np.ndarray:
            e = fit_residuals(model, ref, p)
            voic, overlap, mass, speeds = unpack(p)
            print(
                f"  [{time.perf_counter() - t0:6.0f} s] voicing "
                f"{' / '.join(f'{v * 1e3:.2f}' for v in voic)} mm, overlap "
                f"{' / '.join(f'{v * 1e3:.1f}' for v in overlap)} mm, hammer "
                f"{' / '.join(f'{v * 1e3:.2f}' for v in mass)} g, speeds "
                f"{' / '.join(f'{v:.2f}' for v in speeds)} m/s "
                f"-> rms {np.sqrt(np.mean(e**2)):.2f} dB",
                flush=True,
            )
            return e

        res = optimize.least_squares(
            resid,
            p0,
            bounds=(lo, hi),
            diff_step=0.03,
            loss="soft_l1",
            f_scale=6.0,
            max_nfev=30,
            ftol=2e-3,
        )
        e, st, parts = fit_residuals(model, ref, res.x, detail=True)
    voic, overlap, mass, speeds = unpack(res.x)

    def rms(v):
        return float(np.sqrt(np.mean(np.square(v)))) if len(v) else None

    return {
        "voicing_m": voic,
        "overlap_m": overlap,
        "hammer_mass_kg": mass,
        "layer_speeds_m_s": speeds,
        "anchor_keys": cfg["registers"]["anchor_keys"],
        "hammer_anchor_keys": cfg["registers"].get(
            "hammer_anchor_keys", cfg["registers"]["anchor_keys"]
        ),
        "rms_db": rms(e),
        "rms_harmonics_db": rms(parts["harmonics"]),
        "rms_layer_levels_db": rms(parts["layers"]),
        "rms_register_levels_db": rms(parts["registers"]),
        "off_map_max": float(max(s["off_map"] for s in st.values())),
        "keys": list(FIT_KEYS),
        "floor_db": FLOOR_DB,
        "evaluations": int(res.nfev),
        "strikes": {
            f"{n}:{layer}": {kk: v for kk, v in s.items() if kk != "f0_hz"}
            for (n, layer), s in st.items()
        },
    }


# --- the check -----------------------------------------------------------------------------


def check(quality: str, reuse_audio: bool = False) -> dict:
    """`reuse_audio`: measure the last check's audio/check_aux.wav again (the same events:
    valid while the config hasn't changed) instead of rendering it."""
    cfg = sp.load()
    ref = reference()
    keys = sorted({v["key"] for v in ref.values()})
    vels = cfg["velocity"]["layer_velocities"]
    events, slots = [], []
    t = 0.3
    for layer, vel in zip(LAYERS, vels, strict=True):
        for n in keys:
            note = n + keyboard.MIDI_KEY_OFFSET
            events += [Event(t, "on", note, int(vel)), Event(t + CHECK_HOLD_S, "off", note, 0)]
            slots.append((n, layer, t))
            t += CHECK_SPACING_S
    duration = t + 1.0
    fs = float(circuit.TRANSFER_FS)
    if reuse_audio:
        prev = json.loads((OUT / "summary.json").read_text())
        t_kb, t_c, quality = prev["keyboard_s"], prev["circuit_s"], prev["quality"]
        aux, afs = sf.read(OUT / "audio" / "check_aux.wav")
        if afs != fs or aux.size < int(duration * fs):
            raise ValueError("audio/check_aux.wav isn't this check's: run --check without it")
        v = {"out": aux}
    else:
        t0 = time.perf_counter()
        kb = keyboard.render(events, duration, fs_hz=fs)
        t_kb = time.perf_counter() - t0
        x = circuit.plate_input_v(kb.dc_f)
        print(
            f"  keyboard: {len(slots)} notes, {duration:.0f} s in {t_kb:.0f} s; circuit ...",
            flush=True,
        )
        t0 = time.perf_counter()
        v = circuit.render(x, quality=quality)
        t_c = time.perf_counter() - t0
        print(f"  circuit ({quality}): {t_c:.0f} s ({t_c / duration:.1f}x real time)", flush=True)
        (OUT / "audio").mkdir(parents=True, exist_ok=True)
        sf.write(
            OUT / "audio" / "check_aux.wav", v["out"].astype(np.float32), int(fs), subtype="FLOAT"
        )

    notes = {}
    for n, layer, ts in slots:
        a = int(round(ts * fs))
        seg = v["out"][a : a + int(CHECK_HOLD_S * fs)]
        st = note_stats(seg, fs, sp.note_hz(n))
        st["decay_db_s"] = decay_db_s(seg, fs, st["f0_hz"], t_end_s=CHECK_HOLD_S - 0.05)
        st["speed_m_s"] = sp.hammer_speed(vels[LAYERS.index(layer)])
        notes[f"{n}:{layer}"] = {"key": n, "layer": layer} | st

    # the damper: each key's mid-velocity short note, released at the recording's knee
    short = reference_short()
    dampers = {}
    for n in keys:
        r = short.get(f"{n}:mid")
        knee = r["knee_s"] if r and r["knee_s"] else 0.15
        note = n + keyboard.MIDI_KEY_OFFSET
        kbs = keyboard.render(
            [Event(0.0, "on", note, int(vels[1])), Event(knee, "off", note, 0)],
            knee + 0.6,
            fs_hz=fs,
        )
        d = damped_decay(kbs.dc_f, fs, sp.note_hz(n))
        dampers[n] = {"model": d, "real": r, "config_db_s": sp.key(n).damper_decay_db_s}

    write_ab(v["out"], fs, slots)
    summary = summarize(ref, notes, dampers)
    return {
        "quality": quality,
        "keyboard_s": t_kb,
        "circuit_s": t_c,
        "duration_s": duration,
        "notes": notes,
        "reference": ref,
        "dampers": {str(k): d for k, d in dampers.items()},
        "summary": summary,
    }


def write_ab(aux: np.ndarray, fs: float, slots: list) -> None:
    """Per octave: three keys' mid notes (AB_KEYS), the recording then the model (1.6 s each,
    faded, each at -23 LUFS), 0.4 s apart."""
    fade = int(0.02 * 48000)
    for o, (a, b) in OCTAVES.items():
        parts = []
        for n in AB_KEYS:
            if not a <= n <= b:
                continue
            p = next((SAMPLES / "Long notes" / "Mid vel").glob(f"*-{note_name(n)}.wav"))
            _, real, _ = _load(p)
            ts = next(t for k, lay, t in slots if k == n and lay == "mid")
            i = int(round(ts * fs)) - int(0.002 * fs)
            mod = signal.resample_poly(aux[i : i + int(1.7 * fs)], 1, int(fs // 48000))
            for y in (real[: int(1.6 * 48000)], mod[: int(1.6 * 48000)]):
                y = y.copy()
                y[-fade:] *= np.linspace(1, 0, fade)
                g = 10 ** ((-23.0 - integrated_lufs(y, 48000)) / 20)
                parts += [g * y, np.zeros(int(0.4 * 48000))]
        sf.write(
            OUT / "audio" / f"ab_octave{o}.wav",
            np.concatenate(parts).astype(np.float32),
            48000,
            subtype="FLOAT",
        )


def summarize(ref: dict, notes: dict, dampers: dict) -> dict:
    out = {}
    oct4 = {lay: np.mean([notes[f"{n}:{lay}"]["a1_db"] for n in range(28, 40)]) for lay in LAYERS}
    oct4_r = {lay: np.mean([ref[f"{n}:{lay}"]["a1_db"] for n in range(28, 40)]) for lay in LAYERS}
    for o, (a, b) in OCTAVES.items():
        h, lv, reg, dec = [], [], [], []
        for n in range(a, b + 1):
            for lay in LAYERS:
                m, r = notes[f"{n}:{lay}"], ref[f"{n}:{lay}"]
                h += [
                    x - y
                    for x, y in zip(m["harmonics_db"], r["harmonics_db"], strict=True)
                    if y > FLOOR_DB
                ]
                if lay != "mid":
                    lv.append(
                        (m["a1_db"] - notes[f"{n}:mid"]["a1_db"])
                        - (r["a1_db"] - ref[f"{n}:mid"]["a1_db"])
                    )
                reg.append((m["a1_db"] - oct4[lay]) - (r["a1_db"] - oct4_r[lay]))
                if m["decay_db_s"] is not None and r["decay_hold_db_s"] is not None:
                    dec.append(m["decay_db_s"] - r["decay_hold_db_s"])
        dm = [
            d["model"]["damped_db_s"] / d["real"]["damped_db_s"]
            for k, d in dampers.items()
            if a <= k <= b
            and d["real"]
            and d["real"]["damped_db_s"]
            and d["model"]["damped_db_s"]
            and d["config_db_s"] is not None
        ]

        def rms(v):
            return float(np.sqrt(np.mean(np.square(v)))) if v else None

        out[o] = {
            "harmonics_rms_db": rms(h),
            "harmonics_mean_db": float(np.mean(h)) if h else None,
            "layer_levels_rms_db": rms(lv),
            "register_level_mean_db": float(np.mean(reg)),
            "decay_rms_db_s": rms(dec),
            "damper_ratio_median": float(np.median(dm)) if dm else None,
        }
    return out


def write_readme(res: dict) -> None:
    s = res["summary"]
    lines = [
        "# WZ3: the 200A's keyboard through the circuit against the Pie-finger set",
        "",
        "Generated by `scripts/wurlitzer_register_fit.py --check` (docs/WURLITZER_PLAN.md,",
        "WZ3): the 36 recorded keys at the three layers' MIDI velocities, the Python keyboard",
        "(`varimu/wurlitzer/keyboard.py`) into `config/circuits/wurlitzer_200a.yaml` at",
        f"{res['quality']}, the AUX jack (`out`) measured as the recording (0.15-0.65 s: the",
        "fundamental's level, H2-H5 re it); the recording's absolute level is unknown, so levels",
        "are compared re octave 4 and re the middle layer. The damper on each key's mid short",
        "note, released at the recording's knee. Decays: the fundamental's over 0.2-1.15 s on both",
        "sides (the model's 1.2 s hold); the reed's Q is set from the",
        "recording per frequency (a smooth curve: single keys' outliers stay).",
        "`audio/ab_octave{2,4,6}.wav`: three keys' mid notes per octave, the recording then the",
        "model, each at -23 LUFS; `audio/check_aux.wav` the whole check (0 dBFS = 1 V at the",
        "jack).",
        "",
        f"Keyboard {res['keyboard_s']:.0f} s and circuit {res['circuit_s']:.0f} s for "
        f"{res['duration_s']:.0f} s of audio.",
        "",
        "| Octave | H2-H5 rms (mean) dB | layer levels rms dB | level re octave 4, model - real dB "
        "| decay rms dB/s | damper, model / real (median) |",
        "|---|---|---|---|---|---|",
    ]
    for o, v in s.items():
        dr = f"{v['damper_ratio_median']:.2f}" if v["damper_ratio_median"] is not None else "-"
        dec = f"{v['decay_rms_db_s']:.1f}" if v["decay_rms_db_s"] is not None else "-"
        lines.append(
            f"| {o} | {v['harmonics_rms_db']:.1f} ({v['harmonics_mean_db']:+.1f}) "
            f"| {v['layer_levels_rms_db']:.1f} | {v['register_level_mean_db']:+.1f} "
            f"| {dec} | {dr} |"
        )
    lines += [
        "",
        "| Key | layer | H2-H5 model | H2-H5 real | level re mid, model / real "
        "| decay dB/s model / real |",
        "|---|---|---|---|---|---|",
    ]
    ref, notes = res["reference"], res["notes"]
    for n in sorted({v["key"] for v in notes.values()}):
        for lay in LAYERS:
            m, r = notes[f"{n}:{lay}"], ref[f"{n}:{lay}"]
            lm = m["a1_db"] - notes[f"{n}:mid"]["a1_db"]
            lr = r["a1_db"] - ref[f"{n}:mid"]["a1_db"]
            dm = f"{m['decay_db_s']:.1f}" if m["decay_db_s"] is not None else "-"
            dr = f"{r['decay_hold_db_s']:.1f}" if r["decay_hold_db_s"] is not None else "-"
            lines.append(
                f"| {n} | {lay} | {' / '.join(f'{x:.0f}' for x in m['harmonics_db'])} "
                f"| {' / '.join(f'{x:.0f}' for x in r['harmonics_db'])} | {lm:+.1f} / {lr:+.1f} "
                f"| {dm} / {dr} |"
            )
    lines += [
        "",
        "| Key | damper: config dB/s | model dB/s | real (mid short note) dB/s |",
        "|---|---|---|---|",
    ]
    for k, d in sorted(res["dampers"].items(), key=lambda kv: int(kv[0])):
        cf = f"{d['config_db_s']:.0f}" if d["config_db_s"] is not None else "none"
        md = d["model"]["damped_db_s"]
        rd = d["real"]["damped_db_s"] if d["real"] else None
        lines.append(
            f"| {k} | {cf} | "
            + (f"{md:.0f}" if md is not None else "-")
            + " | "
            + (f"{rd:.0f}" if rd is not None else "-")
            + " |"
        )
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quality", default="production", choices=["production", "draft-1x"])
    ap.add_argument("--reuse-audio", action="store_true", help="re-measure the last check")
    args = ap.parse_args()
    if not (args.measure or args.fit or args.check):
        args.check = True
    OUT.mkdir(parents=True, exist_ok=True)
    if args.measure:
        print("measure (the dampers):", flush=True)
        (OUT / "damper.json").write_text(json.dumps(measure(), indent=1))
    if args.fit:
        print("fit (voicing, hammer mass per register; the layers' speeds):", flush=True)
        f = fit(reference())
        (OUT / "fit.json").write_text(json.dumps(f, indent=1))
        print(
            f"  rms {f['rms_db']:.2f} dB (harmonics {f['rms_harmonics_db']:.2f}, layers "
            f"{f['rms_layer_levels_db']:.2f}, registers {f['rms_register_levels_db']:.2f})"
        )
    if args.check:
        print("check (the keyboard through the circuit):", flush=True)
        res = check(args.quality, args.reuse_audio)
        (OUT / "summary.json").write_text(json.dumps(res, indent=1))
        write_readme(res)
        for o, v in res["summary"].items():
            print(f"  octave {o}: {v}")


if __name__ == "__main__":
    main()
