"""A mix of the sample song through four chains, without and with noise and hum, after 1, 4 and 8
passes (2026-11-14; the user's ask: does noise and hum add something by ear that the dB figures of
scripts/chain_passes.py / chain_spike.py miss?).

    uv run --extra fast --extra listen python scripts/chain_mix.py [--calibrate-only] [--workers N]

Each stem gets a chain fit for it (CHAINS; config/chains.yaml's `use` notes), all with tube preamps
(B5 models tube and resistor noise; transistors and op-amp macros have none, so a transistor preamp
would be too quiet). Each stem's source is at a realistic SPL at the mic. Each pass is staged as
scripts/chain_passes.py stages them: the input at that SPL, turned down where H predicts a higher
peak than pass 1's.

**Two versions of every pass:**
- `clean`: no noise, no hum.
- `noisy`: B5's noise, a seed per stem and pass, plus hum. Hum here is the preamp input
  transformer's stray mains field (50 / 150 / 250 Hz) and, for the tube mics, their supply's ripple
  (100 / 200 / 300 Hz). Both are calibrated per chain, as scripts/chain_spike.py calibrated the
  U47 -> V76: the stray field so that the preamp's hum is HUM_EIN_DB re 0.775 V at its input (the
  level the V76 landed at, 1 dB inside its acceptance limit; provisional for the 610 and the
  REDD.47); the ripple so that it is RIPPLE_V at the mic's output (the U47's NG figure; provisional
  for the C12 and the U67). The simulated supplies' own ripple and mains wander come with the noise.

The mixes put the processed stems back at their dry loudness: each stem's gain is set by its clean
version and applied to both, so the noisy mix is the clean mix plus exactly the noise and hum at
their true level. They are panned (bass and vocal centre, guitar left, harmonies right) and every
mix of a pass count shares one gain. Writes reports/chain_mix/ (README.md): mix_{dry,clean,noisy}
_p{1,4,8}.wav, added_p{N}.wav (noisy minus clean at its true level) and added_p{N}_x30dB.wav
(+30 dB, to hear what it is).
"""

# ruff: noqa: E501  (sources and reasons kept on one line in the variant tables)
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chain_passes as cp  # noqa: E402
import chain_spike as cs  # noqa: E402

from varimu.circuit import builder  # noqa: E402
from varimu.circuit.ir import Control, Resistor, Vccs, VoltageProbe  # noqa: E402
from varimu.config import REPO_ROOT  # noqa: E402
from varimu.listen import matching  # noqa: E402
from varimu.sim import fast  # noqa: E402

VERSION = "mix-1"
OUT = REPO_ROOT / "reports" / "chain_mix"
CACHE = REPO_ROOT / "cache" / "chain_mix"
PASSES = 8
SHOWN = (1, 4, 8)
# stem: its chain, the SPL at the mic (provisional: model knowledge of close-miked levels), the
# chain's settings, the preamp's input transformer secondary (the stray field's winding), the
# mic -> preamp junction, and the tube mic's supply source (its ripple; None: no supply).
CHAINS = {
    "bass": {"chain": "r44_ua610", "spl_db": 100.0, "over": {"level_ua610": 0.4},
             "xfmr": "LT1_UA610_s", "junction": "ia_ua610", "supply": None,
             "why": "44-BX -> UA 610: 'upright bass' in its use note; a bass cab at ~100 dB SPL"},
    "guitar": {"chain": "c12_ua610", "spl_db": 85.0, "over": {"level_ua610": 0.4},
               "xfmr": "LT1_UA610_s", "junction": "ia_ua610", "supply": "VHV_c12",
               "why": "C12 -> UA 610: the C12's top on an acoustic guitar, ~85 dB SPL (at 90 the 610's first stage overloads on the C12: -34 dB residual, the C12 alone -60; its Lo gain link doesn't help; at 85 -44)"},
    "lead vocal": {"chain": "u47_v76", "spl_db": 95.0, "over": {"gain_db_v76": 24},
                   "xfmr": "LT85_V76_s", "junction": "ia_v76", "supply": "VNG_u47",
                   "why": "U47 -> V76: the German broadcast vocal; a singer at ~20 cm, ~95 dB SPL"},
    "harmonies": {"chain": "u67_redd47", "spl_db": 90.0, "over": {"gain_redd47": 34},
                  "xfmr": "LT1_REDD47_s", "junction": "ia_redd47", "supply": "VB_u67",
                  "why": "U67 -> REDD.47: mid-1960s Abbey Road vocals; backing singers a bit back, ~90 dB SPL; the REDD.47 at 34 dB (at 40 its output clipped: -26 dB residual, peaks -4.4 dBFS)"},
}  # fmt: skip
PAN = {"bass": 0.0, "guitar": -0.35, "lead vocal": 0.0, "harmonies": 0.35}  # -1 left .. +1 right
HUM_EIN_DB = -122.4  # chain_spike's calibrated V76 (spike-2): its stray field alone
RIPPLE_V = 3.0e-6  # chain_spike.RIPPLE_TARGET_V: the U47's NG, inside its "about 5 uV"
# provisional: model knowledge (a badly filtered tube-mic supply's ripple, peak). The C12's circuit
# rejects its supply's ripple so well that RIPPLE_V would need ~40 V: it gets this instead.
RIPPLE_MAX_V = 0.5
MIX_LUFS = -20.0  # -18 put the mixes' peaks at +1 dBFS


