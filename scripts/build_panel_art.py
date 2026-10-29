"""Prepare the 670's front-panel art for the native app (docs/NATIVE_APP_PLAN.md, R4).

Reads the hardware art in ``assets/Compressor/`` and writes the textures the app
embeds to ``crates/varimu-app/assets/fairchild_670/``:

- ``panel.png``: the lit panel (``UI Lit.png``) cut to channel 1 and the centre
  section, with the left rack ear mirrored onto the right edge (we simulate one
  channel; channel 2 is lumped idle onto the supplies), the ears' holes transparent;
- ``knob_large.png`` / ``knob_small.png``: the knobs centred on their pivot;
- ``needle.png``: the VU needle turned to point straight up, its pivot at the centre;
- ``screw_balance.png`` / ``screw_zero.png``: the trims' screw heads cut out of the
  panel, so the app can turn them;
- ``layout.json``: where everything sits, in panel pixels, and the scales' angles
  (degrees clockwise from 12 o'clock) measured on the art.

Positions were measured on the art (dark round holes for the knobs, the screw heads'
outlines, the VU scale's tick bases); see docs/UI_PIPELINE.md for the method.

Run: uv run python scripts/build_panel_art.py
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "Compressor"
OUT = ROOT / "crates" / "varimu-app" / "assets" / "fairchild_670"

# ---- measured on UI Lit.png (2244 x 701) ----
TOP, BOTTOM = 121, 568  # the rack panel's rows
EAR = (7, 90)  # the left rack ear's columns (to the panel lip)
CUT = 1216  # just right of the centre section's divider line
HOLES = {  # knob holes: centre of mass of the dark round blobs
    "input_atten_db": (211.6, 348.0),
    "ac_threshold": (442.1, 347.8),
    "time_constant": (637.1, 347.4),
}
SCREWS = {"balance": ((796.8, 465.5), 21), "zero": ((936.8, 465.0), 21)}
# The screws' slots as drawn (degrees clockwise from 12 o'clock, mod 180).
SLOT_DEG = {"balance": 95.0, "zero": 30.0}
# The VU face's opening and the needle's pivot (below the face: the scale's arc
# centre, from its two ends and its top), the scale's radius.
VU_FACE = (748.0, 245.0, 982.0, 380.0)
VU_PIVOT = (866.7, 475.7)
VU_RADIUS = 178.0
# The scale's labelled ticks: (dB, angle), from the tick bases on the arc.
VU_TICKS = [
    (-20, -30.9),
    (-10, -21.9),
    (-7, -15.5),
    (-5, -8.8),
    (-3, -0.3),
    (-1, 7.2),
    (0, 11.5),
    (1, 17.1),
    (2, 23.7),
    (3, 30.5),
]
# The knobs' scales: printed end angles. Input and threshold sweep 0..30 over
# +-138 degrees; the time constant's six detents sit every 36 degrees from -90.
SWEEPS = {
    "input_atten_db": (-138.0, 138.0),
    "ac_threshold": (-138.0, 138.0),
    "time_constant": (-90.0, 90.0),
}
KNOB_DIAMETER = {"large": 128.0, "small": 92.0}  # on the panel, px
LAMP = (1117.0, 362.0)

# ---- measured on the parts (1254 x 1254, or the needle's 2172 x 724) ----
NEEDLE_HUB = (1109.0, 592.0)
NEEDLE_TIP = (566.0, 76.0)
TEXTURE = 256  # knob textures, px


def knob(name: str) -> Image.Image:
    im = Image.open(SRC / f"{name}.png").convert("RGBA")
    a = np.asarray(im)[..., 3]
    ys, xs = np.nonzero(a > 200)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    half = max(xs.max() - cx, cx - xs.min(), ys.max() - cy, cy - ys.min()) + 4
    box = (cx - half, cy - half, cx + half, cy + half)
    im = im.crop(tuple(round(v) for v in box))
    return clean(im.resize((TEXTURE, TEXTURE), Image.LANCZOS))


def clean(im: Image.Image) -> Image.Image:
    """Clear the stray low alpha background removal leaves."""
    px = np.asarray(im).copy()
    px[px[..., 3] < 8] = 0
    return Image.fromarray(px)


def needle() -> tuple[Image.Image, float]:
    """The needle pointing up, its hub at the image centre; and its length (px)."""
    im = Image.open(SRC / "VU meter needle.png").convert("RGBA")
    dx, dy = NEEDLE_TIP[0] - NEEDLE_HUB[0], NEEDLE_TIP[1] - NEEDLE_HUB[1]
    length = float(np.hypot(dx, dy))
    tilt = np.degrees(np.arctan2(dx, -dy))  # clockwise from up
    # Rotate about the hub (PIL turns counter-clockwise for positive angles).
    im = im.rotate(tilt, resample=Image.BICUBIC, center=NEEDLE_HUB, expand=False)
    half = round(length + 70)
    hx, hy = NEEDLE_HUB
    im = im.crop((round(hx - 70), round(hy - half), round(hx + 70), round(hy + half)))
    # 2x the size it is drawn at on the panel (needle reaches just past the scale).
    scale = 2 * (VU_RADIUS + 8) / length
    w, h = im.size
    return clean(im.resize((round(w * scale), round(h * scale)), Image.LANCZOS)), length


def panel(lit: Image.Image) -> Image.Image:
    rgb = lit.convert("RGBA")
    body = rgb.crop((EAR[0], TOP, CUT, BOTTOM))
    ear = rgb.crop((EAR[0], TOP, EAR[1], BOTTOM)).transpose(Image.FLIP_LEFT_RIGHT)
    out = Image.new("RGBA", (body.width + ear.width, body.height))
    out.paste(body, (0, 0))
    out.paste(ear, (body.width, 0))
    # The ears' holes (and any white the crop caught) show through.
    px = np.asarray(out).copy()
    white = px[..., :3].min(axis=2) > 225
    px[white, 3] = 0
    return Image.fromarray(px)


def screw(lit: Image.Image, centre: tuple[float, float], r: int) -> Image.Image:
    """The screw head as a round patch, 2x, its centre at the image centre."""
    cx, cy = centre
    s = 2 * r + 2
    im = lit.convert("RGBA").resize(
        (s * 4, s * 4), Image.BICUBIC, box=(cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2)
    )
    yy, xx = np.mgrid[0 : s * 4, 0 : s * 4]
    d = np.hypot(xx - s * 2 + 0.5, yy - s * 2 + 0.5) / 4
    alpha = np.clip((r + 0.5 - d) * 2, 0, 1)
    px = np.asarray(im).copy()
    px[..., 3] = (alpha * 255).astype(np.uint8)
    return Image.fromarray(px).resize((s * 2, s * 2), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lit = Image.open(SRC / "UI Lit.png")
    pan = panel(lit)
    pan.save(OUT / "panel.png", optimize=True)

    def at(p: tuple[float, float]) -> list[float]:
        return [round(p[0] - EAR[0], 1), round(p[1] - TOP, 1)]

    knob("Large Knob").save(OUT / "knob_large.png", optimize=True)
    knob("Small Knob").save(OUT / "knob_small.png", optimize=True)
    nd, length = needle()
    nd.save(OUT / "needle.png", optimize=True)
    for name, (c, r) in SCREWS.items():
        screw(lit, c, r).save(OUT / f"screw_{name}.png", optimize=True)

    layout = {
        "source": "assets/Compressor/UI Lit.png and its parts; scripts/build_panel_art.py",
        "size": list(pan.size),
        "knobs": {
            key: {
                "at": at(p),
                "sweep_deg": list(SWEEPS[key]),
                "texture": "small" if key == "time_constant" else "large",
                "diameter": KNOB_DIAMETER["small" if key == "time_constant" else "large"],
            }
            for key, p in HOLES.items()
        },
        "trims": {
            key: {"at": at(c), "radius": r, "slot_deg": SLOT_DEG[key], "sweep_deg": [-135.0, 135.0]}
            for key, (c, r) in SCREWS.items()
        },
        "vu": {
            "face": [VU_FACE[0] - EAR[0], VU_FACE[1] - TOP, VU_FACE[2] - EAR[0], VU_FACE[3] - TOP],
            "pivot": at(VU_PIVOT),
            "needle_length": VU_RADIUS + 8,
            "ticks": VU_TICKS,
        },
        "lamp": at(LAMP),
    }
    (OUT / "layout.json").write_text(json.dumps(layout, indent=1) + "\n", encoding="utf-8")
    for f in sorted(OUT.iterdir()):
        print(f.name, f.stat().st_size)


if __name__ == "__main__":
    main()
