"""The Electro-Voice RE20 (docs/CHAINS_PLAN.md WP13): the circuit file (the cartridge R_RE20@1,
Mawby's Variable-D slot entries reduced to its one rear entry, into RE20_OT@1 and EV's network)
against EV's figures (data/datasheets/ev_re20_*.csv; 1.5 mV/Pa) with the entries on the
component's variable_d body. The construction is unpublished, so the cartridge is fitted
(scripts/fit_re20.py); the misses it leaves are asserted at their measured size."""

from __future__ import annotations

import csv

import numpy as np
import pytest

from varimu.circuit import builder, spec
from varimu.config import CONFIG_DIR, DATA_DIR
from varimu.devices import versions
from varimu.devices.library import component_data, load_moving_coil
from varimu.measure import ac
from varimu.mics.free_field import body_entry_factors

VERSION = "R_RE20@1"
ANGLES = [0.0, 90.0, 180.0]
_ENT: dict = {}
_IR: dict = {}
# The misses the fit leaves, at their measured size (CHAINS_PLAN.md WP13's notes): on axis 1.42 dB
# rms, -3.7 dB at 6.5 kHz; rear 1.65 dB rms, +3.9 dB at 5.1 kHz; the 90 deg points 2.1-3.2 dB
# narrower than EV's (-7.4 to -8.3 dB: a supercardioid's side); 10 cm at 100 Hz +9.9 dB (EV:
# "eliminated"); the bass tilt 1.2 dB from 400 to 100 Hz (EV: 4.5 dB).
RMS0, WORST0, RMS1, WORST1 = 1.6, 4.0, 1.8, 4.2
SIDE_MAX, PROX_MAX, TILT_RANGE = 3.4, 10.5, (-2.0, -0.6)


def _ir(settings: dict | None = None):
    key = tuple(sorted((settings or {}).items()))
    if key not in _IR:
        c = spec.load_circuit(CONFIG_DIR / "circuits" / "ev_re20.yaml")
        _IR[key] = builder.build_ir(c, spec.resolve(c, settings or {}), "linear")
    return _IR[key]


def _response(f, theta_deg, distance_m=np.inf, settings=None):
    """Volts open circuit at the XLR per pascal of the wave at the origin, the entries on the
    component's body (the slot entries weighted onto the rear entry)."""
    g = component_data(VERSION)["geometry"]
    f = np.atleast_1d(np.asarray(f, float))
    missing = [x for x in f if (float(x), distance_m) not in _ENT]
    if missing:
        fr, rr = body_entry_factors(
            np.array(missing), np.radians(ANGLES), g["body"], g["diaphragm"]["radius_m"],
            distance_m, geometry=g,
        )  # fmt: skip
        for i, x in enumerate(missing):
            _ENT[(float(x), distance_m)] = (fr[i], rr[i])
    j = ANGLES.index(theta_deg)
    front = np.array([_ENT[(float(x), distance_m)][0][j] for x in f])
    rear = np.array([_ENT[(float(x), distance_m)][1][j] for x in f])
    return front * ac.transfer(_ir(settings), f, "out", drives={"p_rear": rear / front})


def _trace(name):
    with open(DATA_DIR / "datasheets" / "ev_re20_response.csv", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["trace"] == name]
    return (np.array([float(r["freq_hz"]) for r in rows]),
            np.array([float(r["db_re_0deg_1khz"]) for r in rows]))  # fmt: skip


def test_pinned_and_locked():
    assert versions.versions("R_RE20")
    assert versions.versions("RE20_OT")
    c = load_moving_coil(VERSION)
    assert c.re_ohm == pytest.approx(30.0)


def test_sensitivity():
    """EV: 1.5 mV/Pa at 1 kHz, open circuit (the model 1.42)."""
    assert abs(_response([1000.0], 0.0)[0]) == pytest.approx(1.5e-3, rel=0.07)  # 1.42


def test_on_axis_and_rear_follow_the_sheet():
    """The 0 and 180 deg traces (bass tilt off) re 1 kHz on axis, 40 Hz - 14 kHz."""
    ref = abs(_response([1000.0], 0.0)[0])
    cases = (("0_off", 0.0, RMS0, WORST0), ("180_off", 180.0, RMS1, WORST1))
    for name, th, rms_max, worst_max in cases:
        f, d = _trace(name)
        keep = (f >= 40) & (f <= 14000)
        e = 20 * np.log10(abs(_response(f[keep], th)) / ref) - d[keep]
        assert np.sqrt(np.mean(e**2)) < rms_max, name
        assert np.abs(e).max() < worst_max, name


def test_cardioid_side():
    """EV's polar: -4.2 dB at 90 deg below 700 Hz, -5.6 above (the two sides' mean); the
    model is 2.1-3.2 dB narrower (a known miss)."""
    f = np.array([250.0, 1000.0, 2000.0, 4000.0])
    want = np.array([-4.2, -5.6, -5.6, -5.6])
    side = 20 * np.log10(abs(_response(f, 90.0)) / abs(_response(f, 0.0)))
    assert np.abs(side - want).max() < SIDE_MAX


def test_proximity_is_held_down():
    """EV: "The bass-boosting proximity effect ... is eliminated in the RE20". At 10 cm on axis
    the response over the far field's at 100 Hz: +9.9 dB, a known miss (a plain cardioid's is
    ~+9 dB; the SM57's +18 dB at 6 mm): the fitted low end still enters mostly at the head's
    ports, so the bound only guards against it growing."""
    f = np.array([100.0])
    rise = 20 * np.log10(abs(_response(f, 0.0, 0.1)[0] / _response(f, 0.0)[0]))
    assert rise < PROX_MAX


def test_bass_tilt():
    """EV: with the switch on, the low end tilts down 4.5 dB from 400 to 100 Hz (the model 1.2:
    the provisional 30 ohm coil's low source impedance against L1, a known miss)."""
    f = np.array([100.0, 400.0])
    on = 20 * np.log10(abs(_response(f, 0.0, settings={"bass_tilt": 1})))
    off = 20 * np.log10(abs(_response(f, 0.0)))
    tilt = (on[0] - off[0]) - (on[1] - off[1])
    assert TILT_RANGE[0] < tilt < TILT_RANGE[1]
