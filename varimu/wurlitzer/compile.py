"""The 200A's reeds compiled for circuitsim (docs/WURLITZER_PLAN.md, WZ4): a component
version of kind `ep_reeds` that circuitsim's `wurli.rs` plays as a medium.

The keyboard's voices (`keyboard.Voice`, on `key.System`) as data, per key and per system
(the free reed, and the reed under the damper's felt; keys from `damper.undamped_from_key`
up have none):

- **The modes, halved** (as the Rhodes harp's, `varimu.rhodes.compile`): of each conjugate
  pair of the system's complex modes only the upper is kept, its outputs doubled, so every
  output is `Re(sum c_j z_j)` over the kept modes; the force's input `b` isn't doubled.
- **Outputs**: the strike point's displacement and velocity (the hammer's contact), the
  tip's displacement (the sleep test's bound) and the reed's height at the slot's Gauss
  points (`slices`, n_slices x modes, row-major: the pickup).
- **The reach** (the free system only): where a hammer thrown at a ringing reed starts,
  `key.contact`'s lowest the strike point can swing, `sum_i |cs_i| sqrt(q_i^2 + (q_i' /
  omega_i)^2)` over the free reed's real modes i. The free system is proportional, so each
  kept complex mode j is one real mode i: `q_i = Re(rq_j z_j)`, `q_i' / omega_i = Re(rv_j
  z_j)`, the rows `reach_q`, `reach_v` with |cs_i| in them.
- **The damper's switch**: the state moved to the other system's modes through the
  physical coordinates, `z_new = A z + B conj(z)`.

Per key also its blank (which field map), voicing, the slot's Gauss weights and its
capacitance at rest `c0_f` (the reference's own sum: dC = sum_s w_s c(h0 + y_s) - c0).
Once for all keys: each blank's field map c(z) as the reference's cubic spline in piecewise
polynomial form (`x` the breakpoints, `c` the 4 x (len(x) - 1) coefficients, row-major,
highest power first: scipy's PPoly; z held at the ends), the velocity law, the contact's
window, the sleep threshold, and every reed's standing capacitance summed (`standing_f`:
the circuit's CREEDS, `c_reeds_f`).

`compile_reeds()` builds the data; `save()` writes it as the component's next version when it
changed: `config/components/<name>/<N>.yaml` (`varimu.devices.versions`) naming
`<N>.reeds.json` by its sha256.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Any

import numpy as np
from scipy import linalg

from varimu.devices import versions
from varimu.rhodes import compile as hc
from varimu.wurlitzer import key as ky
from varimu.wurlitzer import keyboard as kb
from varimu.wurlitzer import spec as sp

FORMAT = 1
COMPONENT = "WURLI_REEDS"
KIND = "ep_reeds"
DATA_SUFFIX = ".reeds.json"

_c = hc._c


class _Modal:
    """A key.System's complex modes (eig of its A, as keyboard._Motion), halved."""

    def __init__(self, sysm: ky.System):
        lam, v = linalg.eig(sysm.a)
        self.sysm, self.lam, self.v, self.w = sysm, lam, v, linalg.inv(v)
        self.idx, self.factor = hc._halve(lam)

    def row(self, c: np.ndarray) -> np.ndarray:
        """A real output row c (over the physical state) on the kept modes, doubled."""
        return (c @ self.v)[self.idx] * self.factor


def _system(m: _Modal, reach: bool) -> dict[str, Any]:
    s = m.sysm
    out = {
        "modes": int(m.idx.size),
        "lam": _c(m.lam[m.idx]),
        "b": _c((m.w @ s.b)[m.idx]),
        "strike": _c(m.row(s.c_strike)),
        "strike_v": _c(m.row(s.c_strike_v)),
        "tip": _c(m.row(s.c_tip)),
        "slices": _c(np.array([m.row(r) for r in s.c_slices])),  # (n_slices, modes)
    }
    if reach:
        n = s.n
        cs = np.abs(s.c_strike[:n])
        rq = np.zeros(m.idx.size, complex)
        rv = np.zeros(m.idx.size, complex)
        for j, (col, f) in enumerate(zip(m.idx, m.factor, strict=True)):
            vec = m.v[:, col]
            i = int(np.argmax(np.abs(vec[:n])))
            rq[j] = f * vec[i] * cs[i]
            rv[j] = f * vec[n + i] * cs[i] / s.md.omega[i]
        out["reach_q"] = _c(rq)
        out["reach_v"] = _c(rv)
    return out


def _transfer(old: _Modal, new: _Modal) -> dict[str, Any]:
    """z_new = A z + B conj(z) over the kept modes (B's columns of real modes zero)."""
    w = new.w[new.idx]
    v = old.v[:, old.idx]
    a = w @ v
    b = w @ v.conj()
    b[:, np.abs(old.lam[old.idx].imag) <= 1e-12 * np.abs(old.lam[old.idx])] = 0.0
    return {"a": _c(a), "b": _c(b)}  # (new modes, old modes), row-major


