"""Solo a part (ANALOG_MAGIC_FABLE.md AM13), step 1: the output's sensitivity to one part's
value by finite differences.

    s(t) = d out(t) / d ln(value) ~ (y(1 + delta) - y(1 - delta)) / (2 delta)

is what the output gains per unit of relative change of that part: played alone, the part's
"solo"; its level (re the output) ranks the parts of a circuit by how much they matter for a
program, which says which provisional values to source first.

The two runs must differ by the part, not by the solver: no step-size control (both runs take
the same steps), Newton at 1e-9, noise and heaters off, cores in their linear limit (the doc's
settings). Self-check: s at delta 0.005 and 0.02; when they differ by more than -30 dB re s's
own level the part is flagged (the response isn't linear over that range, or s is under the
numerical floor). The reported s is the 0.005 one.

Runs are cached in cache/magic/renders/ keyed by the perturbed IR, the input and the settings.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from varimu.circuit.ir import Capacitor, CircuitIR, Inductor, Resistor
from varimu.magic import render

DELTAS = (0.005, 0.02)
FLAG_DB = -30.0
_VALUE_FIELD = {Resistor: "r_ohm", Capacitor: "c_f", Inductor: "l_h"}


def elements(ir: CircuitIR) -> dict[str, Any]:
    """Every resistor, capacitor and inductor of the IR by name."""
    return {e.name: e for s in ir.sections for e in s.elements if type(e) in _VALUE_FIELD}


def value_of(e) -> float:
    return float(getattr(e, _VALUE_FIELD[type(e)]))


def perturbed(ir: CircuitIR, name: str, factor: float) -> CircuitIR:
    """A copy of the IR with element `name`'s value multiplied by `factor`."""
    found = False
    sections = []
    for s in ir.sections:
        els = []
        for e in s.elements:
            if e.name == name and type(e) in _VALUE_FIELD:
                f = _VALUE_FIELD[type(e)]
                e = dataclasses.replace(e, **{f: getattr(e, f) * factor})
                found = True
            els.append(e)
        sections.append(dataclasses.replace(s, elements=tuple(els)))
    if not found:
        raise KeyError(f"no resistor, capacitor or inductor named {name!r}")
    return dataclasses.replace(ir, sections=tuple(sections))


def solo_settings(quality: str = "production"):
    """The doc's settings: fixed steps, tight Newton."""
    st = render.settings(quality)
    return dataclasses.replace(
        st, error_abstol=0.0, error_reltol=0.0, newton_reltol=1e-9, newton_vntol=1e-9
    )


def build(circuit: str, overrides: Mapping[str, Any] | None = None, cores: str = "linear"):
    """(ir, v_in, v_out) for a circuit file: noise and heaters off."""
    from varimu.circuit import builder, spec
    from varimu.sim.io import full_scale

    c = spec.load_circuit(spec.circuit_path(circuit))
    st = solo_settings()
    v_in, v_out = full_scale(st, c)
    with render._build_lock:
        b = builder.build(
            c,
            dict(overrides or {}),
            triode_formulation=st.triode_formulation,
            cores=cores,
            noise=False,
            heaters=False,
        )
    return b.ir, v_in, v_out


def run_ir(
    ir: CircuitIR,
    x: np.ndarray,
    v_in: float,
    v_out: float,
    *,
    probe: str = "out",
    settings=None,
    cache: bool = True,
) -> np.ndarray:
    """x (dBFS scale) through an IR; the probe on the dBFS scale. Cached."""
    from varimu.sim import fast

    st = settings if settings is not None else solo_settings()
    x = np.asarray(x, float)
    ir_hash = hashlib.sha256(repr(ir).encode()).hexdigest()
    key = render._key(
        ["solo_run", render.VERSION, ir_hash, v_in, v_out, probe, repr(st), render._source_hash()],
        [x],
    )

    def make():
        r = fast.run_transient(ir, x * v_in, settings=st)
        return {"out": np.asarray(r.vectors[f"v({probe})"], float) / v_out}

    return render._cached(key, cache, make)["out"]


