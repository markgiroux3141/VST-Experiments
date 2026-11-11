"""The multitrack deck (docs/PERIOD_GEAR_BACKLOG.md, PG1): MT2, four tracks on one tape and
one transport (the medium as it is: each Tape element's transport keyed by the circuit's
seed, its grain by its name), and MT3's crosstalk model (`varimu.multitrack.crosstalk`)
against Ampex's measured curve."""

from __future__ import annotations

import dataclasses
import json
import math

import numpy as np
import pytest
from scipy import signal as sps

from varimu.devices import library
from varimu.devices.tape import CrossPickup, HeadGeometry, Orientation, TapeNoise, lateral_factor
from varimu.devices.tape_machine import TapeMachineSpec, TapeStream, stream_params, with_neighbours
from varimu.multitrack import crosstalk as x

FS = 96_000.0
OE = 1000.0 / (4.0 * math.pi)
HEAD_351 = HeadGeometry(6.35e-6, 1.5e-3, 5.5e-3)


# --- formats ---------------------------------------------------------------------------


def test_the_four_track_format_fits_half_inch_tape():
    f = x.FOUR_TRACK_HALF_INCH
    assert f.guard_m == pytest.approx(60 * x.MIL)
    span = 3 * f.pitch_m + f.width_m
    assert span < f.tape_m
    assert [j for j, _ in f.neighbours(0)] == [1]
    assert [j for j, _ in f.neighbours(3)] == [2]
    assert [j for j, _ in f.neighbours(1)] == [0, 2]
    assert f.neighbours(1, reach=2)[-1] == (3, pytest.approx(2 * f.pitch_m))
    with pytest.raises(ValueError, match="don't fit"):
        x.TrackFormat("x", 4, 85 * x.MIL, 145 * x.MIL, 500 * x.MIL, "")


# --- MT3: the crosstalk model ----------------------------------------------------------


def test_the_lateral_factor_agrees_with_quadrature_and_falls_with_distance():
    w = 1.78e-3
    for k in (40.0, 500.0, 5e3):
        got = x.lateral([k], 3.3e-3, w)[0]
        assert got == pytest.approx(x.lateral_quad(k, 3.3e-3, w), rel=1e-9)
    near, far = x.lateral([500.0], 3.3e-3, w)[0], x.lateral([500.0], 6.6e-3, w)[0]
    assert 0 < far < near < 1
    # Short waves don't cross the guard band: exp(-k (d - w)) and faster.
    k = np.array([2e3, 4e3])
    lat = x.lateral(k, 3.3e-3, w)
    assert lat[1] / lat[0] < math.exp(-(k[1] - k[0]) * (3.3e-3 - w))
    with pytest.raises(ValueError, match="overlap"):
        x.lateral([100.0], 1e-3, 2e-3)


def test_the_bands_average_power():
    f = np.geomspace(20, 20e3, 500)
    db = np.where(f < 1e3, -40.0, -60.0)
    c, b = x.bands(f, db, per_octave=1)
    assert b[0] == pytest.approx(-40.0) and b[-1] == pytest.approx(-60.0)


@pytest.fixture(scope="module")
def fitted():
    return x.fit(HEAD_351)


def test_the_model_meets_ampexs_curve_on_its_octave_envelope(fitted):
    """Fitted on the three-track Model 300's curve (the 354 manual p 12): within 2.5 dB rms
    on octaves; the mid band is the cores' coupling, the top octaves the record heads'."""
    c, rms = fitted
    assert rms < 2.5
    f, db = x.measured()
    mid = (f > 500) & (f < 3000)
    got = c.curve_db(f[mid], 0.381, x.THREE_TRACK_HALF_INCH)
    assert np.abs(got - db[mid]).max() < 3.5
    # Above ~16 kHz Ampex's curve levels off at -43 dB (the heads' resonance or the
    # equalizers' roll-off, not modelled); the couplings keep rising, 3.1 dB over at 19.6 kHz.
    top = (f > 8e3) & (f < 16e3)
    got = c.curve_db(f[top], 0.381, x.THREE_TRACK_HALF_INCH)
    assert np.abs(got - db[top]).max() < 2.0
    # The bass crosses most: the lowest octave tens of dB above the mid band.
    lo = c.curve_db(np.array([31.5]), 0.381, x.THREE_TRACK_HALF_INCH)[0]
    assert lo > -45.0


