"""The EMT 240's gold foil (docs/REVERB_PLAN.md, the candidates' first): the component
EMT240@1 against its brochure's figures, and the foil reverb device
(config/circuits/foil_reverb.yaml: plate_reverb.yaml's electronics around it)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from varimu import preflight
from varimu.circuit import builder, spec
from varimu.circuit.ir import Plate
from varimu.devices import plate as plt
from varimu.devices.library import load_plate


def foil() -> plt.PlateComponent:
    return load_plate("EMT240@1")


def test_the_foil_meets_its_brochure() -> None:
    c = foil()
    spec_ = plt.PlateSpec(
        c.lx_m, c.ly_m, c.thickness_m, c.density_kg_m3, c.youngs_pa, c.poisson,
        c.tension_n_m, c.drive_xy, c.pickup_xy, c.f_max_hz,
        plt.decay_table(c, 2.0), c.tail_db,
    )  # fmt: skip
    kappa2, tension = plt.stiffness(spec_)
    # "Density of resonances > 3/Hz", constant over the audible range: bending dominates
    # at S / (2 kappa) modes per Hz, tension's share of omega^2 falling as f_x / f past a
    # crossover f_x below 50 Hz (EMT140@1's model: ~32 Hz).
    per_hz = c.lx_m * c.ly_m / (2.0 * math.sqrt(kappa2))
    assert 3.0 < per_hz < 4.0
    omega, _, _ = plt.modes(spec_, 2000.0)
    assert len(omega) == pytest.approx(2000.0 * per_hz, rel=0.05)
    f_x = math.sqrt(kappa2) * (tension / kappa2) / (2 * math.pi)
    assert 20.0 < f_x < 50.0
    # "Reverberation time at 500 Hz 1...4 seconds", flat but for the top.
    assert c.t500_range() == pytest.approx((1.0, 4.0), rel=1e-3)
    for t500 in (1.0, 2.5, 4.0):
        table = dict(plt.decay_table(c, t500))
        assert plt.SIX_LN10 / table[500.0] == pytest.approx(t500, rel=1e-3)
        assert plt.SIX_LN10 / table[125.0] == pytest.approx(t500, rel=0.05)
        assert plt.SIX_LN10 / table[8000.0] < t500


def test_the_foil_is_driven_and_read_at_the_140s_level() -> None:
    """The provisional transducers: a 1.5 ohm motional resistance, and the diffuse field's
    pickup voltage per ampere equal to EMT140@1's."""
    c, ref = foil(), load_plate("EMT140@1")
    assert c.exciter_bl_tm**2 / plt.plate_impedance_ns_per_m(c) == pytest.approx(1.5)

    def level(p: plt.PlateComponent) -> float:
        m = p.density_kg_m3 * p.thickness_m * p.lx_m * p.ly_m
        return (
            p.exciter_bl_tm * p.pickup_v_per_m_s2 / math.sqrt(plt.plate_impedance_ns_per_m(p) * m)
        )

    assert level(c) == pytest.approx(level(ref), rel=1e-9)


def test_the_device_builds_and_passes_preflight() -> None:
    sp = spec.load_circuit(spec.circuit_path("foil_reverb"))
    assert preflight.check_circuit(sp) == []
    plates = [e for e in builder.build(sp).ir.elements() if isinstance(e, Plate)]
    assert len(plates) == 1 and plates[0].thickness_m == pytest.approx(18e-6)
    # DECAY's range is the brochure's.
    lo, hi = sp.controls["decay_500hz_s"]["min"], sp.controls["decay_500hz_s"]["max"]
    assert (lo, hi) == (1.0, 4.0)


def test_the_foil_rings_at_its_decay() -> None:
    """The reference's response: an octave band's envelope decays at the table's rate."""
    from scipy.signal import butter, sosfilt

    c = foil()
    p = plt.PlateSpec(
        c.lx_m, c.ly_m, c.thickness_m, c.density_kg_m3, c.youngs_pa, c.poisson,
        c.tension_n_m, c.drive_xy, c.pickup_xy, 1500.0,
        plt.decay_table(c, 1.0), 60.0,
    )  # fmt: skip
    fs = 4000.0
    h = plt.impulse_response(p, fs)
    y = sosfilt(butter(4, [354.0, 707.0], btype="band", fs=fs, output="sos"), h)
    sch = np.cumsum((y**2)[::-1])[::-1]
    db = 10 * np.log10(sch / sch[0])
    t = np.arange(len(db)) / fs
    sel = (db < -5) & (db > -35)
    t60 = -60.0 / np.polyfit(t[sel], db[sel], 1)[0]
    assert t60 == pytest.approx(1.0, rel=0.1)
