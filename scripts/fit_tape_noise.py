"""Fit Scotch 111's grain (docs/TAPE_PLAN.md, TM3) to 3M Sound Talk No. 34's noise spectra
(data/datasheets/scotch_111_noise.csv): the particle volume to the bulk-erased spectrum
(Fig. 3), the packing field's strength and correlation length to the DC-noise spectrum
(Fig. 2: DC at the 3% level in the head; an exponentially correlated field).

    uv run --extra fast python scripts/fit_tape_noise.py [--seconds 3]

The machine is the first print's (varimu.devices.tape_machine) at 7.5 ips, aligned as the
351 manual says, NAB playback; levels are dB below the 400 Hz tone that gives 3% THD.
Erased tape: no bias, nothing recorded, the particles' Poisson grain only (its power scales
with particle volume over packing). DC noise: the stream fed the 3% tone's rms field
directly (the bulletin's DC in the head winding), with the grain: Poisson plus the packing
field (its power scales with packing_sigma^2). The bulletin's machine noise (Fig. 3) is
added in power to both. Writes reports/tape/noise_fit.json and noise_fit.png; the fitted
numbers are library.SCOTCH111_NOISE (source: this script and its report).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys

import numpy as np
from scipy import signal as sps

from varimu.config import REPO_ROOT
from varimu.devices import library
from varimu.devices.tape import TapeNoise
from varimu.devices.tape_machine import (
    MINUS_18_DBFS_PEAK,
    TapeMachineSpec,
    _filter,
    aligned,
    print_audio,
    rec_network,
    repro_output,
    stream_params,
)

FS = 96_000.0
OUT = REPO_ROOT / "reports" / "tape"
PACKING = 0.35  # provisional, fixed: only volume / packing is seen
V0 = 4.7e-21  # the runs' particle volume (scaled after)
SEED = 1
# The bands fitted. Above 2.4 kHz the bulletin's machine (a "standard audio recorder", its
# HF response not printed) sets the level: its noise there rose when plastic base improved
# head contact (p.3), while this machine is aligned flat. Below 300 Hz its erased noise is
# the machine's own (Fig. 3's machine noise). Erased: 300-2400 Hz; DC noise: 20-2400 Hz.
ERASED_BANDS = (300.0, 2400.0)
DC_BANDS = (20.0, 2400.0)


def bands(y: np.ndarray, lo_hi: np.ndarray) -> np.ndarray:
    """Power per octave band (Welch)."""
    f, p = sps.welch(y, FS, nperseg=1 << 15)
    df = f[1] - f[0]
    return np.array([p[(f >= lo) & (f < hi)].sum() * df for lo, hi in lo_hi])


def tone(spec, tape, al, drive_db: float) -> tuple[float, float]:
    """(THD, the fundamental's rms) of a 400 Hz tone printed at drive_db over 0 VU."""
    n = int(0.4 * FS)
    x = MINUS_18_DBFS_PEAK * np.sin(2 * math.pi * 400.0 * np.arange(n) / FS)
    y = print_audio(x, FS, spec, tape, al, drive_db=drive_db)
    seg = y[n // 3 :]
    k = np.arange(len(seg))
    a = [
        abs(2 * np.mean(seg * np.exp(-2j * math.pi * h * 400.0 * k / FS))) for h in (1, 2, 3, 4, 5)
    ]
    return math.sqrt(sum(v * v for v in a[1:])) / a[0], a[0] / math.sqrt(2.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=3.0)
    a = ap.parse_args()
    import circuitsim

    data = np.genfromtxt(
        REPO_ROOT / "data" / "datasheets" / "scotch_111_noise.csv", delimiter=",", names=True
    )
    lo_hi = np.stack([data["band_lo_hz"], data["band_hi_hz"]], axis=1)
    machine = 10 ** (data["machine_db"] / 10)

    spec = TapeMachineSpec().at_speed(0.1905)
    tape0 = library.load_tape("SCOTCH111@2")
    al = aligned(spec, tape0, REPO_ROOT / "cache" / "tape")

    # The 3% level: THD rises with drive.
    lo, hi = 0.0, 18.0
    for _ in range(14):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if tone(spec, tape0, al, mid)[0] < 0.03 else (lo, mid)
    drive3 = 0.5 * (lo + hi)
    thd3, ref_rms = tone(spec, tape0, al, drive3)
    print(f"3% THD at 400 Hz: {drive3:+.2f} dB over 0 VU (THD {100 * thd3:.2f}%)")
    ref = ref_rms**2

    n = int(a.seconds * FS)
    skip = int(0.5 * FS)
    v = spec.speed_m_s
    delay = int(round(spec.head_distance_m / v * FS))

    def grainy(sigma: float, corr: float, volume: float = V0):
        return dataclasses.replace(tape0, noise=TapeNoise(volume, PACKING, sigma, corr))

    # Erased: no bias, silence, the Poisson grain.
    al0 = dataclasses.replace(al, hg_bias=0.0)
    y = print_audio(np.zeros(n), FS, spec, grainy(0.0, 1e-6), al0, noise_seed=SEED)
    erased0 = bands(y[skip:], lo_hi) / ref

    # DC: the 3% tone's rms field at the head (its record network and drive), bias on.
    x = MINUS_18_DBFS_PEAK * np.sin(2 * math.pi * 400.0 * np.arange(int(0.2 * FS)) / FS)
    gain = al.hg_0vu / MINUS_18_DBFS_PEAK * 10 ** (drive3 / 20)
    rb, ra = rec_network(spec, al.rec_trim_tz_s, al.trim_tp_s)
    head = gain * _filter(rb, ra, x, FS)
    hg_dc = float(np.abs(head[len(head) // 2 :]).max()) / math.sqrt(2.0)
    print(f"DC field: {hg_dc:.0f} A/m ({hg_dc / al.hg_0vu:.2f} of the 0 VU peak)")

    def dc_run(t) -> np.ndarray:
        p = stream_params(spec, t, al.hg_bias, head_distance_m=delay * v / FS)
        feed = np.full(n + delay, hg_dc)
        emf = np.zeros(len(feed) + 1)
        emf[1:] = circuitsim.tape_stream_run(json.dumps(p), FS, feed, noise_seed=SEED)
        y = repro_output(emf[delay : delay + n], FS, spec, t, al)
        return bands(y[skip:], lo_hi) / ref

    dc_shot0 = dc_run(grainy(0.0, 1e-6))
    corrs = [0.1e-3, 0.3e-3, 1e-3, 3e-3, 10e-3, 30e-3]
    dc_unit = {}
    for c in corrs:
        dc_unit[c] = dc_run(grainy(1.0, c, 1e-30))
        print(f"  packing field at corr {c * 1e6:6.0f} um done")

    def db(p):
        return 10 * np.log10(p)

    # The particle volume: erased model = erased0 (V / V0) + machine.
    fit_e = (lo_hi[:, 0] >= ERASED_BANDS[0]) & (lo_hi[:, 1] <= ERASED_BANDS[1])
    fit_d = (lo_hi[:, 0] >= DC_BANDS[0]) & (lo_hi[:, 1] <= DC_BANDS[1])

    def err_v(lv):
        r = db(erased0 * 10**lv / V0 + machine) - data["erased_db"]
        return float(np.sum(r[fit_e] ** 2))

    grid = np.linspace(-24, -16, 801)
    lv = grid[int(np.argmin([err_v(g) for g in grid]))]
    volume = 10**lv
    erased_rms = math.sqrt(err_v(lv) / fit_e.sum())
    print(f"particle volume {volume:.3g} m^3 (packing {PACKING}), erased rms {erased_rms:.2f} dB")

    # The packing field: DC model = dc_shot0 (V / V0) + sigma^2 dc_unit(corr) + machine.
    best = None
    for c in corrs:
        for ls in np.linspace(-4, 0, 401):
            m = dc_shot0 * volume / V0 + (10**ls) ** 2 * dc_unit[c] + machine
            e = float(np.sum(((db(m) - data["dc_3pct_db"])[fit_d]) ** 2))
            if best is None or e < best[0]:
                best = (e, c, 10**ls)
    e, corr, sigma = best
    dc_rms = math.sqrt(e / fit_d.sum())
    print(f"packing sigma {sigma:.3g}, corr {corr * 1e6:.0f} um, DC rms {dc_rms:.2f} dB")

    model_erased = db(erased0 * volume / V0 + machine)
    model_dc = db(dc_shot0 * volume / V0 + sigma**2 * dc_unit[corr] + machine)
    report = {
        "machine": "the first print's at 7.5 ips (varimu.devices.tape_machine), NAB playback",
        "drive_3pct_db": drive3,
        "dc_field_a_m": hg_dc,
        "packing": PACKING,
        "particle_volume_m3": volume,
        "packing_sigma": sigma,
        "packing_corr_m": corr,
        "erased_rms_db": erased_rms,
        "dc_rms_db": dc_rms,
        "erased_fit_bands_hz": list(ERASED_BANDS),
        "dc_fit_bands_hz": list(DC_BANDS),
        "bands_hz": lo_hi.tolist(),
        "erased_db": {"data": data["erased_db"].tolist(), "model": model_erased.tolist()},
        "dc_3pct_db": {"data": data["dc_3pct_db"].tolist(), "model": model_dc.tolist()},
        "machine_db": data["machine_db"].tolist(),
        "tape_only_erased_db": db(erased0 * volume / V0).tolist(),
        "dc_unit_by_corr": {str(c): db(dc_unit[c]).tolist() for c in corrs},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "noise_fit.json").write_text(json.dumps(report, indent=1))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(x, data["erased_db"], "o", color="C0", label="bulk erased (No. 34 Fig. 3)")
    ax.plot(x, model_erased, "-", color="C0", label="model + machine noise")
    ax.plot(x, data["dc_3pct_db"], "s", color="C1", label="DC at the 3% level (Fig. 2)")
    ax.plot(x, model_dc, "-", color="C1", label="model + machine noise")
    ax.plot(x, data["machine_db"], ":", color="0.5", label="machine noise (Fig. 3)")
    ax.set_xticks(x, [f"{int(a)}-{int(b)}" for a, b in lo_hi], rotation=30, fontsize=8)
    ax.set_ylabel("dB below the 3% distortion level")
    ax.set_title(
        f"Scotch 111 at 7.5 ips: particles {volume:.2g} m3, packing {PACKING}, "
        f"field {sigma:.2g} over {corr * 1e6:.0f} um",
        fontsize=9,
    )
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "noise_fit.png", dpi=120)
    print(f"-> {OUT / 'noise_fit.json'}, noise_fit.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
