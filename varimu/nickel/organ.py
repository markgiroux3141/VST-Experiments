"""The Nickel Organ's keyboard: one Voice per key, the voicing procedure, and renders
(docs/NICKEL_ORGAN_PLAN.md).

**Voicing** (the factory's procedure for every key, `voicing`): with POLARIZE at its default
and the lamp cold, a key is struck softly (velocity 1: the small-signal onset; the strip's
coupling falls and its loss rises with the stress's swing, so a harder strike's onset is
higher) twice, its loop open (wiper gain 0) and
closed at a probe gain; the fundamental's decay rate (complex demodulation) is linear in the
loop's gain near its onset, so the gain where it crosses zero is the key's onset g*. Its
trim puts g* at SUSTAIN = `amp.voicing_threshold` (the audio taper there), capped at 1 (a
passive trim can only cut). Cached in cache/nickel/voicing.json by the config's and the
code's hash.

**A render** (`render`): events (varimu.rhodes.midi's: note on / off; knob changes as
("sustain" | "polarize", value)) on one timeline. A key's Voice is made the first time it
is struck: it powers on (POLARIZE ramped up from zero, 30 ms, then 20 ms to settle) out of
the timeline, and keeps its strip's magnetization from then on. A key runs from its strike
until it is released and quiet; between notes it is frozen (nothing in it moves). A
POLARIZE change reaches a frozen key when it next runs, ramped over 20 ms out of the
timeline: the strip is rate independent, so the ramp's path is what it remembers. The keys'
line outs are summed through each key's mixing resistor (`mix_gain`, voiced from the same
soft strike).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, sosfiltfilt

from varimu.config import REPO_ROOT
from varimu.nickel import spec as nspec
from varimu.nickel import voice as nvoice

CACHE = REPO_ROOT / "cache" / "nickel"
FS = int(nvoice.FS_HZ)
QUIET_V = 0.02  # a released key below this (rms over 20 ms) stops running (its own hiss: ~7.5 mV)
POWER_ON_S = (0.03, 0.02)  # POLARIZE's ramp at power-on, then settling
VOICING_VELOCITY = 1
VOICING_PROBE_GAIN = 0.01


def _code_hash() -> str:
    h = hashlib.sha256()
    for p in sorted((REPO_ROOT / "varimu" / "nickel").glob("*.py")):
        if p.name != "organ.py":
            h.update(p.read_bytes())
    h.update(nspec.ORGAN_FILE.read_bytes())
    return h.hexdigest()[:16]


def decay_rate(y: np.ndarray, f_hz: float, fs: float = FS) -> float:
    """The amplitude decay rate (1/s, negative decays) of y's component at f_hz, from its
    complex demodulation's log envelope over the run's 25-90%."""
    t = np.arange(len(y)) / fs
    z = y * np.exp(-2j * np.pi * f_hz * t)
    sos = butter(2, min(30.0, 0.4 * f_hz), fs=fs, output="sos")
    a = np.abs(sosfiltfilt(sos, z.real) + 1j * sosfiltfilt(sos, z.imag))
    i0, i1 = len(a) // 4, len(a) * 9 // 10
    return float(np.polyfit(t[i0:i1], np.log(a[i0:i1] + 1e-30), 1)[0])


def _power_on(vc: nvoice.Voice, polarize: float) -> None:
    vc.run(int(POWER_ON_S[0] * FS), sustain=0.0, polarize=polarize, ramp_s=POWER_ON_S[0])
    vc.run(int(POWER_ON_S[1] * FS), sustain=0.0, polarize=polarize)


def measure_onset(note: int, polarize: float | None = None, oversample: int = 2) -> dict:
    """The key's loop onset g* (see the module docstring) and the rates it came from."""
    d = nspec.load()
    pol = nspec.v(d, "panel.polarize") if polarize is None else polarize
    rates = []
    vc = None
    for g in (0.0, VOICING_PROBE_GAIN):
        vc = nvoice.make_voice(note, d, noise=False, oversample=oversample)
        vc.trim = g
        _power_on(vc, pol)
        vc.strike(VOICING_VELOCITY)
        f1 = float(vc.bar.freq_hz[0])
        # 0.2 s, or 30 periods
        n = int(max(0.2, 30 / f1) * FS)
        y = vc.run(n, sustain=1.0, polarize=pol)
        rates.append(decay_rate(y[int(0.01 * FS) :], f1))
        if g == 0.0:
            level = float(np.sqrt(np.mean(y[: int(0.05 * FS)] ** 2)))
    slope = (rates[1] - rates[0]) / VOICING_PROBE_GAIN
    g_star = -rates[0] / slope if slope > 0 else float("inf")
    return {"note": note, "f1_hz": f1, "rate_open": rates[0], "rate_probe": rates[1],
            "g_star": g_star, "level_v": level}  # fmt: skip