class MixChain:
    """A stem's chain, clean or noisy, for cp.passes / cp.measure_h (`name`, `over`, `noise`,
    `fs`, `run(p, seed)`). A noisy chain renders clean without a seed (H's measurement)."""

    def __init__(self, stem: str, noisy: bool, cal: dict | None):
        k = CHAINS[stem]
        self.stem, self.k, self.noisy, self.cal = stem, k, noisy, cal or {}
        self.base = cp.Chain(k["chain"], False, dict(k["over"]))
        self.name = k["chain"]
        self.over = dict(k["over"]) | (
            {"__mix": f"{VERSION}-noisy", "__cal": self.cal} if noisy else {}
        )
        self.noise = False
        self.fs = self.base.fs

    def circuit(self, p, seed, parts: set):
        """(IR, front, controls): `parts` of {"noise", "stray", "ripple"} on."""
        noise = seed if ("noise" in parts and seed is not None) else False
        ir = builder.build(self.base.c, self.base.over, noise=noise).ir
        front, sig = self.base.entries(p)
        n, fs = len(front), self.fs
        fade = cs.fade_in(n, fs)
        rng = np.random.default_rng([seed or 0, zlib.crc32(self.stem.encode()), zlib.crc32(b"hum")])
        els = {e.name: e for e in ir.elements()}
        repl, extra, controls = {}, [], []

        def series_emf(el_name: str, field: str, name: str, x: np.ndarray) -> None:
            e = repl.get(el_name, els[el_name])
            old = getattr(e, field)
            new = f"{old}__{name}"
            repl[el_name] = replace(e, **{field: new})
            controls.append(Control(name, name))
            sig[name] = x
            extra.extend([
                Resistor(f"RCTL_{name}", name, "0", 1e9),  # numerical: the IR's two-element rule
                Resistor(f"REMF_{name}", new, old, 1.0),
                Vccs(f"GEMF_{name}", old, new, name, "0", 1.0),
            ])  # fmt: skip

        if "stray" in parts:
            s = cs.tones(n, fs, cs.STRAY_HARMONICS, self.cal.get("stray_v", 1e-3), rng) * fade
            w = els[self.k["xfmr"]]
            series_emf(self.k["xfmr"], "b" if w.b != "0" else "a", "hum_xfmr", s)
        if "ripple" in parts and self.k["supply"]:
            r = cs.tones(n, fs, cs.RIPPLE_HARMONICS, self.cal.get("ripple_v", 1e-3), rng) * fade
            series_emf(self.k["supply"], "pos", "hum_supply", r)
        secs = [
            replace(s, elements=tuple(repl.get(e.name, e) for e in s.elements)) for s in ir.sections
        ]
        if extra:
            from varimu.circuit.ir import Section

            secs.append(Section("hum", tuple(extra)))
        ir = replace(ir, sections=tuple(secs), controls=tuple(ir.controls) + tuple(controls))
        return ir, front, sig

    def render(self, p, seed, parts: set, probes=("out",)) -> dict:
        ir, front, sig = self.circuit(p, seed, parts)
        ir = replace(ir, probes=tuple(VoltageProbe(x) for x in probes))
        r = fast.run_transient(ir, front, settings=self.base.s, controls=sig or None)
        return {k[2:-1]: np.asarray(v, float) for k, v in r.vectors.items()}

    def run(self, p: np.ndarray, seed: int | None = None) -> np.ndarray:
        parts = {"noise", "stray", "ripple"} if (self.noisy and seed is not None) else set()
        return self.render(p, seed, parts)["out"] / self.base.out_fs


