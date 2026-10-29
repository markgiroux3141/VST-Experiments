"""Review plots for device fits (written by `varimu fit-devices`)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from varimu.devices.fit import Data6386, cascode_gm
from varimu.devices.pentode import Pentode
from varimu.devices.triode import Triode

# Review plots of the Koren / Child-law fits: digitized points in neutral ink, the model
# as one blue ramp (light to dark along the family's parameter), a second source's
# points in orange; curve values labelled at their ends.
INK, INK2, DOT = "#0b0b0b", "#52514e", "#52514e"
SOURCE2 = "#eb6834"


def _ramp(n):
    import matplotlib

    return [matplotlib.colormaps["Blues"](v) for v in np.linspace(0.45, 1.0, n)]


def _style(a, title, xlabel, ylabel):
    a.set_title(title, color=INK, fontsize=10, loc="left")
    a.set_xlabel(xlabel, color=INK2)
    a.set_ylabel(ylabel, color=INK2)
    a.grid(alpha=0.25)
    a.tick_params(colors=INK2)
    for s in ("top", "right"):
        a.spines[s].set_visible(False)


def _family(
    a,
    data,
    model,
    key_col,
    x_col,
    y_col,
    xs_fn,
    label_fmt,
    *,
    scale=1e3,
    extra=None,
    end_label=True,
):
    """data rows grouped by column key_col; model(key, x) evaluated on xs_fn(key)."""
    keys = sorted(np.unique(data[:, key_col]), reverse=True)
    for k, c in zip(keys, _ramp(len(keys)), strict=True):
        d = data[data[:, key_col] == k]
        a.plot(d[:, x_col], d[:, y_col] * scale, "o", ms=2.5, color=DOT, zorder=3)
        x = xs_fn(k, d)
        y = model(k, x) * scale
        a.plot(x, y, lw=1.5, color=c, zorder=2)
        if end_label:
            a.annotate(
                label_fmt(k),
                (x[-1], y[-1]),
                xytext=(3, 0),
                textcoords="offset points",
                fontsize=7,
                color=INK2,
                va="center",
            )
    if extra is not None:
        extra(a)
    from matplotlib.lines import Line2D

    handles = [
        Line2D([], [], ls="none", marker="o", ms=4, color=DOT, label="sheet (digitized)"),
        Line2D([], [], lw=1.5, color=_ramp(3)[1], label="model"),
    ]
    if extra is not None:
        handles.append(
            Line2D([], [], ls="none", marker="s", ms=4, color=SOURCE2, label="second source")
        )
    a.legend(handles=handles, fontsize=7, loc="upper left", frameon=False)


def _save(fig, path: Path, title: str) -> None:
    import matplotlib.pyplot as plt

    fig.suptitle(title, color=INK, fontsize=11)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=90, facecolor="white")
    plt.close(fig)


def plot_koren_triode(
    t: Triode, data: np.ndarray, data2: np.ndarray | None, published: list, path: Path, title: str
) -> None:
    """Plate curves (columns vg, vp, ip): the fit's data, a second source (data2) and the
    published operating points (dicts with vp_v, vg_v, ip_a, label)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(13, 5.5))

    def xs(vg, d):
        return np.linspace(0, d[:, 1].max(), 200)

    def extra(a):
        if data2 is not None:
            a.plot(data2[:, 1], data2[:, 2] * 1e3, "s", ms=2.5, color=SOURCE2, zorder=1)
        for p in published:
            a.plot(p["vp_v"], p["ip_a"] * 1e3, "x", ms=9, mew=2, color=INK, zorder=4)
            a.annotate(
                p["label"],
                (p["vp_v"], p["ip_a"] * 1e3),
                xytext=(-8, 10),
                textcoords="offset points",
                fontsize=7,
                color=INK,
                ha="right",
            )

    def grid_label(v):
        return f"{v:+g} V" if v else "0 V"

    _family(ax[0], data, lambda vg, x: t.ip(vg, x), 0, 1, 2, xs, grid_label, extra=extra)
    _style(ax[0], "Plate characteristics (grid voltage per curve)", "Vp (V)", "Ip (mA)")
    ax[0].set(xlim=(0, 320), ylim=(0, 10.5))
    # log view: the toes, where a guitar preamp's small currents live
    _family(ax[1], data, lambda vg, x: t.ip(vg, x), 0, 1, 2, xs, grid_label, extra=extra)
    _style(ax[1], "Same, log current", "Vp (V)", "Ip (mA)")
    ax[1].set(xlim=(0, 320), ylim=(0.03, 12), yscale="log")
    _save(fig, path, title)


