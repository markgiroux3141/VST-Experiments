"""The over-bias study's opt-in variants of the tape medium (varimu.tape_variants;
docs/TAPE_PLAN.md, "Over-bias options"): the moving model's forward memory against the
corner formula, its Rust port against the reference, the 3D orientation's axes, the head
law. None of them is on in the base model."""

from __future__ import annotations

import math

import numpy as np
import pytest

from varimu import tape_variants as tv
from varimu.devices.preisach import OE_A_PER_M, Preisach, PreisachParams
from varimu.devices.tape import HeadGeometry, Orientation, Slab, record

OE = OE_A_PER_M


@pytest.fixture(scope="module")
def ensemble() -> Preisach:
    return Preisach(PreisachParams(293 * OE, 0.33, 46 * OE, 2000 * OE, n_table=256))


def _forward(pre: Preisach, h: np.ndarray) -> float:
    t = tv._Tables(pre)
    st = tv.Stack()
    for x in h:
        st.commit(st.trial(t, float(x)))
    return 2.0 * st.up[-1] - 1.0


def test_the_forward_memory_is_the_corner_formula(ensemble):
    """With no mean field, the stack's state after any history equals the backward corner
    formula's (the wiping-out memory, the erased start's virtual extrema), up to the
    tables' interpolation along the diagonal."""
    rng = np.random.default_rng(3)
    for _ in range(60):
        n = int(rng.integers(1, 30))
        h = rng.normal(0.0, 400 * OE, n) * np.linspace(1.5, 0.2, n) ** rng.uniform(0, 2)
        want = float(ensemble.state_after(h[None, :])[0])
        assert _forward(ensemble, h) == pytest.approx(want, abs=2e-6)
    # Decaying bias around a steady field: the anhysteretic's history.
    k = np.arange(400)
    h = 30 * OE + 900 * OE * (1 - k / 400) * np.where(k % 2 == 0, 1.0, -1.0)
    assert _forward(ensemble, h) == pytest.approx(float(ensemble.state_after(h[None])[0]), abs=2e-6)


def test_the_mean_field_shears_or_squares_the_loop(ensemble):
    """alpha < 0 lowers the remanence after a field and lowers the loop's slope; alpha > 0
    raises it (Della Torre's moving model)."""
    hist = np.array([[2000 * OE, -150 * OE, 0.0]])
    base = float(tv.along_x(ensemble, hist)[0])
    neg = float(tv.along_x(ensemble, hist, None, -0.1 * 7e4)[0])
    pos = float(tv.along_x(ensemble, hist, None, 0.05 * 7e4)[0])
    assert neg < base < pos


def _rust_or_skip():
    circuitsim = pytest.importorskip("circuitsim")
    if not hasattr(circuitsim, "tape_moving_stats"):
        pytest.skip("circuitsim without the moving model (rebuild: uv sync --extra fast)")
    return circuitsim


@pytest.mark.parametrize("alpha", [-0.15, 0.04])
def test_the_rust_moving_model_agrees(ensemble, alpha):
    """circuitsim's moving-model recording against the reference, cell for cell: a vector
    ensemble with a steady field on the cells and a different field after the pass."""
    circuitsim = _rust_or_skip()
    v, slab = 0.381, Slab(12.7e-6, 2, 0.5e-6, 0.5e-6)
    head = HeadGeometry(25e-6, 2e-3, 3e-3)
    s = 300e-6 + np.arange(24) * 2.1e-6
    rng = np.random.default_rng(8)
    hs = rng.normal(0.0, 5 * OE, (slab.layers, len(s)))
    he = rng.normal(0.0, 5 * OE, (slab.layers, len(s)))
    ms = 7.0e4
    tv.CAPTURE.clear()
    with tv.variant_kernel(mean_field=alpha, ms_a_m=ms, threads=2, capture=True):
        mx, my = record(
            ensemble,
            head,
            slab,
            lambda t: 300 * OE * np.sin(2 * math.pi * 3000.0 * t),
            500 * OE,
            70e3,
            lambda t: v * t,
            0.0,
            (s[-1] + 400e-6) / v,
            s,
            hg_signal_max=300 * OE,
            h_static=(hs, 0.5 * hs),
            h_end=(he, 0.5 * he),
            orientation=Orientation(1.5, 4),
            engine="rust",
        )
    solves, fails, worst = circuitsim.tape_moving_stats()
    assert solves > 0 and fails == 0, (solves, fails, worst)
    (args,) = tv.CAPTURE
    rx, ry = tv.record_reference(args, alpha, ms)
    np.testing.assert_allclose(mx.ravel(), rx, atol=1e-10)
    np.testing.assert_allclose(my.ravel(), ry, atol=1e-10)
    # The variant moves the recording; without it the kernel is the base model's.
    with tv.variant_kernel(threads=2):
        b = record(*_args(ensemble, head, slab, v, s), **_kw(hs, he), engine="rust")
    a = record(*_args(ensemble, head, slab, v, s), **_kw(hs, he), engine="rust")
    for x, y in zip(a, b, strict=True):
        np.testing.assert_array_equal(x, y)
    assert np.abs(mx - a[0]).max() > 1e-3


