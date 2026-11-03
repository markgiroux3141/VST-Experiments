"""Event kernels for gas-tube strikes: technique K's Python reference
(HYBRID_PHYSICS_PLAN.md H3b; the design is the plan's "K's design").

The exception's **unit** is the tube with what it discharges: the capacitor C at its
anode, the series resistance R_s, the grid returned through R_g to a bias. Its tables are
generated from reference runs of the unit alone (circuitsim production at 3.072 MHz,
`unit_ir`): C charged by a near-constant current from a 10 kV source through a large
resistor (the ramp's slope S), the grid at V_g through R_g, oscillating for four strikes;
the last complete one is the table's (steady oscillation: the previous event's leftover
ions included). From each run (`strike_event`):

- V_s, the anode-to-cathode voltage at the strike (the anode current passing
  `I_STRIKE_A`, interpolated);
- the anode current's pulse from that moment to extinction;
- the dead time: from the strike until the plasma is back to its density before it.

At the audio rate fs the event is the pulse's charge, band-limited by a minimum-phase
low-pass `h` (causal: a solver in a coupled loop can't look ahead) and integrated over
each step: q_k = the integral over step k of (pulse * h)(t - phi / fs), for the strike at
fraction phi of its step. These are exactly the steps of the band-limited capacitor
voltage, so a circuit that integrates them (a current held over each step) carries the
band-limited event (`step_charges`). The tables hold them at `PHASES` + 1 offsets (one per
reference sample: 32 at 3.072 MHz over 96 kHz), linear in between.

At run time (`predict_crossing`, `Emulator`): before each step the margin m = V_ak -
V_s(V_g, S) at the last three samples, extrapolated quadratically, gives the strike's
offset in the step; the event's charges (the tables interpolated over V_g, log S and phi)
are injected over the next steps; no new strike for the dead time.

`Emulator` runs the unit itself at fs with K (the capacitor and its exact charging
between events, the events as their charges): the method's check against the unit's
reference before any engine work (`scripts/thyratron_kernels.py`).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import firwin, kaiserord

from varimu.circuit.ir import (
    Capacitor,
    CircuitIR,
    Device,
    Resistor,
    Section,
    VoltageProbe,
    VoltageSource,
)
from varimu.config import REPO_ROOT

FS = 96000
REF_OVERSAMPLE = 32
REF_RATE = REF_OVERSAMPLE * FS
PHASES = REF_OVERSAMPLE
# The strike: the anode current passing this. What the tube passed before it (the
# pre-conduction: ions lowering the grid's barrier as the strike nears, ~0.2-0.7% of the
# event's charge) goes into the event's first sample (`strike_event`): modelled as a
# current between events, its exponential knee bent the ramp, the margin's extrapolation
# missed by fractions of a sample and the strikes aliased at -50 to -65 dB.
I_STRIKE_A = 1e-3
# The extinction: the anode current below this fraction of its peak.
EXTINCT_REL = 1e-4
# The charging source: 10 kV by default, so the current is constant within ~1% over a 100 V
# ramp (a pentode's constant current); a unit can have its instrument's (Unit.v_charge_v).
V_CHARGE = 10e3
# The ramp's slope S, a table's axis, is its slope at this voltage (about the strike: K
# measures S just before it).
V_SLOPE_REF = 40.0
CACHE = REPO_ROOT / "cache" / "hybrid" / "k"


@dataclass(frozen=True)
class Unit:
    """What the tube discharges: its anode capacitor, series resistance and grid return. The
    grid's return is the impedance the arc and the ramp see, to a bias held steady: RCA's R3
    (2.5k), C1 (0.25 uF) a short at those speeds (14 mV per event); its 49.5k DC path only
    sets the bias. (The grid's charge per event depends on it: a grid held low collects more
    ions. In RCA's circuit that charge into C1 is a standing grid-leak lift of ~0.8 V, ~8 V of
    strike: H3d.)"""

    device: str = "884@1"
    c_f: float = 5e-9
    r_s_ohm: float = 450.0
    r_g_ohm: float = 2.5e3
    # The charger: a source this far above the cathode through the resistor that gives the
    # slope (the instrument's Thevenin equivalent; the default is a constant current).
    v_charge_v: float = V_CHARGE


# --- The band-limiting kernel ------------------------------------------------------------


def minphase_lowpass(oversample: int = REF_OVERSAMPLE, atten_db: float = 100.0) -> np.ndarray:
    """A minimum-phase low-pass at oversample x fs: the passband to 0.25 fs, the stopband from
    0.75 fs (what folds into the passband at fs), `atten_db` down; taps sum to 1. Designed
    linear-phase (Kaiser, 3 dB of margin) and made minimum-phase by the real cepstrum (the
    same magnitude, causal, its energy at the start)."""
    rate = float(oversample)
    n, beta = kaiserord(atten_db + 3.0, 0.5 / (rate / 2))
    h = firwin(n | 1, 0.5, window=("kaiser", beta), fs=rate)
    nfft = 1 << int(np.ceil(np.log2(len(h) * 32)))
    mag = np.abs(np.fft.fft(h, nfft))
    c = np.fft.ifft(np.log(np.maximum(mag, 1e-12))).real
    fold = np.zeros(nfft)
    fold[0] = c[0]
    fold[1 : nfft // 2] = 2.0 * c[1 : nfft // 2]
    fold[nfft // 2] = c[nfft // 2]
    hm = np.fft.ifft(np.exp(np.fft.fft(fold))).real[: len(h)]
    return hm / hm.sum()


def step_charges(
    pulse_a: np.ndarray,
    h: np.ndarray,
    oversample: int = REF_OVERSAMPLE,
    ref_rate_hz: float = REF_RATE,
) -> np.ndarray:
    """The pulse (amperes at the reference rate, from the strike) band-limited by h (at the
    same rate) and integrated over each step of `oversample` reference samples, at every
    offset j / oversample of a step (j = 0 .. oversample): array (oversample + 1, steps),
    coulombs. Each row sums to the pulse's charge."""
    g = np.convolve(pulse_a, h) / ref_rate_hz
    steps = int(np.ceil((len(g) + oversample) / oversample))
    out = np.zeros((oversample + 1, steps))
    for j in range(oversample + 1):
        buf = np.zeros(steps * oversample)
        buf[j : j + len(g)] = g
        out[j] = buf.reshape(steps, oversample).sum(axis=1)
    return out


