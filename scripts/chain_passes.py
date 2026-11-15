"""Caricatures of mic -> preamp chains by repeated passes (an experiment, 2026-11-14).

    uv run --extra fast --extra listen python scripts/chain_passes.py \
        [--chains u47_v76 ...] [--stems "lead vocal" ...] [--passes 8] [--spl-db 100] \
        [--draft] [--time-one] [--analyse-only]

Each stem of `stems/Did she mention my name/sample/` (its mid, (L + R) / 2) is the free-field
sound pressure at a chain's capsule, on axis, a plane wave, its sounding rms
(`scene.sounding_rms`) at `--spl-db`: the chain's output is fed back the same way, at the same
SPL every pass (gain staging: each pass is a realistic use of the chain), 1..N passes.

The chain's linear response H (free-field pressure at the capsule -> `out`) is measured on a
periodic pink multisine at the same SPL (the last two of four periods). With it:

- `pN`        N passes as they come out (tone x N, character x ~N);
- `pN_eqnull` N passes with H^-(N-1) applied: one pass's tone, N passes' character;
- `pN_tone`   one pass with H^(N-1) applied: N passes' tone, one pass's character.

The correction's magnitude is clamped to +-CLAMP_DB and faded to unity outside
[F_LO, F_HI]. Every WAV is loudness matched (`matching.TARGET_LUFS`). Without `--noise` the
renders carry no noise (the circuits have no `noise` block). With it, every pass is built with
B5's noise on (`builder.build(..., noise=seed)`), a seed of its own per stem and pass (a re-amp
pass doesn't repeat the last pass's hiss); H is measured without noise. Reports then go to
`<quality>_noise/`, and each stem's p1 carries `noise_vs_clean`: the noisy p1 minus the
noiseless one (the same input), dB re the noiseless p1.
Passes are cached in cache/chain_passes/; reports in reports/chain_passes/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.circuit import builder, spec
from varimu.config import REPO_ROOT
from varimu.devices.library import component_data
from varimu.listen import difference, matching
from varimu.mics.free_field import capsule_entry_pressures
from varimu.rooms.scene import sounding_rms
from varimu.sim import fast
from varimu.sim.io import TransientSettings, full_scale

P_REF = 20e-6
STEM_DIR = REPO_ROOT / "stems" / "Did she mention my name" / "sample"
CACHE = REPO_ROOT / "cache" / "chain_passes"
OUT = REPO_ROOT / "reports" / "chain_passes"
CHAINS = ["u47_v76", "r44_ua610", "sm57_api312", "carbon_clean", "omni_clean"]
# Gain staging as an engineer would: pass 1's peaks on the lead vocal near -12 dBFS (at the
# chains' defaults, 100 dB SPL put the peaks into the output stages' rails: clipping, not the
# chain). The carbon transmitter at a telephone's ~90 dB SPL (at 100 it saturates, and its output
# clips the clean pre even at 20 dB).
CHAIN_SET: dict[str, dict[str, float]] = {
    "u47_v76": {"gain_db_v76": 24},
    "r44_ua610": {"level_ua610": 0.4},
    "sm57_api312": {"gain_api312": 0.4},
    "carbon_clean": {"gain_db_clean": 20},
    "omni_clean": {"gain_db_clean": 30},
}
CHAIN_SPL_DB = {"carbon_clean": 90.0}
SHOWN = (1, 2, 4, 8)
PERIOD = 1 << 16  # the multisine's period, samples (0.68 s at 96 kHz)
MS_PERIODS = 4
F_MS = (10.0, 40000.0)  # the multisine's band
F_LO, F_HI = (15.0, 25.0), (20000.0, 30000.0)  # the correction fades to unity across these
CLAMP_DB = 60.0
BAND_HZ = (20.0, 20000.0)  # the metrics' band (zero-phase band-pass on both signals)
FADE_S = 0.01


def _settings(draft: bool) -> TransientSettings:
    return TransientSettings.from_sim_settings(
        engine="circuitsim", quality="draft" if draft else None
    )


def _key(chain: str, *parts) -> str:
    h = hashlib.sha256((spec.circuit_path(chain)).read_bytes())
    h.update(json.dumps(parts).encode())
    return h.hexdigest()[:12]


def pass_seed(stem: str, i: int) -> int:
    """The noise seed of `stem`'s pass `i` (B5's streams: one realization per pass)."""
    return (zlib.crc32(stem.encode()) << 8) | i


class Chain:
    def __init__(self, name: str, draft: bool, over: dict | None = None, noise: bool = False):
        self.name = name
        self.noise = noise
        self.over = dict(CHAIN_SET.get(name, {})) if over is None else over
        self.c = spec.load_circuit(spec.circuit_path(name))
        self.q = spec.resolve(self.c, self.over)
        self.s = _settings(draft)
        self.fs = self.s.sample_rate
        self.ir = builder.build(self.c, self.over).ir
        self.rear = any(k.name == "p_rear" for k in self.ir.controls)
        self.out_fs = full_scale(self.s, self.c)[1]
        self.geometry = None
        for key in self.q:
            if str(key).startswith(("capsule_model", "cartridge_model", "ribbon_model")):
                self.geometry = component_data(str(self.q[key])).get("geometry", {})
                break

    def entries(self, p: np.ndarray) -> tuple[np.ndarray, dict]:
        """The capsule's front pressure and the controls (its rear) for free-field `p`."""
        if self.geometry is not None:
            front, rear, _ = capsule_entry_pressures(self.geometry, p, 0.0, self.fs)
        else:
            front, rear = p, p
        return front, ({"p_rear": rear} if self.rear else {})

    def run(self, p: np.ndarray, seed: int | None = None) -> np.ndarray:
        """Free-field pressure at the capsule (Pa) -> `out` (full scale = 1); with the chain's
        noise on and a `seed`, that pass's noise realization (None: noiseless)."""
        ir = self.ir
        if self.noise and seed is not None:
            ir = builder.build(self.c, self.over, noise=seed).ir
        front, controls = self.entries(p)
        v = fast.run_transient(ir, front, settings=self.s, controls=controls or None).vectors[
            "v(out)"
        ]
        return np.asarray(v, float) / self.out_fs