def voicing(notes, progress: bool = False) -> dict[int, dict]:
    """Each key's onset and trim, cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "voicing.json"
    key = _code_hash()
    data = json.loads(path.read_text()) if path.exists() else {}
    if data.get("key") != key:
        data = {"key": key, "keys": {}}
    d = nspec.load()
    thr = nvoice.taper_audio(nspec.v(d, "amp.voicing_threshold"))
    out = {}
    for n in notes:
        k = str(n)
        if k not in data["keys"]:
            m = measure_onset(n)
            m["trim"] = min(1.0, m["g_star"] / thr)
            m["onset_knob"] = None
            data["keys"][k] = m
            path.write_text(json.dumps(data, indent=1))
            if progress:
                print(f"  voiced {n}: f1 {m['f1_hz']:.1f} Hz, onset g* {m['g_star']:.3f}, "
                      f"trim {m['trim']:.3f}", flush=True)  # fmt: skip
        out[n] = data["keys"][k]
    return out


# the soft strike's line out on A4 (the voicing's velocity, loop open): the mix's reference
MIX_REFERENCE_V = 0.04


def mix_gain(voiced: dict) -> float:
    """A key's mixing resistor into the line bus: a soft strike's bell reads alike across
    the keyboard (the Villari EMF falls with frequency: the bass is ~13 dB down). A passive
    mix only cuts, so keys above the reference are cut and keys below it stay at 1."""
    return min(1.0, MIX_REFERENCE_V / max(voiced["level_v"], 1e-9))


@dataclass
class Render:
    audio: np.ndarray  # the summed line outs, volts, 96 kHz
    per_key_peak_stress_pa: dict[int, float] = field(default_factory=dict)
    lamp_peak_k: dict[int, float] = field(default_factory=dict)
    seconds_compute: float = 0.0


def render(
    events: list,
    duration_s: float,
    sustain: float | None = None,
    polarize: float | None = None,
    oversample: int = 2,
    seed: int = 1,
    noise: bool = True,
    progress: bool = False,
) -> Render:
    """The organ's line out for `events`: varimu.rhodes.midi Events ("on" / "off"; "pedal"
    ignored) and (t_s, "sustain" | "polarize", value) tuples for the panel."""
    import time

    t_start = time.perf_counter()
    d = nspec.load()
    sus = nspec.v(d, "panel.sustain") if sustain is None else sustain
    pol = nspec.v(d, "panel.polarize") if polarize is None else polarize
    lo, hi = nspec.v(d, "tuning.lowest_note"), nspec.v(d, "tuning.highest_note")
    evs = []
    for e in events:
        if isinstance(e, tuple):
            evs.append((float(e[0]), e[1], 0, float(e[2])))
        elif e.kind in ("on", "off") and lo <= e.note <= hi:
            evs.append((e.t_s, e.kind, e.note, float(e.value)))
    evs.sort(key=lambda x: (x[0], x[1] == "on"))
    notes = sorted({n for _, k, n, _ in evs if k == "on"})
    voiced = voicing(notes, progress=progress)
    trims = {n: v["trim"] for n, v in voiced.items()}
    mix = {n: mix_gain(v) for n, v in voiced.items()}
    n_total = int(round(duration_s * FS))
    out = np.zeros(n_total)
    voices: dict[int, nvoice.Voice] = {}
    pol_of: dict[int, float] = {}
    running: set[int] = set()
    released: set[int] = set()
    stress: dict[int, float] = {}
    lamp_peak: dict[int, float] = {}
    times = sorted({0} | {min(n_total, int(round(t * FS))) for t, *_ in evs} | {n_total})
    by_sample: dict[int, list] = {}
    for t, k, n, v in evs:
        by_sample.setdefault(min(n_total, int(round(t * FS))), []).append((k, n, v))
    for a, b in zip(times[:-1], times[1:], strict=True):
        for k, n, v in by_sample.get(a, []):
            if k == "sustain":
                sus = v
            elif k == "polarize":
                pol = v
            elif k == "on":
                vc = voices.get(n)
                if vc is None:
                    vc = nvoice.make_voice(n, d, oversample=oversample, seed=seed, noise=noise)
                    vc.trim = trims[n]
                    _power_on(vc, pol)
                    pol_of[n] = pol
                    voices[n] = vc
                if pol_of[n] != pol:
                    vc.run(int(0.02 * FS), sustain=sus, polarize=pol, ramp_s=0.02)
                    pol_of[n] = pol
                vc.strike(int(v))
                running.add(n)
                released.discard(n)
            elif k == "off" and n in voices:
                voices[n].release()
                released.add(n)
        if b <= a:
            continue
        for n in sorted(running):
            vc = voices[n]
            if pol_of[n] != pol:  # POLARIZE turned while it rang
                y = vc.run(b - a, sustain=sus, polarize=pol, ramp_s=0.02)
                pol_of[n] = pol
            else:
                y = vc.run(b - a, sustain=sus, polarize=pol)
            out[a:b] += mix[n] * y
            stress[n] = max(stress.get(n, 0.0), vc.peak_stress_pa)
            lamp_peak[n] = max(lamp_peak.get(n, 0.0), float(vc.probe["lamp_k"].max()))
            tail = y[-min(len(y), int(0.02 * FS)) :]
            if n in released and float(np.sqrt(np.mean(tail**2))) < QUIET_V:
                running.discard(n)
        if progress:
            print(f"  {b / FS:6.2f} s of {duration_s:.2f} ({len(running)} keys running)",
                  flush=True)  # fmt: skip
    return Render(out, stress, lamp_peak, time.perf_counter() - t_start)
