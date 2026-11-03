"""A capsule circuit against its references (MIC_ROOM_PLAN.md A2) -> reports/mics/<circuit>/.

    uv run --extra fast python scripts/capsule_study.py [--circuit capsule_bk4134]

Three comparisons, each on the circuit file (a capsule driven by the pressure at its
front, `in`, pascals as volts; its electrode `out` into the preamp's input):

- the circuit against itself in the frequency domain: the open-circuit response from
  circuitsim's transient render (a multitone at the input) against the IR's AC solution
  (varimu.measure.ac): checks the macro, the builder and the engine on this network;
- the AC solution against the capsule's own closed form (varimu.devices.capsule
  .sensitivity) and against the published figures (the circuit file's `published`
  block): sensitivity at 250 Hz, the response's shape;
- self-noise: a render of silence with the circuit's noise sources on, its output
  spectrum against the AC noise prediction (every resistor's 4kT/R through the network),
  and the A-weighted equivalent noise level (the output noise over the sensitivity, re
  20 uPa) against the published one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.signal import welch

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.devices.capsule import sensitivity
from varimu.devices.library import _published, load_capsule
from varimu.measure import ac
from varimu.sim import fast
from varimu.sim.io import TransientSettings

P_REF = 20e-6
TONES = np.unique(np.round(np.geomspace(10.0, 40000.0, 45)))  # 1 Hz bins
PRE_S, WIN_S = 0.5, 1.0
NOISE_S = 4.0


def a_weight_db(f: np.ndarray) -> np.ndarray:
    """IEC 61672-1 A-weighting (dB; 0 at 1 kHz)."""
    f2 = np.asarray(f, float) ** 2
    ra = (12194.0**2 * f2**2) / (
        (f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194.0**2)
    )
    return 20 * np.log10(np.maximum(ra, 1e-30)) + 2.0


def multitone(fs: int, amp_pa: float) -> np.ndarray:
    t = np.arange(int((PRE_S + WIN_S) * fs)) / fs
    rng = np.random.default_rng(1)
    x = sum(amp_pa * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) for f in TONES)
    return x * np.minimum(1.0, t / 0.02)


def render_response(ir, s: TransientSettings) -> np.ndarray:
    fs = s.sample_rate
    x = multitone(fs, 0.01)
    v = fast.run_transient(ir, x, settings=s).vectors["v(out)"]
    k, n = int(PRE_S * fs), int(WIN_S * fs)
    bins = np.round(TONES * WIN_S).astype(int)
    return np.fft.rfft(v[k : k + n])[bins] / np.fft.rfft(x[k : k + n])[bins]


def render_noise(ir, s: TransientSettings) -> tuple[np.ndarray, np.ndarray]:
    fs = s.sample_rate
    v = fast.run_transient(ir, np.zeros(int(NOISE_S * fs)), settings=s).vectors["v(out)"]
    v = v[int(0.5 * fs) :]
    f, p = welch(v - np.mean(v), fs=fs, nperseg=int(0.25 * fs))
    return f, p


def equivalent_noise_dba(f: np.ndarray, psd_v2: np.ndarray, sens_v_pa: np.ndarray) -> float:
    """The output noise A-weighted over 20 Hz-20 kHz, referred to the input through the
    sensitivity, in dB re 20 uPa."""
    band = (f >= 20) & (f <= 20000)
    df = np.gradient(f)
    pa2 = psd_v2[band] / np.abs(sens_v_pa[band]) ** 2 * 10 ** (a_weight_db(f[band]) / 10)
    return float(10 * np.log10(np.sum(pa2 * df[band]) / P_REF**2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--circuit", default="capsule_bk4134")
    args = ap.parse_args()
    out_dir = REPO_ROOT / "reports" / "mics" / args.circuit
    out_dir.mkdir(parents=True, exist_ok=True)
    c = spec.load_circuit(spec.circuit_path(args.circuit))
    q = spec.resolve(c)
    s = TransientSettings.from_sim_settings(engine="circuitsim")
    quiet = builder.build(c, noise=False).ir
    noisy = builder.build(c, noise=True).ir
    capsule = load_capsule(str(q["capsule_model"]))
    published = _published().get(capsule.name, {}).get("published", {})

    h_ac = ac.transfer(quiet, TONES, "out")
    h_tr = render_response(quiet, s)
    h_cf = sensitivity(
        capsule, TONES, q["polarization_v"], q.get("c_load_f", 0.0), q.get("r_load_ohm", np.inf)
    )
    f250 = np.array([250.0])
    s250 = float(np.abs(ac.transfer(quiet, f250, "out"))[0])

    f_n, p_tr = render_noise(noisy, s)
    p_ac = ac.noise_psd(noisy, f_n, "out")
    sens_n = ac.transfer(quiet, f_n, "out")
    ok = (f_n >= 20) & (f_n <= 20000)
    report = {
        "circuit": args.circuit,
        "sensitivity_250hz_mv_pa": round(1e3 * s250, 3),
        "sensitivity_250hz_db_re_1v_pa": round(20 * np.log10(s250), 2),
        "transient_vs_ac_db": {
            "max_abs": round(float(np.max(np.abs(20 * np.log10(np.abs(h_tr / h_ac))))), 4),
            "below_20khz_max_abs": round(
                float(np.max(np.abs(20 * np.log10(np.abs(h_tr / h_ac)))[TONES <= 20000])), 4
            ),
        },
        "closed_form_vs_ac_db_max_abs": round(
            float(np.max(np.abs(20 * np.log10(np.abs(h_cf / h_ac))))), 6
        ),
        "response_re_250hz_db": {
            f"{f:g}": round(float(20 * np.log10(np.abs(h) / s250)), 2)
            for f, h in zip(TONES, h_ac, strict=True)
        },
        "noise": {
            "rendered_vs_ac_db_median": round(
                float(np.median(10 * np.log10(p_tr[ok] / p_ac[ok]))), 2
            ),
            "equivalent_dba_ac": round(equivalent_noise_dba(f_n, p_ac, sens_n), 2),
            "equivalent_dba_rendered": round(equivalent_noise_dba(f_n, p_tr, sens_n), 2),
        },
        "published": published,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    _plot(out_dir, report, h_ac, h_tr, s250, f_n, p_tr, p_ac, sens_n)
    print(json.dumps({k: v for k, v in report.items() if k != "response_re_250hz_db"}, indent=1))


def _plot(out_dir: Path, report, h_ac, h_tr, s250, f_n, p_tr, p_ac, sens_n) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.8))
    a1.semilogx(TONES, 20 * np.log10(np.abs(h_ac) / s250), label="AC solution")
    a1.semilogx(TONES, 20 * np.log10(np.abs(h_tr) / s250), "o", ms=3, label="transient render")
    pub = report["published"].get("response_db", {})
    if pub:
        fp = np.array([float(k) for k in pub])
        a1.plot(fp, list(pub.values()), "k^", label="published")
    a1.set_title(f"Pressure response re 250 Hz ({report['sensitivity_250hz_mv_pa']} mV/Pa)")
    a1.set_xlabel("Hz")
    a1.set_ylabel("dB")
    a1.set_ylim(-20, 6)
    ok = (f_n >= 10) & (f_n <= 40000)
    pa = 1.0 / np.abs(sens_n[ok])
    a2.semilogx(f_n[ok], 10 * np.log10(p_tr[ok] * pa**2 / P_REF**2), label="rendered")
    a2.semilogx(f_n[ok], 10 * np.log10(p_ac[ok] * pa**2 / P_REF**2), label="AC prediction")
    a2.set_title(
        "Self-noise re the input (dB re 20 uPa per Hz); "
        f"{report['noise']['equivalent_dba_rendered']} dB(A)"
    )
    a2.set_xlabel("Hz")
    for a in (a1, a2):
        a.grid(True, which="both", alpha=0.3)
        a.legend()
    fig.tight_layout()
    fig.savefig(out_dir / "capsule.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()
