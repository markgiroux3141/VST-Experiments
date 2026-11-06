"""The D6's unknowns, each fitted to a different published figure, and a key's `Params`
(docs/CLAVINET_PLAN.md, CL1). Like the Rhodes' fits, one unknown per figure:

- each key's held tension: the key in tune with the key held (as a tuner tunes it);
- the non-speaking fraction (pin to anvil / speaking length) and the yarn's dashpot per
  metre: [G13] 2.3.1, release drops the pitch 3 semitones, and Fig. 5, a released note gone
  in ~0.1 s (both at E4, jointly);
- the rubber's wrap compliance (the press's extra deflection beside the anvil): the finger
  vibrato target (config: provisional);
- the tailpiece's dashpot (the case's resistive admittance): [G13] Fig. 7(a), A2's
  fundamental, T60 ~22 s;
- the steel's bending loss factor: [G13] Fig. 8, E4's partials 7-10, T60 ~3.8 s;
- the wound strings' wrap friction: [G13] Fig. 7(a), A2's partials 2-5 (least squares in
  log T60);
- the mute bar felt's dashpot: the muted decay target (config: provisional).

The rest tension follows from the held one: the pinch deflects the string by delta at the
anvil, stretching it by delta^2 / 2 (1/L + 1/l), so
T_rest = T_held - EA delta^2 / 2 (1/L + 1/l) / (L + l).

The global fits are cached in `cache/clavinet/` by the config's text and these modules'
sources.
"""

from __future__ import annotations

import functools
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy import optimize

from varimu.clavinet import spec, strings

FIT_KEYS = {"release": 36, "high": 36}


def _cache_key(name: str) -> str:
    """The fits' cache key: the config without its `pickups` block (no fit reads it: the
    fits' probe is `pickup_row`, a fixed point on the string), and the fits' code."""
    here = Path(__file__).parent
    blob = spec.split_block(spec.config_text(name), "pickups")[0].encode()
    for mod in ("spec.py", "strings.py", "fit.py"):
        blob += (here / mod).read_bytes()
    return hashlib.sha256(blob).hexdigest()[:16]


def base_params(
    n: int,
    glob: dict[str, float],
    name: str = "d6",
    tension_held: float | None = None,
    mute: float = 0.0,
) -> strings.Params:
    """A key's Params from the config and the global fits (`glob`), untuned (the held
    tension the nominal mu (2 L f)^2 unless given); `mute` the mute bar's slider, 0-1."""
    cfg = spec.load(name)
    g = spec.string(n, name)
    k_hc, p_hc = spec.tangent_hc(cfg)
    an, tg, tp, ls = cfg["anvil"], cfg["tangent"], cfg["tailpiece"], cfg["losses"]
    om = 2 * np.pi * g.f_hz
    anvil_k = an["contact_k_n_m"]
    t_held = (
        tension_held if tension_held is not None else g.mu_kg_m * (2 * g.length_m * g.f_hz) ** 2
    )
    l_ns = glob["nonspeaking_fraction"] * g.length_m
    m_eff = g.mu_kg_m * (g.length_m + l_ns) / 3  # the string's mass the pinch point moves
    return strings.Params(
        geom=g,
        tension_rest_n=t_held,
        tension_held_n=t_held,
        nonspeaking_m=l_ns,
        yarn_length_m=cfg["nonspeaking"]["yarn_fraction"] * l_ns,
        yarn_mass_kg_m=cfg["nonspeaking"]["yarn_mass_kg_m"],
        # the yarn grips by the string's surface: its dashpot scales with the diameter (the
        # fit is per a plain string's)
        yarn_damping_ns_m2=glob["yarn_c_ns_m2"] * g.d_outer_m / cfg["plain"]["diameter_m"],
        tailpiece_k_n_m=tp["k_n_m"],
        tailpiece_c_ns_m=glob["tailpiece_c_ns_m"],
        anvil_gap_m=an["gap_m"],
        anvil_k_n_m=anvil_k,
        anvil_c_ns_m=2 * an["contact_damping_ratio"] * np.sqrt(anvil_k * m_eff),
        grip_k_n_m=an["grip_k_n_m"],
        grip_c_ns_m=an["grip_damping_ratio"] * an["grip_k_n_m"] / om,
        tilt_rad=float(np.radians(an["grip_tilt_deg"])),
        tangent_mass_kg=tg["mass_kg"],
        rubber_k=k_hc,
        rubber_p=p_hc,
        rubber_alpha_s_m=tg["hysteresis_s_m"],
        hold_force_n=tg["hold_force_n"],
        air_density_kg_m3=ls["air_density_kg_m3"],
        air_viscosity_pa_s=ls["air_viscosity_pa_s"],
        eta_bend=glob["eta_bend"],
        wrap_k_n_m=glob["wrap_k_n_m"],
        eta_wrap=glob.get("eta_wrap", 0.0),
        mute_distance_m=cfg["mute"]["distance_m"],
        mute_k_n_m=mute * cfg["mute"]["k_n_m"],
        mute_c_ns_m=mute * glob.get("mute_c_ns_m", 0.0),
    )


