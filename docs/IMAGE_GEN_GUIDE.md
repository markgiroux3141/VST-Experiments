# Image generation guide (ChatGPT Images)

How to get plugin UI art out of an image model in a form the pipeline in
`UI_PIPELINE.md` can use. It's written from what went right and wrong on Valvechild.
The prompts are plain text that should work with any recent ChatGPT image model.
Where this mentions an editor feature (selecting a region to edit), check that your
version has it. If it doesn't, say in the prompt which area to change.

---

## The rules that matter most

1. **One master, everything else is an edit of it.** Generate the unlit background
   once, then make every variant (lit, label fixes) by *editing that image*. A fresh
   generation never lines up: text moves, wear changes, screws rotate.
2. **Edit the smallest possible region.** Select only the area that should change,
   and end every edit prompt with *"Change nothing outside the selected area."*
   Asked to fix one label, the model will otherwise redraw the whole panel.
3. **Separate parts are separate images.** Anything that moves (knobs, needles,
   switch levers, buttons) is generated on its own, on a transparent background,
   with nothing painted into the panel where it goes. The panel gets an empty hole.
4. **No baked shadows or perspective on moving parts.** A painted shadow or 3/4
   view rotates with the part. Ask for "viewed exactly straight on / straight down,
   orthographic, no drop shadow". Shadows are added in code.
