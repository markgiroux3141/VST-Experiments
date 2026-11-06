"""CL1: single keys of the D6 against [G13]'s measurements, and their pickups' EMF as WAVs
(docs/CLAVINET_PLAN.md) -> reports/clavinet/key/.

Per key: the string (length, tension, B nominal and from the held partials 2-7 as [G13]
estimates it), the held partials' frequencies and T60, the release's drop and decay, the
pressure bend, the polarizations' split near each low partial (the beating hypothesis), and
a played note (centre, bridge, both in phase and anti-phase) as float WAV at the EMF (V).

    uv run python scripts/clavinet_key_study.py [--keys 1 17 24 36 60] [--velocity 2.5] [--hold 1.5]
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np
import soundfile as sf

from varimu.clavinet import fit, note, spec, strings
from varimu.config import REPO_ROOT

OUT = REPO_ROOT / "reports" / "clavinet" / "key"

# [G13]'s figures, read (the config's sources say how)
G13_B = {1: 5e-4, 6: 2e-4, 22: 9e-5, 23: 1e-4, 50: 9e-5, 60: 8e-5}
G13_E4_T60 = [8.1, 9.0, 7.0, 8.6, 6.5, 6.0, 3.5, 5.9, 3.1, 4.3]  # Fig. 8, partials 1-10
G13_A2_T60 = [22.0, 16.0, 10.5, 9.7, 4.9]  # Fig. 7(a), read from the slopes


def b_estimate(parts: list[tuple[float, float]]) -> float:
    """[G13] eq. 2 on partials 2-7, averaged."""
    f0 = parts[0][0]
    bs = []
    for n in range(2, 8):
        fn = parts[n - 1][0]
        if np.isfinite(fn):
            bs.append((fn**2 - n * n * f0 * f0) / (n**4 * f0 * f0))
    return float(np.mean(bs))


def polarization_split(p: strings.Params, held: strings.System, count: int) -> list[dict]:
    """Near each partial: the two modes with the most y motion on S, their frequencies,
    and the weaker's share (a beat's depth needs comparable shares)."""
    f, sig, amp = strings.mode_table(held, fit.pickup_row(p, held.lay, 0))
    out = []
    for k in range(1, count + 1):
        fk = k * p.geom.f_hz
        near = np.flatnonzero(np.abs(f - fk) < 0.2 * p.geom.f_hz)
        if near.size < 2:
            out.append({"partial": k, "split_hz": None})
            continue
        top = near[np.argsort(amp[near])[::-1][:2]]
        a1, a2 = amp[top[0]], amp[top[1]]
        out.append(
            {
                "partial": k,
                "split_hz": float(abs(f[top[0]] - f[top[1]])),
                "share_db": float(20 * np.log10(a2 / a1)),
                "depth_db": float(20 * np.log10((a1 + a2) / max(a1 - a2, 1e-30))),
            }
        )
    return out


def study_key(n: int, velocity: float, hold_s: float, wav: bool) -> dict:
    p = fit.params(n)
    g = p.geom
    held = strings.system(p, True)
    parts = fit.partials(held, p, 10)
    f_rel, s_rel = fit.released_fundamental(p)
    an = spec.load()["anvil"]
    lo, hi = an["bend_force_n"]
    row = {
        "key": n,
        "note_hz": g.f_hz,
        "wound": g.wound,
        "speaking_length_m": g.length_m,
        "nonspeaking_m": p.nonspeaking_m,
        "tension_held_n": p.tension_held_n,
        "tension_rest_n": p.tension_rest_n,
        "stress_gpa": p.tension_held_n / (np.pi * g.d_core_m**2 / 4) / 1e9,
        "b_nominal": g.b_nominal,
        "b_from_partials": b_estimate(parts),
        "b_g13": G13_B.get(n),
        "partials_hz": [f for f, _ in parts],
        "partials_t60_s": [float(np.log(1000) / s) for _, s in parts],
        "release_hz": f_rel,
        "release_drop_semitones": float(12 * np.log2(g.f_hz / f_rel)),
        "release_t60_s": float(np.log(1000) / s_rel),
        "bend_cents_1_to_5n": fit.bend_cents(p, hi) - fit.bend_cents(p, lo),
        "polarizations": polarization_split(p, held, 5),
    }
    if wav:
        t0 = time.time()
        pl = note.play(n, velocity, hold_s)
        row["render_s"] = time.time() - t0
        row["contact_s"] = pl.contact_s
        row["max_force_n"] = pl.max_force_n
        c, b = pl.emf_v["centre"], pl.emf_v["bridge"]
        for tag, x in (("centre", c), ("bridge", b), ("both", c + b), ("anti", c - b)):
            sf.write(OUT / f"key{n:02d}_{tag}.wav", x.astype(np.float32), 96000, subtype="FLOAT")
        row["peak_v"] = {"centre": float(np.max(np.abs(c))), "bridge": float(np.max(np.abs(b)))}
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", type=int, nargs="+", default=[1, 6, 17, 22, 24, 36, 50, 60])
    ap.add_argument("--velocity", type=float, default=2.5, help="m/s at the tangent")
    ap.add_argument("--hold", type=float, default=1.5)
    ap.add_argument("--no-wav", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in args.keys:
        r = study_key(n, args.velocity, args.hold, not args.no_wav)
        rows.append(r)
        print(
            f"key {n:2d} {r['note_hz']:7.1f} Hz L={r['speaking_length_m']:.3f} "
            f"T={r['tension_held_n']:.1f} N B={r['b_from_partials']:.2e} (G13 {r['b_g13']}) "
            f"drop={r['release_drop_semitones']:.2f} st "
            f"rel T60={r['release_t60_s']:.3f} s bend={r['bend_cents_1_to_5n']:.1f} c "
            f"T60 1-5: {[round(x, 1) for x in r['partials_t60_s'][:5]]}",
            flush=True,
        )
    summary = {
        "globals": fit.globals_(),
        "level_factor": note.level_factor(),
        "g13_e4_t60": G13_E4_T60,
        "g13_a2_t60": G13_A2_T60,
        "keys": rows,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(f"wrote {OUT / 'summary.json'}")


if __name__ == "__main__":
    main()
