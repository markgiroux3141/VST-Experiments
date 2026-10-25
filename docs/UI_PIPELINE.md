# UI pipeline: from generated art to a live, lit, turning UI

How the Valvechild mockup was built, written so the next UI can be done the same
way. The scripts live in `ui-mockup/`; this document explains what they do, why,
and what to change for new art.

```
 image model                    measure                     prepare                    use
 ───────────                    ───────                     ───────                    ───
 unlit background  ─┐       hole centres, tick angles,   background.png            index.html
 lit background    ─┼─────▶ VU scale, part pivots, ────▶ lit-* overlays, masks ──▶ (later: JUCE)
 knob / needle /   ─┘       lit-vs-unlit alignment       needle, switches,
 switch parts                                            knob-strip (relit frames)
```

See `IMAGE_GEN_GUIDE.md` for how to get the art in the first place.

---

## 1. The art you need

| File | What it is | Hard requirements |
|---|---|---|
| `Unlit Background.png` | The whole panel, power off. **The master**: every coordinate is measured on it. | Empty holes where knobs, switches and lamps go. Meter faces unlit (dull). |
| `Lit Background.png` | The same panel, power on. | Made by **editing** the unlit image, not generated fresh. Only lit regions may differ. |
| `Knob.png` | One knob, transparent background. | Centred, pointer at 12 o'clock, top-down, no drop shadow. |
| `Needle.png` | One meter needle with its hub. | Pointing straight up, transparent. |
| `Switch Up.png` / `Switch Down.png` | Toggle in each state. | Same base, same scale, transparent. Better: base and lever as separate layers. |
| `UI.png` | A full composite for reference only. | Not used by the build; it never lines up exactly. |

Shadows are added in CSS (and later in code), never baked into parts: a baked shadow
rotates with the part.

---

## 2. Measuring the art

Everything is measured in background pixels (1448×1086 for Valvechild). The page
draws the background at that size and scales the whole stage to fit the window, so
these numbers go straight into the page.

**Holes (knobs, switches, lamp sockets).** Threshold the unlit background for very
dark pixels, label connected blobs, keep roughly circular ones (width ≈ height,
fill > 60%), and take each blob's centre of mass. That gave every control position
to a fraction of a pixel.

**Knob scale angles.** Printed scales are not evenly spaced in generated art, so
each knob gets its own `anchors`: pairs of `[angle, value]`, where the angle is
measured clockwise from 12 o'clock. To find the ticks, sample the background along
short radial segments around the hole at every degree, and look for angles that are
much darker than the median. Ticks show up as sharp dips. Map each dip to its
printed label by eye. Values between anchors are interpolated (log scale for
ratio, time and frequency), so the pointer always lands on the printed labels.

**VU scale.** A real VU needle's deflection is proportional to **voltage**, not dB.
Measure the base of each labelled tick on the scale arc. The angle from the needle
pivot to each tick gives a voltage→angle table. Extrapolate the first segment
down to 0 V for the left rest peg. Put the pivot at the bottom centre of the face,
where the needle hub sits.

**Part pivots.** For each part image:
- knob: centre of the solid (alpha > 200) bounding box;
- needle: centre of the hub, i.e. the widest row near the bottom;
- switch: centre of the mounting disc, i.e. the widest row of the solid area.

Then crop each part so the pivot is the **exact image centre**. CSS and JUCE can
then rotate around 50%/50% with no offsets to track.

**When the background is replaced.** If the new background has the same layout,
don't re-measure by hand. Detect the holes in both images, fit an affine transform
between the matching centres (18 points gave < 0.6 px residual), and push every
old coordinate through it.

---

## 3. Preparing assets (`build_assets.py`)

`python build_assets.py` regenerates everything in `ui-mockup/img/` except the knob.

- **Parts** are cropped around their pivot and downsized with Lanczos. Browsers
  alias badly when a 1254 px image is shrunk 10× and rotated live, so never point
  the page at the raw source files. Stray low alpha (< 8) from background removal
  is cleared.
- **Lit/unlit** are handled as in section 4.
- **Masks** for clipping the needles to the meter faces are written as
  inline data URIs in `masks.js` (see the gotchas in section 7).

---

## 4. Lit / unlit lighting

### 4.1 Align the lit image to the unlit one

Image models never return a perfectly registered edit. Ours came back about 0.6%
taller, with sub-pixel wobble on top. `align()` does this:

1. **Tile phase correlation.** High-pass both images (subtract a Gaussian blur),
   then measure the shift of each 96 px tile (stepping every 40 px) with
   `cv2.phaseCorrelate`. Keep tiles with a confident response.
2. **Robust affine fit.** Least squares on the tile shifts, iteratively dropping
   tiles more than 3× the median residual. Lit regions are naturally rejected
   here, because their content really did change.