def test_four_tracks_on_half_inch_cross_about_50_db(fitted):
    """AI-14 p 13: four tracks on 1/2 in, crosstalk rejection around 50 dB (mid band)."""
    c = fitted[0].scaled()
    fmt = x.FOUR_TRACK_HALF_INCH
    mid = c.curve_db(np.array([500.0, 1000.0, 2000.0]), 0.381, fmt)
    assert np.all((mid > -56.0) & (mid < -48.0))
    # Half the speed halves the wavelengths' frequencies: the bass bleed moves down an octave.
    k_fast = c.curve_db(np.array([40.0]), 0.381, fmt)[0]
    k_slow = c.curve_db(np.array([20.0]), 0.1905, fmt)[0]
    assert k_fast == pytest.approx(k_slow, abs=1e-6)


# --- MT3 in the engine: a head reads its neighbours' tracks ------------------------------

#: The deck's pickup: the fit scaled to four tracks (fit.json; `Crosstalk.scaled`), as
#: config/circuits/ampex_300_4.yaml has it. Numbers only matter here as a typical case.
PICKUP = CrossPickup(130 * x.MIL, 0.839373, 1.84809 * 70 * x.MIL, -0.00195347)


def test_the_lateral_factors_quadrature_agrees_with_the_models():
    """`varimu.devices.tape.lateral_factor` (the trapezoidal rule in t, both languages)
    against the model's adaptive quadrature, for the fitted contour 15 um short of the
    neighbour and a narrow one."""
    for d, w in ((PICKUP.pitch_m, PICKUP.contour_width_m), (3.3e-3, 1.78e-3)):
        for k in (48.0, 330.0, 3e3, 3e4):
            want = x.lateral_quad(k, d, w)
            assert lateral_factor(np.array([k]), d, w)[0] == pytest.approx(want, rel=1e-12)
    assert lateral_factor(np.array([0.0]), 3.3e-3, 1.78e-3)[0] == 0.0
    with pytest.raises(ValueError, match="overlap"):
        lateral_factor(np.array([1.0]), 1e-3, 2e-3)


def _rust():
    try:
        import circuitsim
    except ImportError:
        pytest.skip("circuitsim isn't built (uv sync --extra fast)")
    return circuitsim


def _tone(f_hz: float, seconds: float, oe: float = 120.0):
    n = int(seconds * FS)
    t = np.arange(n) / FS
    return oe * OE * np.sin(2 * math.pi * f_hz * t) * np.clip(t / 0.004, 0.0, 1.0)


def test_the_cross_stream_agrees_with_the_reference():
    """circuitsim's stream with crosstalk (`push_many_readouts`) against the reference's
    (`push_both`, its own slope code): the own EMF unchanged bit for bit, the cross EMF
    within rounding."""
    cs = _rust()
    spec, tape, h, bias = _small()
    ref = TapeStream(spec, tape, bias, FS, engine="rust", crosstalk=PICKUP)
    own_ref, cross_ref = ref.push_both(h)
    params = stream_params(spec, tape, bias, crosstalk=("t", 1, PICKUP))
    r = cs.tape_stream_run(json.dumps(params), FS, h, readouts=True)
    assert sorted(r) == ["cross", "emf"]
    own, cross = np.asarray(r["emf"]), np.asarray(r["cross"])
    alone = np.asarray(cs.tape_stream_run(json.dumps(stream_params(spec, tape, bias)), FS, h))
    np.testing.assert_array_equal(own, alone)
    assert np.abs(cross_ref).max() > 0
    assert np.abs(own - own_ref).max() / np.abs(own_ref).max() < 1e-11
    assert np.abs(cross - cross_ref).max() / np.abs(cross_ref).max() < 1e-11


def _fundamental(y: np.ndarray, f_hz: float) -> complex:
    t = np.arange(len(y)) / FS
    return complex(2 * np.mean(y * np.exp(-2j * math.pi * f_hz * t)))


#: A pickup whose two terms add at the tone (the first fit's signs): on the small machine the
#: window cuts the lateral spread's tail by ~0.7 %, which a cancelling pair (the deck's
#: PICKUP: -2.3 % here) magnifies; the property tested doesn't depend on the values.
ADDING = CrossPickup(130 * x.MIL, 0.4827, 1.84815 * 70 * x.MIL, 0.0013465 * 10**0.25)


