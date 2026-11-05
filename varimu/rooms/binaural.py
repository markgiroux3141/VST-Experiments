"""Separation in a stereo mix (docs/ROOM_LOOP_PLAN.md R5): the room experiment's metrics.

A mix is built from the scene's solo prints (varimu.rooms.scene: each source alone
through every mic; the room is linear, and each mic's `intermod_db` says how far the
chains are from it): per source a stereo **stem**, the source's prints panned by the
session's balance law (varimu-app session::balance) and summed. "Loudness lies": each
stem is matched to -23 LUFS on its own, then the target set `tmr_db` under the masker.

Measures, the target against the masker:
- **glimpse_mono**: the separation study's glimpse proportion (varimu.separation.metrics:
  Cooke 2006, 20 ms x 48 ERB cells, 3 dB local SNR) on the mono sum, counting the cells
  the dry target fills (its notes);
- **glimpse_better_ear**: the same with each cell's better channel (the larger
  target-to-masker ratio of left and right): what a listener on headphones can use by
  attending to one ear per cell;
- **be_tmr_db**: per ERB band the better channel's long-term target-to-masker ratio;
- **bmld_db**: per band the binaural masking level difference of the equalization-
  cancellation model as Lavandier & Culling use it (JASA 127(1), 2010, "Prediction of
  binaural speech intelligibility against noise in rooms", after Culling, Hawley and
  Litovsky 2004): BMLD = 10 log10((k - cos(phi_t - phi_m)) / (k - rho_m)), floored at 0,
  k = (1 + s_e^2) exp(w^2 s_d^2) with the EC model's internal noise s_e = 0.25 and
  s_d = 105 us (vom Hovel 1984; provisional: model knowledge of those papers), rho_m the
  masker's interaural coherence and phi_m, phi_t the masker's and target's interaural
  phases in the band (long-term cross-spectra). The left and right channels stand for the
  ears (headphones: no crosstalk). A masker the room pair decorrelates between the
  channels can be cancelled; one panned identically into both can't;
- **effective_tmr_db**: be_tmr + bmld, averaged over the bands (uniform weights: music,
  not speech's band importance). Higher = the target better separated.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from varimu.rooms.scene import _safe, balance
from varimu.separation import metrics

SIGMA_E = 0.25
SIGMA_D_S = 105e-6
LUFS = -23.0


def _read(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    x, fs = sf.read(path, dtype="float64")
    return x, fs


def stems(
    folder: Path, spot_pan: float, room_db: float | None, room_gain: float = 1.0
) -> dict[str, np.ndarray]:
    """Per source its stereo stem (2, n) from a render folder's solos: the spots panned
    -spot_pan (A's) / +spot_pan (B's), the room pair hard left / right at `room_gain`
    (None: muted)."""
    info = json.loads((folder / "render.json").read_text(encoding="utf-8"))
    sources = list(info["mics"][0]["bleed"])
    out: dict[str, np.ndarray] = {}
    for src in sources:
        acc = None
        for m in info["mics"]:
            name = m["name"]
            if name.startswith("room"):
                if room_db is None:
                    continue
                pan, g = (-1.0 if name.endswith("L") else 1.0), room_gain
            else:
                pan, g = (-spot_pan if name.endswith("A") else spot_pan), 1.0
            y, _ = _read(folder / f"{_safe(name)}__{_safe(src)}.wav")
            gl, gr = balance(pan)
            s = g * np.stack([gl * y, gr * y])
            acc = s if acc is None else acc + s
        out[src] = acc
    return out


def room_gain_for(folder: Path, room_db: float, fs: int) -> float:
    """The room pair's gain that puts its loudness `room_db` re the spots' (both sources)."""
    info = json.loads((folder / "render.json").read_text(encoding="utf-8"))
    spots, rooms = [], []
    for m in info["mics"]:
        y, _ = _read(folder / m["file"])
        (rooms if m["name"].startswith("room") else spots).append(y)
    ls = metrics.loudness_lufs(np.sum(spots, axis=0), fs)
    lr = metrics.loudness_lufs(np.sum(rooms, axis=0), fs)
    return float(10 ** ((ls + room_db - lr) / 20))


def _lufs(x: np.ndarray, fs: int) -> float:
    import pyloudnorm

    return float(pyloudnorm.Meter(fs).integrated_loudness(x.T))


def _stft(x: np.ndarray, fs: int, n: int = 4096) -> tuple[np.ndarray, np.ndarray]:
    from scipy.signal import stft

    f, _, z = stft(x, fs, nperseg=n, noverlap=n // 2)
    return f, z


def band_measures(t: np.ndarray, m: np.ndarray, fs: int) -> dict[str, np.ndarray]:
    """Per ERB band (metrics.erb_edges_hz): the better channel's TMR and the BMLD."""
    edges = metrics.erb_edges_hz()
    f, tl = _stft(t[0], fs)
    _, tr = _stft(t[1], fs)
    _, ml = _stft(m[0], fs)
    _, mr = _stft(m[1], fs)
    be, bmld, fc = [], [], []
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        sel = (f >= lo) & (f < hi)
        if not np.any(sel):
            continue
        et = [np.sum(np.abs(z[sel]) ** 2) for z in (tl, tr)]
        em = [np.sum(np.abs(z[sel]) ** 2) for z in (ml, mr)]
        be.append(max(10 * np.log10((et[i] + 1e-30) / (em[i] + 1e-30)) for i in (0, 1)))
        cm = np.sum(ml[sel] * np.conj(mr[sel]))
        ct = np.sum(tl[sel] * np.conj(tr[sel]))
        rho = np.abs(cm) / np.sqrt(em[0] * em[1] + 1e-60)
        w = 2 * np.pi * np.sqrt(lo * hi)
        k = (1 + SIGMA_E**2) * np.exp(w**2 * SIGMA_D_S**2)
        d = 10 * np.log10((k - np.cos(np.angle(ct) - np.angle(cm))) / (k - min(rho, 1.0)))
        bmld.append(max(0.0, float(d)))
        fc.append(np.sqrt(lo * hi))
    return {"fc_hz": np.array(fc), "be_tmr_db": np.array(be), "bmld_db": np.array(bmld)}


