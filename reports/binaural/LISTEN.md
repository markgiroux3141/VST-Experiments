# Listening to the virtual head (docs/BINAURAL_PLAN.md)

**Headphones only** (on speakers the two ears leak into each other and the cues are gone).
Any decent closed or open headphones; the files are diffuse-field equalized. Volume moderate.
Files are 96 kHz stereo float32, -20 LUFS each, in `reports/binaural/listen/` (not in git;
`scripts/binaural_demo.py` and `scripts/binaural_room.py` make them again).

## Heads

| folder | what |
| --- | --- |
| `sphere/` | a rigid ball with point ears, no pinnae: the **control**. Left / right work; front and back are physically identical, so anything you hear "behind" here is your brain guessing. |
| `pp1/` | FABIAN, a dummy head (HUTUBS subject 1), **simulated** from its 3D scan on the GPU. |
| `pp1_measured/` | the same dummy head's **measured** HRTFs (TU Berlin): reality. A / B it against `pp1/`. |
| `pp<N>/` | real people's heads (HUTUBS subjects), simulated from their scans, when rendered. |
| `pp4/`, `pp69/` | the two heads with the **strongest** front / back cues of all 58 (by the simulation; pp4's measured cues are strong too). |
| `pp5/` | the head with the **weakest** front / back cues: if this one works as well for you as pp4, the cue strength isn't what decides it. |
| `<head>-pinna080/`, `-pinna130/` | the same head with its **ears shrunk to 0.8x or grown to 1.3x** (about the ear canal; the rest of the head unchanged), for pp1, pp4, pp5. Bigger ears move the ear's notches lower in pitch. |

## Files in each head's folder

- `tour_noise.wav` (also `_clap`, `_voice`, `_guitar`): the same sound at 10 places, 0.4 s
  apart: **front, front-right, right, back-right, back, back-left, left, front-left,** then
  **above-front** (60 deg up) and **below-front** (30 deg down).
- `circle.wav`: noise going round you twice, clockwise from the front, in 12 s.
- `frontback_noise.wav` (and the other sounds): **30 deg left of your nose, then 30 deg left
  of straight behind**, alternating four times. Both have the same timing and level
  difference between your ears; only the shape of the ear tells them apart. The pair to
  judge: does the second one sound behind you?

## Rooms (`rooms/`)

- `tour_<room>_pp1.wav`: noise bursts at 2 m going clockwise from the front (front,
  front-right, right, back-right, back, back-left, left, front-left), then front-left 30 /
  back-left 150 alternating four times, in the room. Rooms: `treated_studio` (a small
  treated room), `stone_chapel` (a big stone church).
- `band_<room>_pp1.wav`: "Did she mention my name" round you: **lead vocal in front**
  (1.5 m), **guitar back-left**, **harmonies straight behind**, **bass to the right** (2 m).

## A blind test

    uv run --extra binaural --extra listen --with sounddevice python scripts/binaural_listen.py

plays sounds at front-left / back-left / back-right / front-right through `sphere`, `pp1` and
`pp1_measured` in random order; press **F** or **B** (R repeats, Q stops). It prints how
often each head was right (50% = chance) and saves the answers. Add heads with
`--heads sphere pp1 pp7 pp23 ...`, another sound with `--stimulus voice`.

**The suggested round** (picks which head and which ear size sound "behind" to you):

    uv run --extra binaural --extra listen --with sounddevice python scripts/binaural_listen.py --heads sphere pp1 pp4 pp69 pp5 pp4-pinna080 pp4-pinna130 pp1-pinna130

The winner (well above the sphere's score) is the head to build on: more variants of it next.

## What to listen for

1. Left / right should be clear for every head, the sphere too.
2. Front vs back: the sphere should be a coin toss. If a real head's back sounds behind you
   more often than the sphere's, its ears are doing it.
3. Inside vs outside your head: the rooms should sit further out than the anechoic files.
4. Above / below: usually the weakest with someone else's ears.
5. `pp1` vs `pp1_measured`: do the simulated and the measured head place things alike?
