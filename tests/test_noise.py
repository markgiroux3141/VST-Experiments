"""The noise streams and densities (device builder B5): varimu.devices.noise."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.signal import welch

from varimu.config import REPO_ROOT
from varimu.devices import noise as nz

NOISE_FIXTURE = REPO_ROOT / "crates/circuitsim/tests/fixtures/noise/noise.json"

M0, M1 = 0xD2E7470EE14C6C93, 0xCA5A826395121157
W0, W1 = 0x9E3779B97F4A7C15, 0xBB67AE8584CAA73B
MASK = (1 << 64) - 1


def _philox(counter: int, k: tuple[int, int]) -> list[int]:
    """Philox4x64-10 from its definition (Salmon et al. 2011), in Python integers."""
    c = [counter, 0, 0, 0]
    k0, k1 = k
    for _ in range(10):
        p0, p1 = M0 * c[0], M1 * c[2]
        c = [(p1 >> 64) ^ c[1] ^ k0, p1 & MASK, (p0 >> 64) ^ c[3] ^ k1, p0 & MASK]
        k0, k1 = (k0 + W0) & MASK, (k1 + W1) & MASK
    return c


def test_fixture_is_current():
    assert NOISE_FIXTURE.read_text("utf-8") == nz.noise_fixtures_json(), (
        "rerun scripts/export_circuit_fixtures.py"
    )


def test_philox_is_numpys_and_the_definitions():
    assert _philox(0, (0, 0)) == [
        0x16554D9ECA36314C,
        0xDB20FE9D672D0FDC,
        0xD7E772CEE186176B,
        0x7E68B68AEC7BA23B,
    ]  # Random123's known answer
    k = nz.key(99, "IN_R7", nz.STREAM_MAIN)
    words = nz._words(k, 0, 5)
    for b in range(5):
        assert [int(w) for w in words[b]] == _philox(b + 1, k)


def test_streams_are_the_same_from_any_start_and_independent():
    k = nz.key(5, "IN_R1", nz.STREAM_MAIN)
    whole = nz.normals(k, 0, 64)
    for start in (1, 3, 4, 5, 33):
        assert np.array_equal(nz.normals(k, start, 20), whole[start : start + 20])
    others = [
        nz.normals(nz.key(5, "IN_R2", nz.STREAM_MAIN), 0, 64),
        nz.normals(nz.key(6, "IN_R1", nz.STREAM_MAIN), 0, 64),
        nz.normals(nz.key(5, "IN_R1", nz.STREAM_GRID), 0, 64),
    ]
    for o in others:
        assert not np.allclose(o, whole)


def test_normals_are_unit_and_white():
    z = nz.normals(nz.key(1, "IN_R1", 0), 0, 2**20)
    assert abs(z.mean()) < 5 / 2**10
    assert abs(z.var() - 1) < 0.01
    assert abs(np.mean(z**4) - 3) < 0.05  # Gaussian kurtosis
    assert abs(np.mean(z[1:] * z[:-1])) < 5 / 2**10


def test_flicker_is_one_over_f_and_stationary_from_the_start():
    fs = 96000.0
    f = nz.FlickerFilter.design(fs)
    assert (f.residues > 0).all()
    # The design's response in the band: within 0.05 dB of 1/f.
    ff = np.logspace(-2, 4, 300)
    x = np.exp(-2j * np.pi * ff / fs)
    h = f.direct + sum(r / (1 - p * x) for p, r in zip(f.poles, f.residues, strict=True))
    level_db = 10 * np.log10(ff * (f.gain * np.abs(h)) ** 2 * 2 / fs)
    assert np.abs(level_db).max() < 0.05
    # A run: the slope and level from Welch, and the variance right from sample 0 the same
    # as later (no warm-up).
    n = 2**20
    y = f.run(nz.key(3, "BN_X", nz.STREAM_FLICKER), nz.key(3, "BN_X", nz.STREAM_FLICKER_START), n)
    fw, s = welch(y, fs=fs, nperseg=2**17)
    sel = (fw > 2) & (fw < 5e3)
    slope = np.polyfit(np.log10(fw[sel]), np.log10(s[sel]), 1)[0]
    assert abs(slope + 1) < 0.03
    assert abs(10 * np.log10(np.exp(np.mean(np.log(s[sel] * fw[sel]))))) < 0.5
    # Stationary start: many starts' first samples have the stationary variance.
    keys = [
        (nz.key(s, "BN_X", nz.STREAM_FLICKER), nz.key(s, "BN_X", nz.STREAM_FLICKER_START))
        for s in range(400)
    ]
    first = [f.run(k, ks, 1)[0] for k, ks in keys]
    # y0 = gain (d x0 + sum s_i[0]), s[0] stationary (covariance P) with cov(s_i[0], x0) = r_i.
    p_sum = float(np.sum(f.start_chol @ f.start_chol.T))
    var = f.gain**2 * (f.direct**2 + 2 * f.direct * f.residues.sum() + p_sum)
    assert np.var(first) == pytest.approx(var, rel=0.2)


def test_densities():
    t = 300.0
    # 1 MOhm at 300 K: 128.7 nV/sqrt(Hz)
    assert math.sqrt(nz.johnson_a2(1e6, t) * 1e6**2) == pytest.approx(128.7e-9, rel=1e-3)
    gm = 1.6e-3
    # R_eq = 2.5 / gm at 290 K, as a plate current: gm^2 4 k T0 R_eq
    assert nz.shot_a2(gm) == pytest.approx(gm**2 * 4 * nz.K_B * 290 * 2.5 / gm)
    assert nz.shot_a2(-1e-3) == 0.0
    # Pentode: (Ib / Ik)(2.5 / gm)(1 + 8 Ic2 / gm) as R_eq
    ib, ic2 = 3e-3, 0.6e-3
    r_eq = ib / (ib + ic2) * 2.5 / gm * (1 + 8 * ic2 / gm)
    assert nz.shot_a2(gm, ib, ic2, nz.PARTITION) == pytest.approx(gm**2 * 4 * nz.K_B * 290 * r_eq)
    assert nz.grid_shot_a2(-1e-6) == pytest.approx(2 * nz.Q_E * 1e-6)
    assert nz.white_sigma(2.0, 96000.0) == pytest.approx(math.sqrt(96000.0))
    assert 10 * np.log10(nz.interp_gain(20e3, 96000.0)) == pytest.approx(-1.25, abs=0.01)


# --- The IR and the builders ------------------------------------------------------------


def _triode_stage(noise=None):
    from varimu.circuit import builder, spec

    c = spec.load_circuit(spec.circuit_path("triode_stage"))
    return builder.build_ir(c, spec.resolve(c), noise=noise)


def test_noise_is_opt_in():
    from varimu.circuit import builder, ir, spec
    from varimu.config import CONFIG_DIR

    for path in sorted((CONFIG_DIR / "circuits").glob("*.yaml")):
        c = spec.load_circuit(path)
        if c.noise is not None:
            continue
        x = builder.build_ir(c, spec.resolve(c))
        assert x.noise is None and "noise" not in x.to_dict(), path.stem
        assert not any(isinstance(e, ir.NoiseCurrent | ir.TubeNoise) for e in x.elements())


def test_noise_elements_follow_their_parts_and_round_trip():
    from varimu.circuit import ir

    off, on = _triode_stage(), _triode_stage(noise=2**64 - 1)
    assert on.noise == ir.NoiseSpec(2**64 - 1, 96000.0)
    # Without the noise elements, the same circuit in the same order.
    strip = tuple(e for e in on.elements() if not isinstance(e, ir.NoiseCurrent | ir.TubeNoise))
    assert strip == tuple(off.elements())
    resistors = [e for e in on.elements() if isinstance(e, ir.Resistor)]
    noise = {e.name: e for e in on.elements() if isinstance(e, ir.NoiseCurrent)}
    for r in resistors:
        n = noise[f"IN_{r.name}"]
        assert (n.a, n.b) == (r.a, r.b)
        assert n.psd_a2_hz == 4.0 * nz.K_B * nz.RESISTOR_T_K / r.r_ohm
    tubes = [e for e in on.elements() if isinstance(e, ir.TubeNoise)]
    assert [t.device for t in tubes] == [e.name for e in on.elements() if isinstance(e, ir.Device)]
    assert all(t.flicker_v2 == nz.FLICKER_V2 and t.partition == 0.0 for t in tubes)
    assert ir.CircuitIR.from_json(on.to_json()) == on
    assert '"seed": 18446744073709551615' in on.to_json()  # an integer, all 64 bits


def test_the_ir_refuses_bad_noise():
    import dataclasses

    from varimu.circuit import ir

    on = _triode_stage(noise=1)
    with pytest.raises(ir.IRError, match="seed"):
        dataclasses.replace(on, noise=ir.NoiseSpec(-1, 96000.0))
    t = next(e for e in on.elements() if isinstance(e, ir.TubeNoise))
    bad = dataclasses.replace(t, partition=8.0)  # a triode has no screen
    secs = tuple(
        dataclasses.replace(s, elements=tuple(bad if e is t else e for e in s.elements))
        for s in on.sections
    )
    with pytest.raises(ir.IRError, match="partition"):
        dataclasses.replace(on, sections=secs)


def test_a_noisy_run_reproduces_from_its_seed():
    pytest.importorskip("circuitsim")
    from varimu.sim import fast

    x = np.zeros(4800)
    out = [fast.run_transient(_triode_stage(noise=s), x).vectors["v(o)"] for s in (1, 1, 2)]
    quiet = fast.run_transient(_triode_stage(), x).vectors["v(o)"]
    assert np.array_equal(out[0], out[1])
    hiss = out[0] - quiet
    assert np.std(hiss) > 0
    assert np.std(out[2] - out[0]) > 0.5 * np.std(hiss)
