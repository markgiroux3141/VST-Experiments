"""The particle-level tape study (varimu/tape_particles, crates/tapeparticles): the SW
particle against its analytic limits, the three implementations of the bench against each
other (Python f64, Rust f64, GPU f32), packing without overlaps."""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from varimu.tape_particles import bench as bn
from varimu.tape_particles import ensemble as ens
from varimu.tape_particles import pack, sw


def test_barrier_along_the_axis_is_half_one_minus_h_squared():
    h = np.linspace(0.0, 0.9, 10)
    dp, _, _, _, two = sw.barriers(-h, np.zeros_like(h))
    assert two.all()
    np.testing.assert_allclose(dp, 0.5 * (1 - h) ** 2, atol=2e-6)


@pytest.mark.parametrize("psi_deg", [10, 30, 45, 60, 80])
def test_switching_field_follows_the_astroid(psi_deg):
    psi = math.radians(psi_deg)
    hs = np.linspace(0.3, 1.2, 9001)
    dp, *_ = sw.barriers(-hs * math.cos(psi), hs * math.sin(psi), grid=32)
    h_sw = hs[np.argmax(dp == 0)]
    # The grid misses a minimum and saddle closer than a step: switching up to 0.3% early.
    assert abs(h_sw / float(sw.astroid_hsw(np.array(psi))) - 1) < 3.5e-3


def test_random_ensemble_saturation_remanence_is_one_half():
    spec = ens.ParticleSpec(sigma_int_a_m=0.0, kv_kt_median=1e4)
    parts = ens.draw(spec, 4000, seed=2)
    h = np.array([2000.0 * ens.OE, 0.0])
    _, m, _ = ens.run_uniform(parts, spec, h, 1e-4)
    assert abs(m[0] - 0.5) < 0.02


def test_hash_uniform_is_in_unit_interval_and_flat():
    u = ens.hash_uniform(7, np.arange(200_000), 3)
    assert u.min() >= 0 and u.max() < 1
    assert abs(u.mean() - 0.5) < 0.005


def test_packing_leaves_no_overlaps():
    spec = bn.BenchSpec()
    box = bn.make_box(spec, 300, seed=5)
    side = box.side_m
    i, j = np.triu_indices(len(box), 1)
    dr = box.r[i] - box.r[j]
    dr -= side * np.round(dr / side)
    d = box.n * box.l[:, None]
    _, dist, _, _ = pack.segment_distance(dr, d[i], d[j])
    w = box.l / spec.aspect
    assert (dist >= spec.contact * 0.5 * (w[i] + w[j]) * 0.999).all()
    assert abs(box.v.sum() / side**3 - spec.packing) < 1e-12
    assert pack.order(box.n) < 0.15


def _runner_or_skip():
    from varimu.tape_particles import runner

    try:
        runner.tpsim()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no tpsim build: {e}")
    return runner


def test_interaction_field_rust_and_gpu_agree_with_python():
    runner = _runner_or_skip()
    spec = bn.BenchSpec()
    box = bn.make_box(spec, 200, seed=4)
    m0 = (2 * bn.erased_state(len(box), 1) - 1)[:, None] * box.n
    ref = bn.interaction_field(box, spec, m0)
    _, _, info = runner.bench_run(box, spec, np.zeros((1, 3)), 1e-6, field_only=True)
    np.testing.assert_allclose(info["hint"][0], ref, rtol=0, atol=1e-9 * np.abs(ref).max())
    # The GPU: nothing switches (hk huge), its last field is the erased state's.
    stiff = dataclasses.replace(box, hk=np.full(len(box), 1e12))
    try:
        _, _, ginfo = runner.bench_run(stiff, spec, np.zeros((1, 3)), 1e-6, gpu=True)
    except RuntimeError as e:
        pytest.skip(f"no GPU: {e}")
    err = np.abs(ginfo["hint"][0] - ref).max() / np.abs(ref).max()
    assert err < 1e-3  # f32 sums of near fields that cancel