# --- The unit's reference runs -----------------------------------------------------------


def unit_ir(
    unit: Unit, v_g: float, slope_v_s: float, oscillate: bool = False, k: Tables | None = None
) -> CircuitIR:
    """The unit alone: C (out to ground) charged from 10 kV through R_ch at `slope_v_s`
    (V/s, at the ramp's middle), discharged through R_s by the tube (cathode grounded), its
    grid at v_g through R_g. Starts discharged with the plasma off (held for the DC point, as
    in rca_884_sweep.yaml); `oscillate`: the same, run for many cycles. With `k` (a unit's
    tables) the tube is technique K's element instead (H3c)."""
    from varimu.devices.library import load_device

    r_ch = (unit.v_charge_v - V_SLOPE_REF) / (unit.c_f * slope_v_s)
    model = dataclasses.replace(load_device(unit.device), name="TUBE")
    tube = Device("XV", "TUBE", ("a", "g", "w", "0"))
    if k is not None:
        tube = element(k, "XV", "a", "g", "w", "0")
    els = (
        VoltageSource("VH", "hv", "0", unit.v_charge_v),
        Resistor("RCH", "hv", "out", r_ch),
        Capacitor("C", "out", "0", unit.c_f, 0.0),
        Resistor("RS", "out", "a", unit.r_s_ohm),
        tube,
        Capacitor("CW", "w", "0", 1.0, -25.0),
        VoltageSource("VG", "gb", "0", v_g),
        Resistor("RG", "gb", "g", unit.r_g_ohm),
        Resistor("RIN", "in", "0", 1e3),
    )
    return CircuitIR(
        title=f"thyratron unit ({'oscillating' if oscillate else 'one strike'})",
        input_node="in",
        probes=tuple(VoltageProbe(n) for n in ("out", "a", "g", "w")),
        models=() if k is not None else (model,),
        sections=(Section("unit", els),),
    )


def run_unit(unit: Unit, v_g: float, slope_v_s: float, seconds: float, oscillate=False) -> dict:
    """The unit at the reference rate (production's method, error control): its probes, the
    tube's own currents, the model's at the run's voltages (`ia`, the anode's, for the
    strike and the extinction; `ig`, the grid's less its leakage: the K circuit has the
    capacitances and the leakage itself), and `iq`, what left the capacitor over each
    sample (its charge lost less the charger's, per sample's time): the pulse's charge.
    The arc's peak (~0.25 A rising in ~0.5 us, a sample and a half) is sharper than the
    samples, so a sum of `ia` at them missed or overcounted up to ~1% of a strike's charge,
    by where the peak fell (the voice's tables: +-12 cents)."""
    from varimu.devices.library import load_device
    from varimu.devices.thyratron import W_MAX, W_MIN
    from varimu.sim import fast, io

    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="production"),
        sample_rate=REF_RATE,
        oversample=1,
        full_scale_volts_peak=1.0,
        settle_s=0.0,
    )
    ir = unit_ir(unit, v_g, slope_v_s, oscillate)
    res = fast.run_transient(ir, np.zeros(int(seconds * REF_RATE)), settings=st)
    v = {p: np.asarray(res.vectors[f"v({p})"]) for p in ("out", "a", "g", "w")}
    m = load_device(unit.device)
    x = np.exp(np.clip(v["w"], W_MIN, W_MAX))
    v["ia"] = m.anode_a(v["a"], 0.0, v["g"], x)
    v["ig"] = m.grid1_a(v["a"], v["g"], x) - m.g_leak_s * (v["g"] - v["a"])
    r_ch = (unit.v_charge_v - V_SLOPE_REF) / (unit.c_f * slope_v_s)
    out = v["out"]
    i_ch = (unit.v_charge_v - 0.5 * (out[:-1] + out[1:])) / r_ch
    v["iq"] = np.append(unit.c_f * (out[:-1] - out[1:]) * REF_RATE + i_ch, 0.0)
    v["wall_s"] = res.wall_s
    return v


def _extinction(ia: np.ndarray, k: int) -> int | None:
    """The sample where the event struck at k is out: the anode current below EXTINCT_REL of
    its peak so far for 3 us on end (the arc's tail below 1% still carried ~1% of the
    charge: 15-45 cents); None: it never goes out (latched) within the run."""
    seg = ia[k:]
    low = seg < EXTINCT_REL * np.maximum.accumulate(seg)
    hold = int(3e-6 * REF_RATE)
    run = np.convolve(low.astype(int), np.ones(hold, int), "valid")
    first = np.where(run == hold)[0]
    return k + int(first[0]) if len(first) else None