def to_spl(x: np.ndarray, spl_db: float, fs: int) -> np.ndarray:
    x = x - np.mean(x)
    n = int(FADE_S * fs)
    w = 0.5 - 0.5 * np.cos(np.pi * np.arange(n) / n)
    x = x.copy()
    x[:n] *= w
    x[-n:] *= w[::-1]
    return x * (P_REF * 10 ** (spl_db / 20) / sounding_rms(x, fs))


def load_stem(name: str, fs: int) -> np.ndarray:
    x, sr = sf.read(STEM_DIR / f"{name}.wav", always_2d=True)
    assert sr == fs, (sr, fs)
    return x.mean(axis=1)


def passes(
    ch: Chain, stem: str, x: np.ndarray, n: int, spl_db: float, tag: str
) -> list[np.ndarray]:
    """[p1 .. pn], cached per pass. Staging: each pass's input at `spl_db` sounding rms, turned
    down where H predicts an output peak above pass 1's (an engineer watching the meters as the
    compounded EQ makes the signal peakier; otherwise the late passes clip the output stages)."""
    d = CACHE / ch.name / stem
    d.mkdir(parents=True, exist_ok=True)
    key = _key(ch.name, stem, spl_db, tag, ch.over, "peak-staged", *(["noise"] if ch.noise else []))
    f_ms, h_ms = measure_h(ch, spl_db, tag)

    def predicted_peak(p: np.ndarray) -> float:
        return float(np.max(np.abs(apply_power(p, f_ms, h_ms, 1, ch.fs))))

    out, cur = [], x
    ref = None  # (pass 1's output peak, its predicted peak)
    for i in range(1, n + 1):
        f = d / f"p{i}_{key}.npy"
        p = to_spl(cur, spl_db, ch.fs)
        if ref is not None:
            p = p * min(1.0, ref[0] / (predicted_peak(p) * ref[1]))
        if f.exists():
            y = np.load(f).astype(float)
        else:
            t0 = time.perf_counter()
            y = ch.run(p, pass_seed(stem, i))
            wall = time.perf_counter() - t0
            np.save(f, y.astype(np.float32))
            pk = 20 * np.log10(np.max(np.abs(y)) + 1e-12)
            print(f"  {ch.name:13s} {stem:10s} pass {i}: {wall / (len(y) / ch.fs):.2f}x real time, "
                  f"peak {pk:+.1f} dBFS", flush=True)  # fmt: skip
        if ref is None:  # pass 1's output peak per unit of predicted peak
            ref = (float(np.max(np.abs(y))), float(np.max(np.abs(y))) / predicted_peak(p))
        out.append(y)
        cur = y
    return out


