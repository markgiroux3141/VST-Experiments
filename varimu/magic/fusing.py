"""Noise that fuses (ANALOG_MAGIC_FABLE.md AM7): the tape model's own signal-dependent noise
against stationary noise of the same spectrum and power, and two constructed followers.

- n_phys: the tape's grain alone, y1 - y0 (print_audio with flutter off in both, grain seed 1
  against none: the same time base, so the difference is the grain and what it does);
- n_stat: Gaussian noise with n_phys's long-term spectrum (a 4096-tap FIR from its Welch
  spectrum) and its exact rms;
- n_env: n_stat times y0's broadband envelope (Hilbert, low-passed at 30 Hz), rescaled;
- n_band: per ERB band, n_stat's band times y0's envelope in that band, summed, rescaled.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from varimu.separation import grouping


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def stationary_like(n_ref: np.ndarray, fs: int, seed: int, taps: int = 4096) -> np.ndarray:
    """Gaussian noise with n_ref's long-term spectrum and rms."""
    f, p = signal.welch(n_ref, fs, nperseg=taps)
    h = signal.firwin2(taps + 1, f / (fs / 2), np.sqrt(p / p.max()))
    rng = np.random.default_rng([seed, 0x5747])
    w = rng.standard_normal(len(n_ref) + taps)
    y = signal.fftconvolve(w, h)[taps : taps + len(n_ref)]
    return y * _rms(n_ref) / _rms(y)


def broadband_envelope(y0: np.ndarray, fs: int, cutoff_hz: float = 30.0) -> np.ndarray:
    e = np.abs(signal.hilbert(y0))
    sos = signal.butter(2, cutoff_hz, fs=fs, output="sos")
    return np.maximum(signal.sosfiltfilt(sos, e), 0.0)


def env_follower(n_stat: np.ndarray, y0: np.ndarray, fs: int) -> np.ndarray:
    y = n_stat * broadband_envelope(y0, fs)
    return y * _rms(n_stat) / _rms(y)


def band_follower(n_stat: np.ndarray, y0: np.ndarray, fs: int) -> np.ndarray:
    """Per ERB band (grouping's 32 centres, 80 Hz-8 kHz, plus one band above), n_stat's band
    times y0's envelope in that band."""
    centres = list(grouping.erb_centres_hz())
    out = np.zeros_like(n_stat)
    edges = []
    for fc in centres:
        bw = grouping.erb_hz(fc)
        edges.append((max(fc - bw / 2, 20.0), fc + bw / 2))
    edges.append((edges[-1][1], min(20000.0, 0.45 * fs)))
    for lo, hi in edges:
        sos = signal.butter(2, [lo, hi], "bandpass", fs=fs, output="sos")
        nb = signal.sosfiltfilt(sos, n_stat)
        yb = signal.sosfiltfilt(sos, y0)
        env = np.abs(signal.hilbert(yb))
        env = signal.sosfiltfilt(signal.butter(2, 30.0, fs=fs, output="sos"), env)
        env = np.maximum(env, 0.0)
        out += nb * env / (_rms(env) + 1e-30)
    return out * _rms(n_stat) / _rms(out)


def noises(y0: np.ndarray, y1: np.ndarray, fs: int, seed: int = 1) -> dict[str, np.ndarray]:
    n_phys = y1 - y0
    n_stat = stationary_like(n_phys, fs, seed)
    return {
        "n_phys": n_phys,
        "n_stat": n_stat,
        "n_env": env_follower(n_stat, y0, fs),
        "n_band": band_follower(n_stat, y0, fs),
    }


def follow_measures(y0: np.ndarray, n: np.ndarray, fs: int) -> dict:
    """How much n follows y0: temporal coherence (grouping), and the correlation of their
    100 ms level envelopes in dB."""
    tc = grouping.temporal_coherence(y0, n, fs)
    blk = int(0.1 * fs)
    k = len(y0) // blk
    ly = 10 * np.log10(np.mean(y0[: k * blk].reshape(k, blk) ** 2, axis=1) + 1e-30)
    ln = 10 * np.log10(np.mean(n[: k * blk].reshape(k, blk) ** 2, axis=1) + 1e-30)
    sel = ly > ly.max() - 40
    corr = float(np.corrcoef(ly[sel], ln[sel])[0, 1]) if sel.sum() > 3 else float("nan")
    slope = float(np.polyfit(ly[sel], ln[sel], 1)[0]) if sel.sum() > 3 else float("nan")
    return {
        "coherence_cross": tc["cross"],
        "coherence_within": tc["within"],
        "level_corr": corr,
        "level_slope": slope,
        "level_db_re_signal": float(20 * np.log10(_rms(n) / _rms(y0))),
    }
