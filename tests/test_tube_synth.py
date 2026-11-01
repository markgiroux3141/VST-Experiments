"""The tube synth (config/circuits/tube_synth.yaml; S4, docs/TUBE_SYNTH_PLAN.md):
tube_voice.yaml's voice with S4's candidate (b), the reactor-tuned LC oscillator, on the
voice's one supply. The keys give both control inputs: `gate` (the keyboard bus) and
`pitch` (the 6V6GT's grid through the keyboard tuning, varimu-app's `panel::Pitch`).

At draft with the native app's partition (the VCA, the filter, the oscillator, the LFO,
the supplies), measured 2026-10-30: the pitch ~59 Hz at -23 V, ~479 Hz at -15 V, ~1739 Hz
at 0 V (reports/tube_synth/vco/synth_tuning.json); below -23 V the tank's swing saturates
the cores. Since #7 (2026-11-01) VIBRATO's summing scales the key string by 0.979: ~497 Hz
at -15 V (synth_tuning_high.json). The 6V6GT's screen is on two 5651s: on b3 the VCA's opening
sagged it and a held note fell ~780 cents over ~2 s; regulated, ~19 cents. A held key at
-15 V: ~-11 dBFS out at the panel's defaults; key up, the VCA's bleed ~-80 dBFS or less.
"""

import dataclasses
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.preflight import check_circuit
from varimu.sim import fast, io
from varimu.synth import vco

pytest.importorskip("circuitsim", reason="needs `uv sync --extra fast`")

CIRCUIT = Path(CONFIG_DIR / "circuits" / "tube_synth.yaml")
FS = 96000
FULL_SCALE_V = 3.5
PARTITION = (
    "resonance",
    "|",
    "input",
    "filter",
    "cutoff",
    "envelope",
    "|",
    "ring",
    "|",
    "oscillator",
    "pitch",
    "|",
    "lfo",
    "|",
    "power supply",
    "bias supply",
)  # the native app's (panel.rs)
KEY_UP_V, KEY_DOWN_V = -110.0, -1.0


def run(pitch_v, dur_s=1.0, on_s=0.2):
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {}), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("out"), VoltageProbe("o_t")))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(dur_s * FS)
    t = np.arange(n) / FS
    gate = np.where(t >= on_s, KEY_DOWN_V, KEY_UP_V)
    v = fast.run_transient(
        ir,
        np.zeros(n),
        settings=st,
        controls={
            "gate": gate,
            "pitch": np.full(n, pitch_v),
            "key": np.zeros(n),
            "pressure": np.zeros(n),
        },
    ).vectors
    return v["v(out)"], v["v(o_t)"]


def rms_dbfs(y):
    return 20 * np.log10(np.sqrt(np.mean((y - y.mean()) ** 2)) / FULL_SCALE_V + 1e-15)


def test_passes_the_preflight_checks_with_its_gate_and_pitch():
    s = spec.load_circuit(CIRCUIT)
    assert s.cv_inputs == (("gate", "bus"), ("pitch", "pv"), ("key", "kv"), ("pressure", "av"))
    assert check_circuit(s) == []


def test_a_key_sounds_the_oscillator_at_its_pitch():
    out, tank = run(-15.0)
    held, before = out[int(0.5 * FS) :], out[int(0.02 * FS) : int(0.18 * FS)]
    f = vco.frequency(tank[int(0.5 * FS) :], FS)
    print(f, rms_dbfs(held), rms_dbfs(before))
    assert abs(vco.cents(f, 497.5)) < 30
    assert -20 < rms_dbfs(held) < -3
    assert rms_dbfs(before) < rms_dbfs(held) - 50


