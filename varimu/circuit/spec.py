"""Circuit files: parameters with sources, devices, parts (device builder, B1).

A circuit file (config/circuits/*.yaml) describes one circuit for
varimu.circuit.builder, which expands its parts with the parts library
(varimu.circuit.parts) into the circuit IR. Top-level keys:

    title: ...                      # the IR's title
    input: in                       # the node the audio input drives
    cv_inputs: {gate: g, ...}       # control inputs: nodes driven by their own samples
    audio_inputs: {in_r: r, ...}    # second audio inputs: control inputs interpolated as
                                    # the input is (a stereo unit's right channel)
    probes: [out, cv, ...]          # node voltages every render saves
    full_scale: {input_volts_peak: {value, source}, output_volts_peak | output_pascals_peak: {...}}
    controls: {key: {value, min, max | choices, source, unit?, notes?}}
    values: {key: {value, source, genome?, unit?, notes?}}
    device_params: {key: {value, source, genome?}}   # act on device instances
    derived: {module: python.module, values: {key: {source}}}
    mains: {v_rms: <control>, hz: <control>, rated_v_rms: <param or {value, source}>}
    tolerance: {source, seed, spread, tube: {emission_pct, mu_pct}, bands, classes, combined}
    noise: {seed, temperature_k?, flicker_v2?, mains_rms?}   # noise on (device builder B5)
    heaters: {start?: warm | cold, tap?: KEY}  # heated cathodes (device builder B6)
    devices: {key: {device, ...}}   # device model instances, in IR model order
    sections: [{title, tolerance?, substeps?, decimate?, owns?, lag_samples?, method?,
                tube_tables?, substeps_in?, when?, parts: {NAME: {<macro>: <nodes>, ...}}}]
                                    # substeps: steps per sample on a thread of its own (a
                                    # multi-rate part: circuitsim's partition.rs);
                                    # decimate: fir (what it hands on through an
                                    # anti-alias low-pass); owns: [node, ...] (shared nodes
                                    # it owns: an island's output); lag_samples: N
                                    # (it reads the others N samples late and runs
                                    # ahead: a cut only through stiff rails);
                                    # method: its own integration method (e.g.
                                    # trbdf2), tube_tables: true (its triodes from
                                    # tables): TAPE_SPEED_PLAN.md P4;
                                    # substeps_in: events (the island only in a
                                    # build with event kernels, K's at a finer step
                                    # than the sample; a literal build, the kernels'
                                    # reference, runs it at the sample rate: the
                                    # Minimoog's oscillators, HYBRID_PHYSICS_PLAN.md H5);
                                    # when: [control | [control, ...], ...] (built only
                                    # while one entry holds: a control nonzero, a switch
                                    # on, or a list's every control nonzero; `!control`:
                                    # that control at 0: else its parts expand,
                                    # their devices count as used, and nothing of it is in
                                    # the IR, as a switched-off part; its exceptions too: a
                                    # circuit nobody hears needn't run, the Minimoog's
                                    # mixer switches, docs/MINIMOOG_PLAN.md "Real time")

Parameters (controls, values, device_params, derived) are what parts refer to by
key; every one has a `source` (CLAUDE.md, hard rules), and `--set` overrides
any control, value or device parameter. A control has `min` and `max`, or
`choices` (a switch's positions, e.g. its frequencies); one with `unit: position`
is an integer switch position, one with `unit: switch` an on / off switch (choices [0, 1],
an integer; the native app draws it as a checkbox). Values linked to the genome
(`genome:`) have their bounds in config/genome_bounds.yaml. A device parameter may be null: the
device file's value. Derived values are functions of the resolved parameters,
named in the file with their source and computed by the module's function of
the same name (for arithmetic the parts can't express, e.g. lumping parallel
parts); they can't be overridden.

`full_scale` (optional, device builder B9) is the circuit's own audio convention: the
volts a full-scale input sample (1.0) puts on the input node, and the `v(out)` that
reads as 1.0 (a guitar amp takes a pickup's ~1 V and drives a speaker with ~50 V).
The output is `output_volts_peak` or, when `out` is a sound pressure (a `speaker`
part's readout: pascals as volts, component editor C3), `output_pascals_peak`: the
same number to every render path, its unit for display (`full_scale_unit`). Without the
block both are sim_settings' `audio.full_scale_volts_peak`. It is no parameter and not
in the IR: renders and the native app scale around the circuit with it
(`varimu.sim.io.full_scale`).

`noise` (optional, device builder B5) turns the circuit's noise sources on: Johnson noise
on its resistors, shot, grid-current shot and flicker noise on its tubes
(varimu.devices.noise; the builder's docstring says which parts). `seed` is an integer
(every source's stream is keyed by it and its name); `temperature_k` (the resistors') and
`flicker_v2` (K_f, V^2) are parameters or {value, source}, by default varimu.devices.noise's
RESISTOR_T_K and FLICKER_V2; so is `mains_rms`, the mains wander of a circuit with `mains`
parts (default MAINS_RMS, 0 for none). Renders can override it (`build(..., noise=)`).

`heaters` (optional, device builder B6) heats the tubes' cathodes: every triode, pentode and
vacuum diode instance follows one cathode temperature (varimu.devices.cathode; constants and
heater ratings in config/cathodes.yaml), its heater at the mains setting's ratio to the
rated mains (and B5's mains wander when the noise has it); `start` warm (default) or cold
(power on); `tap` a parameter key whose value multiplies that ratio (a heater winding's tap
or series rheostat on the panel: tube_synth's HEATER). Renders can override it
(`build(..., heaters=)`).

Parts and devices are read by varimu.circuit.builder (its docstring has the
macro parts and their parameters).
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import importlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from varimu.circuit.ir import DECIMATIONS, MULTIRATE_METHODS
from varimu.config import ConfigError, load_genome_bounds

# PyYAML reads 1.0e6 (no sign in the exponent) as a string: such a value is an error.
_NUMBER_LIKE = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")
_TOP_KEYS = {
    "title",
    "input",
    "cv_inputs",
    "audio_inputs",
    "probes",
    "full_scale",
    "controls",
    "values",
    "device_params",
    "derived",
    "mains",
    "tolerance",
    "devices",
    "sections",
    "noise",
    "heaters",
    "exceptions",
}

# An exception's nodes per kind (HYBRID_PHYSICS_PLAN.md: technique K's event kernels for a
# group of parts; varimu.devices.reset_events).
EXCEPTION_NODES = {"reset": ("sense", "src", "dst"), "edge": ("plus", "minus", "src", "dst")}


@dataclass(frozen=True)
class CircuitSpec:
    controls: dict[str, dict[str, Any]]
    values: dict[str, dict[str, Any]]
    parts: dict[str, Any] = dataclasses.field(default_factory=dict)  # the tolerance block
    device_params: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    title: str = ""
    input_node: str = "in"
    # Control inputs (cv_inputs: {name: node}, file order): a gate, a pitch voltage.
    cv_inputs: tuple[tuple[str, str], ...] = ()
    # Second audio inputs (audio_inputs: {name: node}, file order): control inputs
    # interpolated as the input is; in the IR after the cv_inputs, marked `audio`.
    audio_inputs: tuple[tuple[str, str], ...] = ()
    probes: tuple[str, ...] = ()
    mains: dict[str, Any] | None = None
    derived: dict[str, Any] = dataclasses.field(default_factory=dict)
    devices: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    sections: tuple[dict[str, Any], ...] = ()
    path: Path | None = None
    # (input, output) volts peak at full scale; None: sim_settings' (the module docstring).
    full_scale: tuple[float, float] | None = None
    full_scale_block: dict[str, Any] | None = None  # as written, with its sources
    full_scale_unit: str = "V"  # the output's: "V", or "Pa" (output_pascals_peak)
    noise: dict[str, Any] | None = None  # the `noise` block as written (None: no noise)
    heaters: dict[str, Any] | None = None  # the `heaters` block (None: cathodes not heated)
    # Physics exceptions (`exceptions: {NAME: {kind, tables, <nodes>, replaces, parts?,
    # renders?, source}}`): in an events build the parts `replaces` names are dropped and the
    # kind's event element (named NAME, its tables config/events/<tables>.json) stands in
    # their place, with `parts` (their off state, ordinary parts) beside it; with `renders:
    # true` in every build (the literal parts can't be simulated at a render's rate either)
    # but a `literal` one (builder.build_ir).
    exceptions: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)

    def part_classes(self) -> dict[str, str]:
        """Designator -> tolerance class."""
        return {d: c for c, ds in self.parts.get("classes", {}).items() for d in ds}

    def defaults(self) -> dict[str, Any]:
        d = {k: e["value"] for k, e in self.controls.items()}
        d.update({k: e["value"] for k, e in self.values.items()})
        d.update({k: e["value"] for k, e in self.device_params.items() if e["value"] is not None})
        return d

    def parameter_keys(self) -> set[str]:
        """Every key `--set` takes."""
        return set(self.controls) | set(self.values) | set(self.device_params)

    def derived_keys(self) -> set[str]:
        return set(self.derived.get("values", {}))

    def derive(self, p: Mapping[str, Any]) -> dict[str, Any]:
        """The derived values for resolved parameters `p`."""
        names = self.derived_keys()
        if not names:
            return {}
        module = importlib.import_module(self.derived["module"])
        return {k: getattr(module, k)(p) for k in names}


def _sourced(where: str, e: Any, errors: list[str], *, allow_null: bool = False) -> None:
    if not isinstance(e, Mapping) or "value" not in e:
        errors.append(f"{where}: needs a `value`")
    elif not str(e.get("source", "")).strip():
        errors.append(f"{where}: needs a `source`")
    elif e["value"] is None and not allow_null:
        errors.append(f"{where}: value is null")
    elif isinstance(e["value"], str) and _NUMBER_LIKE.fullmatch(e["value"].strip()):
        errors.append(f"{where}: value {e['value']!r} is not a number (write 1.0e+6, not 1.0e6)")


@functools.lru_cache(maxsize=16)
def _parse(path: Path, mtime_ns: int, size: int) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_circuit(path: Path) -> CircuitSpec:
    """Read and check a circuit file (parameters and their sources, the tolerance block,
    the shape of devices and sections; the builder checks the parts). Raises ConfigError.
    The parse is cached per (path, modification time, size); each call gets its own copy."""
    path = Path(path).resolve()
    st = path.stat()
    data = copy.deepcopy(_parse(path, st.st_mtime_ns, st.st_size))
    errors: list[str] = []
    unknown = set(data) - _TOP_KEYS
    if unknown:
        errors.append(f"unknown top-level keys {sorted(unknown)}")
    controls = data.get("controls") or {}
    values = data.get("values") or {}
    device_params = data.get("device_params") or {}
    for k, e in controls.items():
        _sourced(f"controls.{k}", e, errors)
        if isinstance(e, Mapping) and not ({"min", "max"} <= set(e) or "choices" in e):
            errors.append(f"controls.{k}: needs `min` and `max`, or `choices`")
        elif isinstance(e, Mapping) and "choices" in e and e.get("value") not in e["choices"]:
            errors.append(f"controls.{k}: value {e.get('value')!r} not in its choices")
    for k, e in values.items():
        _sourced(f"values.{k}", e, errors)
    for k, e in device_params.items():
        _sourced(f"device_params.{k}", e, errors, allow_null=True)
    derived = data.get("derived") or {}
    if derived:
        if not derived.get("module"):
            errors.append("derived: needs a `module`")
        for k, e in (derived.get("values") or {}).items():
            if not isinstance(e, Mapping) or not str(e.get("source", "")).strip():
                errors.append(f"derived.values.{k}: needs a `source`")
    keys = [*controls, *values, *device_params, *(derived.get("values") or {})]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        errors.append(f"parameters defined twice: {dupes}")

    tol = data.get("tolerance") or {}
    if tol:
        if not str(tol.get("source", "")).strip():
            errors.append("tolerance: needs a `source`")
        for k in ("seed", "spread"):
            if k not in tol:
                errors.append(f"tolerance: needs `{k}` (a parameter key)")
        seen: dict[str, str] = {}
        for c, ds in (tol.get("classes") or {}).items():
            if c not in (tol.get("bands") or {}):
                errors.append(f"tolerance: class {c} has no band")
            for d in ds:
                if d in seen:
                    errors.append(f"tolerance: {d} in both {seen[d]} and {c}")
                seen[d] = c

    sections = data.get("sections") or []
    for i, s in enumerate(sections):
        if not isinstance(s, Mapping) or "title" not in s or "parts" not in s:
            errors.append(f"sections[{i}]: needs `title` and `parts`")
        elif extra := set(s) - {
            "title", "parts", "tolerance", "substeps", "decimate", "owns", "lag_samples",
            "method", "tube_tables", "substeps_in", "when",
        }:  # fmt: skip
            errors.append(f"sections[{i}]: unknown keys {sorted(extra)}")
        elif "when" in s and (
            not isinstance(s["when"], list)
            or not s["when"]
            or not all(
                (isinstance(c, str) and c.removeprefix("!") in controls)
                or (
                    isinstance(c, list)
                    and c
                    and all(isinstance(x, str) and x.removeprefix("!") in controls for x in c)
                )
                for c in s["when"]
            )
        ):
            errors.append(
                f"sections[{i}]: when {s['when']!r} (a list of controls or lists of controls)"
            )
        elif "substeps" in s and (
            isinstance(s["substeps"], bool)
            or not isinstance(s["substeps"], int)
            or s["substeps"] < 1
        ):
            errors.append(f"sections[{i}]: substeps {s['substeps']} (a count, 1 or more)")
        elif {"decimate", "owns", "lag_samples", "method", "tube_tables", "substeps_in"} & set(
            s
        ) and s.get("substeps", 1) < 2:
            errors.append(
                f"sections[{i}]: decimate, owns, lag_samples, method, tube_tables and"
                " substeps_in are for a multi-rate section"
            )
        elif "substeps_in" in s and s["substeps_in"] != "events":
            errors.append(f"sections[{i}]: substeps_in {s['substeps_in']!r} (events)")
        elif "method" in s and s["method"] not in MULTIRATE_METHODS:
            errors.append(f"sections[{i}]: method {s['method']!r} (one of {MULTIRATE_METHODS})")
        elif "tube_tables" in s and not isinstance(s["tube_tables"], bool):
            errors.append(f"sections[{i}]: tube_tables {s['tube_tables']!r} (true or false)")
        elif "lag_samples" in s and (
            isinstance(s["lag_samples"], bool)
            or not isinstance(s["lag_samples"], int)
            or s["lag_samples"] < 1
            or "decimate" in s
            or "owns" in s
        ):
            errors.append(
                f"sections[{i}]: lag_samples {s['lag_samples']!r} (a count, 1 or more,"
                " without decimate or owns)"
            )
        elif "decimate" in s and s["decimate"] not in DECIMATIONS:
            errors.append(f"sections[{i}]: decimate {s['decimate']!r} (one of {DECIMATIONS})")
        elif "owns" in s and (
            not isinstance(s["owns"], list)
            or not s["owns"]
            or not all(isinstance(n, str) for n in s["owns"])
        ):
            errors.append(f"sections[{i}]: owns {s['owns']!r} (a list of nodes)")
    for k, e in (data.get("devices") or {}).items():
        if not isinstance(e, Mapping) or "device" not in e:
            errors.append(f"devices.{k}: needs a `device`")
    full_scale, unit = _full_scale(data.get("full_scale"), errors)
    heaters = data.get("heaters")
    if heaters is not None:
        if not isinstance(heaters, Mapping) or set(heaters) - {"start", "tap"}:
            errors.append("heaters: a mapping {start?: warm | cold, tap?: KEY}")
        elif heaters.get("start", "warm") not in ("warm", "cold"):
            errors.append(f"heaters.start: {heaters['start']!r} (warm | cold)")
    noise = data.get("noise")
    if noise is not None:
        if not isinstance(noise, Mapping) or "seed" not in noise:
            errors.append("noise: a mapping {seed, temperature_k?, flicker_v2?}")
        else:
            if extra := set(noise) - {"seed", "temperature_k", "flicker_v2", "mains_rms"}:
                errors.append(f"noise: unknown keys {sorted(extra)}")
            seed = noise["seed"]
            if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**64:
                errors.append(f"noise.seed: {seed!r} is not an integer in [0, 2^64)")
    exceptions = data.get("exceptions") or {}
    part_names = {str(n) for s in sections if isinstance(s, Mapping)
                  for n in (s.get("parts") or {})}  # fmt: skip
    for name, e in exceptions.items():
        where = f"exceptions.{name}"
        if not isinstance(e, Mapping) or e.get("kind") not in EXCEPTION_NODES:
            errors.append(f"{where}: a mapping with kind {sorted(EXCEPTION_NODES)}")
            continue
        nodes = EXCEPTION_NODES[e["kind"]]
        allowed = {"kind", "tables", "replaces", "parts", "source", "notes", "renders", *nodes}
        if e["kind"] == "edge":
            allowed |= {"follows", "follow_gain"}
        if set(e) - allowed or not {"tables", "replaces", "source", *nodes} <= set(e):
            errors.append(f"{where}: keys kind, tables, {', '.join(nodes)}, replaces, source "
                          f"(parts optional); got {sorted(e)}")  # fmt: skip
            continue
        if e.get("renders", False) not in (True, False):
            errors.append(f"{where}.renders: true or false")
        rep = e["replaces"]
        if not isinstance(rep, list) or not rep or not set(map(str, rep)) <= part_names:
            errors.append(f"{where}.replaces: a list of the circuit's part names")
    if errors:
        raise ConfigError(f"{path}:\n  " + "\n  ".join(errors))
    return CircuitSpec(
        controls=controls,
        values=values,
        parts=tol,
        device_params=device_params,
        title=data.get("title", ""),
        input_node=data.get("input", "in"),
        cv_inputs=tuple((str(k), str(v)) for k, v in (data.get("cv_inputs") or {}).items()),
        audio_inputs=tuple((str(k), str(v)) for k, v in (data.get("audio_inputs") or {}).items()),
        probes=tuple(data.get("probes") or ()),
        mains=data.get("mains"),
        derived=derived,
        devices=data.get("devices") or {},
        sections=tuple(sections),
        path=Path(path),
        full_scale=full_scale,
        full_scale_block=data.get("full_scale"),
        full_scale_unit=unit,
        noise=noise,
        heaters=heaters,
        exceptions=dict(exceptions),
    )


_FULL_SCALE_OUTPUTS = {"output_volts_peak": "V", "output_pascals_peak": "Pa"}


def _full_scale(fs: Any, errors: list[str]) -> tuple[tuple[float, float] | None, str]:
    """The `full_scale` block as ((input, output) peak, the output's unit); (None, "V"):
    absent, or an error appended."""
    if fs is None:
        return None, "V"
    outs = [k for k in _FULL_SCALE_OUTPUTS if isinstance(fs, Mapping) and k in fs]
    if not isinstance(fs, Mapping) or len(outs) != 1 or set(fs) != {"input_volts_peak", *outs}:
        errors.append(
            f"full_scale: needs exactly input_volts_peak and one of {list(_FULL_SCALE_OUTPUTS)}"
        )
        return None, "V"
    out = []
    for k in ("input_volts_peak", outs[0]):
        n = len(errors)
        _sourced(f"full_scale.{k}", fs[k], errors)
        if len(errors) > n:
            return None, "V"
        v = fs[k]["value"]
        if isinstance(v, bool) or not isinstance(v, int | float) or not v > 0:
            errors.append(f"full_scale.{k}: value {v!r} is not a positive number")
            return None, "V"
        out.append(float(v))
    return (out[0], out[1]), _FULL_SCALE_OUTPUTS[outs[0]]


def circuit_path(name: str) -> Path:
    """config/circuits/<name>.yaml (KeyError: no such circuit)."""
    from varimu.config import CONFIG_DIR

    path = CONFIG_DIR / "circuits" / f"{name}.yaml"
    if not path.exists():
        raise KeyError(f"no circuit file {path}")
    return path


def resolve(spec: CircuitSpec, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Defaults merged with overrides. Unknown keys and out-of-range controls are errors."""
    p = spec.defaults()
    known = spec.parameter_keys()
    for k, v in (overrides or {}).items():
        if k not in known:
            raise KeyError(f"unknown circuit parameter {k!r}")
        p[k] = v
    for k, e in spec.controls.items():
        if "choices" in e:
            if p[k] not in e["choices"]:
                raise ValueError(f"control {k}={p[k]} not one of {e['choices']}")
        elif not e["min"] <= p[k] <= e["max"]:
            raise ValueError(f"control {k}={p[k]} outside [{e['min']}, {e['max']}]")
    for k, e in spec.controls.items():
        if e.get("unit") in ("position", "switch"):
            p[k] = int(p[k])
    return p


def genome_links(spec: CircuitSpec) -> dict[str, str]:
    """Circuit value key -> genome_bounds.yaml path, for the uncertain values."""
    return {k: e["genome"] for k, e in spec.values.items() if "genome" in e}


def check_genome_links(spec: CircuitSpec) -> list[str]:
    """Problems with the circuit <-> genome_bounds links (empty list = fine): values and
    device parameters (a null device parameter's nominal is the device file's)."""
    bounds = load_genome_bounds()
    links = [(k, e["genome"], e["value"]) for k, e in spec.values.items() if "genome" in e]
    links += [(k, e["genome"], e["value"]) for k, e in spec.device_params.items() if "genome" in e]
    problems = []
    for key, path, v in links:
        b = bounds.get(path)
        if b is None:
            problems.append(f"{key}: genome path {path} not in genome_bounds.yaml")
        elif not b.resolved:
            problems.append(f"{key}: genome bounds {path} still TBD")
        elif v is None:
            continue
        elif b.choices is not None:
            if v not in b.choices:
                problems.append(f"{key}: nominal {v!r} not in {list(b.choices)} ({path})")
        elif not b.min <= v <= b.max:
            problems.append(f"{key}: nominal {v} outside [{b.min}, {b.max}] ({path})")
    return problems
