"""The spring reverb's report (docs/REVERB_PLAN.md, E1-E4) -> reports/reverb/spring/.

    uv run --extra fast --extra listen python scripts/spring_report.py [--only tank device audio]
        [--quality draft-1x] [--clip "Dry Guitar.wav" --start 0 --seconds 12]

- tank: the tank's springs alone (varimu.devices.spring, ACC4AB3C1B@1): each spring's
  response from a force at its input bead to its output bead's velocity, as a spectrogram
  with the theory's arrival times over it (the first arrival and the first two echoes on
  each of the audio branch's three wavenumbers below F_C: L / |v_g| times 1, 3, 5), the
  closed forms T_D and F_C (Parker & Bilbao, appendix B) against the response's own (the
  echo spacing from the low band's envelope autocorrelation; the dispersion's peak), and
  the tank's response as a WAV.
- device: the Fender 6G15 (config/circuits/fender_6g15.yaml) with MIXER fully wet: an
  impulse at the input, the wet output's octave-band decay (Schroeder; the run without the
  impulse subtracted) against the tank's decay table, its spectrogram; per DWELL a 1 kHz
  tone at -12 dBFS: the tank's drive current, its THD and the wet level; the idle hum at the
  output (dry and wet).
- audio: a clip through the whole unit at its default panel (DWELL 0.3, MIXER 0.4: the dry
  plus the wet as the unit mixes them), at DWELL 0.9 / MIXER 0.5 (the drive into the tank's
  saturation), and fully wet.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.signal import butter, sosfilt, spectrogram  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.devices import spring as sp  # noqa: E402
from varimu.devices.library import load_spring_tank  # noqa: E402
from varimu.sim import fast  # noqa: E402
from varimu.sim.io import TransientSettings, load_audio, write_audio  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "reverb" / "spring"
TANK = "ACC4AB3C1B@1"
CIRCUIT = "fender_6g15"
BANDS_HZ = [125, 250, 500, 1000, 2000, 4000]


def band_t60(y: np.ndarray, fs: float, fc: float) -> float:
    """T60 of the octave band at fc: Schroeder's integral, its -5 to -25 dB, times 3."""
    sos = butter(4, [fc / np.sqrt(2), fc * np.sqrt(2)], btype="band", fs=fs, output="sos")
    e = sosfilt(sos, y) ** 2
    sch = np.cumsum(e[::-1])[::-1]
    db = 10 * np.log10(sch / sch[0] + 1e-30)
    t = np.arange(len(db)) / fs
    sel = (db <= -5) & (db >= -25)
    if sel.sum() < 10:
        return float("nan")
    return float(-60.0 / np.polyfit(t[sel], db[sel], 1)[0])


def group_velocity(c2: float, r: float, k: float, beta: np.ndarray) -> np.ndarray:
    om, _ = sp.branch(c2, r, k, beta)
    return np.gradient(om, beta)