def _key(n: int, name: str) -> dict[str, Any]:
    k = sp.key(n, name)
    cfg = sp.load(name)
    free = _Modal(ky.System(k))
    _check_proportional(free)
    fmap = sp.field(k)
    w = free.sysm.slice_w
    c0 = float(w @ fmap(np.full(w.size, k.voicing_m)))
    h = k.hammer
    out = {
        "key": n,
        "note": n + kb.MIDI_KEY_OFFSET,
        "note_hz": k.f_hz,
        "blank": sp.blank(n, cfg),
        "voicing_m": k.voicing_m,
        "slice_w": [float(x) for x in w],
        "c0_f": c0,
        "hammer": {
            "mass_kg": h.mass_kg,
            "stiffness": h.stiffness,
            "exponent": h.exponent,
            "hysteresis_s_m": h.hysteresis_s_m,
        },
        "free": _system(free, reach=True),
    }
    if k.damper_decay_db_s is not None:
        damp = _Modal(ky.System(k, damped=True))
        out["damped"] = _system(damp, reach=False)
        out["to_damped"] = _transfer(free, damp)
        out["to_free"] = _transfer(damp, free)
    return out


def _check_proportional(m: _Modal) -> None:
    """The reach's rows need each kept mode of the free system on one real mode."""
    n = m.sysm.n
    for col in m.idx:
        vec = np.abs(m.v[:n, col])
        if np.sort(vec)[-2] > 1e-9 * vec.max():
            raise ValueError("the free reed's modes aren't one real mode each")


def _field(fm) -> dict[str, Any]:
    sp_ = fm.spline
    return {
        "x": [float(v) for v in sp_.x],
        "c": [float(v) for v in np.asarray(sp_.c).ravel()],  # (4, len(x) - 1), row-major
        "z_range_m": list(fm.z_range_m),
    }


def compile_reeds(name: str = "200a", keys: list[int] | None = None) -> dict[str, Any]:
    """The reeds of instrument `name` as data (see the module docstring); `keys` a subset
    (tests), whose `standing_f` is still the whole keyboard's."""
    cfg = sp.load(name)
    n_keys = int(cfg["keyboard"]["keys"])
    keys = list(keys) if keys is not None else list(range(1, n_keys + 1))
    n_blanks = len(cfg["reed"]["blank_last_reed"])
    first_of = {sp.blank(n, cfg): n for n in range(n_keys, 0, -1)}
    fields = [_field(sp.field(sp.key(first_of[b], name))) for b in range(n_blanks)]
    ff, rng = sp.velocity_law(cfg)
    return {
        "format": FORMAT,
        "instrument": name,
        "keys": [_key(n, name) for n in keys],
        "fields": fields,
        "velocity": {"ff_speed_m_s": ff, "range_db": rng},
        "contact_window_s": kb.CONTACT_WINDOW_S,
        "sleep_m": kb.SLEEP_M,
        "standing_f": float(sp.reeds_f(name)),
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n"


def _yaml(data: dict[str, Any], data_file: str, sha: str, name: str) -> str:
    cfg_sha = hashlib.sha256((sp.WURLITZER_DIR / f"{data['instrument']}.yaml").read_bytes())
    keys = [k["key"] for k in data["keys"]]
    return (
        f"# Generated by varimu/wurlitzer/compile.py (scripts/compile_wurlitzer_reeds.py) on"
        f" {_dt.date.today().isoformat()}.\n"
        "# Don't edit by hand: change config/wurlitzer/ or varimu/wurlitzer/ and recompile.\n"
        f"name: {name}\n"
        f"kind: {KIND}\n"
        "source: \"the Wurlitzer 200A's reeds from physics (docs/WURLITZER_PLAN.md WZ1-WZ4): the\n"
        f"  instrument's values and their sources in config/wurlitzer/{data['instrument']}.yaml,\n"
        "  through varimu/wurlitzer/ (beam FE per reed, the hammer's felt, the damper, the\n"
        "  electrostatic field map per blank), compiled to the keyboard's complex modes by\n"
        '  varimu/wurlitzer/compile.py"\n'
        "instrument:\n"
        f"  file: config/wurlitzer/{data['instrument']}.yaml\n"
        f"  sha256: {cfg_sha.hexdigest()}\n"
        "data:\n"
        f"  file: {data_file}\n"
        f"  sha256: {sha}\n"
        f"keys: [{keys[0]}, {keys[-1]}]\n"
        f"standing_f: {data['standing_f']!r}\n"
    )


def save(name: str = COMPONENT, data: dict[str, Any] | None = None) -> versions.Ref | None:
    """Save the compiled reeds as component `name`'s next version, unless the latest
    version's data is the same (None then)."""
    data = data or compile_reeds()
    text = _dump(data)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    have = versions.versions(name)
    if have:
        latest = load_data(f"{name}@{have[-1]}")
        if _dump(latest) == text:
            return None
    n = (have or [0])[-1] + 1
    data_file = f"{n}{DATA_SUFFIX}"
    folder = versions.COMPONENT_DIR / name.lower()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / data_file).write_text(text, encoding="utf-8", newline="\n")
    ref = versions.save(name, _yaml(data, data_file, sha, name))
    if ref.version != n:
        raise RuntimeError(f"saved {ref}, expected version {n}")
    return ref


def load_data(ref: str) -> dict[str, Any]:
    """A reeds version's compiled data, checked against the sha256 its version names."""
    import yaml

    r, text = versions.read_text(ref)
    d = yaml.safe_load(text)
    if d.get("kind") != KIND:
        raise ValueError(f"{r} is not a reed keyboard of kind {KIND} (kind {d.get('kind')!r})")
    path = versions.COMPONENT_DIR / r.folder / d["data"]["file"]
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != d["data"]["sha256"]:
        raise versions.VersionError(
            f"{r}'s data {path.name} doesn't match the sha256 its version names"
        )
    return json.loads(raw)
