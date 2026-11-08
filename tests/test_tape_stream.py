"""The tape stream (docs/TAPE_PLAN.md, TM4): `varimu.devices.tape_machine.TapeStream`, the
reference, against circuitsim's port (`tape_stream_run`), on a small machine (short poles,
short blocks, two layers) so the reference's own recording kernel runs in seconds."""

from __future__ import annotations

import dataclasses
import json
import math

import numpy as np
import pytest

from varimu.devices import library
from varimu.devices.tape import Orientation
from varimu.devices.tape_machine import TapeMachineSpec, TapeStream, stream_params

FS = 96_000.0
OE = 1000.0 / (4.0 * math.pi)


def _small():
    spec = TapeMachineSpec(
        pole_m=50e-6,
        relax_m=50e-6,
        layers=2,
        table_step=0.0,
        zone_floor_oe=120.0,
        local_zones=True,
        demag_iterations=3,
        block_m=0.4e-3,
        margin_m=0.1e-3,
        head_distance_m=3e-3,
    )
    tape = library.load_tape("SCOTCH111@2")
    tape = dataclasses.replace(tape, orientation=Orientation(tape.orientation.kappa, 3))
    n = int(0.016 * FS)
    t = np.arange(n) / FS
    # A swell into a 1 kHz tone with some 7 kHz on it (deep-gap A/m).
    h = (300 * np.sin(2 * math.pi * 1000 * t) + 80 * np.sin(2 * math.pi * 7000 * t)) * OE
    h *= np.clip(t / 0.008, 0.05, 1.0)
    return spec, tape, h, 750 * OE


def _rust():
    try:
        import circuitsim
    except ImportError:
        pytest.skip("circuitsim isn't built (uv sync --extra fast)")
    if not hasattr(circuitsim, "tape_stream_run"):
        pytest.skip("circuitsim is older than the tape stream")
    return circuitsim


def _medium(spec, tape, bias):
    """The IR's TapeMedium of `stream_params` (its rows as tuples, as the IR decodes them)."""
    from varimu.circuit.ir import TapeMedium

    p = stream_params(spec, tape, bias)
    for k in ("flutter", "flutter_noise"):
        p[k] = tuple(tuple(r) for r in p[k])
    return TapeMedium(**p)


def _rel(a, b) -> float:
    return float(np.abs(a - b).max() / np.abs(b).max())


def test_the_rust_stream_agrees_with_the_reference():
    """Python's stream (its own kernel and circuitsim's) against circuitsim's stream."""
    cs = _rust()
    spec, tape, h, bias = _small()
    ref = TapeStream(spec, tape, bias, FS, engine="python").push_many(h)
    kern = TapeStream(spec, tape, bias, FS, engine="rust").push_many(h)
    port = np.asarray(cs.tape_stream_run(json.dumps(stream_params(spec, tape, bias)), FS, h))
    assert np.abs(ref).max() > 0 and (ref[: int(0.007 * FS)] == 0).all()
    assert _rel(kern, ref) < 1e-11
    assert _rel(port, ref) < 1e-11


def test_chunking_changes_nothing():
    cs = _rust()
    spec, tape, h, bias = _small()
    params = json.dumps(stream_params(spec, tape, bias))
    whole = np.asarray(cs.tape_stream_run(params, FS, h, chunk=len(h)))
    for chunk in (1, 37):
        np.testing.assert_array_equal(np.asarray(cs.tape_stream_run(params, FS, h, chunk)), whole)
    st = TapeStream(spec, tape, bias, FS, engine="rust")
    parts = [st.push_many(h[i : i + 101]) for i in range(0, len(h), 101)]
    np.testing.assert_array_equal(
        np.concatenate(parts), TapeStream(spec, tape, bias, FS, engine="rust").push_many(h)
    )


def test_the_heads_must_leave_room_for_the_blocks():
    spec, tape, _, bias = _small()
    with pytest.raises(ValueError, match="too close"):
        TapeStream(dataclasses.replace(spec, head_distance_m=2e-3), tape, bias, FS)
    with pytest.raises(ValueError, match="reach"):
        TapeStream(dataclasses.replace(spec, pole_m=1e-3), tape, bias, FS)
    cs = _rust()
    p = stream_params(dataclasses.replace(spec, head_distance_m=2e-3), tape, bias)
    with pytest.raises(ValueError, match="too close"):
        cs.tape_stream_run(json.dumps(p), FS, np.zeros(10))


