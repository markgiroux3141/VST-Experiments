# Valvechild UI mockup

Open `index.html` in Chrome; it needs no server.

| File | Purpose |
|---|---|
| `index.html` | The interactive mockup: knobs, switches, VU ballistics, lit/unlit lighting, stand-in signal. `?t=4` fast-forwards 4 s. |
| `build_assets.py` | Rebuilds `img/` from `../assets/UI parts` (parts, lit overlays, masks). |
| `relight_knob.py` | Renders the relit knob frames (`img/knob-strip.webp`). `--preview out.png` compares against naive rotation; `--png` adds a lossless strip. |
| `ART_FIXES.md` | Outstanding corrections for the current art, as image-model prompts. |

After changing source art:

```bash
python build_assets.py
python relight_knob.py      # only if Knob.png changed (~2 min)
```

How it all works, and how to do it for a new UI: `../docs/UI_PIPELINE.md`.
How to get the art from the image model: `../docs/IMAGE_GEN_GUIDE.md`.
