"""Where the aligned Ampex 351's noise comes from (docs/TAPE_PLAN.md, "Gaps" 4: S/N 58.3 dB
against the spec's 60 after the 51 um record gap). The profile's noise measurement
(varimu.measure.tape_suite: tape recorded silent, bias and erase on, the line out 50 Hz-15 kHz)
with the circuit's noise sources kept in some sections only. Each source's stream is keyed by
its element's name, so removing others leaves its samples unchanged; the parts add in power
(independent streams). The tape's grain is removed by an effectively infinite particle count
(particle volume x 1e-9: the grain is Gaussian, its variance 1 / particles per cell) and no
packing noise; `floor` has no noise at all (hum, the bias's residue). Nothing in varimu/
changes.

    uv run --extra fast python scripts/tape_snr_study.py
-> reports/tape/snr_study.{json,png}
"""

from __future__ import annotations

import dataclasses
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy import signal as sps

from varimu.circuit import builder, spec
from varimu.circuit import ir as irm
from varimu.config import REPO_ROOT
from varimu.measure import tape_align as ta
from varimu.measure import tape_suite as ts
from varimu.sim import fast
from varimu.sim.io import TransientSettings

OUT = REPO_ROOT / "reports" / "tape"
SOURCES = (irm.NoiseCurrent, irm.TubeNoise)
GROUPS = {
    "all": None,
    "grain": (),
    "record amplifier": ("record amplifier",),
    "bias and head driver": ("bias and head driver",),
    "reproduce side": ("reproduce amplifier", "output"),
    "supply, mic stage, mains": ("power supply", "microphone stage (idle)"),
    "floor": (),
}
THIRD_OCTAVES = 1000.0 * 2.0 ** (np.arange(-13, 12) / 3.0)


def variant(ir: irm.CircuitIR, name: str) -> irm.CircuitIR:
    keep = GROUPS[name]
    grain = name in ("all", "grain")
    secs = []
    for s in ir.sections:
        els = []
        for e in s.elements:
            if isinstance(e, SOURCES) and keep is not None and s.title not in keep:
                continue
            if isinstance(e, irm.Tape) and not grain:
                m = dataclasses.replace(
                    e.medium,
                    particle_volume_m3=e.medium.particle_volume_m3 * 1e-9,
                    packing_sigma=0.0,
                )
                e = dataclasses.replace(e, medium=m)
            els.append(e)
        secs.append(dataclasses.replace(s, elements=tuple(els)))
    noise = ir.noise
    if keep is not None and "power supply" not in keep:
        noise = dataclasses.replace(noise, mains_rms=0.0)
    return dataclasses.replace(ir, sections=tuple(secs), noise=noise)


def with_cells(ir: irm.CircuitIR, ds_m: float) -> irm.CircuitIR:
    secs = []
    for s in ir.sections:
        els = tuple(
            dataclasses.replace(e, medium=dataclasses.replace(e.medium, ds_m=ds_m))
            if isinstance(e, irm.Tape)
            else e
            for e in s.elements
        )
        secs.append(dataclasses.replace(s, elements=els))
    return dataclasses.replace(ir, sections=tuple(secs))


