"""The 670's transformers on their own (main plan Phase 2, "done when").

Each transformer is the slice's own (varimu.circuit.netlist.transformer: the
same windings, core, gap, eddy loss, leakage and capacitances), driven and
loaded the way the slice drives and loads it, with the tubes replaced by
resistances (STANDALONE: test fixture values, not model data). circuitsim
runs them with Jiles-Atherton cores. Measured:

- frequency response: the gain of a small sine at each frequency, fitted
  over whole periods once the start-up has settled, re 1 kHz;
- low-frequency saturation: THD of a 30 Hz sine (and 1 kHz for contrast)
  against the peak flux density it drives the core to;
- the B-H loop: B from the core node (the netlist's core node voltage, 1 V =
  1 mT), H from the core model along that path (the device in the run is the
  same function of the B path, so this is the H it drew).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import numpy as np

from varimu.circuit import netlist as nl
from varimu.circuit.ir import CircuitIR, Element, Resistor, Section, VoltageProbe
from varimu.devices.core import MU0, TESLA_PER_V
from varimu.sim import fast, io

KEYS = ("t101", "t102", "t103", "t104")
NAMES = {
    "t101": "T101 input",
    "t102": "T102 output",
    "t103": "T103 sidechain input",
    "t104": "T104 sidechain output",
}

# Fixture resistances standing in for the tubes around each transformer (provisional:
# model knowledge, test fixtures only): a 6386 bank's plate resistance at the slice's
# idle (~5 kOhm), a 6973's (a pentode, ~20 kOhm), a grid circuit (1 MOhm).
STANDALONE = {"r_6386_plate_ohm": 5e3, "r_6973_plate_ohm": 20e3, "r_grid_ohm": 1e6}


@dataclass(frozen=True)
class Fixture:
    key: str
    ir: CircuitIR
    out: tuple[str, str]  # differential output nodes ("0" = ground)
    ref_turns: float  # reference winding, for the flux density it sees
    area_m2: float


def _r(name, a, b, ohms) -> Resistor:
    return Resistor(f"R{name}", a, b, ohms)


def fixture(key: str, overrides: Mapping[str, Any] | None = None, cores: str = "ja") -> Fixture:
    """Transformer `key` between the slice's source and load impedances, driven at "in"."""
    p = nl.resolve(overrides)
    rp, rp3, rg = (STANDALONE[k] for k in ("r_6386_plate_ohm", "r_6973_plate_ohm", "r_grid_ohm"))
    t = nl.transformer(key, p, cores)
    if key == "t101":  # 600 ohm source (no pad), R101/R102, the two grids, CT grounded
        around: list[Element] = [
            _r("src", "in", "pri", p["source_impedance_ohm"]),
            _r("101", "pri", "0", p["r101_r102_ohm"]),
            _r("cv", "cv", "0", 1.0),
            _r("ga", "ga", "0", rg),
            _r("gb", "gb", "0", rg),
        ]
        out = ("ga", "gb")
    elif key == "t102":  # plate to plate through two bank resistances, 600 ohm load
        around = [
            _r("pa", "in", "pa", rp),
            _r("pb", "pb", "0", rp),
            _r("107", "t3", "ctr", p["r107_r108_ohm"]),
            _r("108", "ctr", "t2", p["r107_r108_ohm"]),
            _r("load", "out", "0", p["load_ohm"]),
        ]
        out = ("out", "0")
    elif key == "t103":  # the output pads in front, the threshold pots behind (at mid)
        around = [
            _r("145", "in", "s1", p["r145_r148_ohm"]),
            _r("147", "0", "s2", p["r145_r148_ohm"]),
            _r("149", "s1", "s2", p["r149_r150_ohm"]),
            _r("t5", "t5", "0", p["r115a_ohm"] + p["r113_r114_ohm"]),
            _r("t8", "t8", "0", p["r115b_ohm"] + p["r113_r114_ohm"]),
        ]
        out = ("t5", "t8")
    elif key == "t104":  # plate to plate through two 6973 resistances; R136; feedback loads
        around = [
            _r("pa3", "in", "pa3", rp3),
            _r("pb3", "pb3", "0", rp3),
            _r("bp", "bp", "0", 1.0),
            _r("136", "ay", "bk", p["r136_ohm"]),
            _r("bk", "bk", "0", 1.0),
            _r("134", "fy", "0", p["r134_ohm"]),
            _r("135", "fg", "0", p["r135_ohm"]),
        ]
        out = ("ay", "bk")
    else:
        raise KeyError(key)
    # (a linear build may go to ngspice, whose text has no core node)
    probes = {n for n in out if n != "0"} | ({f"{key}_core"} if cores != "linear" else set())
    models = () if cores == "linear" else (nl.transformer_core(key, p),)
    ir = CircuitIR(
        f"{NAMES[key]}, standalone",
        "in",
        tuple(VoltageProbe(n) for n in sorted(probes)),
        models,
        (Section(NAMES[key], tuple(t + around)),),
    )
    return Fixture(key, ir, out, p[f"{key}_turns"], p[f"{key}_core_area_m2"])


def _settings() -> io.TransientSettings:
    s = io.TransientSettings.from_sim_settings(engine="circuitsim")
    return dataclasses.replace(s, full_scale_volts_peak=1.0)


def run(fx: Fixture, x: np.ndarray, settings: io.TransientSettings | None = None) -> dict:
    """Simulate the drive x (volts at "in", at the sample rate): output (V) and B (T)."""
    s = settings or _settings()
    v = fast.run_transient(fx.ir, x, settings=s).vectors
    a, b = fx.out
    out = v[f"v({a})"] - (v[f"v({b})"] if b != "0" else 0.0)
    return {"out": out, "b": v[f"v({fx.key}_core)"] * TESLA_PER_V}


