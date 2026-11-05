"""A scene's live balance (the native app's Room view, BALANCE): each source's stereo stem in
the mics' mix, so the sources' levels can be set while it plays, before the render.

The room is linear: mic m's two entries hear sum_s x_s * h_sm (varimu.rooms.scene's
responses, per unit source). Its chain isn't, but at a quiet level it is close to linear:
`chain_proxy` measures its responses from each entry to its out (at the print's full scale)
in one draft run: a random-phase multisine on each entry, periodic in the response's length,
in two experiments, (front, rear) then (front, -rear), each averaged over whole periods after
settling, so each frequency's two responses are exact (no window, no noise; cached in
cache/rooms/proxies/). Noise on the entries and Welch's estimate were tried first: their
variance on the U47's long low-frequency tail left the proxy -22 dB from the chain.

So mic m's print is about sum_s y_sm, y_sm = x_s * g_sm with g_sm = h_sm,front * H_m,front
+ h_sm,rear * H_m,rear, and the mix of the mics (panned by the session's balance law) is
sum_s stem_s: one stereo stem per source, which a fader scales.

What the proxy leaves out: the chains' saturation (a louder source drives them harder) and
their noise. Each mic's predicted peaks per source (`peaks`, linear, per `PEAK_BLOCK_S`) let
the app bound how hard a balance drives each chain: sum_s g_s peak_sm per block.

`prepare(scene, out_dir)` writes `balance.json` (the sources' SPLs as prepared and their
stems' files, the mics, the peaks) and each source's `<name>.L.wav` / `<name>.R.wav` (mono
float32 at the project's rate, all the same length, from the scene's first sample).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from varimu.config import REPO_ROOT

PROXIES = REPO_ROOT / "cache" / "rooms" / "proxies"
PROXY_QUALITY = "draft"
PROXY_PA_RMS = 0.05  # 68 dB SPL on each entry: quiet, where the chains are linear
PROXY_TAPS = 65536  # each response's length, the multisine's period (0.68 s at 96 kHz)
PROXY_SETTLE_PERIODS = 2  # periods left out after each start (the couplings' tails)
PROXY_PERIODS = 2  # periods averaged
# the responses start this many samples before t = 0: the engine's input interpolation looks
# ahead, so a chain answers a little early, which a periodic measurement wraps to the period's
# end (left there, the omni chain's proxy was -33.5 dB from it, all above 5 kHz)
PROXY_LEAD = 256
PEAK_BLOCK_S = 0.05


def _proxy_key(ir_json: str, settings) -> str:
    import circuitsim

    hsh = hashlib.sha256()
    for part in (
        ir_json,
        repr(settings),
        circuitsim.SOURCE_HASH,
        Path(__file__).read_text(encoding="utf-8"),
    ):
        hsh.update(part.encode())
    return hsh.hexdigest()[:32]


def chain_proxy(chain: str, over: dict) -> tuple[np.ndarray, np.ndarray | None]:
    """A chain's linear responses (front entry -> out, rear entry -> out or None for a chain
    with one entry), `PROXY_TAPS` long at the project's rate, out at the print's full scale
    per pascal, starting `PROXY_LEAD` samples before t = 0 (the module docstring; cached)."""
    from varimu.circuit import builder, spec
    from varimu.rooms.scene import _settings
    from varimu.sim import fast
    from varimu.sim.io import full_scale

    s = _settings(PROXY_QUALITY)
    c = spec.load_circuit(spec.circuit_path(chain))
    ir = builder.build(c, over).ir
    path = PROXIES / f"{_proxy_key(ir.to_json(), s)}.npz"
    if path.exists():
        z = np.load(path)
        return z["front"], (z["rear"] if "rear" in z else None)
    rear = any(k.name == "p_rear" for k in ir.controls)
    p = PROXY_TAPS
    rng = np.random.default_rng([0, zlib.crc32(chain.encode())])
    spec_u = np.zeros((2, p // 2 + 1), complex)  # every bin but DC and Nyquist, phases random
    spec_u[:, 1:-1] = np.exp(2j * np.pi * rng.random((2, p // 2 - 1)))
    u = np.fft.irfft(spec_u, p, axis=-1)
    u *= PROXY_PA_RMS / u.std(axis=-1, keepdims=True)
    spec_u = np.fft.rfft(u, axis=-1)
    reps = PROXY_SETTLE_PERIODS + PROXY_PERIODS
    # experiment 1 (front, rear), then 2 (front, -rear): one run
    signs = (1.0, -1.0) if rear else (1.0,)
    front = np.concatenate([np.tile(u[0], reps) for _ in signs])
    back = np.concatenate([sg * np.tile(u[1], reps) for sg in signs])
    v = fast.run_transient(ir, front, settings=s, controls={"p_rear": back} if rear else None)
    y = v.vectors["v(out)"] / full_scale(s, c)[1]
    ys = []  # each experiment's response, averaged over its periods after the settling ones
    for e in range(len(signs)):
        a = (e * reps + PROXY_SETTLE_PERIODS) * p
        ys.append(np.fft.rfft(y[a : a + PROXY_PERIODS * p].reshape(PROXY_PERIODS, p), axis=-1)
                  .mean(0))  # fmt: skip
    hf = np.zeros((2, p // 2 + 1), complex)
    sl = slice(1, -1)
    if rear:
        hf[0, sl] = (ys[0][sl] + ys[1][sl]) / (2 * spec_u[0, sl])
        hf[1, sl] = (ys[0][sl] - ys[1][sl]) / (2 * spec_u[1, sl])
    else:
        hf[0, sl] = ys[0][sl] / spec_u[0, sl]
    h = np.roll(np.fft.irfft(hf, p, axis=-1), PROXY_LEAD, axis=-1)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp.npz")
    np.savez(tmp, front=h[0], **({"rear": h[1]} if rear else {}))
    os.replace(tmp, path)
    return h[0], (h[1] if rear else None)


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in name).strip() or "x"


def prepare(scene, out_dir: Path, log: Callable[[str], None] = print) -> dict:
    """The scene's stems and peaks into out_dir (the module docstring); returns
    balance.json's data."""
    from scipy.signal import fftconvolve, oaconvolve

    from varimu.rooms.progress import Step, fmt_s
    from varimu.rooms.scene import _settings, balance, scene_responses, source_signals
    from varimu.sim.io import write_audio

    fs = _settings(scene.quality).sample_rate
    log(f"balance: {len(scene.sources)} sources x {len(scene.mics)} mics")
    signals = source_signals(scene, fs)
    h, _ = scene_responses(scene, fs, log)
    # the chains' proxies, one per chain and setting, measured in parallel
    keys = [(m.chain, json.dumps(m.set, sort_keys=True)) for m in scene.mics]
    todo = sorted(set(keys))
    secs = 2 * (PROXY_SETTLE_PERIODS + PROXY_PERIODS) * PROXY_TAPS / fs
    log(f"chain stand-ins: {len(todo)} chains in parallel, each a {secs:.0f} s draft run the "
        "first time (~10 s), then cached")  # fmt: skip
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max(1, min(len(todo), (os.cpu_count() or 4) - 2))) as ex:
        proxies = list(ex.map(lambda k: chain_proxy(k[0], json.loads(k[1])), todo))
    got = dict(zip(todo, proxies, strict=True))
    log(f"chain stand-ins: done in {fmt_s(time.perf_counter() - t0)}")
    n = max(len(x) for x in signals) + h.shape[-1] + PROXY_TAPS - 1
    block = int(round(PEAK_BLOCK_S * fs))
    nb = -(-n // block)
    out_dir.mkdir(parents=True, exist_ok=True)
    peaks = np.zeros((len(scene.sources), len(scene.mics), nb))
    pans = [balance(m.pan) for m in scene.mics]
    nm = len(scene.mics)
    stems = Step(log, "stems", "stems", [len(x) * nm for x in signals])
    sources = []
    for si, (src, x) in enumerate(zip(scene.sources, signals, strict=True)):
        stems.start(si, f"source {si + 1} ({src.name}) through {nm} mics' chains")
        st = np.zeros((2, n))
        for mi in range(nm):
            hf, hr = got[keys[mi]]
            g = fftconvolve(h[si, mi, 0], hf)
            if hr is not None:
                g += fftconvolve(h[si, mi, 1], hr)
            g = g[PROXY_LEAD:]  # back to t = 0 (`chain_proxy`)
            y = oaconvolve(x, g)[:n]
            y = np.pad(y, (0, n - len(y)))
            peaks[si, mi] = np.abs(np.pad(y, (0, nb * block - n))).reshape(nb, block).max(1)
            st[0] += pans[mi][0] * y
            st[1] += pans[mi][1] * y
        files = []
        for side, ch in (("L", 0), ("R", 1)):
            f = out_dir / f"{_safe(src.name)}.{side}.wav"
            write_audio(f, st[ch].astype(np.float32), fs)
            files.append(f.name)
        sources.append({"name": src.name, "spl_db": src.spl_db, "left": files[0],
                        "right": files[1]})  # fmt: skip
    stems.end()
    result = {
        "scene": scene.name,
        "fs": fs,
        "seconds": round(n / fs, 3),
        "sources": sources,
        "mics": [{"name": m.name, "chain": m.chain, "pan": m.pan} for m in scene.mics],
        "peaks_block_s": PEAK_BLOCK_S,
        # (sources, mics, blocks): each mic's print's peak per block, linear re full scale
        "peaks": [[[float(f"{v:.4g}") for v in pm] for pm in ps] for ps in peaks],
        "proxy_level_db_spl": round(20 * np.log10(PROXY_PA_RMS / 20e-6), 1),
    }
    (out_dir / "balance.json").write_text(json.dumps(result), encoding="utf-8")
    log("done")
    return result
