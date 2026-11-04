"""The Rhodes, RH1 (docs/RHODES_PLAN.md): one key at a time, offline, heard straight out of
its pickup (no amp). Writes reports/rhodes/key/:

- per key: strikes over a speed sweep (WAVs in audio/ at one full scale, so soft strikes
  are soft), a plot of the strike (the EMF's first 60 ms, the tip's motion, the spectrum
  early and late, the spectrogram) and its numbers: the pitch heard against the note, the
  tine's decay (from its tip) against Shear's measured Q, the hammer's contact against Muenster &
  Pfeifle's 6.42 ms, the tine's overtones (the bell), the harmonics against the speed (the
  bark);
- the live tier against the reference (the full damped beam): the EMF's difference, dB;
- the voicing sweep at G3 (Shear's 196 Hz figure): harmonics 1-4 against the tine's rest
  height relative to the pole, with Shear's finding (towards the axis, the fundamental and
  odd partials fall and the second dominates);
- `scale.wav`: the keys in turn at mezzo-forte; `voicing.wav`: the voicing sweep's strikes;
- summary.json, keyboard.png, voicing.png.

    uv run python scripts/rhodes_key_study.py [--keys 19 31 ...] [--speeds 0.5 1 2]
        [--seconds 3] [--no-reference]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from scipy import signal  # noqa: E402

from varimu.rhodes import beam as bm  # noqa: E402
from varimu.rhodes import key as ky  # noqa: E402
from varimu.rhodes import pickup as pk  # noqa: E402
from varimu.rhodes import spec  # noqa: E402

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "rhodes" / "key"
FS = 96000.0
# Shear's Ebs (his Q table), G3 (his voicing figure), the 73's ends and the 88's
KEYS = (8, 19, 31, 35, 43, 55, 67, 80, 88)
SPEEDS = (0.5, 1.0, 2.0, 3.0)
VOICING_KEY = 35  # G3, 196 Hz
VOICINGS_MM = (-1.5, -1.0, -0.6, -0.3, 0.0, 0.3, 0.6, 1.0, 1.5)
NOTE_NAMES = ["A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#"]


def name(n: int) -> str:
    return f"{NOTE_NAMES[(n - 1) % 12]}{(n + 8) // 12}"


def harmonics(x: np.ndarray, f0: float, t0: float, t1: float, count: int = 6) -> np.ndarray:
    """Levels (dB re the strongest) of harmonics 1..count in x[t0:t1], Hann window."""
    seg = x[int(t0 * FS) : int(t1 * FS)]
    win = np.hanning(seg.size)
    spec_ = np.abs(np.fft.rfft(seg * win))
    f = np.fft.rfftfreq(seg.size, 1 / FS)
    lv = []
    for h in range(1, count + 1):
        band = (f > h * f0 * 0.97) & (f < h * f0 * 1.03)
        lv.append(spec_[band].max() if band.any() else 0.0)
    lv = np.array(lv)
    return 20 * np.log10(np.maximum(lv, 1e-20) / lv.max())


def pitch_hz(x: np.ndarray, near: float, t0: float, t1: float) -> float:
    seg = x[int(t0 * FS) : int(t1 * FS)]
    n = 1 << int(np.ceil(np.log2(seg.size * 8)))
    s = np.abs(np.fft.rfft(seg * np.hanning(seg.size), n))
    f = np.fft.rfftfreq(n, 1 / FS)
    band = np.flatnonzero((f > near * 0.97) & (f < near * 1.03))
    i = band[np.argmax(s[band])]
    a, b, c = np.log(s[i - 1 : i + 2])
    return float(f[i] + 0.5 * (a - c) / (a - 2 * b + c) * (f[1] - f[0]))


def decay_q(x: np.ndarray, f0: float, t0: float, t1: float) -> float:
    """The fundamental's Q from the slope of its level (a band around f0)."""
    sos = signal.butter(4, [f0 * 0.85, f0 * 1.15], "bandpass", fs=FS, output="sos")
    y = signal.sosfiltfilt(sos, x)
    env = np.abs(signal.hilbert(y))
    t = np.arange(x.size) / FS
    sel = (t > t0) & (t < t1)
    slope = np.polyfit(t[sel], np.log(env[sel] + 1e-30), 1)[0]  # -sigma
    return float(np.pi * f0 / -slope)


