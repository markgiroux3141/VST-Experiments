"""Drums, D1 (docs/DRUM_PLAN.md): struck drums from physics, offline. Per drum in
config/drums/ two parts, each in reports/drums/<drum>/<part>/:

- `bare`: the batter head alone in vacuo (varimu/drums/membrane.py), the first test;
- `drum`: both heads on the shell with the air inside and outside (varimu/drums/drum.py).

Each: hits over a velocity sweep (WAVs in audio/, at the drum's fixed full scale, so soft
hits are soft), the hardest hit again without tension modulation (to hear the glide), a
`sweep.wav` (soft to hard, then the hardest without its glide) and `sweep_plate.wav` (the
same with the EMT 140's plate mixed in: its Python reference's response, a listening aid,
not the plate_reverb circuit), the pitch glide, the strike, plots and summary.json. The
bare head also checks its modes in a soft hit's spectrum against the Bessel ratios, and
its glide off the audio.

    uv run python scripts/drum_study.py [--only tom_13 kick_22] [--part bare drum]
        [--seconds 2] [--no-plate]
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

from varimu.config import load_sim_settings  # noqa: E402
from varimu.devices import library  # noqa: E402
from varimu.devices import plate as plt_ref  # noqa: E402
from varimu.drums import drum as dr  # noqa: E402
from varimu.drums import membrane as mb  # noqa: E402

ROOT = Path(__file__).parents[1]
OUT = ROOT / "reports" / "drums"
CACHE = ROOT / "cache" / "drums"
VELOCITIES = {"tom_13": (0.5, 1.0, 2.0, 3.0, 4.0, 6.0), "kick_22": (0.5, 1.0, 2.0, 3.0, 4.0)}
ROSSING_GLIDE = 0.08  # a 33 cm tom, hard blow (config/drums/tom_13.yaml)
PLATE_T500_S = 2.5  # the damper: decay at 500 Hz
PLATE_WET = 0.35  # the plate's share in sweep_plate.wav (energy-normalized response)


def contacts(force: np.ndarray, fs: float) -> list[tuple[float, float]]:
    """(start s, duration s) of each contact."""
    on = np.concatenate([[0], (force > 0).astype(int), [0]])
    edges = np.flatnonzero(np.diff(on))
    return [(a / fs, (b - a) / fs) for a, b in zip(edges[::2], edges[1::2], strict=True)]


def glide(track_hz: np.ndarray, rest_hz: float, force: np.ndarray, fs: float) -> dict:
    """A mode's frequency over its rest value: its peak (the head stretched under the
    pressing beater), then after the first contact ends and some times after that."""
    raw = track_hz / rest_hz - 1.0
    k = int(np.argmax(raw))
    # the tension swings at twice each mode's frequency: the pitch follows its mean
    n = int(round(fs / rest_hz))
    excess = np.convolve(raw, np.ones(n) / n, mode="same")
    end = int(round(sum(contacts(force, fs)[0]) * fs))
    out = {
        "peak": float(raw[k]),
        "peak_at_s": k / fs,
        "contact_end_s": end / fs,
        "free": float(excess[end]),
    }
    for ms in (20, 50, 100, 200, 400):
        i = end + int(ms * 1e-3 * fs)
        out[f"free_plus_{ms}ms"] = float(excess[i]) if i < excess.size else float("nan")
    below = np.flatnonzero(excess[end:] < 0.5 * excess[end])
    out["free_half_s"] = float(below[0] / fs) if below.size else float("nan")
    return out


def audio_f01(hit: mb.Hit, f01_hz: float) -> tuple[np.ndarray, np.ndarray]:
    """The lowest mode's frequency read off the pressure: band-passed around the (0,1)
    mode (0.8-1.45 f01, below the (1,1) mode's 1.59 only at rest: so read it only while
    the (0,1) mode dominates), the analytic signal's phase slope over 10 ms."""
    sos = signal.butter(4, [0.8 * f01_hz, 1.45 * f01_hz], btype="band", fs=hit.fs, output="sos")
    x = signal.sosfiltfilt(sos, hit.pressure_pa)
    z = signal.hilbert(x)
    phase = np.unwrap(np.angle(z))
    n = int(0.01 * hit.fs)
    f = (phase[n:] - phase[:-n]) / (2 * np.pi * n / hit.fs)
    t = (np.arange(f.size) + n / 2) / hit.fs
    # only where the band is within 40 dB of its peak, and 30 ms past the start (filtfilt)
    env = np.abs(z)[n // 2 : n // 2 + f.size]
    keep = (env > 0.01 * env.max()) & (t > 0.03)
    return t[keep], f[keep]


def mode_check(prep: mb.Prepared, hit: mb.Hit, count: int = 10) -> list[dict]:
    """The `count` modes that reach the mic strongest, each found as the spectrum's peak
    within +-3% of its predicted frequency."""
    md = prep.modes
    x = hit.pressure_pa * signal.windows.tukey(hit.pressure_pa.size, 0.05)
    n_fft = 1 << int(np.ceil(np.log2(x.size * 4)))
    spec = np.abs(np.fft.rfft(x, n_fft))
    freqs = np.fft.rfftfreq(n_fft, 1 / hit.fs)
    # mode amplitude at the mic ~ |D| omega^2 * face / omega (impulse) / decay
    strength = np.abs(prep.mic) * np.abs(prep.face) * md.omega0 / prep.decay
    out = []
    for k in np.argsort(strength)[::-1][:count]:
        f0 = md.f0_hz[k]
        band = (freqs > 0.97 * f0) & (freqs < 1.03 * f0)
        i = np.flatnonzero(band)[np.argmax(spec[band])]
        # parabolic interpolation of the peak in dB
        a, b, c = 20 * np.log10(spec[i - 1 : i + 2])
        di = 0.5 * (a - c) / (a - 2 * b + c)
        f_meas = freqs[i] + di * (freqs[1] - freqs[0])
        out.append(
            {
                "mode": [int(md.m[k]), int(md.n[k])],
                "ratio_bessel": float(md.j[k] / md.j[0]),
                "f_predicted_hz": float(f0),
                "f_found_hz": float(f_meas),
                "error": float(f_meas / f0 - 1),
                "t60_s": float(6.91 / prep.decay[k]),
            }
        )
    return sorted(out, key=lambda r: r["f_predicted_hz"])


def plate_response(fs: int) -> np.ndarray:
    """The EMT 140's plate (EMT140@1, its damper at PLATE_T500_S), force to acceleration,
    from the Python reference: computed at fs / 2 to 10 kHz and -60 dB (enough to listen
    by), brought to fs, normalized to unit energy; cached in cache/drums/."""
    path = CACHE / f"emt140_t{PLATE_T500_S:g}_{fs}.npy"
    if path.exists():
        return np.load(path)
    c = library.load_plate("EMT140@1")
    spec = plt_ref.PlateSpec(
        c.lx_m, c.ly_m, c.thickness_m, c.density_kg_m3, c.youngs_pa, c.poisson,
        c.tension_n_m, c.drive_xy, c.pickup_xy, 10_000.0,
        plt_ref.decay_table(c, PLATE_T500_S), 60.0,
    )  # fmt: skip
    t = time.perf_counter()
    h = plt_ref.impulse_response(spec, fs / 2)
    h = signal.resample_poly(h, 2, 1)
    h /= np.sqrt(np.sum(h * h))
    print(f"plate response: {h.size / fs:.1f} s, computed in {time.perf_counter() - t:.0f} s")
    CACHE.mkdir(parents=True, exist_ok=True)
    np.save(path, h)
    return h


def write(path: Path, pa: np.ndarray, full_scale_pa: float, fs: int) -> None:
    sf.write(path, (pa / full_scale_pa).astype(np.float32), fs, subtype="FLOAT")


def sweeps(audio: Path, hits: dict, flat, full_scale_pa: float, fs: int, plate) -> None:
    """sweep.wav: each hit for 1.5 s, soft to hard, then the hardest without its glide;
    sweep_plate.wav: the same with the plate."""
    seg = int(1.5 * fs)
    parts = [hits[v].pressure_pa[:seg] for v in hits] + [flat.pressure_pa[:seg]]
    dry = np.concatenate([np.pad(p, (0, seg - p.size)) for p in parts])
    write(audio / "sweep.wav", dry, full_scale_pa, fs)
    if plate is not None:
        wet = signal.fftconvolve(dry, plate)[: dry.size + int(2 * fs)]
        mix = np.pad(dry, (0, wet.size - dry.size)) + PLATE_WET * wet
        write(audio / "sweep_plate.wav", mix, full_scale_pa, fs)


def study_bare(name: str, seconds: float, fs: int, plate) -> dict:
    drum = mb.load(name)
    t = time.perf_counter()
    prep = mb.prepare(drum)
    prep_s = time.perf_counter() - t
    md = prep.modes
    f01 = drum.head.f01_hz
    out_dir = OUT / name / "bare"
    audio = out_dir / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    hits, rows = {}, []
    velocities = VELOCITIES.get(name, (1.0, 2.0, 4.0))
    for v in velocities:
        t = time.perf_counter()
        hit = mb.run(prep, fs=fs, seconds=seconds, velocity_m_s=v)
        run_s = time.perf_counter() - t
        hits[v] = hit
        cs = contacts(hit.force_n, fs)
        ta, fa = audio_f01(hit, f01)

        def at(s: float, ta=ta, fa=fa) -> float:
            return (
                float(np.interp(s, ta, fa) / f01 - 1)
                if ta.size and ta[0] <= s <= ta[-1]
                else float("nan")
            )

        rows.append(
            {
                "velocity_m_s": v,
                "peak_pa": float(np.abs(hit.pressure_pa).max()),
                "peak_db_spl": float(20 * np.log10(np.abs(hit.pressure_pa).max() / 2e-5)),
                "peak_force_n": float(hit.force_n.max()),
                "contacts": [[round(a * 1e3, 3), round(d * 1e3, 3)] for a, d in cs],
                "glide": glide(hit.f01_hz, f01, hit.force_n, fs),
                "glide_audio_at_50ms": at(0.05),
                "glide_tension_at_50ms": float(hit.f01_hz[int(0.05 * fs)] / f01 - 1),
                "run_x_real_time": run_s / seconds,
            }
        )
        write(audio / f"hit_{v:g}m_s.wav", hit.pressure_pa, drum.full_scale_pa, fs)
        r, g = rows[-1], rows[-1]["glide"]
        print(
            f"{name} bare {v:g} m/s: {r['peak_db_spl']:.1f} dB SPL peak, contact "
            f"{cs[0][1] * 1e3:.2f} ms; glide free +{g['free'] * 100:.1f}%, "
            f"+{g['free_plus_50ms'] * 100:.2f}% 50 ms on; {run_s / seconds:.1f}x real time"
        )
    v_hard = velocities[-1]
    flat = mb.run(prep, fs=fs, seconds=seconds, velocity_m_s=v_hard, tension_modulation=False)
    write(audio / f"hit_{v_hard:g}m_s_no_glide.wav", flat.pressure_pa, drum.full_scale_pa, fs)
    sweeps(audio, hits, flat, drum.full_scale_pa, fs, plate)

    summary = {
        "drum": name,
        "part": "bare",
        "tension_n_m": drum.head.tension_n_m,
        "modes": int(md.m.size),
        "prepare_s": prep_s,
        "hits": rows,
        "soft_hit_modes": mode_check(prep, hits[velocities[0]]),
        "t60_s_lowest": [
            {
                "mode": [int(md.m[k]), int(md.n[k])],
                "f_hz": float(md.f0_hz[k]),
                "t60_s": float(6.91 / prep.decay[k]),
                "radiation_share": float(prep.decay_radiation[k] / prep.decay[k]),
            }
            for k in np.argsort(md.f0_hz)[:12]
        ],
    }
    if name == "tom_13":
        free = np.array([r["glide"]["free"] for r in rows])
        summary["velocity_for_rossing_glide_m_s"] = float(
            np.interp(ROSSING_GLIDE, free, np.array(velocities))
        )
    tracks = {v: hits[v].f01_hz for v in hits}
    marks = md.f0_hz[np.argsort(md.f0_hz)[:20]]
    plots(name, "a struck head in vacuo", f01, tracks, hits, flat, marks, out_dir, audio_check=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def study_drum(name: str, seconds: float, fs: int, plate) -> dict:
    d2 = dr.load(name)
    drum = d2.drum
    t = time.perf_counter()
    prep = dr.prepare(d2)
    prep_s = time.perf_counter() - t
    fund = dr.fundamental(prep)
    f_rest = float(prep.omega[fund] / (2 * np.pi))
    out_dir = OUT / name / "drum"
    audio = out_dir / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    print(
        f"{name} drum: {prep.omega.size} normal modes ({prep.n_cavity} cavity), prepared in "
        f"{prep_s:.0f} s; the fundamental {f_rest:.1f} Hz (m = {prep.m[fund]})"
    )
    hits, rows = {}, []
    velocities = VELOCITIES.get(name, (1.0, 2.0, 4.0))
    for v in velocities:
        t = time.perf_counter()
        hit = dr.run(prep, fs=fs, seconds=seconds, velocity_m_s=v)
        run_s = time.perf_counter() - t
        hits[v] = hit
        cs = contacts(hit.force_n, fs)
        rows.append(
            {
                "velocity_m_s": v,
                "peak_pa": float(np.abs(hit.pressure_pa).max()),
                "peak_db_spl": float(20 * np.log10(np.abs(hit.pressure_pa).max() / 2e-5)),
                "peak_force_n": float(hit.force_n.max()),
                "contacts": [[round(a * 1e3, 3), round(d * 1e3, 3)] for a, d in cs],
                "glide": glide(hit.f_fund_hz, f_rest, hit.force_n, fs),
                "tension_rise": [
                    float(hit.tension_n_m[0].max() / drum.head.tension_n_m - 1),
                    float(hit.tension_n_m[1].max() / d2.resonant.tension_n_m - 1),
                ],
                "run_x_real_time": run_s / seconds,
            }
        )
        write(audio / f"hit_{v:g}m_s.wav", hit.pressure_pa, drum.full_scale_pa, fs)
        r, g = rows[-1], rows[-1]["glide"]
        print(
            f"{name} drum {v:g} m/s: {r['peak_db_spl']:.1f} dB SPL peak, contact "
            f"{cs[0][1] * 1e3:.2f} ms; glide +{g['free'] * 100:.2f}% at contact's end, "
            f"+{g['free_plus_50ms'] * 100:.2f}% / +{g['free_plus_200ms'] * 100:.2f}% 50 / 200 ms "
            f"on; {run_s / seconds:.1f}x real time"
        )
    v_hard = velocities[-1]
    flat = dr.run(prep, fs=fs, seconds=seconds, velocity_m_s=v_hard, tension_modulation=False)
    write(audio / f"hit_{v_hard:g}m_s_no_glide.wav", flat.pressure_pa, drum.full_scale_pa, fs)
    sweeps(audio, hits, flat, drum.full_scale_pa, fs, plate)

    # the lowest normal modes, and how strongly a strike sounds each at the mic
    order = np.argsort(prep.omega)
    strength = np.abs(prep.mic) * np.abs(prep.face) / prep.decay
    summary = {
        "drum": name,
        "part": "drum",
        "normal_modes": int(prep.omega.size),
        "cavity_modes": int(prep.n_cavity),
        "prepare_s": prep_s,
        "fundamental_hz": f_rest,
        "batter_f01_in_vacuo_hz": drum.head.f01_hz,
        "hits": rows,
        "lowest_modes": [
            {
                "m": int(prep.m[k]),
                "f_hz": float(prep.omega[k] / (2 * np.pi)),
                "ratio": float(prep.omega[k] / prep.omega[fund]),
                "t60_s": float(6.91 / prep.decay[k]),
                "radiation_share": float(prep.decay_radiation[k] / prep.decay[k]),
                "batter_share": float(prep.batter_share[k]),
                "strike_at_mic_db": float(20 * np.log10(strength[k] / strength.max() + 1e-30)),
            }
            for k in order[:24]
        ],
    }
    tracks = {v: hits[v].f_fund_hz for v in hits}
    loud = order[:200][strength[order[:200]] > 1e-2 * strength.max()]
    marks = prep.omega[loud] / (2 * np.pi)
    plots(name, "both heads, the air, the shell", f_rest, tracks, hits, flat, marks, out_dir)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def plots(name, what, f_rest, tracks, hits, flat, marks, out_dir: Path, audio_check=False):
    vs = list(hits)
    fig, ax = plt.subplots(2, 2, figsize=(13, 8))
    for v in vs:
        tr = tracks[v]
        t = np.arange(tr.size) / hits[v].fs
        n = int(round(hits[v].fs / f_rest))
        smooth = np.convolve(tr / f_rest - 1, np.ones(n) / n, mode="same")
        ax[0, 0].plot(t, smooth * 100, label=f"{v:g} m/s")
        if audio_check:
            ta, fa = audio_f01(hits[v], f_rest)
            ax[0, 0].plot(ta, (fa / f_rest - 1) * 100, ":", color=ax[0, 0].lines[-1].get_color())
    ax[0, 0].set(
        xlabel="s",
        ylabel="the fundamental above its rest frequency, %",
        xlim=(0, 0.6),
        ylim=(-2, None),
        title="pitch glide (from the tension"
        + ("; dotted: off the audio)" if audio_check else ")"),
    )
    if name == "tom_13":
        ax[0, 0].axhline(
            ROSSING_GLIDE * 100, color="k", lw=0.8, ls="--", label="Rossing: ~8%, hard blow"
        )
    ax[0, 0].legend(fontsize=8)
    v = vs[-1]
    h = hits[v]
    n = int(0.03 * h.fs)
    t_ms = np.arange(n) / h.fs * 1e3
    ax[0, 1].plot(t_ms, h.force_n[:n], color="C3")
    ax[0, 1].set(xlabel="ms", ylabel="contact force, N", title=f"{v:g} m/s: the strike")
    a2 = ax[0, 1].twinx()
    a2.plot(t_ms, h.pressure_pa[:n], color="C0", lw=0.8)
    a2.set_ylabel("pressure at the mic, Pa")
    f, t, s = signal.spectrogram(h.pressure_pa, h.fs, nperseg=8192, noverlap=7680)
    keep = f < 2000
    ax[1, 0].pcolormesh(
        t, f[keep], 10 * np.log10(s[keep] + 1e-20), vmin=10 * np.log10(s.max()) - 80, shading="auto"
    )
    ax[1, 0].set(xlabel="s", ylabel="Hz", title=f"{v:g} m/s: spectrogram")
    for hh, lab in (
        (hits[vs[0]], f"{vs[0]:g} m/s"),
        (h, f"{v:g} m/s"),
        (flat, f"{v:g} m/s, no glide"),
    ):
        x = hh.pressure_pa
        sp = 20 * np.log10(np.abs(np.fft.rfft(x)) + 1e-12)
        fr = np.fft.rfftfreq(x.size, 1 / hh.fs)
        ax[1, 1].plot(fr, sp, lw=0.7, label=lab)
    for f_m in marks:
        ax[1, 1].axvline(f_m, color="k", lw=0.4, alpha=0.4)
    ax[1, 1].set(
        xscale="log",
        xlim=(0.4 * f_rest, 3000),
        xlabel="Hz",
        ylabel="dB",
        title="spectra (grey: modes at rest)",
    )
    ax[1, 1].legend(fontsize=8)
    fig.suptitle(f"{name}: {what} (DRUM_PLAN.md D1)")
    fig.tight_layout()
    fig.savefig(out_dir / "study.png", dpi=110)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", default=["tom_13", "kick_22"])
    ap.add_argument("--part", nargs="*", default=["bare", "drum"], choices=["bare", "drum"])
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--no-plate", action="store_true")
    a = ap.parse_args()
    fs = load_sim_settings().sample_rate
    plate = None if a.no_plate else plate_response(fs)
    for name in a.only:
        if "bare" in a.part:
            s = study_bare(name, a.seconds, fs, plate)
            if "velocity_for_rossing_glide_m_s" in s:
                print(f"{name}: Rossing's ~8% at {s['velocity_for_rossing_glide_m_s']:.2f} m/s")
        if "drum" in a.part:
            s = study_drum(name, a.seconds, fs, plate)
            for r in s["lowest_modes"][:10]:
                print(
                    f"  m={r['m']} {r['f_hz']:7.1f} Hz ({r['ratio']:.3f}) T60 {r['t60_s']:.2f} s, "
                    f"radiation {r['radiation_share']:.2f}, batter {r['batter_share']:.2f}, "
                    f"strike at mic {r['strike_at_mic_db']:.0f} dB"
                )


if __name__ == "__main__":
    main()
