"""The harp compiled for circuitsim (docs/RHODES_PLAN.md, RH3): a component version of kind
`ep_harp` that circuitsim's `harp.rs` plays as a medium.

The live tier (`key._System`, `tier="modes"`) as data, per key and per system (the free
tine, and the tine under the damper's felt):

- **The modes, halved.** A real system's complex modes come in conjugate pairs whose
  coordinates stay conjugate (the state is real), so only the upper one of each pair is
  kept, with its outputs doubled (the real ones once): every output is `Re(sum c_j z_j)`
  over the kept modes, `c` with the factor in it. The force's input `b` isn't doubled.
- **Outputs**: the strike point's displacement and velocity (the contact's), the tip's
  displacement and velocity (the pickup's).
- **The arc** (the tip's pull-back, `1/2 int w'^2`): a quadratic form in the slopes at the
  tine's quadrature points, reduced to its leading `r` directions: with `M = sqrt(w) Q`
  (the weighted slopes over the modes), each mode's column scaled by how far a strike
  moves it (`|b_j| / |lambda_j|`: a unit impulse's displacement), and `U_r` the leading
  left singular vectors of `[Re M, -Im M]` so scaled (singular values above
  `arc_rank_tol` of the first), `p = Re(P z)` with `P = U_r' M`; then `arc = |p|^2 / 2`
  and `arc' = p . Re(P Lambda z)` (a mode's slope rate is lambda times its slope). Exact
  at full rank. At the default tolerance the rank is 3-4 and a struck key's EMF is within
  -114 dB of the full forms' (keys 8-80 at velocity 127, 2026-11-04; rank 2 was -76 dB).
- **The damper's switch**: the state moved to the other system's modes through the
  physical coordinates, `z_new = A z + B conj(z)` (B's columns zero for real modes).

The pickup's flux map (one for every key: their pickups are alike) as its bicubic
B-spline (`pickup.FluxMap.spline`'s knots and coefficients, FITPACK's order: the y basis
outer, the arc's inner), the velocity law, the wiring's weights, the contact's window, the
sleep threshold and the harp's coils.

`compile_harp()` builds the data; `save()` writes it as the component's next version when
it changed: `config/components/<name>/<N>.yaml` (`varimu.devices.versions`, its sha256 in
versions.lock) naming `<N>.harp.json` by its sha256, so the version pins its data.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np

from varimu.devices import versions
from varimu.rhodes import harp, spec
from varimu.rhodes import key as ky
from varimu.rhodes import pickup as pk

FORMAT = 1
ARC_RANK_TOL = 1e-2  # the arc's directions kept: singular values over the first's
COMPONENT = "MK1_HARP"
DATA_SUFFIX = ".harp.json"

# The harp's coils as the circuit sees them (the manual's Fig. 10-4 wiring): its output
# impedance, read at 1 kHz (provisional), with the coils' DC resistance.
HARP_IMPEDANCE_OHM = 2500.0
HARP_IMPEDANCE_HZ = 1000.0


def _halve(lam: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The kept modes' indices (each pair's upper one by frequency, then the real ones)
    and their output factors (2, 1)."""
    real = np.abs(lam.imag) <= 1e-12 * np.abs(lam)
    upper = np.flatnonzero(~real & (lam.imag > 0))
    lower = np.flatnonzero(~real & (lam.imag < 0))
    if upper.size != lower.size or not np.allclose(
        np.sort_complex(lam[upper]), np.sort_complex(lam[lower].conj()), rtol=1e-9
    ):
        raise ValueError("the modes don't come in conjugate pairs")
    upper = upper[np.argsort(lam[upper].imag, kind="stable")]
    idx = np.concatenate([upper, np.flatnonzero(real)])
    factor = np.concatenate([np.full(upper.size, 2.0), np.ones(int(real.sum()))])
    return idx, factor


def _c(v: np.ndarray) -> dict[str, list[float]]:
    v = np.asarray(v, complex)
    return {"re": v.real.ravel().tolist(), "im": v.imag.ravel().tolist()}


