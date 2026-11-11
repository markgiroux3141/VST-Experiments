"""Fit the Crown PZM-30D (docs/CHAINS_PLAN.md WP26) to AKG / Crown's PZM30 D manual: no value is
printed on its schematic, so the inferred circuit (config/circuits/crown_pzm.yaml) and its capsule
(published_points.yaml "PZM_CAPSULE") are fitted, one figure per unknown:

1. the capsule (numpy, varimu.devices.capsule.sensitivity into the gate): the diaphragm's tension,
   the film's resistance and the vent to Fig. 1's RISING trace re 1 kHz (the 7 kHz peak, its height
   and the fall to 17 kHz, the -5 dB at 20 Hz);
2. through the circuit (circuitsim transients at production): R1 to the 1.1 mA current drain (48 V
   phantom), T1's ratio to the 240 ohm output impedance, the FLAT shunt C4 / R7 to the FLAT trace
   re RISING,
   and the electret's equivalent polarization to 7 mV/Pa open circuit (1 kHz, FLAT).

    uv run --extra fast python scripts/fit_pzm.py [--write] [--only capsule|circuit]

--write puts the capsule's fitted values into published_points.yaml (then `varimu fit-devices
--only PZM_CAPSULE`) and the circuit's into crown_pzm.yaml. Stage 2 uses the saved capsule.
"""

from __future__ import annotations

import argparse
import csv
import math
import re

import numpy as np
from scipy.optimize import brentq, least_squares

from varimu.config import CONFIG_DIR, REPO_ROOT
from varimu.devices import capsule

DATA = REPO_ROOT / "data" / "datasheets"
PUBLISHED = DATA / "published_points.yaml"
CIRCUIT = CONFIG_DIR / "circuits" / "crown_pzm.yaml"
C_GATE_F = 3.0e-12  # provisional: the FET's gate and the can's wiring, as a load on the capsule
SENS_V_PA = 0.007  # akg: 7 mV/Pa open circuit
Z_OUT_OHM = 240.0  # akg
DRAIN_A = 1.1e-3  # akg: current drain


def load_trace() -> dict[str, np.ndarray]:
    out: dict[str, list] = {}
    for r in csv.DictReader((DATA / "crown_pzm30d_response.csv").open(encoding="utf-8")):
        out.setdefault(r["trace"], []).append([float(r["freq_hz"]), float(r["db"])])
    return {k: np.array(v) for k, v in out.items()}


def _published_geometry() -> dict:
    from varimu.devices.library import _plain, _published

    return _plain(_published()["PZM_CAPSULE"]["geometry"])


def capsule_db(geom: dict, f: np.ndarray, e0_v: float) -> np.ndarray:
    lp = capsule.lumped(geom)
    c = capsule.capsule_from_data({"kind": "capsule", "name": "PZM", "lumped": lp})
    h = capsule.sensitivity(c, np.r_[1000.0, f], e0_v, c_load_f=C_GATE_F, r_load_ohm=1e9)
    return 20 * np.log10(np.abs(h[1:]) / abs(h[0]))


def fit_capsule(e0_v: float):
    rising = load_trace()["rising"]
    geom = _published_geometry()

    def put(x):
        g = {**geom, "diaphragm": dict(geom["diaphragm"]), "vent": dict(geom["vent"])}
        g["diaphragm"]["tension_n_m"], g["film_resistance_pa_s_m3"], g["vent"]["lf_3db_hz"] = (
            math.exp(v) for v in x
        )
        return g

    def res(x):
        return capsule_db(put(x), rising[:, 0], e0_v) - rising[:, 1]

    x0 = np.log([300.0, 1.0e9, 20.0])
    s = least_squares(res, x0, bounds=(np.log([30.0, 1e7, 2.0]), np.log([5000.0, 1e11, 60.0])))
    g = put(s.x)
    lp = capsule.lumped(g)
    print(f"capsule: tension {g['diaphragm']['tension_n_m']:.4g} N/m, film "
          f"{g['film_resistance_pa_s_m3']:.4g}, vent {g['vent']['lf_3db_hz']:.4g} Hz; membrane "
          f"{lp['membrane_resonance_hz']:.0f} Hz; RISING rms {np.sqrt(np.mean(s.fun**2)):.2f} dB, "
          f"max {np.max(np.abs(s.fun)):.2f}")  # fmt: skip
    for (f, d), e in zip(rising, s.fun, strict=True):
        print(f"  {f:7.0f} Hz {d:+5.1f} {e:+5.2f}")
    return {"tension_n_m": g["diaphragm"]["tension_n_m"],
            "film_resistance_pa_s_m3": g["film_resistance_pa_s_m3"],
            "lf_3db_hz": g["vent"]["lf_3db_hz"]}  # fmt: skip


