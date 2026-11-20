"""WZ2's study: the Wurlitzer 200A's electronics (config/circuits/wurlitzer_200a.yaml) against
its drawing and the Pie-finger set (docs/WURLITZER_PLAN.md, WZ2).

    uv run --extra fast python scripts/wurlitzer_amp_study.py [--only idle vibrato response power]

- idle: the operating point against the drawing's printed voltages;
- vibrato: at VIBRATO full, the rate and depth (dB peak to peak) of the AUX output's envelope
  on a steady tone, against the Pie-finger set's 5.74 Hz and ~6 dB;
- response: the plate's test input to the AUX output and to the speaker terminals (dB) over
  frequency, VIBRATO off;
- power: the speaker terminals' clipping (1% THD) at 1 kHz into the 8 ohm load.

-> reports/wurlitzer/amp/{summary.json, README.md}
"""

from __future__ import annotations

import argparse
import dataclasses
import json

import numpy as np
from scipy import signal

from varimu.circuit import builder, spec
from varimu.circuit.ir import VoltageProbe
from varimu.config import REPO_ROOT
from varimu.sim import fast, io

CIRCUIT = REPO_ROOT / "config" / "circuits" / "wurlitzer_200a.yaml"
FS = 96000
OUT = REPO_ROOT / "reports" / "wurlitzer" / "amp"
PROBES = (
    "out",
    "spk",
    "j2",
    "h30",
    "o11",
    "o13",
    "pk",
    "pa",
    "b1",
    "c1",
    "e1",
    "c2",
    "e2",
    "x",
    "po",
    "p13",
    "p15",
    "c34",
    "b3",
    "e3",
    "o",
    "v15",
    "vpos",
    "vneg",
    "hv150",
    "vw",
    "c15",
    "e15",
    "c16",
    "e16",
    "et",
    "c7",
    "c14",
    "b10",
)

# the drawing's printed DC voltages (V) at the probes that have one
PRINTED = {
    "b1": 2.45,
    "e1": 1.95,
    "c1": 4.1,
    "c2": 8.8,
    "e2": 3.4,
    "b3": 1.25,
    "e3": 0.68,
    "c34": 5.9,
    "c15": 4.0,
    "e15": 0.96,
    "c16": 7.7,
    "e16": 2.9,
    "et": 0.64,
    "c7": -22.0,
    "c14": -0.65,
    "b10": 0.65,
    "o": 0.0,
    "vpos": 22.5,
    "vneg": -22.5,
    "v15": 15.0,
    "hv150": 150.0,
}


def render(sets: dict, x_in: np.ndarray, quality: str = "production") -> dict[str, np.ndarray]:
    s = spec.load_circuit(CIRCUIT)
    ir = builder.build_ir(s, spec.resolve(s, sets))
    ir = dataclasses.replace(ir, probes=tuple(VoltageProbe(p) for p in PROBES))
    st = dataclasses.replace(
        io.TransientSettings.from_sim_settings(engine="circuitsim", quality=quality),
        full_scale_volts_peak=1.0,
    )
    v = fast.run_transient(ir, x_in, settings=st).vectors
    return {p: np.asarray(v[f"v({p})"]) for p in PROBES}


def idle() -> dict:
    v = render({}, np.zeros(int(0.05 * FS)))
    got = {p: float(np.mean(v[p][-int(0.01 * FS) :])) for p in PROBES}
    rows = {p: {"model_v": got[p], "drawing_v": PRINTED.get(p)} for p in PROBES}
    for p, r in rows.items():
        d = r["drawing_v"]
        print(f"  {p:6s} {r['model_v']:9.3f} V" + (f"   drawing {d:7.2f}" if d is not None else ""))
    iq = (got["o11"] - got["o"]) / 0.47
    print(f"  output stage's idle current {iq * 1e3:.2f} mA (through R37)")
    return rows | {"idle_current_a": iq}


def envelope_db(y: np.ndarray, f0: float, fs: float) -> np.ndarray:
    sos = signal.butter(4, [f0 * 0.7, f0 * 1.4], "bandpass", fs=fs, output="sos")
    z = signal.sosfiltfilt(sos, y)
    env = np.abs(signal.hilbert(z))
    sos2 = signal.butter(2, 40.0, "low", fs=fs, output="sos")
    return 20 * np.log10(signal.sosfiltfilt(sos2, env) + 1e-12)