def _system(s: ky._System, arc_tol: float) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    idx, factor = _halve(s.lam)
    m = np.sqrt(s.w)[:, None] * s.q_map
    mw = m * (np.abs(s.b) / np.maximum(np.abs(s.lam), 1.0))[None, :]
    u, sv, _ = np.linalg.svd(np.hstack([mw.real, -mw.imag]), full_matrices=False)
    r = max(1, int(np.sum(sv > arc_tol * sv[0])))
    p = u[:, :r].T @ m
    out = {
        "modes": int(idx.size),
        "lam": _c(s.lam[idx]),
        "b": _c(s.b[idx]),
        "strike": _c(s.c_strike[idx] * factor),
        "strike_v": _c(s.c_strike_v[idx] * factor),
        "tip": _c(s.c_tip[idx] * factor),
        "tip_v": _c(s.c_tip_v[idx] * factor),
        "arc_rank": r,
        "arc": _c(p[:, idx] * factor),  # (r, modes), row-major
    }
    return out, idx, factor


def _transfer(old: ky._System, old_idx, new: ky._System, new_idx) -> dict[str, Any]:
    """z_new = A z + B conj(z) over the kept modes (B's columns of real modes zero)."""
    w = new.from_phys[new_idx]
    v = old.to_phys[:, old_idx]
    a = w @ v
    b = w @ v.conj()
    b[:, np.abs(old.lam[old_idx].imag) <= 1e-12 * np.abs(old.lam[old_idx])] = 0.0
    return {"a": _c(a), "b": _c(b)}  # (new modes, old modes), row-major


def _key(job: tuple[int, str, float]) -> dict[str, Any]:
    n, name, arc_tol = job
    k = spec.key(n, name)
    free = ky._System(k, "modes")
    damp = ky._System(k, "modes", k.damped)
    f, fi, _ = _system(free, arc_tol)
    d, di, _ = _system(damp, arc_tol)
    h = k.hammer
    return {
        "key": n,
        "note": n + harp.MIDI_KEY_OFFSET,
        "note_hz": k.note_hz,
        "weight": 1.0 / harp.group_size(n),
        "hammer": {
            "mass_kg": h.mass_kg,
            "stiffness": h.stiffness,
            "exponent": h.exponent,
            "hysteresis_s_m": h.hysteresis_s_m,
        },
        "free": f,
        "damped": d,
        "to_damped": _transfer(free, fi, damp, di),
        "to_free": _transfer(damp, di, free, fi),
    }


def _flux(fm: pk.FluxMap) -> dict[str, Any]:
    tx, ty, c = fm.spline.tck
    kx, ky_ = fm.spline.degrees
    if (kx, ky_) != (3, 3):
        raise ValueError(f"the flux map's spline is of degrees {(kx, ky_)}, not bicubic")
    return {
        "ty": [float(t) for t in tx],  # the tip's height (m): the outer basis
        "tg": [float(t) for t in ty],  # the arc's pull-back (m): the inner
        "c": [float(v) for v in c],  # weber-turns, (len(ty) - 4) x (len(tg) - 4)
        "y_range_m": list(fm.y_range_m),
        "dg_range_m": [float(fm.dg_m[0]), float(fm.dg_m[-1])],
    }