def better_ear_glimpse(t, m, fs, notes, local_snr_db=3.0, range_db=50.0) -> float:
    present = metrics._present(metrics.cell_energies(notes, fs), range_db)
    ok = np.zeros_like(present)
    for ch in (0, 1):
        tc, mc = metrics.cell_energies(t[ch], fs), metrics.cell_energies(m[ch], fs)
        ok |= tc > mc * 10 ** (local_snr_db / 10)
    return float((present & ok).sum() / max(1, present.sum()))


def _fit(x: np.ndarray, n: int) -> np.ndarray:
    return np.pad(x, [(0, 0)] * (x.ndim - 1) + [(0, max(0, n - x.shape[-1]))])[..., :n]


def analyse(root: Path, conditions: list[str], mixes: dict, tmr_db: float) -> dict:
    """Every condition x mix (`mixes`: name -> (spot_pan, room_db or None)); writes the
    stems of two mixes per condition for listening; returns the summary."""
    import soundfile as sf

    from varimu.config import REPO_ROOT

    dry = REPO_ROOT / "cache" / "separation" / "conditions" / "dry"
    notes, fs0 = _read(dry / "target.wav")
    rows, table = {}, {}
    for cond in conditions:
        tgt, chg = root / cond / "target", root / cond / "changed"
        info = json.loads((tgt / "render.json").read_text(encoding="utf-8"))
        fs = info["fs"]
        assert fs == fs0
        mics = {
            m["name"]: {
                "chain": m["chain"],
                "set": m["set"],
                "intermod_db": m["intermod_db"],
                "own_minus_other_db": None,
            }
            for m in info["mics"]
        }
        for m in info["mics"]:
            if m["name"].startswith("spot"):
                own = m["name"][-1]
                other = "B" if own == "A" else "A"
                mics[m["name"]]["own_minus_other_db"] = round(
                    m["bleed"][own]["rms_dbfs"] - m["bleed"][other]["rms_dbfs"], 2
                )
        rows[cond] = {"mics": mics, "mixes": {}}
        table[cond] = {}
        for mix, (spot_pan, room_db) in mixes.items():
            rg = 1.0 if room_db is None else room_gain_for(tgt, room_db, fs)
            st = stems(tgt, spot_pan, room_db, rg)
            sc = stems(chg, spot_pan, room_db, rg)
            n = max(st["A"].shape[1], st["B"].shape[1])
            a, b, ac = _fit(st["A"], n), _fit(st["B"], n), _fit(sc["A"], n)
            ga = 10 ** ((LUFS + tmr_db - _lufs(a, fs)) / 20)
            gb = 10 ** ((LUFS - _lufs(b, fs)) / 20)
            a, ac, b = a * ga, ac * ga, b * gb
            nt = _fit(notes, n)
            bm = band_measures(a, b, fs)
            r = {
                "glimpse_mono": round(
                    metrics.glimpse_proportion(a.sum(0), b.sum(0), fs, notes=nt), 4
                ),
                "glimpse_better_ear": round(better_ear_glimpse(a, b, fs, nt), 4),
                "be_tmr_db": round(float(np.mean(bm["be_tmr_db"])), 2),
                "bmld_db": round(float(np.mean(bm["bmld_db"])), 2),
                "bmld_below_1500_db": round(float(np.mean(bm["bmld_db"][bm["fc_hz"] < 1500])), 2),
                "effective_tmr_db": round(float(np.mean(bm["be_tmr_db"] + bm["bmld_db"])), 2),
                "room_gain": round(rg, 4),
            }  # fmt: skip
            rows[cond]["mixes"][mix] = r
            table[cond][mix] = [r["effective_tmr_db"], r["glimpse_better_ear"]]
            if mix in ("centre_room_-6", "panned_room_-6"):
                d = root / cond / "mixes" / mix
                d.mkdir(parents=True, exist_ok=True)
                # each stem at -23 LUFS (the staircase sets the target's level)
                g0 = 10 ** (-tmr_db / 20)
                for fname, x in (("target", a * g0), ("changed", ac * g0), ("masker", b)):
                    sf.write(d / f"{fname}.wav", x.T.astype("<f4"), fs, subtype="FLOAT")
    # deltas against the same chain on both spots (U47 -> V76)
    ref = rows[conditions[0]]["mixes"]
    for cond in conditions:
        for mix, r in rows[cond]["mixes"].items():
            r["delta_effective_db"] = round(r["effective_tmr_db"] - ref[mix]["effective_tmr_db"], 2)
            r["delta_glimpse_be"] = round(
                r["glimpse_better_ear"] - ref[mix]["glimpse_better_ear"], 4
            )
    return {
        "tmr_db": tmr_db,
        "reference": conditions[0],
        "table_columns": ["effective_tmr_db", "glimpse_better_ear"],
        "table": table,
        "conditions": rows,
    }
