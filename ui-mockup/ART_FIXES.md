# Art fixes for the image model

Each prompt below is self-contained. For text and label fixes, use **edit / inpaint mode** on
`assets/UI parts/Background.png`, masking only the area named. Image models tend to redraw
the whole panel when asked to change one label, so keep the mask tight and the rest locked.

Coordinates are pixels in the 1448×1086 background (origin top-left).

---

## 1. Threshold scale: duplicate "-20" (must fix)

The threshold scale reads -40, **-20**, -20, -10, 0. The upper-left label should be -30.

```
Edit this image. In the scale printed around the THRESHOLD knob, the label at the
upper-left (about 10 o'clock, near x=333 y=515) currently reads "-20". Change it to
"-30". Match the existing label font, size, ink colour and wear exactly. Change nothing
else in the image.
```

## 2. Output Gain scale: top label reads "10" (must fix)

It should read "0", matching the Make-Up Gain scale next to it (-20, -10, 0, +10, +20).

```
Edit this image. Above the OUTPUT GAIN knob, the label at 12 o'clock (near x=596 y=757)
reads "10". Change it to "0" so the scale reads -20, -10, 0, +10, +20, identical to the
MAKE-UP GAIN scale beside it. Match the existing font, size, colour and wear. Change
nothing else.
```

## 3. Ratio scale: garbled "29" label (must fix)

The ratio scale reads 1.5, **29**, 2, 4, 6, 10. "29" is not a valid ratio, and the scale is
also lopsided: it starts at about 8 o'clock and stops at 3 o'clock, while every other knob
sweeps evenly from about 8 to 4 o'clock.

```
Edit this image. Redraw only the scale printed around the RATIO knob (centre x=614 y=574).
Use 7 tick marks with labels 1.5, 2, 3, 4, 6, 10, 20, evenly spaced on a 236-degree arc
that runs from about 8 o'clock (lower left) clockwise to about 4 o'clock (lower right),
with "4" at 12 o'clock. Ticks point radially at the knob centre. Use the same tick
length, line weight, font and ink as the ATTACK scale beside it. Leave the knob hole,
the metal escutcheon and the "RATIO" caption untouched. Change nothing else.
```

## 4. Sidechain HPF scale: lopsided sweep (should fix)

The scale runs from 8 o'clock (20 Hz) to only 3 o'clock (400 Hz), so the knob's travel
doesn't match the other knobs.

```
Edit this image. Redraw only the scale around the SIDECHAIN HPF knob (centre x=189
y=838). Use 5 labelled ticks, 20, 60, 100, 200, 400, evenly spaced on a 236-degree arc
from about 8 o'clock clockwise to about 4 o'clock, with "100" at 12 o'clock. Add one
unlabelled minor tick between each pair. Match the line weight, font and ink of the
MAKE-UP GAIN scale. Leave the knob hole, escutcheon and caption untouched. Change
nothing else.
```

## 5. Release units (decide, then fix)

The Release scale runs 0.1 to 60 and is captioned "ms". A 60 ms maximum is very short for
a vari-mu compressor (the Fairchild's release runs from about 0.3 s to 25 s), and 0.1 ms
isn't a usable release. These numbers make sense as **seconds**. If you agree:

```
Edit this image. Under the RELEASE knob (near x=1029 y=650), the small unit caption
reads "ms". Change it to "sec". Match the font, size and ink of the "ms" caption under
the ATTACK knob. Change nothing else.
```

## 6. Stereo Link and Bypass: OFF/ON labels sit side by side, but the switches move up and down (should fix)

The "OFF   ON" captions are laid out left and right, but the toggle art throws up and
down. Power already uses the vertical convention ("ON" above). Note that the raised
Power lever currently covers its "ON" label. Lever up = on.

```
Edit this image. Under the STEREO LINK and BYPASS toggle holes (x=997 y=848 and
x=1138 y=848) there are side-by-side captions "OFF ON". Remove both captions. For each
switch, print "ON" centred above the hole about 48 px above its centre, and "OFF"
centred below the hole about 48 px below its centre. Next to the POWER switch
(x=1289 y=881), move the existing "ON" caption up so its baseline sits about 70 px
above the switch centre, just under the "POWER" caption, and add "OFF" centred about
55 px below the switch centre. Use the same font, size and ink as the existing
captions. Keep the "STEREO LINK", "BYPASS" and "POWER" titles where they are. Change
nothing else.
```

## 7. VU meter scale: ticks don't line up with the needle pivot (nice to have)

The printed scale is an arc whose centre sits far below the meter (around y=500), but the
needle pivots at the bottom of the face (x=328, y=372 for the left meter). The ticks
therefore aren't radial to the needle, so the needle crosses them at a slant. The tick
spacing also isn't a real VU law (the gap between -3 and 0 is too large, and +3 is
squeezed). The mockup corrects for this in code, but a matching scale looks better.

