"""Second toy: stage values AND derivatives (v' is known at every stage: it is F / C) as
output samples: four data per step -> a 4x stream -> decimated. Against 2x and 4x runs.
Also: the same at a 96 kHz step (the draft's rate) against 2x of that."""

from __future__ import annotations

import numpy as np
from scipy import signal
from stage_sampling import AMP, F0, GAMMA, alias_db, f, trbdf2


def weights(offsets, use_deriv, half=16, zones=3.6, reg=1e-10):
    """LS weights giving v((n + off) T) for each off in `offsets`, from v (and T v') at
    (k) T and (k + GAMMA) T, k = n - half + 1 .. n + half; exact for |f| < zones * fs / 2."""
    ks = np.arange(-half + 1, half + 1)
    times = np.concatenate([ks.astype(float), ks + GAMMA])
    fgrid = np.linspace(-zones / 2, zones / 2, 4001)
    e = np.exp(2j * np.pi * np.outer(fgrid, times))
    cols = [e]
    if use_deriv:
        cols.append(e * (2j * np.pi * fgrid)[:, None])  # T v'
    a = np.hstack(cols)
    ar = np.vstack([a.real, a.imag, np.sqrt(reg) * np.eye(a.shape[1])])
    out = []
    for off in offsets:
        d = np.exp(2j * np.pi * fgrid * off)
        dr = np.concatenate([d.real, d.imag, np.zeros(a.shape[1])])
        w, *_ = np.linalg.lstsq(ar, dr, rcond=None)
        out.append(w)
    return ks, out


def run(fs, label):
    seconds = 1.5
    u = lambda t: AMP * np.sin(2 * np.pi * F0 * t)  # noqa: E731
    ends, stages = trbdf2(fs, seconds, u)
    n = len(ends)
    h = 1.0 / fs
    t_end = (np.arange(n) + 1) * h
    t_stage = (np.arange(n) + GAMMA) * h
    v_grid = np.concatenate([[0.0], ends])[:n]  # v(kT)
    d_grid = f(v_grid, u(np.arange(n) * h)) * h  # T v'(kT)
    d_stage = f(stages, u(t_stage)) * h
    _ = t_end

    def rebuild(factor, use_deriv, zones):
        offs = [j / factor for j in range(1, factor)]
        ks, ws = weights(offs, use_deriv, zones=zones)
        nk = len(ks)
        up = np.zeros(factor * n)
        up[0::factor] = v_grid
        for j, w in enumerate(ws, start=1):
            col = np.zeros(n)
            for m in range(40, n - 40):
                acc = w[:nk] @ v_grid[m + ks] + w[nk : 2 * nk] @ stages[m + ks]
                if use_deriv:
                    acc += w[2 * nk : 3 * nk] @ d_grid[m + ks] + w[3 * nk :] @ d_stage[m + ks]
                col[m] = acc
            up[j::factor] = col
        dec = signal.firwin(factor * 128 - 1, (1 - 0.08) / factor, window=("kaiser", 12.0))
        return signal.lfilter(dec, 1.0, up)[::factor][: n - 80]

    def plain(factor):
        e, _ = trbdf2(factor * fs, seconds, u)
        dec = signal.firwin(factor * 128 - 1, (1 - 0.08) / factor, window=("kaiser", 12.0))
        return signal.lfilter(dec, 1.0, np.concatenate([[0.0], e])[: factor * n])[::factor]

    nfft = int(fs)
    print(f"--- step rate {fs} Hz ({label})")
    print(f"points                         {alias_db(ends, fs, nfft):7.1f} dB")
    print(f"values at stages   -> 2x       {alias_db(rebuild(2, False, 1.84), fs, nfft):7.1f} dB")
    print(f"values + slopes    -> 4x       {alias_db(rebuild(4, True, 3.6), fs, nfft):7.1f} dB")
    print(f"a 2x run                       {alias_db(plain(2), fs, nfft):7.1f} dB")
    print(f"a 4x run                       {alias_db(plain(4), fs, nfft):7.1f} dB")


if __name__ == "__main__":
    run(48000, "draft-1x")
    run(96000, "draft")
