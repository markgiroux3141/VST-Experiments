"""What B6's heated cathodes do to the tube synth (device builder B6; TUBE_SYNTH_PLAN.md S4).

    uv run --extra fast python scripts/heater_synth_study.py [--cold-s 60]

tube_synth.yaml at draft with the app's partition (as it plays), a held note at pitch
-15 V:
- the MAINS knob: the note's pitch at 110 / 120 / 127 V, heaters on and off (noise off): the
  cathodes' share of the pitch's dependence on the mains, beside B+'s;
- a cold start (power on, heaters cold, noise off): when the sound comes, and the pitch and
  level settling over `--cold-s` seconds (0.5 s windows);
- the mains wander (noise on, 20 s): the pitch's slow wander with the heaters following it
  and without.
-> reports/tube_synth/heaters/summary.json, warmup.png
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit import ir as I
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io
from varimu.synth import vco

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "tube_synth" / "heaters"
PANEL = {"cutoff": 0.7, "resonance": 0.3, "attack": 0.05, "release": 0.3, "wave": 1.0}
KEY_DOWN_V, PITCH_V = -1.0, -15.0
FULL_SCALE_V = 3.5

_t = importlib.util.spec_from_file_location("t", ROOT / "tests" / "test_tube_synth.py")
_tm = importlib.util.module_from_spec(_t)
_t.loader.exec_module(_tm)
PARTITION = _tm.PARTITION


def render(seconds: float, *, mains_v=120.0, heaters="warm", noise=False):
    s = spec.load_circuit(CONFIG_DIR / "circuits" / "tube_synth.yaml")
    p = spec.resolve(s, {**PANEL, "mains_v_rms": mains_v})
    ir = builder.build_ir(s, p, cores="ja", noise=None if noise else False, heaters=heaters)
    ir = dataclasses.replace(ir, probes=(I.VoltageProbe("out"), I.VoltageProbe("o_t")))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality="draft"),
        full_scale_volts_peak=1.0,
        partition=PARTITION,
    )
    n = int(seconds * st.sample_rate)
    ctl = {"gate": np.full(n, KEY_DOWN_V), "pitch": np.full(n, PITCH_V)}
    v = fast.run_transient(ir, np.zeros(n), settings=st, controls=ctl).vectors
    return v["v(out)"], v["v(o_t)"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cold-s", type=float, default=60.0)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    fs = io.load_sim_settings().sample_rate
    jobs = {
        **{
            ("mains", mv, h): (6.0, dict(mains_v=mv, heaters=h))
            for mv in (110.0, 120.0, 127.0)
            for h in ("warm", False)
        },
        ("cold",): (a.cold_s, dict(heaters="cold")),
        ("wander", "warm"): (20.0, dict(heaters="warm", noise=True)),
        ("wander", False): (20.0, dict(heaters=False, noise=True)),
    }
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {k: ex.submit(render, s, **kw) for k, (s, kw) in jobs.items()}
        res = {k: f.result() for k, f in futs.items()}
    out: dict = {"pitch_v": PITCH_V, "panel": PANEL}

    # The MAINS knob.
    f0 = {k: vco.frequency(res[k][1][int(1.0 * fs) :], fs) for k in res if k[0] == "mains"}
    rows = {}
    for h in ("warm", False):
        hz = [f0[("mains", mv, h)] for mv in (110.0, 120.0, 127.0)]
        c = vco.cents(np.array(hz), hz[1])
        rows["heaters" if h else "no heaters"] = {
            "hz": hz,
            "cents_re_120": c.tolist(),
            "cents_per_v": float((c[2] - c[0]) / 17.0),
        }
    out["mains_knob"] = rows

    # The cold start.
    y, tank = res[("cold",)]
    w = int(0.5 * fs)
    final = vco.frequency(tank[-int(5 * fs) :], fs)
    trace = []
    for i in range(len(y) // w):
        seg_y, seg_t = y[i * w : (i + 1) * w], tank[i * w : (i + 1) * w]
        rms = float(np.sqrt(np.mean((seg_y - np.mean(seg_y)) ** 2)))
        f = vco.frequency(seg_t, fs)
        trace.append(
            {
                "t_s": (i + 0.5) * 0.5,
                "out_dbfs": float(20 * np.log10(max(rms, 1e-12) / FULL_SCALE_V)),
                "cents_re_final": None if not np.isfinite(f) else float(vco.cents(f, final)),
            }
        )
    loud = max(t["out_dbfs"] for t in trace)
    sound_at = next((t["t_s"] for t in trace if t["out_dbfs"] > loud - 20), None)
    out["cold_start"] = {"final_hz": final, "sound_within_20db_at_s": sound_at, "trace": trace}

    # The mains wander.
    wander = {}
    for h in ("warm", False):
        tank = res[("wander", h)][1][int(1.0 * fs) :]
        f00 = vco.frequency(tank, fs)
        t, f = vco.cycle_frequencies(tank, fs, lowpass_hz=3 * f00)
        slow = vco.cents(vco.smoothed(t, f, 0.1), f00)
        wander["heaters" if h else "no heaters"] = {
            "cents_rms": float(np.std(slow)),
            "cents_pp": float(np.ptp(slow)),
        }
    out["mains_wander"] = wander

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "summary.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "cold_start"}, indent=1))
    cs = out["cold_start"]
    print(f"cold start: within 20 dB at {cs['sound_within_20db_at_s']} s, {cs['final_hz']:.1f} Hz")
    for t in cs["trace"][:: max(1, len(cs["trace"]) // 20)]:
        print(t)
    plot(out, OUT_DIR / "warmup.png")


def plot(out: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tr = out["cold_start"]["trace"]
    t = [x["t_s"] for x in tr]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 5.5), sharex=True)
    a1.plot(t, [x["out_dbfs"] for x in tr])
    a1.set_ylabel("output dBFS (rms)")
    a1.set_title("tube synth from cold (heaters cold at 0 s), a held note")
    a2.plot(t, [np.nan if x["cents_re_final"] is None else x["cents_re_final"] for x in tr])
    a2.set_ylabel("cents re the warm pitch")
    a2.set_xlabel("s")
    a2.set_ylim(-200, 200)
    fig.tight_layout()
    fig.savefig(path, dpi=110)


if __name__ == "__main__":
    main()
