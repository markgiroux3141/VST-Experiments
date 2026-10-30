"""Tube synth S4: the oscillator candidates measured side by side (docs/TUBE_SYNTH_PLAN.md).

Each candidate is its own circuit file with a `pitch` control input and no audio input
in use (`CANDIDATES`). Every run builds the circuit with Jiles-Atherton cores (the synth
devices' cores in every quality) and holds the pitch voltage through the render's settling
(sim_settings start.settle_s), so the oscillation is established when the kept part begins.
Measured at production, draft (96 kHz internal: the native app's draft-2x) and draft-1x
(a 48 kHz host):
- pitch against the pitch voltage (the range, octaves per volt, the deviation from an
  exponential law in cents), from the pitch probe;
- the glide after a pitch step (time until the pitch, averaged over 50 ms so ripple FM
  doesn't count, stays within 10 cents of the new pitch);
- the held note's frequency per cycle (ripple FM, drift within the run);
- pitch against the mains voltage (105 / 120 / 127 V: supply sensitivity);
- each output's waveform and harmonics, and its inharmonic power: all of it, and off the
  supply ripple's FM sidebands (aliases and noise: compare the qualities; read it at the
  highest plotted pitch, where the sidebands mask least; varimu.synth.vco);
- speed: wall clock per second of audio, one run at a time.
Results: reports/tube_synth/vco/<candidate>.json and .png.

    uv run --extra fast python scripts/vco_study.py [--only lc ...]
        [--qualities production draft draft-1x]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import CONFIG_DIR
from varimu.sim import fast, io
from varimu.synth import vco

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "tube_synth" / "vco"
QUALITIES = ("production", "draft", "draft-1x")
HOLD_S = 1.0  # kept per sweep point (after the settling)
RIPPLE_SIDEBANDS_HZ = (
    60.0,
    120.0,
    180.0,
    240.0,
)  # the 60 Hz supply's FM sidebands, masked for aliasing
GLIDE_SMOOTH_S = 0.05  # the glide is read on the per-cycle pitch averaged over this


@dataclasses.dataclass(frozen=True)
class Candidate:
    circuit: str
    pitch_probe: str  # the node whose zero crossings give the pitch
    outputs: tuple[str, ...]  # the waveforms reported
    sweep_v: tuple[float, ...]  # pitch voltages of the pitch-against-control sweep
    step_v: tuple[float, float]  # the glide test's step
    note_v: float  # the held note, the mains test's and the waveform plots' middle pitch
    plot_v: tuple[float, ...]  # waveform plots
    pitch_lowpass_hz: float | None = None


CANDIDATES = {
    "lc": Candidate(
        circuit="vco_lc",
        pitch_probe="t",
        outputs=("t", "out"),
        sweep_v=(-42.0, -38.0, -34.0, -30.0, -25.0, -20.0, -15.0, -10.0, -5.0, 0.0),
        step_v=(-30.0, -20.0),
        note_v=-25.0,
        plot_v=(-42.0, -25.0, 0.0),
    ),
}


def render(
    c: Candidate, quality: str, pitch_v: np.ndarray, sets: dict | None = None
) -> tuple[dict[str, np.ndarray], float]:
    s = spec.load_circuit(CONFIG_DIR / "circuits" / f"{c.circuit}.yaml")
    ir = builder.build_ir(s, spec.resolve(s, sets or {}), cores="ja")
    probes = tuple(dict.fromkeys((c.pitch_probe, *c.outputs)))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in probes))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    t0 = time.perf_counter()
    v = fast.run_transient(ir, np.zeros(len(pitch_v)), settings=st, controls={"pitch": pitch_v})
    wall = time.perf_counter() - t0
    return {p: v.vectors[f"v({p})"] for p in probes}, wall


def held(c: Candidate, quality: str, v: float, dur_s: float = HOLD_S, sets=None):
    fs = io.load_sim_settings().sample_rate
    return render(c, quality, np.full(int(dur_s * fs), float(v)), sets)


def measure(name: str, c: Candidate, qualities: tuple[str, ...], workers: int) -> dict:
    fs = io.load_sim_settings().sample_rate
    settle_s = float(io.load_sim_settings().data["start"]["settle_s"])
    res: dict = {"circuit": c.circuit, "sample_rate": fs, "qualities": {}}
    for q in qualities:
        print(f"{name} {q}: sweep", flush=True)
        with ThreadPoolExecutor(workers) as ex:
            sweep = list(ex.map(lambda v, q=q: held(c, q, v), c.sweep_v))
        f = np.array(
            [vco.frequency(r[c.pitch_probe], fs, lowpass_hz=c.pitch_lowpass_hz) for r, _ in sweep]
        )
        ok = np.isfinite(f)
        slope, icpt = (
            np.polyfit(np.array(c.sweep_v)[ok], np.log2(f[ok]), 1)
            if ok.sum() > 1
            else (np.nan, np.nan)
        )
        dev = 1200 * (np.log2(f) - (slope * np.array(c.sweep_v) + icpt))
        outs = {}
        for v, (r, _) in zip(c.sweep_v, sweep, strict=True):
            if v not in c.plot_v:
                continue
            f0 = vco.frequency(r[c.pitch_probe], fs, lowpass_hz=c.pitch_lowpass_hz)
            fc = vco.cycle_frequencies(r[c.pitch_probe], fs, lowpass_hz=c.pitch_lowpass_hz)[1]
            spread = float(np.percentile(fc, 97.5) - np.percentile(fc, 2.5)) if len(fc) > 3 else 0.0
            outs[str(v)] = {
                o: {
                    "peak_to_peak_v": float(np.ptp(r[o])),
                    "pitch_spread_hz": round(spread, 2),
                    "harmonics_db": [
                        round(float(h), 1) for h in vco.harmonics_db(r[o], fs, f0, 12)
                    ],
                    "inharmonic_db": round(vco.inharmonic_db(r[o], fs, f0), 1),
                    "inharmonic_off_ripple_db": round(
                        vco.inharmonic_db(
                            r[o], fs, f0, sidebands_hz=RIPPLE_SIDEBANDS_HZ, spread_hz=spread
                        ),
                        1,
                    ),
                }
                for o in c.outputs
            }

        print(f"{name} {q}: step, mains, held note", flush=True)
        n_step = int(1.5 * fs)
        step = np.full(n_step, c.step_v[0])
        step[int(0.3 * fs) :] = c.step_v[1]
        with ThreadPoolExecutor(workers) as ex:
            jobs = {
                "step": ex.submit(render, c, q, step),
                "note": ex.submit(held, c, q, c.note_v, 3.0),
                **{
                    m: ex.submit(held, c, q, c.note_v, HOLD_S, {"mains_v_rms": m})
                    for m in (105.0, 127.0)
                },
            }
            got = {k: j.result() for k, j in jobs.items()}
        ts, fc = vco.cycle_frequencies(
            got["step"][0][c.pitch_probe], fs, lowpass_hz=c.pitch_lowpass_hz
        )
        final = np.median(fc[ts > 1.2])
        sm = vco.smoothed(ts, fc, GLIDE_SMOOTH_S)  # ripple FM isn't glide
        off = (ts > 0.3) & (np.abs(vco.cents(sm, final)) > 10.0)
        glide_s = float(ts[off].max() - 0.3) if off.any() else 0.0
        tn, fn = vco.cycle_frequencies(
            got["note"][0][c.pitch_probe], fs, lowpass_hz=c.pitch_lowpass_hz
        )
        f_note = float(np.median(fn))
        cn = vco.cents(fn, f_note)
        f_mains = {
            m: vco.frequency(got[m][0][c.pitch_probe], fs, lowpass_hz=c.pitch_lowpass_hz)
            for m in (105.0, 127.0)
        }
        _, wall = held(c, q, c.note_v)  # alone: the parallel runs' walls share the cores
        res["qualities"][q] = {
            "sweep": {
                "pitch_v": list(c.sweep_v),
                "hz": [round(float(x), 2) for x in f],
                "octaves_per_v": round(float(slope), 4),
                "range_octaves": round(float(np.log2(np.nanmax(f) / np.nanmin(f))), 2),
                "cents_off_exponential": [round(float(x), 0) for x in dev],
            },
            "outputs": outs,
            "glide": {
                "from_v": c.step_v[0],
                "to_v": c.step_v[1],
                "to_within_10_cents_s": round(glide_s, 3),
            },
            "held_note": {
                "pitch_v": c.note_v,
                "hz": round(f_note, 2),
                "cycle_cents_rms": round(float(np.std(cn)), 2),
                "cycle_cents_pp": round(float(np.ptp(cn)), 2),
                "first_vs_last_second_cents": round(
                    float(np.median(cn[tn > tn[-1] - 1.0]) - np.median(cn[tn < tn[0] + 1.0])), 2
                ),
            },
            "mains_cents_per_v": round(
                float(vco.cents(f_mains[127.0], f_mains[105.0]) / (127.0 - 105.0)), 2
            ),
            "speed_x_real_time": round(float(wall / (HOLD_S + settle_s)), 2),
        }
        res["qualities"][q]["_plot"] = {
            "sweep": {
                str(v): {o: r[o] for o in c.outputs}
                for v, (r, _) in zip(c.sweep_v, sweep, strict=True)
                if v in c.plot_v
            },
            "freqs": {
                str(v): vco.frequency(r[c.pitch_probe], fs)
                for v, (r, _) in zip(c.sweep_v, sweep, strict=True)
            },
            "step": (ts, fc),
            "note": (tn, cn),
        }
        print(
            json.dumps({k: v for k, v in res["qualities"][q].items() if k != "_plot"}, indent=1),
            flush=True,
        )
    return res


def plot(name: str, res: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fs = res["sample_rate"]
    qs = list(res["qualities"])
    prod = res["qualities"][qs[0]]
    plot_v = list(prod["_plot"]["sweep"])
    outs = list(next(iter(prod["_plot"]["sweep"].values())))
    fig, ax = plt.subplots(2 + len(outs), 3, figsize=(15, 4 * (2 + len(outs))))
    for q in qs:
        sw = res["qualities"][q]["sweep"]
        ax[0, 0].semilogy(sw["pitch_v"], sw["hz"], "o-", label=q)
        ax[0, 1].plot(sw["pitch_v"], sw["cents_off_exponential"], "o-", label=q)
        ts, fc = res["qualities"][q]["_plot"]["step"]
        ax[0, 2].plot(ts, fc, label=q)
        tn, cn = res["qualities"][q]["_plot"]["note"]
        ax[1, 0].plot(tn, cn, label=q)
    ax[0, 0].set(title="pitch against control", xlabel="pitch input (V)", ylabel="Hz")
    ax[0, 1].set(
        title="deviation from the best exponential", xlabel="pitch input (V)", ylabel="cents"
    )
    ax[0, 2].set(title="glide after a pitch step", xlabel="s", ylabel="Hz per cycle")
    ax[1, 0].set(title="held note, per cycle", xlabel="s", ylabel="cents re median")
    for a in ax[0]:
        a.legend()
    ax[1, 0].legend()
    sw = prod["_plot"]["sweep"]
    for v in plot_v:
        f0 = prod["_plot"]["freqs"][v]
        for i, o in enumerate(outs):
            y = sw[v][o]
            n = int(2.5 * fs / f0)
            ax[2 + i, 0].plot(
                np.arange(n) / fs * 1e3, y[-n:] - np.mean(y), label=f"{v} V, {f0:.0f} Hz"
            )
    for q in qs:
        for i, o in enumerate(outs):
            v = plot_v[-1]
            y = res["qualities"][q]["_plot"]["sweep"][v][o]
            y = (y - y.mean()) * np.hanning(len(y))
            p = 20 * np.log10(np.abs(np.fft.rfft(y)) + 1e-12)
            fr = np.fft.rfftfreq(len(y), 1 / fs)
            ax[2 + i, 1 if q == qs[0] else 2].plot(fr / 1e3, p - p.max(), lw=0.5, label=q)
    for i, o in enumerate(outs):
        ax[2 + i, 0].set(title=f"{o}: waveforms (production)", xlabel="ms", ylabel="V")
        ax[2 + i, 0].legend()
        for j in (1, 2):
            ax[2 + i, j].set(
                title=f"{o}: spectrum at {plot_v[-1]} V",
                xlabel="kHz",
                ylabel="dB",
                ylim=(-140, 5),
                xlim=(0, 24),
            )
            ax[2 + i, j].legend()
    ax[1, 1].axis("off")
    ax[1, 2].axis("off")
    fig.suptitle(f"S4 candidate {name}: {res['circuit']}")
    fig.tight_layout()
    fig.savefig(path, dpi=80)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", nargs="*", choices=list(CANDIDATES))
    ap.add_argument("--qualities", nargs="*", default=list(QUALITIES), choices=list(QUALITIES))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    for name in a.only or CANDIDATES:
        res = measure(name, CANDIDATES[name], tuple(a.qualities), a.workers)
        plot(name, res, a.out / f"{name}.png")
        for q in res["qualities"].values():
            q.pop("_plot")
        (a.out / f"{name}.json").write_text(json.dumps(res, indent=1) + "\n")
        print(f"wrote {a.out / name}.json / .png")


if __name__ == "__main__":
    main()
