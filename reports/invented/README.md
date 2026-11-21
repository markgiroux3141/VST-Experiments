# Invented instruments: listening guide (2026-11-21)

Sketches from the second brainstorm (docs/INVENTED_DEVICES.md, "Second brainstorm"). Each is
one new physical mechanism, rendered offline in Python at 48 kHz by
`uv run python scripts/invented_sketches.py [--only NAME]` (~11 min for all).

Every take is two files at **-20 LUFS**: `<take>.wav` (dry) and `<take>_plate.wav` (with 30 %
of the EMT 140 plate). `<take>.png` is its spectrogram, and `summary.json` has the numbers.
Nothing passes through an amp or a speaker: each is the raw physical source.

Suggested order (Claude's guess from the spectra; nobody has listened yet):

| Folder | Take | What to listen for |
|---|---|---|
| `buzz_zither/` | `sharp_then_jawari_C3` | The same pluck twice: a sharp bridge, then the jawari. The buzz should bloom after the attack and sweep. |
| | `tanpura_cycle` | Four drone strings (Pa Sa Sa Sa), three cycles. |
| | `melody_over_tanpura` | A keyed melody (Bhairav-like) over the drone. |
| `rijke_organ/` | `blooming_chord` | Pipes sung by heated gauzes: each note blooms ~1 s after its key, then catches suddenly. |
| | `heater_hysteresis_A3` | The heater turned up, then down: a sudden start, a long hold well below that point, then a stop. |
| | `melody_over_drone` | Legato: the slow attack makes every note a swell. |
| `rosin_wheel/` | `melody_and_chord` | Bars bowed by a rosined wheel: a melody, then a four-bar chord. |
| | `press_sweep_A2` | One bar pressed from a feather to a crush: squeal (2nd mode), tone, then the raucous scrape. |
| `arc_organ/` | `melody_5A` | A singing carbon arc keyed by condensers: bright, buzzy, a hiss between notes. |
| | `currents_3_5_9A` | One phrase at 3, 5 and 9 A. At 9 A it is Ayrton's hissing arc. |
| | `speak_0.4_1.1_1.25ohm` | The tank's resistance near the arc's -1.31 ohm: short notes stay a pure, quiet sine; held ones grow bright. |
| | `two_arcs` | Two arcs, two voices. |
| `aeolian/` | `chord_wind_swell` | A held chord while the wind pedal climbs and falls: the strings walk up the harmonic series and back. |
| | `melody_over_drone` | Gusty wind at the nominal speed. |
| `siren_organ/` | `just_chord_sag_flute`, `_reed` | A 4:5:6:7 chord in just intonation, a key at a time: every note sags as the motor loads. |
| | `harmonic_melody_flute`, `_reed` | A tune on the harmonic-series keyboard (the 7th and 11th harmonics' flat notes). |
| | `speed_glide_reed` | The SPEED lever under a held fifth: the siren's glide. |
| `bubble_organ/` | `single_bubbles` | One bubble per key: a tune, then chords of bubbles. |
| | `held_streams_chord` | Held keys stream bubbles, each nozzle at its own rhythm. |
| | `breath_bend_A3` | More air makes bigger bubbles, so the note bends flat. |

Tell Claude which ones are worth keeping and what's wrong with them. The values that matter
most are named in each module of `varimu/invented/`.
