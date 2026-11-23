"""A simulated head against its measured HRTFs (docs/BINAURAL_PLAN.md, B2): HUTUBS subjects,
whose meshes and measured (and Mesh2HRTF-simulated) HRIRs are published together
(data/hrtf/hutubs/README.md). Per subject: our simulation through crates/roomsim's body
solver, then for every measured direction the magnitude difference in auditory bands (ERB-
spaced, 0.2-16 kHz), the ITD and the ILD, against the measured set and against HUTUBS' own
BEM simulation (its "simulated" set: another solver on the same mesh). Plots and a summary
-> reports/binaural/validate/<subject>/.

    uv run --extra fast --extra binaural python scripts/binaural_validate.py [--subject pp1 ...]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from varimu.binaural import sofa
from varimu.binaural.hrtf import simulate
from varimu.binaural.mesh import read_ply

ROOT = Path(__file__).resolve().parents[1]
HUTUBS = ROOT / "data" / "hrtf" / "hutubs"
OUT = ROOT / "reports" / "binaural" / "validate"


def erb_bands(lo=200.0, hi=16000.0, n=32):
    e = lambda f: 21.4 * np.log10(1 + 0.00437 * f)  # noqa: E731
    ei = lambda x: (10 ** (x / 21.4) - 1) / 0.00437  # noqa: E731
    edges = ei(np.linspace(e(lo), e(hi), n + 1))
    return edges


def band_db(f, H, edges):
    """Energy in each band, dB (..., bands)."""
    out = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        s = (f >= a) & (f < b)
        out.append(10 * np.log10(np.mean(np.abs(H[..., s]) ** 2, axis=-1) + 1e-20))
    return np.stack(out, axis=-1)


def itd_us(f, H):
    """ITD (left minus right arrival, us) from the interaural phase's slope 200-1500 Hz
    (the low-frequency ITD; a left source gives a negative value)."""
    s = (f >= 200) & (f <= 1500)
    ph = np.unwrap(np.angle(H[0][..., s] / H[1][..., s]), axis=-1)
    w = 2 * np.pi * f[s]
    slope = (ph * w).sum(-1) / (w * w).sum()
    return slope * 1e6  # phase L/R = -w (tL - tR) -> tL - tR = -slope


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--subject", nargs="*", default=["pp1"], help="'all': every mesh")
    args = ap.parse_args(argv)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    edges = erb_bands()
    centres = np.sqrt(edges[:-1] * edges[1:])
    summary = {}
    subjects = args.subject
    if subjects == ["all"]:
        subjects = sorted(
            (p.name.split("_")[0] for p in (HUTUBS / "3D head meshes").glob("pp*_3DheadMesh.ply")),
            key=lambda s: int(s[2:]),
        )
    for subj in subjects:
        mesh = read_ply(HUTUBS / "3D head meshes" / f"{subj}_3DheadMesh.ply")
        h = simulate(mesh, f"hutubs_{subj}")
        meas = sofa.read(HUTUBS / "HRIRs" / f"{subj}_HRIRs_measured.sofa")
        bem = sofa.read(HUTUBS / "HRIRs" / f"{subj}_HRIRs_simulated.sofa")
        res = {}
        for label, ref in (("measured", meas), ("hutubs_bem", bem)):
            fr, Hr = ref.tf(1024)
            Hr = np.moveaxis(Hr, 1, 0)  # (2, M, F)
            d = float(ref.distance_m[0])
            Hs = h.tf(ref.az_deg, ref.el_deg, distance_m=d)
            # our transfer functions on the reference's bins
            Hs_i = np.stack(
                [
                    np.stack(
                        [
                            np.interp(fr, h.f_hz, Hs[e, m].real)
                            + 1j * np.interp(fr, h.f_hz, Hs[e, m].imag)
                            for m in range(Hs.shape[1])
                        ]
                    )
                    for e in range(2)
                ]
            )
            bs = band_db(fr, Hs_i, edges)
            br = band_db(fr, Hr, edges)
            # level: the references' absolute calibration is their own; align the
            # direction-averaged level per band (a constant equalization, as measurements are
            # diffuse-field compared)
            diff = bs - br
            offset = diff.mean(axis=(0, 1))
            diff_eq = diff - offset
            itd_s, itd_r = itd_us(fr, Hs_i), itd_us(fr, Hr)
            ild_s = bs[0] - bs[1]
            ild_r = br[0] - br[1]
            res[label] = {
                "lsd_db": float(np.sqrt((diff_eq**2).mean())),
                "lsd_db_raw": float(np.sqrt((diff**2).mean())),
                "lsd_db_by_band": np.sqrt((diff_eq**2).mean(axis=(0, 1))).round(2).tolist(),
                "band_offset_db": offset.round(2).tolist(),
                "itd_rms_us": float(np.sqrt(((itd_s - itd_r) ** 2).mean())),
                "ild_rms_db": float(np.sqrt(((ild_s - ild_r) ** 2).mean())),
            }
            od = OUT / subj
            od.mkdir(parents=True, exist_ok=True)
            # horizontal plane, left ear
            hp = np.flatnonzero(np.abs(ref.el_deg) < 1e-6)
            hp = hp[np.argsort(ref.az_deg[hp])]
            fig, ax = plt.subplots(1, 2, figsize=(12, 4.5), sharey=True)
            for a, B, t in ((ax[0], br[0, hp], label), (ax[1], bs[0, hp], "ours")):
                im = a.pcolormesh(
                    centres / 1000,
                    ref.az_deg[hp],
                    B,
                    shading="nearest",
                    vmin=-25,
                    vmax=15,
                    cmap="magma",
                )
                a.set_xscale("log")
                a.set_xlabel("kHz")
                a.set_title(f"{subj} left ear, horizontal plane: {t}")
            ax[0].set_ylabel("azimuth (deg, 90 = left)")
            fig.colorbar(im, ax=ax)
            fig.savefig(od / f"horizontal_{label}.png", dpi=110)
            plt.close(fig)
            # median plane (front, up, back): the pinna's cues
            fig, ax = plt.subplots(figsize=(8, 4.5))
            for az, el, col in (
                (0, 0, "C0"),
                (180, 0, "C3"),
                (0, 45, "C2"),
                (180, 45, "C1"),
                (0, -30, "C4"),
            ):
                m = int(
                    np.argmin(
                        np.abs(((ref.az_deg - az + 180) % 360) - 180) + np.abs(ref.el_deg - el)
                    )
                )
                ax.semilogx(centres, br[0, m], col, lw=1, ls="--")
                ax.semilogx(
                    centres,
                    bs[0, m] - offset,
                    col,
                    lw=1.6,
                    label=f"az {ref.az_deg[m]:.0f} el {ref.el_deg[m]:.0f}",
                )
            ax.set_xlabel("Hz")
            ax.set_ylabel("dB (left ear)")
            ax.set_title(f"{subj}: median plane, ours (solid, equalized) vs {label} (dashed)")
            ax.legend(fontsize=8)
            ax.grid(alpha=0.3)
            fig.savefig(od / f"median_{label}.png", dpi=110)
            plt.close(fig)
        summary[subj] = res
        print(subj, json.dumps(res, indent=1))
        (OUT / subj / "summary.json").write_text(json.dumps(res, indent=1))
    if len(summary) > 1:
        agg = {
            lab: {
                k: float(np.median([summary[s][lab][k] for s in summary]))
                for k in ("lsd_db", "itd_rms_us", "ild_rms_db")
            }
            for lab in ("measured", "hutubs_bem")
        }
        (OUT / "summary_all.json").write_text(
            json.dumps({"median": agg, "subjects": summary}, indent=1)
        )
        print("median over subjects:", json.dumps(agg, indent=1))


if __name__ == "__main__":
    main()