3. **Smooth flow.** Warp by the affine, run DIS optical flow, blur the flow
   heavily (σ = 20 px) and warp again. That takes out the remaining local wobble
   without chasing the real lighting changes.

Check: a 50/50 blend of the aligned lit image and the unlit image should show no
doubled ticks or text.

### 4.2 Find what lit up

Subtract the unlit luminance from the aligned lit luminance and blur slightly.
Inside the meter boxes, "brightened by > 8 levels", hole-filled and smoothed,
gives a clean mask of each meter face. This beats thresholding the unlit face by
brightness, because face edges are darker than the middle.

### 4.3 Bake one overlay per light source

Each light gets its own PNG with alpha, cropped to its region, so the page can fade
each one on its own schedule:

| Overlay | Content | Fade |
|---|---|---|
| `lit-meter-left/right.png` | lit face pixels × face mask | meter lamps: fast (~0.12 s), slight flicker |
| `lit-tubes.png` | lit grille interior × the **unlit** slot mask | tube heaters: ~2.5 s smoothstep warm-up |
| `lamp-on.png` / `lamp-off.png` | pilot jewel lit / darkened | pilot: near-instant |

Moving parts (needles) sit **above** the lit face, so the overlay can't hide them.
Brighten them a little with a CSS filter as the lamp comes up.

### 4.4 When the lit art disagrees with the unlit art

The lit image will change things it shouldn't. Fix each problem at the overlay
level, not by crossfading the whole panel:

- **Changed structure** (our grille had fewer slats in the lit version): keep the
  unlit structure and show lit pixels only through the unlit openings. Build the
  mask from the unlit image (dark columns → slots → dark pixels inside each slot
  box).
- **Light in the wrong place** (our lamp glowed in the switch socket): cut the lit
  element out, scale it to the right socket, and place it there. Derive the "off"
  version from the same pixels (luminance^1.4 tinted dark amber), so the two match
  exactly.

---

## 5. Relighting rotating parts (`relight_knob.py`)

**Problem.** A knob image has its lighting painted in. Rotating it rotates the
highlights, which reads as the light orbiting the knob.

**Fix in one line.** Split the knob image into *lighting fixed to the screen* plus
*surface detail that turns with the knob*. For each angle, rotate only the detail,
recompute the lighting, and render a frame.

### 5.1 How it works

1. **Height map.** A hand-fitted model of the knob's shape: a radial profile (dome,
   rounded cap edge, groove, skirt lip, skirt, outer round-over) minus concave
   scoops at the measured scallop angles. Normals come from its gradient.
2. **Perspective.** Generated "top-down" art is usually a slight 3/4 view: tall
   parts appear shifted up (our cap: ~25 px). Model this as `screen_y = y − k·h`
   (`PARALLAX`). Undo it before any rotation (`to_ortho`) and redo it after
   (`to_screen`): it belongs to the camera, not the knob.
3. **Lighting, inner area.** Everything inside the scalloped rim is rotationally
   symmetric, so the light at any screen position never changes. Read it straight
   from the image:
   - unwrap to polar (rows = radius, columns = angle);
   - patch over the pointer and the cream wear spots by interpolating around each
     ring, so they don't get frozen on screen;
   - median-filter **along the radius only**: reflections on a turned surface run
     radially, scratches mostly don't. Use a narrow window where the profile curves
     fast (`RADIAL_WINDOWS`);
   - blur the domed cap heavily (`CAP_SMOOTH`): its lighting is a soft gradient,
     and any grain left in it would be doubled by the turning grain in the detail.
4. **Lighting, scalloped rim.** Here the surface direction varies with angle, so
   learn a **matcap** from the rim's clean plastic: the median colour for each
   surface-normal direction (128×128 bins, holes filled by neighbour averaging).
   When the rim turns, rotate its normals and look the colour up again.
5. **Detail** = original − lighting. Scratches, wear and the pointer live here and
   turn with the knob. At 0° the output reproduces the original image exactly, so
   any error only shows up as the knob turns.
6. **Frames.** Render every 2.5° (144 frames) at 768 px, downsample to 256 px and
   pack a 12×12 grid as `knob-strip.webp` (3.8 MB; `--png` adds a lossless PNG for
   JUCE). The page shows the nearest frame and CSS-rotates by the remainder
   (≤ 1.25°), so motion stays continuous.

### 5.2 Adapting it to a new knob

Measure and set these constants at the top of the script:

| Constant | How to measure |
|---|---|
| `CENTER` | Fit a circle to the alpha silhouette: least squares of `r(θ) = r₀ + dx·sinθ − dy·cosθ`. |
| `PARALLAX` | Fit the same circle to the cap edge, which has a strong brightness edge. The difference in centres ÷ the cap height gives `k`. |
| `radial_profile` radii | Read a luminance profile along the knob's **left and right** sides, where the vertical perspective shift doesn't distort radii. Highlights mark lip tops; dark dips mark grooves. |
| `SCALLOPS` | Unwrap to polar and read the arch centres; or find minima of the silhouette radius. Generated flutes are usually uneven, so use the measured angles. |
| `POINTER_HALF_WIDTH` | From the pointer inlay's width. Widen the mask past its dark outline, or a ghost of it gets frozen into the lighting. |

### 5.3 Checking the result

- `python relight_knob.py --preview out.png` shows naive rotation (top row) against
  relit (bottom row) at −120…+120°. In the relit row, highlights must stay at the
  same screen positions.
- A useful debug sheet shows: the matcap, the normal map, the detail layer (should
  look like scratches and wear only, not shading), and a lighting-only render at 0°
  and 120° (should be identical except the rim).
- **Symptoms and causes we hit:**
  - *Relit looks just like the naive rotation* → the matcap is too weak and the
    highlights went into the detail layer. This happened when one matcap covered
    the whole knob. The fix was the inner/rim split.
  - *Ghost of the pointer that doesn't move* → the pointer mask is too narrow.
  - *Extra grain on the cap at some angles* → cap lighting not smoothed enough.

---

## 6. The page (`ui-mockup/index.html`)

- **Stage** = the background at its native size, CSS-scaled to fit. All positions
  in the `KNOBS`, `SWITCHES` and `METERS` tables are background pixels.
- **Knobs:** drag vertically (horizontal drag also turns), Shift for fine, wheel,
  double-click to reset, arrow/Page/Home/End keys. The hit area is the knob body
  only. A value tooltip floats outside the scaled stage so it stays readable.
  Stepped knobs (Time Constant) snap.
- **VU ballistics:** second-order spring/damper in the voltage domain
  (ω = 2π·2.1 Hz, ζ = 0.8): roughly 300 ms rise and ~1.5% overshoot, with hard pegs.
  With no power, both needles fall to the left peg. Once warm, the GR meter sits at 0.
- **Stand-in audio:** a synthetic program envelope (kick/snare/hat bed, sections)
  feeds a simple soft-knee compressor that uses Threshold, Ratio, Attack, Release,
  Time Constant, Sidechain HPF and Bypass, so the GR needle responds to the knobs.
  The dev bar switches test signals.
- **`?t=4`** fast-forwards the simulation 4 s on load. Use it for screenshots.

---

## 7. Gotchas

- **`file://` and CORS.** Chrome won't apply CSS `mask-image` loaded from local
  files, and `fetch()` of local JSON fails. Ship masks as data URIs in a `.js` file,
  and metadata as a `.js` file too (`masks.js`, `knob-strip.js`).
- **CSS masks read alpha**, not luminance. A greyscale PNG mask passes everything;
  put the mask in the alpha channel.
- **SVG filters on thin lines** vanish with the default filter region: a vertical
  line has a zero-width bounding box. Use `filterUnits="userSpaceOnUse"`.
- **`clip-path` clips `filter: drop-shadow`.** For a round hit area, size the
  element to the knob body (`border-radius` limits hit-testing) and let the image
  overflow it.
- **Premultiply alpha** before resizing or warping RGBA. Otherwise dark fringes
  appear at edges.
- **Headless screenshots** render only a few frames. Use `?t=` rather than
  waiting on animations.

---

## 8. Verifying

```bash
chrome --headless=new --disable-gpu --hide-scrollbars --window-size=1488,1180 \
  --virtual-time-budget=1500 --enable-logging=stderr --v=0 \
  --screenshot=shot.png "file:///.../ui-mockup/index.html?t=6"
```

Grep the stderr for `CONSOLE` to catch script errors. Check by eye:
- pointers sit on their printed labels;
- the lit/unlit blend shows no doubled detail;
- knob highlights are in the same place on every knob;
- needles rest on the pegs with the power off.

---

## 9. Toward the plugin (JUCE)

The framework is not decided yet (2026-10-24): it's chosen in the plan's Phase 10.
The current lean is nih-plug (Rust) with a webview editor that reuses this page, and
JUCE is the alternative ([FUTURE_DIRECTIONS.md](FUTURE_DIRECTIONS.md), section 7).
What follows holds for either.

What carries over unchanged:
- `knob-strip` (`--png`): a standard filmstrip knob. Frame = `round(angle / 2.5) mod 144`.
- `lit-*` overlays: draw over the background with opacity, using the same timings.
- Needle and switch sprites, centred on their pivots.
- The geometry tables (`KNOBS` anchors, VU voltage→angle table) and the ballistics
  constants.

What changes: the stand-in signal model is replaced by real meter values from the
audio thread. Smooth them on the UI side with the same ballistics, since a real VU
needle is the ballistic, not the audio.
