"""Hysteretic magnetic core: the Jiles-Atherton model as a circuit device (Phase 2).

The model (Jiles & Atherton 1986), with the irreversible magnetization a
function of the effective field (the form the grain-oriented steel set of
config/magnetics.yaml was identified in, arXiv:2405.11011 eqs. 1-5):

    M = Mrev + Mirr,   He = H + alpha M,   Man = Ms L(He / a)
    dMirr/dHe = dM (Man - Mirr) / (delta k),   Mrev = c (Man - Mirr)
    chi_e = dM/dHe = dM |Man - M| / k + c (Ms / a) L'(He / a)
    dM/dH = chi_e / (1 - alpha chi_e)

with L(x) = coth(x) - 1/x, delta = sign(dH/dt), dM = 1 when delta and
Man - M have the same sign, else 0 (no irreversible change against the
anhysteretic curve; Man - Mirr = (Man - M) / (1 - c)). B = mu0 (H + M).
(The other common form, dMirr/dH = (Man - Mirr) / (delta k - alpha (Man -
Mirr)), as in Holters & Zoelzer, DAFx-16, eq. 9, has a pole where
alpha |Man - Mirr| reaches k; with these materials M lags Man that far near
saturation, and H(B) jumped there. Measured 2026-10-21.)

How it sits in a circuit (varimu.circuit.ir: Winding, MagneticCore): every
core has a node whose voltage is its flux density B (1 V = 1 mT,
TESLA_PER_V). A winding of N turns on a core of cross-section A has
v = N A dB/dt and feeds N i into the core node (Ampere's law), and this
device, from the core node to ground, draws the core's magnetomotive force
l_e H(B): the node's KCL is sum(N i) = l_e H. Air gap and eddy-current loss
are linear (a conductance and a capacitance on the core node, from the
netlist), so the device is the magnetization alone.

The device is rate-independent, as the JA model is: H depends only on the
path of B. Between accepted time steps the path is taken as monotonic, from
the last accepted point (b0, h0) to the B being evaluated, so
H(B) = h0 + integral of dH/dB from b0 to B with delta = sign(B - b0): a
function of B alone within a step, which Newton solves like any other
device. `accept` moves the state on. The integral runs in RK4 substeps:
at most DB_MAX of B, at most DH_REL (a + |H|) of H at the starting slope
(RK4 stays stable where the path is stiff, deep in saturation of a
high-permeability material), and halved until the slopes at its start and
end agree within SLOPE_TOL (curvature: an almost all irreversible material's
initial curve, e.g. mumetall's 2026-10-21 fit, bends within a fraction of a
microtesla of the demagnetized state); a substep after an
accepted one may be twice as long. The right-hand side is continuous (the
irreversible term vanishes where its gate switches), so the halving
converges. The state integrates H, not M: at high permeability H is the
small difference B / mu0 - M, so integrating it keeps it accurate.

Numerical guards (not physics): 1 - alpha chi_e is kept above DEN_FLOOR
(beyond it the model's susceptibility would turn negative; a physical
parameter set stays clear of it), and the Langevin function and its
derivative use Taylor series for |x| < 1e-2.

This is the Python reference; crates/circuitsim/src/devices/core.rs is its
compiled port (same order of operations), tested against fixtures from here.
There is no SPICE implementation (decided 2026-10-21): ngspice simulates the
core in its linear limit (`linear_conductance`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache
from typing import Any

import yaml

from varimu.config import CONFIG_DIR, ConfigError

MAGNETICS_FILE = CONFIG_DIR / "magnetics.yaml"
JA_FIELDS = ("ms_a_per_m", "a_a_per_m", "k_a_per_m", "c", "alpha")

MU0 = 1.25663706212e-6  # H/m (CODATA 2018)
TESLA_PER_V = 1e-3  # core node voltage scale: 1 V on a core node = 1 mT
DB_MAX = 1e-3  # T, the longest RK4 substep along B
DH_REL = 0.05  # ... and its change of H at most this times a + |H|
SLOPE_TOL = 0.25  # ... and the slope at its end within this of its start
DB_MIN = 1e-12  # T, the shortest substep (a guard)
MAX_SUBSTEPS = 1_000_000  # a guard: a transient step takes one or a few
DEN_FLOOR = 0.05


def langevin(x: float) -> float:
    if abs(x) < 1e-2:
        x2 = x * x
        return x * (1 / 3 - x2 * (1 / 45 - x2 * (2 / 945)))
    return 1 / math.tanh(x) - 1 / x


def dlangevin(x: float) -> float:
    if abs(x) < 1e-2:
        x2 = x * x
        return 1 / 3 - x2 * (1 / 15 - x2 * (2 / 189))
    if abs(x) > 300:
        return 1 / (x * x)
    s = math.sinh(x)
    return 1 / (x * x) - 1 / (s * s)


@dataclass(frozen=True)
class CoreState:
    """The last accepted point of the core: B (T), H (A/m), direction of B (+-1)."""

    b: float = 0.0
    h: float = 0.0
    delta: float = 1.0


DEMAGNETIZED = CoreState()


@dataclass(frozen=True)
class MagneticCore:
    """A core of one Jiles-Atherton material with magnetic path length `path_m`.

    Pins (b, ref): the core node and ground. Port voltage: B / TESLA_PER_V;
    port current: path_m * H (A, the magnetomotive force), into pin b.
    """

    name: str
    ms_a_per_m: float  # saturation magnetization Ms
    a_a_per_m: float  # anhysteretic shape a
    k_a_per_m: float  # pinning k (loop width)
    c: float  # reversibility (0..1)
    alpha: float  # inter-domain coupling
    path_m: float  # magnetic path length l_e

    def validate(self) -> list[str]:
        problems = [
            f"{f} = {v} must be > 0"
            for f, v in (
                ("ms_a_per_m", self.ms_a_per_m),
                ("a_a_per_m", self.a_a_per_m),
                ("k_a_per_m", self.k_a_per_m),
                ("path_m", self.path_m),
            )
            if not (math.isfinite(v) and v > 0)
        ]
        if not (0 <= self.c < 1):
            problems.append(f"c = {self.c} must be in [0, 1)")
        if not (math.isfinite(self.alpha) and self.alpha >= 0):
            problems.append(f"alpha = {self.alpha} must be >= 0")
        elif self.alpha * self.c * self.ms_a_per_m / (3 * self.a_a_per_m) >= 1:
            problems.append("alpha c Ms / (3 a) must be < 1 (else dM/dH diverges at the origin)")
        return problems

    # --- The material ---

    def susceptibility(self, h: float, m: float, delta: float) -> float:
        """dM/dH at (H, M) for direction delta."""
        ms, a, k, c, alpha = self.ms_a_per_m, self.a_a_per_m, self.k_a_per_m, self.c, self.alpha
        x = (h + alpha * m) / a
        d = ms * langevin(x) - m
        chi_e = c * (ms / a) * dlangevin(x)
        if delta * d > 0:
            chi_e = chi_e + abs(d) / k
        return chi_e / max(1 - alpha * chi_e, DEN_FLOOR)

    def dh_db(self, b: float, h: float, delta: float) -> float:
        chi = self.susceptibility(h, b / MU0 - h, delta)
        return 1 / (MU0 * (1 + chi))

    def h_of_b(self, b: float, state: CoreState = DEMAGNETIZED) -> tuple[float, float]:
        """H at flux density b on the path from `state`, and dH/dB there."""
        b0, h = state.b, state.h
        if b == b0:
            return h, self.dh_db(b, h, state.delta)
        delta = 1.0 if b > b0 else -1.0
        bj, size = b0, DB_MAX
        for _ in range(MAX_SUBSTEPS):
            rest = b - bj
            k1 = self.dh_db(bj, h, delta)
            size = min(size, DB_MAX, DH_REL * (self.a_a_per_m + abs(h)) / k1)
            while True:
                last = size >= abs(rest)
                step = rest if last else math.copysign(size, rest)
                k2 = self.dh_db(bj + 0.5 * step, h + 0.5 * step * k1, delta)
                k3 = self.dh_db(bj + 0.5 * step, h + 0.5 * step * k2, delta)
                k4 = self.dh_db(bj + step, h + step * k3, delta)
                if abs(k4 - k1) <= SLOPE_TOL * max(k1, k4) or abs(step) <= DB_MIN:
                    break
                size = 0.5 * abs(step)
            h = h + step / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
            if last:
                break
            bj = bj + step
            size = 2 * size
        return h, self.dh_db(b, h, delta)

    def advance(self, b: float, state: CoreState = DEMAGNETIZED) -> CoreState:
        """The state after accepting the point b."""
        h, _ = self.h_of_b(b, state)
        delta = state.delta if b == state.b else (1.0 if b > state.b else -1.0)
        return CoreState(b, h, delta)

    # --- As a device ---

    def port_current(self, v: float, state: CoreState = DEMAGNETIZED) -> tuple[float, float]:
        """(current, d current / d v) at port voltage v (= B / TESLA_PER_V)."""
        h, dh = self.h_of_b(v * TESLA_PER_V, state)
        return self.path_m * h, self.path_m * dh * TESLA_PER_V

    def initial_susceptibility(self) -> float:
        """dM/dH at the demagnetized origin: the model's small-signal limit."""
        return self.susceptibility(0.0, 0.0, 1.0)

    def linear_conductance(self) -> float:
        """Port conductance (A/V) of the linear-limit core: B = mu0 (1 + chi0) H."""
        return self.path_m * TESLA_PER_V / (MU0 * (1 + self.initial_susceptibility()))

    def trace(self, b_path, state: CoreState = DEMAGNETIZED) -> list[float]:
        """H along a path of B values, accepting each point (for loop plots and tests)."""
        out = []
        for b in b_path:
            h, _ = self.h_of_b(float(b), state)
            state = self.advance(float(b), state)
            out.append(h)
        return out


# --- Materials (config/magnetics.yaml) ---


@cache
def materials() -> dict[str, dict[str, Any]]:
    """Every material in config/magnetics.yaml; each needs the JA fields and a source."""
    with open(MAGNETICS_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)["materials"]
    for name, m in data.items():
        missing = [k for k in (*JA_FIELDS, "source") if k not in m]
        if missing:
            raise ConfigError(f"{MAGNETICS_FILE}: material {name} lacks {missing}")
        for k in ("lamination_m", "resistivity_ohm_m"):
            src = k.split("_")[0] + "_source"
            if k in m and not str(m.get(src, "")).strip():
                raise ConfigError(f"{MAGNETICS_FILE}: material {name}: {k} needs {src}")
    return data


def core_model(name: str, material: str, path_m: float, **overrides: float) -> MagneticCore:
    """A core of `material` with magnetic path `path_m`; JA fields can be overridden."""
    m = materials()[material]
    ja = {k: float(overrides.get(k, m[k])) for k in JA_FIELDS}
    unknown = set(overrides) - set(JA_FIELDS)
    if unknown:
        raise KeyError(f"unknown JA parameters {sorted(unknown)}")
    return MagneticCore(name, path_m=float(path_m), **ja)
