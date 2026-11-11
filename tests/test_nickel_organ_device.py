"""The Nickel Organ as a device (docs/NICKEL_ORGAN_DEVICE_PLAN.md): nickel_organ.yaml builds
with its keys as circuitsim's medium pinned to the compiled organ, and a note through the
whole circuit at draft quality (96 kHz, the keys stepped at 192 kHz) is the Python
reference voice's (varimu/nickel/voice.py) through its mixing gain, a sample late."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import CircuitIR, NickelKeys, VoltageProbe
from varimu.nickel import compile as ncompile
from varimu.preflight import check_circuit
from varimu.sim import io

circuitsim = pytest.importorskip("circuitsim")


def _ir(noise: bool | None = None):
    s = spec.load_circuit(spec.circuit_path("nickel_organ"))
    ir = builder.build_ir(s, spec.resolve(s, {}), noise=noise)
    return s, dataclasses.replace(ir, probes=(VoltageProbe("out"),))


def test_it_builds_with_the_keys_pinned_to_the_compiled_organ():
    s, ir = _ir()
    (el,) = [e for e in ir.elements() if isinstance(e, NickelKeys)]
    pinned = s.values["organ_model"]["value"]
    assert (el.data, el.sha256) == ncompile.ir_data(pinned)
    assert (el.out, el.rate_hz, el.step_hz) == ("out", 96000.0, 192000.0)
    assert (el.sustain, el.polarize) == (0.5, 0.35)
    assert 1 <= el.max_keys <= 128
    assert ir.noise is not None, "the keys' hiss is the circuit's noise"
    assert not check_circuit(s), "the pre-flight checks pass"
    back = CircuitIR.from_json(ir.to_json())
    assert back == ir, "the IR round-trips"


def test_a_note_through_the_circuit_is_the_reference_voices():
    from varimu.nickel import organ as norgan
    from varimu.nickel import spec as nspec
    from varimu.nickel import voice as nvoice
    from varimu.sim import fast

    st = io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    assert st.sim_rate == st.sample_rate == nvoice.FS_HZ, "draft steps at the keys' 96 kHz"
    fs = st.sample_rate
    s, ir = _ir(noise=False)
    (el,) = [e for e in ir.elements() if isinstance(e, NickelKeys)]
    sustain, polarize = 0.75, el.polarize
    ir = dataclasses.replace(
        ir,
        sections=tuple(
            dataclasses.replace(
                sec,
                elements=tuple(
                    dataclasses.replace(e, sustain=sustain) if isinstance(e, NickelKeys) else e
                    for e in sec.elements
                ),
            )
            for sec in ir.sections
        ),
    )
    note, vel = 69, 100
    n, on = int(0.08 * fs), int(0.005 * fs)
    st = dataclasses.replace(st, full_scale_volts_peak=1.0)
    y = np.asarray(
        fast.run_transient(
            ir, np.zeros(n), settings=st, notes=[(on / fs, "on", note, vel)]
        ).vectors["v(out)"]
    )
    key = next(
        k for k in ncompile.load(s.values["organ_model"]["value"])["keys"] if k["note"] == note
    )
    vc = nvoice.make_voice(note, nspec.load(), noise=False, oversample=2)
    vc.trim = key["trim"]
    norgan._power_on(vc, polarize)
    vc.strike(vel)
    ref = np.zeros(n)
    ref[on + 1 :] = key["mix"] * vc.run(n - on - 1, sustain=sustain, polarize=polarize)
    assert np.max(np.abs(ref)) > 1e-2, "the reference sounds"
    err = np.sqrt(np.mean((y - ref) ** 2) / np.mean(ref**2))
    assert 20 * np.log10(max(err, 1e-300)) < -100, f"{20 * np.log10(err):.1f} dB"
