"""The Telefunken V76 (device builder B10): config/circuits/telefunken_v76.yaml.

It builds from the generic format, passes the pre-flight checks at every switch
combination, wires the gain switch as IRT drawing S 1176 does, and idles near the
voltages printed on the drawing (data/schematics/telefunken_v76/README.md).
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.circuit.ir import Resistor
from varimu.config import CONFIG_DIR

V76 = CONFIG_DIR / "circuits" / "telefunken_v76.yaml"

# Printed on S 1176 (volts to ground). The rails: 300 V on C36 (printed), then the
# printed currents through R81 1k (21 mA) and R76 6k (6.1 mA).
SUPPLY_V = {"b300": 300.0, "ba": 279.0, "bb": 242.4}
# Electrodes on low DC resistance (cathodes, the screens and plates of V2 and V4).
TUBE_V = {"k1": 11.0, "pl2": 175.0, "sg2": 165.0, "k2": 2.3, "sg3": 71.0, "k3": 16.0,
          "pl4": 170.0, "sg4": 140.0, "k4": 2.2}  # fmt: skip
# Electrode currents (A), each from its resistor: (supply node, electrode, the resistance's
# keys in the circuit file, printed current). V1's and V3's plates and screens sit on
# 0.2-1 MOhm, which turn a tube's current error into a 3-4x larger voltage error, so they
# are checked as currents. V3's plate current isn't printed: from its printed 80 V.
CURRENTS = [
    ("bb", "pl1", ("r59_ohm", "r60_ohm"), 0.6e-3),
    ("bb", "sg1", ("r58_ohm",), 0.15e-3),
    ("bb", "sg2", ("r63_ohm",), 0.7e-3),
    ("bb", "pl3", ("r74_ohm",), (242.4 - 80.0) / 200e3),
    ("bb", "sg3", ("r73_ohm",), 0.18e-3),
    ("ba", "pl4", ("l88_r_ohm",), 11.7e-3),
]


@pytest.fixture(scope="module")
def v76():
    return spec.load_circuit(V76)


def test_builds_and_every_value_is_sourced(v76):
    for cores in ("ja", "linear"):
        c = builder.build(v76, cores=cores)
        assert (c.text is None) == (cores == "ja")
    assert spec.check_genome_links(v76) == []
    a = builder.build_ir(v76, spec.resolve(v76, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(v76, spec.resolve(v76))
    moved = sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True))
    assert moved > 50


def test_preflight_passes_at_every_switch_position(v76):
    assert preflight.check_circuit(v76) == []
    assert len(preflight.switch_configs(v76)) == 12 * 2 * 4 * 2


def _resistors(v76, gain_db):
    ir = builder.build_ir(v76, spec.resolve(v76, {"gain_db": gain_db}))
    return {e.name: e for e in ir.elements() if isinstance(e, Resistor)}


def _pad_db(v76, gain_db, z_primary_ohm=1200.0):
    """The pad's loss re its 34 dB position, from a 200 ohm source into a resistive
    primary (the resistors alone)."""
    r = _resistors(v76, gain_db)
    series = sum(r[n].r_ohm for n in r if n in {"R43", "R42", "R41", "R38", "R39", "R40"})
    shunt = r["R44"].r_ohm if "R44" in r else np.inf
    z = 1 / (1 / shunt + 1 / z_primary_ohm)
    return 20 * np.log10(z / (200.0 + series + z) / (z_primary_ohm / (200.0 + z_primary_ohm)))


def _feedback_tap(v76, gain_db):
    r = _resistors(v76, gain_db)
    (tap,) = [n for n in r if n.startswith("RSFB")]
    return int(tap[-1])


def test_gain_switch_as_drawn(v76):
    # The pad's positions sit 31 / 25 / 16 / 16 dB below 34 (the scale's 3 / 9 / 18 dB,
    # and 24 = 18 + the next feedback tap's 6 dB), within a dB of the primary's
    # impedance (sch: 3,4 k, 1,6 k, 450 ohm per leg, 200 ohm across).
    for gain, loss in ((3, -31), (9, -25), (18, -16), (24, -16)):
        assert _pad_db(v76, gain) == pytest.approx(loss, abs=1.0), gain
    assert _pad_db(v76, 34) == pytest.approx(0.0, abs=0.01)
    taps = {g: _feedback_tap(v76, g) for g in (3, 9, 18, 24, 34, 40, 46, 52, 58, 64, 70, 76)}
    assert taps == {3: 0, 9: 0, 18: 0, 24: 1, 34: 0, 40: 1, 46: 2, 52: 3, 58: 4, 64: 5,
                    70: 6, 76: 7}  # fmt: skip


def test_idles_near_the_printed_voltages(v76):
    """The supply within 3%; the tubes' electrodes within 15% (the EF804S sheet's plate
    current spread is +-19%, 3.2 +- 0.6 mA)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    x = np.zeros(int(0.5 * st.sample_rate))
    v = fast.run_transient(builder.build(v76).ir, x, settings=st).vectors
    n = int(0.1 * st.sample_rate)

    def dc(node):
        return np.mean(v[f"v({node})"][-n:])

    for node, d in SUPPLY_V.items():
        assert dc(node) == pytest.approx(d, rel=0.03), node
    for node, d in TUBE_V.items():
        assert dc(node) == pytest.approx(d, rel=0.15), node
    q = spec.resolve(v76)
    for rail, node, keys, i in CURRENTS:
        r = sum(q[k] for k in keys)
        assert (dc(rail) - dc(node)) / r == pytest.approx(i, rel=0.15), node
