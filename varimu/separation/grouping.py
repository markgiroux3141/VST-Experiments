"""Grouping measures: what the glimpse proportion can't see (docs/SCENE_ANALYSIS.md).

The glimpse proportion (`metrics.py`) is energetic only. The ear also groups by cues that
move no energy between time-frequency cells; these measures put a number on four of them,
each after a published model:

- `temporal_coherence`: how far the two sources' cochlear envelopes rise and fall together
  at 2-32 Hz (temporal coherence: Elhilali et al., Neuron 61, 2009; Krishnan, Elhilali and
  Shamma, PLoS Comput Biol 10, 2014; the hearing-aid literature's across-source modulation
  correlation, Stone and Moore, JASA 2007). Coherent channels are bound into one stream, so
  higher = more fused.
- `onset_coincidence`: the share of one source's onsets that land within +-30 ms of the
  other's (Darwin 1984; a 30-50 ms lead segregates a component; Rasch 1979). Higher = more
  fused.
- `harmonic_cancellation`: de Cheveigne's harmonic cancellation (JASA 97, 1995; 101, 1997):
  the masker is nulled by a comb at its own period, the target's share of what's left is its
  SNR after cancellation. The gain over the plain SNR is what the masker's harmonicity buys;
  energy that belongs to neither source's harmonic series (intermodulation between them)
  survives the comb and costs it. Also the mix's inharmonic share: what survives both combs.
- `envelope_snr`: the envelope-domain SNR of the multi-resolution sEPSM (Joergensen, Ewert
  and Dau, JASA 134, 2013): per audio and modulation channel, the target's envelope power
  over the masker's, combined like independent detectors.

The two sources are the target's and the masker's shares of the mix. For tracks processed
apart they are the processed tracks. For a mix processed together (a bus device), each
share is what that source adds: `bus(t + m) - bus(m)` and `bus(t + m) - bus(t)`
(`shares`); intermodulation between them then lands in both, as the ear would meet it.
Linear processing gives the same shares either way.

The front end is deliberately simple: 4th-order Butterworth bands 1 ERB wide (Glasberg and
Moore 1990) at 24 kHz, Hilbert envelopes, at 1 kHz. Outside the render cache key.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

FS_FRONT = 24000
FS_ENV = 1000
RATES_HZ = (2.0, 4.0, 8.0, 16.0, 32.0)
ONSET_WINDOW_S = 0.03
EDGE_S = 0.3  # trimmed off both ends of the envelopes: the filters' start and end
COMPRESSION = 0.3  # cochlear compression of the envelope (Griffith et al. 2025: power 0.3)


def erb_hz(f):
    return 24.7 * (4.37 * np.asarray(f, float) / 1000 + 1)


def erb_centres_hz(lo_hz: float = 80.0, hi_hz: float = 8000.0, n: int = 32) -> np.ndarray:
    def erb_n(f):
        return 21.4 * np.log10(1 + 0.00437 * f)

    e = np.linspace(erb_n(lo_hz), erb_n(hi_hz), n)
    return (10 ** (e / 21.4) - 1) / 0.00437


def shares(bus, target: np.ndarray, masker: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The target's and the masker's shares of `bus(target + masker)` (see the module)."""
    both = bus(target + masker)
    return both - bus(masker), both - bus(target)


def _down(x: np.ndarray, fs: float, fs_out: int) -> np.ndarray:
    from fractions import Fraction

    r = Fraction(int(fs_out), int(fs)).limit_denominator(1000)
    return signal.resample_poly(np.asarray(x, float), r.numerator, r.denominator)


@dataclass
class Envelopes:
    centres_hz: np.ndarray
    env: np.ndarray  # (channel, sample at FS_ENV), linear amplitude