def compile_harp(
    name: str = "mk1",
    keys: range = spec.KEYS_73,
    arc_tol: float = ARC_RANK_TOL,
    workers: int = 6,
) -> dict[str, Any]:
    """The harp of instrument `name` as data (see the module docstring)."""
    pickups = {spec.key(n, name).pickup for n in keys}
    if len(pickups) != 1:
        raise ValueError("the keys' pickups differ: the harp has one flux map")
    (p,) = pickups
    flux = pk.flux_map(p, workers=workers)
    cfg = spec.load(name)
    jobs = [(n, name, arc_tol) for n in keys]
    if workers > 1:
        # one BLAS thread a worker: six processes each on every core ran ~10x slower
        blas = ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS")
        saved = {v: os.environ.get(v) for v in blas}
        os.environ.update({v: "1" for v in blas})
        try:
            with ProcessPoolExecutor(workers) as pool:
                ks = list(pool.map(_key, jobs))
        finally:
            for v, old in saved.items():
                if old is None:
                    os.environ.pop(v, None)
                else:
                    os.environ[v] = old
    else:
        ks = [_key(j) for j in jobs]
    # a group of g coils in parallel is coil / g; each key is one of its group's g
    r_ohm = sum(p.coil_ohm / harp.group_size(n) ** 2 for n in keys)
    x = float(np.sqrt(max(HARP_IMPEDANCE_OHM**2 - r_ohm**2, 0.0)))
    return {
        "format": FORMAT,
        "instrument": name,
        "keys": ks,
        "flux": _flux(flux),
        "voicing_m": p.voicing_m,
        "velocity": {
            "ff_speed_m_s": harp.ff_speed_m_s(name, flux),
            "range_db": cfg["velocity"]["range_db"],
        },
        "contact_window_s": harp.CONTACT_WINDOW_S,
        "sleep_m": harp.SLEEP_M,
        "arc_rank_tol": arc_tol,
        "coils": {
            "r_ohm": r_ohm,
            "l_h": x / (2 * np.pi * HARP_IMPEDANCE_HZ),
        },
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n"


def _yaml(data: dict[str, Any], data_file: str, sha: str, name: str) -> str:
    cfg_sha = hashlib.sha256((spec.RHODES_DIR / f"{data['instrument']}.yaml").read_bytes())
    keys = [k["key"] for k in data["keys"]]
    coils = data["coils"]
    p = spec.key(keys[0], data["instrument"]).pickup
    return (
        f"# Generated by varimu/rhodes/compile.py (scripts/compile_rhodes_harp.py) on"
        f" {_dt.date.today().isoformat()}.\n"
        "# Don't edit by hand: change config/rhodes/ or varimu/rhodes/ and recompile.\n"
        f"name: {name}\n"
        "kind: ep_harp\n"
        "source: \"the Rhodes Mark I's harp from physics (docs/RHODES_PLAN.md RH1-RH3): the\n"
        f"  instrument's values and their sources in config/rhodes/{data['instrument']}.yaml,\n"
        "  through varimu/rhodes/ (beam FE per key, the hammer's contact, the 2D pickup map),\n"
        "  compiled to the live tier's complex modes by varimu/rhodes/compile.py\"\n"
        "instrument:\n"
        f"  file: config/rhodes/{data['instrument']}.yaml\n"
        f"  sha256: {cfg_sha.hexdigest()}\n"
        "data:\n"
        f"  file: {data_file}\n"
        f"  sha256: {sha}\n"
        f"keys: [{keys[0]}, {keys[-1]}]\n"
        f"arc_rank_tol: {data['arc_rank_tol']!r}\n"
        "coils:\n"
        f"  r_ohm: {coils['r_ohm']!r}\n"
        f"  l_h: {coils['l_h']!r}\n"
        f'  source: "derived: {p.coil_ohm:g} ohm coils (config/rhodes/{data["instrument"]}.yaml)'
        " in the manual's\n"
        "    Fig. 10-4 arrangement (pickups 1-4 a group, then threes, the groups in series);\n"
        "    inductance: the manual (ch.10) gives the harp's output impedance as"
        f" ~{HARP_IMPEDANCE_OHM:g} ohm,\n"
        f"    read at {HARP_IMPEDANCE_HZ:g} Hz (provisional) with the coils' DC resistance,"
        " the rest reactance\n"
        "    (Wheeler's short-coil formula on the provisional bobbin and 2800 turns: 0.034 H"
        " a coil,\n"
        '    against 0.041 H from the manual)"\n'
    )


def save(name: str = COMPONENT, data: dict[str, Any] | None = None) -> versions.Ref | None:
    """Save the compiled harp as component `name`'s next version, unless the latest
    version's data is the same (None then)."""
    data = data or compile_harp()
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
    """A harp version's compiled data, checked against the sha256 its version names."""
    import yaml

    r, text = versions.read_text(ref)
    d = yaml.safe_load(text)
    if d.get("kind") != "ep_harp":
        raise ValueError(f"{r} is not a harp (kind {d.get('kind')!r})")
    path = versions.COMPONENT_DIR / r.folder / d["data"]["file"]
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != d["data"]["sha256"]:
        raise versions.VersionError(
            f"{r}'s data {path.name} doesn't match the sha256 its version names"
        )
    return json.loads(raw)
