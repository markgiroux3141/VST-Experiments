"""The tube microphones' real supplies (CHAINS_PLAN.md NH3, SUPPLY 1): each supply's
winding voltage trimmed so the microphone's rail is its maker's figure, and its reservoir
capacitors' start voltages (a C part's `v0`, held for the DC operating point only) at their
steady state, so a render's 1 s settle starts the supply where it runs (its RC sections take
seconds to settle from the operating point's peak-charged start).

Each trim: long runs (circuitsim production, silence) from the knob's present value and 92% of
it, the secant method until the rail is within 0.05 V of its target; the last run reads the
capacitors. `--write` puts the three values into the circuit file (their lines'
`value:` only; the source strings say how they were derived).

    uv run --extra fast python scripts/mic_supply_trim.py [--only NAME ...] [--seconds 30] [--write]
"""

from __future__ import annotations

import argparse
import dataclasses
import re

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit import ir as I
from varimu.config import CONFIG_DIR
from varimu.sim import fast
from varimu.sim.io import TransientSettings

# name -> the trim: panel values, the winding's value key, the rail probe and its target (V), and
# each start voltage's value key with the capacitor's (positive, negative) nodes.
TRIMS = {
    "akg_c12": {
        "set": {"pattern": 4, "supply": 1},
        "knob": "t_hv_rms_v",
        "probe": "bplus",
        # br: "plate voltage 120 vdc at 0.7 ma" (data/schematics/akg_c12/README.md)
        "target": 120.0,
        "v0": {"c4a_v0_v": ("h1", "nret"), "c4b_v0_v": ("h2", "nret")},
    },
    "neumann_u47": {
        "set": {"supply": 1},
        "knob": "ng_t_r_ohm",
        "probe": "b105",
        "target": 105.0,  # br / ds58: 105 V at 40 mA loaded (data/schematics/neumann_u47/README.md)
        "v0": {"ng_c1_v0_v": ("n1", "0"), "ng_c2_v0_v": ("n2", "0")},
    },
    "neumann_u67": {
        "set": {"supply": 1},
        "knob": "nu_t_r_ohm",
        "probe": "bplus",
        "target": 210.0,  # Neumann's NU67u-930-06: +210 V at 0.88 mA (data/schematics/neumann_u67)
        "v0": {"nu_c1_v0_v": ("n1", "0"), "nu_c3_v0_v": ("n3", "0"), "nu_c4_v0_v": ("bplus", "0")},
    },
    "neumann_m49": {
        "set": {"supply": 1},
        "knob": "nn_t_v_rms",
        "probe": "bplus",
        "target": 116.0,  # man: the NN 48 b's 116 V D.C. plate (data/schematics/neumann_m49)
        "v0": {"nn_c1_v0_v": ("n1", "0"), "nn_c3_v0_v": ("n3", "0"), "nn_c4_v0_v": ("bplus", "0")},
    },
    "telefunken_ela_m251": {
        "set": {"supply": 1},
        "knob": "ns_t_v_rms",
        "probe": "bplus",
        "target": 120.0,  # bplus_v: the C12's 120 V (the 251's supply undocumented)
        "v0": {
            "ns_c4a_v0_v": ("h1", "0"),
            "ns_c4b_v0_v": ("h2", "0"),
            "ns_c5a_v0_v": ("h3", "0"),
            "ns_c5b_v0_v": ("bplus", "0"),
        },  # fmt: skip
    },
}


def steady(name: str, values: dict, nodes: set[str], seconds: float) -> dict[str, float]:
    """Each node's mean over the last second of `seconds` of silence."""
    c = spec.load_circuit(CONFIG_DIR / "circuits" / f"{name}.yaml")
    ir = builder.build_ir(c, spec.resolve(c, values))
    have = {p.node for p in ir.probes}
    ir = dataclasses.replace(
        ir, probes=(*ir.probes, *(I.VoltageProbe(x) for x in sorted(nodes - have - {"0"})))
    )
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    n = int(seconds * st.sample_rate)
    ctl = {k.name: np.zeros(n) for k in ir.controls} or None
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl)
    last = slice(n - int(st.sample_rate), n)
    out = {k[2:-1]: float(np.mean(a[last])) for k, a in v.vectors.items()}
    out["0"] = 0.0
    return out


def trim(name: str, t: dict, seconds: float) -> dict[str, float]:
    c = spec.load_circuit(CONFIG_DIR / "circuits" / f"{name}.yaml")
    k0 = float(spec.resolve(c)[t["knob"]])
    nodes = {t["probe"], *(n for pair in t["v0"].values() for n in pair)}
    # The secant method from the present value and 92% of it, until the rail is within 0.05 V.
    pts: list[tuple[float, float, dict]] = []
    k = k0
    for _ in range(8):
        m = steady(name, {**t["set"], t["knob"]: k}, nodes, seconds)
        r = m[t["probe"]]
        print(f"  {t['knob']} {k:.6g}: {t['probe']} {r:.4f} V (target {t['target']})", flush=True)
        pts.append((k, r, m))
        if abs(r - t["target"]) < 0.05:
            break
        if len(pts) == 1:
            k = 0.92 * k
            continue
        (ka, ra, _), (kb, rb, _) = pts[-2], pts[-1]
        k = kb + (t["target"] - rb) * (kb - ka) / (rb - ra)
    else:
        raise SystemExit(f"{name}: the rail didn't converge to {t['target']} V")
    out = {t["knob"]: k}
    for key, (a, b) in t["v0"].items():
        out[key] = m[a] - m[b]
    return out


def write(name: str, values: dict[str, float]) -> None:
    p = CONFIG_DIR / "circuits" / f"{name}.yaml"
    s = p.read_text(encoding="utf-8")
    for key, v in values.items():
        pat = re.compile(rf"^(  {re.escape(key)}: \{{value: )[^,]+(,)", re.M)
        s, n = pat.subn(lambda m, v=v: f"{m.group(1)}{v:.6g}{m.group(2)}", s)
        if n != 1:
            raise SystemExit(f"{p.name}: {key}'s value line not found once ({n})")
    p.write_text(s, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    for name, t in TRIMS.items():
        if a.only and name not in a.only:
            continue
        print(name)
        values = trim(name, t, a.seconds)
        print("  ->", {k: round(v, 4) for k, v in values.items()})
        if a.write:
            write(name, values)
            print(f"  wrote {name}.yaml")


if __name__ == "__main__":
    main()
