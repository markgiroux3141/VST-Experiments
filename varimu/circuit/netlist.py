"""Fairchild 670 (one channel) -> one coupled circuit (IR) -> SPICE netlist.

Since the device builder's B1 the 670 is a circuit file,
config/circuits/fairchild_670.yaml (parameters with sources, devices, parts),
built by the generic builder (varimu.circuit.builder) with the parts library
(varimu.circuit.parts). This module is the 670's API on top of them, as the
sim, measure and listen layers use it: `build()`, `resolve()`, `load_spec()`,
`genome_links()`, the transformers, the tube instances and the tolerance draws.

Audio path, sidechain and power supply are a single circuit. The control
voltage reaches the 6386 grids through the input transformer's centre tap,
the sidechain is fed from the output transformer (feedback topology), and
every stage hangs off the power supply's rails, as traced on the drawing
(data/schematics/fairchild_670/README.md, "Supply rails"):

- the mains (a sine source) into T302 and the GZ34, C304, L301, C305 + C306:
  the unregulated rail `ur` (12BH7 plate loads, T104's centre tap);
- the series regulator (EL34 pass, 6084 error amplifier, 5651 reference,
  R313 B+ ADJ): 240 V at `bp` (6386 plates, 12AX7 networks), and the R315 /
  R316 tap `sg` (6973 screens);
- the bias supply (T301, the selenium bridge GR301): `nb2` after L302 is the
  6386 cathode return, `nb3` (C108) feeds ZERO, `nb4` (R303) the 6973 grid
  leaks. The 6386 cathode current of both channels runs through L302, whose
  resistance sets the cathode return's voltage.

Channel 2 shares the supply. It is idle (left/right mode, no input) and
lumped: its two 6386 banks as one device of eight triodes, its 12BH7 and
6973 pairs as one double device each, on their own bias networks, so it
draws its own operating current from every rail and moves with the rails as
channel 1 loads them (the circuit file's "channel 2" section; its lumped
values are varimu.circuit.fairchild_670's derived values).

Transformers (Phase 2): windings on a Jiles-Atherton core (varimu.devices.core)
with winding resistance, leakage inductance, self- and interwinding
capacitance, the core's joint gap and classical eddy-current loss
(varimu.circuit.parts.transformer). `cores="linear"` builds the same circuit
with each core in its linear limit: ngspice can only run that (there is no
SPICE core), so the agreement tests compare both engines on it.

Simplifications in this slice (each is a later fidelity step):
- eddy-current loss is the classical thin-lamination term (frequency
  independent); a Cauer ladder for skin effect in the laminations is open;
- the 5651 is a diode in series with its burning voltage (no ignition: it
  is lit from the DC operating point on); electrolytics have no ESR; the
  mains transformers are ideal sources behind their winding resistance and
  leakage (no core); heaters aren't modeled;
- channel 2 is idle and lumped (see above), its parts nominal.

Per-instance tolerance (Phase 3): every part of channel 1 and the power supply
and every tube instance deviates from nominal by its own seeded draw (the
circuit file's "Per-instance tolerance and mismatch" and `tolerance`); each
6386 bank is its four triodes, so mismatch is within a bank too (the Rust
engine solves a bank as one parallel device: the same ports as one triode).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from varimu.circuit import builder, parts
from varimu.circuit import spec as spec_mod
from varimu.circuit.builder import CORE_MODES, Circuit
from varimu.circuit.fairchild_670 import BANK_TRIODES, threshold_section_load_ohm
from varimu.circuit.ir import CircuitIR, Element, Resistor
from varimu.circuit.parts import pentode_instance, tube_instance
from varimu.circuit.spec import CircuitSpec
from varimu.config import CONFIG_DIR
from varimu.devices.core import MagneticCore

__all__ = [
    "BANK_TRIODES",
    "CIRCUIT_FILE",
    "CORE_MODES",
    "Circuit",
    "CircuitSpec",
    "TRANSFORMERS",
    "build",
    "build_ir",
    "check_genome_links",
    "genome_links",
    "load_spec",
    "part_designator",
    "part_factor",
    "pentode_instance",
    "resolve",
    "threshold_section_load_ohm",
    "transformer",
    "transformer_core",
    "tube_deviation",
    "tube_instance",
    "unit_draws",
]

CIRCUIT_FILE = CONFIG_DIR / "circuits" / "fairchild_670.yaml"
TRANSFORMERS = ("t101", "t102", "t103", "t104")


def load_spec(path: Path = CIRCUIT_FILE) -> CircuitSpec:
    return spec_mod.load_circuit(path)


def __getattr__(name: str) -> Any:
    """Constants read from the circuit file: TITLE, INPUT_NODE, PROBE_NODES, SAVE (the
    node voltages every render saves, see varimu.sim.io.run_transient) and TUBE_PARAMS
    (the genome parameters that act on device instances, with their defaults; None:
    the device file's value)."""
    if name in ("TITLE", "INPUT_NODE", "PROBE_NODES", "SAVE", "TUBE_PARAMS"):
        s = load_spec()
        return {
            "TITLE": s.title,
            "INPUT_NODE": s.input_node,
            "PROBE_NODES": s.probes,
            "SAVE": tuple(f"v({n})" for n in s.probes),
            "TUBE_PARAMS": {k: e["value"] for k, e in s.device_params.items()},
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# --- Parameters --------------------------------------------------------------------


def resolve(overrides: Mapping[str, Any] | None = None, spec: CircuitSpec | None = None):
    """Defaults merged with overrides. Unknown keys and out-of-range controls are errors."""
    return spec_mod.resolve(spec or load_spec(), overrides)


def genome_links(spec: CircuitSpec | None = None) -> dict[str, str]:
    """Circuit value key -> genome_bounds.yaml path, for the uncertain values."""
    return spec_mod.genome_links(spec or load_spec())


def check_genome_links(spec: CircuitSpec | None = None) -> list[str]:
    """Problems with the circuit <-> genome_bounds links (empty list = fine)."""
    return spec_mod.check_genome_links(spec or load_spec())


# --- Per-instance tolerance ---------------------------------------------------------------


def _tolerance(p: Mapping[str, Any]) -> parts.Tolerance:
    spec = load_spec()
    tol = builder.tolerance(spec, p)
    assert tol is not None
    return tol


def unit_draws(p: Mapping[str, Any], designator: str, n: int = 1) -> np.ndarray:
    """n draws uniform in [-1, 1] for part `designator` of the unit (passive_seed),
    times passive_spread: default_rng([seed, crc32(designator)]), so adding a part
    doesn't move the others' draws."""
    return _tolerance(p).draws(designator, n)


def tube_deviation(p: Mapping[str, Any], designator: str) -> tuple[float, float]:
    """(emission factor, mu factor) of tube `designator`."""
    return _tolerance(p).tube_deviation(designator)


def part_factor(p: Mapping[str, Any], designator: str, cls: str) -> float:
    """The value factor of one part: its draw in its class's band."""
    return _tolerance(p).part_factor(designator, cls)


_PART = re.compile(r"([RC])(\d{3}[A-Z]?)([abc])?")


def part_designator(element: str) -> str | None:
    """The designator of a channel 1 / power supply part an element is (R105a -> R105,
    a tapped pot's R115Ac -> R115A, RAT1011 -> AT101), None for anything else
    (sources, loads, transformer parts, channel 2, numerical). The circuit file names
    each part's designator itself; this reads it back from an element's name."""
    if element.startswith("RAT101"):
        return "AT101"
    m = _PART.fullmatch(element)
    if not m or m.group(2)[0] not in "13":
        return None
    return m.group(1) + m.group(2)


# --- Building blocks (the parts library, with the 670's old signatures) -------------------


def _r(name: str, a: str, b: str, ohms: float) -> Resistor:
    return parts.resistor(f"R{name}", a, b, ohms)


def _pot(name: str, end_a: str, wiper: str, end_b: str, total: float, pos: float) -> list[Resistor]:
    """Potentiometer R<name>; pos = 0 puts the wiper at end_a, 1 at end_b."""
    return parts.pot(f"R{name}", end_a, wiper, end_b, total, pos)


def _tapped_pot(
    name: str, top: str, wiper: str, tap: str, total: float, pos: float, tap_pos: float
) -> list[Resistor]:
    """Potentiometer R<name> from `top` to ground with a fixed tap (parts.tapped_pot)."""
    return parts.tapped_pot(f"R{name}", "0", tap, wiper, top, total, pos, tap_pos)


def _t_pad(name: str, a: str, b: str, z: float, atten_db: float) -> list[Resistor]:
    """Symmetric T attenuator between a and b (to ground), characteristic impedance z."""
    return parts.t_pad(name, a, b, "0", z, atten_db)


def transformer_core(key: str, p: Mapping[str, Any]) -> MagneticCore:
    """The JA core of transformer `key` (t101..t104) from its material and path length."""
    return builder.transformer_core(load_spec(), key.upper(), p)


def transformer(key: str, p: Mapping[str, Any], cores: str = "ja") -> list[Element]:
    """The 670's transformer `key` (t101..t104) on its circuit nodes."""
    return builder.part_elements(load_spec(), key.upper(), p, cores)


# --- The circuit -------------------------------------------------------------------------------


def build(
    overrides: Mapping[str, Any] | None = None,
    spec: CircuitSpec | None = None,
    *,
    triode_formulation: str | None = None,
    cores: str | None = None,
) -> Circuit:
    """The netlist for one channel. `triode_formulation` is "table" or "exact"
    (default from sim_settings.yaml, devices.triode_formulation); `cores` is
    "ja" or "linear" (default devices.cores). A "ja" build has no SPICE text."""
    return builder.build(
        spec or load_spec(), overrides, triode_formulation=triode_formulation, cores=cores
    )


def build_ir(p: Mapping[str, Any], cores: str = "ja", spec: CircuitSpec | None = None) -> CircuitIR:
    """The circuit IR for resolved parameters `p` (see `resolve()`); `cores`: "ja" or
    "linear" (each core in its linear limit)."""
    return builder.build_ir(spec or load_spec(), p, cores)