def study_key(n: int, speeds, seconds: float, flux: pk.FluxMap, reference: bool) -> dict:
    k = spec.key(n)
    fe = bm.assemble(k.assembly, k.element_m)
    md = bm.modes(fe, f_max_hz=k.f_max_hz)
    kt = bm.tine_mode(fe, md, k.note_hz)
    res: dict = {
        "key": n,
        "name": name(n),
        "note_hz": k.note_hz,
        "fits": k.fits,
        "q_shear_interp": k.q_target,
        "tonebar_f0_muenster_fit_hz": k.tonebar_f0_hz,
        "hammer": {
            "durometer": k.hammer.durometer,
            "strike_x_mm": k.hammer.strike_x_m * 1e3,
            "stiffness": k.hammer.stiffness,
        },
        "modes": [
            {"f_hz": float(f), "ratio": float(f / md.f_hz[kt]), "q": float(q)}
            for f, q in zip(md.f_hz[:8], md.q[:8], strict=False)
        ],
        "strikes": {},
    }
    full_scale = spec.load()["numerics"]["full_scale_v"]
    audio = OUT / "audio"
    strikes = {}
    for v in speeds:
        s = ky.strike(k, v, duration_s=seconds, flux=flux)
        strikes[v] = s
        sf.write(
            audio / f"key_{n:02d}_{v:.1f}ms.wav", (s.emf_v / full_scale).astype(np.float32), int(FS)
        )
        late0 = min(0.3, seconds / 3)
        res["strikes"][f"{v:.1f}"] = {
            "contact_ms": s.contact_s * 1e3,
            "contacts": s.strikes,
            "max_force_n": s.max_force_n,
            "tip_peak_mm": float(np.max(np.abs(s.tip_m)) * 1e3),
            "emf_peak_v": float(np.max(np.abs(s.emf_v))),
            "harmonics_db": harmonics(s.emf_v, k.note_hz, late0, late0 + 0.4).round(1).tolist(),
            "attack_harmonics_db": harmonics(s.emf_v, k.note_hz, 0.0, 0.03).round(1).tolist(),
        }
    mid = strikes[1.0] if 1.0 in strikes else strikes[speeds[0]]
    t1 = min(seconds, 2.5)
    res["pitch_hz"] = pitch_hz(mid.emf_v, k.note_hz, 0.2, t1)
    res["pitch_cents"] = 1200 * np.log2(res["pitch_hz"] / k.note_hz)
    # the tine's decay from its tip (the EMF's fundamental is no measure of it: on a big
    # swing the pickup's law moves energy between the harmonics as the swing shrinks)
    res["q_measured"] = decay_q(mid.tip_m, k.note_hz, 0.2, t1)
    if reference:
        t0 = time.time()
        live = ky.strike(k, 1.0, duration_s=0.5, flux=flux)
        ref = ky.strike(k, 1.0, duration_s=0.5, flux=flux, tier="full", step_oversample=16)
        err = live.emf_v - ref.emf_v
        res["live_vs_reference_db"] = float(10 * np.log10(np.mean(err**2) / np.mean(ref.emf_v**2)))
        res["reference_contact_ms"] = ref.contact_s * 1e3
        res["reference_s"] = time.time() - t0
    plot_key(n, k, md, kt, strikes, OUT / f"key_{n:02d}.png")
    return res


