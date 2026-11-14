"""SC1 (docs/INSTRUMENT_REALISM_FABLE.md): the Suitcase's speakers as a filter after the device.

Live, `rhodes_suitcase` plays each channel's speaker terminal voltage (`live_speaker_v`: the
speakers are loads only). A speaker part without a field winding is linear (R, L, C, Vccs:
`parts.speaker_driver`, `parts.speaker_readout`, whose readout draws no current), so the
pressure 1 m in front is a fixed linear filter H of that voltage, whatever drives it. This
script measures H from the circuit itself: each channel's speaker elements are taken from the
built IR with and without the readout, solved by AC analysis (`varimu.measure.ac`), and H is
the ratio of the readout's `out` to the terminal build's `out` (one driver's volts of the
`series` pair). The impulse response per host rate is H sampled on a long FFT grid,
truncated where its tail is below `TAIL_DB`.

    uv run python scripts/suitcase_speaker_filter.py [--check] [--plot]

Writes config/speaker_filters/<circuit>.json: per channel (`out`, `out_r`) the impulse
response in pascals per volt at each rate in RATES_HZ, the circuit file's sha256 and the
speaker component's version (a filter that doesn't match its circuit is stale), and the
magnitude at a few frequencies. `--check`: exit 1 when the saved file is missing or stale.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

# Thousands of tiny solves: BLAS threads only thrash (100x slower on this desktop).
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.circuit.ir import CircuitIR, Section, VoltageProbe, element_nodes  # noqa: E402
from varimu.measure import ac  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CIRCUIT = "rhodes_suitcase_100w"
# Speaker part per live output (the circuit's probes `out` / `out_r`).
CHANNELS = {"out": "ASPK", "out_r": "BSPK"}
RATES_HZ = (44_100, 48_000, 88_200, 96_000)
WINDOW_S = 1.3  # the FFT's length, at least: the driver's low ring must not wrap round
TAIL_DB = -48.0  # truncate where everything after is below this, re the whole (see below)
# Past ~50 ms the readout's response is mostly its back wave's lumped delay line ringing at
# its cutoff (speaker.LADDER_SECTION_S: 5.1 kHz, Q in the thousands between its end
# terminations), about -70 dB re the peak for over a second: a numerical artifact of the
# readout, not a cone mode. -48 dB keeps ~50 ms and drops it (and keeps the live cost down:
# the convolver runs on the stream's own thread, and the Suitcase plays at its edge).
TAPER = 0.15  # at most this top share of the band below Nyquist is tapered...
TAPER_HZ = (18_000.0, 22_000.0)  # ...to zero over this range, at every rate
MAX_DROPPED_DB = -45.0  # refuse an impulse that drops more of its energy than this
PRE_S = 0.5e-3  # kept ahead of the onset (the band-limited jump's pre-ring): the latency
DROPPED: dict[int, float] = {}  # per rate, filled by impulse()
REPORT_HZ = (50, 100, 200, 500, 1000, 2000, 3000, 4000, 6000, 8000, 12000, 16000)
FORMAT = 1


def circuit_path() -> Path:
    return ROOT / "config" / "circuits" / f"{CIRCUIT}.yaml"


def out_path() -> Path:
    return ROOT / "config" / "speaker_filters" / f"{CIRCUIT}.json"


def sha256(path: Path) -> str:
    """The file's sha256 with CRLF read as LF (a checkout's line endings aren't a change)."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _speaker_ir(ir: CircuitIR, part: str, out: str) -> CircuitIR:
    """The part's elements alone, driven at its plus node (its minus is ground here)."""
    els = [e for e in ir.elements() if part in e.name]
    if not els:
        raise SystemExit(f"{CIRCUIT}: no elements of speaker {part}")
    # The plus node: the coil's series resistance R<PART>_re runs from it.
    re = next(e for e in els if e.name == f"R{part}_re")
    plus = element_nodes(re)[0]
    return CircuitIR(
        title=f"{CIRCUIT} {part}",
        input_node=plus,
        probes=(VoltageProbe(out),),
        models=(),
        sections=(Section(title=part, elements=tuple(els)),),
    )