def tank(summary: dict) -> None:
    c = load_spring_tank(TANK)
    fs = 48000.0
    rows = []
    fig, axes = plt.subplots(len(c.springs), 1, figsize=(10, 4.2 * len(c.springs)))
    axes = np.atleast_1d(axes)
    whole = sp.impulse_response(sp.spec_of(c, 0.45 * fs), fs)
    write_audio(OUT / "tank_response.wav", whole / np.abs(whole).max() * 0.5, int(fs))
    for ax, s in zip(axes, c.springs, strict=True):
        r, big_r, length = 0.5 * s.wire_diameter_m, 0.5 * s.helix_diameter_m, s.wire_length_m()
        one = dataclasses.replace(sp.spec_of(c, 0.45 * fs), springs=((r, big_r, length),))
        h = sp.impulse_response(one, fs)
        f, t, sxx = spectrogram(h[: int(0.6 * fs)], fs, nperseg=512, noverlap=480)
        db = 10 * np.log10(sxx + 1e-30)
        ax.pcolormesh(t, f, db, vmin=db.max() - 70, vmax=db.max(), shading="auto", cmap="gray_r")
        # The theory's arrivals: each wavenumber below F_C, L / |v_g| times 1, 3, 5.
        c2 = c.youngs_pa / c.density_kg_m3
        k = 1.0 / big_r
        beta = np.linspace(1e-3 * k, 1.6 * k, 40000)
        om, _ = sp.branch(c2, r, k, beta)
        vg = np.abs(np.gradient(om, beta))
        fc_hz = om[beta < k].max() / (2 * math.pi)
        for part, col in (
            (beta < beta[np.argmax(np.where(beta < k, om, 0))], "tab:red"),
            ((beta > beta[np.argmax(np.where(beta < k, om, 0))]) & (beta < k), "tab:blue"),
            (beta > k, "tab:green"),
        ):
            fh = om[part] / (2 * math.pi)
            keep = (fh < min(8000.0, 0.95 * fc_hz if col != "tab:green" else 8000.0)) & (fh > 50)
            for m in (1, 3, 5):
                ax.plot(m * length / vg[part][keep], fh[keep], color=col, lw=0.8, alpha=0.8)
        td = sp.delay_s(r, big_r, length, c.youngs_pa, c.density_kg_m3)
        fc = sp.transition_hz(r, big_r, c.youngs_pa, c.density_kg_m3)
        ax.axhline(fc, color="k", ls=":", lw=0.8)
        # The echo spacing from the response: the 100-1000 Hz band's envelope's
        # autocorrelation peak past 10 ms.
        sos = butter(4, [100, 1000], btype="band", fs=fs, output="sos")
        env = np.abs(sosfilt(sos, h[: int(1.5 * fs)]))
        env = env - env.mean()
        ac = np.correlate(env, env, "full")[len(env) - 1 :]
        lo = int(0.01 * fs)
        td_meas = (lo + int(np.argmax(ac[lo : int(0.2 * fs)]))) / fs
        ax.set_xlim(0, 0.6)
        ax.set_ylim(0, 8000)
        ax.set_ylabel("Hz")
        ax.set_title(
            f"spring: {s.turns:g} turns of {1e3 * s.wire_diameter_m:g} mm wire on "
            f"{1e3 * s.helix_diameter_m:g} mm, L {length:.2f} m: T_D {1e3 * td:.1f} ms "
            f"(response {1e3 * td_meas:.1f}), F_C {fc:.0f} Hz (dispersion {fc_hz:.0f})",
            fontsize=9,
        )
        rows.append(
            {
                "wire_length_m": length,
                "td_formula_s": td,
                "td_response_s": td_meas,
                "fc_formula_hz": fc,
                "fc_dispersion_hz": fc_hz,
                "modes": int(
                    len(
                        sp.spring_modes(c.density_kg_m3, c.youngs_pa, r, big_r, length, 0.45 * fs)[
                            0
                        ]
                    )
                ),
            }
        )
    axes[-1].set_xlabel("s")
    fig.suptitle(
        "Spring tank ACC4AB3C1B@1: each spring's response (force at the input bead to the "
        "output bead's velocity)\nlines: the theory's arrivals, x1, x3, x5 (red, blue, green: "
        "the three wavenumbers of a frequency below F_C); dotted: F_C",
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(OUT / "tank_spectrogram.png", dpi=110)
    plt.close(fig)
    summary["tank"] = {"springs": rows}
    print(json.dumps(summary["tank"], indent=1))


def device(summary: dict, quality: str) -> None:
    c = spec.load_circuit(spec.circuit_path(CIRCUIT))
    tank_c = load_spring_tank(TANK)
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    fs = float(st.sample_rate)
    v_in, v_out = c.full_scale
    n = int(6.0 * fs)
    x = np.zeros(n)
    x[int(0.01 * fs)] = 0.5 * fs / 48000.0  # an impulse of 0.5 V at 48 kHz's sample
    wet = {"mixer": 1.0}
    ir = builder.build(c, wet).ir
    t0 = time.perf_counter()
    full = np.asarray(fast.run_transient(ir, x, settings=st).vectors["v(out)"])
    wall = time.perf_counter() - t0
    quiet_r = fast.run_transient(ir, np.zeros_like(x), settings=st).vectors
    quiet = np.asarray(quiet_r["v(out)"])
    y = (full - quiet)[int(0.01 * fs) :]
    table = sp.decay_table(tank_c.t60_500hz_s, tank_c.loss_factor)
    t60 = [band_t60(y, fs, f) for f in BANDS_HZ]
    want = [sp.SIX_LN10 / float(sp.energy_decay(table, np.array([f], float))[0]) for f in BANDS_HZ]
    f, t, sxx = spectrogram(y[: int(1.2 * fs)], fs, nperseg=1024, noverlap=960)
    db = 10 * np.log10(sxx + 1e-30)
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.5))
    ax[0].pcolormesh(t, f, db, vmin=db.max() - 70, vmax=db.max(), shading="auto", cmap="gray_r")
    ax[0].set_ylim(0, 8000)
    ax[0].set_xlabel("s")
    ax[0].set_ylabel("Hz")
    ax[0].set_title("6G15, MIXER wet: an impulse's wet output", fontsize=9)
    ax[1].semilogx(BANDS_HZ, t60, "o-", label="the device's wet output (octave bands)")
    ax[1].semilogx(BANDS_HZ, want, "--", label="the tank's decay table")
    ax[1].axhspan(2.75, 4.0, color="0.85", label="decay code 3 (long): 2.75-4.0 s")
    ax[1].set_xlabel("Hz")
    ax[1].set_ylabel("T60 (s)")
    ax[1].grid(True, which="both", alpha=0.3)
    ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "device_impulse.png", dpi=110)
    plt.close(fig)
    write_audio(OUT / "device_impulse_wet.wav", y / max(np.abs(y).max(), 1e-12) * 0.5, int(fs))

    # The idle hum at the output (dry and wet, the default panel): the mains harmonics
    # (60 Hz and up) over the last 2 s of 4 s of silence (the supply's slow settling and the
    # coupling networks' drift aren't hum).
    hum = {}
    for name, mix in (("dry", 0.0), ("wet", 1.0), ("default", None)):
        vals = {} if mix is None else {"mixer": mix}
        q = np.asarray(
            fast.run_transient(
                builder.build(c, vals).ir, np.zeros(int(4.0 * fs)), settings=st
            ).vectors["v(out)"]
        )[-int(2 * fs) :]
        spec_ = np.fft.rfft(q - q.mean()) / len(q) * 2
        fr = np.fft.rfftfreq(len(q), 1 / fs)
        amp = [abs(spec_[np.argmin(np.abs(fr - 60.0 * h))]) for h in range(1, 13)]
        hum[name] = 20 * math.log10(math.sqrt(sum(a * a / 2 for a in amp)) / v_out + 1e-30)

    # Per DWELL: a 1 kHz tone at -12 dBFS, the tank's input current (the coil's voltage
    # across its own DC resistance: sp_c, the springs' sense), its THD, the input
    # transducer's compression (its force against a linear one's, rms) and the wet level.
    tone_t = np.arange(int(1.0 * fs)) / fs
    tone = 10 ** (-12 / 20) * np.sin(2 * math.pi * 1000 * tone_t) * np.minimum(tone_t / 0.05, 1)

    def at(dw: float) -> dict:
        r = fast.run_transient(builder.build(c, {**wet, "dwell": dw}).ir, tone * v_in, settings=st)
        cur = np.asarray(r.vectors["v(sp_c)"])[-int(0.25 * fs) :] / tank_c.input_re_ohm
        spec_ = np.abs(np.fft.rfft((cur - cur.mean()) * np.hanning(len(cur))))
        fr = np.fft.rfftfreq(len(cur), 1 / fs)
        h = [spec_[np.argmin(np.abs(fr - 1000 * m))] for m in range(1, 8)]
        thd = math.sqrt(sum(v * v for v in h[1:])) / h[0]
        sat = tank_c.input_saturation_a
        comp = np.std(sat * np.tanh(cur / sat)) / np.std(cur)
        out = np.asarray(r.vectors["v(out)"])[-int(0.25 * fs) :]
        return {
            "dwell": dw,
            "tank_current_ma_rms": 1e3 * float(np.std(cur)),
            "transducer_compression_db": 20 * math.log10(comp),
            "drive_thd_pct": 100 * thd,
            "wet_dbfs_rms": 20 * math.log10(np.std(out) / v_out + 1e-30),
        }

    dwells = [0.25, 0.5, 0.75, 1.0]
    with ThreadPoolExecutor(len(dwells)) as ex:
        drive = list(ex.map(at, dwells))
    summary["device"] = {
        "quality": quality,
        "bands_hz": BANDS_HZ,
        "t60_measured_s": [round(v, 3) for v in t60],
        "t60_table_s": [round(v, 3) for v in want],
        "impulse_render_wall_s_per_s": round(wall / (n / fs + st.settle_s), 2),
        "hum_dbfs_rms": {k: round(v, 1) for k, v in hum.items()},
        "drive_per_dwell": drive,
    }
    print(json.dumps(summary["device"], indent=1))