def test_the_print_through_the_port_equals_the_reference():
    """`print_audio` with the whole stream in circuitsim against the reference stream on
    circuitsim's kernel."""
    from varimu.devices.tape_machine import Alignment, print_audio

    _rust()
    spec, tape, _, bias = _small()
    al = Alignment(bias, 200 * OE, 1e-5, 0.0, 1.0)
    # Gentle: the small machine's short poles put the pole edges near the floor.
    x = 0.05 * np.sin(2 * math.pi * 440 * np.arange(int(0.006 * FS)) / FS)
    a = print_audio(x, FS, spec, tape, al, engine="circuitsim")
    b = print_audio(x, FS, spec, tape, al, engine="rust")
    assert np.abs(b).max() > 0
    assert _rel(a, b) < 1e-11


def test_the_ir_element_runs_the_stream():
    """A `Tape` in a circuit (the small machine) sensing a divider's midpoint: its repro
    output equals the reference stream fed the sensed voltage, one sample later; the IR
    round-trips through JSON in both languages."""
    from varimu.circuit.ir import (
        IR_VERSION,
        CircuitIR,
        Resistor,
        Section,
        Tape,
        VoltageProbe,
    )

    cs = _rust()
    spec, tape, h, bias = _small()
    h_per_v = 2e4 * OE
    els = (
        Resistor("R1", "in", "s", 100.0),
        Resistor("R2", "s", "0", 100.0),
        Tape("VTP", "s", "0", h_per_v, "p", _medium(spec, tape, bias)),
        Resistor("RO", "p", "o", 1e3),
        Resistor("RL", "o", "0", 1e3),
    )
    ir = CircuitIR(
        version=IR_VERSION,
        title="tape",
        input_node="in",
        probes=(VoltageProbe("o"), VoltageProbe("s")),
        models=(),
        sections=(Section("tape", els),),
    )
    ir.validate()
    assert CircuitIR.from_json(ir.to_json()) == ir
    assert cs.ir_roundtrip(ir.to_json()) is not None
    out = cs.simulate(ir.to_json(), 2.0 * h / h_per_v, 1.0 / FS, "esdirk4", input_order=1)
    sensed, got = np.asarray(out["v(s)"]), np.asarray(out["v(o)"])
    want = 0.5 * TapeStream(spec, tape, bias, FS, engine="rust").push_many(h_per_v * sensed)
    assert np.abs(want).max() > 0
    assert got[0] == 0.0
    assert _rel(got[1:], want[:-1]) < 1e-9


def test_the_test_circuit_builds_with_the_repro_head_cut_out_in_spice():
    from varimu.circuit import builder
    from varimu.circuit.ir import Tape
    from varimu.circuit.spec import load_circuit
    from varimu.config import REPO_ROOT

    c = builder.build(
        load_circuit(REPO_ROOT / "config" / "circuits" / "tape_test.yaml"), cores="linear"
    )
    tapes = [el for el in c.ir.elements() if isinstance(el, Tape)]
    assert [t.name for t in tapes] == ["VTP"]
    assert tapes[0].medium.demag_iterations == 8 and tapes[0].sense_pos == "tp_a"
    assert "VTP tp_e 0 dc 0" in c.text


def _grainy(tape):
    from varimu.devices.tape import TapeNoise

    # Provisional, for the tests: ~1e6 particles per 1 um cell of the small machine.
    return dataclasses.replace(tape, noise=TapeNoise(4.7e-21, 0.35, 0.05, 20e-6))