def envelopes(x: np.ndarray, fs: float, centres_hz: np.ndarray | None = None) -> Envelopes:
    """Hilbert envelopes of 1-ERB Butterworth bands, low-passed at 150 Hz, at FS_ENV."""
    c = erb_centres_hz() if centres_hz is None else np.asarray(centres_hz, float)
    y = _down(x, fs, FS_FRONT)
    out = []
    for fc in c:
        bw = erb_hz(fc)
        lo, hi = max(fc - bw / 2, 10.0), min(fc + bw / 2, 0.45 * FS_FRONT)
        sos = signal.butter(2, [lo, hi], "bandpass", fs=FS_FRONT, output="sos")
        e = np.abs(signal.hilbert(signal.sosfilt(sos, y)))
        out.append(e)
    env = np.array(out)
    sos = signal.butter(1, 150.0, fs=FS_FRONT, output="sos")
    env = signal.sosfilt(sos, env, axis=1)
    env = signal.resample_poly(env, 1, FS_FRONT // FS_ENV, axis=1)
    return Envelopes(c, np.maximum(env, 0.0))


def _rate_band(env: np.ndarray, rate_hz: float) -> np.ndarray:
    """A constant-Q (Q ~ 1) band of the envelopes around `rate_hz`."""
    sos = signal.butter(
        1, [rate_hz / np.sqrt(2), rate_hz * np.sqrt(2)], "bandpass", fs=FS_ENV, output="sos"
    )
    return signal.sosfiltfilt(sos, env, axis=1)


def temporal_coherence(
    t: np.ndarray, m: np.ndarray, fs: float, *, rates_hz=RATES_HZ, cycles: float = 4.0
) -> dict:
    """Correlation between the target's and the masker's compressed envelopes, per rate band.

    Per rate, windows of `cycles` periods (250 ms at 16 Hz, 2 s at 2 Hz), half overlapped;
    in each the zero-lag correlation of every target channel with every masker channel (the
    coherence matrix's cross-source block), weighted by the two channels' envelope power
    in the window, so channels a source doesn't occupy don't count. `within` is the same on
    the matrix's diagonal only (each channel with itself: Stone and Moore's ASMC).
    Returns {"rates": {rate: (cross, within)}, "cross": mean, "within": mean}."""
    cut = int(EDGE_S * FS_ENV)
    et = envelopes(t, fs).env[:, cut:-cut] ** COMPRESSION
    em = envelopes(m, fs).env[:, cut:-cut] ** COMPRESSION
    per = {}
    for rate in rates_hz:
        edge = int(max(EDGE_S, 1.0 / rate) * FS_ENV)
        bt = _rate_band(et, rate)[:, edge:-edge]
        bm = _rate_band(em, rate)[:, edge:-edge]
        win = int(cycles * FS_ENV / rate)
        hop = max(1, win // 2)
        num_x = den_x = num_d = den_d = 0.0
        for s in range(0, bt.shape[1] - win + 1, hop):
            a = bt[:, s : s + win]
            b = bm[:, s : s + win]
            a = a - a.mean(1, keepdims=True)
            b = b - b.mean(1, keepdims=True)
            pa = np.sqrt((a * a).sum(1))
            pb = np.sqrt((b * b).sum(1))
            cov = a @ b.T  # (ch_t, ch_m)
            w = np.outer(pa, pb)
            # corr * weight = cov; sum of weights = sum of pa pb.
            num_x += cov.sum()
            den_x += w.sum()
            num_d += np.trace(cov)
            den_d += np.trace(w)
        per[rate] = (num_x / max(den_x, 1e-300), num_d / max(den_d, 1e-300))
    return {
        "rates": per,
        "cross": float(np.mean([v[0] for v in per.values()])),
        "within": float(np.mean([v[1] for v in per.values()])),
    }


def onset_strength(x: np.ndarray, fs: float) -> np.ndarray:
    """Summed over channels: the half-wave rectified slope of the compressed envelope
    (a 10 ms Hann smoothing, which can't ring), at FS_ENV."""
    e = envelopes(x, fs).env ** COMPRESSION
    k = np.hanning(int(0.01 * FS_ENV) + 2)[1:-1]
    e = signal.fftconvolve(e, (k / k.sum())[None, :], mode="same", axes=1)
    d = np.diff(e, axis=1, prepend=e[:, :1]) * FS_ENV
    return np.maximum(d, 0.0).sum(0)


def onsets(x: np.ndarray, fs: float, *, rel: float = 0.3, skip_s: float = 0.05) -> np.ndarray:
    """Onset times (s): peaks of `onset_strength` above `rel` of its 99th percentile peak,
    at least 50 ms apart, the first `skip_s` (the filters' start) skipped."""
    o = onset_strength(x, fs)
    o[: int(skip_s * FS_ENV)] = 0.0
    peaks, props = signal.find_peaks(o, distance=int(0.05 * FS_ENV))
    if not len(peaks):
        return np.zeros(0)
    h = o[peaks]
    keep = h > rel * np.percentile(h, 99)
    return peaks[keep] / FS_ENV


def onset_coincidence(
    t: np.ndarray, m: np.ndarray, fs: float, *, window_s: float = ONSET_WINDOW_S
) -> float:
    """The share of the target's onsets with a masker onset within +-`window_s`:
    1 = every onset shared, 0 = none."""
    ot, om = onsets(t, fs), onsets(m, fs)
    if not len(ot) or not len(om):
        return 0.0
    d = np.abs(ot[:, None] - om[None, :]).min(1)
    return float((d <= window_s).mean())


def f0_track(
    x: np.ndarray,
    fs: float,
    *,
    frame_s: float = 0.04,
    hop_s: float = 0.01,
    fmin_hz: float = 60.0,
    fmax_hz: float = 800.0,
    threshold: float = 0.2,
) -> tuple[np.ndarray, np.ndarray]:
    """YIN (de Cheveigne and Kawahara, JASA 2002) on frames of `x` at FS_FRONT: (frame
    times in s, F0 in Hz, NaN where unvoiced or silent)."""
    y = _down(x, fs, FS_FRONT)
    n, hop = int(frame_s * FS_FRONT), int(hop_s * FS_FRONT)
    lag_min, lag_max = int(FS_FRONT / fmax_hz), int(FS_FRONT / fmin_hz)
    times, f0 = [], []
    level = np.sqrt(np.mean(y * y)) + 1e-300
    for s in range(0, len(y) - n - lag_max, hop):
        fr = y[s : s + n + lag_max]
        times.append((s + n / 2) / FS_FRONT)
        if np.sqrt(np.mean(fr[:n] ** 2)) < level * 10 ** (-40 / 20):
            f0.append(np.nan)
            continue
        base = fr[:n]
        d = np.array([np.sum((base - fr[tau : tau + n]) ** 2) for tau in range(lag_max + 1)])
        cmnd = np.ones_like(d)
        cs = np.cumsum(d[1:])
        cmnd[1:] = d[1:] * np.arange(1, len(d)) / np.maximum(cs, 1e-300)
        cand = np.where(cmnd[lag_min:] < threshold)[0]
        if not len(cand):
            f0.append(np.nan)
            continue
        tau = lag_min + cand[0]
        while tau + 1 < len(cmnd) and cmnd[tau + 1] < cmnd[tau]:
            tau += 1
        if 1 <= tau < len(cmnd) - 1:
            a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
            den = a - 2 * b + c
            tau = tau + (0.5 * (a - c) / den if den > 0 else 0.0)
        f0.append(FS_FRONT / tau)
    return np.array(times), np.array(f0)


def _comb(x: np.ndarray, fs: float, times: np.ndarray, f0: np.ndarray) -> np.ndarray:
    """x(n) - x(n - T0(n)), T0 from the F0 track (linear interpolation; identity where
    unvoiced)."""
    n = np.arange(len(x))
    tf = times * fs
    voiced = np.isfinite(f0)
    if not voiced.any():
        return x.copy()
    period = np.interp(n, tf[voiced], fs / f0[voiced])
    on = np.interp(n, tf, voiced.astype(float)) > 0.5
    delayed = np.interp(n - period, n, x, left=0.0)
    return np.where(on, x - delayed, x)


def harmonic_cancellation(
    t: np.ndarray,
    m: np.ndarray,
    fs: float,
    *,
    t_clean=None,
    m_clean=None,
    band_hz: float = 4000.0,
) -> dict:
    """de Cheveigne's harmonic cancellation, below `band_hz` (the resolved, phase-locked
    region; Saddler et al. 2021).

    The masker's F0 is tracked on `m_clean` (default `m`: a bus share carries the other
    source's intermodulation, so pass the masker processed alone), the target's on `t_clean`.
    Returns {"snr_db": plain target / masker, "snr_cancelled_db": after the masker's comb,
    "gain_db": their difference (what the masker's harmonicity buys the target), the same
    three for the masker against the target ("m_*"), and "inharmonic_db": what of the mix
    survives both combs, relative to what survives them from each source alone}."""
    sos = signal.butter(4, band_hz, fs=fs, output="sos")
    t = signal.sosfiltfilt(sos, t)
    m = signal.sosfiltfilt(sos, m)
    tt, ft = f0_track(t if t_clean is None else t_clean, fs)
    tm, fm = f0_track(m if m_clean is None else m_clean, fs)

    def e(x):
        return float(np.sum(x * x)) + 1e-300

    ct_m, cm_m = _comb(t, fs, tm, fm), _comb(m, fs, tm, fm)
    ct_t, cm_t = _comb(t, fs, tt, ft), _comb(m, fs, tt, ft)
    snr = 10 * np.log10(e(t) / e(m))
    snr_c = 10 * np.log10(e(ct_m) / e(cm_m))
    m_snr_c = 10 * np.log10(e(cm_t) / e(ct_t))
    # Both combs on each share: what is harmonic to neither F0 track.
    both_t = _comb(ct_m, fs, tt, ft)
    both_m = _comb(cm_m, fs, tt, ft)
    return {
        "snr_db": float(snr),
        "snr_cancelled_db": float(snr_c),
        "gain_db": float(snr_c - snr),
        "m_snr_db": float(-snr),
        "m_snr_cancelled_db": float(m_snr_c),
        "m_gain_db": float(m_snr_c + snr),
        "residual_db": float(10 * np.log10(e(both_t + both_m) / e(t + m))),
        "voiced_t": float(np.isfinite(ft).mean()),
        "voiced_m": float(np.isfinite(fm).mean()),
    }


def envelope_snr(
    t: np.ndarray, m: np.ndarray, fs: float, *, mod_hz=(1, 2, 4, 8, 16, 32, 64, 128)
) -> dict:
    """The multi-resolution sEPSM's envelope-domain SNR (Joergensen, Ewert and Dau 2013):
    per audio channel and modulation band (octaves, Q 1, only below a quarter of the
    channel's centre), segments 1 / f_mod long; envelope power normalized by the mix's
    envelope mean; SNRenv = (P(mix) - P(masker)) / P(masker), floored at -30 dB; combined as
    sqrt of the sum of squares. Returns {"snr_env_db", "per_mod": {f: dB}}."""
    mix = envelopes(t + m, fs)
    em = envelopes(m, fs).env
    ex = mix.env
    dc = ex.mean(1, keepdims=True) + 1e-300
    total = 0.0
    per_mod = {}
    for f in mod_hz:
        if f < FS_ENV / 4:
            sos = signal.butter(
                1, [f / np.sqrt(2), f * np.sqrt(2)], "bandpass", fs=FS_ENV, output="sos"
            )
            bx = signal.sosfiltfilt(sos, ex, axis=1)
            bm = signal.sosfiltfilt(sos, em, axis=1)
        else:
            continue
        seg = max(int(FS_ENV / f), 4)
        k = ex.shape[1] // seg
        px = (bx[:, : k * seg].reshape(len(ex), k, seg) ** 2).mean(2) / dc**2
        pm = (bm[:, : k * seg].reshape(len(ex), k, seg) ** 2).mean(2) / dc**2
        px, pm = np.maximum(px, 1e-3), np.maximum(pm, 1e-3)
        snr = np.maximum((px - pm) / pm, 10 ** (-30 / 10))
        use = mix.centres_hz / 4 > f
        s = (snr[use].mean(1) ** 2).sum() if use.any() else 0.0
        per_mod[f] = float(10 * np.log10(np.sqrt(s) + 1e-300))
        total += s
    return {"snr_env_db": float(10 * np.log10(np.sqrt(total) + 1e-300)), "per_mod": per_mod}


def all_measures(t, m, fs, *, t_clean=None, m_clean=None) -> dict:
    return {
        "coherence": temporal_coherence(t, m, fs),
        "onsets": onset_coincidence(t, m, fs),
        "harmonic": harmonic_cancellation(t, m, fs, t_clean=t_clean, m_clean=m_clean),
        "envelope_snr": envelope_snr(t, m, fs),
    }
