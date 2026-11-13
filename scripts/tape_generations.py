"""AM4, generations (docs/ANALOG_MAGIC_FABLE.md): the aligned Ampex 351 printed over and over,
as a four-track production bounced its rhythm tracks.

- Unity between generations: a 400 Hz tone at 0 VU (-18 dBFS rms) printed once; the one
  measured gain that brings it back to 0 VU is applied between generations (never a
  loudness normalization: the tape's compression is part of the result).
- A different stretch of tape per generation: generation k is built with noise seed k (grain,
  transport, hiss, hum together).
- The heads' delay is out (render.ampex_351); the electronics' remaining delay is taken out
  by aligning each generation to its input (whole samples).
- Two chains, generation by generation: the program (20 s of the user's cover, its four lanes
  summed plain: cache/magic/forensics/cover/cover_plain.wav, the mid) and a test signal
  (0 VU tones at 400 Hz and 1 kHz, -20 dB tones at 50 / 100 / 1k / 5k / 10k / 15k Hz, a 0 VU
  3150 Hz tone for flutter, silence for S/N).
- The bounce: the rhythm lanes (bass, guitar) each printed, summed, printed again, against
  their sum printed once.

-> reports/magic/generations/ (summary.json, generations.png, audio/ loudness-matched
G0 / G1 / G2 / G4 and the bounce pair).

  uv run --extra fast --extra listen python scripts/tape_generations.py [--generations 4]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import soundfile as sf

from varimu.config import REPO_ROOT
from varimu.listen import difference
from varimu.magic import fingerprints as fp
from varimu.magic import null, render
from varimu.sim.io import load_audio, write_audio

OUT = REPO_ROOT / "reports" / "magic" / "generations"
COVER = REPO_ROOT / "cache" / "magic" / "forensics" / "cover" / "cover_plain.wav"
LANES = REPO_ROOT / "cache" / "lightfoot_mix" / "dry"
VU0 = 10 ** (-18 / 20) * np.sqrt(2)  # 0 VU sine peak (-18 dBFS rms)
RESP_HZ = (50.0, 100.0, 1000.0, 5000.0, 10000.0, 15000.0)


def tone(f, seconds, amp, fs):
    t = np.arange(int(seconds * fs)) / fs
    x = amp * np.sin(2 * np.pi * f * t)
    r = int(0.01 * fs)
    x[:r] *= np.linspace(0, 1, r)
    x[-r:] *= np.linspace(1, 0, r)
    return x


def test_signal(fs):
    """(signal, {name: (start, end) in samples})."""
    parts, marks, pos = [], {}, 0
    def add(name, x):
        nonlocal pos
        parts.append(x)
        marks[name] = (pos, pos + len(x))
        pos += len(x)
    add("thd400", tone(400.0, 4.0, VU0, fs))
    add("thd1k", tone(1000.0, 4.0, VU0, fs))
    for f in RESP_HZ:
        add(f"resp{f:g}", tone(f, 3.0, VU0 * 10 ** (-20 / 20), fs))
    add("flutter", tone(3150.0, 6.0, VU0, fs))
    add("silence", np.zeros(int(4.0 * fs)))
    return np.concatenate(parts), marks


def print_gen(x, k, gain):
    y = render.ampex_351(x * gain, noise=k, tail_s=0.0)["out"]
    d, _ = null.lag_of(x, y, int(0.01 * render.sample_rate()))
    s = int(round(d))
    y = np.roll(y, -s)
    if s > 0:
        y[-s:] = 0.0
    return y[: len(x)]


def measure_tones(y, marks, fs):
    from varimu.measure.tape_align import thd

    def seg(name, skip=0.5, tail=0.25):
        a, b = marks[name]
        return y[a + int(skip * fs) : b - int(tail * fs)]
    out = {"thd400_pct": 100 * thd(seg("thd400"), fs, 400.0)[0],
           "thd1k_pct": 100 * thd(seg("thd1k"), fs, 1000.0)[0]}
    ref = None
    resp = {}
    for f in RESP_HZ:
        r = float(np.sqrt(np.mean(seg(f"resp{f:g}") ** 2)))
        resp[f"{f:g}"] = r
    ref = resp["1000"]
    out["response_db"] = {k: 20 * np.log10(v / ref) for k, v in resp.items()}
    vu = float(np.sqrt(np.mean(seg("thd1k") ** 2)))
    sil = seg("silence", skip=0.5, tail=0.5)
    out["snr_db"] = 20 * np.log10(vu / fp.band_rms(sil, fs, 50.0, 15000.0))
    out["flutter"] = fp.flutter(seg("flutter", 0.0, 0.0), fs, (2000.0, 4500.0))
    return out


def measure_program(g0, gk, fs):
    n = min(len(g0), len(gk))
    g0, gk = g0[:n], gk[:n]
    return {
        "difference": difference.levels(g0, gk),
        "thirds_re_g0": null.band_levels(gk, g0, fs),
        "crest_by_band": fp.crest_by_band(gk, fs),
        "comodulation": fp.comodulation(gk, fs),
        "floor_follow": fp.floor_follow(gk, fs),
        "asymmetry": fp.asymmetry(gk, fs),
        "level_distribution": fp.level_distribution(gk, fs),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--generations", type=int, default=4)
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--start", type=float, default=40.0)
    a = ap.parse_args()
    fs = render.sample_rate()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Unity: the 400 Hz tone at 0 VU, once, without noise.
    u = tone(400.0, 3.0, VU0, fs)
    yu = render.ampex_351(u, noise=False, tail_s=0.0)["out"]
    m = slice(int(1.0 * fs), int(2.5 * fs))
    gain = float(np.sqrt(np.mean(u[m] ** 2)) / np.sqrt(np.mean(yu[m] ** 2)))
    print(f"unity: the 351 gives {-20 * np.log10(gain):+.2f} dB at 0 VU 400 Hz; "
          f"applying {20 * np.log10(gain):+.2f} dB between generations", flush=True)

    x = load_audio(COVER, fs)[int(a.start * fs) : int((a.start + a.seconds) * fs)]
    x = x * 10 ** (-18 / 20) / np.std(x)  # the program at 0 VU rms
    f = int(0.02 * fs)
    x[:f] *= np.linspace(0, 1, f)
    ts, marks = test_signal(fs)
    gens = {"program": [x], "test": [ts]}
    bounce = {}
    with ThreadPoolExecutor(4) as ex:
        # The bounce's first prints run beside generation 1.
        lanes = [load_audio(LANES / f"src_{k}.wav", fs)[int(a.start * fs) : int((a.start + a.seconds) * fs)]
                 for k in (1, 2)]
        tot = lanes[0] + lanes[1]
        sc = 10 ** (-18 / 20) / np.std(tot)
        lanes = [v * sc for v in lanes]
        tot = tot * sc
        fb = [ex.submit(print_gen, lanes[0], 101, gain), ex.submit(print_gen, lanes[1], 102, gain),
              ex.submit(print_gen, tot, 103, gain)]
        for k in range(1, a.generations + 1):
            tk = time.time()
            fp_ = ex.submit(print_gen, gens["program"][-1], k, gain)
            ft = ex.submit(print_gen, gens["test"][-1], k, gain)
            gens["program"].append(fp_.result())
            gens["test"].append(ft.result())
            el = time.time() - tk
            print(f"  generation {k}: {el / 60:.1f} min (ETA {(a.generations - k) * el / 60:.0f} min)",
                  flush=True)
        p1, p2, once = (f.result() for f in fb)
        twice = print_gen(p1 + p2, 104, gain)
        bounce = {"each_then_again": twice, "summed_once": once}
    print(f"all prints in {(time.time() - t0) / 60:.1f} min", flush=True)

    summ = {"gain_between_db": 20 * np.log10(gain), "generations": {}}
    for k in range(0, a.generations + 1):
        r = {"tones": measure_tones(gens["test"][k], marks, fs)}
        if k > 0:
            r["program"] = measure_program(gens["program"][0], gens["program"][k], fs)
        summ["generations"][k] = r
        t = r["tones"]
        print(f"  G{k}: THD 400 {t['thd400_pct']:.2f}% 1k {t['thd1k_pct']:.2f}%, S/N {t['snr_db']:.1f} dB, "
              f"wow {100 * t['flutter']['wow']:.3f}% flutter {100 * t['flutter']['flutter']:.3f}%, "
              f"resp 50 {t['response_db']['50']:+.2f} 15k {t['response_db']['15000']:+.2f}", flush=True)
    summ["bounce"] = {"each_then_again_vs_once": difference.levels(bounce["summed_once"], bounce["each_then_again"])}
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1, default=float))

    from varimu.listen.matching import match_loudness

    keep = [0, 1, 2, a.generations]
    clips = [gens["program"][k] for k in keep]
    matched, _ = match_loudness(clips, fs)
    for k, v in zip(keep, matched, strict=True):
        write_audio(OUT / "audio" / f"cover_G{k}.wav", v, fs)
    mb, _ = match_loudness([bounce["summed_once"], bounce["each_then_again"]], fs)
    write_audio(OUT / "audio" / "bounce_summed_once.wav", mb[0], fs)
    write_audio(OUT / "audio" / "bounce_each_then_again.wav", mb[1], fs)
    plot(summ)
    return 0


def plot(summ):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = summ["generations"]
    ks = sorted(int(k) for k in g)
    fig, ax = plt.subplots(1, 3, figsize=(15, 4))
    ax[0].plot(ks, [g[k]["tones"]["snr_db"] for k in ks], "o-", label="S/N")
    ax[0].plot(ks, [g[ks[0]]["tones"]["snr_db"] - 10 * np.log10(max(k, 1)) if k else g[0]["tones"]["snr_db"] for k in ks],
               "k:", label="G1 - 10 log10 N")
    ax[0].set(xlabel="generation", ylabel="dB", title="S/N")
    for key in ("thd400_pct", "thd1k_pct"):
        ax[1].plot(ks, [g[k]["tones"][key] for k in ks], "o-", label=key)
    ax[1].set(xlabel="generation", ylabel="%", title="THD at 0 VU")
    for f in ("50", "100", "5000", "10000", "15000"):
        ax[2].plot(ks, [g[k]["tones"]["response_db"][f] for k in ks], "o-", label=f"{f} Hz")
    ax[2].set(xlabel="generation", ylabel="dB re 1 kHz", title="response at -20 dB")
    for a_ in ax:
        a_.grid(alpha=0.3)
        a_.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "generations.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
