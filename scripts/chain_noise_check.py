"""Chains' noise against their published figures (CHAINS_PLAN.md "Noise and hum in the chains",
NH2): each preamp's equivalent input noise and each microphone's self-noise, rendered (circuitsim
at production, the circuit's noise on: resistors, tubes, transistors, op-amps) and weighted as
its maker states, with and without NH2's sources (the transistors' shot / channel / flicker
noise, their parasitic resistors' Johnson noise, the op-amps' current noise).

- A preamp: silence into its 150 ohm test generator (RSRC, its Johnson noise counted, as a bench
  measurement has it); the output's noise over the 1 kHz gain, in dBu.
- A microphone: its capsule's front and rear pressures at 0; the output's A-weighted noise over
  the on-axis sensitivity its fit reached (CHAINS_PLAN.md: the circuit's own, not the
  catalog's), in dB SPL.

Weighting is applied to the Welch PSD of the output (A: IEC 61672's analog curve; "unweighted":
20 Hz-20 kHz flat; CCIR: ITU-R 468's curve read rms, where DIN 45 405 reads quasi-peak, so a
CCIR row is indicative only).

    uv run --extra fast python scripts/chain_noise_check.py [--only NAME ...] [--seconds S]
        -> reports/chain_noise/summary.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from pathlib import Path

import numpy as np
from scipy.signal import welch

from varimu.circuit import builder
from varimu.circuit import ir as I
from varimu.circuit.spec import load_circuit
from varimu.config import load_sim_settings
from varimu.sim import fast, io

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "chain_noise"
SEED = 20261115
P_REF = 20e-6
DBU_V = 0.7746

# name -> what is checked. `set`: panel values; `gain_db`: bisect `gain_key` to this gain.
CASES = {
    "ssl_4000e": {
        "kind": "pre", "set": {"mic_gain": 1.0}, "weight": "A",
        "published": -130.6, "bound": "less than",
        "source": "data/schematics/ssl_4000e/README.md: SSL's reissue of the 82E01 circuit, EIN "
                  "< -130.6 dBu (A, 70 dB, 150R); here at its most gain, ~69.6 dB",
    },
    "api_312": {
        "kind": "pre", "gain_key": "gain", "gain_db": 58.0, "weight": "flat",
        "published": -129.0, "bound": "about",
        "source": "data/schematics/api_312/README.md: API's 1972 Circuit Specifications, Fig. 1 "
                  "(58 dB), equivalent input noise -129 dBm, 20-20 kHz unweighted",
    },
    "neumann_u87": {
        "kind": "mic", "sens_v_pa": 7.7e-3, "weight": "CCIR", "published": 26.0, "bound": "about",
        "source": "data/schematics/neumann_u87/README.md: Neumann's 1970s catalog, self-noise "
                  "~26 dB "
                  "(DIN 45 405, quasi-peak); sensitivity 7.7 mV/Pa as K87@2's fit reached",
    },
    "neumann_km84": {
        "kind": "mic", "sens_v_pa": 5.0e-3, "weight": "A", "published": 17.0, "bound": "about",
        "source": "data/schematics/neumann_km84/README.md: 17 dB-A (and 25 dB DIN 45 405); "
                  "sensitivity 5 mV/Pa as KK84@1's fit reached",
    },
    "neumann_u47_fet": {
        "kind": "mic", "sens_v_pa": 8.0e-3, "weight": "A", "published": 18.0, "bound": "about",
        "source": "data/schematics/neumann_u47_fet/README.md: Neumann's brochure, 18 dB-A; "
                  "sensitivity 8 mV/Pa as the circuit reached (CHAINS_PLAN.md WP25)",
    },
    "akg_c414": {
        "kind": "mic", "sens_v_pa": 12.5e-3, "weight": "A", "published": 14.0, "bound": "about",
        "source": "data/schematics/akg_c414/README.md: AKG's C414 B-ULS sheet, 14 dB-A; "
                  "sensitivity 12.5 mV/Pa as fitted (WP23)",
    },
    "crown_pzm": {
        "kind": "mic", "sens_v_pa": 7.0e-3, "weight": "A", "published": 20.0, "bound": "about",
        "source": "data/schematics/crown_pzm/README.md: 20 dB(A); sensitivity 7 mV/Pa as fitted "
                  "(WP26)",
    },
}  # fmt: skip

# NH2's noise elements (to build "before NH2" from the same IR): transistor noise, flicker
# currents, op-amp current noise, a bjt / jfet part's parasitic resistors.
_NH2_NAME = re.compile(r"^IN_(U\w+_(ip|im|en)|RQ\w+_[bce]|RJ\w+_[ds])$")


def without_nh2(ir: I.CircuitIR) -> I.CircuitIR:
    def keep(e) -> bool:
        if isinstance(e, I.TransistorNoise | I.FlickerCurrent):
            return False
        return not (isinstance(e, I.NoiseCurrent) and _NH2_NAME.match(e.name))

    return dataclasses.replace(
        ir,
        sections=tuple(
            dataclasses.replace(s, elements=tuple(e for e in s.elements if keep(e)))
            for s in ir.sections
        ),
    )


def a_weight(f: np.ndarray) -> np.ndarray:
    """IEC 61672's A-weighting, power gain (0 dB at 1 kHz)."""
    f2 = np.asarray(f, float) ** 2
    ra = (12194.0**2 * f2**2) / (
        (f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194.0**2)
    )
    return (ra * 10 ** (2.0 / 20)) ** 2  # A = 20 log10 ra + 2.00 dB (0 dB at 1 kHz)


