"""The Minimoog voice with its own oscillators (docs/MINIMOOG_PLAN.md MM5): the oscillator board
(three oscillators, each an island at 96 kHz holding its event kernels), the mixer, the filter
board, the contours and the keyboard, as the app plays it (draft-1x, partitioned)."""

import dataclasses
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import ConfigError

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))


@pytest.mark.parametrize("script", ["make_minimoog_voice.py", "make_minimoog_oscillators.py"])
def test_generated_files_are_current(script):
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / script), "--check"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_oscillators_are_islands_only_with_their_kernels():
    """`substeps_in: events`: the island in a build with its kernels, the literal reference at the
    sample rate."""
    s = spec.load_circuit(spec.circuit_path("minimoog_voice"))
    p = spec.resolve(s, {"osc2_level": 0.5, "osc3_level": 0.5})  # all three heard
    k = {x.title: x for x in builder.build_ir(s, p, "linear").sections}
    lit = {x.title: x for x in builder.build_ir(s, p, "linear", literal=True).sections}
    for i in (1, 2, 3):
        assert k[f"osc {i}: core"].substeps == 2 and k[f"osc {i}: core"].decimate == "fir"
        assert lit[f"osc {i}: core"].substeps is None
    assert k["osc 3: shapers"].owns == ("o3_out", "o3_tri", "o3_rect")
    assert k["osc 3: reverse sawtooth"].substeps is None  # on the decimated sawtooth
    assert k["ladder"].substeps is None


def test_only_what_can_be_heard_is_built():
    """A section's `when` (docs/MINIMOOG_PLAN.md "Real time"): at the default panel oscillators 2
    and 3 (LEVEL 0), the noise (level 0) and the modulation mix (OSC MOD, FILTER MOD off) aren't
    built, R5 and R52 grounded by the switches' copies; the pre-amp is (EXT ON: its output loads
    the bus through R46 whatever its level). A LEVEL up, OSC MOD on, builds them."""
    s = spec.load_circuit(spec.circuit_path("minimoog_voice"))

    def built(over):
        ir = builder.build_ir(s, spec.resolve(s, over), "linear", events=True)
        return {x.title for x in ir.sections if x.elements}, ir

    on, ir = built({})
    for t in ("osc 2: core", "osc 3: core", "osc 3: reverse sawtooth", "noise: white"):
        assert t not in on
    assert {"osc 1: core", "external pre-amp", "modulation: grounds"} <= on
    assert "modulation mix" not in on and "panel: rails" not in on
    assert ir.sections[[x.title for x in ir.sections].index("osc 2: core")].substeps is None
    on, _ = built({"osc2_level": 0.3})
    assert "osc 2: core" in on and "osc 3: core" not in on
    on, _ = built({"osc2_level": 0.3, "osc2_on": 0})  # its switch off: not heard
    assert "osc 2: core" not in on
    on, _ = built({"osc_mod": 1})  # oscillator 3 into the wheel; the noise only with MOD MIX
    assert {"osc 3: core", "modulation mix"} <= on and "noise: white" not in on
    assert "modulation: grounds" not in on
    on, _ = built({"filter_mod": 1, "mod_mix": 0.5})
    assert {"osc 3: core", "noise: white", "modulation mix"} <= on
    on, _ = built({"ext_on": 0})
    assert "external pre-amp" not in on and "external input" in on


@pytest.mark.parametrize(
    "old, new, message",
    [
        ("  substeps: 2\n  decimate: fir\n", "  decimate: fir\n", "for a multi-rate section"),
        ("substeps_in: events", "substeps_in: later", "substeps_in 'later'"),
        ("  when: [osc_mod, filter_mod]", "  when: [osc_mod, nothing]", "when"),
        ("  when: [osc_mod, filter_mod]", "  when: osc_mod", "when"),
        ("- ['!osc_mod', '!filter_mod']", "- ['!osc_mod', []]", "when"),
    ],
)
def test_section_key_refusals(old, new, message, tmp_path):
    text = spec.circuit_path("minimoog_voice").read_text(encoding="utf-8")
    assert old in text
    bad = tmp_path / "bad.yaml"
    bad.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        spec.load_circuit(bad)


