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


def test_the_astroid_drive():
    """Along the axis the projection; at 45 degrees twice the projection's field magnitude
    (h_sw = 1/2); odd; zero across the axis."""
    assert float(tv.astroid_drive(1.0, 0.0, 3.0, 0.0)) == pytest.approx(3.0)
    c = s = math.sqrt(0.5)
    assert float(tv.astroid_drive(1.0, 0.0, c * 2.0, s * 2.0)) == pytest.approx(4.0)
    assert float(tv.astroid_drive(c, s, -1.0, 0.3)) == pytest.approx(
        -float(tv.astroid_drive(c, s, 1.0, -0.3))
    )
    assert float(tv.astroid_drive(1.0, 0.0, 0.0, 5.0)) == 0.0


def test_the_rust_astroid_recording_agrees(ensemble):
    """circuitsim's astroid-driven recording against the reference, cell for cell."""
    _rust_or_skip()
    v, slab = 0.381, Slab(12.7e-6, 2, 0.5e-6, 0.5e-6)
    head = HeadGeometry(25e-6, 2e-3, 3e-3)
    s = 300e-6 + np.arange(40) * 1.3e-6
    rng = np.random.default_rng(9)
    hs = rng.normal(0.0, 5 * OE, (slab.layers, len(s)))
    he = rng.normal(0.0, 5 * OE, (slab.layers, len(s)))
    tv.CAPTURE.clear()
    with tv.variant_kernel(threads=2, astroid=True, capture=True):
        mx, my = record(*_args(ensemble, head, slab, v, s), **_kw(hs, he), engine="rust")
    (args,) = tv.CAPTURE
    rx, ry = tv.record_astroid_reference(args)
    np.testing.assert_allclose(mx.ravel(), rx, atol=1e-10)
    np.testing.assert_allclose(my.ravel(), ry, atol=1e-10)
    a = record(*_args(ensemble, head, slab, v, s), **_kw(hs, he), engine="rust")
    assert np.abs(mx - a[0]).max() > 1e-3


def test_the_exact_gap_is_westmijzes():
    """docs/TAPE_HEAD_RESEARCH.md 1.3's exact field of a 51 um gap: the mouth (0.834 Hg at
    its centre, 1.98 at 0.49 g), max |H| / max |Hx| at 0.5 and 13.2 um, Karlqvist's far
    away; and the whole head (finite poles) the base model's away from the gap."""
    g = 51e-6
    hx, _ = tv.exact_gap_field(g, np.array([0.0, 0.25 * g, 0.49 * g]), np.full(3, 1e-12 * g))
    np.testing.assert_allclose(hx, [0.834, 0.886, 1.98], atol=2e-3)
    x = np.linspace(-1.5 * g, 1.5 * g, 6001)
    for y, mag, par in ((0.5e-6, 2.17, 1.46), (13.2e-6, 0.65, 0.64)):
        a, b = tv.exact_gap_field(g, x, np.full_like(x, y))
        assert np.hypot(a, b).max() == pytest.approx(mag, abs=6e-3)
        assert np.abs(a).max() == pytest.approx(par, abs=6e-3)
    head = HeadGeometry(g, 1.5e-3, 5.5e-3)
    from varimu.devices.tape import head_field

    xs, ys = np.array([0.6e-3, 1.4e-3, -3e-3]), np.array([4e-6, 8e-6, 2e-6])
    for got, want in zip(tv.exact_head_field(head, xs, ys), head_field(head, xs, ys), strict=True):
        np.testing.assert_allclose(got, want, atol=2e-3 * np.abs(want).max())


