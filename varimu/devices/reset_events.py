"""Event kernels for a relaxation oscillator's reset and a comparator's edge: technique K's
Python reference beyond the gas tube (HYBRID_PHYSICS_PLAN.md "K's design"; the gas tube's is
varimu.devices.thyratron_events, whose band-limiting, crossing prediction and phase
interpolation this reuses). First user: the Minimoog's oscillator (docs/MINIMOOG_PLAN.md MM3,
reports/minimoog/vco/README.md: its ~0.3 us reset stalls every direct simulation below ~10 MHz).

A circuit file's `exceptions` block names each exception's unit: the parts an events build
replaces, the element's nodes, the tables (config/events/<name>.json). Two kinds:

**reset**: a capacitor discharged by a constant current (the ramp falling) and recharged in a
fast event when the ramp, as `sense` sees it, falls through a trigger level. Its element
injects the event's charge from `src` into `dst` (the Minimoog: from the +5 V reference into
C7's lower plate). One axis, the ramp's slope S (V/s, falling, > 0), log-spaced; per point:
- v_t: the sensed ramp at the event's start (the injected current passing `I_START_A`);
- the injected current's pulse from that moment at the reference rate, to its end (below
  `END_REL` of its peak for `END_HOLD_S`); the dead time is its length.
Tables come from reference runs of the unit (`reset_unit_ir`: the circuit without the
summers and the expo, a constant current sink in the expo's place, C7 started a little above
the trigger, at the reference rate with error control).

**edge**: a comparator whose output switches a current to a rail (an open collector). Its
element senses (plus - minus) and injects the output current from `src` into `dst` (the
Minimoog's rectangle: from the collector node into V-), per direction (on: the sink starting
as plus falls below minus; off: as it rises above), one axis the input difference's slope;
per point the output current's waveform from the input's zero crossing to settled.

At the audio rate a reset is its band-limited step charges (thyratron_events.step_charges, the
minimum-phase low-pass); an edge is a step of the held current, band-limited the same way
(`edge_step_table`). Before each step the margin's zero is predicted from the last three
samples (thyratron_events.predict_crossing). circuitsim's reset_events.rs is the port: the same
arithmetic in the same order.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.devices.thyratron_events import cubic_phase, minphase_lowpass, predict_crossing

FS = 96000
REF_OVERSAMPLE = 128
REF_RATE = REF_OVERSAMPLE * FS  # 12.288 MHz: the Minimoog oscillator's converged reference
I_START_A = 100e-6
END_REL = 1e-3
END_HOLD_S = 3e-6
EDGE_SETTLE_REL = 1e-4  # an edge settled: within this of its final value for END_HOLD_S
FIT_S = 10e-6  # a reset's clean ramp: fitted over FIT_V of it (at least FIT_S), ending
FIT_V = 0.02  # FIT_GAP_S before its start
FIT_GAP_S = 3e-6
G_FIT_V = 2.0  # the discharging network's conductance: the ramp's curvature over this of it
HISTORY = 3  # samples the crossing prediction uses: none spans an event
EVENTS_DIR = CONFIG_DIR / "events"
CACHE = REPO_ROOT / "cache" / "hybrid" / "reset"


# --- Band-limited steps for an edge -----------------------------------------------------------


def edge_step_table(shape: np.ndarray, h: np.ndarray, oversample: int) -> np.ndarray:
    """A transition's normalized shape s (0 .. 1 at the reference rate from the event, held at
    its last value after), band-limited by h, integrated over each step of `oversample`
    reference samples at every offset j / oversample (j = 0 .. oversample): array
    (oversample + 1, steps), in steps (multiply by the step h and the current's change). After
    the last column every step integrates to 1 (the new state's whole step)."""
    # the shape held at 1 through the kernel's length (a plain convolution would take it as 0
    # past its end and the step would fall back), then 1 beyond (h sums to 1)
    n = len(shape) + len(h) - 1
    g = np.convolve(np.concatenate([shape, np.ones(len(h) - 1)]), h)[:n]
    g = np.concatenate([g, np.ones(oversample)])
    steps = int(np.ceil((len(g) + oversample) / oversample))
    out = np.zeros((oversample + 1, steps))
    for j in range(oversample + 1):
        buf = np.ones(steps * oversample)
        buf[:j] = 0.0
        buf[j : j + len(g)] = g
        out[j] = buf.reshape(steps, oversample).sum(axis=1) / oversample
    return out


def step_charges_m(pulse_a: np.ndarray, h: np.ndarray, oversample: int, rate: float):
    from varimu.devices.thyratron_events import step_charges

    return step_charges(pulse_a, h, oversample, rate)


# --- Tables -----------------------------------------------------------------------------------


@dataclass
class ResetTables:
    """A reset unit's tables over log slope (ascending): the trigger level, the dead time, each
    point's pulse (amperes at ref_rate_hz into dst, from the event's start), and g_s, the
    discharging network's conductance (how its current grows with the ramp's voltage: Q7's
    Early effect, from the ramp's curvature) for the deficit (`ResetRun`); c_f, the capacitance
    the injected charge lands on (the sensed ramp's step is charge / c_f), for the
    band-limiting's lag correction."""

    log_slope: np.ndarray
    v_t: np.ndarray
    dead_s: np.ndarray
    pulses: list[np.ndarray]
    g_s: np.ndarray
    c_f: float
    source: dict
    ref_rate_hz: float = REF_RATE

    def __post_init__(self):
        self._charges: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self.centroids = np.array([_centroid(p) for p in self.pulses])

    def charges(self, oversample: int) -> tuple[np.ndarray, np.ndarray]:
        """The band-limited and raw step charges (slope, phase, step), coulombs; cached."""
        if oversample not in self._charges:
            h = minphase_lowpass(oversample)
            rate = self.ref_rate_hz
            pts = [
                (
                    step_charges_m(p, h, oversample, rate),
                    step_charges_m(p, np.ones(1), oversample, rate),
                )
                for p in self.pulses
            ]
            steps = max(a.shape[1] for pr in pts for a in pr)
            q = np.zeros((len(self.log_slope), oversample + 1, steps))
            q_raw = np.zeros_like(q)
            for i, (a, b) in enumerate(pts):
                q[i, :, : a.shape[1]] = a
                q_raw[i, :, : b.shape[1]] = b
            self._charges[oversample] = (q, q_raw)
        return self._charges[oversample]

    def to_dict(self) -> dict:
        return {
            "kind": "reset",
            "ref_rate_hz": float(self.ref_rate_hz),
            "c_f": float(self.c_f),
            "log_slope": [float(x) for x in self.log_slope],
            "v_t_v": [float(x) for x in self.v_t],
            "dead_s": [float(x) for x in self.dead_s],
            "pulses_a": [[float(x) for x in p] for p in self.pulses],
            "g_s": [float(x) for x in self.g_s],
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ResetTables:
        return cls(
            log_slope=np.array(d["log_slope"], float),
            v_t=np.array(d["v_t_v"], float),
            dead_s=np.array(d["dead_s"], float),
            pulses=[np.array(p, float) for p in d["pulses_a"]],
            g_s=np.array(d["g_s"], float),
            c_f=float(d["c_f"]),
            source=d["source"],
            ref_rate_hz=float(d["ref_rate_hz"]),
        )


@dataclass
class EdgeTables:
    """A comparator edge's tables, per direction (0: on, the sink starting as plus falls below
    minus; 1: off) over log slope of |plus - minus| (ascending): the output current's waveform
    from the input's zero crossing (amperes at ref_rate_hz, src -> dst), settled at its end."""

    log_slope: np.ndarray
    waves: list[list[np.ndarray]]  # [direction][slope]
    source: dict
    ref_rate_hz: float = REF_RATE

    def __post_init__(self):
        self._steps: dict[int, np.ndarray] = {}

    def levels(self, direction: int, i: int) -> tuple[float, float]:
        w = self.waves[direction][i]
        return float(w[0]), float(w[-1])

    def steps(self, oversample: int) -> np.ndarray:
        """Each wave's normalized band-limited steps (direction, slope, phase, step); cached."""
        if oversample not in self._steps:
            h = minphase_lowpass(oversample)
            tabs = []
            for row in self.waves:
                for w in row:
                    a, b = float(w[0]), float(w[-1])
                    tabs.append(edge_step_table((w - a) / (b - a), h, oversample))
            n = max(t.shape[1] for t in tabs)
            out = np.ones((2, len(self.log_slope), oversample + 1, n))
            for k, t in enumerate(tabs):
                out[k // len(self.log_slope), k % len(self.log_slope), :, : t.shape[1]] = t
            self._steps[oversample] = out
        return self._steps[oversample]

    def to_dict(self) -> dict:
        return {
            "kind": "edge",
            "ref_rate_hz": float(self.ref_rate_hz),
            "log_slope": [float(x) for x in self.log_slope],
            "waves_a": [[[float(x) for x in w] for w in row] for row in self.waves],
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EdgeTables:
        return cls(
            log_slope=np.array(d["log_slope"], float),
            waves=[[np.array(w, float) for w in row] for row in d["waves_a"]],
            source=d["source"],
            ref_rate_hz=float(d["ref_rate_hz"]),
        )


def _centroid(p: np.ndarray) -> float:
    """A pulse's centroid in reference samples from its start (a plain loop: circuitsim's sum)."""
    num, den = 0.0, 0.0
    for n, x in enumerate(p):
        num = num + n * float(x)
        den = den + float(x)
    return num / den


def load_tables(name: str) -> ResetTables | EdgeTables:
    d = json.loads((EVENTS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return ResetTables.from_dict(d) if d["kind"] == "reset" else EdgeTables.from_dict(d)


def save_tables(name: str, t: ResetTables | EdgeTables) -> Path:
    path = EVENTS_DIR / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(t.to_dict(), allow_nan=False) + "\n", encoding="utf-8")
    return path


def _ix(grid: np.ndarray, x: float) -> tuple[int, float]:
    """The cell of an ascending grid holding x (clamped to it) and x's fraction in it."""
    x = min(max(x, float(grid[0])), float(grid[-1]))
    i = min(int(np.searchsorted(grid, x, side="right")) - 1, len(grid) - 2)
    return i, (x - float(grid[i])) / (float(grid[i + 1]) - float(grid[i]))


# --- Run time ---------------------------------------------------------------------------------


def edge_phase_row(q: np.ndarray, j: int, m: int) -> np.ndarray:
    """Row j (-1 .. m + 1) of an edge's (m + 1, steps) step table: beyond the ends, the end
    rows a whole step on (row -1 is row m - 1 a step earlier: what it moved in that step is
    gone, the step after it is 1; row m + 1 is row 1 a step later: nothing in its first)."""
    if j < 0:
        return np.concatenate([q[m - 1][1:], [1.0]])
    if j > m:
        return np.concatenate([[0.0], q[1][:-1]])
    return q[j]


def edge_cubic_phase(q: np.ndarray, j0: int, a: float, m: int) -> np.ndarray:
    """An edge's step table at phase row j0 + a (0 <= a < 1): Lagrange through rows j0 - 1 ..
    j0 + 2 (thyratron_events.cubic_phase's weights, edge_phase_row's ends)."""
    w = (-a * (a - 1.0) * (a - 2.0) / 6.0, (a + 1.0) * (a - 1.0) * (a - 2.0) / 2.0,
         -(a + 1.0) * a * (a - 2.0) / 2.0, (a + 1.0) * a * (a - 1.0) / 6.0)  # fmt: skip
    out = w[0] * edge_phase_row(q, j0 - 1, m)
    out = out + w[1] * edge_phase_row(q, j0, m)
    out = out + w[2] * edge_phase_row(q, j0 + 1, m)
    return out + w[3] * edge_phase_row(q, j0 + 2, m)


class ResetRun:
    """K's run time on a reset unit (circuitsim's reset_events.rs is its port): given the
    sensed ramp after each sample, the current held over the next step from src into dst.

    The ramp the margin sees is the sensed one less what the band-limiting hasn't yet passed
    on (the filtered charges so far less the raw, over c_f), so the margin and the slope see
    the ramp, not the kernel's ringing. Before each step, from the third sample on and once
    the dead time has passed: the slope S from the last two (falling: no event on a rising
    ramp), v_t(S), the margin's zero within the step (predict_crossing on v_t - ramp); then the
    slope at the crossing from the same quadratic and v_t there, once; an event adds its
    charges at that phase (cubic between the table's phase rows) to the pending ones and
    starts the dead time (at least HISTORY samples).

    The deficit (`_deficit`, thyratron_events.Events._deficit's with the other sign): the
    band-limited capacitor reaches its new voltage about the kernel's delay after the
    physical one, and the network discharging it (the expo's Q7, its current growing with
    its collector's voltage: the Early effect, conductance g_s) removes less meanwhile; that
    charge is removed from dst in the event's band-limited shape (`i_comp`, dst -> ground).
    Without it the Minimoog's oscillator ran flat by the kernel's delay: -7 cents at 4 kHz at
    96 kHz, first order in the step."""

    def __init__(self, t: ResetTables, h: float):
        self.t, self.h = t, h
        m = t.ref_rate_hz * h
        self.m = round(m)
        if self.m < 1 or abs(m - self.m) > 1e-9 * self.m:
            raise ValueError(f"the step {h} s isn't a whole number of reference samples")
        q = t.charges(self.m)[0]
        n = q.shape[-1] + 2
        self.pending, self.pending_raw = np.zeros(n), np.zeros(n)
        self.pending_comp = np.zeros(n)
        self.hist = [0.0, 0.0, 0.0]
        self.n = 0
        self.i_held = 0.0
        self.i_comp = 0.0
        self.lag = 0.0
        self.busy_until = 0.0
        self.events = self.late = 0
        self.times: list[float] = []  # each event's sample plus phase (diagnostics)
        # For an edge that follows it (EdgeRun's `lead`), as of the last sense: the lag
        # correction it applied (volts at the sense), the phase of an event it fired for the
        # coming step (None: none), that event's physical jump (its raw charge over c_f).
        self.lag_v = 0.0
        self.fired: float | None = None
        self.jump_v = 0.0

    def _deficit(self, qq: np.ndarray, phi: float, centroid: float, g: float) -> np.ndarray:
        """The charge the discharging network doesn't remove during the kernel's delay, as
        charges per step to remove from dst (in the event's band-limited shape): g times the
        jump (the band-limited charges over c_f) times the delay (their centroid, held over
        each step, less the pulse's own: the phase plus its centroid, less a held current's
        half step on average)."""
        m = self.m
        kq, total = 0.0, 0.0
        for k in range(len(qq)):
            kq = kq + k * float(qq[k])
            total = total + float(qq[k])
        if g <= 0.0 or total <= 0.0:
            return np.zeros(len(qq))
        acc = kq - total * (phi + centroid / m - (m - 1) / (2 * m))
        return qq * (g * self.h / self.t.c_f * acc / total)

    def v_t_at(self, s: float) -> float:
        i, a = _ix(self.t.log_slope, math.log(max(s, 1e-30)))
        return (1.0 - a) * float(self.t.v_t[i]) + a * float(self.t.v_t[i + 1])

    def sense(self, v: float) -> float:
        """Sample n's sensed ramp; the current held over the step to n + 1."""
        t, h, m = self.t, self.h, self.m
        self.lag_v = self.lag / t.c_f
        self.fired = None
        v_phys = v - self.lag_v
        self.hist = [self.hist[1], self.hist[2], v_phys]
        n = self.n
        if n >= 2 and n >= self.busy_until:
            h0, h1, h2 = self.hist
            s = (h1 - h2) / h
            if s > 0.0:
                vt = self.v_t_at(s)
                phi = predict_crossing((vt - h0, vt - h1, vt - h2))
                if phi is not None and phi > 0.0:
                    qa = 0.5 * (h0 - 2.0 * h1 + h2)
                    qb = 0.5 * (h0 - 4.0 * h1 + 3.0 * h2)
                    s2 = -(qb + 2.0 * qa * phi) / h
                    if s2 > 0.0:
                        vt2 = self.v_t_at(s2)
                        phi2 = predict_crossing((vt2 - h0, vt2 - h1, vt2 - h2))
                        if phi2 is not None:
                            s, phi = s2, phi2
                if phi is not None:
                    i, a = _ix(t.log_slope, math.log(s))
                    q_all, raw_all = t.charges(m)
                    q = (1.0 - a) * q_all[i] + a * q_all[i + 1]
                    q_raw = (1.0 - a) * raw_all[i] + a * raw_all[i + 1]
                    dead = (1.0 - a) * float(t.dead_s[i]) + a * float(t.dead_s[i + 1])
                    g = (1.0 - a) * float(t.g_s[i]) + a * float(t.g_s[i + 1])
                    cen = (1.0 - a) * float(t.centroids[i]) + a * float(t.centroids[i + 1])
                    self.events += 1
                    self.late += phi == 0.0
                    self.times.append(n + phi)
                    j = phi * m
                    j0 = min(int(j), m - 1)
                    b = j - j0
                    qq = cubic_phase(q, j0, b, m)
                    rr = (1.0 - b) * q_raw[j0] + b * q_raw[j0 + 1]
                    cc = self._deficit(qq, phi, cen, g)
                    self.fired = phi
                    self.jump_v = float(rr.sum()) / t.c_f
                    self.pending[: len(qq)] += qq
                    self.pending_raw[: len(rr)] += rr
                    self.pending_comp[: len(cc)] += cc
                    # not before the samples the prediction uses all lie after the event's
                    # end (a quadratic through a sample before it, or one the pulse spilled
                    # into, puts a false root in the next step: the reset is far shorter
                    # than a step, so its dead time alone would allow that)
                    self.busy_until = math.ceil(n + phi + dead / h) + HISTORY - 1
        self.i_held = float(self.pending[0]) / h
        self.i_comp = float(self.pending_comp[0]) / h
        self.lag = self.lag + (float(self.pending[0]) - float(self.pending_raw[0]))
        for p in (self.pending, self.pending_raw, self.pending_comp):
            p[:-1] = p[1:].copy()
            p[-1] = 0.0
        self.n = n + 1
        return self.i_held


class EdgeRun:
    """K's run time on a comparator edge (circuitsim's port alongside ResetRun): given the
    sensed (plus - minus) after each sample, the current held over the next step from src into
    dst. The state is the comparator's (on: sinking, plus below minus); a predicted zero of the
    difference within the next step, in the direction that flips it, starts the transition:
    the table's levels at the slope (interpolated), its normalized band-limited step at the
    phase (cubic between phase rows), and the held current moves to the new level through
    them. Starts in the state its first sense says (no transition at the start).

    An edge may follow a reset (its input a divider `gain` of the reset's sensed ramp: the
    Minimoog's rectangle on its saw): it then senses its input corrected by the reset's lag
    (gain times it: the physical input, not the band-limited one, so its own kernel's delay
    isn't stacked on the reset's), and when the reset fires and its physical jump carries the
    input across the threshold (on, the input above zero after it), the edge turns off at the
    reset's phase (a prediction from samples across a jump far shorter than a step can't
    place it: 63 % duty for 52 % at 4 kHz)."""

    def __init__(self, t: EdgeTables, h: float, gain: float | None = None):
        self.t, self.h = t, h
        m = t.ref_rate_hz * h
        self.m = round(m)
        if self.m < 1 or abs(m - self.m) > 1e-9 * self.m:
            raise ValueError(f"the step {h} s isn't a whole number of reference samples")
        st = t.steps(self.m)
        self.pending = np.zeros(st.shape[-1] + 2)
        self.level = 0.0
        self.on: bool | None = None
        self.busy_until = 0
        self.hist = [0.0, 0.0, 0.0]
        self.n = 0
        self.i_held = 0.0
        self.events = self.late = 0
        self.gain = gain

    def _levels(self, d: int, s: float) -> tuple[float, float]:
        i, a = _ix(self.t.log_slope, math.log(max(s, 1e-30)))
        l0, l1 = self.t.levels(d, i), self.t.levels(d, i + 1)
        return (1.0 - a) * l0[0] + a * l1[0], (1.0 - a) * l0[1] + a * l1[1]

    def sense(self, v: float, lead: ResetRun | None = None) -> float:
        """Sample n's sensed plus - minus (and, following a reset, that reset after its own sense
        of sample n); the current held over the step to n + 1."""
        t, h, m = self.t, self.h, self.m
        if lead is not None:
            v = v - self.gain * lead.lag_v
        self.hist = [self.hist[1], self.hist[2], v]
        n = self.n
        if self.on is None:
            self.on = v < 0.0
            self.level = self._levels(0 if self.on else 1, 1.0)[1]
        elif n >= 2 and n >= self.busy_until:
            h0, h1, h2 = self.hist
            # the margin that rises through 0 when the state flips: on <- plus falls below minus
            sign = -1.0 if not self.on else 1.0
            mm = (sign * h0, sign * h1, sign * h2)
            phi = predict_crossing(mm)
            s = abs(h2 - h1) / h
            hold = 0.0
            if (
                lead is not None
                and lead.fired is not None
                and self.on
                and v + self.gain * lead.jump_v > 0.0
            ):
                # the reset's jump carries the input across: off at its phase, as fast as the
                # tables go; no prediction until the reset's own history is past its jump (its
                # raw pulse may spill into the next step: a sample before the jump in the
                # history put a false crossing right after it)
                phi, s = lead.fired, math.exp(float(t.log_slope[-1]))
                hold = lead.busy_until
            if phi is not None:
                d = 0 if not self.on else 1
                i, a = _ix(t.log_slope, math.log(max(s, 1e-30)))
                stp = t.steps(m)[d]
                q = (1.0 - a) * stp[i] + a * stp[i + 1]
                lo, hi = self._levels(d, s)
                j = phi * m
                j0 = min(int(j), m - 1)
                b = j - j0
                qq = edge_cubic_phase(q, j0, b, m)  # in steps: 0 before, 1 after
                # the held current: the old level plus the change times the step's share
                delta = hi - self.level
                self.pending[: len(qq)] += delta * (qq - 1.0)
                self.level = hi
                self.on = not self.on
                self.busy_until = max(n + HISTORY, hold)
                self.events += 1
                self.late += phi == 0.0
        self.i_held = self.level + float(self.pending[0])
        self.pending[:-1] = self.pending[1:].copy()
        self.pending[-1] = 0.0
        self.n = n + 1
        return self.i_held


# --- Reference runs and table generation (the Minimoog oscillator) ------------------------------


def _engine_hash() -> str:
    from varimu.devices.thyratron_events import engine_hash

    return engine_hash()


def tables_key(*parts) -> str:
    import inspect

    h = hashlib.sha256()
    for p in parts:
        h.update(p if isinstance(p, bytes) else json.dumps(p, sort_keys=True, default=str).encode())
    h.update(_engine_hash().encode())
    for f in (reset_event, edge_event):
        h.update(inspect.getsource(f).encode())
    h.update(repr((REF_RATE, I_START_A, END_REL, END_HOLD_S, EDGE_SETTLE_REL)).encode())
    return h.hexdigest()[:16]


def reset_event(v: dict, rate: float, c_f: float, steady: bool) -> dict | None:
    """A reset of a reference run: `i_ev` the injected current per sample (charge per sample
    times the rate), `sense` the sensed ramp. The event starts where i_ev passes I_START_A
    (interpolated; what passed before since the previous event's end goes into its first
    sample), ends below END_REL of its peak for END_HOLD_S; `steady`: the last complete one
    after at least two, else the first."""
    i_ev, sense = v["i_ev"], v["sense"]
    ks = np.where((i_ev[:-1] < I_START_A) & (i_ev[1:] >= I_START_A))[0]
    if not len(ks):
        return None
    hold = int(round(END_HOLD_S * rate))

    def end_of(k: int) -> int | None:
        seg = np.abs(i_ev[k:])
        low = seg < END_REL * np.maximum.accumulate(seg)
        run = np.convolve(low.astype(int), np.ones(hold, int), "valid")
        first = np.where(run == hold)[0]
        return k + int(first[0]) if len(first) else None

    ends = [end_of(int(k)) for k in ks]
    done = [i for i in range(len(ks)) if ends[i] is not None]
    if steady:
        done = [i for i in done if i >= 2]
    if not done:
        return None
    i = done[-1] if steady else done[0]
    k, end = int(ks[i]), ends[i]
    start = ends[i - 1] if i > 0 and ends[i - 1] is not None else 0
    frac = (I_START_A - i_ev[k]) / (i_ev[k + 1] - i_ev[k])
    # The clean ramp: a line fitted over FIT_S ending FIT_GAP_S before the start (the event's
    # onset, the comparator's output moving through C9 and Q4's Cgd, bumps the ramp up for ~1
    # us before the injected current passes I_START_A; K sees the ramp at the audio rate,
    # before it). v_t is the line at the start, the slope its fall.
    g0 = int(round(FIT_GAP_S * rate))
    # the window: FIT_V of ramp (at least FIT_S), by a coarse slope over all the clean ramp
    # there is (a short window at a slow ramp is the solver's tolerance, not the ramp)
    a0 = start + g0
    s0 = (sense[a0] - sense[k - g0]) / max(k - g0 - a0, 1) * rate
    span = FIT_V / s0 if s0 > 0 else FIT_S
    lo = max(k - g0 - int(round(max(span, FIT_S) * rate)), a0)
    if k - g0 - lo < 8:
        raise RuntimeError("reset_event: too little clean ramp before the event to fit")
    idx = np.arange(lo, k - g0)
    b1, b0 = np.polyfit(idx - k, sense[idx], 1)
    v_t = float(b0 + b1 * frac)
    s = float(-b1 * rate)
    # The discharging network's conductance: the ramp's curvature over G_FIT_V of it before the
    # gap (S = -v' and G = c_f dS/dv = -c_f v'' / v'; Q7's Early effect: a few % over the ramp)
    span_g = G_FIT_V / s0 if s0 > 0 else FIT_S
    lo_g = max(k - g0 - int(round(span_g * rate)), a0)
    idx_g = np.arange(lo_g, k - g0)
    tt = (idx_g - k) / rate
    c2, c1, _ = np.polyfit(tt, sense[idx_g], 2)
    # at the window's end (the ramp's slope there is v' = c1 + 2 c2 t)
    v1 = c1 + 2.0 * c2 * float(tt[-1])
    g_s = max(-c_f * 2.0 * c2 / v1, 0.0) if v1 < 0 else 0.0
    t = np.arange(0, end - k) + frac
    pulse = np.interp(k + t, np.arange(len(i_ev)), i_ev)
    pre = float(i_ev[start : k + 1].sum() - (1.0 - frac) * i_ev[k]) / rate
    pulse[0] += pre * rate
    w = max(int(2e-6 * rate), 2)
    return dict(v_t=v_t, pulse=pulse, dead_s=(end - k - frac) / rate, slope=s, g_s=g_s,
                g_window_v=float(sense[lo_g] - sense[k - g0]),
                charge_c=float(pulse.sum() / rate), peak_a=float(pulse.max()),
                v_restart=float(sense[end:end + w].max()),
                onset_bump_v=float(sense[k] - (b0 + b1 * 0)))  # fmt: skip


def edge_event(v: dict, rate: float, direction: int) -> dict | None:
    """An edge of a reference run: `diff` (plus - minus) and `i_out`; the first zero crossing of
    diff in the direction (0: falling, the sink turning on; 1: rising) after the run's start,
    the output current from there (shifted by the fraction) until settled within
    EDGE_SETTLE_REL of its swing for END_HOLD_S."""
    d, i_out = v["diff"], v["i_out"]
    ks = (
        np.where((d[:-1] >= 0) & (d[1:] < 0))[0]
        if direction == 0
        else np.where((d[:-1] < 0) & (d[1:] >= 0))[0]
    )
    if not len(ks):
        return None
    k = int(ks[0])
    frac = d[k] / (d[k] - d[k + 1])
    hold = int(round(END_HOLD_S * rate))
    a = float(np.median(i_out[max(k - hold, 0) : k]))
    tail = i_out[k:]
    b = float(np.median(tail[-hold:]))
    swing = abs(b - a)
    near = np.abs(tail - b) < EDGE_SETTLE_REL * swing
    run = np.convolve(near.astype(int), np.ones(hold, int), "valid")
    first = np.where(run == hold)[0]
    if not len(first):
        return None
    end = k + int(first[0]) + hold
    t = np.arange(0, end - k) + frac
    wave = np.interp(k + t, np.arange(len(i_out)), i_out)
    wave[0] = a
    wave[-1] = b
    w = max(int(2e-6 * rate), 2)
    s = float(abs(d[k - w] - d[k]) / (w / rate)) if k >= w else float(abs(d[k] - d[k + 1]) * rate)
    return dict(wave=wave, slope=s, levels=(a, b))


# --- Fixtures for circuitsim's port (crates/circuitsim/tests/reset_events.rs) -----------------

FIXTURE_RESET, FIXTURE_EDGE = "minimoog_osc_reset", "minimoog_osc_edge"
FIXTURE_GAIN = 0.7  # an edge following the reset through a divider of its ramp


def reset_element(t: ResetTables, name: str, sense: str, src: str, dst: str):
    from varimu.circuit.ir import ResetEvents

    d = t.to_dict()
    return ResetEvents(
        name=name, sense=sense, src=src, dst=dst, c_f=float(t.c_f),
        ref_rate_hz=float(t.ref_rate_hz), log_slope=tuple(d["log_slope"]),
        v_t_v=tuple(d["v_t_v"]), dead_s=tuple(d["dead_s"]),
        pulses_a=tuple(tuple(p) for p in d["pulses_a"]), g_s=tuple(d["g_s"]), source="fixture",
    )  # fmt: skip


def edge_element(t: EdgeTables, name: str, plus: str, minus: str, src: str, dst: str,
                 follows: str | None = None, gain: float | None = None):  # fmt: skip
    from varimu.circuit.ir import EdgeEvents

    d = t.to_dict()
    return EdgeEvents(
        name=name, plus=plus, minus=minus, src=src, dst=dst, ref_rate_hz=float(t.ref_rate_hz),
        log_slope=tuple(d["log_slope"]),
        waves_a=tuple(tuple(tuple(w) for w in r) for r in d["waves_a"]),
        source="fixture", follows=follows, follow_gain=gain,
    )  # fmt: skip


def _fixture_run(rt: ResetTables, et: EdgeTables, h: float, slope: float, seconds: float) -> dict:
    """K on an emulated oscillator (a constant current out of C, the resets from the tables)
    with an edge following it (its input FIXTURE_GAIN of the ramp less half the swing, the
    threshold wobbling a little): the senses in and the currents out, per sample."""
    reset = ResetRun(rt, h)
    edge = EdgeRun(et, h, gain=FIXTURE_GAIN)
    i_c = slope * rt.c_f
    v = 4.8
    out: dict = {"h": h, "ramp": [], "reset_currents": [], "comp_currents": [], "diffs": [],
                 "edge_currents": []}  # fmt: skip
    for k in range(int(seconds / h)):
        i = reset.sense(v)
        diff = FIXTURE_GAIN * (v - 2.4) - 0.002 * math.sin(k / 9.0)
        j = edge.sense(diff, reset)
        out["ramp"].append(v)
        out["reset_currents"].append(i)
        out["comp_currents"].append(reset.i_comp)
        out["diffs"].append(diff)
        out["edge_currents"].append(j)
        v += (i - reset.i_comp - i_c) * h / rt.c_f
    out.update(resets=reset.events, reset_late=reset.late, edges=edge.events,
               edge_late=edge.late)  # fmt: skip
    return out


def fixtures() -> dict:
    """The Minimoog's tables as the IR's elements, an edge's step tables at 64 and 128
    reference samples a step, and runs of the reset with an edge following it on an emulated
    oscillator at 96 and 192 kHz."""
    from varimu.circuit.ir import _encode

    rt, et = load_tables(FIXTURE_RESET), load_tables(FIXTURE_EDGE)
    out: dict = {
        "reset": _encode(reset_element(rt, "XRESET", "ramp", "ref5", "d")),
        "edge": _encode(edge_element(et, "XRECT", "p", "m", "rc", "vn", "XRESET", FIXTURE_GAIN)),
        "edge_steps": {},
        "runs": [],
    }
    w = et.waves[0][10]
    a, b = float(w[0]), float(w[-1])
    for m in (64, 128):
        out["edge_steps"][str(m)] = {
            "shape": ((w - a) / (b - a)).tolist(),
            "steps": edge_step_table((w - a) / (b - a), minphase_lowpass(m), m).tolist(),
        }
    for h, slope, seconds in ((1 / 96000, 2200.0, 0.006), (1 / 96000, 21000.0, 0.002),
                              (1 / 192000, 9000.0, 0.003)):  # fmt: skip
        out["runs"].append(_fixture_run(rt, et, h, slope, seconds))
    return out


def fixtures_json() -> str:
    return json.dumps(fixtures(), allow_nan=False) + "\n"