def stretch_tension(p: strings.Params, delta2_m2: float) -> float:
    g = p.geom
    big_l, ln = g.length_m, p.nonspeaking_m
    return float(g.ea_n * delta2_m2 / 2 * (1 / big_l + 1 / ln) / (big_l + ln))


def deflection2(p: strings.Params, force_n: float | None = None) -> float:
    """The pinch's deflection squared: the anvil point's static displacement plus the
    rubber's wrap beside it (F / k_wrap)."""
    q = p if force_n is None else replace(p, hold_force_n=force_n)
    xs = strings.static(q)
    lay = strings.layout(q)
    d = np.hypot(xs[lay.ua(0)], xs[lay.ua(1)]) + q.hold_force_n / q.wrap_k_n_m
    return float(d * d)


def with_rest_tension(p: strings.Params) -> strings.Params:
    """T_rest from T_held and the static press's deflection (two passes)."""
    q = p
    for _ in range(2):
        q = replace(q, tension_rest_n=p.tension_held_n - stretch_tension(q, deflection2(q)))
    return q


def pickup_row(p: strings.Params, lay: strings.Layout, plane: int = 0) -> np.ndarray:
    """A probe on S a fifth of the way from the tailpiece (no partial below 5 is nulled)."""
    return strings.point_rows(p, lay, plane, 0.19 * p.geom.length_m, 0.0)


def partials(
    sysm: strings.System, p: strings.Params, count: int, f0_hz: float | None = None
) -> list[tuple[float, float]]:
    """(frequency, decay rate) of the speaking partials 1..count: for each, the mode with
    the largest y-displacement on S near k f0 sqrt(1 + B k^2)."""
    f, sig, amp = strings.mode_table(sysm, pickup_row(p, sysm.lay))
    f0 = f0_hz or p.geom.f_hz
    b = p.geom.ei_n_m2 * np.pi**2 / (p.tension_held_n * p.geom.length_m**2)
    out = []
    for k in range(1, count + 1):
        fk = k * f0 * np.sqrt(1 + b * k * k) / np.sqrt(1 + b)
        near = np.flatnonzero(np.abs(f - fk) < 0.3 * f0)
        if near.size == 0:
            out.append((float("nan"), float("nan")))
            continue
        i = near[np.argmax(amp[near])]
        out.append((float(f[i]), float(sig[i])))
    return out


def tune(p: strings.Params, target_hz: float | None = None) -> strings.Params:
    """The held tension that puts the held speaking fundamental on the note."""
    target = target_hz or p.geom.f_hz
    q = with_rest_tension(p)
    for _ in range(4):
        held = strings.system(q, True)
        f1 = partials(held, q, 1)[0][0]
        if abs(f1 / target - 1) < 1e-7:
            break
        q = with_rest_tension(replace(q, tension_held_n=q.tension_held_n * (target / f1) ** 2))
    return q


