# The book: *Sound from Physics* (working title)

A book-length PDF that explains the project to someone new to all of it. It starts from
what sound is and works up to the two machines it ends on: the tube synth
([TUBE_SYNTH_PLAN.md](../TUBE_SYNTH_PLAN.md)) and the Ampex 351 tape machine
([TAPE_PLAN.md](../TAPE_PLAN.md)).

Status (2026-11-02): **sketch.** The chapters exist as headings with yellow *Sketch* boxes
holding each one's plan. Only the preface's opening is written prose (a sample of the voice).

## Structure

| File | Part | Chapters |
|---|---|---|
| `chapters/00-front.typ` | Front matter | Contents, Preface (who it's for, how to read it) |
| `chapters/01-sound.typ` | I Sound and Signals | 1 What Sound Is, 2 Sound in a Computer |
| `chapters/02-parts.typ` | II The Old Parts | 3 Passive parts, 4 Supplies, 5 The Vacuum Tube, 6 Iron and Hysteresis |
| `chapters/03-simulation.typ` | III Simulating a Circuit | 7 Equations, 8 Time steps, 9 Fast enough to play, 10 Keeping honest |
| `chapters/04-synth.typ` | IV The Tube Synth | 11 The Idea, 12 Filter, 13 Oscillator, 14 Voice, 15 Colour and movement, 16 Playing it |
| `chapters/05-tape.typ` | V The Tape Machine | 17 How tape records, 18 Particles, 19 The medium, 20 Grain and motion, 21 The Ampex 351 |
| `chapters/06-back.typ` | Back matter | Where next, maths refresher, glossary, reproducing results, sources |

`style.typ` is the look (7 x 10 in pages, Libertinus Serif, chapter and part openers) and the
callouts: `sketch` (the plan, hidden in a reader's copy), `deeper` (optional maths),
`listen` (an audio example), `incode` (where it lives in the repo), `todo-figure` (a figure
still to make) and `report-figure` (a plot straight from `reports/`).

## Building

Needs [Typst](https://typst.app) 0.13 or later, a single executable:
`winget install --id Typst.Typst` (or `cargo install --locked typst-cli`).

```sh
cd docs/book
typst compile --root ../.. book.typ build/varimu-book.pdf                      # draft, with the plan boxes
typst compile --root ../.. --input sketch=false book.typ build/varimu-book.pdf # a reader's copy
typst watch --root ../.. book.typ build/varimu-book.pdf                        # rebuilds on save
```

`--root ../..` lets figures come from the repo's `reports/` (paths start with `/`). The PDF
goes to `build/`, which is git-ignored.

## Open decisions (the user's)

- **Title and voice.** The working title and the preface's tone.
- **The audio companion.** Where the `listen` examples live (a web page with a link or QR
  code per example?). The drum prints in `reports/tape/audio/` come from Cambridge-MT
  multitracks (educational use only), so public examples need other material: the synth's
  own playing, or recordings the user owns.
- **Public or private.** If it goes public: no scanned manuals or datasheets reproduced
  (cite them), and brand names only to say what a model is of.
- **Depth.** Whether the "Going deeper" maths stays optional boxes or becomes a parallel
  track (an appendix per part).