def _args(ensemble, head, slab, v, s):
    return (
        ensemble,
        head,
        slab,
        lambda t: 300 * OE * np.sin(2 * math.pi * 3000.0 * t),
        500 * OE,
        70e3,
        lambda t: v * t,
        0.0,
        (s[-1] + 400e-6) / v,
        s,
    )


def _kw(hs, he):
    return dict(
        hg_signal_max=300 * OE,
        h_static=(hs, 0.5 * hs),
        h_end=(he, 0.5 * he),
        orientation=Orientation(1.5, 4),
    )


def test_the_3d_axes_are_projections():
    """Orientation3D: weights sum to 1, axes' in-plane lengths at most 1; strongly
    concentrated it is the aligned model; its orientation ratio rises with kappa."""
    o = tv.Orientation3D(2.0, 1.0)
    ux, uy, w = o.axes()
    assert w.sum() == pytest.approx(1.0)
    assert np.all(np.hypot(ux, uy) <= 1.0 + 1e-12)
    # The study's quadrature against a fine one: the remanence along x.
    for k in (0.0, 1.5, 3.0):
        o = tv.Orientation3D(k, 1.0)
        a = o.axes()
        assert float((a[2] * a[0]).sum()) == pytest.approx(o.ratios()["x"], rel=1e-2)
    ors = [tv.Orientation3D(k, 1.0).ratios()["or_xz"] for k in (0.0, 1.0, 3.0)]
    assert ors[0] < ors[1] < ors[2]
    assert tv.Orientation3D(0.0, 0.0).ratios()["or_xz"] == pytest.approx(1.0, rel=1e-3)


def test_the_head_law_is_bounded_and_mumetall_rises():
    """The head law maps small fields to themselves, stays monotone, and with mumetall's
    rising amplitude permeability is at most slightly superlinear before saturation."""
    law = tv.HeadLaw(reluctance_ratio=250.0, area_ratio=1.0, f_hz=70e3, lamination_m=0.1e-3)
    h = np.linspace(-2000 * OE, 2000 * OE, 41)
    out = law.apply(h)
    assert np.all(np.diff(out) > 0)
    assert out[21] / h[21] == pytest.approx(1.0, rel=2e-2)
    ratio = out[-1] / h[-1]
    assert 0.9 < ratio < 1.1


@pytest.mark.parametrize("alpha", [-0.1, 0.06])
def test_the_rust_static_loops_agree(ensemble, alpha):
    """The moving model's loops (the static fit's histories) in circuitsim against the
    reference."""
    _rust_or_skip()
    h = np.linspace(100, 900, 7) * OE
    hist = np.stack([h, -h, h, -h, h, np.zeros_like(h)], axis=1)
    o = Orientation(1.5, 4)
    a = alpha * 7e4
    np.testing.assert_allclose(
        tv.along_x_rust(ensemble, hist, o, a), tv.along_x(ensemble, hist, o, a), atol=1e-10
    )