# --- stage 2: through the circuit ----------------------------------------------------------------


class Bench:
    def __init__(self):
        from varimu.circuit import builder, spec
        from varimu.sim.io import TransientSettings

        self.builder, self.spec = builder, spec
        self.c = spec.load_circuit(CIRCUIT)
        self.s = TransientSettings.from_sim_settings(engine="circuitsim")
        self.fs = self.s.sample_rate
        self.over: dict[str, float] = {}

    def run(self, x, over=None):
        from varimu.sim import fast

        ir = self.builder.build(self.c, {**self.over, **(over or {})}).ir
        return fast.run_transient(ir, x, settings=self.s).vectors

    def tones(self, freqs, amp_pa=0.05, seconds=0.4, over=None) -> np.ndarray:
        """Complex V(out) per pascal at each frequency (rounded to 5 Hz), the last 0.2 s."""
        f = np.round(np.asarray(freqs) / 5.0) * 5.0
        t = np.arange(int(seconds * self.fs)) / self.fs
        x = amp_pa * np.sin(2 * np.pi * f[:, None] * t).sum(0) * np.minimum(1, t / 0.05)
        y = self.run(x, over)["v(out)"]
        n = int(0.2 * self.fs)
        tt, yy = t[-n:], y[-n:]
        return np.array([2 * np.mean(yy * np.exp(-2j * np.pi * fk * tt)) / amp_pa / -1j
                         for fk in f])  # fmt: skip

    def drain_a(self, over=None) -> float:
        v = self.run(np.zeros(int(0.05 * self.fs)), over)
        return float((96.0 - v["v(p2)"][-1] - v["v(p3)"][-1]) / 6810.0)

    def thd_at(self, spl_db: float = 150.0, over=None) -> float:
        """THD at spl_db (akg: 3% at 150 dB SPL), 1 kHz, open circuit."""
        from varimu.measure import metrics

        t = np.arange(int(0.3 * self.fs)) / self.fs
        p = 20e-6 * 10 ** (spl_db / 20) * math.sqrt(2)
        x = p * np.sin(2 * np.pi * 1000 * t) * np.minimum(1, t / 0.05)
        y = self.run(x, {"r_pre_leg_ohm": 1e9, **(over or {})})["v(out)"][-self.fs // 10 :]
        return float(metrics.harmonics(y, 1000.0, self.fs).thd)


def fit_circuit(b: Bench) -> dict[str, float]:
    out: dict[str, float] = {}
    r1 = brentq(lambda r: b.drain_a({"r1_ohm": r}) - DRAIN_A, 3e3, 1e7, xtol=1.0)
    out["r1_ohm"] = r1
    b.over["r1_ohm"] = r1
    print(f"R1 {r1:.0f} ohm: {b.drain_a() * 1e3:.3f} mA")

    def z_out(n):
        oc = abs(b.tones([1000.0], over={"t_ratio": n, "r_pre_leg_ohm": 1e9, "response": 1})[0])
        ld = abs(b.tones([1000.0], over={"t_ratio": n, "r_pre_leg_ohm": 120.0, "response": 1})[0])
        return 240.0 * (oc / ld - 1.0)

    n = math.exp(brentq(lambda x: math.log(z_out(math.exp(x)) / Z_OUT_OHM), math.log(0.1),
                        math.log(3.0), xtol=1e-3))  # fmt: skip
    out["t_ratio"] = n
    b.over["t_ratio"] = n
    print(f"T1 ratio {n:.4f}: {z_out(n):.1f} ohm")
    tr = load_trace()
    flat = tr["flat"]
    rising = tr["rising"]
    lf = np.log10(rising[:, 0])
    want = flat[:, 1] - np.interp(np.log10(flat[:, 0]), lf, rising[:, 1])
    f = flat[:, 0]
    h_r = b.tones(f, over={"response": 0})

    def res(x):
        c4, r7 = math.exp(x[0]), math.exp(x[1])
        h_f = b.tones(f, over={"response": 1, "c4_f": c4, "r7_ohm": r7})
        return 20 * np.log10(np.abs(h_f / h_r)) - want

    lo, hi = np.log([1e-10, 10.0]), np.log([1e-6, 1e5])
    s = least_squares(res, np.log([10e-9, 1000.0]), bounds=(lo, hi), diff_step=0.02)
    out["c4_f"], out["r7_ohm"] = (math.exp(v) for v in s.x)
    b.over.update(c4_f=out["c4_f"], r7_ohm=out["r7_ohm"])
    print(f"C4 {out['c4_f'] * 1e9:.3f} nF, R7 {out['r7_ohm']:.0f} ohm: FLAT re RISING rms "
          f"{np.sqrt(np.mean(s.fun**2)):.2f} dB")  # fmt: skip
    for (fh, _), e, w in zip(flat, s.fun, want, strict=True):
        print(f"  {fh:7.0f} Hz want {w:+5.2f} {e:+5.2f}")
    e0 = float(b.spec.resolve(b.c)["electret_v"])
    for _ in range(4):
        s = abs(b.tones([1000.0], over={"electret_v": e0, "r_pre_leg_ohm": 1e9, "response": 1})[0])
        e0 *= SENS_V_PA / s
    out["electret_v"] = e0
    b.over["electret_v"] = e0
    print(f"electret {e0:.2f} V: {s * 1e3:.3f} mV/Pa (before the last step)")

    return out


def yaml_num(x: float, digits: int = 5) -> str:
    t = f"{x:.{digits}g}"
    if "e" in t and "." not in t.split("e")[0]:
        t = t.replace("e", ".0e", 1)
    return t


def write_capsule(v: dict[str, float]) -> None:
    text = PUBLISHED.read_bytes().decode("utf-8")
    start = text.index('"PZM_CAPSULE":')
    end = text.find('\n"', start + 1)
    end = len(text) if end < 0 else end
    block = text[start:end]
    for k, x in v.items():
        block, c = re.subn(rf"({k}: \{{value: )[^}}]+", rf"\g<1>{yaml_num(x)}", block)
        if c != 1:
            raise SystemExit(f"PZM_CAPSULE: {c} lines for {k}")
    PUBLISHED.write_bytes((text[:start] + block + text[end:]).encode("utf-8"))


def write_circuit(v: dict[str, float]) -> None:
    text = CIRCUIT.read_bytes().decode("utf-8")
    for k, x in v.items():
        text, c = re.subn(rf"(\n  {k}: \{{value: )[^,}}]+", rf"\g<1>{yaml_num(x)}", text)
        if c != 1:
            raise SystemExit(f"crown_pzm.yaml: {c} lines for {k}")
    CIRCUIT.write_bytes(text.encode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--only", choices=["capsule", "circuit"])
    args = ap.parse_args()
    if args.only != "circuit":
        from varimu.circuit import spec

        e0 = float(spec.resolve(spec.load_circuit(CIRCUIT))["electret_v"])
        v = fit_capsule(e0)
        if args.write:
            write_capsule(v)
            print(
                "-> published_points.yaml PZM_CAPSULE (now: varimu fit-devices --only PZM_CAPSULE)"
            )
    if args.only != "capsule":
        v = fit_circuit(Bench())
        if args.write:
            write_circuit(v)
            print(f"-> {CIRCUIT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
