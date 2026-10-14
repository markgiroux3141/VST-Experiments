"""Tabulated triodes: Python reference vs analytic model vs ngspice table2D."""

import numpy as np
import pytest

from varimu.circuit.netlist import tube_instance
from varimu.devices.library import load_device
from varimu.devices.table import GRIDS, bilinear, cached_table, interpolation_error, table_subckt
from varimu.sim import ngspice


@pytest.mark.parametrize(
    "name,region,limit",
    [
        ("6386", ((-80.0, 0.0), (50.0, 450.0)), 3e-5),
        ("12AX7", ((-4.0, 0.0), (50.0, 300.0)), 1e-4),
        ("12BH7", ((-15.0, 0.0), (20.0, 300.0)), 2e-4),
    ],
)
def test_table_interpolation_error_is_small(name, region, limit):
    t = load_device(name)
    assert interpolation_error(t, GRIDS[name], *region) < limit


def test_bilinear_is_exact_on_grid_points():
    t = load_device("12BH7")
    g = GRIDS["12BH7"]
    vg, vp = g.vg[::37], g.vp[::23]
    G, P = np.meshgrid(vg, vp)
    np.testing.assert_allclose(bilinear(t, g, G, P), t.ip(G, P), rtol=1e-12, atol=1e-18)


def test_cached_table_depends_on_the_model(tmp_path):
    base = load_device("6386")
    a = cached_table(tube_instance(base, "x", n_parallel=4), GRIDS["6386"], tmp_path)
    b = cached_table(tube_instance(base, "x", n_parallel=4), GRIDS["6386"], tmp_path)
    c = cached_table(
        tube_instance(base, "x", n_parallel=4, emission_scale=0.9), GRIDS["6386"], tmp_path
    )
    assert a == b and a != c and a.exists() and c.exists()


def _have_ngspice():
    try:
        ngspice.find_ngspice()
        return True
    except ngspice.SimulatorNotFound:
        return False


@pytest.mark.skipif(not _have_ngspice(), reason="ngspice not available")
def test_spice_table_agrees_with_python_bilinear_reference(tmp_path):
    """One .op with an independent instance per bias point (see test_spice_agreement.py)."""
    import shutil
    import subprocess

    t = tube_instance(load_device("6386"), "6386_t", n_parallel=4, emission_scale=0.95)
    g = GRIDS["6386"]
    shutil.copyfile(cached_table(t, g, tmp_path / "tables"), tmp_path / "t.tab")
    # Off-grid points, including some inside the coarse regions.
    pts = [(vg, vp) for vg in (-120.3, -55.55, -17.33, -4.21, -0.07) for vp in (15.3, 99.9, 240.5)]
    lines = ["* table agreement", table_subckt(t, "t.tab")]
    for k, (vg, vp) in enumerate(pts):
        lines += [
            f"vp{k} p{k} 0 dc {vp}",
            f"vg{k} g{k} 0 dc {vg}",
            f"x{k} p{k} g{k} 0 {t.subckt_name}",
        ]
    vecs = " ".join(f"i(vp{k})" for k in range(len(pts)))
    lines += [".control", "set numdgt=12", "op", f"print {vecs}", "quit", ".endc", ".end"]
    (tmp_path / "in.cir").write_text("\n".join(lines))
    out = subprocess.run(
        [str(ngspice.find_ngspice()), "-b", "in.cir"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout
    got = {
        m.group(1): float(m.group(2))
        for m in (
            __import__("re").match(r"\s*i\((vp\d+)\)\s*=\s*(\S+)", line)
            for line in out.splitlines()
        )
        if m
    }
    ip = np.array([-got[f"vp{k}"] for k in range(len(pts))])
    vg, vp = np.array(pts).T
    ref = bilinear(t, g, vg, vp)
    # Plate current plus the grid conduction model is all that flows; grid is negative here.
    np.testing.assert_allclose(ip, ref, rtol=1e-6, atol=1e-11)
    # And the table stays close to the analytic model: the error is documented as a
    # fraction of the largest current in the region (see varimu.devices.table).
    exact = t.ip(vg, vp)
    assert np.max(np.abs(ip - exact)) < 5e-5 * np.max(exact)
