"""Listening renders for the virtual head (docs/BINAURAL_PLAN.md): sounds placed and moved
round a head, anechoic, for headphones -> reports/binaural/listen/<head>/ (+ README.md).

Heads: `sphere` (no ears: the control, front and back can't differ), `pp1` (FABIAN, the
HUTUBS dummy head, simulated by crates/roomsim's body solver), `pp1_measured` (the same
head's measured HRIRs: reality, to A/B the simulation against), and any simulated HUTUBS
subject (`pp<N>`, from the cache; scripts/binaural_validate.py simulates them).

Per head:
- tour_<stimulus>.wav: the stimulus at front, front-right, right, back-right, back,
  back-left, left, front-left (clockwise from the nose, 45 deg apart), then above-front
  (elevation 60) and below-front (elevation -30); 0.4 s of silence between positions.
- circle.wav: pink noise going round twice clockwise from the front in 12 s.
- frontback_<stimulus>.wav: the stimulus at 30 deg left of the nose, then its mirror 30 deg
  left of straight behind (azimuth 150), alternating four times: the same time and level
  difference between the ears, only the ear's shape tells them apart.

Each file is loudness-normalized (-20 LUFS) and 96 kHz stereo float32 (left = left ear).

    uv run --extra binaural --extra listen python scripts/binaural_demo.py \
        [--heads sphere pp1 pp1_measured pp2 ...]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf

from varimu.binaural.hrtf import cached_head
from varimu.binaural.render import FS, Binaural, SofaHead, SphereHead

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "binaural" / "listen"
HUTUBS = ROOT / "data" / "hrtf" / "hutubs"

TOUR = [
    (0, 0),
    (-45, 0),
    (-90, 0),
    (-135, 0),
    (180, 0),
    (135, 0),
    (90, 0),
    (45, 0),
    (0, 60),
    (0, -30),
]
TOUR_NAMES = [
    "front",
    "front-right",
    "right",
    "back-right",
    "back",
    "back-left",
    "left",
    "front-left",
    "above-front",
    "below-front",
]


def load_head(name: str):
    if name == "sphere":
        return SphereHead()
    if name.endswith("_measured"):
        subj = name.removesuffix("_measured")
        return SofaHead(HUTUBS / "HRIRs" / f"{subj}_HRIRs_measured.sofa", name)
    h = cached_head(f"hutubs_{name}")
    if h is None:
        raise SystemExit(
            f"{name}: not simulated yet (scripts/binaural_validate.py --subject {name},"
            " or scripts/binaural_variants.py for ppN-pinnaSSS)"
        )
    return h


def _read(path: Path, start_s: float | None, seconds: float) -> np.ndarray:
    from scipy.signal import resample_poly

    x, fs = sf.read(path, dtype="float64", always_2d=True)
    x = x.mean(axis=1)
    if fs != FS:
        from fractions import Fraction

        q = Fraction(FS, fs).limit_denominator(1000)
        x = resample_poly(x, q.numerator, q.denominator)
    n = int(seconds * FS)
    if start_s is None:  # the loudest window
        cs = np.concatenate([[0.0], np.cumsum(x**2)])
        w = n // 8
        e = cs[w:] - cs[:-w]  # energy of each window of w samples
        c = int(np.argmax(e)) + w // 2
        lo = max(0, min(c - n // 2, len(x) - n))
    else:
        lo = int(start_s * FS)
    y = x[lo : lo + n]
    ramp = int(0.01 * FS)
    y[:ramp] *= np.linspace(0, 1, ramp)
    y[-ramp:] *= np.linspace(1, 0, ramp)
    return y / (np.abs(y).max() + 1e-12)


def pink(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    X = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / FS)
    X[1:] /= np.sqrt(f[1:])
    X[0] = 0
    X[f < 60] *= (f[f < 60] / 60) ** 2
    y = np.fft.irfft(X, n)
    return y / np.abs(y).max()


def stimuli() -> dict[str, np.ndarray]:
    bursts = []
    for k in range(3):
        b = pink(int(0.25 * FS), 100 + k)
        r = int(0.005 * FS)
        b[:r] *= np.linspace(0, 1, r)
        b[-r:] *= np.linspace(1, 0, r)
        bursts += [b, np.zeros(int(0.06 * FS))]
    out = {"noise": np.concatenate(bursts)}
    clap = sorted((ROOT / "samples" / "drums" / "clap").glob("*.wav"))
    if clap:
        c = _read(clap[0], 0.0, 0.4)
        out["clap"] = np.concatenate([c, np.zeros(int(0.15 * FS)), c])
    voice = ROOT / "stems" / "Did she mention my name" / "full" / "lead vocal.wav"
    if voice.exists():
        out["voice"] = _read(voice, None, 2.5)
    guitar = ROOT / "data" / "clips" / "Dry Guitar.wav"
    if guitar.exists():
        out["guitar"] = _read(guitar, None, 2.5)
    return out


def normalize(y: np.ndarray) -> np.ndarray:
    import pyloudnorm

    meter = pyloudnorm.Meter(FS)
    lufs = meter.integrated_loudness(y.T)
    y = y * 10 ** ((-20.0 - lufs) / 20)
    peak = np.abs(y).max()
    return y / peak * 0.95 if peak > 0.95 else y


def render_head(name: str, stims: dict, out: Path):
    b = Binaural(load_head(name))
    out.mkdir(parents=True, exist_ok=True)
    gap = np.zeros((2, int(0.4 * FS)))
    for sname, x in stims.items():
        parts = []
        for az, el in TOUR:
            parts += [b.place(x, az, el), gap]
        sf.write(
            out / f"tour_{sname}.wav",
            normalize(np.concatenate(parts, axis=1)).T.astype(np.float32),
            FS,
        )
        parts = []
        for _ in range(4):
            parts += [b.place(x, 30, 0), gap, b.place(x, 150, 0), gap, gap]
        sf.write(
            out / f"frontback_{sname}.wav",
            normalize(np.concatenate(parts, axis=1)).T.astype(np.float32),
            FS,
        )
    n = 12 * FS
    az = -720.0 * np.arange(n) / n  # clockwise from the front, twice
    y = b.path(pink(n, 7) * 0.5, az, np.zeros(n))
    sf.write(out / "circle.wav", normalize(y).T.astype(np.float32), FS)
    print(f"{name}: {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--heads", nargs="*", default=["sphere", "pp1", "pp1_measured"])
    args = ap.parse_args(argv)
    stims = stimuli()
    for h in args.heads:
        render_head(h, stims, OUT / h)


if __name__ == "__main__":
    main()
