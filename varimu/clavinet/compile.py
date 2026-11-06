"""The Clavinet's strings compiled for circuitsim (docs/CLAVINET_PLAN.md, CL3): a component
version of kind `clav_strings` that circuitsim's `clavinet.rs` plays as a medium, and that
`varimu.clavinet.live` (the live tier's Python twin) plays the same way.

Per key, from `fit.params(n)` with `f_cut_hz` set to the live band (`LIVE_BAND_HZ`):

- **The released system** (no key: the whole string, the yarn on its short side): its
  modes, **halved** as the Rhodes harp's are (`varimu.rhodes.compile`): of each conjugate
  pair only the upper one is kept, every output row doubled for it (real modes once), so
  an output is `Re(sum c_j z_j)`. Kept: the eigenvalues, the modal inputs of a force on
  the anvil point's y and x (not doubled), and output rows for the anvil point (y, x, vy,
  vx: the contacts') and each pickup (y and vy, the displacement averaged over its bar as
  `note.py` reads it).
- **The held system** (the pinch linearized about the static press, the tangent its last
  coordinate): its eigenvalues, the pickup rows, the tangent's rows (its position and
  velocity: where the release starts it), and the static press's pickup y and tangent
  position.
- **The switch at the end of the strike** (`to_held`): `z_h = A z_r + B conj(z_r) + t_z
  zt + t_v vt + c`, the released modal state and the tangent's position and velocity onto
  the held modes about the static press (`c` the press). B's columns are zero for real
  modes. This is `note.py`'s `held.to_modal(... - us)` as matrices.
- **The release** (`release`): `z_r = A z_h + B conj(z_h) + c` back onto every released
  mode, the press included (`c`); the release's contacts then run on them (`note.py`).
- **The contacts** (the strike's and the release's): the tangent's mass, travel, hold
  force and the key's return force; the rubber's Hunt-Crossley law (K, p, alpha) and its
  sideways grip (spring and dashpot); the anvil's spring, dashpot, gap and tilt.
- **The pickups**: per pickup, dLambda/dh(h) on a uniform grid of the string's height
  over the bar (`pickup.linkage_map`'s spline at dx = 0, the level factor
  `note.level_factor` folded in), linear between its points; the side (below / above) and
  the clearance: `h = clearance + sgn y` clipped into the map, `emf = -dL/dh(h) sgn vy`.
  This is `pickup.emf` exactly when the map doesn't depend on the string's place across
  the bar (dLambda/dx = 0): true of the "along" model, the default; the compile refuses a
  map that sees x (`DX_SLOPE_MAX`), whose x the live tier doesn't read.
- **Bend** (aftertouch): cents against the hold force (`fit.bend_cents`) on a grid from
  the tuned hold force to the bend target's largest force (`anvil.bend_force_n`).

Instrument-wide: the velocity law ([G13] 3.2, linear MIDI 1-127 to the tangent's speed),
the contacts' numerics (the strike's window and settle rule, the release's open rule, the
cap: `note.py`'s) and the sleep threshold.

**Format.** `<N>.strings.json` (the header: scalars, shapes, and every array's place in
the sidecar) and `<N>.strings.bin` (little-endian, the arrays back to back, each on 8
bytes; a complex array is its real part then its imaginary part; the four transfer
matrices float32, `SINGLE`, everything else float64). The version
`config/components/<name>/<N>.yaml` pins both by sha256 (`varimu.devices.versions`), and
the header names the sidecar's sha256 and length again.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from varimu.clavinet import fit, note, pickup, spec, strings
from varimu.devices import versions

FORMAT = 1
COMPONENT = "D6_STRINGS"
HEADER_SUFFIX = ".strings.json"
BINARY_SUFFIX = ".strings.bin"

#: The live band: each key's basis keeps the segments' modes up to it.
LIVE_BAND_HZ = 12000.0
#: The pickups' tables: points over the linkage map's height range.
TABLE_POINTS = 4096
#: The arrays the sidecar keeps in float32 (the switches' transfers: 93% of the data; their
#: rounding moves a note's EMF by ~-120 dB against float64's -130).
SINGLE = frozenset({"to_held.a", "to_held.b", "release.a", "release.b"})
#: The largest |dLambda/dx| against |dLambda/dh| the live tier's x-blind pickups accept.
DX_SLOPE_MAX = 1e-9
#: Bend (aftertouch) grid: forces from the tuned hold force to the bend's largest.
BEND_POINTS = 9
#: The contacts' numerics (note.py's): the strike's minimum window and settle rule, the
#: release's (open for `OPEN_S` past `OPEN_WINDOW_S`), the cap on either.
STRIKE_WINDOW_S = 0.010
SETTLE_S = 0.002
OPEN_WINDOW_S = 0.002
OPEN_S = 0.001
CONTACT_MAX_S = 0.06
#: A voice sleeps when its EMF's bound falls under this (V, both pickups).
SLEEP_V = 1e-8

R_ROWS = (
    "anvil_y",
    "anvil_x",
    "anvil_vy",
    "anvil_vx",
    "centre_y",
    "centre_vy",
    "bridge_y",
    "bridge_vy",
)
H_ROWS = R_ROWS[4:]
PICKUPS = note.PICKUPS


def _halve(lam: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The kept modes (each pair's upper one by frequency, then the real ones by decay)
    and their output factors (2, 1)."""
    real = _real_mask(lam)
    upper = np.flatnonzero(~real & (lam.imag > 0))
    lower = np.flatnonzero(~real & (lam.imag < 0))
    if upper.size != lower.size or not np.allclose(
        np.sort_complex(lam[upper]), np.sort_complex(lam[lower].conj()), rtol=1e-9
    ):
        raise ValueError("the modes don't come in conjugate pairs")
    upper = upper[np.argsort(lam[upper].imag, kind="stable")]
    reals = np.flatnonzero(real)
    reals = reals[np.argsort(-lam[reals].real, kind="stable")]
    idx = np.concatenate([upper, reals])
    factor = np.concatenate([np.full(upper.size, 2.0), np.ones(reals.size)])
    return idx, factor