def test_a_neighbour_reads_the_kernels_ratio():
    """A tone on one track: the cross EMF over the track's own EMF at the tone is the
    pickup's bracket over the head's (both read the same magnetization, the spacing's and
    the layers' losses common): [core sinc - (unshielded L + core) c] / [sinc - c], c the
    contour term, as varimu.multitrack.crosstalk's `playback` has it over a flat head."""
    spec, tape, _, bias = _small()
    spec = dataclasses.replace(spec, flutter=False)
    f = 1500.0
    h = _tone(f, 0.022)
    own, cross = TapeStream(spec, tape, bias, FS, engine="rust", crosstalk=ADDING).push_both(h)
    late = slice(int(0.012 * FS), int(0.012 * FS) + int(15 * FS / f))  # 15 whole periods
    got = _fundamental(cross[late], f) / _fundamental(own[late], f)
    head = spec.rep_head()
    k = np.array([2 * math.pi * f / spec.speed_m_s])
    lat = lateral_factor(k, ADDING.pitch_m, ADDING.contour_width_m)[0]
    c = -x.contour_term(head, k)[0]
    gap = x.gap_term(head, k)[0]
    want = (ADDING.core * gap - (ADDING.unshielded * lat + ADDING.core) * c) / (gap - c)
    assert abs(got.imag) < 3e-3 * abs(got)
    # The cross slope is read over the own head's reach either side of a block (the
    # stream's window): the lateral spread's 1/x^2 tail past it is cut. On this small
    # machine (0.2 mm reach against a 3.3 mm pitch) that is 0.7 %; on the deck's heads (14
    # mm) at most 2 % (0.17 dB) at 31.5 Hz-4 kHz, PERIOD_GEAR_BACKLOG.md "Where it stands".
    assert got.real == pytest.approx(want, rel=1e-2)


def _group_ir(tracks: tuple[int, ...], split: bool = False, sync: bool = False):
    """Tapes of one group (the small machine) recording scaled copies of the input, each
    on its own track (sync: each record head's playback on y<i> too): (ir, spec, tape,
    bias, h_per_v)."""
    from varimu.circuit.ir import IR_VERSION, CircuitIR, Resistor, Section, Tape, VoltageProbe

    spec, tape, _, bias = _small()
    h_per_v = 2e4 * OE
    scales = (1.0, 0.6, 0.3, 0.8)[: len(tracks)]
    secs = []
    for i, (tr, sc) in enumerate(zip(tracks, scales, strict=True)):
        p = stream_params(
            spec,
            tape,
            bias,
            crosstalk=("deck", tr, PICKUP),
            sync_h_per_a=SYNC_H_PER_A if sync else None,
        )
        for k in ("flutter", "flutter_noise"):
            p[k] = tuple(tuple(r) for r in p[k])
        from varimu.circuit.ir import TapeCrosstalk, TapeMedium, TapeSync

        p["crosstalk"] = TapeCrosstalk(**p["crosstalk"])
        if sync:
            p["sync"] = TapeSync(**p["sync"])
        y = f"y{i}" if sync else None
        els = (
            Resistor(f"RA{i}", "in", f"s{i}", (1 - sc) * 100.0 + 1e-3),
            Resistor(f"RB{i}", f"s{i}", "0", sc * 100.0),
            Tape(f"VT{i}", f"s{i}", "0", h_per_v, f"o{i}", TapeMedium(**p), sync_out=y),
            Resistor(f"RL{i}", f"o{i}", "0", 1e3),
        ) + ((Resistor(f"RY{i}", f"y{i}", "0", 1e3),) if sync else ())
        secs.append(Section(f"track {i}", els))
    if not split:
        secs = [Section("deck", tuple(e for s in secs for e in s.elements))]
    probes = tuple(VoltageProbe(f"s{i}") for i in range(len(tracks))) + tuple(
        VoltageProbe(f"o{i}") for i in range(len(tracks))
    )
    if sync:
        probes += tuple(VoltageProbe(f"y{i}") for i in range(len(tracks)))
    ir = CircuitIR(
        version=IR_VERSION,
        title="deck",
        input_node="in",
        probes=probes,
        models=(),
        sections=tuple(secs),
    )
    return ir, spec, tape, bias, h_per_v