```
Edit this image. Redraw only the printed scale inside both VU meter faces (left face
centred near x=330 y=290, right face identical, shifted 790 px right). The needle
pivot is at the bottom centre of each face (left meter x=328 y=372). Draw the scale arc
as a circle centred exactly on that pivot with a radius of 95 px, sweeping from -62
degrees to +62 degrees (0 = straight up). Use standard VU tick positions
(proportional to voltage): -20, -10, -7, -5, -3, -2, -1, 0, +1, +2, +3, with labelled
major ticks at -20, -10, -7, -3, 0 and +3, and the red band from 0 to +3. All ticks
point radially at the pivot. Keep the "VU" legend, the cream face, the bezel and the
INPUT and GAIN REDUCTION captions unchanged. Same font, ink and line weight as now.
```

## 8. Knob: baked lighting spins with the knob (handled in code now)

`relight_knob.py` now rebuilds the knob's lighting so it stays fixed while the knob
turns. It works from the single `Knob.png`. Two things would still improve it:

- The art has 8 scallops at uneven spacing (27°, 63°, 108°, 152°, 207°, 251°, 295°,
  335°). A knob with evenly spaced flutes would look more manufactured.
- It's a slight 3/4 view (the cap appears about 25 px higher than the rim). The
  script corrects for this, but a straight top-down render is easier to relight.

```
Generate the same vintage black bakelite fluted knob with a cream pointer line,
1254x1254 transparent PNG, centred, pointer at 12 o'clock, viewed exactly straight
down (orthographic, no perspective tilt), with 8 identical flutes evenly spaced every
45 degrees, the first centred at 22.5 degrees clockwise from the pointer. Lit by a
soft key light at the top left. No drop shadow.
```

## 9. Toggle switch: the base changes between states (should fix)

`Switch Up.png` and `Switch Down.png` have different mounting rings (bright brass
versus darker steel, about 4% different in size, different nut shape), so the base
visibly changes when you flip it. Only the lever should change.

```
Generate three transparent PNG layers, 1254x1254 px, for a vintage nickel-plated
panel toggle switch viewed straight on from the front, all sharing the same centre
point (the centre of the bushing, at the exact image centre):

"switch-base.png": the round mounting washer, hex nut and threaded bushing only, no
lever. Washer diameter 680 px.
"switch-lever-up.png": only the bat-handle lever, angled upward and emerging from the
bushing centre, with its own contact shadow.
"switch-lever-down.png": the same lever angled downward.

Identical metal finish, wear and lighting (light from the top left) across all three
layers. No drop shadow under the washer.
```

## 10. Lit background: two mismatches (worked around in code)

`Lit Background.png` is used for the meter, tube and lamp lighting, but:

- **The pilot lamp is lit in the wrong socket.** The glowing jewel is in the large
  POWER switch socket (where the toggle sits), not the small lamp socket above
  "POWER". `build_assets.py` lifts the jewel and moves it into the small socket.
- **The grille slats changed.** The lit version has fewer, wider-spaced slats than the
  unlit one, so crossfading them would show doubled slats. The page keeps the unlit
  slats and shows the lit tubes only through their gaps.
- The whole lit image is also stretched about 0.6% vertically. The build script
  re-aligns it automatically.

If you regenerate it, edit the unlit image with a mask limited to the meter faces,
the grille *openings* and the small lamp socket, and say "keep the grille slats
exactly as they are".