def calibrate(stem: str) -> dict:
    """The stray field's and the ripple's amplitudes for `stem`'s chain (noiseless runs)."""
    f = CACHE / f"cal_{VERSION}_{stem.replace(' ', '_')}.json"
    if f.exists():
        return json.loads(f.read_text())
    mc = MixChain(stem, True, {"stray_v": 1e-3, "ripple_v": 1e-3})
    fs, j = mc.fs, mc.k["junction"]
    t = np.arange(int(0.6 * fs)) / fs
    tone = 0.05 * math.sqrt(2) * np.sin(2 * np.pi * 1000 * t)
    r = mc.render(tone, None, set(), probes=("out", j))
    g = cs.band_rms(r["out"], fs) / cs.band_rms(r[j], fs)  # the preamp's gain from its input
    sil = np.zeros(int(2.0 * fs))
    ein1 = cs.band_rms(mc.render(sil, 7, {"stray"})["out"], fs) / g
    cal = {"preamp_gain_db": round(20 * math.log10(g), 2),
           "stray_v": 1e-3 * 0.775 * 10 ** (HUM_EIN_DB / 20) / ein1}  # fmt: skip
    if stem == "lead vocal":
        # The V76's pad is ahead of T85 at 24 dB, so an EIN rule at this gain would shrink the field
        # (4.6 uV); a stray field doesn't follow the gain switch: chain_spike's, calibrated at the
        # spec's 52 dB (25.6 uV).
        cal["stray_v_ein_rule"] = cal["stray_v"]
        cal["stray_v"] = cs.calibrate()["stray_v"]
    if mc.k["supply"]:
        rip1 = cs.band_rms(mc.render(sil, 7, {"ripple"}, probes=(j,))[j], fs)
        cal["ripple_v"] = 1e-3 * RIPPLE_V / rip1
        if cal["ripple_v"] > RIPPLE_MAX_V:  # a supply this well filtered doesn't reach RIPPLE_V
            cal["ripple_v_rule"] = cal["ripple_v"]
            cal["ripple_v"] = RIPPLE_MAX_V
            cal["ripple_at_mic_out_v"] = RIPPLE_V * RIPPLE_MAX_V / cal["ripple_v_rule"]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(cal, indent=1))
    return cal


def pan(x: np.ndarray, p: float) -> np.ndarray:
    a = (p + 1) * math.pi / 4  # constant power
    return np.stack([x * math.cos(a), x * math.sin(a)], axis=1)


def lufs(x: np.ndarray, fs: int) -> float:
    return matching.integrated_lufs(x if x.ndim == 1 else x.mean(axis=1), fs)