5. **Give numbers.** Canvas size, centre point, angles, counts ("8 identical flutes
   every 45°"), label lists in order. Vague prompts get creative results.
6. **Check every result before using it.** See "Acceptance checks" below. The build
   script tolerates small misalignment, not structural changes.

---

## Order of work

1. **Concept composite.** The full UI with knobs in place (`UI.png`). Reference
   only; iterate on the look here.
2. **Unlit master background.** The panel with empty holes, power off.
3. **Fix labels and scales** on the master with masked edits (see `ui-mockup/ART_FIXES.md`).
   Do this *before* the lit version, so both share the fixes.
4. **Lit background** = masked edit of the finished master.
5. **Components:** knob, needle, switch base and levers, lamp, buttons.

---

## Prompts

Replace `{…}` placeholders. Keep the style sentence identical across every prompt
for one product, so parts match the panel.

**Style sentence (example):** *Weathered 1960s studio rack hardware: cream enamel
panel with rust and chipped paint, black bakelite knobs with cream pointer lines,
aged nickel toggles, warm studio lighting from the top left.*

### Concept composite

```
A front-panel UI for an audio plugin called "{NAME}", a {DESCRIPTION}, 1448x1086,
straight-on front view filling the frame. {STYLE SENTENCE}
Controls, left to right:
- Top row knobs: {NAME (scale labels in order)}, ...
- Bottom row knobs: ...
- Toggles: {NAME (ON above, OFF below)}, ...
- Meters: {e.g. two analogue VU meters labelled INPUT and GAIN REDUCTION, scale
  -20 -10 -7 -5 -3 -2 -1 0 +1 +2 +3, red band from 0 to +3}
Every number on every scale must be correct, legible and appear once. All rotary
scales sweep the same 270 degrees, from 7:30 to 4:30, with the centre value at 12.
```

### Unlit master background

Start from the concept composite as input, or a fresh generation if starting over.

```
Using this panel as the design, produce the bare panel with every control removed:
where each knob was, show an empty round mounting hole with its metal escutcheon
ring; where each toggle was, an empty threaded hole; where each lamp was, an empty
lamp socket. Keep every printed label, scale, tick and caption exactly where it is.
The unit is powered off: meter faces are dull grey-beige with no backlight, tube
windows are dark, lamps are unlit. Same canvas size, 1448x1086, straight-on view.
```

### Lit background (edit of the master)

Select **only**: the meter faces, the openings between grille slats (not the slats),
and the lamp socket(s).

```
The unit is powered on. Incandescent lamps behind the bottom edge of each meter
light the faces warm cream-amber, brightest at the bottom centre. Through the
openings in the tube grille, vacuum tubes glow orange with visible heater
filaments. The pilot lamp in the small socket above the word "POWER" glows amber.
Keep every printed mark, tick and number exactly where it is. Keep the grille
slats exactly as they are. Change nothing outside the selected area.
```

Problems we saw: the lamp lit up in the wrong socket, the grille slats were
redrawn with different spacing, and the whole image came back ~0.6% stretched. The
build fixes all three, but naming the exact socket and "keep the slats" in the
prompt avoids the first two.

### Knob

```
A single vintage black bakelite control knob, {DIAMETER, e.g. 1000} px across,
centred on a 1254x1254 transparent PNG. Viewed exactly straight down,
orthographic, no perspective tilt. Pointer: a cream inlaid line from the centre
to the rim at 12 o'clock. {N} identical flutes cut into the rim, evenly spaced
every {360/N} degrees. Worn edges and fine scratches. Lit by a soft key light at
the top left. No drop shadow, nothing else in the image.
```

If the relighting script will be used, top-down and evenly spaced flutes matter
most. Our knob was a slight 3/4 view with uneven flutes, which made the job harder.

Optional extra: a two-layer version, which makes relighting trivial:

```
Two transparent PNG layers of the same knob, same size and registration:
Layer A "knob-body": colour, texture, scratches, wear and the pointer, lit flat and
evenly from directly above, NO highlights, NO shading, NO shadow.
Layer B "knob-light": only the lighting for a key light at the top left (specular
highlights on the rim and top face, darker shading on the lower-right flutes),
transparent everywhere else.
```

### Meter needle

```
A single analogue meter needle on a transparent 1254x1254 PNG: a thin tapered
{material} pointer with a round brass hub at its base. Pointing straight up. The
hub centre is exactly at x=627, and the tip touches y=40. Viewed straight on, no
shadow.
```

### Toggle switch (base and levers as layers)

```
Three transparent 1254x1254 PNG layers of one vintage nickel-plated panel toggle
switch, viewed straight on from the front, sharing one centre point (the bushing
centre at the exact image centre):
"switch-base": round washer, hex nut and threaded bushing only, no lever,
washer 680 px across.
"switch-lever-up": only the bat-handle lever, angled up, emerging from the centre.
"switch-lever-down": the same lever angled down.
Identical metal finish and top-left lighting on all three. No drop shadow.
```

We got two separate whole-switch images instead, and their washers differed (brass
vs steel, 4% different in size). The base visibly changed when toggled.

### Pilot lamp

```
Two transparent 128x128 PNGs of a round faceted amber jewel lamp lens seen from
the front, 112 px across, centred. "lamp-off": dark amber glass, unlit, small
specular highlight at the top left. "lamp-on": the same lens lit bright orange from
behind, near-white hot centre. No outer glow (added in code).
```

### Label and scale fixes

Select only the label or scale:

```
In the selected area, the label currently reads "{WRONG}". Change it to "{RIGHT}".
Match the existing font, size, ink colour and wear exactly. Change nothing outside
the selected area.
```

For a whole scale, list every label in order, the tick count, the sweep ("from
7:30 clockwise to 4:30, centre value at 12") and "ticks point radially at the knob
centre".

---

## Acceptance checks

Run these before handing art to the build. Most take a minute with the snippets in
`UI_PIPELINE.md`.

| Asset | Check | Why |
|---|---|---|
| Any background | Every scale label is correct and appears once. | We had duplicate "-20", a "29" ratio and "10" where "0" belonged. |
| Any background | OFF/ON captions match the direction the control moves. | Ours were side by side for up/down toggles. |
| Lit vs unlit | Same size; after alignment, the difference shows only in lit regions. | Anything else will ghost during the fade. |
| Lit vs unlit | Structures (slats, bezels, screws) unchanged. | Our grille slats changed. |
| Lit vs unlit | Each light is in the right place. | Our lamp was in the switch socket. |
| Knob | Silhouette is a circle (fit residual of a few px); flutes evenly spaced; cap concentric with the rim. | Uneven or tilted knobs need more modelling to relight. |
| Knob, needle, switch | Alpha is clean (no halo, no stray specks); no drop shadow. | Halos and shadows rotate. |
| Switch states | Washer and nut pixel-identical between states. | Otherwise the base jumps when toggled. |
| Needle | Hub is round, needle points exactly up. | The pivot is measured from the hub. |