def strike_event(v: dict, steady: bool = False) -> dict | None:
    """A strike of a reference run: the first, or (`steady`) the last one that completes,
    after at least two before it (in steady oscillation: the previous event's leftover ions
    lower the strike; first strikes after a long ramp ran 2-12 cents flat at 4 kHz). Gives
    V_s, the pulse from the strike (shifted by the fraction to start exactly there) with what
    the tube passed on the ramp before it (since the previous extinction, or the run's start)
    in its first sample, the grid's pulse over the same samples (the current into the grid
    pin, its own before the strike in the first), the charges, the event's length (to
    extinction) and the dead time (until the plasma is back to its density 1 us before the
    strike). A strike whose arc never goes out (the charging current holds it: latched)
    gives only V_s and `latched`."""
    ia, ig, out, w = v["ia"], v["ig"], v["out"], v["w"]
    ks = np.where((ia[:-1] < I_STRIKE_A) & (ia[1:] >= I_STRIKE_A))[0]
    if not len(ks):
        return None
    ends = [_extinction(ia, int(k)) for k in ks]
    if ends[0] is None:
        k = int(ks[0])
        return dict(v_s=float(out[k]), latched=True)
    if steady:
        done = [i for i in range(2, len(ks)) if ends[i] is not None]
        if not done:
            raise RuntimeError("steady: fewer than three complete strikes in the run")
        # the last whose plasma is seen back to its density before the strike within the
        # run (its dead time; a strike near the run's end has none yet)
        for i in reversed(done):
            k0 = int(ks[i])
            pk0 = k0 + int(np.argmax(ia[k0 : ends[i]]))
            if (w[pk0:] <= float(w[max(k0 - REF_RATE // 1_000_000, 0)])).any():
                break
        start = ends[i - 1]
    else:
        i, start = 0, 0
    k, end = int(ks[i]), ends[i]
    frac = (I_STRIKE_A - ia[k]) / (ia[k + 1] - ia[k])
    v_s = float(out[k] + frac * (out[k + 1] - out[k]))
    pk = k + int(np.argmax(ia[k:end]))
    t = np.arange(0, end - k) + frac
    # the charge per sample from the capacitor (`run_unit`'s iq: per interval, from the
    # strike's point within its first)
    iq = v["iq"]
    pulse = np.interp(k + t, np.arange(len(iq)), iq)
    pre_c = float(iq[start : k + 1].sum() - (1.0 - frac) * iq[k]) / REF_RATE
    pulse[0] += pre_c * REF_RATE
    gpulse = np.interp(k + t, np.arange(len(ig)), ig)
    pre_g = float(ig[start : k + 1].sum() - (1.0 - frac) * ig[k]) / REF_RATE
    gpulse[0] += pre_g * REF_RATE
    w_pre = float(w[max(k - REF_RATE // 1_000_000, 0)])
    back = np.where(w[pk:] <= w_pre)[0]
    dead = (pk + int(back[0]) - k - frac) / REF_RATE if len(back) else np.nan
    return dict(
        v_s=v_s,
        latched=False,
        pulse=pulse,
        grid_pulse=gpulse,
        charge_c=float(pulse.sum() / REF_RATE),
        pre_charge_c=pre_c,
        grid_charge_c=float(gpulse.sum() / REF_RATE),
        event_s=(end - k - frac) / REF_RATE,
        dead_s=float(dead),
        peak_a=float(ia[pk]),
        v_low=float(out[end - 1]),
    )


# --- Tables -----------------------------------------------------------------------------


@dataclass
class Tables:
    """A unit's K tables over (v_g, log slope), both ascending: V_s, the dead time, the
    latched points, and each point's pulse (the anode current at the reference rate from
    the strike, empty where latched), indexed [v_g][slope]; their source. The step charges
    for an engine's step are derived (`charges`)."""

    unit: Unit
    v_g: np.ndarray
    log_slope: np.ndarray
    v_s: np.ndarray
    dead_s: np.ndarray
    latched: np.ndarray
    pulses: list[list[np.ndarray]]
    grid_pulses: list[list[np.ndarray]]
    source: dict
    ref_rate_hz: float = REF_RATE

    def __post_init__(self):
        self._charges: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        self._centroids: np.ndarray | None = None

    def centroids(self) -> np.ndarray:
        """Each point's pulse centroid (v_g, slope), in reference samples from the strike (0
        where latched)."""
        if self._centroids is None:
            c = np.zeros(self.v_s.shape)
            for i, row in enumerate(self.pulses):
                for j, p in enumerate(row):
                    if len(p):
                        num, den = 0.0, 0.0
                        for n, x in enumerate(p):
                            num = num + n * float(x)
                            den = den + float(x)
                        c[i, j] = num / den
            self._centroids = c
        return self._centroids

    def charges(self, oversample: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The step charges (v_g, slope, phase, step) for a step of `oversample` reference
        samples (zeros where latched): the anode's band-limited and raw, the grid's
        band-limited; cached."""
        if oversample not in self._charges:
            h = minphase_lowpass(oversample)
            rate = self.ref_rate_hz
            pts = [[(step_charges(p, h, oversample, rate),
                     step_charges(p, np.ones(1), oversample, rate),
                     step_charges(g, h, oversample, rate))
                    if len(p) else None for p, g in zip(row, grow, strict=True)]
                   for row, grow in zip(self.pulses, self.grid_pulses, strict=True)]  # fmt: skip
            steps = max(a.shape[1] for row in pts for pr in row if pr for a in pr)
            q = np.zeros((len(self.v_g), len(self.log_slope), oversample + 1, steps))
            q_raw, q_grid = np.zeros_like(q), np.zeros_like(q)
            for i, row in enumerate(pts):
                for j, pr in enumerate(row):
                    if pr:
                        for dst, src in zip((q, q_raw, q_grid), pr, strict=True):
                            dst[i, j, :, : src.shape[1]] = src
            self._charges[oversample] = (q, q_raw, q_grid)
        return self._charges[oversample]

    def to_dict(self) -> dict:
        return {
            "unit": dataclasses.asdict(self.unit),
            "ref_rate_hz": float(self.ref_rate_hz),
            "v_g_v": [float(x) for x in self.v_g],
            "log_slope": [float(x) for x in self.log_slope],
            "v_s_v": self.v_s.tolist(),
            "dead_s": self.dead_s.tolist(),
            "latched": self.latched.tolist(),
            "pulses_a": [[[float(x) for x in p] for p in row] for row in self.pulses],
            "grid_pulses_a": [[[float(x) for x in p] for p in row] for row in self.grid_pulses],
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Tables:
        return cls(
            unit=Unit(**d["unit"]),
            v_g=np.array(d["v_g_v"], float),
            log_slope=np.array(d["log_slope"], float),
            v_s=np.array(d["v_s_v"], float),
            dead_s=np.array(d["dead_s"], float),
            latched=np.array(d["latched"], bool),
            pulses=[[np.array(p, float) for p in row] for row in d["pulses_a"]],
            grid_pulses=[[np.array(p, float) for p in row] for row in d["grid_pulses_a"]],
            source=d["source"],
            ref_rate_hz=d["ref_rate_hz"],
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), allow_nan=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> Tables:
        return cls.from_dict(json.loads(path.read_text()))


def source_label(name: str, t: Tables) -> str:
    """A ThyratronEvents' source: its tables' name and reference key."""
    return f"config/events/{name}.json, reference {t.source.get('key', '?')}"


def element(
    t: Tables, name: str, a: str, g: str, w: str, k: str, model=None, source: str | None = None
):
    """The tables as the IR's ThyratronEvents on the device's pins (a, g, w, k), with the
    off tube of `model` (default: the unit's device): its capacitances and grid leakage."""
    from varimu.circuit.ir import ThyratronEvents
    from varimu.devices.library import load_device

    m = model if model is not None else load_device(t.unit.device)
    d = t.to_dict()
    return ThyratronEvents(
        name=name, a=a, g=g, w=w, k=k,
        c_gk_f=m.c_gk, c_ga_f=m.c_ga, c_ak_f=m.c_ak, g_leak_s=m.g_leak_s,
        c_f=t.unit.c_f, r_s_ohm=t.unit.r_s_ohm, r_g_ohm=t.unit.r_g_ohm,
        ref_rate_hz=float(t.ref_rate_hz),
        v_g_v=tuple(d["v_g_v"]), log_slope=tuple(d["log_slope"]),
        v_s_v=tuple(tuple(r) for r in d["v_s_v"]),
        dead_s=tuple(tuple(r) for r in d["dead_s"]),
        latched=tuple(tuple(bool(x) for x in r) for r in d["latched"]),
        pulses_a=tuple(tuple(tuple(p) for p in row) for row in d["pulses_a"]),
        grid_pulses_a=tuple(tuple(tuple(p) for p in row) for row in d["grid_pulses_a"]),
        source=source if source is not None else f"reference {t.source.get('key', '?')}",
    )  # fmt: skip


def tables_of(el) -> Tables:
    """An IR ThyratronEvents' tables (the unit's device unknown there: '?')."""
    return Tables(
        unit=Unit(device="?", c_f=el.c_f, r_s_ohm=el.r_s_ohm, r_g_ohm=el.r_g_ohm),
        v_g=np.array(el.v_g_v, float),
        log_slope=np.array(el.log_slope, float),
        v_s=np.array(el.v_s_v, float),
        dead_s=np.array(el.dead_s, float),
        latched=np.array(el.latched, bool),
        pulses=[[np.array(p, float) for p in row] for row in el.pulses_a],
        grid_pulses=[[np.array(p, float) for p in row] for row in el.grid_pulses_a],
        source={},
        ref_rate_hz=el.ref_rate_hz,
    )


def _reference_code() -> str:
    """The source the tables depend on: the unit, its runs, the strike's extraction."""
    import inspect

    fns = (unit_ir, run_unit, _extinction, strike_event, _one)
    consts = (REF_RATE, I_STRIKE_A, EXTINCT_REL, V_SLOPE_REF)
    return "".join(inspect.getsource(f) for f in fns) + repr(consts)


def engine_hash() -> str:
    """circuitsim's sources less the event kernels' (events.rs): what a reference run
    without them depends on. (The installed build is checked against the tree on every
    run: varimu.sim.fast.check_build.)"""
    crate = REPO_ROOT / "crates" / "circuitsim"
    files = [REPO_ROOT / "Cargo.toml", crate / "Cargo.toml", crate / "build.rs"]
    files += sorted(f for f in (crate / "src").rglob("*.rs") if f.name != "events.rs")
    h = hashlib.sha256()
    for f in files:
        if f.exists():
            h.update(f.relative_to(REPO_ROOT).as_posix().encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def tables_key(unit: Unit, v_g: np.ndarray, slopes: np.ndarray) -> str:
    """The reference's identity: the unit, the grid, the component file, the code (the
    engine without the event kernels, which the reference runs don't use)."""
    from varimu.devices import versions

    h = hashlib.sha256()
    h.update(json.dumps(dataclasses.asdict(unit), sort_keys=True).encode())
    h.update(np.asarray(v_g, float).tobytes() + np.asarray(slopes, float).tobytes())
    h.update(versions.path(unit.device).read_bytes())
    h.update(engine_hash().encode())
    h.update(_reference_code().encode())
    return h.hexdigest()[:16]


def _one(args):
    unit, vg, s = args
    # the first strike by ~V / S, then three cycles of at most that (the 884 strikes ~10.7 V
    # per volt of grid: a margin over it)
    seconds = 4 * (15.0 * abs(vg) + 20.0) / s + 2e-3
    v = run_unit(unit, vg, s, seconds, oscillate=True)
    e = strike_event(v, steady=True)
    if e is None:
        raise RuntimeError(f"no strike at v_g {vg} V, slope {s:g} V/s within {seconds} s")
    e["wall_s"] = v["wall_s"]
    return e


def build_tables(unit: Unit, v_g, slopes, workers: int = 7) -> Tables:
    """The unit's tables from a reference run per grid point (cached by `tables_key`)."""
    from concurrent.futures import ProcessPoolExecutor

    # both axes ascending (`lookup` interpolates by searchsorted)
    v_g, slopes = np.sort(np.asarray(v_g, float)), np.sort(np.asarray(slopes, float))
    key = tables_key(unit, v_g, slopes)
    path = CACHE / f"{key}.json"
    if path.exists():
        return Tables.load(path)
    grid = [(unit, vg, s) for vg in v_g for s in slopes]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        evs = list(ex.map(_one, grid))
    shape = (len(v_g), len(slopes))
    import circuitsim

    def at(i, j):
        return evs[i * shape[1] + j]

    t = Tables(
        unit=unit,
        v_g=v_g,
        log_slope=np.log(slopes),
        v_s=np.array([e["v_s"] for e in evs]).reshape(shape),
        # a latched point has no event (the arc never goes out): no pulse, no dead time
        dead_s=np.array([0.0 if e["latched"] else e["dead_s"] for e in evs]).reshape(shape),
        latched=np.array([e["latched"] for e in evs]).reshape(shape),
        pulses=[
            [np.zeros(0) if at(i, j)["latched"] else at(i, j)["pulse"] for j in range(shape[1])]
            for i in range(shape[0])
        ],
        grid_pulses=[
            [
                np.zeros(0) if at(i, j)["latched"] else at(i, j)["grid_pulse"]
                for j in range(shape[1])
            ]
            for i in range(shape[0])
        ],  # fmt: skip
        source={
            "reference": "circuitsim production (esdirk4, error control), 3.072 MHz, oversample 1",
            "device": unit.device,
            "circuitsim": circuitsim.SOURCE_HASH,
            "key": key,
            "events": [
                {k: v for k, v in e.items() if k not in ("pulse", "grid_pulse")} for e in evs
            ],  # fmt: skip
        },
    )
    t.save(path)
    return t


# --- Run time ----------------------------------------------------------------------------
# circuitsim's events.rs is the port: the same arithmetic in the same order.


def predict_crossing(m: tuple[float, float, float]) -> float | None:
    """The margin at the last three samples (m[2] now): the first zero of the quadratic
    through them in the next step, as a fraction of it (0, 1]; None if there is none. A
    margin already >= 0 (a crossing the extrapolation missed) starts at once: 0."""
    m0, m1, m2 = m
    if m2 >= 0.0:
        return 0.0
    # m(x) = m2 + b x + a x^2 through (-2, m0), (-1, m1), (0, m2)
    a = 0.5 * (m0 - 2.0 * m1 + m2)
    b = 0.5 * (m0 - 4.0 * m1 + 3.0 * m2)
    if abs(a) <= 1e-12 * (abs(b) + abs(m2)):
        roots = [-m2 / b] if b != 0.0 else []
    else:
        disc = b * b - 4.0 * a * m2
        if disc < 0.0:
            return None
        r = math.sqrt(disc)
        # the numerically stable pair
        qq = -0.5 * (b + math.copysign(r, b))
        roots = [qq / a, m2 / qq] if qq != 0.0 else []
    xs = [x for x in roots if 0.0 < x <= 1.0]
    return float(min(xs)) if xs else None


def _ix(grid: np.ndarray, x: float) -> tuple[int, float]:
    """The cell of an ascending grid holding x (clamped to it) and x's fraction in it."""
    x = min(max(x, float(grid[0])), float(grid[-1]))
    i = min(int(np.searchsorted(grid, x, side="right")) - 1, len(grid) - 2)
    return i, (x - float(grid[i])) / (float(grid[i + 1]) - float(grid[i]))


@dataclass
class Lookup:
    """The tables at one condition: V_s, the dead time, the charges (phase, step), or
    latched (the arc holds: no event)."""

    v_s: float
    dead_s: float
    latched: bool
    q: np.ndarray | None
    q_raw: np.ndarray | None
    q_grid: np.ndarray | None = None
    centroid: float = 0.0  # the pulse's, reference samples from the strike


@dataclass
class Corners:
    """A condition's four corners on the grid (point, weight), V_s over them, and the
    weights of the latched corners and of the others."""

    points: tuple[tuple[int, int, float], ...]
    v_s: float
    w_latched: float
    w_live: float

    @property
    def latched(self) -> bool:
        return self.w_latched >= 0.5


def corners(t: Tables, v_g: float, slope_v_s: float) -> Corners:
    """The condition on the grid: bilinear in (v_g, log slope), clamped to it, and V_s
    there (`lookup`'s first half: what the margin needs every sample)."""
    (i, a), (j, b) = _ix(t.v_g, v_g), _ix(t.log_slope, math.log(max(slope_v_s, 1e-30)))
    pts = ((i, j, (1.0 - a) * (1.0 - b)), (i + 1, j, a * (1.0 - b)),
           (i, j + 1, (1.0 - a) * b), (i + 1, j + 1, a * b))  # fmt: skip
    v_s = 0.0
    w_latched = 0.0
    w_live = 0.0
    for p, s, w in pts:
        v_s = v_s + w * float(t.v_s[p, s])
        if t.latched[p, s]:
            w_latched = w_latched + w
        else:
            w_live = w_live + w
    return Corners(pts, v_s, w_latched, w_live)


def lookup(
    t: Tables, oversample: int, v_g: float, slope_v_s: float, c: Corners | None = None
) -> Lookup:
    """Bilinear in (v_g, log slope), clamped to the grid. V_s over the four corners; the
    charges and the dead time over the corners not latched, their weights renormalized;
    latched when the latched corners weigh half or more. `c`: the condition's `corners`,
    if they're known."""
    c = c if c is not None else corners(t, v_g, slope_v_s)
    if c.latched:
        return Lookup(c.v_s, 0.0, True, None, None)
    q_all, raw_all, grid_all = t.charges(oversample)
    cent = t.centroids()
    dead, centroid = 0.0, 0.0
    q = np.zeros(q_all.shape[2:])
    q_raw = np.zeros(q_all.shape[2:])
    q_grid = np.zeros(q_all.shape[2:])
    for p, s, w in c.points:
        if t.latched[p, s]:
            continue
        if c.w_latched > 0.0:
            w = w / c.w_live
        dead = dead + w * float(t.dead_s[p, s])
        centroid = centroid + w * float(cent[p, s])
        q = q + w * q_all[p, s]
        q_raw = q_raw + w * raw_all[p, s]
        q_grid = q_grid + w * grid_all[p, s]
    return Lookup(c.v_s, dead, False, q, q_raw, q_grid, centroid)


def phase_row(q: np.ndarray, j: int, m: int) -> np.ndarray:
    """Row j (-1 .. m + 1) of an (m + 1, steps) charge table: beyond the ends, the end rows a
    whole step on (row -1 is row m - 1 a step earlier, its first two steps merged; row m + 1
    is row 1 a step later, its last two merged), the charge kept."""
    if j < 0:
        r = q[m - 1]
        return np.concatenate([[float(r[0]) + float(r[1])], r[2:], [0.0]])
    if j > m:
        r = q[1]
        return np.concatenate([[0.0], r[:-2], [float(r[-2]) + float(r[-1])]])
    return q[j]


def cubic_phase(q: np.ndarray, j0: int, a: float, m: int) -> np.ndarray:
    """The charges at phase row j0 + a (0 <= a < 1): Lagrange through rows j0 - 1 .. j0 + 2
    (the weights sum to 1: the charge is kept). Linear between the 33 rows left the strike's
    phase drifting over the sample grid as a sideband at -67 dB (6 kHz, short pulses)."""
    w = (-a * (a - 1.0) * (a - 2.0) / 6.0, (a + 1.0) * (a - 1.0) * (a - 2.0) / 2.0,
         -(a + 1.0) * a * (a - 2.0) / 2.0, (a + 1.0) * a * (a - 1.0) / 6.0)  # fmt: skip
    out = w[0] * phase_row(q, j0 - 1, m)
    out = out + w[1] * phase_row(q, j0, m)
    out = out + w[2] * phase_row(q, j0 + 1, m)
    return out + w[3] * phase_row(q, j0 + 2, m)


class Events:
    """K's run time on one unit (circuitsim's events.rs is its port): given the senses
    after each sample (v_ak, v_gk), the currents held over the next step: a -> k (the
    return value), into the grid, g -> k (`i_grid`), and the charging network's deficit from
    ground into the anode (`i_comp`, `_deficit`).

    The unit's capacitor is v_ak plus R_s times the current held over the step just ended;
    the physical voltage adds what the band-limiting hasn't yet passed on (the filtered
    charges so far less the raw, over C), so the margin and the slope see the ramp, not
    the kernel's ringing. The grid's coordinate is v_gk less R_g C_ga S (the off tube's
    coupling into the unit's grid return, which the tables' bias axis already holds).
    Before each step, from the third sample on and once the dead time has passed: the
    slope S from the last two physical voltages (no strike on a falling ramp), the tables
    at (v_g, S), the margin's zero within the step (`predict_crossing`); a strike there
    adds its charges at that phase to the pending ones (and the charging network's deficit:
    `_deficit`) and starts the dead time. A latched
    condition plays no event (K doesn't play the held arc: the ramp runs on), counted once
    per crossing."""

    def __init__(self, t: Tables, h: float, c_ga_f: float = 0.0):
        self.t, self.h = t, h
        m = t.ref_rate_hz * h
        self.m = round(m)
        if self.m < 1 or abs(m - self.m) > 1e-9 * self.m:
            raise ValueError(f"the step {h} s isn't a whole number of reference samples")
        q = t.charges(self.m)[0]
        self.c_ga_f = c_ga_f
        n = q.shape[-1] + 2
        self.pending, self.pending_raw = np.zeros(n), np.zeros(n)
        self.pending_grid = np.zeros(n)
        self.pending_comp = np.zeros(n)
        self.i_grid = 0.0
        self.i_comp = 0.0
        self.hist = [0.0, 0.0, 0.0]
        self.n = 0
        self.i_held = 0.0
        self.lag = 0.0
        self.busy_until = 0.0  # in samples
        self.in_latch = False
        self.events = self.late = self.latched = 0

    def _deficit(self, qq: np.ndarray, phi: float, centroid: float) -> np.ndarray:
        """What the charging network doesn't deliver because of the kernel's delay, as
        charges per step to deliver instead (from ground into the anode): the band-limited
        capacitor sits above the physical one for ~2 samples after each strike, so a charging
        network whose current falls with the capacitor's voltage (a resistor from the supply:
        conductance G) delivers less meanwhile than it would have, G (v - v_phys) summed over
        the event, and the next strike comes late (RCA's sweep: -11 cents at C6, ~d / RC). G
        is measured from the ramp's curvature (G = -C dS/dv over the last three samples, none
        below 0); the charge is delivered in the event's band-limited shape (no aliasing of
        its own). It comes from the network's side, not off the tube's charge: the tube's
        current still reaches the cathode whole (a self-biased cathode, RCA's, sits on the
        tube's average current: taken off the tube's, the cathode sat 13 mV low there, ~+9
        cents through the control ratio). The lag is the band-limited charges' centroid (held
        over each step) less the pulse's own (the strike's phase plus the pulse's centroid,
        less the half step a held current adds on average): the raw step charges' centroid
        jumps with the phase by up to half a step, and the deficit with it (-55 dB of
        sidebands at 6 kHz)."""
        h0, h1, h2 = self.hist
        c, h = self.t.unit.c_f, self.h
        g = 0.0
        if h2 > h0:
            g = max(-c * 2.0 * (h2 - 2.0 * h1 + h0) / (h * (h2 - h0)), 0.0)
        m = self.m
        kq, total = 0.0, 0.0
        for k in range(len(qq)):
            kq = kq + k * float(qq[k])
            total = total + float(qq[k])
        if g == 0.0 or total <= 0.0:
            return np.zeros(len(qq))
        acc = kq - total * (phi + centroid / m - (m - 1) / (2 * m))
        return qq * (g * h / c * acc / total)

    def sense(self, v_ak: float, v_gk: float) -> float:
        """Sample n's senses; the current held over the step to n + 1."""
        u, h, m = self.t.unit, self.h, self.m
        v_phys = v_ak + u.r_s_ohm * (self.i_held - self.i_comp) + self.lag / u.c_f
        self.hist = [self.hist[1], self.hist[2], v_phys]
        n = self.n
        fired = False
        if n >= 2 and n >= self.busy_until:
            s = (self.hist[2] - self.hist[1]) / h
            if s > 0.0:
                vg = v_gk - u.r_g_ohm * self.c_ga_f * s
                c = corners(self.t, vg, s)
                phi = predict_crossing((self.hist[0] - c.v_s, self.hist[1] - c.v_s,
                                        self.hist[2] - c.v_s))  # fmt: skip
                if phi is not None and phi > 0.0:
                    # the slope at the crossing, from the same quadratic (the last interval's
                    # sits up to a step before it, by the phase: on a curved ramp V_s(S)
                    # moved with it, ~1e-5 of the period of jitter, -60 dB sidebands at 6 kHz)
                    h0, h1, h2 = self.hist
                    qa = 0.5 * (h0 - 2.0 * h1 + h2)
                    qb = 0.5 * (h0 - 4.0 * h1 + 3.0 * h2)
                    s2 = (qb + 2.0 * qa * phi) / h
                    if s2 > 0.0:
                        vg2 = v_gk - u.r_g_ohm * self.c_ga_f * s2
                        c2 = corners(self.t, vg2, s2)
                        phi2 = predict_crossing((h0 - c2.v_s, h1 - c2.v_s, h2 - c2.v_s))
                        if phi2 is not None:
                            c, phi = c2, phi2
                if phi is not None:
                    fired = True
                    if c.latched:
                        if not self.in_latch:
                            self.latched += 1
                        self.in_latch = True
                    else:
                        lk = lookup(self.t, m, vg, s, c)
                        self.in_latch = False
                        self.events += 1
                        self.late += phi == 0.0
                        j = phi * m
                        j0 = min(int(j), m - 1)
                        a = j - j0
                        qq = cubic_phase(lk.q, j0, a, m)
                        rr = (1.0 - a) * lk.q_raw[j0] + a * lk.q_raw[j0 + 1]
                        gg = cubic_phase(lk.q_grid, j0, a, m)
                        cc = self._deficit(qq, phi, lk.centroid)
                        self.pending[: len(qq)] += qq
                        self.pending_comp[: len(cc)] += cc
                        self.pending_raw[: len(rr)] += rr
                        self.pending_grid[: len(gg)] += gg
                        self.busy_until = n + phi + lk.dead_s / h
        if not fired:
            self.in_latch = False
        self.i_held = float(self.pending[0]) / h
        self.i_grid = float(self.pending_grid[0]) / h
        self.i_comp = float(self.pending_comp[0]) / h
        self.lag = self.lag + (float(self.pending[0]) - float(self.pending_raw[0]))
        for v in (self.pending, self.pending_raw, self.pending_grid, self.pending_comp):
            v[:-1] = v[1:].copy()
            v[-1] = 0.0
        self.n = n + 1
        return self.i_held


class Emulator:
    """The unit at fs with K: C charged from 10 kV through R_ch (exact between samples for a
    current held over each step), the strikes from `Events` (the grid at the bias). Its
    output is C's voltage at each sample."""

    def __init__(self, t: Tables, v_g: float, slope_v_s: float, fs: float = FS):
        self.t, self.v_g = t, v_g
        u = t.unit
        self.r_ch = (u.v_charge_v - V_SLOPE_REF) / (u.c_f * slope_v_s)
        self.tau = self.r_ch * u.c_f
        self.h = 1.0 / fs
        self.ev = Events(t, self.h)

    @property
    def events(self) -> int:
        return self.ev.events

    @property
    def late(self) -> int:
        return self.ev.late

    def run(self, n: int) -> np.ndarray:
        u = self.t.unit
        decay = np.exp(-self.h / self.tau)
        v = np.zeros(n)
        for k in range(n - 1):
            # the capacitor as the circuit's a-k sense sees it: through R_s carrying the
            # tube's current less the deficit's
            i_ev = self.ev.sense(v[k] - u.r_s_ohm * (self.ev.i_held - self.ev.i_comp), self.v_g)
            v_inf = u.v_charge_v - self.r_ch * (i_ev - self.ev.i_comp)
            v[k + 1] = v_inf + (v[k] - v_inf) * decay
        return v


# --- Fixtures for circuitsim's port (crates/circuitsim/tests/events.rs) ------------------


def _fixture_tables() -> Tables:
    """A synthetic unit: a 3 x 3 grid with distinct pulses (an arc's rise and exponential
    tail, length and charge varying with the condition) and one latched corner."""
    v_g = np.array([-8.0, -6.0, -4.0])
    log_s = np.log([3e3, 3e4, 3e5])
    v_s = np.array([[80.0, 82.0, 85.0], [55.0, 57.0, 60.0], [30.0, 33.0, 37.0]])
    dead = np.array([[30e-6, 28e-6, 26e-6], [32e-6, 29e-6, 27e-6], [35e-6, 31e-6, 0.0]])
    latched = np.zeros((3, 3), bool)
    latched[2, 2] = True
    pulses, grid_pulses = [], []
    for i in range(3):
        row, grow = [], []
        for j in range(3):
            if latched[i, j]:
                row.append(np.zeros(0))
                grow.append(np.zeros(0))
                continue
            n = 40 + 13 * i + 7 * j
            t = np.arange(n) / REF_RATE
            tau = (2.0 + i + 0.5 * j) * 1e-6
            # about C times a sweep (5 nF, ~45 V: ~0.2 uC), the pre-conduction in sample 0
            p = (0.05 + 0.01 * j) * (1 - np.exp(-t / 0.5e-6)) * np.exp(-t / tau)
            p[0] += 0.003 * (1 + i)
            row.append(p)
            # ~2% of it out of the grid, slower
            g = -(0.001 + 0.0002 * i) * (1 - np.exp(-t / 1e-6)) * np.exp(-t / (2 * tau))
            g[0] -= 1e-5 * (1 + j)
            grow.append(g)
        pulses.append(row)
        grid_pulses.append(grow)
    return Tables(Unit(c_f=5e-9), v_g, log_s, v_s, dead, latched, pulses, grid_pulses,
                  {"fixture": True})  # fmt: skip


def element_fixture(t: Tables):
    from varimu.circuit.ir import ThyratronEvents

    d = t.to_dict()
    return ThyratronEvents(
        name="XV1", a="a", g="g", w="w", k="k", c_gk_f=2e-12, c_ga_f=6e-12, c_ak_f=6e-13,
        g_leak_s=4e-11, c_f=t.unit.c_f, r_s_ohm=t.unit.r_s_ohm, r_g_ohm=t.unit.r_g_ohm,
        ref_rate_hz=float(t.ref_rate_hz), v_g_v=tuple(d["v_g_v"]),
        log_slope=tuple(d["log_slope"]), v_s_v=tuple(tuple(r) for r in d["v_s_v"]),
        dead_s=tuple(tuple(r) for r in d["dead_s"]),
        latched=tuple(tuple(bool(x) for x in r) for r in d["latched"]),
        pulses_a=tuple(tuple(tuple(p) for p in row) for row in d["pulses_a"]),
        grid_pulses_a=tuple(tuple(tuple(p) for p in row) for row in d["grid_pulses_a"]),
        source="fixture",
    )  # fmt: skip


def events_fixtures() -> dict:
    """The kernels at 16 and 32 reference samples per step, step charges of a pulse, the
    crossing prediction on cases, lookups on the synthetic tables, and runs of `Events` on
    an emulated unit (a ramp with its strikes, the grid wobbling): the senses and the
    currents."""
    from varimu.circuit.ir import _encode

    t = _fixture_tables()
    out: dict = {"element": _encode(element_fixture(t)), "kernels": {}, "step_charges": {},
                 "crossings": [], "lookups": [], "runs": []}  # fmt: skip
    for m in (16, 32):
        out["kernels"][str(m)] = minphase_lowpass(m).tolist()
        p = t.pulses[1][1]
        out["step_charges"][str(m)] = {
            "pulse": p.tolist(),
            "filtered": step_charges(p, minphase_lowpass(m), m).tolist(),
            "raw": step_charges(p, np.ones(1), m).tolist(),
        }
    cases = [(-3.0, -2.0, -1.0), (-3.0, -2.5, -2.0), (-1.0, -2.0, -3.0), (-2.0, -1.0, 0.5),
             (-0.3, -0.2, -0.1), (-4.0, -1.0, -0.2), (-1e-3, -5e-4, -1e-9), (-5.0, -3.0, -2.0),
             (-1.0, -1.0, -1.0), (-2.0, -0.5, -0.25)]  # fmt: skip
    for c in cases:
        out["crossings"].append({"m": list(c), "phi": predict_crossing(c)})
    for vg, s in ((-6.0, 3e4), (-7.1, 1.1e4), (-4.5, 2e5), (-4.1, 2.8e5), (-4.0, 3e5),
                  (-20.0, 1.0), (5.0, 1e9), (-5.0, 8e4)):  # fmt: skip
        lk = lookup(t, 32, vg, s)
        out["lookups"].append({
            "v_g": vg, "slope": s, "v_s": lk.v_s, "dead_s": lk.dead_s, "latched": lk.latched,
            "q": None if lk.q is None else lk.q.tolist(),
            "q_raw": None if lk.q_raw is None else lk.q_raw.tolist(),
            "q_grid": None if lk.q_grid is None else lk.q_grid.tolist(),
            "centroid": lk.centroid,
        })  # fmt: skip
    for vg, s, fs in ((-6.0, 2e4, FS), (-4.6, 1.2e5, FS), (-7.0, 6e3, 2 * FS), (-4.0, 2.9e5, FS)):
        em = Emulator(t, vg, s, fs=fs)
        em.ev.c_ga_f = 6e-12
        v = np.zeros(int(0.012 * fs))
        senses, currents, grid, comp = [], [], [], []
        for k in range(len(v) - 1):
            vak = v[k] - t.unit.r_s_ohm * (em.ev.i_held - em.ev.i_comp)
            vgk = vg + 0.01 * math.sin(k / 7.0)
            i_ev = em.ev.sense(vak, vgk)
            senses.append([vak, vgk])
            currents.append(i_ev)
            grid.append(em.ev.i_grid)
            comp.append(em.ev.i_comp)
            v_inf = t.unit.v_charge_v - em.r_ch * (i_ev - em.ev.i_comp)
            v[k + 1] = v_inf + (v[k] - v_inf) * math.exp(-em.h / em.tau)
        out["runs"].append({"h": em.h, "c_ga_f": 6e-12, "senses": senses, "currents": currents,
                            "grid_currents": grid, "comp_currents": comp,
                            "events": em.ev.events, "late": em.ev.late,
                            "latched": em.ev.latched})  # fmt: skip
    return out


def events_fixtures_json() -> str:
    return json.dumps(events_fixtures(), allow_nan=False) + "\n"
