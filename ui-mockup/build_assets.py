"""Prepare web-ready UI assets from the source art in ../assets/UI parts.

- Moving parts (needle, switches) are cropped so their pivot sits exactly at the
  image centre, then downsampled with Lanczos.
- "Unlit Background.png" is the master panel. "Lit Background.png" is warped onto
  it (it came out of the image model slightly stretched), and the lit regions are
  baked into separate overlays that the page fades in independently:
    lit-meter-left/right.png   the backlit VU faces
    lit-tubes.png              the glowing tubes, seen only through the unlit grille slots
    lamp-on/off.png            the pilot lamp jewel, moved into the lamp socket
                               (the lit art put it in the power switch socket)
- The knob is handled separately by relight_knob.py.

Run:  python build_assets.py
"""
import base64
import io
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

HERE = Path(__file__).parent
SRC = HERE.parent / "assets" / "UI parts"
OUT = HERE / "img"

# Pivot points measured in the source images (px).
NEEDLE_PIVOT = (623.0, 1050.0)  # centre of the brass hub
NEEDLE_TIP_Y = 44
SWITCH_UP_CENTER = (623.0, 780.5)    # centre of the mounting nut / bushing
SWITCH_DOWN_CENTER = (626.5, 580.0)

# Regions in the unlit background (px, 1448x1086).
VU_LEFT_BOX = (140, 196, 530, 386)   # x0, y0, x1, y1 around the left meter face
VU_RIGHT_OFFSET = 790                # right meter is an exact copy shifted right
GRILLE_BOX = (581, 229, 877, 307)
LIT_LAMP_CENTER = (1290.4, 886.8)    # where the lit art drew the jewel (switch socket)
LIT_LAMP_RADIUS = 24                 # jewel radius there, inside the bezel ring
LAMP_SOCKET_RADIUS = 16.5            # radius of the real lamp socket's opening
LAMP_SPRITE_SCALE = 2                # sprites are drawn at 2x for sharpness


# ---------------------------------------------------------------- helpers

def crop_centered(img, center, half_w, half_h):
    """Crop a box centred on `center`, padding with transparency past the edges."""
    cx, cy = center
    box = (round(cx - half_w), round(cy - half_h), round(cx + half_w), round(cy + half_h))
    canvas = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), (0, 0, 0, 0))
    canvas.paste(img.crop(box), (0, 0))
    return canvas


def clean_alpha(img, floor=8):
    """Drop faint stray alpha left over from background removal."""
    a = np.array(img)
    a[..., 3] = np.where(a[..., 3] < floor, 0, a[..., 3])
    return Image.fromarray(a)


def save(img, name, size=None):
    if size:
        img = img.resize(size, Image.LANCZOS)
    img.save(OUT / name, optimize=True)
    print(f"  {name:22s} {img.width}x{img.height}")


def with_alpha(rgb, mask):
    """RGB image + float mask in 0..1 -> RGBA PIL image."""
    a = (np.clip(mask, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, a]), "RGBA")


def as_alpha(mask_img):
    """CSS mask-image reads alpha by default, so carry the mask in the alpha channel."""
    rgba = Image.new("RGBA", mask_img.size, (255, 255, 255, 0))
    rgba.putalpha(mask_img)
    return rgba


# ---------------------------------------------------------------- moving parts

def build_parts():
    needle = clean_alpha(Image.open(SRC / "Needle.png").convert("RGBA"))
    length = NEEDLE_PIVOT[1] - NEEDLE_TIP_Y + 4
    # Pivot ends up at the exact image centre, so CSS can rotate around 50% 50%.
    n = crop_centered(needle, NEEDLE_PIVOT, 112, length)
    save(n, "needle.png", (round(n.width * 0.5), round(n.height * 0.5)))

    half = 700
    for src, name, center in (("Switch Up.png", "switch-up.png", SWITCH_UP_CENTER),
                              ("Switch Down.png", "switch-down.png", SWITCH_DOWN_CENTER)):
        sw = clean_alpha(Image.open(SRC / src).convert("RGBA"))
        save(crop_centered(sw, center, half, half), name, (360, 360))