def plot_key(n, k, md, kt, strikes, path):
    fig, ax = plt.subplots(2, 2, figsize=(13, 8))
    for v, s in strikes.items():
        sel = s.t_s < 0.06
        ax[0, 0].plot(s.t_s[sel] * 1e3, s.emf_v[sel], lw=0.8, label=f"{v} m/s")
        ax[0, 1].plot(s.t_s[sel] * 1e3, s.tip_m[sel] * 1e3, lw=0.8, label=f"{v} m/s")
    ax[0, 0].set(
        xlabel="ms", ylabel="EMF, V", title=f"key {n} ({name(n)}, {k.note_hz:.1f} Hz): the pickup"
    )
    ax[0, 1].set(xlabel="ms", ylabel="tip, mm", title="the tine's tip")
    ax[0, 0].legend(fontsize=8)
    s = strikes[max(strikes)]
    for (t0, t1), lab in (((0.0, 0.03), "first 30 ms"), ((0.3, 0.7), "0.3-0.7 s")):
        seg = s.emf_v[int(t0 * FS) : int(t1 * FS)]
        nfft = 1 << 16
        sp = 20 * np.log10(np.abs(np.fft.rfft(seg * np.hanning(seg.size), nfft)) + 1e-12)
        f = np.fft.rfftfreq(nfft, 1 / FS)
        ax[1, 0].semilogx(f[1:], sp[1:] - sp.max(), lw=0.7, label=lab)
    for f in md.f_hz[: kt + 6]:
        ax[1, 0].axvline(f, color="k", lw=0.4, ls=":")
    ax[1, 0].set(
        xlim=(20, 24000),
        ylim=(-100, 5),
        xlabel="Hz",
        ylabel="dB",
        title=f"spectrum, {max(strikes)} m/s (dotted: the assembly's modes)",
    )
    ax[1, 0].legend(fontsize=8)
    f, t, sxx = signal.spectrogram(s.emf_v, FS, nperseg=4096, noverlap=3072)
    ax[1, 1].pcolormesh(
        t, f, 10 * np.log10(sxx + 1e-20), shading="auto", vmin=10 * np.log10(sxx.max()) - 90
    )
    ax[1, 1].set(ylim=(0, min(12000, 12 * k.note_hz)), xlabel="s", ylabel="Hz", title="spectrogram")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def voicing_sweep(flux: pk.FluxMap, seconds: float) -> dict:
    k = spec.key(VOICING_KEY)
    full_scale = spec.load()["numerics"]["full_scale_v"]
    rows, clips = [], []
    for vo in VOICINGS_MM:
        s = ky.strike(k, 1.0, duration_s=min(seconds, 1.5), flux=flux, voicing_m=vo * 1e-3)
        h = harmonics(s.emf_v, k.note_hz, 0.3, 0.7, count=4)
        lv = 20 * np.log10(np.max(np.abs(s.emf_v[int(0.3 * FS) : int(0.7 * FS)])))
        rows.append(
            {"voicing_mm": vo, "harmonics_db": h.round(1).tolist(), "peak_dbv": round(float(lv), 1)}
        )
        clips.append(s.emf_v / full_scale)
        clips.append(np.zeros(int(0.2 * FS)))
    sf.write(OUT / "audio" / "voicing.wav", np.concatenate(clips).astype(np.float32), int(FS))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    hm = np.array([r["harmonics_db"] for r in rows])
    for i in range(hm.shape[1]):
        ax.plot(VOICINGS_MM, hm[:, i], "o-", label=f"H{i + 1}")
    ax.set(
        xlabel="tine's rest above the pole's axis, mm",
        ylabel="dB re the strongest",
        title=f"voicing, key {VOICING_KEY} ({name(VOICING_KEY)}, {k.note_hz:.0f} Hz), "
        "1 m/s, 0.3-0.7 s",
    )
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT / "voicing.png", dpi=100)
    plt.close(fig)
    h0 = next(r for r in rows if r["voicing_mm"] == 0.0)["harmonics_db"]
    off = next(r for r in rows if r["voicing_mm"] == 1.0)["harmonics_db"]
    return {
        "key": VOICING_KEY,
        "rows": rows,
        "shear_check": {
            "centred_h2_strongest": bool(np.argmax(h0) == 1),
            "centred_h1_minus_h2_db": round(h0[0] - h0[1], 1),
            "offset_1mm_h1_minus_h2_db": round(off[0] - off[1], 1),
        },
    }