def test_tapes_of_a_group_read_their_neighbours_in_a_circuit():
    """Three tracks of one tape in a circuit (tracks 0, 1, 2; the middle one has two
    neighbours, the edges one): each repro output is its own EMF plus its neighbours'
    cross EMFs (`with_neighbours`), a sample after the sensed field, as the reference
    streams give them; the IR round-trips through JSON in both languages."""
    from varimu.circuit.ir import CircuitIR

    cs = _rust()
    _, _, h, _ = _small()
    tracks = (0, 1, 2)
    ir, spec, tape, bias, h_per_v = _group_ir(tracks)
    ir.validate()
    assert CircuitIR.from_json(ir.to_json()) == ir
    assert cs.ir_roundtrip(ir.to_json()) is not None
    out = cs.simulate(ir.to_json(), h / h_per_v, 1.0 / FS, "esdirk4", input_order=1)
    own, cross = [], []
    for i in range(len(tracks)):
        st = TapeStream(spec, tape, bias, FS, engine="rust", crosstalk=PICKUP)
        a, b = st.push_both(h_per_v * np.asarray(out[f"v(s{i})"]))
        own.append(a)
        cross.append(b)
    want = with_neighbours(list(tracks), own, cross)
    for i in range(len(tracks)):
        got = np.asarray(out[f"v(o{i})"])
        assert got[0] == 0.0
        # The repro coil works into RL as an ideal source here: out = EMF.
        assert np.abs(got[1:] - want[i][:-1]).max() / np.abs(want[i]).max() < 1e-9
    # The middle track hears both neighbours: more of the others than the edge tracks.
    xt = [np.std(want[i] - own[i]) / np.std(own[i]) for i in range(3)]
    assert xt[1] > xt[0] and xt[1] > xt[2] > 0


def test_record_heads_play_back_their_tracks_and_neighbours_in_a_circuit():
    """The same three tracks with each record head's playback (Sel-Sync) on its own node:
    the record head's EMF plus its neighbours' record-head cross EMFs, as the reference's
    `sync_out` / `sync_cross_out` give them; the repro outputs as without Sel-Sync."""
    cs = _rust()
    _, _, h, _ = _small()
    tracks = (0, 1, 2)
    ir, spec, tape, bias, h_per_v = _group_ir(tracks, sync=True)
    out = cs.simulate(ir.to_json(), h / h_per_v, 1.0 / FS, "esdirk4", input_order=1)
    own, cross, sync, sync_cross = [], [], [], []
    for i in range(len(tracks)):
        st = TapeStream(
            spec, tape, bias, FS, engine="rust", crosstalk=PICKUP, sync_h_per_a=SYNC_H_PER_A
        )
        a, b = st.push_both(h_per_v * np.asarray(out[f"v(s{i})"]))
        own.append(a)
        cross.append(b)
        sync.append(st.sync_out)
        sync_cross.append(st.sync_cross_out)
    for name, want in (
        ("o", with_neighbours(list(tracks), own, cross)),
        ("y", with_neighbours(list(tracks), sync, sync_cross)),
    ):
        for i in range(len(tracks)):
            got = np.asarray(out[f"v({name}{i})"])
            assert got[0] == 0.0
            assert np.abs(got[1:] - want[i][:-1]).max() / np.abs(want[i]).max() < 1e-9


def test_a_group_keeps_its_tracks_apart_and_together():
    """Two tapes on one track of a group are refused (both languages); a partition that
    puts a group's tracks in different parts is refused."""
    from varimu.circuit.ir import IRError

    cs = _rust()
    with pytest.raises(IRError, match="both track 1"):
        _group_ir((1, 1))
    # circuitsim's own check (`media::crosstalk_pairs`): the JSON of a valid IR, edited.
    ok, *_ = _group_ir((0, 1))
    d = json.loads(ok.to_json())
    for e in d["sections"][0]["elements"]:
        if e["kind"] == "tape":
            e["medium"]["crosstalk"]["track"] = 1.0
    with pytest.raises((ValueError, RuntimeError), match="both track 1"):
        cs.simulate(json.dumps(d), np.zeros(4), 1.0 / FS, "esdirk4")
    ir, *_ = _group_ir((0, 1), split=True)
    ir.validate()
    with pytest.raises((ValueError, RuntimeError), match="different parts"):
        cs.simulate(ir.to_json(), np.zeros(4), 1.0 / FS, "esdirk4", partition=["track 1"])


# --- MT4: Sel-Sync, the record head as a playback head ------------------------------------

#: The record head reads with its own gap and its field per ampere (rec_h_per_a; the 351's
#: 8.0e6 A/m per A, TAPE_PLAN.md "Gaps").
SYNC_H_PER_A = 8.0e6


def _sync_spec():
    """The small machine (its record gap 12.7 um: the deck's 51 um would put its short
    poles' edges in the recording zone)."""
    return _small()