def _real_mask(lam: np.ndarray) -> np.ndarray:
    return np.abs(lam.imag) <= 1e-12 * np.abs(lam)


def _transfer(w_new: np.ndarray, sel: np.ndarray, v_old: np.ndarray, lam_old: np.ndarray):
    """(A, B) with z_new = A z + B conj(z): w_new's kept rows, `sel` (the old physical
    state into the new's), v_old's kept columns."""
    a = w_new @ (sel @ v_old)
    b = w_new @ (sel @ v_old.conj())
    b[:, _real_mask(lam_old)] = 0.0
    return a, b


def _tables(p: strings.Params, name: str) -> dict[str, Any]:
    cfg = spec.load(name)
    pks = pickup.pickups(name)
    g = p.geom
    mu_r = cfg["steel"]["mu_r"]
    scale = note.level_factor(name)
    out = {}
    for w in PICKUPS:
        pk = pks[w]
        lmap = pickup.linkage_map(pk, g.n, g.d_magnetic_m, mu_r)
        h = np.linspace(lmap.h_m[0], lmap.h_m[-1], TABLE_POINTS)
        dxs = np.linspace(lmap.dx_m[0], lmap.dx_m[-1], 21)
        gx, gh = np.meshgrid(dxs, h, indexing="ij")
        slope_h = np.max(np.abs(lmap(gx, gh, dh=1)))
        slope_x = np.max(np.abs(lmap(gx, gh, ddx=1)))
        if slope_x > DX_SLOPE_MAX * slope_h:
            raise ValueError(
                f"key {g.n}, {w} pickup: its map sees the string's place across the bar"
                f" (|dL/dx| {slope_x:.3g} against |dL/dh| {slope_h:.3g}); the live tier"
                " reads y only (pickup model 'along')"
            )
        dh = scale * lmap(np.zeros_like(h), h, dh=1)
        out[w] = {
            "sgn": 1.0 if pk.side == "below" else -1.0,
            "clearance_m": float(pk.clearance_m),
            "h_lo_m": float(h[0]),
            "h_hi_m": float(h[-1]),
            "dmax_dh": float(np.max(np.abs(dh))),
            "dh": dh,
        }
    return out


