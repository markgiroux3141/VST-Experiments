"""CL2: the D6's electronics (config/circuits/clavinet_d6.yaml, drawn from Hohner's E7
schematic) against [G13]: the idle point, the tone rockers' responses (Fig. 11's shapes:
TREBLE's peak, ALL's notch, BRILLIANT's high-pass, all off silent), the amp with the tone
stack removed (G13's simulation: nearly flat, -3 dB at 130 Hz, +3 dB at 4 kHz) and THD at
1 kHz against the pickup's EMF (G13's measurement: 1% at the largest normal level, 3.6% on
fortissimo chord peaks; `--level` prints the EMF at 1% and 3.6%, d6.yaml's `level_v`)
-> reports/clavinet/amp/.

    uv run --extra fast python scripts/clavinet_amp_study.py [--set k=v ...] [--level]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.circuit.ir import VoltageProbe  # noqa: E402
from varimu.config import CONFIG_DIR  # noqa: E402
from varimu.sim import fast, io  # noqa: E402

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "clavinet" / "amp"
CIRCUIT = CONFIG_DIR / "circuits" / "clavinet_d6.yaml"
FS = 96000
PROBES = ("out", "x", "sel", "ts", "b1", "c1", "b2", "c2", "e2", "vcc", "zb")
TONES = {
    "ALL": dict(soft=1, medium=1, treble=1, brilliant=1),
    "SOFT": dict(soft=1, medium=0, treble=0, brilliant=0),
    "MEDIUM": dict(soft=0, medium=1, treble=0, brilliant=0),
    "TREBLE": dict(soft=0, medium=0, treble=1, brilliant=0),
    "BRILLIANT": dict(soft=0, medium=0, treble=0, brilliant=1),
    "NONE": dict(soft=0, medium=0, treble=0, brilliant=0),
}


def render(sets: dict, emf: np.ndarray, quality: str = "production") -> dict[str, np.ndarray]:
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in PROBES))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    z = np.zeros_like(emf)
    v = fast.run_transient(
        ir, z, settings=st, controls={"centre": emf, "bridge": z, "bridge_neg": z}
    ).vectors
    return {p: np.asarray(v[f"v({p})"]) for p in PROBES}


def multisine(freqs: np.ndarray, amp_v: float, n: int) -> np.ndarray:
    t = np.arange(n) / FS
    rng = np.random.default_rng(1)
    ph = rng.uniform(0, 2 * np.pi, freqs.size)
    return (
        amp_v
        * np.sum(np.sin(2 * np.pi * freqs[:, None] * t + ph[:, None]), axis=0)
        / np.sqrt(freqs.size)
    )


def tone_bins(x: np.ndarray, freqs: np.ndarray) -> np.ndarray:
    spec_ = np.fft.rfft(x)
    return spec_[np.round(freqs * x.size / FS).astype(int)]


def thd(x: np.ndarray, f0: float, harmonics: int = 10) -> float:
    n = x.size
    w = np.hanning(n)
    s = np.abs(np.fft.rfft(x * w))
    k0 = int(round(f0 * n / FS))
    fund = s[k0 - 2 : k0 + 3].max()
    h = [s[k * k0 - 2 : k * k0 + 3].max() for k in range(2, harmonics + 1) if k * k0 + 3 < s.size]
    return float(np.sqrt(np.sum(np.square(h))) / fund)


def thd_at(sets: dict, emf_peak_v: float) -> tuple[float, float]:
    n = int(0.4 * FS)
    t = np.arange(n) / FS
    v = render(sets, emf_peak_v * np.sin(2 * np.pi * 1000 * t))
    seg = v["out"][n // 2 :]
    return thd(seg, 1000.0), float(np.max(np.abs(seg)))


# the tone stack removed ([G13] 2.3.6's simulation): SOFT's cell active and open, the
# others shorted, so nothing loads the chain node
NO_STACK = dict(soft=1, medium=0, treble=0, brilliant=0, r_soft_ohm=1e12, c_soft_f=1e-18)


def amp_shelf(sets: dict) -> dict[str, float]:
    """The amp with the tone stack removed: out over the pickup's EMF at 130 Hz and 4 kHz
    against 1 kHz (dB), and at 1 kHz itself."""
    freqs = np.array([130.0, 1000.0, 4000.0])
    x_in = multisine(freqs, 0.002, FS // 2)
    v = render({**sets, **NO_STACK}, x_in)
    db = 20 * np.log10(np.abs(tone_bins(v["out"], freqs) / tone_bins(x_in, freqs)))
    return {"130": float(db[0] - db[1]), "4000": float(db[2] - db[1]), "1000": float(db[1])}


def _bisect(f, lo: float, hi: float, target: float, rising: bool, steps: int = 14) -> float:
    """log bisection of f(x) = target, f rising (or falling) in x on [lo, hi]."""
    a, b = np.log(lo), np.log(hi)
    for _ in range(steps):
        m = 0.5 * (a + b)
        above = f(float(np.exp(m))) > target
        a, b = (a, m) if above == rising else (m, b)
    return float(np.exp(0.5 * (a + b)))


def thd_levels(sets: dict) -> dict[str, float]:
    """The centre pickup's EMF (1 kHz, peak) at which the amp reaches 1% and 3.6% THD."""
    f = lambda a: thd_at({**sets, "pickup_select": 0}, a)[0]  # noqa: E731
    return {
        "emf_1pct_v": _bisect(f, 0.005, 0.5, 0.01, rising=True, steps=16),
        "emf_3p6pct_v": _bisect(f, 0.005, 0.5, 0.036, rising=True, steps=16),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", nargs="*", default=[])
    ap.add_argument(
        "--level",
        action="store_true",
        help="print the EMF at 1% and 3.6% THD (d6.yaml's level_v is half the first)",
    )
    args = ap.parse_args()
    base = dict(kv.split("=", 1) for kv in args.set)
    base = {k: float(v) for k, v in base.items()}
    if args.level:
        print(json.dumps(thd_levels(base), indent=1))
        return
    base.setdefault("pickup_select", 0)
    OUT.mkdir(parents=True, exist_ok=True)
    out: dict = {"sets": base}

    # the idle point
    n = int(0.05 * FS)
    v = render(base, np.zeros(n))
    out["idle_v"] = {p: float(v[p][-1]) for p in PROBES}

    # the tone rockers: a quiet multisine on the centre pickup's EMF (both stages linear)
    n = FS  # 1 s: 1 Hz bins
    freqs = np.unique(np.round(np.geomspace(40, 15000, 60)))
    x_in = multisine(freqs, 0.01, n)
    inb = tone_bins(x_in, freqs)
    resp = {}
    for name, sw in TONES.items():
        v = render({**base, **sw}, x_in)
        hx = tone_bins(v["x"], freqs) / inb
        ho = tone_bins(v["out"], freqs) / inb
        resp[name] = {
            "x_db": (20 * np.log10(np.abs(hx) + 1e-30)).tolist(),
            "out_db": (20 * np.log10(np.abs(ho) + 1e-30)).tolist(),
        }
    # the amp with the tone stack removed: out over the EMF
    v = render({**base, **NO_STACK}, x_in)
    resp["AMP"] = {"gain_db": (20 * np.log10(np.abs(tone_bins(v["out"], freqs) / inb))).tolist()}
    out["freqs_hz"] = freqs.tolist()
    out["tone"] = resp
    f = freqs
    tre = np.array(resp["TREBLE"]["x_db"])
    all_ = np.array(resp["ALL"]["x_db"])
    band = (f > 2000) & (f < 6000)
    out["checks"] = {
        "treble_peak_hz": float(f[np.argmax(tre)]),
        "all_peak_hz": float(f[np.argmax(all_)]),
        "all_notch_hz": float(f[band][np.argmin(all_[band])]),
        "none_max_db": float(np.max(resp["NONE"]["x_db"])),
        "none_below_all_db": float(np.max(all_) - np.max(resp["NONE"]["x_db"])),
        "treble_peak_db": float(np.max(tre)),
        "brilliant_10k_db": float(np.interp(10000, f, resp["BRILLIANT"]["x_db"])),
        "amp_gain_1k_db": float(np.interp(1000, f, resp["AMP"]["gain_db"])),
        "amp_gain_130_db": float(np.interp(130, f, resp["AMP"]["gain_db"])),
        "amp_gain_4k_db": float(np.interp(4000, f, resp["AMP"]["gain_db"])),
    }

    # THD at 1 kHz against the EMF's level (the default rockers)
    n = int(0.5 * FS)
    t = np.arange(n) / FS
    rows = []
    for amp in (0.01, 0.02, 0.04, 0.08, 0.16, 0.32):
        v = render(base, amp * np.sin(2 * np.pi * 1000 * t))
        seg = v["out"][n // 2 :]
        rows.append(
            {
                "emf_peak_v": amp,
                "thd": thd(seg, 1000.0),
                "out_peak_v": float(np.max(np.abs(seg))),
                "base_peak_v": float(np.ptp(v["b1"][n // 2 :]) / 2),
            }
        )
    out["thd"] = rows
    out["shelf_db"] = amp_shelf(base)
    out["thd_levels"] = thd_levels(base)
    (OUT / "summary.json").write_text(json.dumps(out, indent=1))

    fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
    for name in TONES:
        if name != "NONE":
            ax[0].semilogx(f, resp[name]["x_db"], label=name)
    ax[0].set_title("tone rockers: chain node / pickup EMF ([G13] Fig. 11)")
    ax[0].set_xlabel("Hz")
    ax[0].set_ylabel("dB")
    ax[0].legend()
    ax[0].grid(True, which="both", alpha=0.3)
    ax[1].semilogx(f, resp["AMP"]["gain_db"])
    ax[1].set_title("the amp, tone stack removed: out / pickup EMF (volume at default)")
    ax[1].grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "amp.png", dpi=110)
    print(
        json.dumps(
            {
                "idle": out["idle_v"],
                "checks": out["checks"],
                "shelf": out["shelf_db"],
                "thd": rows,
                "thd_levels": out["thd_levels"],
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
