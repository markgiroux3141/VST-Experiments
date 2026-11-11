"""Compile the Nickel Organ for circuitsim's live tier: the component NICKEL_ORGAN's next
version, `config/components/nickel_organ/<N>.yaml` and its `<N>.organ.json`
(docs/NICKEL_ORGAN_PLAN.md, "The Rust voice"; varimu/nickel/compile.py).

The Python reference (varimu/nickel/voice.py) builds a key's bar by finite elements and
voices every key by striking it twice; neither belongs in the app. This writes what the Rust
voice (`crates/circuitsim/src/nickel.rs`) needs: the circuit's values as plain floats, the
amplifier's idle point (solved here), the #327's table, and per key its bar's modes (a
frequency, a decay rate and the shapes at the strip, the hammer, the damper and the tip), its
ladder capacitor, voicing trim and mixing gain.

    uv run python scripts/compile_nickel_organ.py [--check] [--notes LO HI]

The first run voices every key that isn't in cache/nickel/voicing.json (~10 s a key). A
version is saved only when the data changed; moving the circuit
(config/circuits/nickel_organ.yaml's `organ_model`) to it is an explicit edit. `--check`
exits 1 when the latest version differs from what the config and the code give now.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from varimu.nickel import bar as nbar  # noqa: E402
from varimu.nickel import compile as ncompile  # noqa: E402
from varimu.nickel import organ as norgan  # noqa: E402
from varimu.nickel import spec as nspec  # noqa: E402
from varimu.nickel import voice as nvoice  # noqa: E402


def _triode(t: nvoice.Triode) -> dict:
    return {
        "mu": t.mu, "ex": t.ex, "kg1": t.kg1, "kp": t.kp, "kvb": t.kvb,
        "g_perv": t.g_perv, "g_contact": t.g_contact, "g_smooth": t.g_smooth,
    }  # fmt: skip


def compile_organ(lo: int | None = None, hi: int | None = None, progress: bool = False) -> dict:
    d = nspec.load()
    p = nvoice.params()
    lo = nspec.v(d, "tuning.lowest_note") if lo is None else lo
    hi = nspec.v(d, "tuning.highest_note") if hi is None else hi
    notes = list(range(lo, hi + 1))
    voiced = norgan.voicing(notes, progress=progress)
    vk1, vp1 = nvoice._idle_triode(p.pre, p.b_plus, p.ra, p.rk)
    vk3, vp3 = nvoice._idle_triode(p.drv, p.b_plus, p.drv_ra, p.drv_rk)
    vk6, ip6 = nvoice._idle_power(p)
    ni = p.ni
    pw = p.pwr
    params = {
        "turns": p.turns, "area_m2": p.area_m2, "l_g": p.l_g, "l_sigma": p.l_sigma,
        "r_arm": p.r_arm, "r_b": p.r_b, "e_strip": p.e_strip, "fb_max": p.fb_max,
        "r_shunt": p.r_shunt, "n_in": p.n_in, "noise_ohm": p.noise_ohm,
        "b_plus": p.b_plus, "ra": p.ra, "rk": p.rk, "cc": p.cc, "rg": p.rg, "rk6": p.rk6,
        "r_lad": p.r_lad, "lad_ratio": p.lad_ratio, "lad_max_hz": p.lad_max_hz,
        "n_ot": p.n_ot, "l_m": p.l_m, "r_d": p.r_d, "r_out": p.r_out, "c_out": p.c_out,
        "drv_ra": p.drv_ra, "drv_rk": p.drv_rk, "drv_cc": p.drv_cc, "rg6": p.rg6,
        "hammer_kg": p.hammer_kg, "felt_k": p.felt_k, "felt_p": p.felt_p,
        "felt_loss": p.felt_loss, "v_min": p.v_min, "v_max": p.v_max,
        "damper_t60": p.damper_t60, "relay_s": p.relay_s, "polarity": p.polarity,
        "lamp_t_max_k": nvoice.LAMP_T_MAX_K, "t_room_k": nvoice.T_ROOM_K,
    }  # fmt: skip
    keys = []
    for n in notes:
        f = nspec.v(d, "tuning.a4_hz") * 2 ** ((n - 69) / 12)
        b = nbar.build(d, f)
        f_pole = min(p.lad_ratio * float(b.freq_hz[0]), p.lad_max_hz)
        v = voiced[n]
        keys.append(
            {
                "note": n,
                "freq_hz": [float(x) for x in b.freq_hz],
                "sigma_per_s": [float(x) for x in b.sigma_per_s],
                "s_strip": [float(x) for x in b.s_strip],
                "phi_strike": [float(x) for x in b.phi_strike],
                "phi_damper": [float(x) for x in b.phi_damper],
                "phi_tip": [float(x) for x in b.phi_tip],
                "strip_volume_m3": b.strip_volume_m3,
                "strip_m": b.design.strip_m,
                "c_lad": 0.382 / (2 * math.pi * p.r_lad * f_pole),
                "trim": v["trim"],
                "mix": norgan.mix_gain(v),
            }
        )
    return {
        "version": 1,
        "fs_hz": nvoice.FS_HZ,
        "source": "scripts/compile_nickel_organ.py from config/nickel/organ.yaml",
        "panel": {"sustain": nspec.v(d, "panel.sustain"), "polarize": nspec.v(d, "panel.polarize")},
        "nickel": {
            "ms": ni.ms,
            "a": ni.a,
            "k": ni.k,
            "c": ni.c,
            "alpha": ni.alpha,
            "lambda_s": ni.lambda_s,
        },  # fmt: skip
        "params": params,
        "pre": _triode(p.pre),
        "drv": _triode(p.drv),
        "pwr": {
            "mu": pw.mu,
            "ex": pw.ex,
            "kg1": pw.kg1,
            "kg2": pw.kg2,
            "kp": pw.kp,
            "kvb": pw.kvb,
        },  # fmt: skip
        "lamp": {
            "t0": p.lamp.t0,
            "dt": p.lamp.dt,
            "r": list(p.lamp.r),
            "loss": list(p.lamp.loss),
            "mc": list(p.lamp.mc),
        },  # fmt: skip
        "idle": {"vk1": vk1, "vp1": vp1, "vk3": vk3, "vp3": vp3, "vk6": vk6, "ip6": ip6},
        "keys": keys,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--notes", nargs=2, type=int, metavar=("LO", "HI"))
    a = ap.parse_args()
    lo, hi = a.notes if a.notes else (None, None)
    data = compile_organ(lo, hi, progress=True)
    if a.check:
        have = ncompile.latest()
        same = have is not None and ncompile.load(have) == json.loads(ncompile.dump(data))
        print(f"{have} up to date" if same else "stale: rerun without --check")
        return 0 if same else 1
    ref = ncompile.save(data)
    if ref is None:
        print(f"unchanged: {ncompile.latest()}")
    else:
        print(f"saved {ref} ({len(data['keys'])} keys)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