def test_the_grain_agrees_and_is_seeded():
    cs = _rust()
    spec, tape, h, bias = _small()
    tape = _grainy(tape)
    params = json.dumps(stream_params(spec, tape, bias))
    ref = TapeStream(spec, tape, bias, FS, engine="rust", noise_seed=7).push_many(h)
    port = np.asarray(cs.tape_stream_run(params, FS, h, noise_seed=7))
    clean = np.asarray(cs.tape_stream_run(params, FS, h))
    again = np.asarray(cs.tape_stream_run(params, FS, h, chunk=33, noise_seed=7))
    other = np.asarray(cs.tape_stream_run(params, FS, h, noise_seed=8))
    assert _rel(port, ref) < 1e-11
    np.testing.assert_array_equal(again, port)
    assert 1e-6 < _rel(port, clean) < 0.3 and _rel(other, port) > 1e-6
    with pytest.raises(ValueError, match="noise block"):
        TapeStream(spec, _small()[1], bias, FS, noise_seed=7)


def test_the_ir_element_takes_the_circuits_noise():
    """With the circuit's noise on, the element's grain is keyed by (its seed, its name)."""
    from varimu.circuit.ir import (
        IR_VERSION,
        CircuitIR,
        NoiseSpec,
        Resistor,
        Section,
        Tape,
        VoltageProbe,
    )

    cs = _rust()
    spec, tape, h, bias = _small()
    tape = _grainy(tape)
    h_per_v = 2e4 * OE
    els = (
        Resistor("R1", "in", "s", 100.0),
        Resistor("R2", "s", "0", 100.0),
        Tape("VTP", "s", "0", h_per_v, "o", _medium(spec, tape, bias)),
        Resistor("RL", "o", "0", 1e3),
    )
    ir = CircuitIR(
        version=IR_VERSION,
        title="tape",
        input_node="in",
        probes=(VoltageProbe("o"), VoltageProbe("s")),
        models=(),
        sections=(Section("tape", els),),
        noise=NoiseSpec(seed=11, rate_hz=FS),
    )
    ir.validate()
    out = cs.simulate(ir.to_json(), 2.0 * h / h_per_v, 1.0 / FS, "esdirk4", input_order=1)
    sensed, got = np.asarray(out["v(s)"]), np.asarray(out["v(o)"])
    st = TapeStream(
        spec, tape, bias, FS, engine="rust", noise_seed=11, noise_name="VTP", transport_seed=11
    )
    want = st.push_many(h_per_v * sensed)
    assert _rel(got[1:], want[:-1]) < 1e-9


def test_erased_tape_carries_the_particles_variance():
    """Silent tape without bias records nothing: its cells hold the particles' Poisson
    grain alone, sum_j w_j cos^2 phi_j / N per cell (N particles per cell)."""
    spec, tape, _, _ = _small()
    tape = _grainy(tape)
    st = TapeStream(spec, tape, 0.0, FS, engine="rust", noise_seed=3)
    st.push_many(np.zeros(int(0.012 * FS)))
    mx = np.concatenate([b[0] for b in st.rec.values()], axis=1)
    nz = tape.noise
    n_cell = nz.packing * spec.ds_m * (tape.coating_m / spec.layers) * spec.track_m
    n_cell /= nz.particle_volume_m3
    cs, _, wt = tape.orientation.axes()
    want = math.sqrt(float(np.sum(wt * cs * cs)) / n_cell)
    assert mx.size > 2000
    assert abs(mx.std() / want - 1.0) < 0.05


def test_the_transports_flutter_is_the_351s():
    """The speed's 0.5-250 Hz rms, 0.08%, the size that makes a tone recorded and played
    back deviate the 351's 0.11% (scripts/tape_flutter.py), scrape flutter above it; no
    flutter: the tape runs at its speed exactly."""
    spec, tape, _, bias = _small()
    st = TapeStream(TapeMachineSpec(), tape, bias, FS)
    eps = st._speeds(1, int(20 * FS)) / 0.381 - 1.0
    k = np.fft.rfft(eps)
    f = np.fft.rfftfreq(len(eps), 1 / FS)

    def rms(lo, hi):
        m = (f >= lo) & (f <= hi)
        return math.sqrt(2 * float(np.sum(np.abs(k[m]) ** 2))) / len(eps)

    assert 0.075e-2 < rms(0.5, 250) < 0.095e-2
    assert 0.02e-2 < rms(250, 10e3) < 0.04e-2
    still = TapeStream(dataclasses.replace(spec, flutter=False), tape, bias, FS)
    assert not still.moving