def multisine(fs: int, spl_db: float) -> np.ndarray:
    """One period of a pink, random-phase multisine (seeded), every bin in F_MS excited."""
    rng = np.random.default_rng([20261114, 1])
    f = np.fft.rfftfreq(PERIOD, 1 / fs)
    a = np.where((f >= F_MS[0]) & (f <= F_MS[1]), 1 / np.sqrt(np.maximum(f, 1.0)), 0.0)
    X = a * np.exp(2j * np.pi * rng.random(len(f)))
    x = np.fft.irfft(X, n=PERIOD)
    return x * (P_REF * 10 ** (spl_db / 20) / np.sqrt(np.mean(x**2)))


def measure_h(ch: Chain, spl_db: float, tag: str) -> tuple[np.ndarray, np.ndarray]:
    """(freqs, H) on the period's grid, NaN outside the multisine's band."""
    f_cache = CACHE / ch.name / f"H_{_key(ch.name, spl_db, tag, PERIOD, MS_PERIODS, ch.over)}.npz"
    if f_cache.exists():
        z = np.load(f_cache)
        return z["f"], z["h"]
    one = multisine(ch.fs, spl_db)
    y = ch.run(np.tile(one, MS_PERIODS))
    yp = y[-2 * PERIOD :].reshape(2, PERIOD).mean(axis=0)
    X, Y = np.fft.rfft(one), np.fft.rfft(yp)
    f = np.fft.rfftfreq(PERIOD, 1 / ch.fs)
    band = (f >= F_MS[0]) & (f <= F_MS[1])
    h = np.full(len(f), np.nan + 0j)
    h[band] = Y[band] / X[band]
    f_cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(f_cache, f=f, h=h)
    return f, h


def h_on_grid(f_ms: np.ndarray, h_ms: np.ndarray, f: np.ndarray) -> np.ndarray:
    """H (normalized to 1 at 1 kHz) on another frequency grid: bulk delay out, real and imaginary
    parts interpolated, delay back. Outside the measured band: H's edge value."""
    ok = np.isfinite(h_ms)
    fm, hm = f_ms[ok], h_ms[ok]
    i1k = np.argmin(np.abs(fm - 1000.0))
    hm = hm / np.abs(hm[i1k])
    # bulk delay from the phase slope over 1-5 kHz
    sel = (fm > 1000) & (fm < 5000)
    ph = np.unwrap(np.angle(hm[sel]))
    tau = -np.polyfit(2 * np.pi * fm[sel], ph, 1)[0]
    hr = hm * np.exp(2j * np.pi * fm * tau)
    re = np.interp(f, fm, hr.real)
    im = np.interp(f, fm, hr.imag)
    return (re + 1j * im) * np.exp(-2j * np.pi * f * tau)


