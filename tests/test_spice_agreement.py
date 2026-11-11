"""Python reference models vs. their generated SPICE subcircuits (ngspice).

Skipped when ngspice isn't installed (see CLAUDE.md for the portable install).
"""

import numpy as np
import pytest

from varimu.devices.library import load_device
from varimu.sim import ngspice

try:
    ngspice.find_ngspice()
except ngspice.SimulatorNotFound:
    pytest.skip("ngspice not available", allow_module_level=True)

# Everything is solved as one `.op` with an independent instance per bias point.
# A DC *sweep* would not test the equations. ngspice reports a behavioral source's
# value linearized from the previous sweep point and accepts it after one
# iteration (the error scales with step^2; see CLAUDE.md, known issues). The
# initialization modes of a fresh operating point evaluate the expressions exactly.
# SPICE also adds GMIN (1e-12 S) across junctions, hence the small absolute tolerance.
# RTOL is set by wrdata's output precision (10 significant digits).
ATOL, RTOL = 1e-11, 2e-8
TIGHT = "reltol=1e-12 abstol=1e-16 vntol=1e-13"


def _op(netlist_lines, vectors):
    r = ngspice.run("\n".join(netlist_lines), "op", vectors, options=TIGHT)
    return {v: float(r[v][0]) for v in vectors}


@pytest.mark.parametrize(
    "name", ["6386", "12AX7", "12BH7", "12AY7", "VF14T@1", "E88CC@1", "AC701@1"]
)
def test_triode_plate_and_grid_current_agree(name):
    t = load_device(name)
    pts = [(vg, vp) for vg in (-70, -40, -20, -10, -4, -1, 0, 0.5) for vp in range(0, 401, 25)]
    lines = [t.subckt()]
    for k, (vg, vp) in enumerate(pts):
        lines += [
            f"vp{k} p{k} 0 dc {vp}",
            f"vg{k} g{k} 0 dc {vg}",
            f"x{k} p{k} g{k} 0 {t.subckt_name}",
        ]
    r = _op(lines, [f"i(vp{k})" for k in range(len(pts))] + [f"i(vg{k})" for k in range(len(pts))])
    vg, vp = np.array(pts, float).T
    ip = -np.array([r[f"i(vp{k})"] for k in range(len(pts))])
    ig = -np.array([r[f"i(vg{k})"] for k in range(len(pts))])
    np.testing.assert_allclose(ip, t.ip(vg, vp), rtol=RTOL, atol=ATOL, err_msg=f"{name} Ip")
    np.testing.assert_allclose(ig, t.ig(vg), rtol=RTOL, atol=ATOL, err_msg=f"{name} Ig")


POWER = ((-60, -40, -25, -15, -5), (150, 250))
SMALL = ((-6, -4, -2.5, -1.5, -0.5, 0), (40, 90, 160))  # signal pentodes, low screens


@pytest.mark.parametrize(
    "name,grid",
    [("6973", POWER), ("6V6GT", POWER), ("EF804S@1", SMALL), ("E83F@1", SMALL), ("EF86@1", SMALL)],
)
def test_pentode_agrees(name, grid):
    """Koren's screen law (6973, 6V6GT) and the "e1" law (EF804S, E83F, EF86)."""
    p = load_device(name)
    pts = [(vg, vs, vp) for vg in grid[0] for vs in grid[1] for vp in range(0, 401, 25)]
    lines = [p.subckt()]
    for k, (vg, vs, vp) in enumerate(pts):
        lines += [
            f"vp{k} p{k} 0 dc {vp}",
            f"vs{k} s{k} 0 dc {vs}",
            f"vg{k} g{k} 0 dc {vg}",
            f"x{k} p{k} s{k} g{k} 0 {p.subckt_name}",
        ]
    r = _op(lines, [f"i(vp{k})" for k in range(len(pts))] + [f"i(vs{k})" for k in range(len(pts))])
    vg, vs, vp = np.array(pts, float).T
    ip = -np.array([r[f"i(vp{k})"] for k in range(len(pts))])
    is2 = -np.array([r[f"i(vs{k})"] for k in range(len(pts))])
    np.testing.assert_allclose(ip, p.ip(vg, vs, vp), rtol=RTOL, atol=ATOL)
    np.testing.assert_allclose(is2, p.ig2(vg, vs), rtol=RTOL, atol=ATOL)