def _voice_run(note: int, seconds: float = 0.8, overrides=None):
    pytest.importorskip("circuitsim")
    import minimoog_gate_check as gc

    from varimu.sim import fast

    s = spec.load_circuit(spec.circuit_path("minimoog_voice"))
    ir = builder.build_ir(s, spec.resolve(s, overrides or {}), "linear")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"), VoltageProbe("o1_ramp")))
    import minimoog_vcf_study as vs

    st = dataclasses.replace(
        vs.settings("draft-1x"),
        newton_reltol=1e-5,
        newton_vntol=1e-5,
        partition=gc.VOICE_PARTITION,
        partition_coupling="hold",
    )
    fs = st.sample_rate
    n = int(seconds * fs)
    off, on = gc.gate_levels(s, "gate")
    gate = np.full(n, off)
    gate[int(0.2 * fs) :] = on
    key = np.full(n, gc.key_volts(s, note))
    r = fast.run_transient(ir, np.zeros(n), settings=st, controls={"key": key, "gate": gate})
    return fs, {k[2:-1]: np.asarray(v) for k, v in r.vectors.items()}


def test_the_voice_is_silent_until_a_key_and_plays_at_the_oscillators_pitch():
    """No key: nothing at the MAIN OUTPUT; a key (A3 on 8'): about 1.5 V peak (-18 dBFS at the
    file's full scale) and oscillator 1 at the stand-alone oscillator's pitch through the keyboard
    circuit (its file's key_* are that circuit's output), within a cent."""
    import minimoog_vco_trim as trim

    fs, v = _voice_run(57)
    out = v["out"]
    assert np.abs(out[int(0.05 * fs) : int(0.19 * fs)]).max() < 1e-3
    peak = np.abs(out[int(0.25 * fs) :]).max()
    assert 1.0 < peak < 2.2, peak
    full = spec.load_circuit(spec.circuit_path("minimoog_voice")).full_scale
    assert -21.0 < 20 * np.log10(peak / full[1]) < -15.0
    t = trim.falling_crossings(v["o1_ramp"][int(0.3 * fs) :], 2.5)
    f_voice = (len(t) - 2) / (t[-1] - t[1]) * fs
    f_alone = trim.target_hz(57, trim.RANGE_8)  # the trims hold it to equal temperament
    assert abs(trim.cents(f_voice, f_alone)) < 1.5, f_voice


def test_oscillator_3_control_and_reverse_sawtooth():
    """OSC 3 CONTROL off: oscillator 3 no longer follows the keys; REV SAW 3 OUT is the sawtooth
    upside down."""
    pytest.importorskip("circuitsim")
    import minimoog_vco_trim as trim

    from varimu.sim import fast, io

    s = spec.load_circuit(spec.circuit_path("minimoog_osc3"))
    d = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    st = dataclasses.replace(
        d, host_rate=48000, oversample=2, full_scale_volts_peak=1.0, newton_reltol=1e-3,
        newton_vntol=1e-3, settle_s=0.005,
    )  # fmt: skip
    hz = {}
    for control in (1, 0):
        for note in (45, 57):
            ir = builder.build_ir(s, spec.resolve(s, {"control": control}), "linear", events=True)
            ir = dataclasses.replace(
                ir, probes=tuple(VoltageProbe(p) for p in ("ramp", "out", "rsaw"))
            )
            n = int(0.25 * st.sample_rate)
            kv = np.full(n, trim.keyboard_volts(note))
            r = fast.run_transient(ir, np.zeros(n), settings=st, controls={"key": kv})
            ramp = np.asarray(r.vectors["v(ramp)"])[2000:]
            t = trim.falling_crossings(ramp, 2.5)
            hz[control, note] = (len(t) - 2) / (t[-1] - t[1]) * st.sample_rate
            if control == 1 and note == 45:
                out = np.asarray(r.vectors["v(out)"])[2000:]
                rsaw = np.asarray(r.vectors["v(rsaw)"])[2000:]
                assert np.corrcoef(out, rsaw)[0, 1] < -0.99
                assert np.ptp(rsaw) > 3.0
    assert abs(trim.cents(hz[1, 57], hz[1, 45]) - 1200) < 5  # an octave with the keys
    assert abs(trim.cents(hz[0, 57], hz[0, 45])) < 1  # none without