def apply_power(y: np.ndarray, f_ms, h_ms, k: int, fs: int) -> np.ndarray:
    """y through H^k (k may be negative), magnitude clamped, faded to unity outside the band."""
    n = 1 << int(np.ceil(np.log2(len(y) + fs)))  # >= 1 s of padding against the wrap
    f = np.fft.rfftfreq(n, 1 / fs)
    h = h_on_grid(f_ms, h_ms, f)
    g = h**k
    mag = np.abs(g)
    lim = 10 ** (CLAMP_DB / 20)
    g = g / mag * np.clip(mag, 1 / lim, lim)
    w = np.clip((f - F_LO[0]) / (F_LO[1] - F_LO[0]), 0, 1) * np.clip(
        (F_HI[1] - f) / (F_HI[1] - F_HI[0]), 0, 1
    )
    g = w * g + (1 - w)
    pad = n - len(y)
    yy = np.concatenate([np.zeros(pad // 2), y, np.zeros(pad - pad // 2)])
    z = np.fft.irfft(np.fft.rfft(yy) * g, n=n)
    return z[pad // 2 : pad // 2 + len(y)]


def band(x: np.ndarray, fs: int) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt

    return sosfiltfilt(butter(4, BAND_HZ, btype="bandpass", fs=fs, output="sos"), x)


def char_db(a: np.ndarray, b: np.ndarray, fs: int) -> dict[str, float]:
    """difference.levels of (a, b) in the audible band, the first and last EDGE_S left out (the
    passes' fades and the truncation of each pass's delay are time-varying: not the chain)."""
    n = len(a) if len(a) <= len(b) else len(b)
    e = int(EDGE_S * fs)
    return difference.levels(band(a[:n], fs)[e:-e], band(b[:n], fs)[e:-e])


EDGE_S = 0.1
# The residual's band (brick-wall). Below 40 Hz the stems' rumble meets the correction's fade to
# unity under 15-25 Hz: 95+ % of the U47 -> V76's residual at 80 dB SPL was there (2026-11-14).
RESID_BAND_HZ = (40.0, 20000.0)


def brick(x: np.ndarray, fs: int, lo_hi=RESID_BAND_HZ) -> np.ndarray:
    m = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(m, 1 / fs)
    X[(f < lo_hi[0]) | (f > lo_hi[1])] = 0.0
    return np.fft.irfft(X, m)


def residual_db(x: np.ndarray, y: np.ndarray, f_ms, h_ms, k: int, fs: int) -> float | None:
    """What the chain's measured response doesn't explain: `y` against g H^k `x` (H measured on the
    multisine, applied exactly, no fit; g a least-squares gain, the staging's), dB re `y` in
    RESID_BAND_HZ with EDGE_S left out at each end. k = 0: `y` against g `x`. None where H^k boosts
    past +CLAMP_DB re its 1 kHz value in the band (apply_power clamps it there: no prediction; a cut
    clamped at -CLAMP_DB leaves at most that much behind).

    This replaces `char_db`'s fitted decomposition for the passes. On these chains the fit's floor
    (a pure H^k through it) equals the "character" it reports, from the long low-frequency time
    constants a 0.34 s, 1/12-octave-smoothed fit can't follow. This measure's floor, by the same
    chains at 60 and 80 dB SPL and the omni control: about -55 to -64 dB."""
    if k:
        ok = np.isfinite(h_ms) & (f_ms >= RESID_BAND_HZ[0]) & (f_ms <= RESID_BAND_HZ[1])
        fin = np.flatnonzero(np.isfinite(h_ms))
        db = 20 * np.log10(np.abs(h_ms[ok]))
        db1k = 20 * np.log10(np.abs(h_ms[fin[np.argmin(np.abs(f_ms[fin] - 1000.0))]]))
        dev = k * (
            db - db1k
        )  # H^k re 1 kHz in the band; only a clamped boost breaks the prediction
        if np.max(dev) > CLAMP_DB:  # (a cut clamped at -CLAMP_DB leaves at most that much behind)
            return None
        x = apply_power(x, f_ms, h_ms, k, fs)
    n = min(len(x), len(y))
    e = int(EDGE_S * fs)
    a, b = brick(x[:n], fs)[e:-e], brick(y[:n], fs)[e:-e]
    g = float(np.dot(a, b) / np.dot(a, a))
    r = b - g * a
    return round(float(10 * np.log10(np.mean(r**2) / np.mean(b**2))), 2)


def residuals(ys, dry, spl_db: float, f_ms, h_ms, k: int, fs: int) -> dict:
    """Pass k's residuals: against the dry stem through H^k (what k passes added beyond their
    tone), and against its own input through H (what this pass alone added)."""
    xin = to_spl(ys[k - 2] if k > 1 else dry, spl_db, fs)
    return {
        "residual_vs_dry": residual_db(to_spl(dry, 94.0, fs), ys[k - 1], f_ms, h_ms, k, fs),
        "residual_this_pass": residual_db(xin, ys[k - 1], f_ms, h_ms, 1, fs),
    }


def peak_dbfs(y: np.ndarray) -> float:
    return round(float(20 * np.log10(np.max(np.abs(y)))), 1)


def write(path: Path, x: np.ndarray, fs: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gain = 10 ** ((matching.TARGET_LUFS - matching.integrated_lufs(x, fs)) / 20)
    y = x * gain
    pk = np.max(np.abs(y))
    if pk > 0.99:  # keep the loudness match honest: say so rather than clip
        rel = path.relative_to(OUT)
        print(f"  ! {rel} peaks {20 * np.log10(pk):+.1f} dBFS at the match; scaled down")
        y = y * 0.99 / pk
    sf.write(path, y.astype(np.float32), fs, subtype="FLOAT")


def plot_h(results: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = list(results)
    fig, axes = plt.subplots(len(names), 1, figsize=(8, 2.6 * len(names)), sharex=True)
    for ax, name in zip(np.atleast_1d(axes), names, strict=True):
        f, h = results[name]
        ok = np.isfinite(h)
        f, h = f[ok], h[ok]
        i1k = np.argmin(np.abs(f - 1000))
        db = 20 * np.log10(np.abs(h) / np.abs(h[i1k]))
        sm = np.convolve(db, np.ones(31) / 31, mode="same")
        for k in SHOWN:
            ax.semilogx(f, k * sm, label=f"{k} pass{'es' if k > 1 else ''}")
        ax.set_ylim(-40, 25)
        ax.set_xlim(20, 30000)
        ax.grid(True, which="both", alpha=0.3)
        ax.set_title(name, fontsize=9)
        ax.set_ylabel("dB re 1 kHz")
    np.atleast_1d(axes)[0].legend(fontsize=7, ncol=4)
    np.atleast_1d(axes)[-1].set_xlabel("Hz")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chains", nargs="*", default=CHAINS)
    ap.add_argument("--stems", nargs="*", default=None)
    ap.add_argument("--passes", type=int, default=8)
    ap.add_argument("--spl-db", type=float, default=100.0)
    ap.add_argument("--draft", action="store_true")
    ap.add_argument(
        "--time-one", action="store_true", help="one pass of each chain on 2 s, then stop"
    )
    ap.add_argument(
        "--set", nargs="*", default=None, metavar="KEY=VALUE", help="overrides (one chain)"
    )
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--noise", action="store_true", help="B5's noise on, a seed per stem and pass")
    args = ap.parse_args()
    tag = "draft" if args.draft else "production"
    stems = args.stems or sorted(p.stem for p in STEM_DIR.glob("*.wav"))
    over = (
        None
        if args.set is None
        else {k: float(v) for k, v in (kv.split("=", 1) for kv in args.set)}
    )
    chains = {n: Chain(n, args.draft, over, noise=args.noise) for n in args.chains}
    fs = next(iter(chains.values())).fs

    if args.time_one:
        x = load_stem(stems[0], fs)[int(1.0 * fs) : int(3.0 * fs)]
        for ch in chains.values():
            t0 = time.perf_counter()
            y = ch.run(to_spl(x, args.spl_db, fs))
            wall = time.perf_counter() - t0
            print(f"{ch.name}: {wall / 2.0:.2f}x real time (2 s + settle), "
                  f"peak {20 * np.log10(np.max(np.abs(y)) + 1e-12):+.1f} dBFS")  # fmt: skip
        return

    dry = {s: load_stem(s, fs) for s in stems}
    t0 = time.perf_counter()
    with ThreadPoolExecutor(args.workers) as ex:
        spl = {n: CHAIN_SPL_DB.get(n, args.spl_db) for n in chains}
        hs = {n: ex.submit(measure_h, ch, spl[n], tag) for n, ch in chains.items()}
        hs = {n: f.result() for n, f in hs.items()}  # the passes' staging reads them
        ps = {(n, s): ex.submit(passes, ch, s, dry[s], args.passes, spl[n], tag)
              for n, ch in chains.items() for s in stems}  # fmt: skip
        ps = {k: f.result() for k, f in ps.items()}
        clean = {}
        if args.noise:  # the noiseless pass 1 of the same input (cached by a run without --noise)
            cs = {n: Chain(n, args.draft, over) for n in chains}
            clean = {(n, s): ex.submit(passes, cs[n], s, dry[s], 1, spl[n], tag)
                     for n in chains for s in stems}  # fmt: skip
            clean = {k: f.result()[0] for k, f in clean.items()}
    print(f"renders done in {(time.perf_counter() - t0) / 60:.1f} min", flush=True)

    global OUT
    OUT = OUT / (tag + ("_noise" if args.noise else ""))
    OUT.mkdir(parents=True, exist_ok=True)
    plot_h(hs, OUT / "responses.png")
    summary: dict = {"spl_db": args.spl_db, "quality": tag, "noise": args.noise, "chains": {}}
    for s in stems:
        write(OUT / s / "dry.wav", dry[s], fs)
    for n in chains:
        f_ms, h_ms = hs[n]
        rows = {}
        for s in stems:
            ys = ps[(n, s)]
            d = OUT / s / n
            for k in SHOWN:
                if k > len(ys):
                    continue
                yk = ys[k - 1]
                write(d / f"p{k}.wav", yk, fs)
                xin = to_spl(ys[k - 2] if k > 1 else dry[s], spl[n], fs)  # this pass's input
                row = {
                    "residual_vs_dry": residual_db(to_spl(dry[s], 94.0, fs), yk, f_ms, h_ms, k, fs),
                    "residual_this_pass": residual_db(xin, yk, f_ms, h_ms, 1, fs),
                    "vs_dry": char_db(to_spl(dry[s], 94.0, fs), yk, fs),
                }
                if k == 1 and clean:
                    c1 = clean[(n, s)]
                    e = int(EDGE_S * fs)
                    dn, cn = band(yk - c1, fs)[e:-e], band(c1, fs)[e:-e]
                    row["noise_vs_clean"] = round(
                        float(10 * np.log10(np.mean(dn**2) / np.mean(cn**2))), 2
                    )
                if k > 1:
                    eq = apply_power(yk, f_ms, h_ms, -(k - 1), fs)
                    tone = apply_power(ys[0], f_ms, h_ms, k - 1, fs)
                    write(d / f"p{k}_eqnull.wav", eq, fs)
                    write(d / f"p{k}_tone.wav", tone, fs)
                    # the floor: p1 through H^(k-1) and back, the same clamps and fades
                    rt = apply_power(tone, f_ms, h_ms, -(k - 1), fs)
                    row["eqnull_vs_p1"] = char_db(ys[0], eq, fs)
                    row["floor_vs_p1"] = char_db(ys[0], rt, fs)
                    row["eqnull_residual_vs_p1"] = residual_db(ys[0], eq, f_ms, h_ms, 0, fs)
                    row["eqnull_floor_vs_p1"] = residual_db(ys[0], rt, f_ms, h_ms, 0, fs)
                rows.setdefault(s, {})[f"p{k}"] = row
        ok = np.isfinite(h_ms)
        fm, hm = f_ms[ok], h_ms[ok]
        i1k = np.argmin(np.abs(fm - 1000))
        pts = {}
        for fq in (50, 100, 200, 500, 2000, 5000, 10000, 15000, 20000):
            i = np.argmin(np.abs(fm - fq))
            pts[str(fq)] = round(float(20 * np.log10(np.abs(hm[i]) / np.abs(hm[i1k]))), 2)
        peaks = {s: [peak_dbfs(y) for y in ps[(n, s)]] for s in stems}
        summary["chains"][n] = {"spl_db": spl[n], "set": chains[n].over, "h_db_re_1k": pts,
                                "pass_peaks_dbfs": peaks, "stems": rows}  # fmt: skip
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    for n, c in summary["chains"].items():
        print(n)
        for s, v in c["stems"].items():
            cells = [
                f"{p} {fmt_db(r['residual_vs_dry'])} ({fmt_db(r['residual_this_pass'])})"
                for p, r in v.items()
            ]
            print(f"  {s:11s} residual vs dry (this pass): " + " | ".join(cells))


def fmt_db(v: float | None) -> str:
    return "   n/a" if v is None else f"{v:6.1f}"


if __name__ == "__main__":
    main()
