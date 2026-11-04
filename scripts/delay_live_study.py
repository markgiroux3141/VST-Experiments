"""The tape delay's real-time tier, measured before anything is built (docs/DELAY_PLAN.md,
"Real time", "Measure first").

`electronics`: does the Ampex 351's circuit, without the medium, fit real time at the draft
quality (96 kHz internal, TR-BDF2, tube tables, linear cores)? The aligned machine with the
oscillator out of its socket (the live tier carries the bias as an amplitude, TAPE_PLAN.md
TM5's option B), no multi-rate sections, and the tape replaced by a resistor from the input
into the repro head's grid at about the level a tape gives there (the drawing's -68 dB re
0.78 V at 8.2 dB under the operating level, so the repro side works as hard as it does on
tape; flat, without the tape's spectrum). Each layout timed on the drums at +6 dB drive, one
job alone, the 1 s settle counted:
- `one`: every section on the audio thread, the supply on the draft's second (its default);
- `split`: record | reproduce and output | supply, each on a thread of its own (the medium
  is where the live tier cuts; the repro side then gets no feed: idle, a lower bound).

    uv run --extra fast python scripts/delay_live_study.py electronics [--seconds 4]

`medium`: the reduced tape (varimu.delay.reduced) against the full stream on the same deep-gap
field, the drums at each `--drives`. `--speed-ips 7.5` runs both at 7-1/2 ips (the full
medium's cells 7.62 per bias wavelength there); `--reduction-ips 15` then plays the reduction
made at 15 ips, its apertures (positions behind the gap) scaled by the speeds' ratio and its
D(k) (a wavenumber's) as measured there: whether one speed's reduction serves another.

    uv run --extra fast python scripts/delay_live_study.py medium --demag [--speed-ips 7.5]
        [--reduction-ips 15] [--h-max 200e3 --points 481]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time

import numpy as np

from varimu.circuit import builder, spec
from varimu.circuit import ir as irm
from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta
from varimu.sim import fast
from varimu.sim.io import TransientSettings, load_audio

CACHE = REPO_ROOT / "cache" / "delay" / "live"
RECORD = ("record amplifier", "bias and head driver", "microphone stage (idle)")
GROUP_BREAK = "|"


def electronics_ir(overrides: dict, feed_ohm: float | None) -> irm.CircuitIR:
    """The aligned 351 at the audio rate with no tape (see the module docs). feed_ohm: the
    resistor from the input to the repro head's grid (None: none)."""
    c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
    ir = builder.build(c, {**overrides, "oscillator": 0}, cores="linear", noise=False).ir
    secs = []
    for s in ir.sections:
        els = [e for e in s.elements if not isinstance(e, irm.Tape)]
        if feed_ohm is not None and s.title == "reproduce amplifier":
            els.append(irm.Resistor("RFEED", ir.input_node, "rh", feed_ohm))
        secs.append(dataclasses.replace(s, elements=tuple(els), substeps=None))
    return dataclasses.replace(ir, sections=tuple(secs))


def electronics(a) -> dict:
    al = ta.aligned()
    st = TransientSettings.from_sim_settings(engine="circuitsim", quality="draft")
    fs = st.sample_rate
    c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
    v_in, v_out = c.full_scale
    x = load_audio(REPO_ROOT / "data" / "clips" / a.clip, fs)[: int(a.seconds * fs)]
    u = x * v_in * 10 ** (a.drive_db / 20)
    # The repro head's grid: -68 dB re 0.78 V at 8.2 dB under the operating level (0 VU in =
    # -18 dBFS rms) against the input's 0 VU, 0.2449 V rms; 2R25 330K is the grid's load.
    head_v = 0.775 * 10 ** ((-68 + 8.2) / 20)
    ratio = head_v / 0.2449
    feed_ohm = 330e3 * (1 / ratio - 1)
    layouts = {
        "one": (electronics_ir(al.overrides, feed_ohm), st),
        "split": (
            electronics_ir(al.overrides, None),
            dataclasses.replace(st, partition=(*RECORD, GROUP_BREAK, "power supply")),
        ),
    }
    res = {}
    for name in a.layouts:
        ir, s = layouts[name]
        stats: dict = {}
        t0 = time.perf_counter()
        r = fast.run_transient(ir, u, settings=s, stats=stats)
        el = time.perf_counter() - t0
        y = r.vectors["v(out)"] / v_out
        row = {
            "x_real_time": el / (len(u) / fs + s.settle_s),
            "seconds": el,
            "out_dbfs_peak": float(20 * np.log10(np.abs(y).max() + 1e-12)),
            "partition": fast.partition_sections(ir, s),
        }
        res[name] = row
        print(name, json.dumps(row), flush=True)
    return res