def envelope_stats(y: np.ndarray, f0: float, fs: float, skip_s: float) -> dict:
    """The vibrato's rate, depth (the detrended dB envelope's 1st to 99th percentile) and
    shape (the envelope's 2nd harmonic re its fundamental, dB): the same measure on the model
    and on the recording."""
    e = envelope_db(y, f0, fs)[int(skip_s * fs) : -int(0.2 * fs)]
    tt = np.arange(e.size) / fs
    e = e - np.polyval(np.polyfit(tt, e, 2), tt)
    nfft = 1 << 22
    sp_ = np.abs(np.fft.rfft(e * np.hanning(e.size), nfft))
    fr = np.fft.rfftfreq(nfft, 1 / fs)
    sel = (fr > 1) & (fr < 15)
    k1 = np.flatnonzero(sel)[np.argmax(sp_[sel])]
    k2 = int(np.argmin(np.abs(fr - 2 * fr[k1])))
    return {
        "rate_hz": float(fr[k1]),
        "depth_db_pp": float(np.percentile(e, 99) - np.percentile(e, 1)),
        "h2_db": float(20 * np.log10(sp_[k2 - 3 : k2 + 4].max() / sp_[k1 - 3 : k1 + 4].max())),
    }


PIE_FINGER = (
    REPO_ROOT
    / "real instrument samples"
    / "Pie-finger Wurlitzer 200A sample set"
    / "Pie-finger Wurlitzer 200A sample set"
)


def vibrato_reference() -> dict:
    """The Pie-finger set's VIBRATO-full notes in octave 4 (the low-velocity set: no pedal),
    measured as the model is."""
    import re

    import soundfile as sf

    notes = {
        "C": 0,
        "C#": 1,
        "D": 2,
        "D#": 3,
        "E": 4,
        "F": 5,
        "F#": 6,
        "G": 7,
        "G#": 8,
        "A": 9,
        "A#": 10,
        "B": 11,
    }
    rows = []
    for p in sorted((PIE_FINGER / "Vibrato notes" / "vibrato (full), low vel").glob("*4.wav")):
        m = re.search(r"-([A-G]#?)4\.wav$", p.name)
        f0 = 440.0 * 2 ** ((notes[m.group(1)] - 9) / 12) * 2 ** (5 / 1200)
        y, fs = sf.read(p)
        on = int(np.argmax(np.abs(y) > 0.1 * np.max(np.abs(y))))
        y = y[on:]
        if y.size < 1.8 * fs:
            continue
        rows.append(envelope_stats(y, f0, fs, 0.3))
    return {k: float(np.median([r[k] for r in rows])) for k in rows[0]} | {"notes": len(rows)}


def vibrato_model(trim: float | None = None, seconds: float = 3.0) -> dict:
    f0 = 330.0
    n = int(seconds * FS)
    t = np.arange(n) / FS
    sets = {"vibrato": 1.0} | ({} if trim is None else {"vib_trim": trim})
    v = render(sets, 0.2 * np.sin(2 * np.pi * f0 * t))
    r = envelope_stats(v["out"], f0, FS, 1.0)
    osc = v["c34"][int(1.0 * FS) :]
    return r | {"osc_vpp": float(np.ptp(osc)), "osc_mean_v": float(np.mean(osc))}


def vibrato() -> dict:
    real = vibrato_reference()
    model = vibrato_model()
    print(
        f"  Pie-finger (octave 4, {real['notes']} notes): rate {real['rate_hz']:.3f} Hz, depth "
        f"{real['depth_db_pp']:.2f} dB p-p, envelope H2 {real['h2_db']:.1f} dB"
    )
    print(
        f"  model: rate {model['rate_hz']:.3f} Hz, depth {model['depth_db_pp']:.2f} dB p-p, "
        f"envelope H2 "
        f"{model['h2_db']:.1f} dB; oscillator {model['osc_vpp']:.2f} V p-p (drawing 11.5) around "
        f"{model['osc_mean_v']:.2f} V (drawing 5.9)"
    )
    return {"model": model, "pie_finger": real}