def sensitivity(
    ir: CircuitIR,
    x: np.ndarray,
    name: str,
    v_in: float,
    v_out: float,
    *,
    probe: str = "out",
    deltas: Sequence[float] = DELTAS,
    settings=None,
) -> dict:
    """{"s": s at deltas[0], "y": the mean of its two runs (the output to first order),
    "level_db": s re y, "check_db": s(deltas[1]) - s(deltas[0]) re s, "flag": bool}."""
    ss, ys = [], []
    for d in deltas:
        yp = run_ir(perturbed(ir, name, 1 + d), x, v_in, v_out, probe=probe, settings=settings)
        ym = run_ir(perturbed(ir, name, 1 - d), x, v_in, v_out, probe=probe, settings=settings)
        ss.append((yp - ym) / (2 * d))
        ys.append(0.5 * (yp + ym))
    s, y = ss[0], ys[0]
    lv = level_db(s, y)
    ck = level_db(ss[1] - ss[0], s)
    return {"s": s, "y": y, "level_db": lv, "check_db": ck, "flag": bool(ck > FLAG_DB)}


def level_db(x: np.ndarray, re: np.ndarray) -> float:
    a, b = float(np.sqrt(np.mean(x * x))), float(np.sqrt(np.mean(re * re)))
    return 20 * np.log10(a / b) if a > 0 and b > 0 else float("-inf")


def sources(circuit: str) -> dict[str, tuple[str, str]]:
    """{part name: (the value's key or "inline", its source text)} from the circuit file: the
    first parameter of each part that names a sourced value."""
    from varimu.circuit import spec

    c = spec.load_circuit(spec.circuit_path(circuit))
    pools = [c.values, c.controls, c.device_params, getattr(c, "derived", {}) or {}]
    out = {}
    for sec in c.sections:
        for pname, part in sec.get("parts", {}).items():
            for v in part.values():
                if isinstance(v, dict) and "source" in v:
                    out[pname] = ("inline", str(v["source"]))
                    break
                if isinstance(v, str):
                    hit = next((p[v] for p in pools if isinstance(p, dict) and v in p), None)
                    if isinstance(hit, dict) and "source" in hit:
                        out[pname] = (v, str(hit["source"]))
                        break
    return out


def source_for(name: str, srcs: Mapping[str, tuple[str, str]]) -> tuple[str, str]:
    """An element's part: its own name, else the longest part name it starts with (a macro's
    elements carry their part's name as a prefix)."""
    if name in srcs:
        return srcs[name]
    best = max((p for p in srcs if name.startswith(p)), key=len, default=None)
    return srcs[best] if best else ("", "")


def rank(
    ir: CircuitIR,
    x: np.ndarray,
    v_in: float,
    v_out: float,
    *,
    probe: str = "out",
    names: Sequence[str] | None = None,
    workers: int | None = None,
    keep_signals: int = 10,
    settings=None,
) -> list[dict]:
    """Every element's sensitivity, sorted by level (loudest first). The top `keep_signals`
    keep "s" and "y"; the rest only their numbers."""
    from varimu.sim.runner import default_jobs

    els = elements(ir)
    names = list(names) if names is not None else list(els)

    def one(n):
        r = sensitivity(ir, x, n, v_in, v_out, probe=probe, settings=settings)
        r.update(name=n, kind=type(els[n]).__name__, value=value_of(els[n]))
        return r

    with ThreadPoolExecutor(workers or default_jobs()) as ex:
        rows = list(ex.map(one, names))
    rows.sort(key=lambda r: -r["level_db"])
    for r in rows[keep_signals:]:
        r.pop("s", None)
        r.pop("y", None)
    return rows


def table_json(rows: Sequence[dict]) -> str:
    return json.dumps(
        [{k: v for k, v in r.items() if k not in ("s", "y")} for r in rows],
        indent=1,
        default=float,
    )
