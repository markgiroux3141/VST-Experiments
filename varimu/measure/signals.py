"""Deterministic test signal library (Phase 0).

Levels are peak dBFS: 0 dBFS is a sine of amplitude 1.0. The mapping from full
scale to circuit volts is `audio.full_scale_volts_peak` in sim_settings.yaml and
is applied by the simulation layer, not here.

Every generator is a pure function of its parameters and the sample rate. The
generators that need randomness also take a numpy Generator. `render` derives
that Generator from (library seed, signal name), so adding or removing a signal
never changes the others. Rendering the same library with the same seed gives
bit-identical output for a given platform and numpy version, and manifest.json
records a hash of each signal so changes are visible.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import zlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

import varimu


@dataclass(frozen=True)
class Signal:
    samples: np.ndarray  # mono, float64
    sample_rate: int
    meta: dict[str, Any] = field(default_factory=dict)
    # Arrays that belong with the signal, e.g. the inverse filter of a sweep.
    companions: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.sample_rate


def db_to_amp(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _amp(level_dbfs: float | None) -> float:
    return 0.0 if level_dbfs is None else db_to_amp(level_dbfs)


def _rise(n: int) -> np.ndarray:
    """Raised-cosine ramp from 0 to 1 over n samples, excluding both endpoints."""
    return 0.5 - 0.5 * np.cos(np.pi * (np.arange(n) + 0.5) / n)


def _fade(x: np.ndarray, fade_in: int, fade_out: int) -> np.ndarray:
    x = x.copy()
    if fade_in:
        x[:fade_in] *= _rise(fade_in)
    if fade_out:
        x[-fade_out:] *= _rise(fade_out)[::-1]
    return x


def _stepped_sine(
    freq_hz: float,
    segments: Sequence[tuple[float, float | None]],
    sample_rate: int,
    ramp_s: float = 0.0,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Phase-continuous sine whose amplitude steps between (duration_s, level_dbfs) segments.

    A level of None means silence. Segment edges are snapped to whole carrier
    cycles, so with ramp_s=0 every step lands on a positive-going zero crossing.
    The landing is exact when sample_rate / freq_hz is an integer. With
    ramp_s > 0, each step becomes a raised-cosine transition centered on the edge.
    """
    edges_s = np.concatenate([[0.0], np.cumsum([d for d, _ in segments])])
    edges = np.round(np.round(edges_s * freq_hz) / freq_hz * sample_rate).astype(int)
    if np.any(np.diff(edges) <= 0):
        raise ValueError("a segment is shorter than half a carrier cycle")

    amps = [_amp(level) for _, level in segments]
    gain = np.repeat(amps, np.diff(edges))
    if ramp_s > 0:
        k = max(1, round(ramp_s * sample_rate))
        for i, e in enumerate(edges[1:-1]):
            lo, hi = max(e - k // 2, edges[i]), min(e + k - k // 2, edges[i + 2])
            gain[lo:hi] = amps[i] + (amps[i + 1] - amps[i]) * _rise(hi - lo)

    t = np.arange(edges[-1]) / sample_rate
    seg_meta = [
        {"start": int(a), "stop": int(b), "level_dbfs": level}
        for (_, level), a, b in zip(segments, edges[:-1], edges[1:], strict=True)
    ]
    return np.sin(2 * np.pi * freq_hz * t) * gain, seg_meta


# --- Generators ----------------------------------------------------------------


def tone_burst(
    *,
    freq_hz: float,
    base_dbfs: float | None,
    burst_dbfs: float,
    pre_s: float,
    burst_s: float,
    release_s: float,
    sample_rate: int,
) -> Signal:
    """Base level, step up to the burst, step back down: attack/release measurement.

    Steps are abrupt (on zero crossings) so the attack measurement isn't
    blurred by a ramp.
    """
    x, segs = _stepped_sine(
        freq_hz, [(pre_s, base_dbfs), (burst_s, burst_dbfs), (release_s, base_dbfs)], sample_rate
    )
    return Signal(
        x,
        sample_rate,
        {
            "freq_hz": freq_hz,
            "segments": segs,
            "burst_start": segs[1]["start"],
            "burst_stop": segs[1]["stop"],
        },
    )


def thump_bursts(
    *,
    freq_hz: float,
    burst_dbfs: Sequence[float],
    lead_silence_s: float,
    burst_s: float,
    gap_s: float,
    sample_rate: int,
) -> Signal:
    """Bursts out of digital silence: thump measurement.

    Use a high carrier frequency so the thump (a low-frequency transient from
    control-voltage imbalance on the push-pull grids) can be separated from the
    signal by low-pass filtering the output.
    """
    segments: list[tuple[float, float | None]] = [(lead_silence_s, None)]
    for level in burst_dbfs:
        segments += [(burst_s, level), (gap_s, None)]
    x, segs = _stepped_sine(freq_hz, segments, sample_rate)
    bursts = [s for s in segs if s["level_dbfs"] is not None]
    return Signal(x, sample_rate, {"freq_hz": freq_hz, "segments": segs, "bursts": bursts})


def stepped_sine(
    *,
    freq_hz: float,
    start_dbfs: float,
    stop_dbfs: float,
    step_db: float,
    hold_s: float,
    ramp_s: float = 0.002,
    sample_rate: int,
) -> Signal:
    """Ascending level staircase: static compression curve.

    Each step is held long enough for the gain reduction to settle. Measure it
    over the end of each segment (see meta["segments"]).
    """
    if step_db <= 0 or stop_dbfs < start_dbfs:
        raise ValueError("need step_db > 0 and stop_dbfs >= start_dbfs")
    n_steps = round((stop_dbfs - start_dbfs) / step_db) + 1
    levels = [round(start_dbfs + i * step_db, 9) for i in range(n_steps)]
    x, segs = _stepped_sine(freq_hz, [(hold_s, lv) for lv in levels], sample_rate, ramp_s)
    return Signal(x, sample_rate, {"freq_hz": freq_hz, "segments": segs})


def exp_sweep(
    *,
    f_start_hz: float,
    f_stop_hz: float,
    duration_s: float,
    level_dbfs: float,
    pre_s: float,
    post_s: float,
    fade_out_s: float = 0.01,
    sample_rate: int,
) -> Signal:
    """Synchronized exponential sine sweep, for harmonic distortion by Farina's method.

    The rate constant L is rounded so that f_start * L is an integer (Novak et
    al., "Synchronized swept-sine", JAES 2015). The sweep then starts at phase
    zero, and each harmonic's impulse response lands L * ln(k) seconds before
    the linear one. The actual duration is L * ln(f_stop / f_start), so it
    differs slightly from duration_s.

    companions["inverse"] is the Farina inverse filter (time-reversed sweep with
    a +6 dB/octave envelope), scaled so that convolving the sweep with it peaks
    at 1.0. Convolving a recorded output with it gives the linear IR at sample
    meta["ir_index"] and the k-th harmonic IR at
    ir_index - round(L * ln(k) * sample_rate).
    """
    f1, f2 = f_start_hz, f_stop_hz
    L = round(f1 * duration_s / np.log(f2 / f1)) / f1
    n = round(L * np.log(f2 / f1) * sample_rate)
    t = np.arange(n) / sample_rate
    sweep = db_to_amp(level_dbfs) * np.sin(2 * np.pi * f1 * L * np.expm1(t / L))
    sweep = _fade(sweep, 0, round(fade_out_s * sample_rate))

    inverse = sweep[::-1] * np.exp(-t / L)
    nfft = 1 << (2 * n - 1).bit_length()
    peak = np.max(np.abs(np.fft.irfft(np.fft.rfft(sweep, nfft) * np.fft.rfft(inverse, nfft), nfft)))
    inverse /= peak

    pre, post = round(pre_s * sample_rate), round(post_s * sample_rate)
    x = np.concatenate([np.zeros(pre), sweep, np.zeros(post)])
    meta = {
        "f_start_hz": f1,
        "f_stop_hz": f2,
        "L_s": L,
        "level_dbfs": level_dbfs,
        "sweep_start": pre,
        "sweep_stop": pre + n,
        "ir_index": pre + n - 1,
    }
    return Signal(x, sample_rate, meta, {"inverse": inverse})


def twin_tone(
    *,
    f1_hz: float,
    f2_hz: float,
    ratio: float,
    level_dbfs: float,
    duration_s: float,
    fade_s: float = 0.01,
    sample_rate: int,
) -> Signal:
    """Two-tone IMD signal: f1 at `ratio` times the amplitude of f2.

    The amplitudes sum to the peak level. SMPTE is 60 Hz + 7 kHz at 4:1, and
    CCIF is 19 kHz + 20 kHz at 1:1.
    """
    peak = db_to_amp(level_dbfs)
    a2 = peak / (1 + ratio)
    t = np.arange(round(duration_s * sample_rate)) / sample_rate
    x = ratio * a2 * np.sin(2 * np.pi * f1_hz * t) + a2 * np.sin(2 * np.pi * f2_hz * t)
    k = round(fade_s * sample_rate)
    return Signal(
        _fade(x, k, k),
        sample_rate,
        {
            "f1_hz": f1_hz,
            "f2_hz": f2_hz,
            "ratio": ratio,
            "level_dbfs": level_dbfs,
            "steady_start": k,
            "steady_stop": len(t) - k,
        },
    )


def multitone(
    *,
    f_lo_hz: float,
    f_hi_hz: float,
    n_tones: int,
    level_dbfs: float,
    period_s: float,
    repeats: int,
    sample_rate: int,
    rng: np.random.Generator,
) -> Signal:
    """Log-spaced, bin-centered multitone with random phases: frequency response under GR.

    Tones are snapped to multiples of 1/period_s, so an FFT over any whole
    period has no leakage. The signal repeats `repeats` times, so the first
    period can be discarded as settling. The phases come from `rng`, and the
    peak is normalized to level_dbfs.
    """
    period_n = round(period_s * sample_rate)
    if not np.isclose(period_n, period_s * sample_rate):
        raise ValueError("period_s * sample_rate must be an integer")
    bin_hz = sample_rate / period_n
    bins = np.unique(np.round(np.geomspace(f_lo_hz, f_hi_hz, n_tones) / bin_hz).astype(int))
    phases = rng.uniform(0, 2 * np.pi, len(bins))
    t = np.arange(period_n) / sample_rate
    one = np.sum(np.cos(2 * np.pi * np.outer(bins * bin_hz, t) + phases[:, None]), axis=0)
    one *= db_to_amp(level_dbfs) / np.max(np.abs(one))
    return Signal(
        np.tile(one, repeats),
        sample_rate,
        {
            "freqs_hz": (bins * bin_hz).tolist(),
            "phases_rad": phases.tolist(),
            "level_dbfs": level_dbfs,
            "period_samples": period_n,
            "repeats": repeats,
        },
    )


GENERATORS: dict[str, Callable[..., Signal]] = {
    "tone_burst": tone_burst,
    "thump_bursts": thump_bursts,
    "stepped_sine": stepped_sine,
    "exp_sweep": exp_sweep,
    "twin_tone": twin_tone,
    "multitone": multitone,
}


# --- Library ---------------------------------------------------------------------


@dataclass(frozen=True)
class SignalSpec:
    name: str
    kind: str  # key into GENERATORS
    params: dict[str, Any]


def default_library() -> list[SignalSpec]:
    """The standard measurement set run on every candidate (see plan, Phase 4)."""
    specs: list[SignalSpec] = []

    # Attack/release. Carriers divide 96 kHz evenly so steps land exactly on zero crossings.
    for f in (100, 1000, 6000):
        for lv in (-20, -10, 0):
            specs.append(
                SignalSpec(
                    f"burst_{f}hz_{lv}dbfs",
                    "tone_burst",
                    dict(
                        freq_hz=f,
                        base_dbfs=-40,
                        burst_dbfs=lv,
                        pre_s=1.0,
                        burst_s=1.0,
                        release_s=5.0,
                    ),
                )
            )
    # The slowest Time Constant positions release over tens of seconds.
    specs.append(
        SignalSpec(
            "burst_long_release_1000hz_0dbfs",
            "tone_burst",
            dict(freq_hz=1000, base_dbfs=-40, burst_dbfs=0, pre_s=1.0, burst_s=2.0, release_s=30.0),
        )
    )

    # Static compression curve.
    for f in (100, 1000):
        specs.append(
            SignalSpec(
                f"steps_{f}hz",
                "stepped_sine",
                dict(freq_hz=f, start_dbfs=-50, stop_dbfs=0, step_db=1, hold_s=0.5),
            )
        )

    # Harmonic distortion vs level and frequency. Start low for transformer LF saturation.
    for lv in (-30, -20, -10, 0):
        specs.append(
            SignalSpec(
                f"ess_{lv}dbfs",
                "exp_sweep",
                dict(
                    f_start_hz=10,
                    f_stop_hz=24000,
                    duration_s=10.0,
                    level_dbfs=lv,
                    pre_s=0.5,
                    post_s=1.0,
                ),
            )
        )

    # IMD.
    for lv in (-30, -20, -10, 0):
        specs.append(
            SignalSpec(
                f"smpte_{lv}dbfs",
                "twin_tone",
                dict(f1_hz=60, f2_hz=7000, ratio=4.0, level_dbfs=lv, duration_s=2.0),
            )
        )
        specs.append(
            SignalSpec(
                f"ccif_{lv}dbfs",
                "twin_tone",
                dict(f1_hz=19000, f2_hz=20000, ratio=1.0, level_dbfs=lv, duration_s=2.0),
            )
        )

    # Thump.
    specs.append(
        SignalSpec(
            "thump_6000hz",
            "thump_bursts",
            dict(
                freq_hz=6000, burst_dbfs=[-20, -10, 0], lead_silence_s=2.0, burst_s=0.5, gap_s=5.0
            ),
        )
    )

    # Frequency response under gain reduction.
    for lv in (-20, -10):
        specs.append(
            SignalSpec(
                f"multitone_{lv}dbfs",
                "multitone",
                dict(f_lo_hz=20, f_hi_hz=20000, n_tones=31, level_dbfs=lv, period_s=1.0, repeats=4),
            )
        )

    return specs


def render(spec: SignalSpec, *, sample_rate: int, seed: int) -> Signal:
    fn = GENERATORS[spec.kind]
    kwargs = dict(spec.params, sample_rate=sample_rate)
    if "rng" in inspect.signature(fn).parameters:
        kwargs["rng"] = np.random.default_rng([seed, zlib.crc32(spec.name.encode())])
    sig = fn(**kwargs)
    peak = float(np.max(np.abs(sig.samples)))
    if peak > 1.0 + 1e-9:
        raise ValueError(f"{spec.name}: peak {peak:.6f} exceeds full scale")
    return sig


def to_float32(x: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(x, dtype="<f4")


def sha256(x: np.ndarray) -> str:
    """Hash of the samples exactly as written to disk (little-endian float32)."""
    return hashlib.sha256(to_float32(x).tobytes()).hexdigest()


def _json_default(o: Any) -> Any:
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serializable: {type(o).__name__}")


def write_library(
    out_dir: Path,
    *,
    seed: int,
    sample_rate: int,
    specs: Iterable[SignalSpec] | None = None,
) -> dict[str, Any]:
    """Render specs (default: the full library) to float32 WAVs plus manifest.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for spec in default_library() if specs is None else specs:
        sig = render(spec, sample_rate=sample_rate, seed=seed)
        files = {"signal": f"{spec.name}.wav"}
        hashes = {"signal": sha256(sig.samples)}
        sf.write(out_dir / files["signal"], to_float32(sig.samples), sample_rate, subtype="FLOAT")
        for key, arr in sig.companions.items():
            files[key] = f"{spec.name}.{key}.wav"
            hashes[key] = sha256(arr)
            sf.write(out_dir / files[key], to_float32(arr), sample_rate, subtype="FLOAT")
        entries.append(
            {
                "name": spec.name,
                "kind": spec.kind,
                "params": spec.params,
                "files": files,
                "sha256": hashes,
                "num_samples": len(sig.samples),
                "duration_s": sig.duration_s,
                "meta": sig.meta,
            }
        )

    manifest = {
        "varimu_version": varimu.__version__,
        "numpy_version": np.__version__,
        "seed": seed,
        "sample_rate": sample_rate,
        "signals": entries,
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=_json_default)
    return manifest