def _ips_tag(ips: float) -> str:
    """Cache names' speed tag (none at 15 ips: the caches made before speeds had tags)."""
    return "" if ips == 15.0 else f"_{ips:g}ips"


def medium_setup(a, ips: float | None = None):
    """The 351's tape spec at `ips` (default `--speed-ips`; no flutter: runs compare sample
    by sample), the tape, the aligned bias, the reduction (cached), the networks."""
    from varimu.delay import reduced as rd
    from varimu.devices import library
    from varimu.devices import tape_machine as tm

    c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
    p = spec.resolve(c, {})
    ips = a.speed_ips if ips is None else ips
    p = {**p, "speed_m_s": ips * 0.0254}
    sp = dataclasses.replace(rd.spec_351(p), flutter=False)
    tape = library.load_tape(str(p["tape_model"]))
    hb = rd.bias_hg(a.bias_ma_rms, p["rec_h_per_a"])
    # 0 VU: the aligned machine's 0.38 mA rms of audio in the head at 400 Hz (the alignment's
    # check), as a deep-gap peak.
    hg_0vu = rd.bias_hg(0.38, p["rec_h_per_a"])
    path = CACHE / f"reduction_{hb:.0f}_{a.h_max:.0f}_{a.points}{_ips_tag(ips)}.npz"
    if path.exists():
        z = np.load(path)
        red = rd.Reduction(**{k: (z[k] if z[k].ndim else float(z[k])) for k in z.files})
    else:
        t0 = time.perf_counter()
        red = rd.reduce(sp, tape, hb, a.h_max, a.points)
        print(f"reduction in {time.perf_counter() - t0:.0f} s", flush=True)
        np.savez(path, **dataclasses.asdict(red))
    # The idealized NAB networks (the medium-level alignment's trims; both runs go through
    # the same ones, so they only weight the comparison as a listener hears it).
    al = tm.Alignment(
        hg_bias=hb, hg_0vu=hg_0vu, rec_trim_tz_s=6.88e-6, rep_trim_tz_s=1.05e-5, out_gain=1.0
    )
    return sp, tape, red, al, tm


