"""The Helios mic amplifier (docs/CHAINS_PLAN.md WP19): config/circuits/helios.yaml, traced from
Iron Age Audioworks' IA-H9 (rev 1), a Helios Type 69 clone (data/schematics/helios_ia_h9/).

It builds, passes the pre-flight checks, idles centred between its +8 / -15.3 V rails; GAIN
follows 1 + 47k / R(GAIN) times T1's 1:10, the EQ CUT divider and the output amp's x6.7 (25-72
dB over the labels 20-70); the pad (T1's 1:1 tap) takes ~20 dB; the HPF cuts the bass.
"""

from __future__ import annotations

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR

HELIOS = CONFIG_DIR / "circuits" / "helios.yaml"
FS = 96000.0


@pytest.fixture(scope="module")
def helios():
    return spec.load_circuit(HELIOS)


def test_builds_and_every_value_is_sourced(helios):
    for cores in ("ja", "linear"):
        c = builder.build(helios, cores=cores)
        assert (c.text is None) == (cores == "ja")
    assert spec.check_genome_links(helios) == []
    a = builder.build_ir(helios, spec.resolve(helios, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(helios, spec.resolve(helios))
    moved = sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True))
    assert moved > 20


def test_preflight_passes(helios):
    assert preflight.check_circuit(helios) == []


def test_switches_rewire(helios):
    def names(**ov):
        return {e.name for e in builder.build_ir(helios, spec.resolve(helios, ov)).elements()}

    assert "RPAD0" in names(pad=0) and "RPAD1" in names(pad=1)
    assert "RG50" in names(gain=50) and "RG70" not in names(gain=50)
    assert "RH2" in names(hpf=0) and "RH2" not in names(hpf=1)


def _gain_db(c, over, f_hz=1000.0, amp=1e-4, dur_s=0.12):
    from varimu.sim import fast

    ir = builder.build_ir(c, spec.resolve(c, over), "ja")
    t = np.arange(int(dur_s * FS)) / FS
    x = amp * np.sin(2 * np.pi * f_hz * t) * np.minimum(1.0, t / 0.02)
    v = {k: np.asarray(y) for k, y in fast.run_transient(ir, x).vectors.items()}
    if amp == 0.0:
        return -np.inf, v
    n = int(round(FS / f_hz * max(1, int(0.02 * f_hz))))
    tt, y = t[-n:], v["v(out)"][-n:]
    m = np.column_stack([np.sin(2 * np.pi * f_hz * tt), np.cos(2 * np.pi * f_hz * tt), np.ones(n)])
    a, b, _ = np.linalg.lstsq(m, y, rcond=None)[0]
    return 20 * np.log10(np.hypot(a, b) / amp), v


def test_idle_is_centred_and_quiet(helios):
    """Q3 / Q7 at ~10 mA, their collectors near the rails' midpoint (-3.65 V)."""
    pytest.importorskip("circuitsim")
    _, v = _gain_db(helios, {}, amp=0.0, dur_s=0.04)
    for node in ("o1", "o7"):
        assert -6.0 < v[f"v({node})"][-1] < -3.0
    assert np.ptp(v["v(out)"][-1000:]) < 1e-6


def test_gain_steps_and_pad(helios):
    pytest.importorskip("circuitsim")
    for gain, want in ((20, 25.2), (40, 40.0), (50, 50.0), (70, 72.3)):
        got, _ = _gain_db(helios, {"gain": gain})
        assert got == pytest.approx(want, abs=0.5), gain
    hi, _ = _gain_db(helios, {"gain": 70})
    pad, _ = _gain_db(helios, {"gain": 70, "pad": 1}, amp=1e-3)
    assert hi - pad == pytest.approx(19.6, abs=0.5)


def test_hpf_cuts_the_bass(helios):
    """The Sallen-Key with the follower's input across R18: ~-5 dB at 80 Hz, flat at 1 kHz."""
    pytest.importorskip("circuitsim")
    ref, _ = _gain_db(helios, {"gain": 50, "hpf": 1})
    flat, _ = _gain_db(helios, {"gain": 50})
    lf, _ = _gain_db(helios, {"gain": 50, "hpf": 1}, f_hz=80.0, dur_s=0.4)
    assert abs(ref - flat) < 0.2
    assert -6.0 < lf - ref < -3.5