def _key(job: tuple[int, str, float]) -> dict[str, Any]:
    """Key n compiled: its scalars, and its arrays as numpy (complex or real)."""
    n, name, band = job
    cfg = spec.load(name)
    p = replace(fit.params(n, name), f_cut_hz=band)
    lay = strings.layout(p)
    rel = strings.system(p, False, lay)
    held = strings.system(p, True, lay)
    ns, nh = lay.n_string, held.n
    width = cfg["pickups"]["bar_width_m"]
    us = strings.static(p)

    def on(r: np.ndarray, vel: bool, total: int) -> np.ndarray:
        """A row r on the coordinates' displacements (vel: velocities) of a state of
        `total` coordinates."""
        out = np.zeros(2 * total)
        o = total if vel else 0
        out[o : o + r.size] = r
        return out

    ys = {
        w: strings.point_rows(p, lay, 0, note.pickup_distance_m(w, n, name), width) for w in PICKUPS
    }

    # --- released ---
    ri, rf = _halve(rel.lam)
    vr = rel.v[:, ri]
    e_ay, e_ax = np.zeros(ns), np.zeros(ns)
    e_ay[lay.ua(0)] = 1.0
    e_ax[lay.ua(1)] = 1.0
    r_phys = [on(e_ay, False, ns), on(e_ax, False, ns), on(e_ay, True, ns), on(e_ax, True, ns)]
    for w in PICKUPS:
        r_phys += [on(ys[w], False, ns), on(ys[w], True, ns)]
    r_rows = (np.array(r_phys) @ vr) * rf
    b_y = rel.input(lay.ua(0))[ri]
    b_x = rel.input(lay.ua(1))[ri]

    # --- held ---
    hi, hf = _halve(held.lam)
    vh = held.v[:, hi]
    h_phys = []
    for w in PICKUPS:
        h_phys += [on(ys[w], False, nh), on(ys[w], True, nh)]
    h_rows = (np.array(h_phys) @ vh) * hf
    e_t = np.zeros(nh)
    e_t[nh - 1] = 1.0
    t_rows = (np.array([on(e_t, False, nh), on(e_t, True, nh)]) @ vh) * hf
    static = {w: float(ys[w] @ us[:ns]) for w in PICKUPS}

    # --- the switches through the physical coordinates ---
    # released (u_s, v_s) -> held (u_s, zt, v_s, vt): the string's coordinates
    sel_rh = np.zeros((2 * nh, 2 * ns))
    sel_rh[:ns, :ns] = np.eye(ns)
    sel_rh[nh : nh + ns, ns:] = np.eye(ns)
    wh = held.w[hi]
    th_a, th_b = _transfer(wh, sel_rh, vr, rel.lam[ri])
    t_z = wh[:, ns]
    t_v = wh[:, nh + ns]
    t_c = -wh[:, :nh] @ us
    # held -> released (the tangent's coordinates dropped), the press added back
    wr = rel.w[ri]
    rr_a, rr_b = _transfer(wr, sel_rh.T, vh, held.lam[hi])
    rr_c = wr[:, :ns] @ us[:ns]

    # --- bend ---
    an = cfg["anvil"]
    forces = np.linspace(p.hold_force_n, float(an["bend_force_n"][1]), BEND_POINTS)
    cents = [fit.bend_cents(p, float(f)) for f in forces]

    tables = _tables(p, name)
    scalars = {
        "key": n,
        "note": spec.midi_note(n, cfg),
        "note_hz": float(p.geom.f_hz),
        "wound": bool(p.geom.wound),
        "coords": {"released": ns, "held": nh},
        "contact": {
            "tangent_mass_kg": float(p.tangent_mass_kg),
            "travel_m": float(cfg["tangent"]["travel_m"]),
            "hold_force_n": float(p.hold_force_n),
            "return_force_n": float(cfg["tangent"]["return_force_n"]),
            "rubber_k": float(p.rubber_k),
            "rubber_p": float(p.rubber_p),
            "rubber_alpha_s_m": float(p.rubber_alpha_s_m),
            "anvil_k_n_m": float(p.anvil_k_n_m),
            "anvil_c_ns_m": float(p.anvil_c_ns_m),
            "anvil_gap_m": float(p.anvil_gap_m),
            "tilt_rad": float(p.tilt_rad),
            "grip_k_n_m": float(p.grip_k_n_m),
            "grip_c_ns_m": float(p.grip_c_ns_m),
        },
        "static_y_m": static,
        "static_tangent_m": float(us[nh - 1]),
        "bend": {"forces_n": forces.tolist(), "cents": cents},
        "pickups": {w: {k: v for k, v in tables[w].items() if k != "dh"} for w in PICKUPS},
    }
    arrays = {
        "released.lam": rel.lam[ri],
        "released.b_y": b_y,
        "released.b_x": b_x,
        "released.rows": r_rows,
        "held.lam": held.lam[hi],
        "held.rows": h_rows,
        "held.tangent": t_rows,
        "to_held.a": th_a,
        "to_held.b": th_b,
        "to_held.t_z": t_z,
        "to_held.t_v": t_v,
        "to_held.c": t_c,
        "release.a": rr_a,
        "release.b": rr_b,
        "release.c": rr_c,
    }
    for w in PICKUPS:
        arrays[f"tables.{w}.dh"] = tables[w]["dh"]
    return {"scalars": scalars, "arrays": arrays}


