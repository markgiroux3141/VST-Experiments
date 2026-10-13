"""Review plots for device fits (written by `varimu fit-devices`)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from varimu.devices.fit import Data6386, cascode_gm
from varimu.devices.triode import Triode


def plot_6386(t: Triode, data: Data6386, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 2, figsize=(13, 10))
    (a_plate, a_tr), (a_gm, a_law) = ax

    for vg in np.unique(data.plate[:, 0]):
        d = data.plate[data.plate[:, 0] == vg]
        a_plate.plot(d[:, 1], d[:, 2] * 1e3, "k.", ms=1.5)
        vp = np.linspace(0, 400, 200)
        a_plate.plot(vp, t.ip(vg, vp) * 1e3, lw=1, label=f"{vg:g} V")
    a_plate.set(
        xlim=(0, 400),
        ylim=(0, 36),
        xlabel="Vp (V)",
        ylabel="Ip (mA)",
        title="Plate characteristics (ET-T1113 p.5)",
    )
    a_plate.legend(fontsize=7, ncol=3, title="Vg")

    for vp in np.unique(data.transfer[:, 0]):
        d = data.transfer[data.transfer[:, 0] == vp]
        a_tr.plot(d[:, 1], d[:, 2] * 1e3, "k.", ms=1.5)
        vg = np.linspace(-56, 0, 200)
        a_tr.plot(vg, t.ip(vg, vp) * 1e3, lw=1, label=f"{vp:g} V")
    a_tr.set(
        xlim=(-56, 0),
        ylim=(0, 40),
        xlabel="Vg (V)",
        ylabel="Ip (mA)",
        title="Transfer characteristics (p.4)",
    )
    a_tr.legend(fontsize=8, title="Vp")

    for e in np.unique(data.cascode_gm[:, 0]):
        d = data.cascode_gm[data.cascode_gm[:, 0] == e]
        a_gm.semilogy(d[:, 1], d[:, 2] * 1e6, "k.", ms=1.5)
        vg = np.linspace(-60, 0, 300)
        a_gm.semilogy(vg, cascode_gm(t.ip, vg, e) * 1e6, lw=1, label=f"{e:g} V")
    a_gm.set(
        xlim=(-60, 0),
        ylim=(10, 1e4),
        xlabel="Vg1 (V)",
        ylabel="gm (umho)",
        title="Cascode gm vs bias (p.3): the compression law",
    )
    a_gm.legend(fontsize=8, title="Ecc2")

    vg = np.linspace(-60, 0, 400)
    for vp in (100, 150, 200, 250):
        a_law.semilogy(vg, t.gm(vg, vp) * 1e6, lw=1, label=f"Vp = {vp} V")
    a_law.plot([-16], [100], "kx", ms=8, label="sheet: 100 umho @ -16 V, Vp 100")
    a_law.set(
        xlim=(-60, 0),
        ylim=(1, 1e4),
        xlabel="Vg (V)",
        ylabel="gm (umho)",
        title="Model: single-section gm vs bias",
    )
    a_law.legend(fontsize=8)

    for a in ax.flat:
        a.grid(alpha=0.3, which="both")
    fig.suptitle("6386 variable-mu model vs GE ET-T1113 (dots: digitized sheet)")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=90)
    plt.close(fig)
