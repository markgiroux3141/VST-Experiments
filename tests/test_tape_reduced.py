"""The reduced tape medium (docs/DELAY_PLAN.md, "The reduced medium"): circuitsim's port
against the Python reference (varimu.delay.reduced.ReducedStream), on a synthetic
reduction (agreement doesn't need physical tables), with and without the transport's
flutter and the coating's grain, and on a bias grid with the bias turned mid-run (BIAS as a
knob)."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from varimu.delay import reduced as rd
from varimu.devices import tape_machine as tm
from varimu.devices.library import load_tape

circuitsim = pytest.importorskip("circuitsim")

FS = 96000.0
DS = 2e-6


def _reduction(
    layers: int, hg_bias: float = 30e3, depth: float = 1.0
) -> tuple[rd.Reduction, tuple[np.ndarray, np.ndarray]]:
    """A synthetic reduction; `depth` scales its saturation field, aperture and D(k) (a
    stand-in for another bias's)."""
    h = np.linspace(-40e3, 40e3, 81)
    scale = 15e3 * depth * (1.0 + 0.1 * np.arange(layers))[:, None]
    mx = 0.3 * np.tanh(h[None, :] / scale)
    slope = 0.3 / scale[:, 0]
    tau0, dt, taps = -30e-6, 1.3e-6, 100
    tau = tau0 + dt * np.arange(taps)
    centre = (50e-6 * depth - 2e-6 * np.arange(layers))[:, None]
    ax = np.exp(-(((tau[None, :] - centre) / 15e-6) ** 2))
    ax = ax / ax.sum(axis=1, keepdims=True)
    ky = -1e-7 * (tau[None, :] - centre) / 15e-6 * ax
    red = rd.Reduction(h, mx, slope, tau0, dt, ax, ky, hg_bias=hg_bias)
    k = np.linspace(0.0, 2e6, 50)
    d = 1.0 / np.sqrt(np.sqrt(1.0 + (k / (5e5 * depth)) ** 2))
    return red, (k, d)


def _params(spec, tape, red, demag, head_distance_m, hg_bias=None) -> str:
    """The stream's JSON with a reduction: one (red: a Reduction, demag (k, D)) or a bias
    grid's (red: BiasReductions, demag (k, [D per point]))."""
    reds = red if isinstance(red, rd.BiasReductions) else rd.BiasReductions((red,))
    rows = [demag[1]] if np.ndim(demag[1]) == 1 else list(demag[1])
    hg = reds.points[0].hg_bias if hg_bias is None else hg_bias
    p = tm.stream_params(
        dataclasses.replace(spec, ds_m=DS), tape, hg, head_distance_m=head_distance_m
    )
    r0 = reds.points[0]
    p["reduced"] = {
        "h_a_m": r0.h_a_m.tolist(),
        "tau0_s": r0.tau0_s,
        "dt_s": r0.dt_s,
        "points": [
            {
                "bias_a_m": r.hg_bias,
                "mx": r.mx.tolist(),
                "slope": r.slope.tolist(),
                "ax": r.ax.tolist(),
                "ky": r.ky.tolist(),
                "demag_d": np.asarray(d).tolist(),
            }
            for r, d in zip(reds.points, rows, strict=True)
        ],
        "demag_k": demag[0].tolist(),
    }
    return json.dumps(p)


@pytest.mark.parametrize("moving, grain", [(False, False), (True, True)])
def test_port_agrees_with_reference(moving, grain):
    tape = load_tape("SCOTCH111@3")
    spec = dataclasses.replace(tm.TapeMachineSpec(), flutter=moving)
    red, demag = _reduction(spec.layers)
    v = spec.speed_m_s
    delay = int(round(spec.head_distance_m / v * FS))
    d = delay * v / FS
    rng = np.random.default_rng([7, 351])
    n = delay + int(0.12 * FS)
    x = np.convolve(rng.standard_normal(n), np.ones(6) / 6.0, mode="same") * 25e3
    seed = 3 if grain else None
    ref = rd.ReducedStream(
        spec, tape, red, FS, ds_m=DS, demag=demag, head_distance_m=d, noise_seed=seed
    )
    chunk = 2000
    e_ref = np.concatenate([ref.push_many(x[c : c + chunk]) for c in range(0, n, chunk)])
    e_rs = np.asarray(
        circuitsim.tape_stream_run(
            _params(spec, tape, red, demag, d), FS, x, chunk=1234, noise_seed=seed
        )
    )
    live = np.abs(e_ref).max()
    assert live > 0 and np.count_nonzero(e_ref) > 0.05 * n
    assert np.abs(e_rs - e_ref).max() <= 1e-10 * live


def test_reduction_checked():
    tape = load_tape("SCOTCH111@3")
    spec = tm.TapeMachineSpec()
    red, demag = _reduction(spec.layers)
    p = json.loads(_params(spec, tape, red, demag, spec.head_distance_m))
    p["reduced"]["points"][0]["slope"] = p["reduced"]["points"][0]["slope"][:-1]
    with pytest.raises(Exception, match="reduction"):
        circuitsim.tape_stream_run(json.dumps(p), FS, np.zeros(10))


def test_bias_grid_turned_mid_run():
    """Three biases' reductions, the stream started between the first two and the bias
    turned twice (past the grid's top: held): the port records each block at the bias set
    when it records it, its flux slope with that bias's D(k), as the reference."""
    tape = load_tape("SCOTCH111@3")
    spec = dataclasses.replace(tm.TapeMachineSpec(), flutter=True)
    pts = [
        _reduction(spec.layers, hg, depth) for hg, depth in ((20e3, 0.8), (30e3, 1.0), (45e3, 1.3))
    ]
    reds = rd.BiasReductions(tuple(r for r, _ in pts))
    demag = (pts[0][1][0], np.array([d for _, (_, d) in pts]))
    v = spec.speed_m_s
    delay = int(round(spec.head_distance_m / v * FS))
    d = delay * v / FS
    rng = np.random.default_rng([8, 351])
    n = delay + int(0.2 * FS)
    x = np.convolve(rng.standard_normal(n), np.ones(6) / 6.0, mode="same") * 25e3
    turns = [(int(0.05 * FS), 38e3), (int(0.12 * FS), 60e3)]
    ref = rd.ReducedStream(
        spec, tape, reds, FS, ds_m=DS, demag=demag, hg_bias=24e3, head_distance_m=d
    )
    out, pos = [], 0
    for end, hg in [*turns, (n, None)]:
        while pos < end:
            e = min(pos + 2000, end)
            out.append(ref.push_many(x[pos:e]))
            pos = e
        if hg is not None:
            ref.set_bias(hg)
    e_ref = np.concatenate(out)
    e_rs = np.asarray(
        circuitsim.tape_stream_run(
            _params(spec, tape, reds, demag, d, hg_bias=24e3), FS, x, chunk=1234, bias_a_m=turns
        )
    )
    live = np.abs(e_ref).max()
    assert live > 0
    assert np.abs(e_rs - e_ref).max() <= 1e-10 * live
    # The turns are heard: the same run at one bias differs.
    fixed = rd.ReducedStream(
        spec, tape, reds, FS, ds_m=DS, demag=demag, hg_bias=24e3, head_distance_m=d
    )
    e_fixed = fixed.push_many(x)
    assert np.abs(e_fixed - e_ref).max() > 1e-3 * live