def compile_strings(
    name: str = "d6",
    keys: range | list[int] | None = None,
    band_hz: float = LIVE_BAND_HZ,
    workers: int = 6,
) -> dict[str, Any]:
    """The strings of instrument `name` as data: {"header": ..., "arrays": {key: {...}}}
    (the arrays numpy; `pack` lays them out)."""
    cfg = spec.load(name)
    keys = keys or range(1, int(cfg["tuning"]["keys"]) + 1)
    fit.globals_(name)  # the global fits once, before the workers read their cache
    note.level_factor(name)
    jobs = [(n, name, band_hz) for n in keys]
    if workers > 1:
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
    lo, hi = cfg["tangent"]["velocity_range_m_s"]
    header = {
        "format": FORMAT,
        "instrument": name,
        "live_band_hz": band_hz,
        "velocity": {"lo_m_s": float(lo), "hi_m_s": float(hi)},
        "pressure": {"max_force_n": float(cfg["anvil"]["bend_force_n"][1])},
        "contact": {
            "strike_window_s": STRIKE_WINDOW_S,
            "settle_s": SETTLE_S,
            "open_window_s": OPEN_WINDOW_S,
            "open_s": OPEN_S,
            "max_s": CONTACT_MAX_S,
        },
        "sleep_v": SLEEP_V,
        "table_points": TABLE_POINTS,
        "r_rows": list(R_ROWS),
        "h_rows": list(H_ROWS),
        "keys": [k["scalars"] for k in ks],
    }
    return {"header": header, "arrays": {k["scalars"]["key"]: k["arrays"] for k in ks}}


