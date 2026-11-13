"""The literal bias's second line family (docs/TAPE_PLAN.md "Gaps" 8): lines at
|fs/2 - f_b|-type frequencies (6.0 kHz at f_b 90 and 102 kHz), -67 to -75 dB re a tone ~4 dB
over operating level, the same on 0.5 and 0.25 um cells but gone on cells of 7.62 per
ACTUAL bias wavelength (reports/tape/chirp/alias_map.json). A diagnosis: the tape medium
alone (circuitsim's TapeStream, the deck's medium as scripts/chirp_alias_map.py takes it,
the transport off), fed an ideal head field (a sine bias plus a 55.3 Hz tone at 0.6 mA rms on
8.0e6 A/m per A, the bias at the 351's 2.94 mA rms), one sampling changed at a time:

- the host rate fs (192 / 96 / 384 kHz, the literal input at m fs = 3.84 MHz throughout);
- the substeps m at 192 kHz;
- the cells (0.5, 0.25, 0.4 um and 7.62 per actual bias wavelength);
- the medium's own numerics (local zones, the demag iteration, the head's image, the
  playback's band edge lam_min, the zone floor);
- the tone (55.3 Hz / 1 kHz).

Per run: the strongest lines 200 Hz - 20 kHz that aren't the tone's harmonics (dB re the
tone), and the level at |fs/2 - f_b|. -> reports/tape/chirp/family2.json.

    uv run --extra fast python scripts/chirp_family2.py [--fb 90000 102000] [--only NAME ...]
        [--gpu] [--seconds 0.5]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
import time

import numpy as np

from varimu.config import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import chirp_medium  # noqa: E402

OUT = REPO_ROOT / "reports" / "tape" / "chirp"
TONE_HZ = 55.3
BIAS_MA, AUDIO_MA, HEAD_A_M_PER_A = 2.94, 0.6, 8.0e6

#: name -> (medium overrides, fs, m, tone_hz); "ds_matched" sets ds per f_b.
VARIANTS: dict[str, tuple[dict, float, int, float]] = {
    "base": ({"ds_m": 0.5e-6}, 192e3, 20, TONE_HZ),
    "ds025": ({"ds_m": 0.25e-6}, 192e3, 20, TONE_HZ),
    "ds040": ({"ds_m": 0.4e-6}, 192e3, 20, TONE_HZ),
    "ds0125": ({"ds_m": 0.125e-6}, 192e3, 20, TONE_HZ),
    # 7-1/2 ips (the 351's TP_LO, lam_min scaled as parts.tape does): the alias goes with
    # v / ds, so half the cells.
    "lo_ds025": ({"ds_m": 0.25e-6, "speed_m_s": 0.1905, "lam_min_m": 5.715e-6}, 192e3, 20, TONE_HZ),
    "lo_ds0125": (
        {"ds_m": 0.125e-6, "speed_m_s": 0.1905, "lam_min_m": 5.715e-6},
        192e3,
        20,
        TONE_HZ,
    ),
    "ds_matched": ({"ds_m": "matched"}, 192e3, 20, TONE_HZ),
    "fs96": ({"ds_m": 0.5e-6}, 96e3, 40, TONE_HZ),
    "fs384": ({"ds_m": 0.5e-6}, 384e3, 10, TONE_HZ),
    "m10": ({"ds_m": 0.5e-6}, 192e3, 10, TONE_HZ),
    "m40": ({"ds_m": 0.5e-6}, 192e3, 40, TONE_HZ),
    "no_local_zones": ({"ds_m": 0.5e-6, "local_zones": False}, 192e3, 20, TONE_HZ),
    "no_demag": ({"ds_m": 0.5e-6, "demag_iterations": 0}, 192e3, 20, TONE_HZ),
    "no_image": ({"ds_m": 0.5e-6, "head_image": False}, 192e3, 20, TONE_HZ),
    "floor_half": ({"ds_m": 0.5e-6, "zone_floor": 0.5}, 192e3, 20, TONE_HZ),
    "tone1k": ({"ds_m": 0.5e-6}, 192e3, 20, 1000.0),
}


def lines(y: np.ndarray, fs: float, tone_hz: float, n: int = 4) -> list[tuple[float, float]]:
    w = np.blackman(len(y))
    sp = np.abs(np.fft.rfft(y * w)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / fs)
    ref = sp[np.abs(f - tone_hz) < 4].sum()
    harm = np.abs(f / tone_hz - np.round(f / tone_hz)) * tone_hz < 15
    ok = (f > 200) & (f < 20_000) & ~harm
    out: list[tuple[float, float]] = []
    for i in np.argsort(np.where(ok, sp, 0.0))[::-1]:
        if not ok[i]:
            break
        fi = float(f[i])
        if all(abs(fi - g) > 300 for g, _ in out):
            out.append((round(fi), round(10 * math.log10(sp[i - 3 : i + 4].sum() / ref), 1)))
        if len(out) == n:
            break
    return out


def level_at(y: np.ndarray, fs: float, tone_hz: float, at_hz: float) -> float | None:
    if not 200 < at_hz < fs / 2:
        return None
    w = np.blackman(len(y))
    sp = np.abs(np.fft.rfft(y * w)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / fs)
    ref = sp[np.abs(f - tone_hz) < 4].sum()
    return round(10 * math.log10(sp[np.abs(f - at_hz) < 30].sum() / ref + 1e-300), 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fb", type=float, nargs="+", default=[90_000.0, 102_000.0])
    ap.add_argument("--only", nargs="+")
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--seconds", type=float, default=0.5)
    ap.add_argument("--out", default="family2.json")
    a = ap.parse_args()
    import circuitsim

    base = dataclasses.replace(chirp_medium.medium("deck"), flutter=(), flutter_noise=())
    path = OUT / a.out
    res = json.loads(path.read_text()) if path.exists() else {"rows": []}
    for name in a.only or list(VARIANTS):
        over, fs, m, tone = VARIANTS[name]
        for fb in a.fb:
            over2 = dict(over)
            if over2.get("ds_m") == "matched":
                over2["ds_m"] = base.speed_m_s / (fb * 7.62)
            if "zone_floor" in over2:
                over2["zone_floor_a_m"] = base.zone_floor_a_m * over2.pop("zone_floor")
            md = dataclasses.replace(base, bias_substeps=m, f_bias_hz=fb, **over2)
            params = json.dumps(dataclasses.asdict(md))
            n = int((a.seconds + md.head_distance_m / md.speed_m_s + 0.05) * fs)
            t = (np.arange(n * m) + 1 - 2 * m) / (m * fs)
            env = np.clip(t / 0.02, 0.0, 1.0)
            hb = BIAS_MA * 1e-3 * math.sqrt(2) * HEAD_A_M_PER_A
            ha = AUDIO_MA * 1e-3 * math.sqrt(2) * HEAD_A_M_PER_A
            h = env * (
                ha * np.sin(2 * math.pi * tone * t) + hb * np.sin(2 * math.pi * fb * t + 0.3)
            )
            t0 = time.time()
            y = np.asarray(circuitsim.tape_stream_run(params, fs, h, chunk=20 * m * 48, gpu=a.gpu))
            y = y[int(md.head_distance_m / md.speed_m_s * fs) + int(0.05 * fs) :]
            row = {
                "variant": name,
                "f_bias_hz": fb,
                "fs": fs,
                "substeps": m,
                "ds_um": md.ds_m * 1e6,
                "tone_hz": tone,
                "lines": lines(y, fs, tone),
                "at_half_fs_minus_fb": level_at(y, fs, tone, abs(fs / 2 - fb)),
                "seconds": round(time.time() - t0, 1),
                "gpu": a.gpu,
            }
            print(json.dumps(row), flush=True)
            res["rows"] = [
                r for r in res["rows"] if (r["variant"], r["f_bias_hz"]) != (name, fb)
            ] + [row]
            path.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
