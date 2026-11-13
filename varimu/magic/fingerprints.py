"""Record forensics (ANALOG_MAGIC_FABLE.md AM1): numbers from audio that might separate a
1960s record from a modern one. Each function is checked on synthetic signals with known
answers (tests/test_magic_fingerprints.py) before it sees music.

Inputs: `x` mono (n,) or stereo (n, 2), `fs`. Everything is analysed at ANALYSIS_FS (48 kHz,
resampled with resample_poly). `floor_follow` and `bass_arrival` are proxies that music
confounds (the program's own highs, an instrument's own low build-up): compare them only
between versions of the same material.
"""

from __future__ import annotations

from math import gcd

import numpy as np
from scipy import signal

from varimu.separation import grouping

ANALYSIS_FS = 48000
THIRDS_HZ = tuple(float(1000 * 2 ** (k / 3)) for k in range(-16, 14))  # 25 Hz - 20 kHz
OCTAVES_HZ = (63.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0)
WINDOW_S = 3.0
HUM_HZ = (50.0, 60.0, 100.0, 120.0, 150.0, 180.0)


def to_fs(x: np.ndarray, fs: int, fs_out: int = ANALYSIS_FS) -> np.ndarray:
    x = np.asarray(x, float)
    if fs == fs_out:
        return x
    g = gcd(int(fs), int(fs_out))
    return signal.resample_poly(x, fs_out // g, int(fs) // g, axis=0)


def mono(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, float)
    return x.mean(axis=1) if x.ndim == 2 else x


def _windows(n: int, fs: int, seconds: float = WINDOW_S):
    w = int(seconds * fs)
    for s in range(0, max(n - w + 1, 1), w):
        yield slice(s, min(s + w, n))


# --- Spectrum -----------------------------------------------------------------------------


def ltas(x: np.ndarray, fs: int) -> dict:
    """Third-octave long-term spectrum (mean power density per band, dB re 1/Hz), its tilt
    (dB/octave, a line through 100 Hz-10 kHz) and the highest band within 40 dB of 1 kHz's."""
    y = to_fs(mono(x), fs)
    f, p = signal.welch(y, ANALYSIS_FS, nperseg=8192, window="hann")
    bands: dict[float, float] = {}
    for fc in THIRDS_HZ:
        sel = (f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6))
        if sel.any():
            bands[round(fc, 1)] = float(10 * np.log10(np.mean(p[sel]) + 1e-30))
    fcs = np.array(list(bands))
    lv = np.array(list(bands.values()))
    sel = (fcs >= 99) & (fcs <= 10100)
    tilt = float(np.polyfit(np.log2(fcs[sel]), lv[sel], 1)[0])
    ref = lv[np.argmin(np.abs(fcs - 1000))]
    above = fcs[lv >= ref - 40]
    return {"bands_db": bands, "tilt_db_oct": tilt, "hf_edge_hz": float(above.max())}


# --- Peaks and shape ----------------------------------------------------------------------


def _crest_db(x: np.ndarray) -> float:
    r = np.sqrt(np.mean(x * x))
    return float(20 * np.log10(np.abs(x).max() / r)) if r > 0 else float("nan")


def crest_by_band(x: np.ndarray, fs: int) -> dict:
    """Per octave band 63 Hz-8 kHz (4th-order Butterworth): peak over rms in dB per 3 s
    window, the median over windows; also the broadband crest."""
    y = to_fs(mono(x), fs)
    out: dict[str, float] = {}
    out["broadband"] = float(np.nanmedian([_crest_db(y[s]) for s in _windows(len(y), ANALYSIS_FS)]))
    for fc in OCTAVES_HZ:
        sos = signal.butter(
            4,
            [fc / np.sqrt(2), min(fc * np.sqrt(2), 0.45 * ANALYSIS_FS)],
            "bandpass",
            fs=ANALYSIS_FS,
            output="sos",
        )
        b = signal.sosfilt(sos, y)
        b = b[int(0.2 * ANALYSIS_FS) :]
        vals = [_crest_db(b[s]) for s in _windows(len(b), ANALYSIS_FS)]
        out[f"{fc:g}"] = float(np.nanmedian(vals)) if vals else float("nan")
    return out


def asymmetry(x: np.ndarray, fs: int) -> dict:
    """Per 3 s window: 20 log10(max positive / max negative) and the skewness; the median of
    their absolute values (a waveform's lopsidedness, which phase rotation changes)."""
    y = to_fs(mono(x), fs)
    pk, sk = [], []
    for s in _windows(len(y), ANALYSIS_FS):
        w = y[s] - np.mean(y[s])
        mp, mn = w.max(), -w.min()
        if mp > 0 and mn > 0:
            pk.append(abs(20 * np.log10(mp / mn)))
        sd = np.std(w)
        if sd > 0:
            sk.append(abs(float(np.mean(w**3) / sd**3)))
    return {
        "peak_ratio_db": float(np.median(pk)) if pk else float("nan"),
        "skewness": float(np.median(sk)) if sk else float("nan"),
    }