def pack(data: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    """The header with every array's place ({"at": byte offset, "shape": [...], "complex":
    bool, "dtype": "f4" | "f8"} under each key's "arrays") and the sidecar's bytes
    (little-endian; the transfers `SINGLE` float32, the rest float64)."""
    header = json.loads(json.dumps(data["header"]))
    chunks: list[bytes] = []
    at = 0
    for kd in header["keys"]:
        places = {}
        for field, arr in data["arrays"][kd["key"]].items():
            arr = np.asarray(arr)
            cplx = np.iscomplexobj(arr)
            dtype = "f4" if field in SINGLE else "f8"
            parts = [arr.real, arr.imag] if cplx else [arr]
            places[field] = {
                "at": at,
                "shape": list(arr.shape),
                "complex": bool(cplx),
                "dtype": dtype,
            }
            for part in parts:
                b = np.ascontiguousarray(part, dtype="<" + dtype).tobytes()
                chunks.append(b)
                at += len(b)
            pad = -at % 8  # every array starts on 8 bytes
            chunks.append(b"\0" * pad)
            at += pad
        kd["arrays"] = places
    return header, b"".join(chunks)


def _dump(header: dict[str, Any]) -> str:
    return json.dumps(header, separators=(",", ":"), allow_nan=False) + "\n"


def unpack(header: dict[str, Any], blob: bytes) -> dict[int, dict[str, np.ndarray]]:
    """Each key's arrays from the sidecar (numpy float64 / complex128)."""
    out = {}
    for kd in header["keys"]:
        arrs = {}
        for field, pl in kd["arrays"].items():
            size = int(np.prod(pl["shape"])) if pl["shape"] else 1
            dt = np.dtype("<" + pl["dtype"])
            n = 2 * size if pl["complex"] else size
            flat = np.frombuffer(blob, dtype=dt, count=n, offset=pl["at"]).astype(float)
            a = flat[:size].reshape(pl["shape"])
            if pl["complex"]:
                a = a + 1j * flat[size:].reshape(pl["shape"])
            arrs[field] = np.array(a)
        out[kd["key"]] = arrs
    return out


def _yaml(header: dict, files: dict[str, tuple[str, str]], name: str) -> str:
    cfg_sha = hashlib.sha256((spec.CLAVINET_DIR / f"{header['instrument']}.yaml").read_bytes())
    keys = [k["key"] for k in header["keys"]]
    (hf, hs), (bf, bs) = files["header"], files["binary"]
    return (
        f"# Generated by varimu/clavinet/compile.py (scripts/compile_clavinet_strings.py) on"
        f" {_dt.date.today().isoformat()}.\n"
        "# Don't edit by hand: change config/clavinet/ or varimu/clavinet/ and recompile.\n"
        f"name: {name}\n"
        "kind: clav_strings\n"
        "source: \"the Hohner Clavinet D6's strings from physics (docs/CLAVINET_PLAN.md\n"
        "  CL1-CL3): the instrument's values and their sources in\n"
        f"  config/clavinet/{header['instrument']}.yaml,\n"
        "  through varimu/clavinet/ (substructured stiff strings in two planes, the tangent's\n"
        "  strike and hold, the release, the bar pickups' map), compiled to the live tier's\n"
        '  complex modes by varimu/clavinet/compile.py"\n'
        "instrument:\n"
        f"  file: config/clavinet/{header['instrument']}.yaml\n"
        f"  sha256: {cfg_sha.hexdigest()}\n"
        "data:\n"
        f"  file: {hf}\n"
        f"  sha256: {hs}\n"
        "binary:\n"
        f"  file: {bf}\n"
        f"  sha256: {bs}\n"
        f"keys: [{keys[0]}, {keys[-1]}]\n"
        f"live_band_hz: {header['live_band_hz']!r}\n"
    )


def save(name: str = COMPONENT, data: dict[str, Any] | None = None) -> versions.Ref | None:
    """Save the compiled strings as component `name`'s next version, unless the latest
    version's data is the same (None then)."""
    data = data or compile_strings()
    header, blob = pack(data)
    bin_sha = hashlib.sha256(blob).hexdigest()
    have = versions.versions(name)
    if have and _same(f"{name}@{have[-1]}", header, bin_sha):
        return None
    n = (have or [0])[-1] + 1
    folder = versions.COMPONENT_DIR / name.lower()
    folder.mkdir(parents=True, exist_ok=True)
    bf, hf = f"{n}{BINARY_SUFFIX}", f"{n}{HEADER_SUFFIX}"
    header["binary"] = {"file": bf, "sha256": bin_sha, "bytes": len(blob)}
    text = _dump(header)
    (folder / bf).write_bytes(blob)
    (folder / hf).write_text(text, encoding="utf-8", newline="\n")
    hs = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ref = versions.save(name, _yaml(header, {"header": (hf, hs), "binary": (bf, bin_sha)}, name))
    if ref.version != n:
        raise RuntimeError(f"saved {ref}, expected version {n}")
    return ref


def _same(ref: str, header: dict[str, Any], bin_sha: str) -> bool:
    """Whether version `ref` holds this compile (its sidecar's hash and the header
    without its own file names)."""
    have, _ = load_header(ref)
    if have["binary"]["sha256"] != bin_sha:
        return False
    a = {k: v for k, v in have.items() if k != "binary"}
    return _dump(a) == _dump(header)


def is_current(ref: str, data: dict[str, Any]) -> bool:
    header, blob = pack(data)
    return _same(ref, header, hashlib.sha256(blob).hexdigest())


def files(ref: str) -> tuple[Path, Path, dict[str, Any]]:
    """(header path, sidecar path, the version's YAML) of strings version `ref`, both
    files checked against the sha256s the version names."""
    import yaml

    r, text = versions.read_text(ref)
    d = yaml.safe_load(text)
    if d.get("kind") != "clav_strings":
        raise ValueError(f"{r} is not a Clavinet's strings (kind {d.get('kind')!r})")
    folder = versions.COMPONENT_DIR / r.folder
    hp, bp = folder / d["data"]["file"], folder / d["binary"]["file"]
    raw = hp.read_text(encoding="utf-8").replace("\r\n", "\n")
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != d["data"]["sha256"]:
        raise versions.VersionError(f"{r}'s data {hp.name} doesn't match its sha256")
    return hp, bp, d


def load_header(ref: str) -> tuple[dict[str, Any], Path]:
    hp, bp, _ = files(ref)
    return json.loads(hp.read_text(encoding="utf-8")), bp


def load_data(ref: str) -> tuple[dict[str, Any], dict[int, dict[str, np.ndarray]]]:
    """A strings version's header and arrays, the sidecar checked against its sha256."""
    hp, bp, d = files(ref)
    header = json.loads(hp.read_text(encoding="utf-8"))
    blob = bp.read_bytes()
    if hashlib.sha256(blob).hexdigest() != d["binary"]["sha256"]:
        raise versions.VersionError(f"{ref}'s sidecar {bp.name} doesn't match its sha256")
    return header, unpack(header, blob)


def from_compiled(data: dict[str, Any]) -> tuple[dict[str, Any], dict[int, dict[str, np.ndarray]]]:
    """A compile's (header, arrays) as `load_data` gives them (through the sidecar's
    layout, its float32 transfers included: the twin plays the same numbers either way)."""
    header, blob = pack(data)
    return header, unpack(header, blob)


_CHECKED: dict[tuple[str, int, int], str] = {}


def ir_data(ref: str) -> tuple[str, str]:
    """(the header's path relative to the repository's root, forward slashes; the sidecar's
    sha256) of strings version `ref`, as the IR's `clav_strings` element names them: both
    files checked against the sha256s the version names (the sidecar once per process
    while its size and time are unchanged)."""
    from varimu.config import REPO_ROOT

    hp, bp, d = files(ref)
    sha = d["binary"]["sha256"]
    st = bp.stat()
    key = (str(bp), st.st_size, st.st_mtime_ns)
    if _CHECKED.get(key) != sha:
        if hashlib.sha256(bp.read_bytes()).hexdigest() != sha:
            raise versions.VersionError(f"{ref}'s sidecar {bp.name} doesn't match its sha256")
        _CHECKED[key] = sha
    return hp.resolve().relative_to(REPO_ROOT.resolve()).as_posix(), sha