def vibrato_fit() -> dict:
    """R17 (`vib_trim`) bisected so VIBRATO full's depth is the Pie-finger set's: the depth
    rises from R17 = 0 (the cell saturated) to a maximum near a quarter turn."""
    target = vibrato_reference()["depth_db_pp"]
    lo, hi = 0.0, 0.25
    d_lo = vibrato_model(lo)["depth_db_pp"]
    for _ in range(7):
        mid = 0.5 * (lo + hi)
        d = vibrato_model(mid)["depth_db_pp"]
        print(f"  vib_trim {mid:.4f}: depth {d:.2f} dB (target {target:.2f})", flush=True)
        if (d - target) * (d_lo - target) > 0:
            lo, d_lo = mid, d
        else:
            hi = mid
    trim = 0.5 * (lo + hi)
    return {"vib_trim": trim, "target_db_pp": target, "model": vibrato_model(trim)}


def response() -> dict:
    freqs = np.unique(np.round(np.geomspace(30, 15000, 36)))
    n = FS
    t = np.arange(n) / FS
    rng = np.random.default_rng(1)
    ph = rng.uniform(0, 2 * np.pi, freqs.size)
    x = (
        0.05
        * np.sum(np.sin(2 * np.pi * freqs[:, None] * t + ph[:, None]), axis=0)
        / np.sqrt(freqs.size)
    )
    v = render({}, x)
    seg = slice(n // 2, n)
    k = np.round(freqs * (n // 2) / FS).astype(int)

    def gain(y: np.ndarray) -> np.ndarray:
        return 20 * np.log10(
            np.abs(np.fft.rfft(y[seg])[k]) / np.abs(np.fft.rfft(x[seg])[k]) + 1e-30
        )

    out = {
        "freqs_hz": freqs.tolist(),
        "aux_db": gain(v["out"]).tolist(),
        "spk_db": gain(v["spk"]).tolist(),
        "plate_db": gain(v["pk"]).tolist(),
        "preamp_db": gain(v["po"]).tolist(),
    }
    for f_, a, s_, pl in zip(
        freqs[::5], out["aux_db"][::5], out["spk_db"][::5], out["plate_db"][::5], strict=True
    ):
        print(f"  {f_:7.0f} Hz  plate {pl:6.1f}  aux {a:6.1f}  speaker {s_:6.1f} dB")
    return out


def thd(y: np.ndarray, f0: float) -> float:
    n = y.size
    s = np.abs(np.fft.rfft(y * np.hanning(n)))
    k0 = int(round(f0 * n / FS))
    fund = s[k0 - 2 : k0 + 3].max()
    h = [s[k * k0 - 2 : k * k0 + 3].max() for k in range(2, 11) if k * k0 + 3 < s.size]
    return float(np.sqrt(np.sum(np.square(h))) / fund)


def power() -> dict:
    """The speaker terminals' 1% THD point at 1 kHz, VOLUME full, raising the test input."""
    rows = []
    for a in (0.05, 0.1, 0.2, 0.45, 1.0, 1.6, 2.0, 2.4, 2.8, 3.2):
        n = int(0.3 * FS)
        t = np.arange(n) / FS
        v = render({"volume": 1.0}, a * np.sin(2 * np.pi * 1000 * t))
        seg = v["spk"][n // 2 :]
        p_w = float(np.mean(seg**2) / 8.0)
        rows.append(
            {
                "in_v": a,
                "thd": thd(seg, 1000.0),
                "watts": p_w,
                "aux_vpk": float(np.max(np.abs(v["out"][n // 2 :]))),
            }
        )
        print(
            f"  in {a:.2f} V: {p_w:6.2f} W into 8 ohm, THD {rows[-1]['thd'] * 100:6.2f} %, "
            f"AUX {rows[-1]['aux_vpk']:.3f} V peak"
        )
    return {"rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=["idle", "vibrato", "response", "power"])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "summary.json"
    res = json.loads(path.read_text()) if path.exists() else {}
    for name in args.only:
        print(f"{name}:", flush=True)
        res[name] = globals()[name]()
    path.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
