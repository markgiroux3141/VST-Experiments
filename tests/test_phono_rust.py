"""The groove player's Rust engine against the Python reference (docs/PHONO_PLAN.md G1's
Rust half; varimu/phono/player.py, crates/circuitsim/src/phono.rs): the cylinder played
with mistracking and dust, the drive, and two coupled contacts."""

from __future__ import annotations

import numpy as np
import pytest

from varimu.phono import cylinder as cy
from varimu.phono import damage as dm
from varimu.phono import groove as gv
from varimu.phono import player as pl
from varimu.phono import transport as tr
from varimu.phono.network import GROUND, Network, Stepper

circuitsim = pytest.importorskip("circuitsim")


def _rel_db(a: np.ndarray, b: np.ndarray) -> float:
    return 20 * np.log10(np.max(np.abs(a - b)) / np.max(np.abs(b)))


def _loud_groove(spec, seconds=0.08, seed=3):
    """A hot hill-and-dale tone burst with dust: the tip flies on its peaks."""
    fs = spec["numerics"]["fs_hz"]
    v = cy.groove_speed(spec, spec["reproducer"]["rpm"])
    t = np.arange(int(seconds * fs)) / fs
    z = 2.5 * spec["cylinder"]["max_amplitude_m"] * np.sin(2 * np.pi * 900 * t)
    z *= np.clip(t / 0.01, 0, 1)
    g = gv.write(z, v, fs, spec["cylinder"]["cut_depth_m"])
    d = dict(spec["damage"], dust_per_m=400.0)
    dm.dust(g, d, seed)
    return g


def test_rust_player_equals_the_reference_on_a_mistracking_cylinder():
    spec = cy.load()
    g = _loud_groove(spec)
    ref = cy.play(spec, g, engine="python")
    fast = cy.play(spec, g, engine="rust")
    assert ref.mistracking_fraction() > 0.01  # the case under test: flights and landings
    assert _rel_db(fast.pressure_pa, ref.pressure_pa) < -150
    assert _rel_db(fast.force_n, ref.force_n) < -150
    assert _rel_db(fast.tip_m - fast.surface_m, ref.tip_m - ref.surface_m) < -120


def test_rust_drive_equals_the_reference():
    spec = cy.load()
    m = spec["player_motor"]
    load = 3e-3 * (1 + 0.5 * (np.arange(16000) > 8000))
    a = tr.simulate(m, 160.0, 0.0278, 2.0, 8000.0, load, 1, "player", engine="python")
    b = tr.simulate(m, 160.0, 0.0278, 2.0, 8000.0, load, 1, "player", engine="rust")
    w0 = np.mean(a.omega)
    assert np.max(np.abs(a.omega - b.omega)) / w0 < 1e-12
    assert np.max(np.abs(a.s_m - b.s_m)) < 1e-12


def test_two_coupled_contacts_agree():
    """A tip held between two walls (a V-groove's in miniature): a mass on two Hertz
    contacts at +-45 degrees, lateral on a spring, vertical under its weight."""
    c = np.sqrt(0.5)
    net = Network()
    for ax in ("x", "y"):
        net.capacitor(ax, GROUND, 2e-5)
        net.conductance(ax, GROUND, 0.05)
        net.integrator(ax, f"z{ax}")
    net.inductor("x", GROUND, 1 / 800.0, "kx")
    net.current_source("y", "gravity")
    for wall, sx in (("L", 1.0), ("R", -1.0)):  # each wall pushes along its normal
        net.current_source("x", f"f{wall}", c * sx)
        net.current_source("y", f"f{wall}", c)
    sys = net.compile()
    h = 1 / 192000
    st = Stepper(sys, h)
    n = 6000
    t = np.arange(n) * h
    lateral = 20e-6 * np.sin(2 * np.pi * 700 * t) + 4e-6 * np.sin(2 * np.pi * 5300 * t)
    contacts = [
        pl.Contact(
            f"f{w}", c * sx * sys.pick("zx") + c * sys.pick("zy"), 2e8, 3.0, c * sx * lateral
        )
        for w, sx in (("L", 1.0), ("R", -1.0))
    ]
    inputs = {"gravity": -0.3 * np.minimum(t / 0.003, 1.0)}
    x0 = np.zeros(len(sys.names))
    out_rows = np.array([sys.pick("zx"), sys.pick("zy")])
    a = pl.run(st, x0, inputs, contacts, out_rows, n, engine="python")
    b = pl.run(st, x0, inputs, contacts, out_rows, n, engine="rust")
    assert np.mean(np.all(a.forces > 0, axis=0)) > 0.3  # both walls carry load
    assert _rel_db(b.forces, a.forces) < -150
    assert _rel_db(b.outputs, a.outputs) < -150
