"""The Rhodes's 73 keys side by side (docs/RHODES_PLAN.md, RH2: "the keyboard's pitch and
decay across the range are plausible against published measurements"). Writes
reports/rhodes/keyboard/: keyboard.png, summary.json.

Per key, from the fits (varimu/rhodes/spec.py): the fundamental against the note (cents),
its exact damped Q against Shear's measurements, the bar alone (clamped) against the note,
the struck bar's resonance on its mount against Muenster & Pfeifle's, the spring's mass,
the tine's own loss, the released note's Q (the damper). From strikes at velocity 64 and
127 (varimu/rhodes/harp.py's law; the pickup left out): the hammer's contact and the tip's
swing.

    uv run python scripts/rhodes_keyboard_survey.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from varimu.rhodes import beam as bm  # noqa: E402
from varimu.rhodes import (
    harp,  # noqa: E402
    spec,  # noqa: E402
)
from varimu.rhodes import key as ky  # noqa: E402

OUT = Path(__file__).parents[1] / "reports" / "rhodes" / "keyboard"


class _NoFlux:
    y_range_m = (-1.0, 1.0)
    dg_m = np.array([0.0, 1.0])

    def __call__(self, y, dg, dy=0, ddg=0):
        return np.zeros_like(y)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    ff = harp.ff_speed_m_s()
    rows = []
    for n in spec.KEYS_73:
        k = spec.key(n)
        fe = bm.assemble(k.assembly, k.element_m)
        md = bm.modes(fe, count=24)
        row = {
            "key": n,
            "note_hz": k.note_hz,
            "cents": 1200 * np.log2(k.fits["fundamental_hz"] / k.note_hz),
            "q": k.fits["fundamental_q"],
            "q_shear_interp": k.q_target,
            "bar_clamped_over_note": k.fits["tonebar_clamped_hz"] / k.note_hz,
            "bar_mode_hz": float(md.f_hz[bm.mount_mode(fe, md)]),
            "bar_mode_muenster_hz": k.tonebar_f0_hz,
            "spring_g": k.fits["spring_mass_kg"] * 1e3,
            "tine_loss": k.fits["tine_loss"],
            "released_q": bm.damped_q(k.damped, k.note_hz),
        }
        for vel in (64, 127):
            s = ky.strike(k, harp.hammer_speed(vel, ff), duration_s=0.08, flux=_NoFlux())
            row[f"contact_ms_{vel}"] = s.contact_s * 1e3
            row[f"swing_mm_{vel}"] = float(np.max(np.abs(s.tip_m)) * 1e3)
            row[f"contacts_{vel}"] = s.strikes
        rows.append(row)
        print(
            f"key {n}: {row['cents']:+.2f} c, Q {row['q']:.0f} ({row['q_shear_interp']:.0f}), "
            f"contact {row['contact_ms_64']:.1f} ms, swing {row['swing_mm_127']:.1f} mm",
            flush=True,
        )
    keys = np.array([r["key"] for r in rows])

    def col(name):
        return np.array([r[name] for r in rows])

    fig, ax = plt.subplots(2, 3, figsize=(16, 8.5))
    ax[0, 0].plot(keys, col("cents"), "o-", ms=3)
    ax[0, 0].set(xlabel="key", ylabel="cents", title="the fundamental against the note")
    ax[0, 1].semilogy(keys, col("q"), "o-", ms=3, label="model (exact, damped)")
    pts = np.array(spec.load()["anchors"]["q_shear"])
    ax[0, 1].semilogy(49 + 12 * np.log2(pts[:, 0] / 440), pts[:, 1], "kx", ms=8, label="Shear 2011")
    ax[0, 1].semilogy(keys, col("released_q"), "o-", ms=3, label="released (the damper)")
    ax[0, 1].set(xlabel="key", ylabel="Q", title="the fundamental's decay")
    ax[0, 1].legend(fontsize=8)
    ax[0, 2].plot(keys, col("bar_mode_hz"), "o-", ms=3, label="model: the bar's mode on its mount")
    mp = np.array(spec.load()["anchors"]["tonebar_muenster"], float)
    ax[0, 2].plot(mp[:, 0] + 7, mp[:, 2], "kx", ms=8, label="Muenster & Pfeifle")
    ax[0, 2].set(xlabel="key", ylabel="Hz", title="the struck bar's resonance", yscale="log")
    ax[0, 2].legend(fontsize=8)
    ax[1, 0].plot(keys, col("bar_clamped_over_note"), "o-", ms=3)
    ax[1, 0].axhline(1.0, color="k", lw=0.5)
    ax[1, 0].set(xlabel="key", ylabel="ratio", title="the balanced bar alone (clamped) / the note")
    for vel, mk in ((64, "o-"), (127, "s-")):
        ax[1, 1].plot(keys, col(f"contact_ms_{vel}"), mk, ms=3, label=f"velocity {vel}")
        ax[1, 2].plot(keys, col(f"swing_mm_{vel}"), mk, ms=3, label=f"velocity {vel}")
    ax[1, 1].axhline(6.42, color="k", ls="--", label="Muenster & Pfeifle (average)")
    ax[1, 1].set(xlabel="key", ylabel="ms", title="the hammer's first contact")
    ax[1, 1].legend(fontsize=8)
    ax[1, 2].set(xlabel="key", ylabel="mm", title="the tip's largest swing", yscale="log")
    ax[1, 2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "keyboard.png", dpi=100)
    plt.close(fig)
    (OUT / "summary.json").write_text(
        json.dumps({"ff_speed_m_s": ff, "keys": rows}, indent=1, default=float), encoding="utf-8"
    )
    print(f"done in {time.time() - t0:.0f} s -> {OUT}")


if __name__ == "__main__":
    main()