def released_fundamental(p: strings.Params) -> tuple[float, float]:
    """(frequency, decay rate) of the released string's lowest mode with the most motion
    on S."""
    rel = strings.system(p, False)
    f, sig, amp = strings.mode_table(rel, pickup_row(p, rel.lay))
    lo = f > 0.25 * p.geom.f_hz
    f, sig, amp = f[lo], sig[lo], amp[lo]
    order = np.argsort(f)
    f, sig, amp = f[order], sig[order], amp[order]
    # the lowest mode carrying real motion on S between ~an octave below and the note
    inb = (f > 0.45 * p.geom.f_hz) & (f < 0.995 * p.geom.f_hz)
    band = inb & (amp > 0.3 * np.max(amp[inb]))
    i = np.flatnonzero(band)[0]
    return float(f[i]), float(sig[i])


def bend_cents(p: strings.Params, force_n: float) -> float:
    """Cents the held fundamental moves from the tuned hold force to `force_n` (by the
    tension the pinch's deflection adds, the static press solved again)."""
    t = p.tension_rest_n + stretch_tension(p, deflection2(p, force_n))
    return float(600 * np.log2(t / p.tension_held_n))


def _solve(err, a: float, b: float, n: int = 13) -> float:
    """The root of err nearest a on a scan from a to b (the branch that starts at a: the
    losses here are not monotonic, a dashpot too strong clamps and reflects); without a
    sign change, the scanned point closest to it."""
    xs = np.linspace(a, b, n)
    es = [err(x) for x in xs]
    for i in range(n - 1):
        if es[i] == 0:
            return float(xs[i])
        if es[i] * es[i + 1] < 0:
            lo, hi = sorted((xs[i], xs[i + 1]))
            return float(optimize.brentq(err, lo, hi, xtol=1e-3))
    return float(xs[int(np.argmin(np.abs(es)))])


