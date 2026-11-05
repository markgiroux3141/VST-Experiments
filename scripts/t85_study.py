"""The V76's input loop (COMPONENT_EDITOR_PLAN.md C2 step 8): why T85's version 1 misses
the Braunbuch's flat response, and what a T85 would need.

T85's primary halves are in series with the 40 Hz network between them (S 1176: C5-C8,
4 x 2 uF, then C9 2 uF across R54, trimmed): a series loop of the 200 ohm generator, the
halves' copper, the primary's magnetizing inductance and the network, the windings'
voltage driving the secondary (into V1's grid: unloaded). An AC model of that loop,
checked against the circuit (the voltage across the windings re the generator's EMF, re
1 kHz, the nominal unit at 76 dB: within ~0.1-0.2 dB above 34 Hz), then swept against
sheet 6 point 5a (60 Hz-15 kHz +-0.5 dB re 1 kHz; 40 Hz -1.5..+0.5; 15 Hz >= 12 dB down),
with what the stages after T85 add (OUT_MINUS_SEC, measured on the nominal unit) added.

Findings (2026-11-04):
- the network pins the whole primary at ~3 H (lower: the bump grows; the V72's 26 H: a
  peak at 15 Hz), whatever R54;
- lossless with version 1's 77 ohm per half, no inductance and no R54 meets the spec (best
  0.86 dB above 60 Hz): the loop needs damping, ~150-250 ohm of copper per half (R54 then
  50-300 ohm) or a core loss angle of ~0.1-0.2;
- in the circuit (a gapped 280-turn design compiled by varimu-components, its compiled
  form inline in a copy of the V76), the low end then meets the spec at the drawn R54 of
  300 ohm (93 Hz +0.4 dB, was +0.98) and 40 Hz k3 at +22 dB out, 34 dB gain falls to
  0.45% (was 2.43%; more turns on a gapped core: 200 turns 0.92%, 270 0.44%, 400 0.19%);
- but at 1:30 the secondary's capacitance reflects 900x onto that copper and the leakage:
  BV 191's disc layout either droops 15 kHz (-7 dB) or peaks it (+3 dB), interleaved -12 dB.
  Version 1's top end is flat only on idealized leakage (0.05 mH) and capacitance (10 pF).
  Stopped there (the user's call): the low end's gain was judged too subtle for a whole
  provisional high-frequency construction.

    uv run python scripts/t85_study.py
"""

from __future__ import annotations

import numpy as np

F = np.array([15, 18, 22, 28, 34, 40, 50, 60, 76, 93, 120, 170, 255, 382, 572, 1000.0])
# The nominal unit at 76 dB (2026-11-04): the voltage across T85's windings re 1 kHz, and
# the output minus T85's secondary (what the stages after it add).
CIRCUIT_WINDINGS_DB = np.array(
    [-12.43, -9.71, -6.80, -3.63, -1.59, -0.35, 0.67, 1.06, 1.23, 1.20, 1.06, 0.77]
    + [0.45, 0.22, 0.08, 0]
)
OUT_MINUS_SEC_DB = np.array(
    [0.24, -0.72, -1.08, -1.05, -0.88, -0.73, -0.53, -0.40, -0.26, -0.19, -0.11, -0.05]
    + [-0.03, -0.02, 0.0, 0]
)
RS_OHM, C5_8_F, C9_F = 200.0, 8e-6, 2e-6  # bb sheet 5's generator; sch 5-8, 9


def windings_db(l_h, r54, r_half=77.0, rp=None, tand=0.0) -> np.ndarray:
    """The windings' voltage re the EMF, re 1 kHz (dB): the whole primary's inductance
    `l_h`, optionally lossy (a parallel `rp`, or a loss angle `tand`)."""
    w = 2 * np.pi * F
    zl = 1j * w * l_h / (1 + 1j * tand)
    if rp:
        zl = zl * rp / (zl + rp)
    z_net = 1 / (1j * w * C5_8_F) + 1 / (1 / max(r54, 1e-3) + 1j * w * C9_F)
    db = 20 * np.log10(abs(zl / (RS_OHM + 2 * r_half + zl + z_net)))
    return db - db[-1]


def spec(out: np.ndarray) -> tuple[float, float, float, bool]:
    flat = float(np.max(abs(out[F >= 60])))
    at40, at15 = float(out[F == 40][0]), float(out[F == 15][0])
    return flat, at40, at15, flat <= 0.5 and -1.5 <= at40 <= 0.5 and at15 <= -12


def main() -> None:
    m = windings_db(3.0, 450.0)
    print("the model (3 H, 77 ohm per half, R54 450) vs the circuit, re 1 kHz:")
    for f, a, b in zip(F, m, CIRCUIT_WINDINGS_DB, strict=True):
        print(f"  {f:6.0f} Hz {a:+7.2f} {b:+7.2f}")

    def best(label, rows):
        ok = sorted(r for r in rows if r[-1])
        print(f"\n{label}: {len(ok)} meet the spec" + ("" if ok else " (none)"))
        for flat, at40, at15, what, _ in ok[:6]:
            print(f"  worst 60 Hz+ {flat:.2f} dB, 40 Hz {at40:+.2f}, 15 Hz {at15:+.1f} | {what}")

    def row(what, o):
        return (*spec(o)[:3], what, spec(o)[3])

    lossless = [
        row(f"L {lh} H, R54 {r54}", windings_db(lh, r54) + OUT_MINUS_SEC_DB)
        for lh in (1, 2, 3, 4, 6, 8, 12, 16, 26, 40)
        for r54 in (0, 50, 100, 200, 300, 450, 700, 1000, 2000, 1e9)
    ]
    best("lossless, 77 ohm per half (version 1's copper)", lossless)
    copper = []
    for lh in (2.5, 3.0, 3.5):
        for rh in (77, 100, 120, 150, 200, 250, 300, 400):
            for r54 in (0, 50, 100, 200, 300, 450, 700, 1000):
                o = windings_db(lh, r54, r_half=rh) + OUT_MINUS_SEC_DB
                copper.append(row(f"L {lh} H, {rh} ohm per half, R54 {r54}", o))
    best("lossless, more copper per half", copper)
    loss = []
    for lh in (3, 5, 8, 12, 16, 25, 40):
        for tand in (0.05, 0.1, 0.2, 0.3, 0.5):
            for r54 in (0, 100, 200, 300, 450, 700, 1000):
                o = windings_db(lh, r54, tand=tand) + OUT_MINUS_SEC_DB
                loss.append(row(f"L {lh} H, tan d {tand}, R54 {r54}", o))
    best("77 ohm per half, a lossy core", loss)


if __name__ == "__main__":
    main()