# ---------------------------------------------------------------- lit / unlit

def align(moving, fixed):
    """Warp `moving` onto `fixed`: robust affine from tile phase correlation,
    then a heavily smoothed optical-flow correction for the remaining wobble."""
    def highpass(a, sigma):
        a = a.astype(np.float32)
        return a - cv2.GaussianBlur(a, (0, 0), sigma)

    gf = cv2.cvtColor(fixed, cv2.COLOR_RGB2GRAY)
    gm = cv2.cvtColor(moving, cv2.COLOR_RGB2GRAY)
    hf, hm = highpass(gf, 5), highpass(gm, 5)
    h, w = gf.shape

    tile = 96
    win = cv2.createHanningWindow((tile, tile), cv2.CV_32F)
    pts = []
    for y in range(10, h - tile - 10, 40):
        for x in range(10, w - tile - 10, 40):
            (dx, dy), resp = cv2.phaseCorrelate(hf[y:y + tile, x:x + tile], hm[y:y + tile, x:x + tile], win)
            if resp > 0.25:
                pts.append((x + tile / 2, y + tile / 2, dx, dy))
    p = np.array(pts)
    design = np.c_[np.ones(len(p)), p[:, 0], p[:, 1]]
    keep = np.ones(len(p), bool)
    for _ in range(5):
        cx = np.linalg.lstsq(design[keep], p[keep, 2], rcond=None)[0]
        cy = np.linalg.lstsq(design[keep], p[keep, 3], rcond=None)[0]
        res = np.hypot(p[:, 2] - design @ cx, p[:, 3] - design @ cy)
        keep = res < max(0.6, 3 * np.median(res[keep]))
    print(f"  lit alignment: affine from {keep.sum()}/{len(p)} tiles, median residual {np.median(res[keep]):.2f} px")

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    mx = (xx + cx[0] + cx[1] * xx + cx[2] * yy).astype(np.float32)
    my = (yy + cy[0] + cy[1] * xx + cy[2] * yy).astype(np.float32)
    warped = cv2.remap(moving, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    def hp8(a):
        return cv2.normalize(highpass(a, 4), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM).calc(
        hp8(gf), hp8(cv2.cvtColor(warped, cv2.COLOR_RGB2GRAY)), None)
    flow = np.dstack([cv2.GaussianBlur(flow[..., i], (0, 0), 20) for i in range(2)]).astype(np.float32)
    return cv2.remap(warped, xx + flow[..., 0], yy + flow[..., 1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def face_mask(lit_gain, box):
    """The meter window: everywhere the lamp brightens the face (ticks and text
    included), with the outline smoothed so the bezel edge reads cleanly."""
    x0, y0, x1, y1 = box
    lit_area = lit_gain[y0:y1, x0:x1] > 8
    lab, _ = ndimage.label(lit_area)
    sizes = ndimage.sum(lit_area, lab, range(1, lab.max() + 1))
    face = ndimage.binary_fill_holes(lab == (np.argmax(sizes) + 1)).astype(np.float32)
    disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))
    face = cv2.morphologyEx(cv2.morphologyEx(face, cv2.MORPH_CLOSE, disk), cv2.MORPH_OPEN, disk)
    face = (cv2.GaussianBlur(face, (0, 0), 3) > 0.5).astype(np.float32)   # round off the wiggles
    return Image.fromarray((cv2.GaussianBlur(face, (0, 0), 0.8) * 255).astype(np.uint8))


def grille_slots(gray):
    """Mask (0..1) of the openings between the unlit grille's slats."""
    x0, y0, x1, y1 = GRILLE_BOX
    region = gray[y0:y1, x0:x1]
    dark_cols = region[25:55].mean(0) < 35   # slots are near-black through the middle
    slots, start = [], None
    for i, d in enumerate(np.append(dark_cols, False)):
        if d and start is None:
            start = i
        elif not d and start is not None:
            if i - start >= 6:
                slots.append((start, i))
            start = None
    boxes = np.zeros_like(region, dtype=bool)
    for a, b in slots:
        boxes[10:69, a:b] = True
    keep = boxes & (region < 22)  # follows the rounded slot ends
    print(f"  grille: {len(slots)} slots")
    return cv2.GaussianBlur(keep.astype(np.float32), (0, 0), 0.8)


def lamp_sprites(lit):
    """Lift the lit jewel out of the switch socket, scale it to the lamp socket,
    and derive a dark 'off' version from the same pixels."""
    r_src = LIT_LAMP_RADIUS + 3
    cx, cy = LIT_LAMP_CENTER
    patch = cv2.getRectSubPix(lit, (2 * r_src, 2 * r_src), (cx, cy)).astype(np.float32) / 255
    out = round(2 * LAMP_SOCKET_RADIUS * LAMP_SPRITE_SCALE * r_src / LIT_LAMP_RADIUS)
    patch = cv2.resize(patch, (out, out), interpolation=cv2.INTER_AREA)
    yy, xx = np.mgrid[0:out, 0:out]
    r = np.hypot(xx - (out - 1) / 2, yy - (out - 1) / 2) / (out / 2) * r_src / LIT_LAMP_RADIUS
    alpha = np.clip((1.0 - r) / 0.08, 0, 1)   # feathered disc at the jewel edge

    on = np.clip(patch, 0, 1)
    lum = on @ np.array([0.3, 0.55, 0.15], np.float32)
    # Unlit amber glass: keep the facet structure, drop the emission.
    off = np.dstack([0.42 * lum ** 1.4 + 0.10, 0.20 * lum ** 1.4 + 0.035, 0.08 * lum ** 1.4 + 0.012])
    for name, img in (("lamp-on.png", on), ("lamp-off.png", off)):
        save(with_alpha((np.clip(img, 0, 1) * 255).astype(np.uint8), alpha), name)


def build_backgrounds():
    unlit = np.array(Image.open(SRC / "Unlit Background.png").convert("RGB"))
    lit = align(np.array(Image.open(SRC / "Lit Background.png").convert("RGB")), unlit)
    Image.fromarray(unlit).save(OUT / "background.png", optimize=True)
    print("  background.png         (unlit master)")
    gray = cv2.cvtColor(unlit, cv2.COLOR_RGB2GRAY).astype(np.float32)
    lit_gain = cv2.GaussianBlur(cv2.cvtColor(lit, cv2.COLOR_RGB2GRAY).astype(np.float32) - gray, (0, 0), 2)

    masks = {}
    x0, y0, x1, y1 = VU_LEFT_BOX
    for side, dx in (("Left", 0), ("Right", VU_RIGHT_OFFSET)):
        box = (x0 + dx, y0, x1 + dx, y1)
        face = face_mask(lit_gain, box)
        masks[f"vu{side}"] = face
        m = np.array(face) / 255
        save(with_alpha(lit[box[1]:box[3], box[0]:box[2]], m), f"lit-meter-{side.lower()}.png")

    gx0, gy0, gx1, gy1 = GRILLE_BOX
    save(with_alpha(lit[gy0:gy1, gx0:gx1], grille_slots(gray)), "lit-tubes.png")
    lamp_sprites(lit)

    # Needle layers are clipped to the faces at runtime. Chrome refuses CSS mask images
    # loaded from file:// (they are fetched with CORS), so ship them as data URIs.
    uris = {}
    for name, m in masks.items():
        buf = io.BytesIO()
        as_alpha(m).save(buf, "PNG", optimize=True)
        uris[name] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    (OUT / "masks.js").write_text("// Generated by build_assets.py - do not edit.\n"
                                  "window.UI_MASKS = " + json.dumps(uris, indent=1) + ";\n")
    print("  masks.js               needle clip masks (inline data URIs)")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    build_parts()
    build_backgrounds()
