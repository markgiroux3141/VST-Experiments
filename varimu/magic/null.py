"""How deep two passes of the same input cancel, stage by stage (ANALOG_MAGIC_FABLE.md AM0).

`align` lines b up with a (a fractional delay), `delay_track` / `dewarp` follow and remove a
slowly varying delay (a time base: wow and flutter), and `null_report` gives the residual's
level after each stage: raw, gain, one fixed filter (varimu.listen.difference's character
part), the time base. All levels in dB re a's rms.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import correlate, fftconvolve, medfilt, resample_poly
from scipy.signal.windows import hann, kaiser

from varimu.listen import difference

SMOOTH_S = 0.01  # the delay track's smoothing: 20 ms windows and this follow ~25 Hz of wow
THIRD_OCTAVES_HZ = tuple(float(1000 * 2 ** (k / 3)) for k in range(-17, 14))  # 20 Hz - 20 kHz


def rms_db(x: np.ndarray, re: np.ndarray | float) -> float:
    num = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    den = float(np.sqrt(np.mean(np.square(re)))) if not np.isscalar(re) else float(re)
    if num <= 0 or den <= 0:
        return float("-inf")
    return 20 * np.log10(num / den)


def frac_delay(x: np.ndarray, d: float, taps: int = 512) -> np.ndarray:
    """x delayed by d samples (any real d), same length: integer part by shifting, the
    fraction by a Kaiser-windowed (beta 10) sinc of `taps` taps (flat to ~0.97 of Nyquist)."""
    n = int(np.floor(d))
    f = d - n
    if f > 1e-12:
        k = np.arange(-taps // 2 + 1, taps // 2 + 1)
        h = np.sinc(k - f) * kaiser(taps, 10.0)
        h /= h.sum()
        y = fftconvolve(x, h)[taps // 2 - 1 : taps // 2 - 1 + len(x)]
    else:
        y = np.asarray(x, float).copy()
    out = np.zeros_like(y)
    if n >= 0:
        out[n:] = y[: len(y) - n] if n else y
    else:
        out[: len(y) + n] = y[-n:]
    return out


def _peak_lag(c: np.ndarray, lags: np.ndarray) -> tuple[float, float]:
    """(lag of the correlation's peak refined by a parabola through three points, peak)."""
    i = int(np.argmax(c))
    if 0 < i < len(c) - 1:
        y0, y1, y2 = c[i - 1], c[i], c[i + 1]
        den = y0 - 2 * y1 + y2
        p = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        return float(lags[i] + p), float(y1 - 0.25 * (y0 - y2) * p)
    return float(lags[i]), float(c[i])


def lag_of(a: np.ndarray, b: np.ndarray, max_lag: int) -> tuple[float, float]:
    """(how many samples b lags a, normalized correlation at the peak)."""
    n = min(len(a), len(b))
    a, b = np.asarray(a[:n], float), np.asarray(b[:n], float)
    c = correlate(b, a, mode="full", method="fft")
    lags = np.arange(-n + 1, n)
    sel = np.abs(lags) <= max_lag
    norm = np.sqrt(np.dot(a, a) * np.dot(b, b))
    return _peak_lag(c[sel] / (norm if norm > 0 else 1.0), lags[sel])


def refine_lag(a: np.ndarray, b: np.ndarray, d0: float, width: float = 1.0) -> float:
    """The lag near d0 that maximizes the correlation of a with b moved back by it (a
    golden-section search on the windowed-sinc delay; the parabola alone is biased by the
    peak's shape up to ~0.1 sample)."""
    n = min(len(a), len(b))
    m = min(n, 1 << 19)
    lo = max(0, (n - m) // 2)
    aa, bb = a[lo : lo + m], b[lo : lo + m]
    edge = int(abs(d0) + width) + 40

    def score(d: float) -> float:
        y = frac_delay(bb, -d)
        return -float(np.dot(aa[edge:-edge], y[edge:-edge]))

    g = (np.sqrt(5) - 1) / 2
    x0, x1 = d0 - width, d0 + width
    c, e = x1 - g * (x1 - x0), x0 + g * (x1 - x0)
    fc, fe = score(c), score(e)
    for _ in range(30):
        if fc < fe:
            x1, e, fe = e, c, fc
            c = x1 - g * (x1 - x0)
            fc = score(c)
        else:
            x0, c, fc = c, e, fe
            e = x0 + g * (x1 - x0)
            fe = score(e)
    return float((x0 + x1) / 2)


def align(a, b, fs, max_lag_s=0.05) -> tuple[np.ndarray, np.ndarray, float]:
    """a and b cut to their overlap with b moved to match a; the delay of b in samples
    (fractional: the cross-correlation's peak refined by a parabola, applied as a
    windowed-sinc fractional delay)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    d, _ = lag_of(a, b, int(max_lag_s * fs))
    d = refine_lag(a, b, d)
    bb = frac_delay(b, -d)
    n = min(len(a), len(b))
    lo = int(np.ceil(abs(d))) + 32
    hi = n - lo
    return a[lo:hi], bb[lo:hi], d


def delay_track(a, b, fs, window_s=0.02, hop_s=0.005, max_lag_s=0.002):
    """(times, delay of b against a in seconds) from windowed cross-correlations, each peak
    refined by a parabola; windows whose correlation peak is under 0.5 are NaN."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = min(len(a), len(b))
    w, hop, ml = int(window_s * fs), int(hop_s * fs), int(max_lag_s * fs)
    win = hann(w)
    times, delays = [], []
    for s in range(ml, n - w - ml, hop):
        aw = a[s : s + w] * win
        bw = b[s - ml : s + w + ml]
        c = correlate(bw, aw, mode="valid", method="fft")  # lag -ml..ml
        e_b = np.convolve(bw * bw, np.ones(w), mode="valid")  # Cauchy-Schwarz: peak <= 1
        norm = np.sqrt(np.dot(aw, aw) * np.maximum(e_b, 1e-300))
        lags = np.arange(-ml, ml + 1)
        lag, peak = _peak_lag(c / norm, lags)
        times.append((s + w / 2) / fs)
        delays.append(lag / fs if peak >= 0.5 else np.nan)
    return np.asarray(times), np.asarray(delays)


def dewarp(b, fs, times, delay_s) -> np.ndarray:
    """b resampled so that its delay track against a is zero: NaNs filled by linear
    interpolation, the track smoothed (a 3-point median, then a SMOOTH_S Hann), b read at
    t + delay(t) from an 8x upsampled copy by linear interpolation."""
    b = np.asarray(b, float)
    d = np.asarray(delay_s, float).copy()
    ok = np.isfinite(d)
    if not ok.any():
        return b.copy()
    d[~ok] = np.interp(np.flatnonzero(~ok), np.flatnonzero(ok), d[ok])
    d = medfilt(d, 3)
    hop = float(np.median(np.diff(times))) if len(times) > 1 else 0.01
    k = max(3, int(round(SMOOTH_S / hop)) | 1)
    w = hann(k + 2)[1:-1]
    d = np.convolve(np.pad(d, k // 2, mode="edge"), w / w.sum(), mode="valid")
    t = np.arange(len(b)) / fs
    dt = np.interp(t, times, d)
    up = 8
    bu = resample_poly(b, up, 1)
    pos = (t + dt) * fs * up
    return np.interp(pos, np.arange(len(bu)), bu, left=0.0, right=0.0)


def band_levels(r: np.ndarray, a: np.ndarray, fs: float) -> dict[float, float]:
    """Per third octave: r's level in the band re a's level in it (dB), from Welch spectra."""
    from scipy.signal import welch

    n = min(len(r), len(a), 1 << 15)
    f, pr = welch(r, fs, nperseg=n)
    _, pa = welch(a, fs, nperseg=n)
    out = {}
    for fc in THIRD_OCTAVES_HZ:
        if fc * 2 ** (1 / 6) > fs / 2:
            break
        sel = (f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6))
        if sel.sum() == 0:
            continue
        num, den = pr[sel].sum(), pa[sel].sum()
        out[round(fc, 1)] = (
            float(10 * np.log10(num / den)) if num > 0 and den > 0 else float("-inf")
        )
    return out


def _edge(n: int) -> int:
    """Samples left out at each end when measuring a fixed filter's residual: the FIR's half
    length (difference.linear_fit), whose convolution starts and ends on zeros."""
    taps = min(difference.LINEAR_FIT_N, 1 << int(np.floor(np.log2(max(n // 2, 2)))))
    return max(1, min(taps // 2, n // 4))


def null_report(a, b, fs, *, max_lag_s=0.05, dewarp_stage=True) -> dict:
    """How deep two passes null, in stages. All levels in dB re a's rms.
    raw: a - b after `align`. gain: a - g b. filter: the character part of
    difference.decompose(a, b) (one fixed filter removed). dewarped: the character part
    after `dewarp` (the time base removed). bands: the gain residual per third octave re a's
    level in that band. over_time: (t, gain residual per 100 ms block, dB re a's rms)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == len(b) and np.array_equal(a, b):
        return {"identical": True, "raw": float("-inf"), "gain": float("-inf"),
                "filter": float("-inf"), "dewarped": float("-inf"), "delay_samples": 0.0,
                "bands": {}, "over_time": [[], []]}
    aa, bb, d = align(a, b, fs, max_lag_s)
    out: dict = {"identical": False, "delay_samples": d}
    out["raw"] = rms_db(aa - bb, aa)
    g = difference.align_gain(aa, bb)
    rg = aa - g * bb
    out["gain_factor"] = g
    out["gain"] = rms_db(rg, aa)
    # The fixed filter and the time base see b moved by whole samples only (decompose
    # fits any delay itself; a fractional delay's droop near Nyquist would read as character).
    k = int(round(d))
    lo = abs(k) + 32
    ai, bi = a[lo : min(len(a), len(b)) - lo], np.roll(b, -k)[lo : min(len(a), len(b)) - lo]
    dec = difference.decompose(ai, bi)
    e = _edge(len(ai))
    out["filter"] = rms_db(dec.character[e:-e], ai[e:-e])
    out["tone"] = rms_db(dec.tone[e:-e], ai[e:-e])
    if dewarp_stage:
        t, dl = delay_track(ai, bi, fs)
        bw = dewarp(bi, fs, t, dl)
        m = int(0.01 * fs)
        a2, b2 = ai[m:-m], bw[m:-m]
        e2 = _edge(len(a2))
        out["dewarped"] = rms_db(
            difference.decompose(a2, b2).character[e2:-e2], a2[e2:-e2]
        )
        good = np.isfinite(dl)
        out["delay_track_rms_us"] = (
            float(np.std(dl[good]) * 1e6) if good.sum() > 2 else float("nan")
        )
    out["bands"] = band_levels(rg, aa, fs)
    blk = int(0.1 * fs)
    nb = len(aa) // blk
    ref = float(np.sqrt(np.mean(aa * aa)))
    out["over_time"] = [
        [round((k + 0.5) * 0.1, 3) for k in range(nb)],
        [rms_db(rg[k * blk : (k + 1) * blk], ref) for k in range(nb)],
    ]
    return out