def plot_koren_pentode(
    p: Pentode,
    plate: np.ndarray,
    plate_vg2: np.ndarray,
    transfer: np.ndarray,
    screen: np.ndarray,
    published: list,
    path: Path,
    title: str,
) -> None:
    """The 6V6GT's four figures: plate (vg2, vg1, va, ia) at one screen voltage, plate at
    Vg1 = 0 per screen voltage, transfer (va, vg2, vg1, ia), screen current (va, vg1,
    vg2, ig2)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 2, figsize=(13, 10))
    (a_pl, a_vg2), (a_tr, a_sc) = ax

    def va_axis(k, d):
        return np.linspace(0, 400, 300)

    def marks(a):
        for q in published:
            a.plot(q["va_v"], q["ia_a"] * 1e3, "x", ms=9, mew=2, color=INK, zorder=4)
            a.annotate(
                q["label"],
                (q["va_v"], q["ia_a"] * 1e3),
                xytext=(6, 6),
                textcoords="offset points",
                fontsize=7,
                color=INK,
            )

    vg2_0 = plate[0, 0]
    _family(a_pl, plate, lambda vg1, x: p.ip(vg1, vg2_0, x), 1, 2, 3, va_axis, lambda v: f"{v:g} V")
    marks(a_pl)
    _style(a_pl, f"Plate characteristics, Vg2 = {vg2_0:g} V (Vg1 per curve)", "Va (V)", "Ia (mA)")
    a_pl.set(xlim=(0, 430), ylim=(0, 130))

    _family(
        a_vg2, plate_vg2, lambda vg2, x: p.ip(0.0, vg2, x), 0, 2, 3, va_axis, lambda v: f"Vg2 {v:g}"
    )
    _style(a_vg2, "Plate characteristics, Vg1 = 0 (Vg2 per curve)", "Va (V)", "Ia (mA)")
    a_vg2.set(xlim=(0, 450), ylim=(0, 130))

    va_t = transfer[0, 0]
    _family(
        a_tr,
        transfer,
        lambda vg2, x: p.ip(x, vg2, va_t),
        1,
        2,
        3,
        lambda k, d: np.linspace(d[:, 2].min() - 2, 0, 200),
        lambda v: f"Vg2 {v:g}",
    )
    _style(a_tr, f"Transfer, Va = {va_t:g} V", "Vg1 (V)", "Ia (mA)")
    a_tr.set(xlim=(-40, 3), ylim=(0, 120))

    _family(
        a_sc,
        screen,
        lambda vg2, x: p.ig2(x, vg2),
        2,
        1,
        3,
        lambda k, d: np.linspace(d[:, 1].min() - 2, 0, 200),
        lambda v: f"Vg2 {v:g}",
    )
    _style(
        a_sc,
        f"Screen current, Va = {screen[0, 0]:g} V (Koren's Ig2 ignores Va)",
        "Vg1 (V)",
        "Ig2 (mA)",
    )
    a_sc.set(xlim=(-40, 3), ylim=(0, 14))
    _save(fig, path, title)


def plot_vacuum_diode(d, data: np.ndarray, published: list, path: Path, title: str) -> None:
    """Plate curve (columns va, ia) and the Child-law fit, linear and log."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    v = np.linspace(0.01, data[:, 0].max() * 1.05, 300)
    for a, log in zip(ax, (False, True), strict=True):
        a.plot(
            data[:, 0], data[:, 1] * 1e3, "o", ms=3, color=DOT, label="sheet (digitized)", zorder=3
        )
        a.plot(v, d.i(v) * 1e3, lw=1.5, color=_ramp(3)[1], label="model (Child law)")
        for q in published:
            a.plot(q["va_v"], q["ia_a"] * 1e3, "x", ms=9, mew=2, color=INK, zorder=4)
            a.annotate(
                q["label"],
                (q["va_v"], q["ia_a"] * 1e3),
                xytext=(6, -12),
                textcoords="offset points",
                fontsize=7,
                color=INK,
            )
        a.legend(fontsize=7, loc="upper left", frameon=False)
        if log:
            _style(a, "Log-log: slope 1.5 is Child's law", "Va (V)", "Ia (mA)")
            a.set(xscale="log", yscale="log", xlim=(3, 150), ylim=(1, 600))
        else:
            _style(a, "Plate characteristic, each section", "Va (V)", "Ia (mA)")
            a.set(xlim=(0, 130), ylim=(0, 480))
    _save(fig, path, title)


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
