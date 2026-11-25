"""Aging a built circuit, and its carbon resistors' excess noise injected into the coupled
simulation (docs/PART_NOISE_PLAN.md PB1-PB2, the first spike on the Fender 5F1).

**Aging** is a transform on the built IR (FUTURE_DIRECTIONS.md section 2: in the place of the
tolerance draws, after them), from a `Condition` and a unit seed:
- carbon composition resistors drift up (a seeded draw per part, high values more), their
  noise index rises, and their Johnson sources follow the new value;
- paper coupling capacitors get a leakage resistor across them (the classic fault: DC from the
  plate onto the next grid);
- electrolytics lose capacitance and gain ESR (a resistor in series; new parts have one too,
  from a dissipation factor).

**Excess noise** (two passes; one-pass, in the engine, is PB2 proper): each noisy resistor gets
a Norton current source in parallel, a `Vccs` driven by a control input. Pass 1 runs with the
controls at zero and reads each resistor's current I(t); pass 2 drives each source with
I(t) dR/R(t) (`varimu.part_noise.resistor`), so the noise is amplified, distorted, compressed
and modulated by the coupled circuit. The current is pass 1's, not pass 2's: the error is the
noise's own effect on that current, second order in dR/R (dR/R is ~1e-6 at realistic levels,
~1e-3 at x1000). Same IR, same B5 seed in both passes: pass 2 - pass 1 is exactly what the
excess noise adds.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

import numpy as np

from varimu.circuit import ir as irm
from varimu.part_noise import resistor, rng_for

# --- The parts' laws (all provisional until sourced) ---------------------------------------

NI_SLOPE_DB_PER_DECADE = 6.7
NI_SLOPE_SOURCE = (
    "provisional: model knowledge (carbon composition's noise index grows with the value, "
    "web: https://epci.eu/resistors-noise-and-corrosion/ Fig. R1-15, values in an image; "
    "~-13 dB at 1k, 0 dB at 100k, +7 dB at 1M, inside Motchenbacher & Connelly's -20..+10 dB)"
)
POT_NI_ADD_DB = 3.0
POT_SOURCE = "provisional: model knowledge (a carbon pot's track, a little noisier than a resistor)"
TAN_DELTA_120HZ = 0.1
ESR_SOURCE = (
    "provisional: model knowledge (a new high-voltage aluminium electrolytic's dissipation "
    "factor ~0.1 at 120 Hz, ESR = tan d / (2 pi 120 C); IEC 60384-4 allows up to ~0.15-0.2)"
)
CONDITION_SOURCE = (
    "provisional: model knowledge (FUTURE_DIRECTIONS.md section 2's forms: carbon "
    "compositions drift up 5-15%+ over decades, high values most; electrolytics dry, C down, "
    "ESR up (end of life: C -20%, tan d 2x and beyond); old paper coupling capacitors leak, "
    "putting volts of DC on the next grid; the four points' numbers are not fitted to data)"
)


@dataclass(frozen=True)
class Condition:
    name: str
    title: str
    drift_mean: float  # carbon composition, at 100k (a share of the value)
    drift_sd: float
    ni_add_db: float  # on the noise index
    coupling_leak_ohm: float | None  # None: no leakage
    electro_c: float  # capacitance factor
    electro_esr: float  # ESR factor
    source: str = CONDITION_SOURCE


CONDITIONS = {
    c.name: c
    for c in (
        Condition("new", "new (1958, fresh from the factory)", 0.0, 0.0, 0.0, None, 1.0, 1.0),
        Condition("played", "played (~1975, gigged, kept dry)", 0.04, 0.03, 3.0, 1e9, 0.9, 2.0),
        Condition(
            "cap_job", "needs a cap job (today, original parts)", 0.12, 0.06, 8.0, 2e7, 0.5, 8.0
        ),
        Condition(
            "wreck", "a wreck (damp basement, never serviced)", 0.25, 0.10, 15.0, 3e6, 0.2, 30.0
        ),
    )
}


@dataclass(frozen=True)
class PartsMap:
    """Which IR elements of a circuit are which kind of part."""

    carbon: tuple[str, ...]  # carbon composition resistors
    pots: tuple[str, ...]  # carbon pot halves (noisy, not drifted)
    coupling: tuple[str, ...]  # paper coupling capacitors
    electrolytic: tuple[str, ...]


CHAMP_5F1 = PartsMap(
    # Every resistor of a late-50s Fender is carbon composition (Allen-Bradley); the jack
    # contacts and the numerical leak are not resistors.
    carbon=(
        "RIN1",
        "RGA",
        "RGB",
        "RPLA",
        "RKA",
        "RPLB",
        "RKB",
        "RFB",
        "RG6",
        "RK6",
        "RB12",
        "RB23",
    ),
    pots=("RVOLa", "RVOLb"),
    coupling=("CCA", "CCB"),
    electrolytic=("CB1", "CB2", "CB3", "CK6"),
)


@dataclass(frozen=True)
class Noisy:
    name: str
    a: str
    b: str
    r_ohm: float
    ni_db: float


def carbon_ni_db(r_ohm: float, add_db: float) -> float:
    return (
        resistor.CARBON_COMP.noise_index_db
        + NI_SLOPE_DB_PER_DECADE * math.log10(r_ohm / 1e5)
        + add_db
    )


def drift_factor(name: str, r_ohm: float, cond: Condition, seed: int) -> float:
    """1 + a seeded drift, scaled up for high values (x1 at 100k, ~x1.25 at 1M)."""
    if cond.drift_mean == 0.0 and cond.drift_sd == 0.0:
        return 1.0
    scale = max(0.5, 1.0 + 0.25 * math.log10(r_ohm / 1e5))
    z = rng_for(seed, f"drift:{name}").standard_normal()
    return max(0.5, 1.0 + scale * (cond.drift_mean + cond.drift_sd * z))


def apply(ir: irm.CircuitIR, parts: PartsMap, cond: Condition, seed: int):
    """(the aged IR, its noisy resistors)."""
    noisy: list[Noisy] = []
    new_r: dict[str, float] = {}
    sections = []
    for sec in ir.sections:
        out = []
        for e in sec.elements:
            if isinstance(e, irm.Resistor) and e.name in parts.carbon:
                r = e.r_ohm * drift_factor(e.name, e.r_ohm, cond, seed)
                new_r[e.name] = r
                out.append(dataclasses.replace(e, r_ohm=r))
                noisy.append(Noisy(e.name, e.a, e.b, r, carbon_ni_db(e.r_ohm, cond.ni_add_db)))
            elif isinstance(e, irm.Resistor) and e.name in parts.pots:
                out.append(e)
                ni = carbon_ni_db(e.r_ohm, cond.ni_add_db + POT_NI_ADD_DB)
                noisy.append(Noisy(e.name, e.a, e.b, e.r_ohm, ni))
            elif isinstance(e, irm.Capacitor) and e.name in parts.coupling:
                out.append(e)
                if cond.coupling_leak_ohm is not None:
                    out.append(irm.Resistor(f"RLK_{e.name}", e.a, e.b, cond.coupling_leak_ohm))
            elif isinstance(e, irm.Capacitor) and e.name in parts.electrolytic:
                mid = f"{e.name}_esr"
                esr = TAN_DELTA_120HZ / (2 * math.pi * 120.0 * e.c_f) * cond.electro_esr
                out.append(dataclasses.replace(e, b=mid, c_f=e.c_f * cond.electro_c))
                out.append(irm.Resistor(f"RESR_{e.name}", mid, e.b, esr))
            else:
                out.append(e)
        sections.append(dataclasses.replace(sec, elements=tuple(out)))
    # Johnson sources follow the drifted values (4kT/R).
    fixed = []
    for sec in sections:
        els = []
        for e in sec.elements:
            if isinstance(e, irm.NoiseCurrent) and e.name.startswith("IN_"):
                r_name = e.name[3:]
                if r_name in new_r:
                    old = next(n for n in _resistors(ir) if n.name == r_name).r_ohm
                    e = dataclasses.replace(e, psd_a2_hz=e.psd_a2_hz * old / new_r[r_name])
            els.append(e)
        fixed.append(dataclasses.replace(sec, elements=tuple(els)))
    missing = set(parts.carbon + parts.pots + parts.coupling + parts.electrolytic) - {
        e.name for e in ir.elements()
    }
    if missing:
        raise KeyError(f"not in the circuit: {sorted(missing)}")
    return dataclasses.replace(ir, sections=tuple(fixed)), noisy


def _resistors(ir: irm.CircuitIR):
    return (e for e in ir.elements() if isinstance(e, irm.Resistor))


# --- Excess noise as controlled sources ------------------------------------------------------

GM_S = 1e-6  # each source's transconductance: a control volt is a microamp


def control_name(r: str) -> str:
    return f"xn_{r}"


def with_sources(ir: irm.CircuitIR, noisy: list[Noisy]) -> irm.CircuitIR:
    """The IR with a Norton source per noisy resistor (controls at zero: the same circuit),
    and probes on every node they need."""
    els = []
    for n in noisy:
        c = control_name(n.name)
        els.append(irm.Vccs(f"GXN_{n.name}", n.a, n.b, c, "0", GM_S))
        # A load on the control's node (a node needs two elements; a Vccs's control draws
        # nothing): it loads only the control's own source, nothing in the circuit.
        els.append(irm.Resistor(f"RXN_{n.name}", c, "0", 1e6))
    els = tuple(els)
    controls = tuple(irm.Control(control_name(n.name), control_name(n.name)) for n in noisy)
    have = {p.node for p in ir.probes}
    need = sorted({x for n in noisy for x in (n.a, n.b) if x != "0"} - have)
    return dataclasses.replace(
        ir,
        sections=(*ir.sections, irm.Section("excess noise", els)),
        controls=(*ir.controls, *controls),
        probes=(*ir.probes, *(irm.VoltageProbe(x) for x in need)),
    )


def zero_controls(noisy: list[Noisy], n: int) -> dict[str, np.ndarray]:
    return {control_name(x.name): np.zeros(n) for x in noisy}


def excess_controls(
    vectors: dict[str, np.ndarray],
    noisy: list[Noisy],
    rate_hz: float,
    seed: int,
    exaggerate: float = 1.0,
) -> dict[str, np.ndarray]:
    """Each source's control from pass 1's node voltages: I(t) dR/R(t) / GM_S, dR/R scaled
    by `exaggerate` (x10 = +20 dB of noise index)."""
    n = len(next(iter(vectors.values())))
    zero = np.zeros(n)
    out = {}
    for x in noisy:
        va = vectors.get(f"v({x.a})", zero) if x.a != "0" else zero
        vb = vectors.get(f"v({x.b})", zero) if x.b != "0" else zero
        i = (va - vb) / x.r_ohm
        d = resistor.fluctuation(x.ni_db, n, rate_hz, seed, f"excess:{x.name}")
        out[control_name(x.name)] = i * d * exaggerate / GM_S
    return out