def _literal(m: int, phase: float = 0.3):
    """The small machine's signal plus its bias as one field at m samples per step (the
    literal bias, TM5's option A): fast sample k at (k + 1 - 2 m) / (m FS)."""
    spec, tape, h, bias = _small()
    n = len(h)
    k = np.arange(n * m)
    t = (k + 1 - 2 * m) / (m * FS)
    # The signal at the fast times: the same expression as _small's (its envelope too).
    sig = (300 * np.sin(2 * math.pi * 1000 * t) + 80 * np.sin(2 * math.pi * 7000 * t)) * OE
    sig *= np.clip(t / 0.008, 0.05, 1.0)
    hf = sig + bias * np.sin(2 * math.pi * spec.f_bias_hz * t + phase)
    return spec, tape, hf, bias, h, phase


def test_the_literal_rust_stream_agrees_with_the_reference():
    """The literal bias: Python's stream against circuitsim's on the head's whole field."""
    cs = _rust()
    m = 16
    spec, tape, hf, _, _, _ = _literal(m)
    ref = TapeStream(spec, tape, 0.0, FS, engine="python", literal=m).push_many(hf)
    kern = TapeStream(spec, tape, 0.0, FS, engine="rust", literal=m).push_many(hf)
    p = stream_params(spec, tape, 0.0)
    p["bias_substeps"] = m
    port = np.asarray(cs.tape_stream_run(json.dumps(p), FS, hf, chunk=16 * m))
    assert len(ref) == len(hf) // m and np.abs(ref).max() > 0
    assert _rel(kern, ref) < 1e-11
    assert _rel(port, ref) < 1e-11
    with pytest.raises(ValueError, match="literal"):
        cs.tape_stream_run(json.dumps(p), FS, hf[:-1])


def test_the_extremum_refinement_is_quartic():
    """The literal bias's peak values (TAPE_PLAN.md "Gaps" 4): on a carrier at 20.7 samples
    per period (the 351's 92.9 kHz at 10 substeps) plus a slow offset, over every sampling
    phase, the quartic through five samples finds the peak within 4e-6 of the carrier (its
    interpolation error, ~h^6: 6e-8 at 41.3 samples); the parabola through three was off by
    up to 2e-4 (its error, beating against the oscillator, was a -78.6 dBFS line in the
    351's noise)."""
    from varimu.devices.tape_machine import parabola_extremum, refine_extremum

    w = 2 * math.pi / 20.7
    quartic, parabola = [], []
    for phase in np.linspace(-0.5, 0.5, 41):
        y = [0.2 + math.cos(w * (k - phase)) for k in (-2, -1, 0, 1, 2)]
        d, v = refine_extremum(*y)
        assert d == pytest.approx(phase, abs=5e-5)
        quartic.append(abs(v - 1.2))
        parabola.append(abs(parabola_extremum(*y[1:4])[1] - 1.2))
    assert max(quartic) < 5e-6
    assert 1e-4 < max(parabola) < 1e-3