def bands(y: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Third-octave band powers 31.5 Hz-16 kHz."""
    f = np.fft.rfftfreq(len(y), 1.0 / fs)
    p = np.abs(np.fft.rfft(y)) ** 2
    fc = 1000.0 * 2.0 ** (np.arange(-15, 13) / 3.0)
    out = np.array([p[(f >= c * 2 ** (-1 / 6)) & (f < c * 2 ** (1 / 6))].sum() for c in fc])
    return fc, out


def demag_correction(a, sp, tape, red, al, tm, fs) -> tuple[np.ndarray, np.ndarray]:
    """D(k): the reference stream's linear response over the reduced stream's without the
    correction, on band-limited white noise at a_level dB re 0 VU's field, as a function
    of the wavenumber k = 2 pi f / v (its magnitude, smoothed over a sixth of an octave;
    D(0) = 1). Cached."""
    import circuitsim
    from scipy import signal

    from varimu.delay import reduced as rd

    tag = _ips_tag(sp.speed_m_s / 0.0254)
    path = CACHE / f"demag_{red.hg_bias:.0f}_{a.ds_um:g}_{a.demag_level_db:+.0f}{tag}.npz"
    if path.exists():
        z = np.load(path)
        return z["k"], z["d"]
    rng = np.random.default_rng([1, 351])
    n = int(4.0 * fs)
    b, aa = signal.butter(8, 20e3, fs=fs)
    w = signal.lfilter(b, aa, rng.standard_normal(n))
    h = w / np.sqrt(np.mean(w**2)) * al.hg_0vu / np.sqrt(2) * 10 ** (a.demag_level_db / 20)
    v = sp.speed_m_s
    delay = int(round(sp.head_distance_m / v * fs))
    feed = np.concatenate([h, np.zeros(delay + 64)])
    params = tm.stream_params(sp, tape, red.hg_bias, head_distance_m=delay * v / fs)
    e_ref = circuitsim.tape_stream_run(json.dumps(params), fs, feed)[delay - 1 : delay - 1 + n]
    st = rd.ReducedStream(sp, tape, red, fs, ds_m=a.ds_um * 1e-6, head_distance_m=delay * v / fs)
    chunk = int(fs * 0.05)
    e_red = np.concatenate([st.push_many(feed[c : c + chunk]) for c in range(0, len(feed), chunk)])
    e_red = e_red[delay - 1 : delay - 1 + n]
    f, sxy = signal.csd(e_red, e_ref, fs=fs, nperseg=8192)
    _, sxx = signal.welch(e_red, fs=fs, nperseg=8192)
    mag = np.abs(sxy / sxx)
    keep = (f > 20) & (f < 0.45 * fs)
    f, mag = f[keep], mag[keep]
    sm = np.array([mag[(f >= x * 2 ** (-1 / 12)) & (f <= x * 2 ** (1 / 12))].mean() for x in f])
    sm = sm / sm[0]
    k = np.concatenate([[0.0], 2 * np.pi * f / v])
    d = np.concatenate([[1.0], sm])
    np.savez(path, k=k, d=d)
    return k, d


def medium(a) -> dict:
    """The reduced medium against the reference stream on the same deep-gap field (see
    the module docs)."""
    import circuitsim

    from varimu.delay import reduced as rd

    sp, tape, red, al, tm = medium_setup(a)
    fs = TransientSettings.from_sim_settings(engine="circuitsim").sample_rate
    demag = demag_correction(a, sp, tape, red, al, tm, fs) if a.demag else None
    tag = ("_demag" if a.demag else "") + _ips_tag(a.speed_ips)
    if a.reduction_ips is not None and a.reduction_ips != a.speed_ips:
        # Another speed's reduction: its apertures are positions behind the gap (their times
        # scale as the speeds' ratio), its D(k) a function of the wavenumber.
        sp_r, _, red_r, _, _ = medium_setup(a, a.reduction_ips)
        q = sp_r.speed_m_s / sp.speed_m_s
        red = dataclasses.replace(red_r, tau0_s=red_r.tau0_s * q, dt_s=red_r.dt_s * q)
        demag = demag_correction(a, sp_r, tape, red_r, al, tm, fs) if a.demag else None
        tag += f"_from{a.reduction_ips:g}"
    x = load_audio(REPO_ROOT / "data" / "clips" / a.clip, fs)[: int(a.seconds * fs)]
    tp = al.trim_tp_s
    rb, ra = tm.rec_network(sp, al.rec_trim_tz_s, tp)
    pb, pa = tm.rep_network(sp, al.rep_trim_tz_s, tp)
    v = sp.speed_m_s
    delay = int(round(sp.head_distance_m / v * fs))
    res = {}
    for drive in a.drives:
        gain = al.hg_0vu / tm.MINUS_18_DBFS_PEAK * 10 ** (drive / 20)
        h = gain * tm._filter(rb, ra, x, fs)
        feed = np.concatenate([h, np.zeros(delay + 64)])
        ref_path = CACHE / (
            f"emf_ref_{a.clip}_{a.seconds:g}_{drive:+.0f}_{red.hg_bias:.0f}"
            f"{_ips_tag(a.speed_ips)}.npy"
        )
        t0 = time.perf_counter()
        if ref_path.exists():
            e_ref = np.load(ref_path)
        else:
            params = tm.stream_params(sp, tape, red.hg_bias, head_distance_m=delay * v / fs)
            e_ref = circuitsim.tape_stream_run(json.dumps(params), fs, feed)
            np.save(ref_path, e_ref)
        t_ref = time.perf_counter() - t0
        t0 = time.perf_counter()
        st = rd.ReducedStream(
            sp, tape, red, fs, ds_m=a.ds_um * 1e-6, demag=demag, head_distance_m=delay * v / fs
        )
        chunk = int(fs * 0.05)
        e_red = np.concatenate(
            [st.push_many(feed[c : c + chunk]) for c in range(0, len(feed), chunk)]
        )
        t_red = time.perf_counter() - t0
        y_ref = tm._filter(pb, pa, e_ref, fs)[delay - 1 : delay - 1 + len(x)]
        y_red = tm._filter(pb, pa, e_red, fs)[delay - 1 : delay - 1 + len(x)]
        np.save(CACHE / f"medium_ref_{drive:+.0f}{_ips_tag(a.speed_ips)}.npy", y_ref)
        np.save(CACHE / f"medium_red{tag}_{drive:+.0f}.npy", y_red)
        fc, b_ref = bands(y_ref, fs)
        _, b_red = bands(y_red, fs)
        d_bands = 10 * np.log10(b_red / b_ref)
        rms = np.sqrt(np.mean(y_ref**2))
        row = {
            "diff_db": float(20 * np.log10(np.sqrt(np.mean((y_red - y_ref) ** 2)) / rms)),
            "level_db": float(20 * np.log10(np.sqrt(np.mean(y_red**2)) / rms)),
            "bands_db": {f"{f:.0f}": round(float(d), 2) for f, d in zip(fc, d_bands, strict=True)},
            "ref_x_real_time": t_ref / (len(feed) / fs),
            "reduced_x_real_time": t_red / (len(feed) / fs),
        }
        res[f"{drive:+.0f}"] = row
        print(f"drive {drive:+.0f} dB", json.dumps(row), flush=True)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("study", choices=["electronics", "medium"])
    ap.add_argument("--drives", type=float, nargs="+", default=[0.0, 6.0, 12.0])
    ap.add_argument("--bias-ma-rms", type=float, default=2.94)
    ap.add_argument("--h-max", type=float, default=80e3)
    ap.add_argument("--points", type=int, default=321)
    ap.add_argument("--ds-um", type=float, default=2.0)
    ap.add_argument("--speed-ips", type=float, default=15.0)
    ap.add_argument("--reduction-ips", type=float, help="play the reduction made at this speed")
    ap.add_argument("--demag", action="store_true", help="the demagnetization correction D(k)")
    ap.add_argument("--demag-level-db", type=float, default=-12.0)
    ap.add_argument("--layouts", nargs="+", default=["one", "split"])
    ap.add_argument("--clip", default="drums_setmefree.wav")
    ap.add_argument("--seconds", type=float, default=4.0)
    ap.add_argument("--drive-db", type=float, default=6.0)
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    res = electronics(a) if a.study == "electronics" else medium(a)
    tag = ""
    if a.study == "medium":
        tag = ("_demag" if a.demag else "") + _ips_tag(a.speed_ips)
        tag += f"_from{a.reduction_ips:g}" if a.reduction_ips not in (None, a.speed_ips) else ""
    log = CACHE / f"{a.study}{tag}.json"
    log.write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
