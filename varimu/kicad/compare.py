"""Two circuit IRs compared element by element, regardless of order.

The importer's promise (device builder B3): an imported circuit has the same sections
(by title), in each the same elements (by name, every field equal: nodes, values, the
tolerance draws), the same device models (by name, every parameter equal), the same
input, probes and title. Element and model order may differ: they reorder the
engines' unknowns, which moves results only at the solver's tolerance (measured in
docs/DEVICE_BUILDER_PLAN.md, B3).
"""

from __future__ import annotations

from varimu.circuit.ir import CircuitIR


def ir_differences(a: CircuitIR, b: CircuitIR, limit: int = 20) -> list[str]:
    """What differs between `a` and `b` beyond order (empty: equivalent)."""
    out: list[str] = []
    for f in ("title", "input_node", "probes", "version"):
        if getattr(a, f) != getattr(b, f):
            out.append(f"{f}: {getattr(a, f)!r} != {getattr(b, f)!r}")
    ma, mb = {m.name: m for m in a.models}, {m.name: m for m in b.models}
    for name in sorted(set(ma) | set(mb)):
        if name not in ma or name not in mb:
            out.append(f"model {name}: only in {'b' if name not in ma else 'a'}")
        elif ma[name] != mb[name]:
            out.append(f"model {name}: differs")
    sa, sb = {s.title: s for s in a.sections}, {s.title: s for s in b.sections}
    if set(sa) != set(sb):
        out.append(f"sections: {sorted(sa)} != {sorted(sb)}")
    for title in sorted(set(sa) & set(sb)):
        ea = {e.name: e for e in sa[title].elements}
        eb = {e.name: e for e in sb[title].elements}
        if len(ea) != len(sa[title].elements) or len(eb) != len(sb[title].elements):
            out.append(f"section {title}: element names repeat")
        for name in sorted(set(ea) | set(eb)):
            x, y = ea.get(name), eb.get(name)
            if x != y:
                out.append(f"{title}/{name}: {x} != {y}")
    return out[:limit] + ([f"... {len(out) - limit} more"] if len(out) > limit else [])