_IRS: dict[str, tuple[CircuitIR, CircuitIR]] = {}


def speaker_irs() -> dict[str, tuple[CircuitIR, CircuitIR]]:
    """Per channel, its speaker part alone from the readout build and the terminal build."""
    if not _IRS:
        s = spec.load_circuit(circuit_path())
        p = spec.resolve(s, {})
        full = builder.build_ir(s, p, cores="linear", speaker_readout=True)
        term = builder.build_ir(s, p, cores="linear", speaker_readout=False)
        for node, part in CHANNELS.items():
            _IRS[node] = (_speaker_ir(full, part, node), _speaker_ir(term, part, node))
    return _IRS


def responses(f_hz: np.ndarray) -> dict[str, np.ndarray]:
    """H(f) per channel: pascals at 1 m per volt of the live `out` (one driver's volts).
    The terminal build's `out` is a fixed fraction of the drive (1 / series): checked at a
    few frequencies, not solved on the whole grid."""
    out = {}
    for node, (readout, terminal) in speaker_irs().items():
        tv = ac.transfer(terminal, [10.0, 1000.0, 20000.0], node)
        if not np.allclose(tv, tv[0].real, rtol=1e-12, atol=0):
            raise SystemExit(f"{node}: the terminal build's out isn't a constant fraction: {tv}")
        out[node] = ac.transfer(readout, f_hz, node) / tv[0].real
    return out


def latency(fs: int) -> int:
    """The filter's delay in samples at fs: PRE_S kept ahead of the onset."""
    return int(np.ceil(PRE_S * fs))


def n_fft(fs: int) -> int:
    """A power of two covering WINDOW_S at fs: 44.1 / 88.2 kHz and 48 / 96 kHz pairs share
    their frequency spacing, so one solve serves both."""
    return 1 << int(np.ceil(np.log2(fs * WINDOW_S)))


_GRID: dict[float, dict[str, np.ndarray]] = {}  # per spacing: H on the widest grid solved


def h_on_grid(fs: int, node: str) -> np.ndarray:
    n = n_fft(fs)
    df = fs / n
    need = n // 2 + 1
    have = _GRID.get(df)
    if have is None or len(have[node]) < need:
        widest = max((r for r in RATES_HZ if r / n_fft(r) == df), default=fs)
        f = np.fft.rfftfreq(n_fft(widest), 1 / widest)
        f[0] = 1e-3  # H(0) is 0 (pressure follows acceleration); a regular solve near it
        print(f"solving H on {len(f)} frequencies ({df:.3f} Hz apart)", flush=True)
        have = _GRID[df] = responses(f)
    return have[node][:need].copy()


