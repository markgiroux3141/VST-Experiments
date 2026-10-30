"""The tube synth's voice (config/circuits/tube_voice.yaml; S3, docs/TUBE_SYNTH_PLAN.md):
tube_filter.yaml's filter with notes in. The keyboard bus (the `gate` control input,
-110 V no key, -1 V a key down) drives a diode-steered envelope into the center tap of an
interstage transformer whose secondary drives a push-pull 6386 VCA.

A 110 Hz saw at full scale (1 V peak) or silence, at draft-1x (what the app plays), the
gate down from 0.3 s to 0.9 s. Measured 2026-10-30 (attack / release rotations 0.2 / 0.4
unless said; dBFS re the 2.5 V output full scale):
- the envelope node -109.7 V with no key, -1.0 V held; 90% open in 1.6 ms (attack 0) to
  431 ms (0.7); back to 10% in 7 ms (release 0) to 313 ms (0.4). The level (a 440 Hz
  tone) rises 10-90% in 2.0 ms at attack 0, 52 ms at 0.2. Through a phase splitter's
  coupling capacitors and 2.2M grid leaks it took ~390 ms at any setting: they filtered
  the bias with a 220 ms time constant;
- the saw: -74 dBFS before the key (bleed), -7.3 dBFS held;
- silence: the gate's own thump ~1.3 mV peak (the envelope is common mode at the output
  transformer); hum with a key held 0.67 mV at 120 Hz (-71 dBFS).
"""

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.preflight import check_circuit
from varimu.sim import fast, io

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

from engine_compare import FS  # noqa: E402

CIRCUIT = Path(CONFIG_DIR / "circuits" / "tube_voice.yaml")
FULL_SCALE_V = 2.5
KEY_UP_V, KEY_DOWN_V = -110.0, -1.0
DUR_S, ON_S, OFF_S = 1.6, 0.3, 0.9


def run(x, probes=("out", "env"), **controls):
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {"cutoff": 0.5, **controls}))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft-1x"),
        full_scale_volts_peak=1.0,
    )
    t = np.arange(len(x)) / FS
    gate = np.where((t >= ON_S) & (t < OFF_S), KEY_DOWN_V, KEY_UP_V)
    return fast.run_transient(ir, x, settings=st, controls={"gate": gate}).vectors


def saw():
    t = np.arange(int(DUR_S * FS)) / FS
    return 2 * ((110 * t) % 1.0) - 1.0


def rms_dbfs(y, a, b):
    seg = y[int(a * FS) : int(b * FS)]
    return 20 * np.log10(np.sqrt(np.mean(seg**2)) / FULL_SCALE_V + 1e-15)


def test_passes_the_preflight_checks_with_its_gate():
    s = spec.load_circuit(CIRCUIT)
    assert s.cv_inputs == (("gate", "bus"),)
    assert check_circuit(s) == []


def test_a_key_opens_and_closes_the_vca():
    v = run(saw())
    y, env = v["v(out)"], v["v(env)"]
    before, held = rms_dbfs(y, 0.1, 0.29), rms_dbfs(y, 0.6, 0.89)
    print(before, held, env[int(0.29 * FS)], env[int(0.89 * FS)])
    assert env[int(0.29 * FS)] < -105 and env[int(0.89 * FS)] > -3
    assert -12 < held < -3 and before < held - 60


@pytest.mark.parametrize(("attack", "lo_ms", "hi_ms"), [(0.0, 0.5, 5), (0.7, 150, 500)])
def test_attack_sets_the_rise(attack, lo_ms, hi_ms):
    env = run(np.zeros(int(DUR_S * FS)), attack=attack)["v(env)"]
    lo, hi = env[int(0.29 * FS)], env[int(0.89 * FS)]
    t90 = np.argmax(env[int(ON_S * FS) :] > lo + 0.9 * (hi - lo)) / FS * 1e3
    print(attack, t90)
    assert lo_ms < t90 < hi_ms


@pytest.mark.parametrize(("release", "lo_ms", "hi_ms"), [(0.0, 2, 30), (0.4, 200, 600)])
def test_release_sets_the_fall(release, lo_ms, hi_ms):
    env = run(np.zeros(int(DUR_S * FS)), release=release, attack=0.0)["v(env)"]
    lo, hi = env[int(0.29 * FS)], env[int(0.89 * FS)]
    t10 = np.argmax(env[int(OFF_S * FS) :] < lo + 0.1 * (hi - lo)) / FS * 1e3
    print(release, t10)
    assert lo_ms < t10 < hi_ms


def test_the_gate_barely_thumps_and_the_voice_is_quiet():
    """Silence in: the push-pull VCA cancels the envelope's movement (common mode at the
    output transformer); a key held leaves the supply's hum well down."""
    y = run(np.zeros(int(DUR_S * FS)))["v(out)"]
    thump = np.max(np.abs(y[int(ON_S * FS) : int((ON_S + 0.1) * FS)]))
    tail = y[int(0.6 * FS) : int(0.89 * FS)]
    tail = tail - np.polyval(np.polyfit(np.arange(len(tail)), tail, 2), np.arange(len(tail)))
    sp = np.abs(np.fft.rfft(tail * np.hanning(len(tail)))) / len(tail) * 4
    hum = sp[round(120 / (FS / len(tail)))]
    print(f"thump {thump * 1e3:.2f} mV, hum {hum * 1e3:.3f} mV")
    assert thump < 0.02 * FULL_SCALE_V
    assert 20 * np.log10(hum / FULL_SCALE_V) < -65