def test_the_literal_bias_finds_the_carriers_peaks():
    """Fed an ideal carrier, the literal stream records about what the medium's own bias
    does: the refined peaks converge with the samples per step (32 against 64), and the
    rest is the physics the own bias leaves out (the extrema of bias plus signal move with
    the signal's slope; it takes the carrier's peaks and the signal there): 0.34% here."""
    _rust()

    def lit(m):
        spec, tape, hf, _, _, _ = _literal(m)
        return TapeStream(spec, tape, 0.0, FS, engine="rust", literal=m).push_many(hf)

    spec, tape, hf, bias, h, phase = _literal(32)
    own = TapeStream(spec, tape, bias, FS, engine="rust", bias_phase=phase).push_many(h)
    l32, l64 = lit(32), lit(64)
    assert _rel(l32, l64) < 2e-4
    assert 1e-3 < _rel(l64, own) < 5e-3
    st = TapeStream(spec, tape, 0.0, FS, engine="rust", literal=32)
    st.push_many(hf[: len(hf) // 2 // 32 * 32])
    tp, _ = st.literal_peaks(0.004, 0.005)
    # The extrema of bias plus signal move with the signal's slope (here up to ~0.4%).
    assert np.allclose(np.diff(tp), 0.5 / spec.f_bias_hz, rtol=1e-2)


def test_a_multirate_part_feeds_the_literal_bias():
    """The literal bias through circuitsim's multi-rate partition: a section of M steps
    per sample drives the "record head" node with an ideal bias plus a tone; the tape in
    the audio part senses it remotely. Its output equals the reference stream fed the same
    fast samples (the DC point's twice, then each sample's M steps), one sample later."""
    pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")
    from varimu.circuit.ir import CircuitIR, Resistor, Section, SineSource, Tape, VoltageProbe
    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    m = 16
    spec, tape, _, bias = _small()
    medium = dataclasses.replace(_medium(spec, tape, 0.0), bias_substeps=m)
    sig = 300 * OE
    ir = CircuitIR(
        title="literal bias",
        input_node="in",
        probes=(VoltageProbe("out"),),
        models=(),
        sections=(
            Section(
                "audio",
                (
                    Resistor("RIN", "in", "0", 1e3),
                    Resistor("RL", "out", "0", 1e6),
                    Resistor("RLINKA", "link", "0", 1e6),
                    Tape("VTP", "hp", "0", 1.0, "out", medium),
                ),
            ),
            Section(
                "head",
                (
                    SineSource("VB", "hpa", "0", 0.0, bias, spec.f_bias_hz, 0.0),
                    SineSource("VS", "hp", "hpa", 0.0, sig, 1000.0, 0.0),
                    Resistor("RH", "hp", "0", 1e3),
                    Resistor("RLINKB", "link", "0", 1e6),
                ),
                m,
            ),
        ),
    )
    n = int(0.016 * FS)
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    s = dataclasses.replace(s, sample_rate=int(FS), oversample=1, settle_s=0.0)
    out = fast.run_transient(ir, np.zeros(n), settings=s).vectors["v(out)"]
    # The reference: two DC batches (the sources' values at t = 0: 0 V), then each
    # sample's steps, at (k + 1) / (m FS) for k = 0, 1, ...
    t = (np.arange((n - 1) * m) + 1) / (m * FS)
    hf = np.concatenate(
        [np.zeros(2 * m), bias * np.sin(2 * math.pi * spec.f_bias_hz * t)
         + sig * np.sin(2 * math.pi * 1000.0 * t)]
    )  # fmt: skip
    ref = TapeStream(spec, tape, 0.0, FS, engine="rust", literal=m).push_many(hf)
    # Push k's EMF drives sample k + 1 (push 0 at the DC point).
    assert np.abs(ref).max() > 0
    assert _rel(out[1:], ref[: n - 1]) < 1e-6


def test_a_streams_origin_moves_only_what_depends_on_time():
    """`origin` (TAPE_SPEED_PLAN.md P3): the stream starts at that step of a longer run. A
    stream without grain or flutter doesn't depend on time: the same output. The flutter's
    phase and noise continue from there: other speeds, the same level. The grain
    comes from cells further along the tape: the same coating, other cells."""
    cs = _rust()
    spec, tape, h, bias = _small()
    still = dataclasses.replace(spec, flutter=False)
    plain = json.dumps(stream_params(still, tape, bias))
    base = np.asarray(cs.tape_stream_run(plain, FS, h))
    for k in (0, 96_000):
        got = np.asarray(cs.tape_stream_run(plain, FS, h, origin=k))
        np.testing.assert_array_equal(got, base)
    moving = json.dumps(stream_params(spec, tape, bias))
    f0 = np.asarray(cs.tape_stream_run(moving, FS, h, transport_seed=3))
    fk = np.asarray(cs.tape_stream_run(moving, FS, h, transport_seed=3, origin=96_000))
    assert _rel(fk, f0) > 1e-9 and abs(np.std(fk) / np.std(f0) - 1.0) < 0.05
    grainy = json.dumps(stream_params(still, _grainy(tape), bias))
    g0 = np.asarray(cs.tape_stream_run(grainy, FS, h, noise_seed=7))
    gk = np.asarray(cs.tape_stream_run(grainy, FS, h, noise_seed=7, origin=96_000))
    assert _rel(gk, g0) > 1e-6
    assert abs(np.std(gk - base) / np.std(g0 - base) - 1.0) < 0.5
