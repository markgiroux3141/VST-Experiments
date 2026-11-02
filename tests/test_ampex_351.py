"""The Ampex 351 (docs/TAPE_PLAN.md, TM5): config/circuits/ampex_351.yaml.

Its record driver's tube (6201@1) meets RCA's sheet; the circuit builds, passes the
pre-flight checks, and idles near the voltages printed on the 1962 schematic (measured
with the oscillator tube removed: `oscillator` 0). With the oscillator in, the record side
runs at the bias's rate (the literal bias, TM5's option A) and biases the record head. The
bias section's own circuit (ampex_351_bias.yaml, TM5's measurement) builds and checks too.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR
from varimu.devices.library import _published, load_device

MACHINE = CONFIG_DIR / "circuits" / "ampex_351.yaml"
BIAS = CONFIG_DIR / "circuits" / "ampex_351_bias.yaml"

# The schematic's DC voltages (p95; 20 kOhm/V meter, record mode, 117 V line, the
# oscillator tube removed): data/schematics/ampex_351/README.md.
PRINTED = {
    "b330": 330, "b300": 300, "b275": 275, "b250": 250, "b220": 220, "b215": 215,
    "b190": 190, "n180": 180, "bosc": 300, "p1b": 170, "k1b": 1.4, "p1a": 170, "k1a": 1.6,
    "p2b": 75, "k2b": 26, "p2a": 150, "k3b": 1.0, "p4a": 110, "k4a": 1.0, "k4b": 0.6,
    "p5a": 295, "p5b": 295, "k5": 13,
}  # fmt: skip
# Off by more than the plan's +-20% (TAPE_PLAN.md, TM5's status), bounded here so they
# don't drift further: 12AX7 plates on 220-330K loads, where a small current error is a
# large voltage error (2V3a, on a 10 MOhm grid leak, also hangs on the provisional grid
# current's contact potential).
LOOSE = {"p3b": 100, "p3a": 90, "p4b": 90}


@pytest.fixture(scope="module")
def machine():
    return spec.load_circuit(MACHINE)


def test_6201_meets_rcas_points():
    pub = _published()["6201"]
    t = load_device("6201@1")
    for p in pub["class_a1"]:
        vk = p["rk_ohm"] * p["ip_a"]
        vg, vp = -vk, p["supply_v"] - vk
        assert t.ip(vg, vp) == pytest.approx(p["ip_a"], rel=0.02)
        assert t.gm(vg, vp) == pytest.approx(p["gm_s"], rel=0.02)
        assert t.rp(vg, vp) == pytest.approx(p["rp_ohm"], rel=0.02)
    cut = pub["cutoff"]
    assert t.ip(cut["vg_v"], cut["supply_v"]) == pytest.approx(cut["ip_a"], rel=0.1)


def test_builds_and_passes_the_checks(machine):
    for cores in ("ja", "linear"):
        builder.build(machine, cores=cores)
    assert preflight.check_circuit(machine) == []
    assert preflight.check_circuit(spec.load_circuit(BIAS)) == []
    # Bridging input, 0 VU = -10 dBm; line output, 0 VU = +8 dBm (manual p11), each at
    # -18 dBFS rms.
    vin, vout = machine.full_scale
    assert vin == pytest.approx(0.2449 * 10 ** (18 / 20), rel=1e-3)
    assert vout == pytest.approx(1.9494 * 10 ** (18 / 20), rel=1e-3)


def test_the_drawings_driver_cathode_is_inconsistent():
    """1V2a's printed 150 V plate on 22K from 275 V is 5.7 mA, which its 2420 ohm cathode
    resistors put at 13.8 V, not the printed 6 V: the model follows the parts."""
    assert (275 - 150) / 22e3 * (220 + 2200) == pytest.approx(13.75, rel=1e-3)


def test_idles_near_the_printed_voltages(machine):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    x = np.zeros(int(0.1 * st.sample_rate))
    c = builder.build(machine, {"oscillator": 0}, cores="linear")
    v = fast.run_transient(c.ir, x, settings=st).vectors
    n = int(0.05 * st.sample_rate)
    for node, d in PRINTED.items():
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(d, rel=0.20), node
    for node, d in LOOSE.items():
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(d, rel=0.40), node
    # The supply from the 6X4 to the output stage within 6%.
    for node in ("b330", "b300", "b275", "b250", "p5a"):
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(PRINTED[node], rel=0.06), node


def test_the_oscillator_biases_the_record_head(machine):
    """The literal bias (TM5, option A): the record side at 20 steps per sample, the
    oscillator started from its kick, ~80 mA in the erase head and a few mA of bias in the
    record head (the probes at 192 kHz, not decimated: they alias the 99 kHz but keep its
    size)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    import dataclasses

    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    st = dataclasses.replace(st, sample_rate=192_000, oversample=1, settle_s=0.0)
    x = np.zeros(int(0.02 * st.sample_rate))
    v = fast.run_transient(builder.build(machine, cores="linear").ir, x, settings=st).vectors
    late = slice(len(x) // 2, None)
    ers, head = v["v(ers)"][late], v["v(rbc)"][late] / 1000.0  # through 5R24, 1000 ohm
    assert 150 < ers.max() < 300 and -300 < ers.min() < -150
    assert 2e-3 < head.max() < 5e-3 and -5e-3 < head.min() < -2e-3