@pytest.mark.parametrize(
    "name,vmin,vmax",
    [
        ("GZ34", -5.0, 60.0),
        ("5Y3GT", -5.0, 150.0),
        ("SI_RECTIFIER", -5.0, 1.2),
        # 18 cells in series (n ~45): SPICE's cubic region starts at -3 n Vt ~ -3.5 V,
        # where the stack's large is puts the difference at ~4e-8 A (reverse leakage isn't
        # modeled anyway), so from -3.4 V.
        ("B450C80@1", -3.4, 40.0),
    ],
)
def test_diodes_agree(name, vmin, vmax):
    d = load_device(name)
    v = np.linspace(vmin, vmax, 41)
    behavioral = hasattr(d, "subckt")
    lines = [d.subckt() if behavioral else d.model_card()]
    for k, vk in enumerate(v):
        dev = f"x{k} a{k} 0 {d.subckt_name}" if behavioral else f"d{k} a{k} 0 {d.model_name}"
        lines += [f"va{k} a{k} 0 dc {vk}", dev]
    r = _op(lines, [f"i(va{k})" for k in range(len(v))])
    i = -np.array([r[f"i(va{k})"] for k in range(len(v))])
    # Below -3*n*Vt, SPICE's D model replaces the exponential with a cubic
    # approximation (SPICE3 diode reverse region). That differs from pure Shockley
    # by ~2e-11 A, which is physically irrelevant, hence the looser absolute tolerance.
    np.testing.assert_allclose(i, d.i(v), rtol=1e-7, atol=5e-11)


def test_lamp_agrees():
    """The lamp's filament current and dT/dt (its thermal port's current), cold to past its
    rating, both polarities, and clamped below and above the fits' range."""
    d = load_device("LAMP327@1")
    volts = (-30.0, -2.0, 0.0, 0.4, 5.0, 28.0)
    pts = [(v, u) for v in volts for u in (-150, 0, 120, 900, 2000, 3300)]
    lines = [d.subckt()]
    for k, (v, u) in enumerate(pts):
        lines += [
            f"va{k} a{k} 0 dc {v}",
            f"vt{k} t{k} 0 dc {u}",
            f"x{k} a{k} t{k} 0 {d.subckt_name}",
        ]
    r = _op(lines, [f"i(va{k})" for k in range(len(pts))] + [f"i(vt{k})" for k in range(len(pts))])
    v, u = np.array(pts, float).T
    ia, it = d.currents(v, u)
    got_a = -np.array([r[f"i(va{k})"] for k in range(len(pts))])
    got_t = -np.array([r[f"i(vt{k})"] for k in range(len(pts))])
    np.testing.assert_allclose(got_a, ia, rtol=RTOL, atol=ATOL, err_msg="filament current")
    # At the rated point heat in and out cancel (~3e4 K/s each): the floor is wrdata's 10
    # digits of those terms.
    np.testing.assert_allclose(got_t, it, rtol=RTOL, atol=1e-4, err_msg="dT/dt")


def test_optocoupler_agrees():
    """The optocoupler's four port currents (the LED's both ends, the cell's state, the cell):
    the LED off, at its knee, bright and past its tangent's start; the state dark to bright
    and negative (Newton's excursions); the cell both ways."""
    d = load_device("VTL5C1@1")
    pts = [
        (vl + lk, lk, u, vr)
        for vl in (-2.0, 0.0, 1.45, 1.6, 2.6)
        for lk in (0.0, 4.0)
        for u in (-0.3, 0.0, 0.02, 2.0)
        for vr in (-6.0, 0.5)
    ]
    lines = [d.subckt()]
    for k, (v0, v1, u, vr) in enumerate(pts):
        lines += [
            f"vla{k} la{k} 0 dc {v0}",
            f"vlk{k} lk{k} 0 dc {v1}",
            f"vs{k} s{k} 0 dc {u}",
            f"vra{k} ra{k} 0 dc {vr}",
            f"x{k} la{k} lk{k} s{k} ra{k} 0 {d.subckt_name}",
        ]
    pins = ("vla", "vlk", "vs", "vra")
    r = _op(lines, [f"i({p}{k})" for k in range(len(pts)) for p in pins])
    want = np.array([d.currents(p) for p in pts])
    got = -np.array([[r[f"i({p}{k})"] for p in pins] for k in range(len(pts))])
    for j, what in enumerate(("LED (la)", "LED (lk)", "state", "cell")):
        np.testing.assert_allclose(got[:, j], want[:, j], rtol=RTOL, atol=ATOL, err_msg=what)