def plot_keyboard(results: list[dict]) -> None:
    keys = [r["key"] for r in results]
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    ax[0].semilogy(keys, [r["q_measured"] for r in results], "o-", label="model (the tine's tip)")
    pts = np.array(spec.load()["anchors"]["q_shear"])
    shear_keys = 49 + 12 * np.log2(pts[:, 0] / 440.0)
    ax[0].semilogy(shear_keys, pts[:, 1], "kx", label="Shear 2011")
    ax[0].set(xlabel="key", ylabel="Q", title="the fundamental's decay")
    ax[0].legend()
    for v in ("0.5", "1.0", "2.0"):
        ax[1].plot(
            keys,
            [r["strikes"].get(v, {}).get("contact_ms", np.nan) for r in results],
            "o-",
            label=f"{v} m/s",
        )
    ax[1].axhline(6.42, color="k", ls="--", label="Muenster & Pfeifle (average)")
    ax[1].set(xlabel="key", ylabel="ms", title="the hammer's contact")
    ax[1].legend(fontsize=8)
    for v in ("0.5", "1.0", "2.0", "3.0"):
        h = [r["strikes"].get(v, {}).get("harmonics_db", [np.nan, np.nan]) for r in results]
        ax[2].plot(keys, [x[1] - x[0] for x in h], "o-", label=f"{v} m/s")
    ax[2].set(
        xlabel="key", ylabel="H2 - H1, dB", title="the bark: second harmonic re the fundamental"
    )
    ax[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "keyboard.png", dpi=100)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--keys", type=int, nargs="+", default=list(KEYS))
    ap.add_argument("--speeds", type=float, nargs="+", default=list(SPEEDS))
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--no-reference", action="store_true")
    args = ap.parse_args()
    (OUT / "audio").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    flux = pk.flux_map(spec.key(49).pickup, progress=True)
    results = []
    for n in args.keys:
        t = time.time()
        r = study_key(n, args.speeds, args.seconds, flux, not args.no_reference)
        results.append(r)
        contact = r["strikes"].get("1.0", {}).get("contact_ms", float("nan"))
        print(
            f"key {n:2d} {r['name']:>4}: pitch {r['pitch_cents']:+.1f} c, "
            f"Q {r['q_measured']:.0f} (Shear {r['q_shear_interp']:.0f}), "
            f"contact {contact:.2f} ms, "
            f"live vs ref {r.get('live_vs_reference_db', float('nan')):.1f} dB "
            f"({time.time() - t:.0f} s)",
            flush=True,
        )
    full_scale = spec.load()["numerics"]["full_scale_v"]
    scale = []
    for n in args.keys:
        x, _ = (
            sf.read(OUT / "audio" / f"key_{n:02d}_1.0ms.wav")
            if 1.0 in args.speeds
            else (None, None)
        )
        if x is not None:
            scale += [x[: int(1.5 * FS)], np.zeros(int(0.1 * FS))]
    if scale:
        sf.write(OUT / "audio" / "scale.wav", np.concatenate(scale).astype(np.float32), int(FS))
    voicing = voicing_sweep(flux, args.seconds)
    print(f"voicing: {voicing['shear_check']}")
    plot_keyboard(results)
    summary = {
        "keys": results,
        "voicing": voicing,
        "full_scale_v": full_scale,
        "seconds": time.time() - t0,
    }
    (OUT / "summary.json").write_text(
        json.dumps(summary, indent=1, default=float), encoding="utf-8"
    )
    print(f"done in {time.time() - t0:.0f} s -> {OUT}")


if __name__ == "__main__":
    main()