def _fit_once(glob: dict[str, float], name: str) -> dict[str, float]:
    cfg = spec.load(name)
    glob = dict(glob)
    # the non-speaking fraction (release 3 semitones down) and the yarn's dashpot (a
    # released note gone in release_t60_s), at E4, jointly: the yarn's damping moves the
    # released pitch, and the losses aren't monotonic in either (a grid, then a refinement)
    n_rel = FIT_KEYS["release"]
    drop = cfg["nonspeaking"]["release_drop_semitones"]
    t60 = cfg["nonspeaking"]["release_t60_s"]

    def rel_obj(x: np.ndarray) -> float:
        gl = dict(glob, nonspeaking_fraction=float(np.exp(x[0])), yarn_c_ns_m2=float(np.exp(x[1])))
        p = tune(base_params(n_rel, gl, name))
        try:
            f_rel, sig = released_fundamental(p)
        except IndexError:
            return 1e6
        d = 12 * np.log2(p.geom.f_hz / f_rel)
        return float((d - drop) ** 2 + (4 * np.log(np.log(1000) / sig / t60)) ** 2)

    grid = [
        (lr, lc)
        for lr in np.log(np.linspace(0.08, 0.4, 9))
        for lc in np.log(np.geomspace(0.1, 50.0, 9))
    ]
    best = min(grid, key=lambda x: rel_obj(np.array(x)))
    res = optimize.minimize(
        rel_obj,
        np.array(best),
        method="Nelder-Mead",
        options={"xatol": 1e-3, "fatol": 1e-6, "maxiter": 120},
    )
    glob["nonspeaking_fraction"] = float(np.exp(res.x[0]))
    glob["yarn_c_ns_m2"] = float(np.exp(res.x[1]))

    # the rubber's wrap: the bend target at its key
    an = cfg["anvil"]
    n_b = int(an["bend_key"])
    f1, f2 = an["bend_force_n"]

    def bend_err(log_k: float) -> float:
        gl = dict(glob, wrap_k_n_m=float(np.exp(log_k)))
        p = tune(base_params(n_b, gl, name))
        return bend_cents(p, f2) - bend_cents(p, f1) - an["bend_target_cents"]

    glob["wrap_k_n_m"] = float(
        np.exp(optimize.brentq(bend_err, np.log(1e3), np.log(1e8), xtol=1e-3))
    )

    # the tailpiece's dashpot (low partials; its resistive branch, scanned from strong
    # damping down) and the bending loss (high), alternately
    tp = cfg["tailpiece"]
    n_lo = int(tp["fit_key"])
    ls = cfg["losses"]
    n_hi = int(ls["high_fit_key"])
    k_a, k_b = (int(x) for x in ls["high_fit_partials"])
    targets = np.array(ls["wound_t60_s"])
    for _ in range(3):

        def lo_err(log_c: float) -> float:
            gl = dict(glob, tailpiece_c_ns_m=float(np.exp(log_c)))
            p = tune(base_params(n_lo, gl, name))
            sig = partials(strings.system(p, True), p, 1)[0][1]
            return np.log(np.log(1000) / sig) - np.log(tp["fundamental_t60_s"])

        glob["tailpiece_c_ns_m"] = float(np.exp(_solve(lo_err, np.log(1e5), np.log(1e0))))

        def hi_err(log_eta: float) -> float:
            gl = dict(glob, eta_bend=float(np.exp(log_eta)))
            p = tune(base_params(n_hi, gl, name))
            sigs = [s for _, s in partials(strings.system(p, True), p, k_b)[k_a - 1 :]]
            return np.log(np.log(1000) / np.mean(sigs)) - np.log(ls["high_t60_s"])

        glob["eta_bend"] = float(np.exp(_solve(hi_err, np.log(1e-6), np.log(1e-1))))

        def wrap_err(log_eta: float) -> float:
            gl = dict(glob, eta_wrap=float(np.exp(log_eta)))
            p = tune(base_params(n_lo, gl, name))
            sigs = np.array(
                [s for _, s in partials(strings.system(p, True), p, 1 + targets.size)[1:]]
            )
            return float(np.mean((np.log(np.log(1000) / sigs) - np.log(targets)) ** 2))

        res = optimize.minimize_scalar(
            wrap_err, bounds=(np.log(1e-7), np.log(1e-1)), method="bounded", options={"xatol": 1e-3}
        )
        glob["eta_wrap"] = float(np.exp(res.x))
    # the mute bar's felt: muted E4 at its target decay (the slider fully on)
    mu = cfg["mute"]
    n_m = int(mu["fit_key"])

    def mute_err(log_c: float) -> float:
        gl = dict(glob, mute_c_ns_m=float(np.exp(log_c)))
        p = tune(base_params(n_m, gl, name, mute=1.0))
        sig = partials(strings.system(p, True), p, 1)[0][1]
        return np.log(np.log(1000) / sig) - np.log(mu["muted_t60_s"])

    glob["mute_c_ns_m"] = float(np.exp(_solve(mute_err, np.log(1e-4), np.log(1e2))))
    return glob


START = {
    "nonspeaking_fraction": 0.19,
    "yarn_c_ns_m2": 1.0,
    "wrap_k_n_m": 5.0e3,
    "tailpiece_c_ns_m": 250.0,
    "eta_bend": 1.0e-3,
    "mute_c_ns_m": 0.1,
    "eta_wrap": 0.0,
}


@functools.cache
def globals_(name: str = "d6") -> dict[str, float]:
    """The global fits (cached on disk)."""
    spec.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = spec.CACHE_DIR / f"fits_{_cache_key(name)}.json"
    if path.exists():
        return json.loads(path.read_text())
    glob = dict(START)
    for _ in range(2):
        glob = _fit_once(glob, name)
    path.write_text(json.dumps(glob, indent=1))
    return glob


@functools.cache
def params(n: int, name: str = "d6", mute: float = 0.0) -> strings.Params:
    """Key n's Params, tuned with the key held (and the mute bar off: muting retunes
    nothing, the felt only loads the string)."""
    p = tune(base_params(n, globals_(name), name))
    if mute > 0:
        q = base_params(n, globals_(name), name, tension_held=p.tension_held_n, mute=mute)
        p = replace(q, tension_rest_n=p.tension_rest_n)
    return p