@pytest.mark.parametrize("astroid", [False, True])
def test_the_rust_exact_gap_recording_agrees(ensemble, astroid):
    """circuitsim's recording with the exact gap (alone and with the astroid) against the
    reference, cell for cell; tabulated within the tables' error; the variant moves the
    recording; outside the block the head is the base model's again."""
    circuitsim = _rust_or_skip()
    v, slab = 0.381, Slab(12.7e-6, 2, 0.5e-6, 0.5e-6)
    head = HeadGeometry(51e-6, 1.5e-3, 5.5e-3)
    s = 300e-6 + np.arange(40) * 1.3e-6
    rng = np.random.default_rng(10)
    hs = rng.normal(0.0, 5 * OE, (slab.layers, len(s)))
    he = rng.normal(0.0, 5 * OE, (slab.layers, len(s)))
    tv.CAPTURE.clear()
    with tv.variant_kernel(threads=2, astroid=astroid, exact_gap=True, capture=True):
        mx, my = record(*_args(ensemble, head, slab, v, s), **_kw(hs, he), engine="rust")
        tab = record(
            *_args(ensemble, head, slab, v, s), **_kw(hs, he), engine="rust", table_step=0.025
        )
        if astroid:
            rx, ry = tv.record_astroid_reference(tv.CAPTURE[0])
        else:
            rx, ry = (
                a.ravel()
                for a in record(*_args(ensemble, head, slab, v, s), **_kw(hs, he), engine="python")
            )
    np.testing.assert_allclose(mx.ravel(), rx, atol=1e-10)
    np.testing.assert_allclose(my.ravel(), ry, atol=1e-10)
    np.testing.assert_allclose(tab[0], mx, atol=1e-5)
    with tv.variant_kernel(threads=2, astroid=astroid):
        base = record(*_args(ensemble, head, slab, v, s), **_kw(hs, he), engine="rust")
    assert np.abs(mx - base[0]).max() > 1e-3
    assert circuitsim is not None


def test_the_astroid_on_3d_axes(ensemble):
    """On a 3D axis the astroid's angle is between the field and the whole axis: an axis
    out of the head's plane needs a larger field than its in-plane projection says; unit
    axes keep the in-plane formula; circuitsim's recording on 3D axes agrees with the
    reference."""
    _rust_or_skip()
    c, s = 0.6, 0.0  # 53 degrees out of the plane, along x in it
    # Field along x: psi is the axis's own angle to x, h_sw(53 deg) < 1, so the drive
    # exceeds |H| though the in-plane formula would see the field along the axis.
    d = float(tv.astroid_drive(c, s, 1.0, 0.0))
    ct = 0.6
    st = math.sqrt(1 - ct * ct)
    assert d == pytest.approx((np.cbrt(ct) ** 2 + np.cbrt(st) ** 2) ** 1.5)
    v, slab = 0.381, Slab(12.7e-6, 2, 0.5e-6, 0.5e-6)
    head = HeadGeometry(25e-6, 2e-3, 3e-3)
    s_c = 300e-6 + np.arange(30) * 1.3e-6
    rng = np.random.default_rng(11)
    hs = rng.normal(0.0, 5 * OE, (slab.layers, len(s_c)))
    he = rng.normal(0.0, 5 * OE, (slab.layers, len(s_c)))
    kw = _kw(hs, he) | {"orientation": tv.Orientation3D(1.5, 3.0, n_t=3, n_p=4)}
    tv.CAPTURE.clear()
    with tv.variant_kernel(threads=2, astroid=True, capture=True):
        mx, my = record(*_args(ensemble, head, slab, v, s_c), **kw, engine="rust")
    rx, ry = tv.record_astroid_reference(tv.CAPTURE[0])
    np.testing.assert_allclose(mx.ravel(), rx, atol=1e-10)
    np.testing.assert_allclose(my.ravel(), ry, atol=1e-10)


def test_the_exact_gap_on_the_gpu(ensemble):
    """The GPU kernel takes the exact gap through its field tables (f32, within its rounding
    of the f64 tables); without tables it refuses rather than use Karlqvist's field."""
    circuitsim = _rust_or_skip()
    if not hasattr(circuitsim, "tape_gpu") or circuitsim.tape_gpu()[0] is None:
        pytest.skip("no GPU")
    v, slab = 0.381, Slab(12.7e-6, 2, 0.5e-6, 0.5e-6)
    head = HeadGeometry(51e-6, 1.5e-3, 5.5e-3)
    s = 300e-6 + np.arange(40) * 1.3e-6
    tv.CAPTURE.clear()
    with tv.variant_kernel(threads=2, exact_gap=True, capture=True):
        record(*_args(ensemble, head, slab, v, s), orientation=Orientation(1.5, 4), engine="rust")
    k = tv.CAPTURE[0]
    kw = {n: k[n] for n in ("preisach", "head", "heights", "zones", "s_rec", "hg", "s_cells")}
    axes = np.ascontiguousarray(np.asarray(k["axes"], float).ravel())

    def run(gpu, step):
        return circuitsim.tape_record(
            *kw.values(), axes, None, None, None, None, step, gpu, 2, 0.0, 0.0, False, True
        )

    cpu = run(False, 0.025)
    gpu = run(True, 0.025)
    for a, b in zip(gpu, cpu, strict=True):
        np.testing.assert_allclose(np.asarray(a), np.asarray(b), atol=2e-5)
    with pytest.raises(Exception, match="tables"):
        run(True, 0.0)
