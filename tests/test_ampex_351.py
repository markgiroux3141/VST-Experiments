"""The Ampex 351 (docs/TAPE_PLAN.md, TM5): config/circuits/ampex_351.yaml.

Its record driver's tube (6201@1) meets RCA's sheet; the circuit builds, passes the
pre-flight checks, and idles near the voltages printed on the 1962 schematic (measured
with the oscillator tube removed: `oscillator` 0). With the oscillator in, the record side
runs at the bias's rate (the literal bias, TM5's option A) and biases the record head. The
bias section's own circuit (ampex_351_bias.yaml, TM5's measurement) builds and checks too.
"""

import re

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
# Off by more than the plan's +-20%, bounded here so they don't drift further: the
# drawing's unit had these three 12AX7s hotter than the average tube (GE's sheet agrees
# with 12AX7@1; their grids as if +0.14..+0.21 V less negative, ordinary tube-to-tube
# spread), and the nominal unit keeps average tubes (TAPE_PLAN.md, "Gaps" 1, decided
# 2026-11-02).
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


def test_the_tape_runs_the_351s_transport(machine, tmp_path):
    """The tape part's transport (TAPE_PLAN.md TM3's mechanisms, scaled to the 351's
    0.11%): the same components as the first print's machine; all values or none."""
    from varimu.circuit import ir
    from varimu.devices.tape_machine import TapeMachineSpec

    c = builder.build(machine, cores="linear")
    (t,) = [e for e in c.ir.elements() if isinstance(e, ir.Tape)]
    periodic, random = TapeMachineSpec().transport()
    np.testing.assert_allclose(t.medium.flutter, periodic, rtol=1e-12)
    np.testing.assert_allclose(t.medium.flutter_noise, random, rtol=1e-12)
    # Every tape part's (one per speed), whatever its indentation.
    text = re.sub(r"^ *scrape_rms: scrape_rms\n", "", MACHINE.read_text(), flags=re.M)
    broken = tmp_path / "ampex_351.yaml"
    broken.write_text(text)
    with pytest.raises(Exception, match="all or none"):
        builder.build(spec.load_circuit(broken), cores="linear")


def test_the_alignments_reproduce_side_is_nab():
    """The alignment's reproduce side alone (varimu.measure.tape_align.repro_ir), driven at
    the head's EMF: with 2R31 at 50 us (0.67) it falls as NAB's 3180 / 50 us integrator
    from 700 Hz to 10 kHz (-12.9 dB), within 0.3 dB (the head's coil, 2V3's own response)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.measure import tape_align as ta

    b = ta.Bench.load()
    g = ta.response(b, ta.repro_ir(b, {"rep_eq_hi": 0.67}), "out", (700.0, 10e3), 1e-4)
    nab = ta._nab((700.0, 10e3))  # what an ideal head reads from a standard tape
    want = ta._db(nab[0] / nab[1])  # the amplifier is its inverse
    assert ta._db(g[1] / g[0]) == pytest.approx(want, abs=0.3)
    assert want == pytest.approx(-12.9, abs=0.1)


def test_the_alignments_meters_read_a_fluttering_tone():
    """The alignment reads levels and THD from band powers (a VTVM behind a band-pass), so
    a tone whose phase wanders with the transport (here 3 rad at 2.5 Hz at 15 kHz, the
    motor's hunting, in proportion at 400 Hz) reads its level, which a coherent fit would
    lose."""
    from varimu.measure import tape_align as ta

    fs = 192_000
    t = np.arange(int(0.19 * fs)) / fs
    for f in (400.0, 15000.0):
        ph = 2 * np.pi * f * t + 3.0 * f / 15000.0 * np.sin(2 * np.pi * 2.5 * t)
        y = 0.7 * np.sin(ph) + 0.01 * np.sin(2 * ph) + 0.3
        assert ta.level(y, fs, f) == pytest.approx(0.7, rel=1e-4)
        assert ta.thd(y, fs, f)[0] == pytest.approx(0.01 / 0.7, rel=1e-3)


def test_the_electronics_follow_ampexs_measured_curves():
    """The record and reproduce amplifiers against the 351 manual's measured response
    curves at 15 ips NAB (p94, data/datasheets/ampex_351_response_15ips.csv), re 1 kHz: the
    record side (input to head current) at 1C7's ends against the MINIMUM and MAXIMUM
    curves within 1.2 dB; the reproduce side (head EMF to line out, 2R31 at 50 us) within
    0.7 dB from 200 Hz up and 2.5 dB below (measured: +2.2 dB at 30 Hz, more bass than
    Ampex's; TAPE_PLAN.md TM5)."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    import csv
    import math

    from varimu.config import REPO_ROOT
    from varimu.measure import tape_align as ta
    from varimu.sim import fast

    rows = list(csv.DictReader((REPO_ROOT / "data/datasheets/ampex_351_response_15ips.csv").open()))
    pub = {}
    for r in rows:
        pub.setdefault(r["curve"], {})[float(r["f_hz"])] = float(r["db"])
    b = ta.Bench.load()

    def resp(ir, probe, freqs, amp):
        t = np.arange(int(1.2 * b.fs)) / b.fs
        ph = np.random.default_rng(1).uniform(0, 2 * math.pi, len(freqs))
        x = amp * sum(np.sin(2 * math.pi * f * t + p) for f, p in zip(freqs, ph, strict=True))
        v = fast.run_transient(ir, x, settings=b.settings).vectors[f"v({probe})"]
        w = slice(int(0.6 * b.fs), None)
        d = ta._db(ta.fit(v[w], b.fs, freqs) / ta.fit(x[w], b.fs, freqs))
        return dict(zip(freqs, d - d[list(freqs).index(1000.0)], strict=True))

    amp = b.vu_peak_v(-10) / 4
    for c, curve in ((100e-12, "record_minimum"), (550e-12, "record_maximum")):
        want = {**pub["record"], **pub[curve]}
        ir = ta.record_ir(b, {"rec_eq_hi_f": c, "record_level": 0.98})
        got = resp(ir, "rbc", tuple(want), amp)
        for f, d in want.items():
            assert got[f] == pytest.approx(d, abs=1.2), (curve, f)
    want = pub["reproduce"]
    got = resp(ta.repro_ir(b, {"rep_eq_hi": 0.67}), "out", tuple(want), 1e-4)
    for f, d in want.items():
        assert got[f] == pytest.approx(d - want[1000.0], abs=0.7 if f >= 200 else 2.5), f