def test_bench_rust_matches_python_on_a_short_loop():
    """Kinetic Monte Carlo diverges once a single near-threshold decision differs, so the
    check is the trace's agreement in the box's magnetization."""
    runner = _runner_or_skip()
    spec = bn.BenchSpec()
    box = bn.make_box(spec, 150, seed=6)
    m = 16
    ph = 2 * np.pi * np.arange(1, m + 1) / m
    happ = np.zeros((m, 3))
    happ[:, 0] = 500 * bn.OE * np.sin(ph)
    _, _, tr = bn.run(box, spec, happ, 1 / (60 * m), seed=1, trace=True)
    _, trr, _ = runner.bench_run(box, spec, happ, 1 / (60 * m), seed=1, gpu=False, trace=True)
    assert np.abs(trr[:, 0, :] - tr).max() < 0.05
    try:
        _, trg, _ = runner.bench_run(box, spec, happ, 1 / (60 * m), seed=1, gpu=True, trace=True)
    except RuntimeError as e:
        pytest.skip(f"no GPU: {e}")
    assert np.abs(trg[:, 0, :] - tr).max() < 0.08


def test_moving_head_rust_and_gpu_agree_with_python():
    """The strip's pass (head field, static fields, the master equation) in numpy, Rust f64
    and the GPU's f32, on a few cells."""
    from varimu.tape_particles import strip as sp

    _runner_or_skip()
    spec = bn.BenchSpec(hk_median_a_m=730 * bn.OE, sigma_ln_hk=0.25, interactions="none")
    mach = sp.Machine()
    num = sp.Numerics(layers=2, steps_per_cycle=8, floor_a_m=200 * bn.OE)
    parts = sp.sample(spec, 24, seed=2)
    x = np.array([1e-6, 2e-6])
    rng = np.random.default_rng(0)
    hs = rng.normal(0, 500, (2, 2, 2, 2))
    he = rng.normal(0, 500, (2, 2, 2, 2))
    args = (parts, spec, mach, num, 15e3, 999.0, 400 * bn.OE, x, hs, he)
    ref = sp.reference(*args)
    cpu, _ = sp.run(*args, gpu=False)
    # f64 against f64: a particle at a basin's edge may flip one step apart (master
    # equation's sure switch), 1e-6 of saturation here.
    assert np.abs(cpu - ref).max() < 1e-5
    try:
        gpu, _ = sp.run(*args, gpu=True)
    except RuntimeError as e:
        pytest.skip(f"no GPU: {e}")
    assert np.abs(gpu - ref).max() < 1e-3


def test_moving_head_local_demag_rust_and_gpu_agree_with_python():
    import dataclasses

    from varimu.tape_particles import strip as sp

    _runner_or_skip()
    spec = bn.BenchSpec(hk_median_a_m=730 * bn.OE, sigma_ln_hk=0.25, interactions="none")
    mach = sp.Machine()
    num = sp.Numerics(layers=2, steps_per_cycle=8, floor_a_m=200 * bn.OE, local_demag=True)
    parts = sp.sample(spec, 24, seed=2)
    x = np.array([1e-6, 2e-6])
    z = np.zeros((2, 2, 2, 2))
    args = (parts, spec, mach, num, 15e3, 999.0, 400 * bn.OE, x, z, z)
    ref = sp.reference(*args)
    off = sp.reference(
        parts,
        spec,
        mach,
        dataclasses.replace(num, local_demag=False),
        15e3,
        999.0,
        400 * bn.OE,
        x,
        z,
        z,
    )
    assert np.abs(ref - off).max() > 1e-3  # the demagnetization acts
    cpu, _ = sp.run(*args, gpu=False)
    assert np.abs(cpu - ref).max() < 1e-5
    try:
        gpu, _ = sp.run(*args, gpu=True)
    except RuntimeError as e:
        pytest.skip(f"no GPU: {e}")
    assert np.abs(gpu - ref).max() < 1e-3
