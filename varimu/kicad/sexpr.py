"""S-expressions as KiCad writes them: nested lists of atoms, tab-indented."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sym:
    """An unquoted atom (a keyword: `yes`, `passive`, `line`)."""

    name: str


def num(x: float) -> str:
    """A coordinate or size: at most 4 decimals, no trailing zeros."""
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _atom(x) -> str:
    if isinstance(x, Sym):
        return x.name
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, int | float):
        return num(x)
    s = str(x).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'


def dumps(node: list, indent: int = 0) -> str:
    """One node: `(head atoms... children...)`; a child list goes on its own line,
    atoms stay on the head's line (KiCad's layout)."""
    head, *rest = node
    tabs = "\t" * indent
    atoms = [a for a in rest if not isinstance(a, list)]
    kids = [k for k in rest if isinstance(k, list)]
    line = tabs + "(" + " ".join([head.name, *(_atom(a) for a in atoms)])
    if not kids:
        return line + ")"
    if head.name == "pts":
        return line + " " + " ".join(dumps(k) for k in kids) + ")"
    body = "\n".join(dumps(k, indent + 1) for k in kids)
    return f"{line}\n{body}\n{tabs})"


def S(head: str, *rest) -> list:
    """A node with head `head` (an unquoted keyword)."""
    return [Sym(head), *rest]


Y, N = Sym("yes"), Sym("no")