def cells() -> int:
    """`--cells`: the floor's line against the cells. The oscillator's frequency (192 kHz,
    oversample 1: production's probes hide it), the noiseless machine's line (frequency,
    level) and band noise with the cells as built (7.62 per wavelength of the nominal
    f_bias_hz), at 7.62 per wavelength of the measured frequency, and at half the length."""
    al = ta.aligned()
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st.sample_rate
    c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
    _, v_out = c.full_scale
    ir0 = builder.build(c, al.overrides, cores="ja", noise=False).ir
    tape = next(e for e in ir0.elements() if isinstance(e, irm.Tape))
    ds0, v = tape.medium.ds_m, tape.medium.speed_m_s
    hi = dataclasses.replace(st, sample_rate=192_000, oversample=1)
    r = fast.run_transient(ir0, np.zeros(int(0.05 * 192_000)), settings=hi).vectors["v(rbc)"]
    r = r[len(r) // 2 :] - np.mean(r[len(r) // 2 :])
    up = np.nonzero((r[:-1] < 0) & (r[1:] >= 0))[0]
    frac = up + r[up] / (r[up] - r[up + 1])
    f_osc = 192_000 * (len(frac) - 1) / (frac[-1] - frac[0])
    print(f"oscillator {f_osc:.1f} Hz (cells: {v / ds0 / 1e3:.1f} kHz)", flush=True)
    rows = {
        "as built": ds0,
        "7.62 per measured wavelength": v / (f_osc * 7.62),
        "half length": ds0 / 2,
    }
    if "--substeps" in sys.argv:
        # The record side's step instead: the line doesn't move with the cells.
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import speed_351

        subs = [int(a) for a in sys.argv[sys.argv.index("--substeps") + 1 :] if a.isdigit()]
        rows = {f"{m} substeps": m for m in subs}
    x = np.zeros(int((ts.MEASURE_FROM_S + ts.NOISE_S) * fs))

    def one(item):
        name, ds = item
        t1 = time.time()
        ir = speed_351.with_substeps(ir0, ds) if "substeps" in name else with_cells(ir0, ds)
        y = fast.run_transient(ir, x, settings=st).vectors["v(out)"]
        y = y[int(ts.MEASURE_FROM_S * fs) :] / v_out
        y = y - np.mean(y)
        f, p = sps.periodogram(y * np.hanning(len(y)), fs)
        band = (f > 1000) & (f < 15000)
        i = int(np.argmax(np.where(band, p, 0)))
        line = 10 * math.log10(p[max(i - 3, 0) : i + 4].sum() * (f[1] - f[0]) / 0.375 + 1e-30)
        noise = 20 * math.log10(ts.band_rms(y, fs, ts.NOISE_BAND_HZ) + 1e-30)
        out = {"setting": ds, "line_hz": float(f[i]), "line_dbfs": line,
               "noise_dbfs_rms": noise, "seconds": time.time() - t1}  # fmt: skip
        print(f"{name}: {json.dumps(out)}", flush=True)
        return name, out

    with ThreadPoolExecutor(3) as ex:
        res = dict(ex.map(one, rows.items()))
    res = {"f_osc_hz": f_osc, "rows": res}
    name = "snr_substeps.json" if "--substeps" in sys.argv else "snr_cells.json"
    (OUT / name).write_text(json.dumps(res, indent=1))
    return 0


def main() -> int:
    if "--cells" in sys.argv:
        return cells()
    al = ta.aligned()
    st = TransientSettings.from_sim_settings(engine="circuitsim")
    fs = st.sample_rate
    c = spec.load_circuit(spec.circuit_path(ta.CIRCUIT))
    _, v_out = c.full_scale
    ir0 = builder.build(c, al.overrides, cores="ja").ir
    x = np.zeros(int((ts.MEASURE_FROM_S + ts.NOISE_S) * fs))
    t0 = time.time()

    def one(name: str) -> tuple[str, np.ndarray]:
        r = fast.run_transient(variant(ir0, name), x, settings=st)
        y = r.vectors["v(out)"][int(ts.MEASURE_FROM_S * fs) :] / v_out
        print(f"  {name} ({time.time() - t0:.0f} s)", flush=True)
        return name, y

    with ThreadPoolExecutor(ts.MAX_JOBS) as ex:
        ys = dict(ex.map(one, GROUPS))
    prof = json.loads((REPO_ROOT / "reports/units/ampex351_heads51/report.json").read_text())
    three = prof["distortion"]["at"]["3pct"]["out_dbfs_rms"]
    res = {"three_pct_out_dbfs_rms": three, "band_hz": list(ts.NOISE_BAND_HZ), "rows": {}}
    for name, y in ys.items():
        y = y - np.mean(y)
        band = 20 * math.log10(ts.band_rms(y, fs, ts.NOISE_BAND_HZ) + 1e-30)
        f, p = sps.welch(y, fs, nperseg=fs // 10)
        thirds = []
        for fc in THIRD_OCTAVES:
            b = (f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6))
            thirds.append(10 * math.log10(p[b].sum() * (f[1] - f[0]) + 1e-30))
        res["rows"][name] = {"noise_dbfs_rms": band, "sn_db": three - band, "thirds_dbfs": thirds}
        print(f"{name:26s} {band:7.2f} dBFS rms  (S/N {three - band:5.1f} dB)", flush=True)
    res["thirds_hz"] = THIRD_OCTAVES.tolist()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "snr_study.json").write_text(json.dumps(res, indent=1))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4.8))
    for name, r in res["rows"].items():
        lw = 2.5 if name == "all" else 1.2
        label = f"{name}: {r['noise_dbfs_rms']:.1f}"
        ax.semilogx(THIRD_OCTAVES, r["thirds_dbfs"], ".-", ms=3, lw=lw, label=label)
    title = "The aligned 351's noise by source (silent tape, bias on; 50 Hz-15 kHz rms)"
    ax.set(xlabel="third-octave band (Hz)", ylabel="dBFS", title=title)
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "snr_study.png", dpi=110)
    return 0


if __name__ == "__main__":
    sys.exit(main())
