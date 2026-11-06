"""The JFET (varimu.devices.jfet; DEVICE_BUILDER_PLAN.md B12, CHAINS_PLAN.md WP21): the
Python reference against ngspice's native level-1 `J` (`.op` on a grid of bias points,
N- and P-channel, normal and inverse mode, with and without the doping tail B), its
Jacobian against finite differences, and the `jfet` part in the builder.

The compiled port's agreement with the reference is crates/circuitsim/tests/devices.rs
(fixtures from varimu.devices.fixtures); the Rust builder's is varimu-circuit's
tests/agreement.rs."""

import itertools

import numpy as np
import pytest

from varimu.devices.jfet import SPICE_GMIN, Jfet, parse_card

TIGHT = "reltol=1e-12 abstol=1e-16 vntol=1e-13"
# wrdata's 10 significant digits; ngspice's -IS below -5 N Vt differs by < 0.007 IS.
ATOL, RTOL = 1e-13, 2e-8

MODELS = {
    # The square law (B = 1, SPICE's default) on a 2N3819-class card.
    "square": Jfet("J_SQ", "njf", -3.0, 1.304e-3, lambda_per_v=2.25e-3, is_a=33.57e-15),
    # The doping tail and a gate emission coefficient.
    "tail": Jfet(
        "J_TAIL", "njf", -2.0, 1e-3, lambda_per_v=0.01, is_a=1e-14, n=1.2, b=0.9, pb_v=0.8
    ),  # fmt: skip
    "pchannel": Jfet("J_P", "pjf", -1.55, 2e-3, lambda_per_v=0.02, b=0.7, pb_v=1.0),
}

_VGS = (-6.0, -3.2, -1.9, -1.0, -0.5, 0.0, 0.3, 0.6)
_VDS = (-10.0, -2.0, -0.5, -0.05, 0.0, 0.05, 0.5, 1.4, 2.0, 10.0)


def _ngspice():
    from varimu.sim import ngspice

    try:
        ngspice.find_ngspice()
    except ngspice.SimulatorNotFound:
        pytest.skip("ngspice not available")
    return ngspice


def _grid(q: Jfet) -> np.ndarray:
    pts = [(vds, vgs) for vgs, vds in itertools.product(_VGS, _VDS) if vgs - vds <= 0.6]
    return q.sign * np.array(pts, float)


@pytest.mark.parametrize("name", list(MODELS))
def test_reference_agrees_with_ngspice(name):
    """One `.op` with an instance per bias point; ngspice's GMIN across both gate junctions
    is added to the reference."""
    ngspice = _ngspice()
    q = MODELS[name]
    pts = _grid(q)
    lines = [q.model_card()]
    for k, (vds, vgs) in enumerate(pts):
        lines += [
            f"vd{k} d{k} 0 dc {vds}",
            f"vg{k} g{k} 0 dc {vgs}",
            f"j{k} d{k} g{k} 0 {q.model_name}",
        ]
    vecs = [f"i(vd{k})" for k in range(len(pts))] + [f"i(vg{k})" for k in range(len(pts))]
    r = ngspice.run("\n".join(lines), "op", vecs, options=TIGHT)
    got_d = -np.array([float(r[f"i(vd{k})"][0]) for k in range(len(pts))])
    got_g = -np.array([float(r[f"i(vg{k})"][0]) for k in range(len(pts))])
    vds, vgs = pts.T
    i_d, i_g = q.currents(vds, vgs)
    vgd = vgs - vds
    i_d = i_d - SPICE_GMIN * vgd
    i_g = i_g + SPICE_GMIN * (vgs + vgd)
    np.testing.assert_allclose(got_d, i_d, rtol=RTOL, atol=ATOL, err_msg=f"{name} Id")
    np.testing.assert_allclose(got_g, i_g, rtol=RTOL, atol=ATOL, err_msg=f"{name} Ig")


@pytest.mark.parametrize("name", list(MODELS))
def test_jacobian_matches_finite_differences(name):
    q = MODELS[name]
    h = 1e-7
    checked = 0
    for vds, vgs in _grid(q):
        # Skip the cutoff kinks (vgst or vgdt at 0) where differences straddle them.
        s = q.sign
        if min(abs(s * vgs - q.vto_v), abs(s * (vgs - vds) - q.vto_v)) < 1e-3:
            continue
        jac = q.jacobian(vds, vgs)
        for j, dv in enumerate(((h, 0.0), (0.0, h))):
            hi = np.array(q.currents(vds + dv[0], vgs + dv[1]))
            lo = np.array(q.currents(vds - dv[0], vgs - dv[1]))
            fd = (hi - lo) / (2 * h)
            np.testing.assert_allclose(jac[:, j], fd, rtol=1e-5, atol=1e-12)
            checked += 1
    assert checked > 100


def test_channel_is_symmetric():
    """A JFET used as a resistor passes signal both ways: swapping drain and source (the
    gate held to the source) mirrors the channel current exactly."""
    q = MODELS["tail"]
    for vgs, vds in itertools.product((-1.5, -0.7, 0.0), (0.05, 0.3, 1.0)):
        i_fwd, _, _ = q.channel(vgs, vds)
        i_rev, _, _ = q.channel(vgs - vds, -vds)  # the same terminals, roles swapped
        assert i_rev == pytest.approx(-i_fwd, rel=1e-14)


def test_square_law_textbook():
    """B = 1: IDSS = BETA VTO^2 at vgs = 0 in saturation (the 2N3819-class card: ~11.7
    mA at LAMBDA's vds), and the linear region's channel resistance 1 / (2 BETA vgst)."""
    q = MODELS["square"]
    i, _, _ = q.channel(0.0, 10.0)
    assert float(i) == pytest.approx(q.beta_a_per_v2 * 9.0 * (1 + 10 * q.lambda_per_v))
    _, _, g = q.channel(-1.0, 0.0)
    assert 1.0 / float(g) == pytest.approx(1.0 / (2 * q.beta_a_per_v2 * 2.0))


def test_parse_card():
    pol, p = parse_card(
        ".model 2N3819 NJF(Beta=1.304m Betatce=-.5 Rd=1 Rs=1 Lambda=2.25m Vto=-3 "
        "Vtotc=-2.5m Is=33.57f Isr=322.4f N=1 Nr=2 Xti=3 Alpha=311.7u Vk=243.6 "
        "Cgd=1.6p M=.3622 Pb=1 Fc=.5 Cgs=2.414p Kf=9.882E-18 Af=1 mfg=Vishay)"
    )
    assert pol == "njf" and p["BETA"] == pytest.approx(1.304e-3) and p["VTO"] == -3.0
    assert p["CGS"] == pytest.approx(2.414e-12) and "MFG" not in p