def ccir_weight(f: np.ndarray) -> np.ndarray:
    """ITU-R 468's weighting, power gain: 18.2 dB + 20 log10 R(f) (0 dB at 1 kHz, +12.2 dB at
    6.3 kHz), R from ITU-R BS.468-4's analytic form."""
    f = np.asarray(f, float)
    h1 = (-4.737338981378384e-24 * f**6 + 2.043828333606125e-15 * f**4
          - 1.363894795463638e-7 * f**2 + 1)  # fmt: skip
    h2 = (1.306612257412824e-19 * f**5 - 2.118150887518656e-11 * f**3
          + 5.559488023498642e-4 * f)  # fmt: skip
    r = 1.246332637532143e-4 * f / np.hypot(h1, h2)
    return (r * 10 ** (18.2 / 20)) ** 2


def weighted_rms(v: np.ndarray, fs: float, weight: str) -> float:
    f, s = welch(v - np.mean(v), fs=fs, nperseg=2**14)
    band = (f >= 20.0) & (f <= 20000.0)
    w = {"A": a_weight, "CCIR": ccir_weight}.get(weight)
    g = w(f[band]) if w else np.ones(band.sum())
    df = f[1] - f[0]
    return float(np.sqrt(np.sum(s[band] * g) * df))


def settings():
    return io.TransientSettings.from_sim_settings(engine="circuitsim")


def run(ir: I.CircuitIR, x: np.ndarray, controls=None) -> np.ndarray:
    return fast.run_transient(ir, x, settings=settings(), controls=controls).vectors["v(out)"]


def gain_1k(spec, values: dict, fs: float) -> float:
    """The 1 kHz gain (V / V, `in` to `out`) of a small tone, noise off."""
    ir = builder.build(spec, values, noise=False, hum=False).ir
    n = int(0.3 * fs)
    t = np.arange(n) / fs
    amp = 1e-4
    y = run(ir, amp * np.sin(2 * np.pi * 1000.0 * t))[n // 3 :]
    tt = t[n // 3 :]
    c, s = (2 * np.mean(y * np.cos(2 * np.pi * 1000.0 * tt)),
            2 * np.mean(y * np.sin(2 * np.pi * 1000.0 * tt)))  # fmt: skip
    return float(np.hypot(c, s) / amp)


def silence_controls(ir: I.CircuitIR, n: int):
    return {c.name: np.zeros(n) for c in ir.controls} if ir.controls else None


def check(name: str, case: dict, seconds: float) -> dict:
    spec = load_circuit(ROOT / "config" / "circuits" / f"{name}.yaml")
    fs = float(load_sim_settings().sample_rate)
    values = dict(case.get("set", {}))
    out: dict = {"source": case["source"], "published": case["published"],
                 "bound": case["bound"], "weight": case["weight"]}  # fmt: skip
    if case["kind"] == "pre":
        if "gain_db" in case:
            lo, hi = 0.0, 1.0
            for _ in range(12):
                mid = 0.5 * (lo + hi)
                g = 20 * np.log10(gain_1k(spec, {**values, case["gain_key"]: mid}, fs))
                lo, hi = (mid, hi) if g < case["gain_db"] else (lo, mid)
            values[case["gain_key"]] = 0.5 * (lo + hi)
        gain = gain_1k(spec, values, fs)
        out["gain_db"] = 20 * np.log10(gain)
    out["set"] = values
    ir = builder.build(spec, values, noise=SEED, hum=False).ir
    n = int(seconds * fs)
    for label, the_ir in (("now", ir), ("before_nh2", without_nh2(ir))):
        v = run(the_ir, np.zeros(n), silence_controls(the_ir, n))
        rms = weighted_rms(v, fs, case["weight"])
        if case["kind"] == "pre":
            out[label] = 20 * np.log10(rms / gain / DBU_V)  # dBu at the input
        else:
            out[label] = 20 * np.log10(rms / case["sens_v_pa"] / P_REF)  # dB SPL
        out[f"{label}_out_v"] = rms
    out["now_minus_published_db"] = out["now"] - case["published"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--seconds", type=float, default=2.0)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for name, case in CASES.items():
        if a.only and name not in a.only:
            continue
        r = check(name, case, a.seconds)
        summary[name] = r
        unit = "dBu" if case["kind"] == "pre" else f"dB SPL ({case['weight']})"
        print(f"{name:18s} now {r['now']:7.1f}  before NH2 {r['before_nh2']:7.1f}  published "
              f"{case['bound']} {case['published']:6.1f} {unit}", flush=True)  # fmt: skip
        path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
