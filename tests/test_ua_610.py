"""The UA 610-A (the chains build-out's WP2): config/circuits/ua_610.yaml.

It builds from the generic format, passes the pre-flight checks at every switch position,
idles near a clone's measured voltages (the drawing prints none: data/schematics/ua_610/
README.md), and its gain structure follows the drawing: the Lo / Hi link's step and the
LEVEL pot's law.
"""

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, parts, spec
from varimu.config import CONFIG_DIR

UA610 = CONFIG_DIR / "circuits" / "ua_610.yaml"

# "610 - Final Voltage.png": a GroupDIY builder's clone at B+ 298 V. V1-A's pair is left
# out: its 0.98 V cathode (0.21 mA in R27) disagrees with its plate's drop (0.44 mA in R6,
# 0.48 mA in R7), so one of the clone's readings or parts isn't the drawing's.
CLONE_V = {"bp": 298, "r2": 277, "r3": 260, "r4": 221, "p2": 156, "k2": 1.13, "p3": 89,
           "k3": 1.9, "p4": 287, "k4": 3.4}  # fmt: skip


@pytest.fixture(scope="module")
def ua610():
    return spec.load_circuit(UA610)


def test_builds_and_every_value_is_sourced(ua610):
    for cores in ("ja", "linear"):
        c = builder.build(ua610, cores=cores)
        assert (c.text is None) == (cores == "ja")
    assert spec.check_genome_links(ua610) == []
    a = builder.build_ir(ua610, spec.resolve(ua610, {"passive_spread": 1.0, "passive_seed": 3}))
    b = builder.build_ir(ua610, spec.resolve(ua610))
    moved = sum(e != e0 for e, e0 in zip(a.elements(), b.elements(), strict=True))
    assert moved > 20


def test_preflight_passes(ua610):
    assert preflight.check_circuit(ua610) == []


def test_switches_rewire_the_eq(ua610):
    """S2 puts one ladder point on V2-A's cathode per position (none at 0); S3's decks
    short R21 || C9 except at +6 and put R25 || C13 in series at -6 (sch)."""

    def names(**ov):
        return {e.name for e in builder.build_ir(ua610, spec.resolve(ua610, ov)).elements()}

    assert not {"RS2M6", "RS2P3", "RS2P6"} & names(hf_eq=0)
    assert "RS2M6" in names(hf_eq=-6) and "RS2P6" in names(hf_eq=6)
    assert {"RS3A", "RS3B"} <= names(lf_eq=0)
    assert "RS3A" not in names(lf_eq=6) and "RS3B" in names(lf_eq=6)
    assert {"R25", "C13"} <= names(lf_eq=-6) and "RS3B" not in names(lf_eq=-6)


def _run(c, overrides, x):
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    return fast.run_transient(builder.build_ir(c, spec.resolve(c, overrides)), x, settings=st), st


def test_idles_near_the_clone(ua610):
    """At the clone's B+ (298 V) every rail, plate and cathode within 12% of its readings;
    V1-A self-consistent (its cathode and plate currents agree); V2-B, which carries T2's
    DC, near the clone's 6.1 mA (thread 73280: 'about 6.5mA')."""
    v, st = _run(ua610, {"b_plus_v": 298.0}, np.zeros(int(0.3 * 96000)))
    n = int(0.05 * st.sample_rate)
    m = {k[2:-1]: float(np.mean(a[-n:])) for k, a in v.vectors.items()}
    for node, ref in CLONE_V.items():
        assert m[node] == pytest.approx(ref, rel=0.12), node
    q = spec.resolve(ua610)
    assert m["k1"] / q["r27_ohm"] == pytest.approx((m["r4"] - m["p1"]) / q["r6_ohm"], rel=0.02)
    assert 5.5e-3 < m["k4"] / q["r18_ohm"] < 6.8e-3


def test_gain_structure(ua610):
    """The Lo link is ~8 dB below Hi (the R11 / R9 tap; web: '~9 dB', thread 47543), and
    the LEVEL pot only divides (V2-A's grid draws nothing): the gain at a rotation is the
    full gain plus its taper."""
    fs = 96000
    t = np.arange(int(0.4 * fs)) / fs
    x = 1e-4 * np.sin(2 * np.pi * 1000 * t) * np.minimum(1, t / 0.02)
    q = spec.resolve(ua610)

    def gain_db(**ov):
        v, _ = _run(ua610, ov, x)
        y = v.vectors["v(out)"][-int(0.1 * fs) :]
        return 20 * np.log10(np.sqrt(2) * np.std(y) / 1e-4)

    hi, lo, mid = gain_db(level=1.0), gain_db(level=1.0, gain_link=0), gain_db(level=0.3)
    assert 7.5 < hi - lo < 9.0
    assert mid - hi == pytest.approx(20 * np.log10(parts.taper(0.3, q["r13_taper_mid"])), abs=0.1)
    assert 60.0 < hi < 75.0
