"""The Ampex 351's direct monitor as a microphone preamp (docs/CHAINS_PLAN.md, WP7;
scripts/make_351_record.py, scripts/a351_record_trim.py)."""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT

NAME = "ampex_351_record"
# The drawing's DC voltages (sch p 95, record mode, the oscillator removed; the manual: 3K1b
# keeps B+ "nearly constant in any mode"), as tests/test_ampex_351.py reads them.
PRINTED = {
    "b330": 330, "b300": 300, "b250": 250, "b220": 220, "p1b": 170, "k1b": 1.4, "p1a": 170,
    "k1a": 1.6, "p4a": 110, "k4a": 1.0, "p5a": 295, "p5b": 295, "k5": 13,
}  # fmt: skip
LOOSE = {"p4b": 90}  # the drawing's hot 12AX7 (tests/test_ampex_351.py, LOOSE)


def _script(name: str):
    path = REPO_ROOT / "scripts" / f"{name}.py"
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def circuit():
    return spec.load_circuit(spec.circuit_path(NAME))


def _fast():
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    return fast, TransientSettings.from_sim_settings(engine="circuitsim")


def _tone_rms(c, over, node, f_hz, in_v_rms):
    fast, st = _fast()
    fs = st.sample_rate
    t = np.arange(int(0.6 * fs)) / fs
    x = in_v_rms * np.sqrt(2) * np.sin(2 * np.pi * f_hz * t)
    v = fast.run_transient(builder.build_ir(c, spec.resolve(c, over)), x, settings=st).vectors
    from varimu.measure import metrics

    h = metrics.harmonics(v[f"v({node})"][-int(0.25 * fs) :], f_hz, fs)
    return float(h.amps[0] / np.sqrt(2))  # the fundamental (a plate still settles below it)


def test_generated_file_is_current():
    m = _script("make_351_record")
    assert spec.circuit_path(NAME).read_text(encoding="utf-8") == m.render(), (
        "stale: rerun `uv run python scripts/make_351_record.py`"
    )


def test_builds_and_passes_the_checks(circuit):
    for cores in ("ja", "linear"):
        ir = builder.build(circuit, cores=cores).ir
    names = {e.name for s in ir.sections for e in s.elements}
    # Out of record mode: no oscillator, head driver, heads or tape; nothing multi-rate.
    assert not names & {"XV6A", "XV6B", "XV2A", "LT5A", "TP"}
    assert all(s.substeps is None for s in ir.sections)
    assert preflight.check_circuit(circuit) == []
    assert circuit.full_scale == pytest.approx((1.0960, 17.36), rel=1e-4)


def test_idles_near_the_printed_voltages(circuit):
    fast, st = _fast()
    x = np.zeros(int(0.1 * st.sample_rate))
    v = fast.run_transient(builder.build(circuit, cores="linear").ir, x, settings=st).vectors
    n = int(0.05 * st.sample_rate)
    for node, d in PRINTED.items():
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(d, rel=0.20), node
    for node, d in LOOSE.items():
        assert np.mean(v[f"v({node})"][-n:]) == pytest.approx(d, rel=0.40), node


def test_record_calibrate_reads_operating_level(circuit):
    """-10 dBm into the unbalanced bridge at the aligned RECORD LEVEL gives +8 dBm out (the
    manual's RECORD CALIBRATE), and the microphone input then needs ~200 uV (man p 11) at
    full RECORD LEVEL."""
    out = _tone_rms(circuit, {"input_transfer": 1}, "out", 500.0, 0.2449)
    assert 20 * np.log10(out / 1.9494) == pytest.approx(0.0, abs=0.1)
    g = _tone_rms(circuit, {"record_level": 1.0}, "out", 1000.0, 1e-4) / 1e-4
    assert 1.9494 / g == pytest.approx(200e-6, rel=0.26)  # within 2 dB


def test_stage_levels_follow_the_drawing(circuit):
    """sch p 95: -80 dB re 0.78 V at 5J1 (500 Hz, full RECORD LEVEL, MICROPHONE) reads -57 at
    1V1b's grid, -35 at 1V1a's, -12 at 1V1a's plate."""
    vin = 0.78 * 10 ** (-80 / 20)
    for node, d in (("g1b", -57.0), ("g1a", -35.0), ("p1a", -12.0)):
        got = 20 * np.log10(_tone_rms(circuit, {"record_level": 1.0}, node, 500.0, vin) / 0.78)
        assert got == pytest.approx(d, abs=2.0), node


def test_input_transfer_switches_the_path(circuit):
    """At MICROPHONE the bridge is off the pins (and 6T1 at the bridge): each input's signal
    reaches RECORD LEVEL only through its own path."""
    mic = _tone_rms(circuit, {"input_transfer": 0}, "ib", 1000.0, 1e-3)
    bridge = _tone_rms(circuit, {"input_transfer": 1}, "ib", 1000.0, 1e-3)
    g1b_at_bridge = _tone_rms(circuit, {"input_transfer": 1}, "g1b", 1000.0, 1e-3)
    assert 20 * np.log10(mic / 1e-3) == pytest.approx(44.5, abs=2.0)  # 6T1 + 1V1b
    assert 20 * np.log10(bridge / 1e-3) == pytest.approx(-15.4, abs=0.5)  # 4R5 / 4R4 || 4R9
    assert g1b_at_bridge < 1e-6
