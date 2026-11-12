"""The pedals (config/circuits/ibanez_ts808.yaml, fuzz_face.yaml) and their rigs
(scripts/make_pedal_rig.py): every value sourced, pre-flight clean, the TS808's DRIVE and its
symmetric clipping, the Fuzz Face's bias on its selected pair, and a rig's amp idling as the
amp alone, its jack at 0 V.
"""

import importlib.util

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, REPO_ROOT

CIRCUITS = CONFIG_DIR / "circuits"


def _load(name):
    return spec.load_circuit(CIRCUITS / f"{name}.yaml")


def _generator():
    path = REPO_ROOT / "scripts" / "make_pedal_rig.py"
    s = importlib.util.spec_from_file_location("make_pedal_rig", path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _run(c, x, **values):
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    st = TransientSettings.from_sim_settings(engine="circuitsim")
    ir = builder.build(c, spec.resolve(c, values)).ir
    return fast.run_transient(ir, x, settings=st).vectors


@pytest.mark.parametrize("name", ["ibanez_ts808", "fuzz_face"])
def test_pedals_build_and_check(name):
    c = _load(name)
    assert spec.check_genome_links(c) == []
    assert preflight.check_circuit(c) == []


def test_rigs_are_current_and_check():
    g = _generator()
    for pedal, amp in g.RIGS:
        path = g.out_path(pedal, amp)
        assert path.read_text(encoding="utf-8") == g.compose(pedal, amp), path.name
        assert preflight.check_circuit(spec.load_circuit(path)) == [], path.name


def test_ts808_drive_and_symmetric_clipping():
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    c = _load("ibanez_ts808")
    t = np.arange(19200) / 96000.0

    def measure(drive, amp):
        y = _run(c, amp * np.sin(2 * np.pi * 1000 * t), drive=drive, level=1.0)["v(out)"]
        y = y[len(t) // 2 :]
        sp = np.abs(np.fft.rfft(y * np.hanning(len(y))))
        f = np.fft.rfftfreq(len(y), 1 / 96000.0)
        h = [sp[np.argmin(abs(f - k * 1000))] for k in (1, 2, 3)]
        return 20 * np.log10(np.std(y) / (amp / np.sqrt(2))), h[1] / h[0], h[2] / h[0]

    # Measured 2026-11-12: 14.6 / 25.7 dB small-signal gain at DRIVE 0 / 1; at 0.3 V in the
    # third harmonic -22 dB, the second -57 dB (the antiparallel pair: symmetric).
    g0, _, _ = measure(0.0, 0.01)
    g1, _, _ = measure(1.0, 0.01)
    assert g1 > g0 + 8.0
    _, h2, h3 = measure(0.5, 0.3)
    assert h3 > 0.03 and h2 < 0.01


def test_fuzz_face_biases_on_its_selected_pair():
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    v = _run(_load("fuzz_face"), np.zeros(24000))
    mean = {k: float(np.mean(v[f"v({k})"][-4000:])) for k in ("c1", "e2", "c2")}
    # ElectroSmash's targets: Q1 collector -0.5..-0.7 V, Q2 emitter -0.5 V, Q2 collector
    # -4.5 V (measured 2026-11-12: -0.64, -0.50, -4.67 V).
    assert -0.75 < mean["c1"] < -0.45
    assert mean["e2"] == pytest.approx(-0.5, abs=0.1)
    assert mean["c2"] == pytest.approx(-4.5, abs=0.5)


def test_a_rig_idles_as_its_amp():
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    x = np.zeros(24000)
    rig = _run(_load("ibanez_ts808_marshall_1987"), x)
    amp = _run(_load("marshall_1987"), x)
    assert abs(np.mean(rig["v(jack)"][-4000:])) < 1e-3
    for node in ("b1", "bias", "p1b", "p2a"):
        a, b = (float(np.mean(v[f"v({node})"][-4000:])) for v in (rig, amp))
        assert a == pytest.approx(b, rel=1e-4), node