def _tone(f: float, amp: float, fs: int, periods: int, settle_s: float) -> tuple[np.ndarray, int]:
    """A sine faded in over 5 ms; returns it and the start of the analysed whole periods."""
    n_settle = int(settle_s * fs)
    n_per = fs / f
    n = n_settle + int(round(periods * n_per))
    t = np.arange(n) / fs
    x = amp * np.sin(2 * np.pi * f * t) * np.minimum(1.0, t / 0.005)
    return x, n_settle


def _fit(y: np.ndarray, f: float, fs: int, harmonics: int = 1) -> np.ndarray:
    """Complex amplitudes of harmonics 1..h of f in y (least squares over y)."""
    t = np.arange(len(y)) / fs
    cols = [np.ones_like(t)]
    for k in range(1, harmonics + 1):
        cols += [np.cos(2 * np.pi * k * f * t), np.sin(2 * np.pi * k * f * t)]
    c, *_ = np.linalg.lstsq(np.stack(cols, axis=1), y, rcond=None)
    return c[1::2] - 1j * c[2::2]


def frequency_response(fx: Fixture, freqs, amp: float = 0.1, jobs: int = 8) -> np.ndarray:
    """Gain (dB, output over drive) at each frequency; small signal."""
    fs = _settings().sample_rate

    def one(f):
        x, a = _tone(f, amp, fs, periods=max(4, int(f * 0.02)), settle_s=max(0.1, 8 / f))
        y = run(fx, x)["out"][a:]
        return 20 * np.log10(abs(_fit(y, f, fs)[0]) / amp)

    with ThreadPoolExecutor(jobs) as ex:
        return np.array(list(ex.map(one, freqs)))


def drive_for_flux(fx: Fixture, f: float, b_peak: float) -> float:
    """Drive amplitude that gives about `b_peak` at f, from the small-signal winding voltage."""
    fs = _settings().sample_rate
    amp = 0.1
    x, a = _tone(f, amp, fs, periods=4, settle_s=max(0.1, 8 / f))
    b = run(fx, x)["b"][a:]
    return amp * b_peak / max(1e-12, abs(_fit(b, f, fs)[0]))


def thd(fx: Fixture, f: float, amps, jobs: int = 8, harmonics: int = 9) -> list[dict]:
    """THD (%) of the output and the peak B, per drive amplitude at frequency f."""
    fs = _settings().sample_rate

    def one(amp):
        x, a = _tone(f, amp, fs, periods=4, settle_s=max(0.1, 8 / f))
        r = run(fx, x)
        h = np.abs(_fit(r["out"][a:], f, fs, harmonics))
        return {
            "drive_v": float(amp),
            "b_peak_t": float(np.max(np.abs(r["b"][a:]))),
            "out_v_rms": float(h[0] / np.sqrt(2)),
            "thd_pct": float(100 * np.sqrt(np.sum(h[1:] ** 2)) / h[0]),
        }

    with ThreadPoolExecutor(jobs) as ex:
        return list(ex.map(one, amps))


def loop(fx: Fixture, f: float, amp: float, periods: int = 3) -> dict:
    """B (T) over the last period and H (A/m) along it; plus the field from a minor-loop
    drive (f at amp/2 plus 20 f at amp/10)."""
    fs = _settings().sample_rate
    p = nl.resolve()
    core = nl.transformer_core(fx.key, p)
    x, a = _tone(f, amp, fs, periods=periods, settle_s=max(0.1, 8 / f))
    b = run(fx, x)["b"]
    h = np.array(core.trace(b))
    last = slice(len(b) - int(round(fs / f)), len(b))
    t = np.arange(len(x)) / fs
    xm = 0.5 * x + 0.1 * amp * np.sin(2 * np.pi * 20 * f * t) * np.minimum(1.0, t / 0.005)
    bm = run(fx, xm)["b"]
    hm = np.array(core.trace(bm))
    return {
        "b": b[last],
        "h": h[last],
        "b_minor": bm[last],
        "h_minor": hm[last],
        "bsat_t": MU0 * core.ms_a_per_m,
    }


# --- The "done when" figures ----------------------------------------------------------------

FREQS_HZ = (10, 20, 30, 40, 100, 300, 1000, 3000, 10000, 15000, 20000, 30000, 40000)
FLUX_STEPS = (0.05, 0.2, 0.5, 0.8, 0.95, 1.05)  # peak B, fractions of mu0 Ms (30 Hz)


def summary(key: str, flux_steps=FLUX_STEPS) -> dict:
    """Frequency response re 1 kHz, THD at 30 Hz and 1 kHz against peak flux, and the
    30 Hz B-H loop near saturation (with minor loops), of transformer `key`."""
    fx = fixture(key)
    core = nl.transformer_core(key, nl.resolve())
    bsat = MU0 * core.ms_a_per_m
    g = frequency_response(fx, FREQS_HZ)
    g = g - g[FREQS_HZ.index(1000)]
    amp = drive_for_flux(fx, 30.0, 0.5 * bsat)  # small-signal estimate, refined by the runs
    drives = [amp * s / 0.5 for s in flux_steps]
    lf = thd(fx, 30.0, drives)
    hf = thd(fx, 1000.0, drives)
    lp = loop(fx, 30.0, amp * 0.95 / 0.5)
    return {
        "name": NAMES[key],
        "material": nl.resolve()[f"{key}_core_material"],
        "bsat_t": bsat,
        "freqs_hz": list(FREQS_HZ),
        "gain_db": [round(float(v), 3) for v in g],
        "thd_30hz": lf,
        "thd_1khz": hf,
        "loop": {k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in lp.items()},
    }