def test_photocell_agrees():
    """The photocell's four port currents (none at the lamp's two sensing pins, the cell's
    state, the cell): the lamp below the floor, glowing, at its rating and past 2856 K, its
    reference pin off ground; the state dark to bright and negative; the cell both ways."""
    import dataclasses

    d = dataclasses.replace(load_device("PDVP9203@1"), lux=40.0)
    pts = [
        (dt + tb, tb, u, vr)
        for dt in (-250.0, 900.0, 2000.0, 3100.0)
        for tb in (0.0, 21.0)
        for u in (-0.3, 0.0, 2e3, 5e4)
        for vr in (-6.0, 0.5)
    ]
    lines = [d.subckt()]
    for k, (vt, vtb, u, vr) in enumerate(pts):
        lines += [
            f"vt{k} t{k} 0 dc {vt}",
            f"vtb{k} tb{k} 0 dc {vtb}",
            f"vs{k} s{k} 0 dc {u}",
            f"vra{k} ra{k} 0 dc {vr}",
            f"x{k} t{k} tb{k} s{k} ra{k} 0 {d.subckt_name}",
        ]
    pins = ("vt", "vtb", "vs", "vra")
    r = _op(lines, [f"i({p}{k})" for k in range(len(pts)) for p in pins])
    want = np.array([d.currents(p) for p in pts])
    got = -np.array([[r[f"i({p}{k})"] for p in pins] for k in range(len(pts))])
    for j, what in enumerate(("lamp (t)", "lamp (tb)", "state", "cell")):
        np.testing.assert_allclose(got[:, j], want[:, j], rtol=RTOL, atol=ATOL, err_msg=what)


def test_carbon_agrees():
    """A carbon button's current (into a, out of b; none into its force pin): pulled off,
    through its softened zero force, and pressed."""
    d = load_device("CARBON_BUTTON@1")
    pts = [
        (va, vb, f) for va in (-2.0, 0.3) for vb in (0.0, 1.5) for f in (-0.5, 0.0, 0.01, 0.3, 2.0)
    ]
    lines = [d.subckt()]
    for k, (va, vb, f) in enumerate(pts):
        lines += [
            f"va{k} a{k} 0 dc {va}",
            f"vb{k} b{k} 0 dc {vb}",
            f"vf{k} f{k} 0 dc {f}",
            f"x{k} a{k} b{k} f{k} 0 {d.subckt_name}",
        ]
    pins = ("va", "vb", "vf")
    r = _op(lines, [f"i({p}{k})" for k in range(len(pts)) for p in pins])
    want = np.array([d.currents(p) for p in pts])
    got = -np.array([[r[f"i({p}{k})"] for p in pins] for k in range(len(pts))])
    for j, what in enumerate(("a", "b", "force")):
        np.testing.assert_allclose(got[:, j], want[:, j], rtol=RTOL, atol=ATOL, err_msg=what)


def test_gyrator_agrees():
    """A field-scaled gyrator's currents (i_a = g V(b), i_b = -g V(a), g = g_per_v V(f); none
    into f): both ports both ways, the field reversed, off and on."""
    from varimu.devices.gyrator import Gyrator

    d = Gyrator("GYR_TEST", 0.0537)
    pts = [(va, vb, f) for va in (-2.0, 0.3) for vb in (0.0, 1.5) for f in (-1.0, 0.0, 0.4, 18.6)]
    lines = [d.subckt()]
    for k, (va, vb, f) in enumerate(pts):
        lines += [
            f"va{k} a{k} 0 dc {va}",
            f"vb{k} b{k} 0 dc {vb}",
            f"vf{k} f{k} 0 dc {f}",
            f"x{k} a{k} b{k} f{k} 0 {d.subckt_name}",
        ]
    pins = ("va", "vb", "vf")
    r = _op(lines, [f"i({p}{k})" for k in range(len(pts)) for p in pins])
    want = np.array([d.currents(p) for p in pts])
    got = -np.array([[r[f"i({p}{k})"] for p in pins] for k in range(len(pts))])
    for j, what in enumerate(("a", "b", "field")):
        np.testing.assert_allclose(got[:, j], want[:, j], rtol=RTOL, atol=ATOL, err_msg=what)


