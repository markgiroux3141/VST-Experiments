"""The keyboard's design (config/victorian/reeds.yaml) as each key's values (`KeyParams`).

Per key: the reed's length from its (tuned) frequency (a uniform cantilever, f1 =
(1.8751^2 / 2 pi) (t / L^2) sqrt(E / 12 rho)), its two modes (the second at
(4.6941 / 1.8751)^2 = 6.267 f1, each a tip mass m / 4) and their shapes at the drive point; the
magnet's gap from the reed's design swing; the local circuit's L / R from the reed's period and
its pull from the design swing, so its current, resistance and turns follow; the contacts and
the carbon as the file has them. `tuning` files each reed until the running reed speaks its
note; `keyboard` is the compiled data, saved as the component GRAY_REEDS (`save`).
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import yaml

from varimu.config import REPO_ROOT
from varimu.devices import versions
from varimu.victorian import spec
from varimu.victorian.reed import MU0, KeyParams, Mode

BETA1 = 1.8751040687
BETA2 = 4.6940911330


def shape(beta: float, xi: float) -> float:
    """A uniform cantilever's mode shape (root clamped, tip free) at xi = s / L, the tip's 1."""

    def phi(z: float) -> float:
        sig = (math.cosh(beta) + math.cos(beta)) / (math.sinh(beta) + math.sin(beta))
        bz = beta * z
        return math.cosh(bz) - math.cos(bz) - sig * (math.sinh(bz) - math.sin(bz))

    return phi(xi) / phi(1.0)


def shape_mean(beta: float, xi0: float, xi1: float, n: int = 64) -> float:
    """The shape averaged over [xi0, xi1] (a pole face), by the midpoint rule."""
    s = 0.0
    for k in range(n):
        s += shape(beta, xi0 + (k + 0.5) * (xi1 - xi0) / n)
    return s / n


def note_hz(cfg: dict[str, Any], note: int) -> float:
    return spec.v(cfg, "tuning.a4_hz") * 2.0 ** ((note - 69) / 12.0)


def notes(cfg: dict[str, Any]) -> list[int]:
    return list(range(spec.v(cfg, "tuning.lowest_note"), spec.v(cfg, "tuning.highest_note") + 1))


def key_params(cfg: dict[str, Any], note: int, tune: float = 1.0, **override: Any) -> KeyParams:
    """Key `note`'s values, its reed filed to `tune` times the note's frequency (the free
    reed's first mode: `tuning` finds the factor that makes the running reed speak the note);
    `override` replaces any KeyParams field (studies, bends)."""
    v = lambda k: spec.v(cfg, k)  # noqa: E731
    lo, hi = v("tuning.lowest_note"), v("tuning.highest_note")
    u = (note - lo) / (hi - lo)
    f1 = note_hz(cfg, note) * tune
    e, rho, w = v("reed.youngs_pa"), v("reed.density_kg_m3"), v("reed.width_m")
    t = v("reed.thickness_low_m") + u * (v("reed.thickness_high_m") - v("reed.thickness_low_m"))
    c1 = BETA1 * BETA1 / (2.0 * math.pi) * math.sqrt(e / (12.0 * rho))
    length = math.sqrt(c1 * t / f1)
    m_tip = rho * w * t * length / 4.0
    w1 = 2.0 * math.pi * f1
    ratio2 = (BETA2 / BETA1) ** 2
    q1 = v("reed.q1")
    q2 = q1 * (1.0 / ratio2) ** v("reed.q_exponent")
    # The drive point: the pole face's centre at `drive_point` of the length, the face
    # `pole_depth_m` long (clipped to the reed).
    half = 0.5 * v("magnet.pole_depth_m") / length
    xi = v("magnet.drive_point")
    xi0, xi1 = max(xi - half, 0.0), min(xi + half, 1.0)
    modes = (
        Mode(omega=w1, zeta=0.5 / q1, mass_kg=m_tip, b=shape_mean(BETA1, xi0, xi1)),
        Mode(omega=w1 * ratio2, zeta=0.5 / q2, mass_kg=m_tip, b=shape_mean(BETA2, xi0, xi1)),
    )
    k_reed = 1.0 / sum(m.b * m.b / (m.mass_kg * m.omega * m.omega) for m in modes)
    a_lo, a_hi = v("reed.amplitude_low_m"), v("reed.amplitude_high_m")
    amp = a_lo * (a_hi / a_lo) ** u
    gap = v("magnet.gap_ratio") * amp
    area = w * v("magnet.pole_depth_m")
    g_c = v("magnet.core_gap_m")
    x_c = v("contact.preload_fraction") * amp
    # The local circuit: its time constant L / R a fraction of the reed's period (so the pull
    # lags the contact and does work on the reed instead of stiffening it), and its pull at
    # the steady current, with the reed at the screws, a fraction of what deflects the reed by
    # its design swing. L i^2 / G is that pull (G the magnetic gap), and L = tau R, i = V / R,
    # so the current follows: i = F G / (tau V); then R, L and the turns.
    big_g = 2.0 * (gap - x_c) + g_c
    tau = v("magnet.tau_fraction") / f1
    v_loc = v("magnet.local_v")
    pull = v("magnet.drive_fraction") * k_reed * amp
    i_d = pull * big_g / (tau * v_loc)
    r_total = v_loc / i_d
    turns = math.sqrt(tau * r_total * big_g / (MU0 * area))
    r_drive = r_total - v("magnet.local_ohm")
    k_s = v("contact.spring_ratio") * k_reed
    k_stop = 100.0 * k_reed
    vals: dict[str, Any] = dict(
        note=note,
        f_hz=f1,
        modes=modes,
        turns=turns,
        area_m2=area,
        gap_m=gap,
        core_gap_m=g_c,
        r_drive_ohm=r_drive,
        stop_m=gap - v("magnet.stop_m"),
        k_stop_n_m=k_stop,
        c_stop_ns_m=2.0 * 0.5 * math.sqrt(k_stop * m_tip),
        x_c_m=x_c,
        f_pre_n=v("contact.preload_force_fraction") * k_reed * x_c,
        k_s_n_m=k_s,
        c_s_ns_m=2.0 * v("contact.spring_zeta") * math.sqrt(k_s * m_tip),
        r_c0_ohm=v("contact.r0_ohm"),
        f_c0_n=v("contact.f0_n"),
        r_film_ohm=v("contact.film_ohm"),
        cond_drive_f=v("contact.condenser_f") + v("contact.stray_f"),
        cond_line_f=v("contact.stray_f"),
        v_arc=v("contact.arc_v"),
        i_arc_min_a=v("contact.arc_min_a"),
        r_arc_ohm=v("contact.arc_ohm"),
        e_fe_v_m=v("contact.field_emission_v_m"),
        v_paschen=v("contact.paschen_v"),
        d_paschen_m=v("contact.paschen_gap_m"),
        e_air_v_m=v("contact.air_v_m"),
        g_open_s=v("carbon.open_s"),
        g0_s=v("carbon.g0_s"),
        f0_n=v("carbon.f0_n"),
        n_carbon=v("carbon.exponent"),
        f_max_n=v("carbon.force_max_n"),
        vel_exp=v("carbon.velocity_exponent"),
        touch_gain=v("carbon.touch_gain"),
        tau_on_s=v("carbon.tau_on_s"),
        tau_off_s=v("carbon.tau_off_s"),
        q_damper=v("damper.q"),
    )
    vals.update(override)
    return KeyParams(**vals)


def describe(p: KeyParams) -> dict[str, float]:
    """A key's design figures, for reports."""
    m = p.modes[0]
    big_g = 2.0 * (p.gap_m - p.x_c_m) + p.core_gap_m
    ell = MU0 * p.turns**2 * p.area_m2 / big_g
    return {
        "note": p.note,
        "f_hz": p.f_hz,
        "tip_mass_g": m.mass_kg * 1e3,
        "k_drive_n_m": 1.0 / sum(q.b * q.b / (q.mass_kg * q.omega * q.omega) for q in p.modes),
        "b1": p.modes[0].b,
        "b2": p.modes[1].b,
        "gap_mm": p.gap_m * 1e3,
        "turns": p.turns,
        "r_drive_ohm": p.r_drive_ohm,
        "l_mh": ell * 1e3,
        "x_c_um": p.x_c_m * 1e6,
    }


# --- tuning: each reed filed until it speaks its note ------------------------------------------

TUNING_CACHE = REPO_ROOT / "cache" / "victorian" / "tuning.json"


def _cfg_hash(cfg: dict[str, Any]) -> str:
    import inspect

    from varimu.victorian import reed as _reed

    text = (
        json.dumps(cfg, sort_keys=True)
        + inspect.getsource(_reed)
        + inspect.getsource(key_params)
        + inspect.getsource(_measure)
    )
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _measure(args: tuple[dict[str, Any], int, float]) -> float:
    from varimu.victorian import reed as _reed

    cfg, note, tune = args
    p = key_params(cfg, note, tune)
    seconds = max(0.6, 25.0 / p.f_hz + 0.35)  # the bass builds up for ~0.35 s
    o = _reed.run(
        p,
        seconds,
        spec.v(cfg, "magnet.local_v"),
        spec.v(cfg, "magnet.line_v"),
        [(0.0, "on", 100)],
        oversample=spec.v(cfg, "numerics.oversample"),
        probes=True,
    )
    return _reed.pitch_hz(o["x"])


def tuning(cfg: dict[str, Any], passes: int = 2, progress: bool = False) -> dict[int, float]:
    """Per note the factor its free reed is filed to so that, maintained on the nominal local
    battery, it speaks the note (the instrument maker's tuning in place); cached in
    cache/victorian/tuning.json by the design's and the code's hash."""
    from concurrent.futures import ProcessPoolExecutor

    key = _cfg_hash(cfg)
    cache: dict[str, Any] = {}
    if TUNING_CACHE.exists():
        cache = json.loads(TUNING_CACHE.read_text(encoding="utf-8"))
    if key in cache:
        return {int(k): v for k, v in cache[key].items()}
    ns = notes(cfg)
    tune = {n: 1.0 for n in ns}
    workers = max(1, (os.cpu_count() or 2) - 2)
    with ProcessPoolExecutor(workers) as ex:
        for k in range(passes):
            fs = list(ex.map(_measure, [(cfg, n, tune[n]) for n in ns]))
            for n, f in zip(ns, fs, strict=True):
                tune[n] *= note_hz(cfg, n) / f
            if progress:
                cents = [1200 * math.log2(f / note_hz(cfg, n)) for n, f in zip(ns, fs, strict=True)]
                worst = max(abs(c) for c in cents)
                print(f"tuning pass {k + 1}: worst {worst:.1f} cents before it")
    cache[key] = {str(n): t for n, t in tune.items()}
    TUNING_CACHE.parent.mkdir(parents=True, exist_ok=True)
    TUNING_CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return tune


# --- the component -----------------------------------------------------------------------------

COMPONENT = "GRAY_REEDS"
KIND = "reed_keys"
DATA_SUFFIX = ".reeds.json"
CONFIG_FILE = "config/victorian/reeds.yaml"


def params_dict(p: KeyParams) -> dict[str, Any]:
    d = dataclasses.asdict(p)
    d["modes"] = [dataclasses.asdict(m) for m in p.modes]
    return d


def from_data(d: dict[str, Any]) -> KeyParams:
    """A key's values back from the compiled data (the tests' reference reads these)."""
    d = dict(d)
    d["modes"] = tuple(Mode(**m) for m in d["modes"])
    return KeyParams(**d)


def keyboard(cfg: dict[str, Any] | None = None, progress: bool = False) -> dict[str, Any]:
    """The compiled keyboard: every key's values, its reed tuned."""
    cfg = cfg or spec.load("reeds")
    tune = tuning(cfg, progress=progress)
    return {
        "version": 1,
        "source": f"varimu/victorian/compile.py from {CONFIG_FILE}",
        "keys": [params_dict(key_params(cfg, n, tune[n])) for n in notes(cfg)],
    }


def dump(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"))


def _yaml(name: str, data_file: str, sha: str) -> str:
    cfg_sha = versions.text_hash((REPO_ROOT / CONFIG_FILE).read_text(encoding="utf-8"))
    return (
        f"# Generated by varimu/victorian/compile.py (scripts/compile_victorian_reeds.py) on"
        f" {_dt.date.today().isoformat()}.\n"
        "# Don't edit by hand: change config/victorian/reeds.yaml or varimu/victorian/ and\n"
        "# recompile.\n"
        f"name: {name}\n"
        f"kind: {KIND}\n"
        "source: \"the Victorian synth's keyboard of self-interrupting reeds\n"
        "  (docs/VICTORIAN_SYNTH_PLAN.md): the values in config/victorian/reeds.yaml and their\n"
        "  sources, through varimu/victorian/compile.py (each reed's length, modes and magnet,\n"
        "  each reed filed to pitch in place by the reference), for circuitsim's reeds.rs\"\n"
        "instrument:\n"
        f"  file: {CONFIG_FILE}\n"
        f"  sha256: {cfg_sha}\n"
        "data:\n"
        f"  file: {data_file}\n"
        f"  sha256: {sha}\n"
    )


def latest() -> str | None:
    have = versions.versions(COMPONENT)
    return f"{COMPONENT}@{have[-1]}" if have else None


def files(ref: str) -> tuple[Path, str, dict[str, Any]]:
    """Version `ref`'s data file, its sha256 (checked) and its yaml."""
    r, text = versions.read_text(ref)
    d = yaml.safe_load(text)
    if d.get("kind") != KIND:
        raise ValueError(f"{r} is not a reed keyboard (kind {d.get('kind')!r})")
    p = versions.COMPONENT_DIR / r.folder / d["data"]["file"]
    sha = versions.text_hash(p.read_text(encoding="utf-8"))
    if sha != d["data"]["sha256"]:
        raise versions.VersionError(f"{r}'s data {p.name} doesn't match its sha256")
    return p, sha, d


def ir_data(ref: str) -> tuple[str, str]:
    """The IR's (data path relative to the repository's root, sha256) for version `ref`."""
    p, sha, _ = files(ref)
    return p.resolve().relative_to(REPO_ROOT.resolve()).as_posix(), sha


def load(ref: str) -> dict[str, Any]:
    p, _, _ = files(ref)
    return json.loads(p.read_text(encoding="utf-8"))


def save(data: dict[str, Any], name: str = COMPONENT) -> versions.Ref | None:
    """Save as component `name`'s next version, unless the latest one's data is the same."""
    text = dump(data)
    sha = versions.text_hash(text)
    have = versions.versions(name)
    if have:
        _, old, _ = files(f"{name}@{have[-1]}")
        if old == sha:
            return None
    n = (have or [0])[-1] + 1
    folder = versions.COMPONENT_DIR / name.lower()
    folder.mkdir(parents=True, exist_ok=True)
    df = f"{n}{DATA_SUFFIX}"
    (folder / df).write_text(text, encoding="utf-8", newline="\n")
    ref = versions.save(name, _yaml(name, df, sha))
    if ref.version != n:
        raise RuntimeError(f"saved {ref}, expected version {n}")
    return ref
