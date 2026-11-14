"""SC1 step 3 (docs/INSTRUMENT_REALISM_FABLE.md): the speaker filter against the readout build.

Renders the Suitcase (`rhodes_suitcase_100w`) on rhodes_render.py's demo phrase, its first
two bars, at draft twice: with the speakers' readouts (`out` / `out_r` the pressure 1 m out,
as renders are) and as the app plays it live (`speaker_readout=False`: each channel's one
driver's terminal volts). The second, convolved with config/speaker_filters/<circuit>.json's
impulse at the render's rate, should be the first delayed by the filter's latency.

    uv run --extra fast --extra listen python scripts/suitcase_speaker_filter_check.py [--bars 2]

Prints, per channel, the difference re the readout build's signal (rms dB, whole and per
octave band) and writes reports/rhodes/speaker_filter/check.json and the three WAVs
(readout, terminal, filtered; 0 dBFS = the file's 25 Pa or the live 14 V).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
import rhodes_render  # noqa: E402
import suitcase_speaker_filter as filt  # noqa: E402

from varimu.circuit import builder, spec  # noqa: E402
from varimu.sim import fast  # noqa: E402
from varimu.sim.io import TransientSettings, full_scale, write_audio  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "rhodes" / "speaker_filter"
LIVE_SPEAKER_V = 14.0  # the app's `live_speaker_v` for rhodes_suitcase (panel.rs)
BANDS_HZ = (63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)


def db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-30)))


def band_rms(x: np.ndarray, fs: float, fc: float) -> float:
    sos = signal.butter(
        4, [fc / np.sqrt(2), min(fc * np.sqrt(2), 0.45 * fs)], "bandpass", fs=fs, output="sos"
    )
    return float(np.sqrt(np.mean(signal.sosfilt(sos, x) ** 2)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bars", type=int, default=2)
    ap.add_argument("--tail", type=float, default=1.5)
    a = ap.parse_args()

    saved = json.loads(filt.out_path().read_text())
    if saved["circuit_sha256"] != filt.sha256(filt.circuit_path()):
        raise SystemExit("the speaker filter is stale: run scripts/suitcase_speaker_filter.py")

    beat = 60 / 90
    end = a.bars * 4 * beat
    events = [e for e in rhodes_render.demo_events() if e.t_s < end]
    events = sorted(events, key=lambda e: (e.t_s, e.kind != "off"))
    notes = [(e.t_s, e.kind, e.note, e.value) for e in events]
    duration = max(e.t_s for e in events) + a.tail

    c = spec.load_circuit(filt.circuit_path())
    p = spec.resolve(c, {})
    s = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    fs = int(s.sample_rate)
    if str(fs) not in saved["channels"]["out"]["impulse_pa_per_v"]:
        raise SystemExit(f"no impulse at {fs} Hz")
    x = np.zeros(int(round(duration * fs)))
    runs = {}
    for label, readout in (("readout", True), ("terminal", False)):
        ir = builder.build_ir(c, p, speaker_readout=readout)
        t0 = time.perf_counter()
        vec = fast.run_transient(ir, x, settings=s, notes=notes).vectors
        dt = time.perf_counter() - t0
        print(
            f"{label}: {dt:.0f} s for {duration:.1f} s ({dt / duration:.1f}x real time)", flush=True
        )
        runs[label] = {ch: np.asarray(vec[f"v({ch})"]) for ch in filt.CHANNELS}

    d = saved["latency_samples"][str(fs)]
    result = {"fs_hz": fs, "duration_s": duration, "latency_samples": d, "channels": {}}
    OUT.mkdir(parents=True, exist_ok=True)
    stereo = {k: [] for k in ("readout", "terminal", "filtered")}
    for ch in filt.CHANNELS:
        g = np.asarray(saved["channels"][ch]["impulse_pa_per_v"][str(fs)])
        ref = runs["readout"][ch]
        y = signal.oaconvolve(runs["terminal"][ch], g)[: len(ref)]
        ref_d = np.concatenate([np.zeros(d), ref])[: len(ref)]
        err = y - ref_d
        skip = int(0.05 * fs)  # the run's first 50 ms (both start from the operating point)
        whole = db(np.sqrt(np.mean(err[skip:] ** 2)) / np.sqrt(np.mean(ref_d[skip:] ** 2)))
        bands = {
            str(fc): round(db(band_rms(err[skip:], fs, fc) / band_rms(ref_d[skip:], fs, fc)), 1)
            for fc in BANDS_HZ
        }
        result["channels"][ch] = {"difference_db": round(whole, 1), "bands_db": bands}
        print(f"{ch}: difference {whole:.1f} dB re the readout build; per octave {bands}")
        pa = full_scale(s, c)[1]  # the file's 25 Pa
        stereo["readout"].append(ref_d / pa)
        stereo["terminal"].append(runs["terminal"][ch] / LIVE_SPEAKER_V)
        stereo["filtered"].append(y / pa)
    for k, v in stereo.items():
        write_audio(OUT / f"check_{k}.wav", np.column_stack(v).astype(np.float32), fs)
    (OUT / "check.json").write_text(json.dumps(result, indent=1) + "\n")
    print(f"wrote {OUT / 'check.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
