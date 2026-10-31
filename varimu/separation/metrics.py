"""Separation measures: per-track loudness matching and the glimpse proportion.

Loudness lies (CLAUDE.md's hard rule), and for separation it lies twice: a louder track
also sounds more separated. So every track is matched to the same integrated loudness
(ITU-R BS.1770) on its own, before it's mixed.

The glimpse proportion (Cooke, "A glimpsing model of speech perception in noise", JASA
119(3), 2006) is the energetic part of separation only: the share of the target's
time-frequency cells where it beats everything else by `local_snr_db`. Cells are 20 ms
frames on ERB-spaced bands (Glasberg and Moore 1990). Grouping cues (common fate, onsets,
distance) don't show in it; only the listening test sees them.
"""

from __future__ import annotations

import numpy as np

TARGET_LUFS = -23.0


def loudness_lufs(x: np.ndarray, fs: float) -> float:
    import pyloudnorm

    return float(pyloudnorm.Meter(int(fs)).integrated_loudness(np.asarray(x, float)))


def match_loudness(x: np.ndarray, fs: float, target_lufs: float = TARGET_LUFS) -> np.ndarray:
    return np.asarray(x, float) * 10 ** ((target_lufs - loudness_lufs(x, fs)) / 20)


def erb_edges_hz(lo_hz: float = 80.0, hi_hz: float = 12000.0, n: int = 48) -> np.ndarray:
    """Band edges equally spaced on the ERB-number scale (Glasberg and Moore 1990)."""

    def erb_n(f):
        return 21.4 * np.log10(1 + 0.00437 * f)

    e = np.linspace(erb_n(lo_hz), erb_n(hi_hz), n + 1)
    return (10 ** (e / 21.4) - 1) / 0.00437


def cell_energies(x: np.ndarray, fs: float, frame_s: float = 0.02) -> np.ndarray:
    """Energy per (ERB band, frame): Hann frames of 2 x `frame_s` hopped by `frame_s`."""
    hop = int(frame_s * fs)
    nwin = 2 * hop
    n_frames = max(1, (len(x) - nwin) // hop + 1)
    frames = np.lib.stride_tricks.sliding_window_view(np.asarray(x, float), nwin)[::hop][:n_frames]
    p = np.abs(np.fft.rfft(frames * np.hanning(nwin), axis=1)) ** 2
    f = np.fft.rfftfreq(nwin, 1.0 / fs)
    edges = erb_edges_hz()
    band = np.digitize(f, edges) - 1
    out = np.zeros((len(edges) - 1, n_frames))
    for b in range(len(edges) - 1):
        sel = band == b
        if sel.any():
            out[b] = p[:, sel].sum(1)
    return out


def _present(cells: np.ndarray, range_db: float) -> np.ndarray:
    return cells > cells.max() * 10 ** (-range_db / 10)


def glimpse_proportion(
    target: np.ndarray,
    rest: np.ndarray,
    fs: float,
    *,
    local_snr_db: float = 3.0,
    range_db: float = 50.0,
    notes: np.ndarray | None = None,
) -> float:
    """The share of the target's cells (those within `range_db` of its loudest cell) where
    it is `local_snr_db` above `rest` (the other tracks, as mixed).

    `notes`, the target before processing: count only the cells where it was present, so
    energy that processing adds in new cells (distortion's harmonics, a reverb's tail
    between notes) doesn't count as the notes being heard."""
    return _proportion(
        cell_energies(target, fs),
        cell_energies(rest, fs),
        fs,
        0.0,
        local_snr_db,
        _present(cell_energies(notes if notes is not None else target, fs), range_db),
    )


def _proportion(t, r, fs, g_db, local_snr_db, present) -> float:
    glimpsed = present & (t * 10 ** (g_db / 10) > r * 10 ** (local_snr_db / 10))
    return float(glimpsed.sum() / max(1, present.sum()))


def level_for_proportion(
    target: np.ndarray,
    rest: np.ndarray,
    fs: float,
    proportion: float,
    *,
    lo_db: float = -40.0,
    hi_db: float = 20.0,
    local_snr_db: float = 3.0,
    range_db: float = 50.0,
    notes: np.ndarray | None = None,
) -> float:
    """The gain (dB) on `target` at which its glimpse proportion against `rest` is
    `proportion` (bisection; the proportion rises with the gain). `notes` as in
    `glimpse_proportion`."""
    t, r = cell_energies(target, fs), cell_energies(rest, fs)
    present = _present(cell_energies(notes if notes is not None else target, fs), range_db)

    def prop(g_db):
        return _proportion(t, r, fs, g_db, local_snr_db, present)

    if prop(lo_db) >= proportion:
        return lo_db
    if prop(hi_db) < proportion:
        return hi_db
    for _ in range(40):
        mid = 0.5 * (lo_db + hi_db)
        if prop(mid) < proportion:
            lo_db = mid
        else:
            hi_db = mid
    return 0.5 * (lo_db + hi_db)