def test_the_sync_readout_agrees_with_the_reference():
    """The record head's readout and its cross (Sel-Sync with crosstalk) in circuitsim's
    stream against the reference's, within rounding; the repro head's as before."""
    cs = _rust()
    spec, tape, h, bias = _sync_spec()
    ref = TapeStream(
        spec, tape, bias, FS, engine="rust", crosstalk=PICKUP, sync_h_per_a=SYNC_H_PER_A
    )
    own_ref, cross_ref = ref.push_both(h)
    sync_ref, sync_cross_ref = ref.sync_out, ref.sync_cross_out
    params = stream_params(spec, tape, bias, crosstalk=("t", 1, PICKUP), sync_h_per_a=SYNC_H_PER_A)
    r = cs.tape_stream_run(json.dumps(params), FS, h, readouts=True, chunk=333)
    assert sorted(r) == ["cross", "emf", "sync", "sync_cross"]
    for got, want in (
        (r["emf"], own_ref),
        (r["cross"], cross_ref),
        (r["sync"], sync_ref),
        (r["sync_cross"], sync_cross_ref),
    ):
        got = np.asarray(got)
        assert np.abs(want).max() > 0
        assert np.abs(got - want).max() / np.abs(want).max() < 1e-11


def test_the_record_heads_playback_response():
    """The record head reads what the repro head reads, through its own gap: at a tone,
    sync over repro is the heads' spectra's ratio (their pole faces alike: the gap loss and
    the field per ampere). With the deck's 51 um gap at 15 ips its first null is at
    v / g = 7.47 kHz: Sel-Sync's dull monitor (PERIOD_GEAR_BACKLOG.md, MT4)."""
    from varimu.devices.tape import head_hx_spectrum

    spec, tape, _, bias = _sync_spec()
    spec = dataclasses.replace(spec, flutter=False)
    for f in (1000.0, 6000.0):
        h = _tone(f, 0.022, oe=60.0)
        st = TapeStream(spec, tape, bias, FS, engine="rust", sync_h_per_a=SYNC_H_PER_A)
        own = st.push_many(h)
        sync = st.sync_out
        n = int(round(FS / f * round(0.008 * f)))  # whole periods
        late = slice(int(0.012 * FS), int(0.012 * FS) + n)
        got = _fundamental(sync[late], f) / _fundamental(own[late], f)
        k = np.array([2 * math.pi * f / spec.speed_m_s])
        want = (SYNC_H_PER_A * head_hx_spectrum(spec.rec_head(), k, 0.0)[0]) / (
            1.0 * head_hx_spectrum(spec.rep_head(), k, 0.0)[0]
        )
        assert abs(got.imag) < 1e-3 * abs(got)
        assert got.real == pytest.approx(want, rel=1e-3)
    assert spec.speed_m_s / 51e-6 == pytest.approx(7470.6, abs=0.1)


def test_an_overdub_monitored_in_sync_lines_up_to_a_sample():
    """Pass 1 records a burst on track A; its Sel-Sync readout, advanced by the head
    distance (the readout is the record head's reading of what the repro head reads, so a
    head distance late), is what pass 2 hears off A's record head. Pass 2 records the same
    burst on track B where it hears A's. Played back, B's burst lines up with A's to a
    sample (the readout's zero-phase heads; the transport shared, flutter on)."""
    spec, tape, _, bias = _sync_spec()
    lag = int(round(spec.head_distance_m / spec.speed_m_s * FS))
    spec = dataclasses.replace(spec, head_distance_m=lag * spec.speed_m_s / FS)
    n = int(0.03 * FS)
    t = np.arange(n) / FS
    t0 = 0.008

    def burst(at: float) -> np.ndarray:
        return 200 * OE * np.sin(2 * math.pi * 3000 * (t - at)) * np.exp(-(((t - at) / 4e-4) ** 2))

    def run(x):
        st = TapeStream(
            spec, tape, bias, FS, engine="rust", sync_h_per_a=SYNC_H_PER_A, transport_seed=3
        )
        return st.push_many(x), st.sync_out

    rep_a, sync_a = run(burst(t0))
    # What pass 2 hears off A's record head at sample t: push k reads the record head at
    # t_{k+1} on the tape the record gap passed lag samples before (the flutter's integral
    # over the head distance moves that by a fraction of a sample).
    heard = np.concatenate([sync_a[lag - 1 :], np.zeros(lag - 1)])
    env = np.abs(sps.hilbert(heard))
    t_heard = int(np.argmax(env)) / FS
    assert t_heard == pytest.approx(t0, abs=1.5 / FS)
    rep_b, _ = run(burst(t_heard))

    def peak(y):
        return int(np.argmax(np.abs(sps.hilbert(y))))

    assert abs(peak(rep_b) - peak(rep_a)) <= 1
    xc = np.correlate(rep_b, rep_a, "full")
    assert int(np.argmax(xc)) - (len(rep_a) - 1) in (-1, 0, 1)