def write(path: Path, x: np.ndarray, fs: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pk = float(np.max(np.abs(x)))
    if pk > 0.99:
        print(f"  ! {path.name} peaks {20 * math.log10(pk):+.1f} dBFS; scaled down")
        x = x * 0.99 / pk
    sf.write(path, x.astype(np.float32), fs, subtype="FLOAT")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--calibrate-only", action="store_true")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    args = ap.parse_args()
    fs = cp._settings(False).sample_rate
    t0 = time.perf_counter()
    with ThreadPoolExecutor(args.workers) as ex:
        cals = {s: ex.submit(calibrate, s) for s in CHAINS}
        cals = {s: f.result() for s, f in cals.items()}
        print(json.dumps(cals, indent=1), flush=True)
        if args.calibrate_only:
            return
        dry = {s: cp.load_stem(s, fs) for s in CHAINS}
        mcs = {(s, v): MixChain(s, v == "noisy", cals[s] if v == "noisy" else None)
               for s in CHAINS for v in ("clean", "noisy")}  # fmt: skip
        hs = {
            s: ex.submit(cp.measure_h, mcs[(s, "clean")], CHAINS[s]["spl_db"], "production")
            for s in CHAINS
        }
        hs = {s: f.result() for s, f in hs.items()}
        jobs = {(s, v): ex.submit(cp.passes, mc, s, dry[s], PASSES, CHAINS[s]["spl_db"], "production")
                for (s, v), mc in mcs.items()}  # fmt: skip
        ys = {k: f.result() for k, f in jobs.items()}
    print(f"renders done in {(time.perf_counter() - t0) / 60:.1f} min", flush=True)
    report(cals, hs, ys, dry, fs)


def report(cals, hs, ys, dry, fs) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict = {
        "chains": {s: CHAINS[s] | {"calibration": cals[s]} for s in CHAINS},
        "stems": {},
        "mixes": {},
    }
    e = int(cp.EDGE_S * fs)
    dry_mix = sum(pan(dry[s], PAN[s]) for s in CHAINS)
    g_dry = 10 ** ((MIX_LUFS - lufs(dry_mix, fs)) / 20)
    write(OUT / "mix_dry.wav", dry_mix * g_dry, fs)
    for k in SHOWN:
        mixes = {}
        for v in ("clean", "noisy"):
            parts = []
            for s in CHAINS:
                y = ys[(s, v)][k - 1]
                gain = 10 ** (
                    (lufs(dry[s], fs) - lufs(ys[(s, "clean")][k - 1], fs)) / 20
                )  # the clean's
                parts.append(pan(y * gain, PAN[s]))
                if v == "noisy":
                    f_ms, h_ms = hs[s]
                    yc = ys[(s, "clean")][k - 1]
                    n = min(len(y), len(yc))
                    d, c = cp.brick(y[:n] - yc[:n], fs)[e:-e], cp.brick(yc[:n], fs)[e:-e]
                    summary["stems"].setdefault(s, {})[f"p{k}"] = {
                        "noisy_minus_clean_db": round(
                            float(10 * np.log10(np.mean(d**2) / np.mean(c**2))), 2
                        ),
                        "clean": cp.residuals(
                            ys[(s, "clean")], dry[s], CHAINS[s]["spl_db"], f_ms, h_ms, k, fs
                        ),
                        "noisy": cp.residuals(
                            ys[(s, "noisy")], dry[s], CHAINS[s]["spl_db"], f_ms, h_ms, k, fs
                        ),
                        "peaks_dbfs": {
                            vv: cp.peak_dbfs(ys[(s, vv)][k - 1]) for vv in ("clean", "noisy")
                        },
                    }
            n = min(len(p) for p in parts)
            mixes[v] = sum(p[:n] for p in parts)
        g = 10 ** ((MIX_LUFS - lufs(mixes["clean"], fs)) / 20)  # one gain for the pair
        for v, m in mixes.items():
            write(OUT / f"mix_{v}_p{k}.wav", m * g, fs)
        d = (mixes["noisy"] - mixes["clean"]) * g
        write(OUT / f"added_p{k}.wav", d, fs)
        write(OUT / f"added_p{k}_x30dB.wav", d * 10**1.5, fs)
        dd, cc = d[e:-e].mean(axis=1), (mixes["clean"] * g)[e:-e].mean(axis=1)
        quiet = np.sqrt(np.mean(dd**2)) / np.percentile(
            np.sqrt(np.mean(cc[: len(cc) // 4800 * 4800].reshape(-1, 4800) ** 2, axis=1)), 5
        )
        summary["mixes"][f"p{k}"] = {
            "added_db_re_mix": round(float(10 * np.log10(np.mean(dd**2) / np.mean(cc**2))), 2),
            "added_db_re_quietest_5pct_50ms": round(float(20 * np.log10(quiet)), 2),
            "added_dbfs_rms": round(float(10 * np.log10(np.mean(dd**2))), 2),
        }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary["mixes"], indent=1))
    for s, v in summary["stems"].items():
        print(s, {p: (r["noisy_minus_clean_db"], r["clean"]["residual_vs_dry"], r["noisy"]["residual_vs_dry"])
                  for p, r in v.items()})  # fmt: skip


if __name__ == "__main__":
    main()