def audio(clip: str, start: float, seconds: float, quality: str) -> None:
    c = spec.load_circuit(spec.circuit_path(CIRCUIT))
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality=quality)
    fs = st.sample_rate
    v_in, v_out = c.full_scale
    x = load_audio(REPO / "data" / "clips" / clip, fs)[
        int(start * fs) : int((start + seconds) * fs)
    ]
    # The clip at -18 dBFS rms (a guitar's level into the unit).
    x = x * 10 ** (-18 / 20) / (np.std(x) + 1e-30)
    xp = np.concatenate([x, np.zeros(int(3.0 * fs))])
    runs = {
        "default": {},
        "dwell0.9_mix0.5": {"dwell": 0.9, "mixer": 0.5},
        "wet": {"mixer": 1.0},
    }

    def one(vals: dict) -> np.ndarray:
        r = fast.run_transient(builder.build(c, vals).ir, xp * v_in, settings=st)
        return np.asarray(r.vectors["v(out)"]) / v_out

    t0 = time.time()
    with ThreadPoolExecutor(len(runs)) as ex:
        ys = list(ex.map(one, runs.values()))
    stem = Path(clip).stem.replace(" ", "_")
    write_audio(OUT / "audio" / f"{stem}_dry.wav", xp, fs)
    for name, y in zip(runs, ys, strict=True):
        write_audio(OUT / "audio" / f"{stem}_6g15_{name}.wav", y, fs)
        print(
            f"  {name}: peak {20 * math.log10(np.abs(y).max() + 1e-30):.1f} dBFS, "
            f"rms {20 * math.log10(np.std(y) + 1e-30):.1f} dBFS"
        )
    print(f"{len(runs)} renders of {len(xp) / fs:.1f} s in {time.time() - t0:.0f} s")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="+", default=["tank", "device", "audio"])
    ap.add_argument("--quality", default="production")
    ap.add_argument("--clip", default="Dry Guitar.wav")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--seconds", type=float, default=12.0)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "summary.json"
    summary = json.loads(path.read_text()) if path.exists() else {}
    if "tank" in a.only:
        tank(summary)
    if "device" in a.only:
        device(summary, a.quality)
    path.write_text(json.dumps(summary, indent=1))
    if "audio" in a.only:
        audio(a.clip, a.start, a.seconds, a.quality)


if __name__ == "__main__":
    main()