# --- MT2: four tracks, one transport ---------------------------------------------------


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
    n = int(0.012 * FS)
    t = np.arange(n) / FS
    h = 300 * OE * np.sin(2 * math.pi * 1000 * t) * np.clip(t / 0.006, 0.05, 1.0)
    return spec, tape, h, 750 * OE


def _grainy(tape):
    return dataclasses.replace(tape, noise=TapeNoise(4.7e-21, 0.35, 0.05, 20e-6))


def test_tracks_of_one_tape_share_the_transport_and_not_the_grain():
    """Four streams of one circuit: one transport (keyed by the circuit's seed, not the
    track: the same speeds bit for bit, the same playback without grain), each its own
    grain (keyed by the element's name)."""
    spec, tape, h, bias = _small()
    assert spec.flutter
    names = ("VT1", "VT2", "VT3", "VT4")
    clean = [
        TapeStream(spec, tape, bias, FS, engine="rust", noise_name=n, transport_seed=11)
        for n in names
    ]
    speeds = [st._speeds(1, 4000) for st in clean]
    for s in speeds[1:]:
        np.testing.assert_array_equal(s, speeds[0])
    assert np.std(speeds[0]) > 0
    outs = [st.push_many(h) for st in clean]
    for o in outs[1:]:
        np.testing.assert_array_equal(o, outs[0])
    grainy = [
        TapeStream(
            spec,
            _grainy(tape),
            bias,
            FS,
            engine="rust",
            noise_seed=11,
            noise_name=n,
            transport_seed=11,
        ).push_many(h)
        for n in names
    ]
    noise = [g - outs[0] for g in grainy]
    late = slice(len(h) // 2, None)
    for i in range(4):
        for j in range(i + 1, 4):
            r = np.corrcoef(noise[i][late], noise[j][late])[0, 1]
            assert abs(r) < 0.5, (i, j, r)


def test_narrow_tracks_hiss_as_the_square_root_of_their_width():
    """The grain's playback noise against the signal: S/N in proportion to sqrt(width)
    (Ampex AI-14 p 11: +3 dB per doubling), so the 300-4's 70 mil tracks are 5.3 dB under the
    351's full track (234 mil). The hiss is unbiased tape's (the particles alone): the small
    machine's biased silence also records a residue that scales with width like a signal."""
    spec, tape, h, bias = _small()
    tape = _grainy(tape)
    sn = {}
    for mil in (70, 234):
        sp = dataclasses.replace(spec, track_m=mil * x.MIL, flutter=False)
        sig = TapeStream(sp, dataclasses.replace(tape, noise=None), bias, FS).push_many(h)
        hiss = TapeStream(sp, tape, 0.0, FS, noise_seed=5).push_many(np.zeros_like(h))
        late = slice(len(h) // 2, None)
        sn[mil] = 20 * math.log10(np.std(sig[late]) / np.std(hiss[late]))
    assert sn[234] - sn[70] == pytest.approx(10 * math.log10(234 / 70), abs=0.3)


# --- MT1: the tape ---------------------------------------------------------------------


def test_scotch_202_is_111_moved_to_eilers_figures():
    """SCOTCH202@1 (scripts/make_scotch202.py, current): Eilers' 315 Oe against 111's 270, the
    same 0.64 lines per 1/4 in (0 dB re 111), half the particle volume (provisional)."""
    import subprocess
    import sys

    from varimu.config import REPO_ROOT

    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "make_scotch202.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    t, u = library.load_tape("SCOTCH202@1"), library.load_tape("SCOTCH111@3")
    assert t.preisach.hc_median_a_m / u.preisach.hc_median_a_m == pytest.approx(315 / 270)
    assert t.ms_a_m * t.coating_m == pytest.approx(u.ms_a_m * u.coating_m)
    assert t.noise.particle_volume_m3 == pytest.approx(0.5 * u.noise.particle_volume_m3)