# --- Level --------------------------------------------------------------------------------


def k_weight(x: np.ndarray, fs: int) -> np.ndarray:
    """BS.1770's K filter (its two biquads re-derived for fs; scripts/lightfoot_mix_analyze.py)."""
    f0, g, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = np.tan(np.pi * f0 / fs)
    vh = 10 ** (g / 20)
    vb = vh**0.4996667741545416
    a0 = 1 + k / q + k * k
    b = [(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0]
    a = [1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    y = signal.lfilter(b, a, x, axis=0)
    f0, q = 38.13547087602444, 0.5003270373238773
    k = np.tan(np.pi * f0 / fs)
    a0 = 1 + k / q + k * k
    a = [1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0]
    return signal.lfilter([1, -2, 1], a, y, axis=0)


def short_term_levels(x: np.ndarray, fs: int, block_s=0.4, hop_s=0.1) -> np.ndarray:
    """K-weighted levels (LUFS-like, -0.691 + 10 log10 of the channels' summed mean square)
    of 400 ms blocks every 100 ms."""
    y = k_weight(np.asarray(x, float), fs)
    p = y * y if y.ndim == 1 else (y * y).sum(axis=1)
    c = np.concatenate([[0.0], np.cumsum(p)])
    b, h = int(block_s * fs), int(hop_s * fs)
    starts = np.arange(0, len(p) - b + 1, h)
    ms = (c[starts + b] - c[starts]) / b
    return -0.691 + 10 * np.log10(ms + 1e-30)


def level_distribution(x: np.ndarray, fs: int) -> dict:
    """Short-term level's 10 / 50 / 95 percentiles and the spread p95 - p10 (blocks more than
    40 dB under the loudest dropped: silence between songs isn't dynamics)."""
    lv = short_term_levels(x, fs)
    lv = lv[lv > lv.max() - 40]
    p10, p50, p95 = np.percentile(lv, [10, 50, 95])
    return {"p10": float(p10), "p50": float(p50), "p95": float(p95), "spread_db": float(p95 - p10)}


# --- Modulation ---------------------------------------------------------------------------


def _mod_band(env: np.ndarray, lo: float = 2.0, hi: float = 32.0) -> np.ndarray:
    sos = signal.butter(2, [lo, hi], "bandpass", fs=grouping.FS_ENV, output="sos")
    return signal.sosfiltfilt(sos, env, axis=1)


def comodulation(x: np.ndarray, fs: int, min_apart: int = 8) -> dict:
    """Envelopes of 32 ERB bands (grouping.envelopes), compressed (power 0.3), band-passed
    2-32 Hz; the mean correlation of every pair at least `min_apart` channels apart: how
    much the record's bands move together."""
    e = grouping.envelopes(mono(x), fs)
    env = e.env**grouping.COMPRESSION
    edge = int(grouping.EDGE_S * grouping.FS_ENV)
    m = _mod_band(env)[:, edge:-edge]
    m = m - m.mean(axis=1, keepdims=True)
    sd = m.std(axis=1)
    ok = sd > 0
    z = np.zeros_like(m)
    z[ok] = m[ok] / sd[ok, None]
    c = (z @ z.T) / m.shape[1]
    n = len(c)
    i, j = np.triu_indices(n, k=min_apart)
    vals = c[i, j][ok[i] & ok[j]]
    return {"mean_corr": float(np.mean(vals)) if len(vals) else float("nan")}


def floor_follow(x: np.ndarray, fs: int) -> dict:
    """A proxy for noise that follows the signal. STFT (2048, hop 512 at 48 kHz). Per frame:
    floor = the 10th percentile of bin power in 6-12 kHz (dB), level = 100 Hz-4 kHz power
    (dB). Over frames within 30 dB of the loudest: the slope of floor on level and their
    correlation."""
    y = to_fs(mono(x), fs)
    f, _, z = signal.stft(y, ANALYSIS_FS, nperseg=2048, noverlap=2048 - 512, boundary=None)
    p = np.abs(z) ** 2
    hi = (f >= 6000) & (f <= 12000)
    lo = (f >= 100) & (f <= 4000)
    floor = 10 * np.log10(np.percentile(p[hi], 10, axis=0) + 1e-30)
    level = 10 * np.log10(p[lo].sum(axis=0) + 1e-30)
    sel = level > level.max() - 30
    if sel.sum() < 10:
        return {"slope": float("nan"), "corr": float("nan")}
    slope = float(np.polyfit(level[sel], floor[sel], 1)[0])
    corr = float(np.corrcoef(level[sel], floor[sel])[0, 1])
    return {"slope": slope, "corr": corr}


# --- Lines, stereo, pitch -----------------------------------------------------------------


def hum(x: np.ndarray, fs: int, fft_s: float = 16.0) -> dict:
    """Mains lines: per frequency, the line's amplitude (peak dBFS, the noise around it
    removed) and how far it stands above the median of its neighbours (dB), from Hann
    FFTs of fft_s, power-averaged."""
    y = to_fs(mono(x), fs)
    n = int(fft_s * ANALYSIS_FS)
    if len(y) < n:
        n = 1 << int(np.floor(np.log2(len(y))))
    w = np.hanning(n)
    acc = None
    count = 0
    for s in range(0, len(y) - n + 1, n // 2):  # half overlap
        X = np.fft.rfft(y[s : s + n] * w)
        acc = np.abs(X) ** 2 if acc is None else acc + np.abs(X) ** 2
        count += 1
    p = acc / count
    df = ANALYSIS_FS / n
    out = {}
    for f0 in HUM_HZ:
        k0 = int(round(f0 / df))
        win = max(1, int(round(0.5 / df)))
        kp = k0 - win + int(np.argmax(p[k0 - win : k0 + win + 1]))
        nb = np.r_[kp - int(5 / df) : kp - int(1 / df), kp + int(1 / df) + 1 : kp + int(5 / df) + 1]
        noise = float(np.median(p[nb]))
        # Hann: a sine of amplitude A gives |X| = A sum(w) / 2 at its bin; the main lobe's
        # three bins hold 1.5x the peak's power in all (sum w^2 / (sum w)^2 * n = 1.5).
        line = max(float(p[kp - 1 : kp + 2].sum()) - 3 * noise, 0.0) / 1.5
        amp = 2 * np.sqrt(line) / w.sum()
        out[f"{f0:g}"] = {
            "level_dbfs": float(20 * np.log10(amp)) if amp > 0 else float("-inf"),
            "above_db": float(10 * np.log10(p[kp] / noise)) if noise > 0 else float("inf"),
        }
    return out


def stereo(x: np.ndarray, fs: int) -> dict | None:
    """Stereo only: L / R correlation, side over mid (dB), coherence per octave band."""
    x = np.asarray(x, float)
    if x.ndim != 2 or x.shape[1] != 2:
        return None
    y = to_fs(x, fs)
    left, right = y[:, 0], y[:, 1]
    mid, side = (left + right) / 2, (left - right) / 2
    corr = float(np.corrcoef(left, right)[0, 1]) if np.std(left) > 0 and np.std(right) > 0 else 1.0
    ms, ss = np.mean(mid**2), np.mean(side**2)
    f, coh = signal.coherence(left, right, ANALYSIS_FS, nperseg=4096)
    bands = {}
    for fc in OCTAVES_HZ:
        sel = (f >= fc / np.sqrt(2)) & (f < fc * np.sqrt(2))
        bands[f"{fc:g}"] = float(np.mean(coh[sel])) if sel.any() else float("nan")
    return {
        "corr": corr,
        "side_over_mid_db": float(10 * np.log10(ss / ms)) if ss > 0 and ms > 0 else float("-inf"),
        "coherence": bands,
    }


def tuning(x: np.ndarray, fs: int, window_s: float = 10.0) -> dict:
    """Per window: spectral peaks 200-2000 Hz of the averaged power spectrum (16384-point
    segments, peaks refined by a parabola on log power), each peak's cents modulo 100 re
    A4 = 440 Hz, their circular mean weighted by peak power: the record's pitch offset.
    The median over windows and the drift (max - min)."""
    y = to_fs(mono(x), fs)
    offs = []
    for s in _windows(len(y), ANALYSIS_FS, window_s):
        seg = y[s]
        if len(seg) < 16384 or np.std(seg) == 0:
            continue
        f, p = signal.welch(seg, ANALYSIS_FS, nperseg=16384, window="hann")
        lp = 10 * np.log10(p + 1e-30)
        sel = np.flatnonzero((f >= 200) & (f <= 2000))
        pk, prop = signal.find_peaks(lp[sel], prominence=10)
        if len(pk) < 3:
            continue
        idx = sel[pk]
        order = np.argsort(prop["prominences"])[::-1][:30]
        idx = idx[order]
        a, b, c = lp[idx - 1], lp[idx], lp[idx + 1]
        den = a - 2 * b + c
        d = np.where(den != 0, 0.5 * (a - c) / den, 0.0)
        fpk = f[idx] + d * (f[1] - f[0])
        cents = 1200 * np.log2(fpk / 440.0)
        ang = 2 * np.pi * np.mod(cents, 100) / 100
        wgt = 10 ** (b / 10)
        m = np.angle(np.sum(wgt * np.exp(1j * ang)))
        offs.append(float(m / (2 * np.pi) * 100))
    if not offs:
        return {"offset_cents": float("nan"), "drift_cents": float("nan")}
    # Unwrap around the circular mean of the windows before the median and the drift.
    cm = np.angle(np.mean(np.exp(2j * np.pi * np.array(offs) / 100))) / (2 * np.pi) * 100
    rel = (np.array(offs) - cm + 50) % 100 - 50 + cm
    return {"offset_cents": float(np.median(rel)), "drift_cents": float(rel.max() - rel.min())}


def band_rms(x: np.ndarray, fs: float, lo: float, hi: float) -> float:
    """rms of x's content between lo and hi, from its spectrum (brick-wall: a filter's skirt
    would scale a component near a band edge)."""
    x = np.asarray(x, float) - np.mean(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / fs)
    sel = (f >= lo) & (f < hi)
    return float(np.sqrt(2 * np.sum(np.abs(X[sel]) ** 2)) / len(x))


def flutter(
    x: np.ndarray,
    fs: int,
    band_hz: tuple[float, float],
    segment_s: tuple[float, float] | None = None,
) -> dict:
    """A sustained fixed-pitch partial's frequency deviation (the method of
    scripts/tape_flutter.py): band-pass, Hilbert, instantaneous frequency over its mean; rms
    in 0.2-6 Hz (wow) and 6-200 Hz (flutter), as fractions."""
    y = mono(x)
    if segment_s is not None:
        y = y[int(segment_s[0] * fs) : int(segment_s[1] * fs)]
    sos = signal.butter(4, list(band_hz), "bandpass", fs=fs, output="sos")
    z = signal.hilbert(signal.sosfiltfilt(sos, y))
    inst = np.diff(np.unwrap(np.angle(z))) * fs / (2 * np.pi)
    edge = int(0.3 * fs)
    inst = inst[edge:-edge]
    dev = inst / np.mean(inst) - 1.0
    # Decimate the deviation to 1 kHz before the narrow filters.
    dec = int(fs // 1000)
    d = signal.resample_poly(dev, 1, dec)
    return {"wow": band_rms(d, fs / dec, 0.2, 6.0), "flutter": band_rms(d, fs / dec, 6.0, 200.0)}


def bass_arrival(x: np.ndarray, fs: int, max_lag_s: float = 0.06) -> dict:
    """Paired comparisons only: at each onset, when the 40-100 Hz envelope reaches half its
    maximum after the 2-6 kHz envelope does (within +- max_lag_s); the median (positive: the
    bass arrives later). (The doc's cross-correlation peak is biased by the bands' different
    envelope shapes; the half-maximum crossing isn't.)"""
    y = to_fs(mono(x), fs)
    fe = 1000

    def env(lo, hi):
        sos = signal.butter(4, [lo, hi], "bandpass", fs=ANALYSIS_FS, output="sos")
        e = np.abs(signal.hilbert(signal.sosfiltfilt(sos, y)))  # zero phase: no band delay
        return signal.resample_poly(e, 1, ANALYSIS_FS // fe)

    lo_e, hi_e = env(40, 100), env(2000, 6000)
    ons = grouping.onsets(y, ANALYSIS_FS)
    pre, w = int(0.05 * fe), int(max_lag_s * fe) + int(0.25 * fe)
    lags = []
    for t in ons:
        s = int(t * fe) - pre
        if s < 0 or s + w > len(lo_e):
            continue
        # Arrival: the first time each band's envelope reaches half its maximum in the
        # window (zero-phase filters: a smoothed step's half point stays on the step).
        a, b = hi_e[s : s + w], lo_e[s : s + w]
        if a.max() <= 0 or b.max() <= 0:
            continue
        ta = int(np.argmax(a >= 0.5 * a.max()))
        tb = int(np.argmax(b >= 0.5 * b.max()))
        if abs(tb - ta) <= int(max_lag_s * fe):
            lags.append((tb - ta) / fe)
    return {"median_s": float(np.median(lags)) if lags else float("nan"), "n": len(lags)}


def all_fingerprints(x: np.ndarray, fs: int) -> dict:
    """Every fingerprint of one excerpt except the manual / paired ones (flutter,
    bass_arrival)."""
    out = {
        "ltas": ltas(x, fs),
        "crest_by_band": crest_by_band(x, fs),
        "asymmetry": asymmetry(x, fs),
        "level_distribution": level_distribution(x, fs),
        "comodulation": comodulation(x, fs),
        "floor_follow": floor_follow(x, fs),
        "hum": hum(x, fs),
        "tuning": tuning(x, fs),
    }
    st = stereo(x, fs)
    if st is not None:
        out["stereo"] = st
    return out