@pytest.mark.parametrize("name", ["KEY_CONTACT@1", "KEY_BREAK@1"])
def test_contact_agrees(name):
    """A contact's current (into a, out of b; none into its control pin): its springs both
    ways, its control open, inside the smoothstep and closed (a make and a break contact)."""
    d = load_device(name)
    pts = [
        (va, vb, c) for va in (-2.0, 0.3) for vb in (0.0, 1.5) for c in (-1.0, 0.3, 0.5, 0.7, 2.0)
    ]
    lines = [d.subckt()]
    for k, (va, vb, c) in enumerate(pts):
        lines += [
            f"va{k} a{k} 0 dc {va}",
            f"vb{k} b{k} 0 dc {vb}",
            f"vc{k} c{k} 0 dc {c}",
            f"x{k} a{k} b{k} c{k} 0 {d.subckt_name}",
        ]
    pins = ("va", "vb", "vc")
    r = _op(lines, [f"i({p}{k})" for k in range(len(pts)) for p in pins])
    want = np.array([d.currents(p) for p in pts])
    got = -np.array([[r[f"i({p}{k})"] for p in pins] for k in range(len(pts))])
    for j, what in enumerate(("a", "b", "control")):
        np.testing.assert_allclose(got[:, j], want[:, j], rtol=RTOL, atol=ATOL, err_msg=what)


def test_6386_capacitances_in_ac():
    """Grid-driven AC current with the plate at AC ground: jw(Cgk + Cgp), well into cutoff."""
    t = load_device("6386")
    net = t.subckt() + (f"vg g 0 dc -100 ac 1\nvp p 0 dc 0\nx1 p g 0 {t.subckt_name}")
    r = ngspice.run(net, "ac dec 3 1e5 1e7", ["i(vg)"])
    c = -r["i(vg)"].imag / (2 * np.pi * r["scale"])
    np.testing.assert_allclose(c, t.c_gk + t.c_gp, rtol=1e-6)


@pytest.mark.parametrize("name", ["884@1", "2D21@1"])
def test_thyratron_agrees(name):
    """A thyratron's anode, grid and state-port currents (HYBRID_PHYSICS_PLAN.md H1): cutoff,
    the strike's densities and the arc, the grid either side of its floating potential, the
    state from its physical floor (w ~ -25: the background ionization) past its top. Below the
    floor the state port's -s0 / x reaches 1e20 / s and ngspice resolves it to ~1e-6 (w = -60);
    the clamp past W_MIN is checked against Rust (crates/circuitsim/tests/devices.rs)."""
    d = load_device(name)
    tri = d.mu_g2 is None
    pts = [
        (va, vg2, vg, w)
        for va in (-10.0, 9.0, 16.0, 40.0, 150.0, 300.0)
        for vg2 in ((0.0,) if tri else (0.0, 3.0))
        for vg in (-50.0, -4.0, -0.7, 1.0)  # not -0.6: there electrons and ions cancel exactly
        for w in (-30.0, -20.0, -3.0, 1.0, 6.0, 45.0)
    ]
    lines = [d.subckt()]
    for k, (va, vg2, vg, w) in enumerate(pts):
        lines += [f"va{k} a{k} 0 dc {va}", f"vg{k} g{k} 0 dc {vg}", f"vw{k} w{k} 0 dc {w}"]
        if tri:
            lines.append(f"x{k} a{k} g{k} w{k} 0 {d.subckt_name}")
        else:
            lines += [f"vs{k} s{k} 0 dc {vg2}", f"x{k} a{k} s{k} g{k} w{k} 0 {d.subckt_name}"]
    vecs = [f"i(v{p}{k})" for p in "agw" for k in range(len(pts))]
    r = _op(lines, vecs)
    va, vg2, vg, w = np.array(pts, float).T
    want = d.currents(va, vg, w) if tri else d.currents(va, vg2, vg, w)
    ia, ig, iw = (want[0], want[1], want[2]) if tri else (want[0], want[2], want[3])
    for p, ref in (("a", ia), ("g", ig), ("w", iw)):
        got = -np.array([r[f"i(v{p}{k})"] for k in range(len(pts))])
        # The state port's rates reach ~1e10 / s: wrdata's 10 digits set its floor.
        atol = 1e-3 if p == "w" else ATOL
        np.testing.assert_allclose(got, ref, rtol=1e-8, atol=atol, err_msg=f"{name} i{p}")