def impulse(fs: int, node: str) -> np.ndarray:
    N_FFT = n_fft(fs)  # noqa: N806 (the transform's length)
    f = np.fft.rfftfreq(N_FFT, 1 / fs)
    h = h_on_grid(fs, node)
    h[0] = 0.0
    # Band-limited, H's sharp onset pre-rings (wraps to the FFT's end). A raised-cosine taper
    # to zero over the top of the audio band (TAPER_HZ, or the top share TAPER of a lower
    # Nyquist) keeps that small; above it the cone's breakup is inaudible anyway.
    top = min(fs / 2, TAPER_HZ[1])
    lo = min(TAPER_HZ[0], (1 - TAPER) * top)
    w = np.where(f > lo, 0.5 * (1 + np.cos(np.pi * np.clip((f - lo) / (top - lo), 0, 1))), 1.0)
    h = h * w
    full = np.fft.irfft(h, N_FFT)
    # The response jumps at t = 0 (the front wave's onset); band-limited, half that ramp lies
    # before 0 and wraps to the FFT's end. PRE_S of it is kept (the filter's latency, in
    # samples: latency(fs)); the rest of the wrapped end is dropped, like the tail.
    d = latency(fs)
    full = np.roll(full, d)
    x, pre = full[: -N_FFT // 8], full[-N_FFT // 8 :]
    total = float(np.sum(full * full))
    e = np.cumsum((x * x)[::-1])[::-1]  # energy from n on
    limit = total * 10 ** (TAIL_DB / 10)
    n = int(np.argmax(e < limit)) if np.any(e < limit) else len(x)
    tail = float(e[n]) if n < len(x) else 0.0
    dropped_db = 10 * np.log10((float(np.sum(pre * pre)) + tail) / total)
    if dropped_db > MAX_DROPPED_DB:
        raise SystemExit(f"impulse at {fs} Hz: {dropped_db:.1f} dB of its energy dropped")
    DROPPED[fs] = round(float(dropped_db), 1)
    return x[:n]


def compute() -> dict:
    s = spec.load_circuit(circuit_path())
    p = spec.resolve(s, {})
    channels = {}
    rep = responses(np.asarray(REPORT_HZ, float))
    for node in CHANNELS:
        irs = {str(fs): impulse(fs, node).tolist() for fs in RATES_HZ}
        channels[node] = {
            "part": CHANNELS[node],
            "impulse_pa_per_v": irs,
            "magnitude_db_re_1pa_per_v": {
                str(f): round(float(20 * np.log10(abs(v))), 2)
                for f, v in zip(REPORT_HZ, rep[node], strict=True)
            },
        }
    return {
        "format": FORMAT,
        "circuit": CIRCUIT,
        "circuit_sha256": sha256(circuit_path()),
        "speaker_component": str(p["speaker_model"]),
        "source": "scripts/suitcase_speaker_filter.py: AC analysis of the circuit's speaker "
        "parts, readout over terminal build (docs/INSTRUMENT_REALISM_FABLE.md SC1)",
        "input": "the live build's out / out_r: one driver's terminal volts",
        "output": "pascals 1 m on axis in front of the channel's front driver",
        "rates_hz": list(RATES_HZ),
        "dropped_energy_db": {str(k): v for k, v in DROPPED.items()},
        "latency_samples": {str(fs): latency(fs) for fs in RATES_HZ},
        "channels": channels,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the saved filter is stale")
    ap.add_argument("--plot", action="store_true", help="save the response plot beside the report")
    a = ap.parse_args()
    path = out_path()
    if a.check:
        if not path.exists():
            print(f"{path}: missing")
            return 1
        saved = json.loads(path.read_text())
        if saved["circuit_sha256"] != sha256(circuit_path()):
            print(f"{path}: stale (the circuit changed)")
            return 1
        print(f"{path}: current")
        return 0
    data = compute()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")
    for node, ch in data["channels"].items():
        lens = {fs: len(v) for fs, v in ch["impulse_pa_per_v"].items()}
        print(f"{node} ({ch['part']}): taps {lens}")
        print("  dB re 1 Pa/V:", ch["magnitude_db_re_1pa_per_v"])
    print(f"wrote {path}")
    if a.plot:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        f = np.geomspace(20, 20_000, 400)
        h = responses(f)
        fig, ax = plt.subplots(figsize=(8, 4))
        for node, v in h.items():
            ax.semilogx(f, 20 * np.log10(np.abs(v)), label=node)
        ax.set_xlabel("Hz")
        ax.set_ylabel("dB re 1 Pa per terminal volt")
        ax.set_title(f"{CIRCUIT}: speaker pressure / terminal voltage")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend()
        rep = ROOT / "reports" / "rhodes" / "speaker_filter"
        rep.mkdir(parents=True, exist_ok=True)
        fig.savefig(rep / "response.png", dpi=120, bbox_inches="tight")
        print(f"wrote {rep / 'response.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
