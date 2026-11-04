"""The Ampex 351 slap echo's circuit file (docs/DELAY_PLAN.md, "The 351 echo";
scripts/make_351_echo.py)."""

from __future__ import annotations

import importlib.util
import json

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT


def _generator():
    path = REPO_ROOT / "scripts" / "make_351_echo.py"
    s = importlib.util.spec_from_file_location("make_351_echo", path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def test_generated_files_are_current():
    m = _generator()
    for name, text in ((m.OUT, m.render()), (m.OUT_PINGPONG, m.render_pingpong())):
        assert spec.circuit_path(name).read_text(encoding="utf-8") == text, (
            f"stale {name}: rerun `uv run python scripts/make_351_echo.py`"
        )


def test_echo_is_the_aligned_351_with_a_console():
    c = spec.load_circuit(spec.circuit_path("ampex_351_echo"))
    al = json.loads((REPO_ROOT / "reports" / "tape" / "ampex_351_alignment.json").read_text())
    p = spec.resolve(c, {})
    for k, v in al["overrides"].items():
        assert p[k] == v
    ir = builder.build(c, cores="linear", noise=False).ir
    by_name = {e.name: (s, e) for s in ir.sections for e in s.elements}
    # The bus feeds the bridging input; the return's pot sits at the audio rate and only its
    # feed resistor in the multi-rate record side.
    assert by_name["RIN_S"][1].a == "rin"
    assert by_name["RSB"][0].substeps and by_name["RRB"][0].substeps
    rrep = [n for n in by_name if n.startswith("RREP")]
    assert rrep and all(by_name[n][0].substeps is None for n in rrep)


def test_live_build_plays_the_reduced_tape():
    """An events build (the live qualities): the oscillator and its network out, the record
    side at the audio rate, the tape on its reduction at the aligned bias; production keeps
    the literal machine."""
    from varimu.circuit import ir as irm

    c = spec.load_circuit(spec.circuit_path("ampex_351_echo"))
    live = builder.build(c, cores="linear", noise=False, events=True).ir
    prod = builder.build(c, cores="linear", noise=False).ir
    assert all(s.substeps is None for s in live.sections)
    assert any(s.substeps for s in prod.sections)
    names = {e.name for s in live.sections for e in s.elements}
    assert not names & {"XV6A", "XV6B", "LT5A", "LER", "C13"}
    (tape,) = [e for s in live.sections for e in s.elements if isinstance(e, irm.Tape)]
    m = tape.medium
    assert m.reduced is not None and m.bias_substeps is None and m.hg_bias_a_m > 0
    (lit,) = [e for s in prod.sections for e in s.elements if isinstance(e, irm.Tape)]
    assert lit.medium.reduced is None and lit.medium.bias_substeps == 20


def test_pingpong_is_two_machines_crossed():
    """The 351-2: two channels on one capstan supply, the send into the left only, each
    return into the other side; live, both tapes on the reduction."""
    from varimu.circuit import ir as irm

    c = spec.load_circuit(spec.circuit_path("ampex_351_2_echo"))
    for events in (False, True):
        ir = builder.build(c, cores="linear", noise=False, events=events).ir
        els = {e.name: e for s in ir.sections for e in s.elements}
        assert els["RRB"].a == "rpt_r" and els["RRB"].b == "rin"
        assert els["RRB_r"].a == "rpt" and els["RRB_r"].b == "rin_r"
        # A pot builds as its two halves (names after the part's).
        assert any(n.startswith("RSEND") and not n.startswith("RSEND_r") for n in els)
        assert not any(n.startswith("RSEND_r") for n in els)
        assert els["RSB_r"].a == "0" and els["RSB_r"].b == "rin_r"  # the bus loaded alike
        tapes = [e for e in els.values() if isinstance(e, irm.Tape)]
        assert len(tapes) == 2 and {t.supply for t in tapes} == {"cap_hz"}
        assert all(t.medium.track_m == 1.905e-3 for t in tapes)
        assert all((t.medium.reduced is not None) == events for t in tapes)
    assert {"out", "out_r"} <= set(c.probes)


def test_speed_switch():
    """The 351's speed switch: each speed its own tape part (a medium's cells are per bias
    wavelength) with its own reduction live; EQUAL SWITCH's contacts swap 1C7 for 1C46 in
    place (both trimmers always in the circuit)."""
    from varimu.circuit import ir as irm

    c = spec.load_circuit(spec.circuit_path("ampex_351_echo"))
    for speed, name, v in ((1, "VTP", 0.381), (0, "VTP_LO", 0.1905)):
        for events in (False, True):
            o = {"speed": speed, "equalization": speed}
            ir = builder.build(c, o, cores="linear", noise=False, events=events).ir
            els = {e.name: e for s in ir.sections for e in s.elements}
            (tape,) = [e for e in els.values() if isinstance(e, irm.Tape)]
            assert tape.name == name and tape.medium.speed_m_s == v
            assert tape.supply == "cap_hz"
            assert (tape.medium.reduced is not None) == events
            closed, open_ = ("RSEQ_HI", "RSEQ_LO") if speed else ("RSEQ_LO", "RSEQ_HI")
            assert els[closed].r_ohm < 1.0 and els[open_].r_ohm > 1e9
    # The full medium's cells follow the bias wavelength, the reduction's are its own.
    lo = builder.build(c, {"speed": 0}, cores="linear", noise=False).ir
    (t,) = [e for s in lo.sections for e in s.elements if isinstance(e, irm.Tape)]
    assert abs(t.medium.ds_m - 0.25e-6) < 1e-12


def test_live_slap_lands_a_head_distance_later():
    """A click through the live echo (REPEAT 0) at each speed: the slap a head distance over
    the speed later, plus the electronics' ~1 ms (the capstan's supply read every step: a
    run computing only its probes once read a stale supply, and the tape ran at a third of
    its speed)."""
    import numpy as np
    import pytest

    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    pytest.importorskip("circuitsim")
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    fs = st.sample_rate
    c = spec.load_circuit(spec.circuit_path("ampex_351_echo"))
    v_in, _ = c.full_scale
    k = int(0.02 * fs)
    for speed, expected_s in ((1, 0.0508 / 0.381), (0, 0.0508 / 0.1905)):
        x = np.zeros(int((expected_s + 0.06) * fs))
        t = np.arange(int(0.002 * fs)) / fs
        x[k : k + len(t)] = 0.5 * np.sin(2 * np.pi * 1000 * t) * np.hanning(len(t))
        o = {"speed": speed, "equalization": speed, "repeat": 0.0}
        ir = builder.build(c, o, cores="linear", noise=False, events=True).ir
        y = fast.run_transient(ir, x * v_in, settings=st).vectors["v(out)"]
        env = np.abs(y - np.median(y))
        lo = k + int(0.02 * fs)
        d = (lo + int(np.argmax(env[lo:])) - k) / fs
        assert expected_s < d < expected_s + 0.003, (speed, d)


def test_a_bias_turn_keeps_the_tape():
    """BIAS live: a turn of BIAS ADJUST between a click and its slap updates the stream in
    place (the reduced tape's bias for the blocks recorded from then on): the click already
    on the tape still comes back a head distance later, as if unturned."""
    import numpy as np
    import pytest

    from varimu.sim import fast
    from varimu.sim.io import TransientSettings

    circuitsim = pytest.importorskip("circuitsim")
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    fs = s.sample_rate
    c = spec.load_circuit(spec.circuit_path("ampex_351_echo"))
    v_in, _ = c.full_scale

    def ir_at(f):
        o = {"repeat": 0.0, "bias_adjust_f": f}
        return builder.build(c, o, cores="linear", noise=False, events=True).ir

    x = np.zeros(int(0.2 * fs))
    k = int(0.02 * fs)
    t = np.arange(int(0.002 * fs)) / fs
    x[k : k + len(t)] = 0.5 * np.sin(2 * np.pi * 1000 * t) * np.hanning(len(t))
    outs = []
    for turn in (False, True):
        ir = ir_at(31e-12)
        st = circuitsim.Stream(
            ir.to_json(),
            1.0 / s.sim_rate,
            0.0,
            s.method,
            solver=s.solver,
            reltol=s.newton_reltol,
            vntol=s.newton_vntol,
            input_order=s.input_order,
            newton_reuse=s.newton_reuse,
            tube_tables=s.tube_tables,
            partition=fast.partition_sections(ir, s) or None,
            partition_coupling=s.partition_coupling,
        )
        st.process(np.zeros(int(s.settle_s * fs)))
        half = int(0.06 * fs)  # after the click, before its slap (~134 ms)
        a = np.asarray(st.process(x[:half] * v_in)["v(out)"])
        if turn:
            st.update(ir_at(78e-12).to_json())
        b = np.asarray(st.process(x[half:] * v_in)["v(out)"])
        outs.append(np.concatenate([a, b]))
    y0, y1 = (np.abs(o - np.median(o)) for o in outs)
    lo = k + int(0.1 * fs)
    assert int(np.argmax(y1[lo:])) == int(np.argmax(y0[lo:]))
    assert y1[lo:].max() == pytest.approx(y0[lo:].max(), rel=0.05)
