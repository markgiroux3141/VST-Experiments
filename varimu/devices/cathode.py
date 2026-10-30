"""A tube's cathode temperature and what it does (device builder B6, the heater): the Python
reference.

**Heat.** The heater (rated V0, I0; its resistance R = R0 (T / T0)^ALPHA, a tungsten wire
whose temperature tracks the cathode's) heats the cathode, which loses heat by radiation:

    C dT/dt = P_heater(T) - S (T^4 - T_amb^4),   S = V0 I0 / (T0^4 - T_amb^4)

so the rated heater holds the rated temperature T0, and C = tau 4 S T0^3 makes `tau` the
linearized time constant there. Driven by voltage (a heater winding: P = V^2 / R), a 1%
change of V moves T by 2 / (4 + ALPHA) % (0.38%); driven by current (Phywe's set-up:
P = I^2 R), by 2 / (4 - ALPHA) % (0.71%).

**Emission.** Richardson-Dushman, I_s(T) = I_s0 (T / T0)^2 exp(-(phi / k)(1/T - 1/T0)), the
tube's emission capacity at T0 being `is0_a`. The tube's current is held under it by a smooth
ceiling, I / (1 + (I / I_s)^n)^(1/n), on every electrode alike; in a circuit (`heated`) taken
relative to its value at T0, since the tube models were fitted at the rated heater.

**The space-charge shift.** In front of a space-charge-limited cathode the potential has a
minimum V_m = (kT / q) ln(I / I_s(T)) (Langmuir): electrons leave over it, so the electrodes
see their voltages relative to it. Heating deepens it (I_s rises), which drives the tube like
a grid made more positive by

    dV = V_m(T0) - V_m(T) = (k / q) [T0 ln(I / I_s0) - T ln(I / I_s(T))]

zero at T0: the tube models' fits (at rated heater) hold there. I is the tube's current at
its unshifted operating point (`shift_v`), so the shift is a function of the port voltages and
T. ~+1.7 mV/K for a tube at 1% of its emission (phi 1.2 eV).

Values (`EC92`, fitted to Phywe LEP 4.1.10's Fig. 4 by scripts/fit_cathode.py) and the
provisional ones carry their sources in CATHODE_SOURCES.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

K_EV = 8.617333262e-5  # Boltzmann's constant, eV/K (CODATA 2018)

T0_K = 1050.0
T_AMB_K = 300.0
ALPHA = 1.2
TAU_S = 10.0

CATHODE_SOURCES = {
    "t0_k": (
        "provisional: model knowledge (oxide-coated cathodes run ~1000-1100 K; Herrmann & "
        "Wagener, The Oxide-Coated Cathode, 1951; Spangenberg, Vacuum Tubes, 1948)"
    ),
    "t_amb_k": "provisional: model knowledge (the chassis' air; the cathode sees it radiating)",
    "alpha": (
        "provisional: model knowledge (tungsten's resistance ~ T^1.2 over 1000-2000 K; the "
        "heater's temperature taken to track the cathode's)"
    ),
    "tau_s": (
        "provisional: model knowledge (RCA prints 'heater warm-up time 11 s' for its "
        "controlled-warm-up series-string types; a patent cites ~5.5 s to 10% current for a "
        "1.5 W oxide cathode)"
    ),
}


@dataclass(frozen=True)
class Cathode:
    """One tube's cathode: its heater rating, emission capacity at the rated temperature,
    work function, ceiling sharpness, and the thermal constants."""

    heater_v: float
    heater_a: float
    is0_a: float
    phi_ev: float
    n: float
    t0_k: float = T0_K
    t_amb_k: float = T_AMB_K
    alpha: float = ALPHA
    tau_s: float = TAU_S

    # --- heat ---

    @property
    def radiation(self) -> float:
        """S: W per K^4 radiated (the rated heater holds T0)."""
        return self.heater_v * self.heater_a / (self.t0_k**4 - self.t_amb_k**4)

    @property
    def heat_capacity(self) -> float:
        """C, J/K: tau is the linearized time constant at T0."""
        return self.tau_s * 4.0 * self.radiation * self.t0_k**3

    def heater_ohm(self, t_k: float) -> float:
        return self.heater_v / self.heater_a * (t_k / self.t0_k) ** self.alpha

    def heater_w(self, t_k: float, *, volts: float | None = None, amps: float | None = None):
        """Heater power at cathode temperature t_k, driven by `volts` or `amps`."""
        r = self.heater_ohm(t_k)
        return volts * volts / r if amps is None else amps * amps * r

    def dt_dt(self, t_k: float, volts: float) -> float:
        p = volts * volts / self.heater_ohm(t_k)
        return (p - self.radiation * (t_k**4 - self.t_amb_k**4)) / self.heat_capacity

    def steady_k(self, *, volts: float | None = None, amps: float | None = None) -> float:
        """The temperature a heater voltage (or current) holds: bisection."""
        lo, hi = self.t_amb_k, 4.0 * self.t0_k
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            gain = self.heater_w(mid, volts=volts, amps=amps)
            loss = self.radiation * (mid**4 - self.t_amb_k**4)
            lo, hi = (mid, hi) if gain > loss else (lo, mid)
        return 0.5 * (lo + hi)

    def warm(self, volts, t0_k: float, dt_s: float) -> np.ndarray:
        """Temperatures along a heater voltage sequence `volts` (one per dt_s), from t0_k:
        explicit Euler (the engines' order; tau >> dt)."""
        out = np.empty(len(volts))
        t = t0_k
        for i, v in enumerate(volts):
            t = t + dt_s * self.dt_dt(t, float(v))
            out[i] = t
        return out

    # --- emission ---

    def is_a(self, t_k: float) -> float:
        """Emission capacity at t_k (Richardson-Dushman, normalized at T0)."""
        return (
            self.is0_a
            * (t_k / self.t0_k) ** 2
            * math.exp(-(self.phi_ev / K_EV) * (1.0 / t_k - 1.0 / self.t0_k))
        )

    def ceiling(self, i_a, is_a: float):
        """The smooth ceiling's factor on a tube current i_a (all electrodes alike)."""
        x = np.maximum(np.asarray(i_a, float), 0.0) / is_a
        return (1.0 + x**self.n) ** (-1.0 / self.n)

    def shift_v(self, t_k: float, i_a) -> np.ndarray:
        """The space-charge shift (V, as on the grid) at t_k for a tube current i_a (its
        unshifted operating point's): 0 at T0."""
        i = np.clip(np.asarray(i_a, float), I_MIN_A, None)
        vt0, vt = K_EV * self.t0_k, K_EV * t_k
        r0 = np.minimum(i / self.is0_a, 1.0)
        r = np.minimum(i / self.is_a(t_k), 1.0)
        return vt0 * np.log(r0) - vt * np.log(r)


# The shift's current floor: a cut-off tube's potential minimum (and shift) stays finite.
I_MIN_A = 1e-9


# --- The circuits' cathodes (config/cathodes.yaml) -----------------------------------


@dataclass(frozen=True)
class Oxide:
    """config/cathodes.yaml's `oxide`: what every heated tube shares."""

    t0_k: float
    t_amb_k: float
    alpha: float
    tau_s: float
    phi_ev: float
    n: float
    emission_a_per_w: float


def load_cathodes(path=None) -> tuple[Oxide, dict[str, dict]]:
    """config/cathodes.yaml: the oxide constants (values) and the tube types' heaters."""
    import yaml

    from varimu.config import CONFIG_DIR

    d = yaml.safe_load((path or CONFIG_DIR / "cathodes.yaml").read_text(encoding="utf-8"))
    ox = Oxide(**{k: float(v["value"]) for k, v in d["oxide"].items()})
    return ox, d["tubes"]


def instance_is0_a(ox: Oxide, tube: dict, parallel: int = 1) -> float:
    """A device instance's emission at T0: emission per heater watt x its share of the
    heater (a bank of `parallel` tubes: that many)."""
    w = float(tube["heater_v"]) * float(tube["heater_a"]) / int(tube["cathodes"])
    return ox.emission_a_per_w * w * parallel


def heated(currents, v, shift_port: int, t_k: float, i_ref: float, is0_a: float, ox: Oxide):
    """A heated tube's port currents (the reference the engines port): the inner model
    `currents(v)` (port voltages -> port currents) at its control port moved by the space-
    charge shift for (t_k, i_ref), every current then under the emission ceiling. The shift's
    current `i_ref` is the tube's own at its last operating point (the engines: the last
    accepted step), so the device stays a function of its port voltages."""
    c = Cathode(1.0, 1.0, is0_a, ox.phi_ev, ox.n, t0_k=ox.t0_k)
    v2 = np.array(v, float)
    v2[shift_port] += float(c.shift_v(t_k, i_ref))
    i = np.asarray(currents(v2), float)
    ik = max(float(np.sum(i)), 0.0)
    # Relative to T0's: the inner models were fitted at the rated heater, so their curves
    # already hold whatever the ceiling takes there; a tube at T0 is its model exactly.
    return i * float(c.ceiling(ik, c.is_a(t_k)) / c.ceiling(ik, is0_a))


def port_currents(m, v) -> list[float]:
    """A tube model's port currents in the engines' convention (varimu.devices.fixtures):
    triode (Vpk, Vgk) -> (Ip, Ig), pentode (Vpk, Vg2k, Vg1k) -> (Ip, Ig2, Ig1), diode (Vak)."""
    from varimu.devices.diode import VacuumDiode
    from varimu.devices.pentode import Pentode
    from varimu.devices.triode import Triode

    if isinstance(m, Triode):
        return [float(m.ip(v[1], v[0])), float(m.ig(v[1]))]
    if isinstance(m, Pentode):
        return [float(m.ip(v[2], v[1], v[0])), float(m.ig2(v[2], v[1])), float(m.ig1(v[2]))]
    if isinstance(m, VacuumDiode):
        return [float(m.i(v[0]))]
    raise TypeError(type(m))


def cathode_fixtures_json() -> str:
    """Fixtures for crates/circuitsim/tests/cathode.rs: `heated` on a triode, a pentode and a
    vacuum diode over port voltages, temperatures and reference currents (written by
    scripts/export_circuit_fixtures.py; tests/test_cathode.py checks the file is current)."""
    import json

    from varimu.circuit.ir import model_to_dict
    from varimu.devices.library import load_device

    ox, tubes = load_cathodes()
    cases = [
        ("12AX7@1", "12AX7", 1, [(250.0, -1.5), (100.0, -0.5), (300.0, 0.3), (150.0, -4.0)]),
        ("6V6GT@1", "6V6GT", 2, [(250.0, 250.0, -12.5), (100.0, 250.0, -5.0), (300.0, 200.0, 0.5)]),
        ("6X4@1", "6X4", 0, [(5.0,), (20.0,), (50.0,), (-1.0,)]),
    ]
    out = []
    for device, kind, port, volts in cases:
        m = load_device(device)
        is0 = instance_is0_a(ox, tubes[kind])
        pts = []
        for v in volts:
            for t in (750.0, 900.0, 1000.0, ox.t0_k, 1080.0):
                for i_ref in (1e-6, 1e-3, 2e-2):
                    i = heated(lambda x, m=m: port_currents(m, x), v, port, t, i_ref, is0, ox)
                    pts.append({"v": list(v), "t_k": t, "i_ref": i_ref, "currents": i.tolist()})
        out.append({"model": model_to_dict(m), "port": port, "is0_a": is0, "points": pts})
    d = {"phi_ev": ox.phi_ev, "n": ox.n, "t0_k": ox.t0_k, "devices": out}
    return json.dumps(d, indent=1) + "\n"