def test_a_key_barely_moves_the_cutoff_driver():
    """V4's screen is on its own 5651s: the VCA's sag on b1 no longer pulls its current
    (and the cutoff) down while a key is held (on b1 at CUTOFF 0.15: 0.86 -> 0.39 mA,
    ~800 cents of cutoff; regulated ~10%, ~140 cents)."""
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {"cutoff": 0.15}), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("k4"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(1.5 * FS)
    t = np.arange(n) / FS
    gate = np.where(t >= 0.5, KEY_DOWN_V, KEY_UP_V)
    k4 = fast.run_transient(
        ir,
        np.zeros(n),
        settings=st,
        controls={
            "gate": gate,
            "pitch": np.full(n, -15.0),
            "key": np.zeros(n),
            "pressure": np.zeros(n),
        },
    ).vectors["v(k4)"]
    up, held = np.mean(k4[int(0.3 * FS) : int(0.5 * FS)]), np.mean(k4[int(1.3 * FS) :])
    print(up, held)  # V4's cathode current in mA (1k)
    assert 0.85 < held / up < 1.0


@pytest.mark.parametrize("amount", [0.0, 1.0])
def test_env_amount_adds_control_current_only_while_the_envelope_is_open(amount):
    """ENV AMOUNT: V7 beside V4 on the control windings, its grid on the envelope, AMOUNT
    its screen. At 0 it never conducts; at 1 it adds ~10 mA with a key held (CUTOFF 0.15:
    ~600 Hz -> ~4 kHz) and stops within a few ms of the release."""
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(
        s, spec.resolve(s, {"cutoff": 0.15, "env_amount": amount, "release": 0.0}), cores="ja"
    )
    ir = dataclasses.replace(ir, probes=(VoltageProbe("k7"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(1.0 * FS)
    t = np.arange(n) / FS
    gate = np.where((t >= 0.2) & (t < 0.6), KEY_DOWN_V, KEY_UP_V)
    i7 = (
        fast.run_transient(
            ir,
            np.zeros(n),
            settings=st,
            controls={
                "gate": gate,
                "pitch": np.full(n, -15.0),
                "key": np.zeros(n),
                "pressure": np.zeros(n),
            },
        ).vectors["v(k7)"]
        / 2.2
    )  # mA, V7's cathode (2.2k)
    up, held, after = i7[int(0.15 * FS)], i7[int(0.55 * FS)], i7[int(0.7 * FS)]
    print(amount, up, held, after)
    assert abs(up) < 0.01 and abs(after) < 0.01
    if amount == 0.0:
        assert abs(held) < 0.01
    else:
        assert 7.0 < held < 13.0


def test_a_held_note_droops_by_tens_of_cents_not_semitones():
    """The VCA opening sags the supply; the regulated screen keeps the pitch within ~20
    cents of where it started (unregulated, ~780 cents)."""
    _, tank = run(-15.0, dur_s=2.0, on_s=0.1)
    early = vco.frequency(tank[int(0.15 * FS) : int(0.35 * FS)], FS)
    late = vco.frequency(tank[int(1.7 * FS) :], FS)
    print(early, late)
    assert abs(vco.cents(late, early)) < 50


def glide_step(glide):
    """A key held while the pitch steps -20 -> -15 V at 0.3 s: the tank's per-cycle pitch.
    The LFO off: from a run's start its lamp warms for seconds and its changing draw on b1
    moves the pitch ~10 cents meanwhile (SYNTH_IDEAS.md #7), which isn't the glide."""
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {"glide": glide, "lfo_on": 0}), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("o_t"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(1.6 * FS)
    pitch = np.where(np.arange(n) / FS >= 0.3, -15.0, -20.0)
    tank = fast.run_transient(
        ir,
        np.zeros(n),
        settings=st,
        controls={
            "gate": np.full(n, KEY_DOWN_V),
            "pitch": pitch,
            "key": np.zeros(n),
            "pressure": np.zeros(n),
        },
    ).vectors["v(o_t)"]
    ts, fc = vco.cycle_frequencies(tank, FS)
    return ts, vco.smoothed(ts, fc, 0.05)


def test_glide_slides_the_pitch_and_lands_on_the_note():
    """GLIDE (SYNTH_IDEAS.md #1): at 0 a step lands within 10 cents in ~30 ms, as without
    it; at 0.75 (~0.16 s time constant) it is still under halfway (in cents) 40 ms in, and
    lands on the same note (scripts/glide_study.py: 0.68 s to within 10 cents)."""
    ts0, f0 = glide_step(0.0)
    ts1, f1 = glide_step(0.75)
    lo, hi = np.median(f0[(ts0 > 0.1) & (ts0 < 0.28)]), np.median(f0[ts0 > 1.3])
    print(lo, hi)
    assert np.all(np.abs(vco.cents(f0[ts0 > 0.36], hi)) < 10)

    def gone(ts, f, t):
        return vco.cents(np.interp(t, ts, f), lo) / vco.cents(hi, lo)

    print(gone(ts0, f0, 0.34), gone(ts1, f1, 0.34), np.median(f1[ts1 > 1.3]))
    assert gone(ts0, f0, 0.34) > 0.9
    assert gone(ts1, f1, 0.34) < 0.5
    assert abs(vco.cents(np.median(f1[ts1 > 1.3]), hi)) < 10


@pytest.mark.parametrize("track", [0.0, 1.0])
def test_key_track_moves_the_cutoff_driver_with_the_key_string(track):
    """KEY TRACK (SYNTH_IDEAS.md #2): the key string (0.75 V a key, 0 V at C4) under the
    CUTOFF pot. At CUTOFF 0.3 and KEY TRACK 1, C4 -> C5 lifts V4's grid ~4.8 V
    (scripts/keytrack_study.py: the cutoff 1.27 -> 2.22 kHz); at KEY TRACK 0 the key
    string changes nothing."""
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {"cutoff": 0.3, "key_track": track}), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("g4"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(1.6 * FS)
    key = np.where(np.arange(n) / FS >= 1.0, 9.0, 0.0)  # C4, then C5
    g4 = fast.run_transient(
        ir,
        np.zeros(n),
        settings=st,
        controls={
            "gate": np.full(n, KEY_DOWN_V),
            "pitch": np.full(n, -15.0),
            "key": key,
            "pressure": np.zeros(n),
        },
    ).vectors["v(g4)"]
    c4, c5 = np.mean(g4[int(0.8 * FS) : int(1.0 * FS)]), np.mean(g4[int(1.4 * FS) :])
    print(track, c4, c5)
    # -20.5 V before the LFO (2026-11-01): its draw left the rails ~0.2 V lower
    assert abs(c4 - (-20.7)) < 0.15  # KEY TRACK barely moves C4's cutoff
    if track == 0.0:
        assert abs(c5 - c4) < 0.05  # the grid itself still settles ~0.03 V then
    else:
        assert 4.5 < c5 - c4 < 5.1


def test_pressure_raises_the_cutoff_driver():
    """PRESSURE (SYNTH_IDEAS.md #3): the aftertouch strip (0 V at rest, 15 V pressed fully)
    under the KEY TRACK pot. At CUTOFF 0.3 and PRESSURE 1, pressing fully lifts V4's grid
    ~7.3 V (scripts/keytrack_study.py --pressure-v: the cutoff 1.27 -> 2.71 kHz)."""
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, {"cutoff": 0.3, "pressure": 1.0}), cores="ja")
    ir = dataclasses.replace(ir, probes=(VoltageProbe("g4"),))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(1.6 * FS)
    pressure = np.where(np.arange(n) / FS >= 1.0, 15.0, 0.0)
    controls = {
        "gate": np.full(n, KEY_DOWN_V),
        "pitch": np.full(n, -15.0),
        "key": np.zeros(n),
        "pressure": pressure,
    }
    g4 = fast.run_transient(ir, np.zeros(n), settings=st, controls=controls).vectors["v(g4)"]
    rest, pressed = np.mean(g4[int(0.8 * FS) : int(1.0 * FS)]), np.mean(g4[int(1.4 * FS) :])
    print(rest, pressed)
    assert abs(rest - (-20.7)) < 0.15
    assert 6.8 < pressed - rest < 7.8


def test_a_starved_heater_flattens_and_sags_the_voice():
    """HEATER (SYNTH_IDEAS.md #4) at 0.7 of rated, warm: the cathodes' space-charge shift
    and the 6X4's emission ceiling (B+ at b3 ~207 -> ~193 V) drop the held note ~110 cents
    (scripts/heater_knob_study.py: within the rated +-10%, ~+-20 cents)."""
    knob = importlib.util.spec_from_file_location(
        "heater_knob_study", Path(__file__).parents[1] / "scripts" / "heater_knob_study.py"
    )
    mod = importlib.util.module_from_spec(knob)
    knob.loader.exec_module(mod)
    rated, starved = mod.run(1.0), mod.run(0.7)
    print(rated, starved)
    assert -160 < vco.cents(starved["hz"], rated["hz"]) < -70
    assert 8 < rated["b3_v"] - starved["b3_v"] < 25


def test_a_small_reservoir_hums_and_the_6x4_stays_in_rating():
    """RESERVOIR (SYNTH_IDEAS.md #6): 2 uF against 20 uF puts ~17 dB more of the supply's
    120 Hz ripple on the note (sidebands -16 / -33 dB re the harmonics) and makes the pitch
    warble (scripts/supply_study.py); the 6X4's steady-state peak plate current stays under
    GE's 245 mA."""
    study = importlib.util.spec_from_file_location(
        "supply_study", Path(__file__).parents[1] / "scripts" / "supply_study.py"
    )
    mod = importlib.util.module_from_spec(study)
    study.loader.exec_module(mod)
    normal, small = (mod.run("6x4", c, CIRCUIT) for c in (20e-6, 2e-6))
    print(normal, small)
    side = {r["c_reservoir_uf"]: r["ripple_sidebands_db"]["120"] for r in (normal, small)}
    assert side[2.0] - side[20.0] > 12
    assert small["pitch_spread_cents"] > 3 * normal["pitch_spread_cents"]
    assert max(normal["plate_peak_ma"], small["plate_peak_ma"]) < 245


def test_the_lfo_runs_at_its_rate_and_reaches_the_pitch_and_the_cutoff():
    """The lamp-stabilized Wien bridge (SYNTH_IDEAS.md #7) at RATE 1 (~19 Hz) from the start
    of a run, VIBRATO and WOBBLE at 1: it oscillates at its rate, the lamp warms toward
    ~590 K holding ~7.3 V peak (scripts/lfo_study.py: settled in ~4 s), the pitch swings at
    its rate (+-~33 cents) and V4's grid with it (~3 V peak to peak)."""
    study = importlib.util.spec_from_file_location(
        "lfo_study", Path(__file__).parents[1] / "scripts" / "lfo_study.py"
    )
    mod = importlib.util.module_from_spec(study)
    study.loader.exec_module(mod)
    v = mod.run({"lfo_rate": 1.0, "vibrato": 1.0, "wobble": 1.0}, 3.0)
    m = mod.lfo_measures(v, FS)
    vib = mod.vibrato_cents(v, FS, m["f_hz"])
    g4 = np.ptp(v["g4"][-len(v["g4"]) // 4 :])
    print(m, vib, g4)
    assert abs(m["f_hz"] / 19.33 - 1) < 0.03
    assert 4.0 < m["amp_peak_v"] < 12.0 and abs(m["dc_v"]) < 1.5
    assert 450.0 < m["lamp_k"] < 700.0
    assert vib > 15.0
    assert g4 > 2.0


def test_lfo_off_takes_the_oscillator_out_and_holds_the_pitch():
    """LFO OFF (`lfo_on` 0, the user's call: CPU): no tubes or lamp of the LFO in the circuit;
    its supply is on a winding of its own, so the pitch is the LFO on's (measured
    2026-11-01: 497.251 Hz on and off at -15 V)."""
    s = spec.load_circuit(CIRCUIT)
    off = builder.build_ir(s, spec.resolve(s, {"lfo_on": 0}), cores="ja")
    on = builder.build_ir(s, spec.resolve(s, {"lfo_on": 1}), cores="ja")
    names = lambda ir: {e.name for e in ir.elements()}  # noqa: E731
    lfo_parts = {"XLV1A", "XLV1B", "XLV2A", "XLV2B", "XLP"}
    assert lfo_parts <= names(on) and not lfo_parts & names(off)
    _, tank_on = run(-15.0)
    study = importlib.util.spec_from_file_location(
        "lfo_study", Path(__file__).parents[1] / "scripts" / "lfo_study.py"
    )
    mod = importlib.util.module_from_spec(study)
    study.loader.exec_module(mod)
    v = mod.run({"lfo_on": 0}, 1.0)
    assert "lfo" not in v  # the LFO and its pots are out of the circuit
    f_off = vco.frequency(v["o_t"][int(0.5 * FS) :], FS)
    f_on = vco.frequency(tank_on[int(0.5 * FS) :], FS)
    print(f_off, f_on)
    assert abs(vco.cents(f_off, f_on)) < 5


def ring_study():
    study = importlib.util.spec_from_file_location(
        "ring_study", Path(__file__).parents[1] / "scripts" / "ring_study.py"
    )
    mod = importlib.util.module_from_spec(study)
    study.loader.exec_module(mod)
    assert tuple(mod.PARTITION) == PARTITION
    return mod


def test_the_ring_is_in_only_with_the_lfo_and_ring_on():
    """The ring modulator (SYNTH_IDEAS.md #14) runs on the LFO's supply with the LFO as its
    carrier: its parts are in only with LFO ON and RING ON (`ring_on`, off by default: no
    thread for it), and otherwise its mixer resistor's far end is grounded."""
    s = spec.load_circuit(CIRCUIT)
    names = lambda sets: {e.name for e in builder.build_ir(s, spec.resolve(s, sets)).elements()}  # noqa: E731
    ring = {"XRGVA", "XRGVB", "XRGVC", "DRG1", "DRG2", "DRG3", "DRG4"}
    for lfo_on, ring_on in ((0, 0), (0, 1), (1, 0), (1, 1)):
        n = names({"lfo_on": lfo_on, "ring_on": ring_on})
        on = lfo_on and ring_on
        assert (ring <= n) if on else not (ring & n), (lfo_on, ring_on)
        assert ("RRXGA" in n or "RRXGB" in n) != bool(on), (lfo_on, ring_on)
    assert s.controls["ring_on"]["value"] == 0 and s.controls["lfo_audio"]["value"] == 0


def test_the_lfo_audio_range_reaches_audio_rates():
    """LFO AUDIO (`lfo_audio`): the Wien bridge's switched-out capacitors leave 10 nF, RATE
    then ~8 Hz-1.9 kHz (scripts/ring_study.py measure: 147 Hz at 0.5, 1884 Hz at 1, ~8 V peak,
    THD 0.3-0.6% once the lamp has settled: from a start it blooms, ~11.6 V peak and 4% THD
    at 1.5 s); the switch is contacts, so the IR's structure doesn't change."""
    mod = ring_study()
    s = spec.load_circuit(CIRCUIT)
    lo = builder.build_ir(s, spec.resolve(s, {"lfo_audio": 0}))
    hi = builder.build_ir(s, spec.resolve(s, {"lfo_audio": 1}))
    assert [e.name for e in lo.elements()] == [e.name for e in hi.elements()]
    for rate, want_hz in ((0.5, 147.4), (1.0, 1884.0)):
        r, _, fs = mod.run_synth(
            CIRCUIT, {"lfo_audio": 1, "lfo_rate": rate}, -15.0, 4.0, PARTITION, ["lfo"], keep_s=1.0
        )
        row = mod._lfo_row(r, fs, {})
        print(rate, row)
        assert abs(row["lfo_hz"] / want_hz - 1) < 0.03
        assert 4.0 < row["lfo_pk_v"] < 12.0 and row["lfo_thd_pct"] < 2.0


def test_the_ring_multiplies_the_oscillator_by_the_lfo_and_leaves_the_pitch():
    """RING ON, the oscillator out of the mix (OSC 0), the LFO at AUDIO ~590 Hz, a key at
    -15 V (~499 Hz): the output is the sum and difference tones, the oscillator and the
    carrier each >= 25 dB under them (measured -34 / -36 dB); the pitch is the ring off's
    (its supply is the LFO's: 499.347 / 499.346 Hz off / on). After 3 s, the LFO settled (at
    2 s its bloom left the carrier -22.5 dB)."""
    mod = ring_study()
    pr = ["out", "o_t", "lfo"]
    sets = {"ring_on": 1, "osc_level": 0.0, "lfo_audio": 1, "lfo_rate": 0.75}
    r, _, fs = mod.run_synth(CIRCUIT, sets, -15.0, 3.0, PARTITION, pr, keep_s=1.0)
    y = r["out"]
    f1, f2 = vco.frequency(r["o_t"], fs), vco.frequency(r["lfo"], fs)
    prod = max(mod.tone_db(y, fs, abs(f1 - f2)), mod.tone_db(y, fs, f1 + f2))
    osc, car = mod.tone_db(y, fs, f1) - prod, mod.tone_db(y, fs, f2) - prod
    r0, _, _ = mod.run_synth(CIRCUIT, {}, -15.0, 2.0, PARTITION, ["o_t"], keep_s=1.0)
    f_off = vco.frequency(r0["o_t"], fs)
    print(f1, f2, osc, car, f_off)
    assert osc < -25 and car < -25
    assert abs(vco.cents(f1, f_off)) < 3
