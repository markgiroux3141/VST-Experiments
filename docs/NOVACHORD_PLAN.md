# A divide-down tube polysynth for strings and pads: the Hammond Novachord

Drafted 2026-11-05 from a conversation with the user ("in keeping with our physics first
philosophy, how would we create a retro poly synth that was good at strings and other pad
like sounds?"). The user's decisions the same day:

1. **Divide-down** at least to start, because it costs less CPU than a voice per note.
2. **The Novachord as built** first, deviating where needed.
3. **A separate instrument**, not a section of tube_synth.
4. **Polyphony:** as much as we can get away with live; 8 voices is acceptable.
5. **The ensemble effect:** delegated to Claude. The decision is below, under
   "The ensemble".

Nothing is built. This plan is for picking up later. Milestones NV0-NV7, worked in order
with the usual "done when" discipline.

## Why divide-down, and why the Novachord

A pad needs many notes held at once. The project's per-voice tube designs can't do that
live: one tube_synth voice is ~62% load, and tube_synth_poly's four voices are rendered
offline (MIDI_TAKES_PLAN.md).

A divide-down instrument works differently:

- **Shared sources:** twelve top-octave oscillators run all the time, and divider chains
  make every lower octave.
- **Per-key gating:** each key only gates its own already-running pitch through its own
  envelope.

So the cost sits in shared parts. A key that isn't sounding costs nothing once its gate is
cut off. Every string machine since (Solina, ARP String Ensemble, Polymoog) is built this
way.

The **Hammond Novachord** (1938-42, 1,069 built) is the tube original:

- 72 keys, fully polyphonic.
- About 163 tubes and over 1,000 capacitors.
- Its slow attack setting is the one the restorers single out for strings.
- It is on Vera Lynn's "We'll Meet Again" (1939), the *Gone with the Wind* entr'acte,
  *Rebecca*, *High Noon* and *The Twilight Zone*.

TUBE_SYNTH_PLAN.md already lists it as history to learn from, and tube_synth's envelope
already borrows its keying. SYNTH_IDEAS #10 (dividers), #21 (formant banks) and #22
(paraphony on one supply) are this instrument's ideas in tube_synth form.

## What is known about it (2026-11-05, web sources; values are the gap)

**Signal path,** from the service manual's "Scheme of Operation" excerpt (Hammond, *The
Novachord: a manual for the service technician*, 2nd ed.; web:
https://oldtech.com/synth/HammondNovaC1.html):

- **Oscillators:** 12 oscillators, **6C8-G**, at the top octave (F to E).
  - Wikipedia: L-C tuned, with the inductors' cores mounted on flat springs.
  - Cirocco: each top-octave compartment holds a transformer with an adjustable core
    (fine tuning), a tube and a coarse-tuning capacitor.
- **Dividers:** 60 frequency dividers, **6W7-G**, cascaded so that each stage is an
  octave below the one before.
  - The manual calls them "non-linear amplifiers".
  - Wikipedia: vacuum-tube monostables, one tetrode per lower note.
  - The circuit itself is still to be found.
- **Control tubes:** 72, **6W7-G**, one per key. Each is a valve that passes its
  oscillator's or divider's signal only while the key is down.
- **Envelope:**
  - A seven-position ATTACK switch varies the operating voltage applied to all the key
    circuits.
  - Times are fixed and only levels change (Cirocco).
  - Setting 1 is percussive, 3 is like an ADSR, 4 is organ-like, 7 is for strings.
  - SUSTAIN pedals remove the control tubes' cut-off bias: one pedal for the lower 36
    keys, two duplicate pedals for the whole keyboard.
  - A modern recreation (Look Mum No Computer forum, after "the original Novachord
    circuit"; web: https://lookmumnocomputer.discourse.group/t/diy-hammond-novachord/5353)
    keys a 6J6 through two capacitors (C4, C5) between references at 0 and -100 V. At
    fast attack C4 jumps to about half of C5's voltage, then decays. At slow attack the
    two join and rise slowly. This is a guide, not the original's values.
- **Per-note filters:** 60 passive band-passes, one per divider compartment. A BRIGHT /
  MELLOW switch adds capacitors into the control tube circuits of every key except the
  lowest 18.
- **Tone controls** (in the control box, all keys, in parallel):
  - DEEP TONE (low-pass), FIRST / SECOND / THIRD RESONATOR (tuned circuits), BRILLIANT
    TONE (high-pass) and FULL TONE (flat).
  - Each has three loudness positions plus off; with all six off it is silent.
  - Cirocco counts 5 passive resonators and an 18-channel passive mixer.
- **Keyboard balance:** BALANCER shunts resistors across the lower half's outputs.
- **Vibrato:** six reeds, about 7 Hz each and each slightly different. Each works on a
  pair of adjacent oscillators, through three 12-pole switches.
  - NORMAL and SMALL can be combined.
  - A STARTER lever sets the reeds going; they are then kept going electrically.
  - Wikipedia's spring-mounted inductor cores suggest the reeds move the oscillators'
    cores. Unconfirmed: reading the circuit settles it.
- **Output stage:**
  - Preamp: 2 x 6J7. The expression pedal is a variable capacitor in this stage.
  - Power amp: 7 tubes, four **2A3** in parallel push-pull, into two 12-inch speakers.
  - Supply: 10 tubes.
- **Character** (Hollow Sun's sampled unit; web:
  https://hollowsun.com/hs2/products/novachord/index.htm): "grain and wheeziness",
  hum, low-end rumble, background noise, "subtle tuning differences and timbral and
  envelope variations" between notes. The polyphonic vibrato is heard as "a rich
  ensemble effect".

**Sources to find (NV0):**

- **The service manual** (print, 2nd edition; a GroupDIY request went unanswered:
  https://groupdiy.com/threads/looking-for-hammond-novachord-service-manual.40260).
- **The schematics.**
- **The patents:** the Smithsonian's record lists Laurens Hammond's US 2,126,464 and
  US 2,126,682 (1938; web: https://si.edu/object/novachord:nmah_606057). Hanert's
  US 2,254,284 and the Hammond / Hanert application Ser. No. 387,113 (1941) may cover the
  divider and keying.
- **Phil Cirocco's restoration** (web: https://discretesynthesizers.com/nova/intro.htm,
  `generator.htm`).
- **Tube data:** RCA's sheets for the 6C8-G, 6W7-G, 6J7 and 2A3.

Walled sources go to the user, each URL alone in a code block (memory: "user fetches
walled sources"). Until the circuit values are found, they are provisional with sources,
as Hard rules require.

## The ensemble (the user delegated the choice)

**Decision: the Novachord's own six-reed vibrato is the ensemble.**

Strings need slow, decorrelated pitch motion between notes; that is what a section of
players sounds like. The Novachord gets it from six reeds at slightly different rates on
different oscillator pairs. Notes a semitone apart move independently, and a chord shimmers.
That is the Solina's ensemble without a delay line. It is "as built" and cheap, because it
modulates only the 12 masters and the dividers follow.

**If it isn't lush enough (NV6),** the deviations in order:

1. **The Hammond scanner chorus** (same maker, late 1940s): a lumped LC delay line (9-25
   sections by model) read by a motor-driven 16-way capacitive scanner. Chorus mixes the
   scanned output with the dry signal.
   - Sources: web: https://www.b3world.com/hammond-technical-information-02.html,
     https://stefanv.com/electronics/hammond_vibrato_mod.html.
   - It runs as a medium beside the netlist, like the plate. As DK states its LC sections
     would cost with their square (the 5E3 speaker lesson).
2. **A saturable-reactor delay line** (invented): the same ladder with reactor inductors.
   DC on the control windings sets the delay: a tube-era BBD driven Solina-style by two
   lamp LFOs (~0.6 and ~6 Hz) in three phases.
3. **A multi-head tape loop** on the delay track's transport.

## The architecture: two tiers from one circuit

**Production (the reference)** is the literal instrument as one netlist, rendered offline:

- 12 masters with their reeds, 60 dividers, 72 control tubes and their envelopes.
- Band-passes, tone controls, preamp, 2A3 amp, speakers, and the 10-tube supply.

It is partitioned per octave column or per key group (circuitsim's N-part partitions), and
shares one supply. It is what the live tier is checked against. Its speed is unknown:
measure it in NV3.

**Live** follows the Rhodes precedent (RH3: 73 keys ringing at 80-84% load).

- **The masters, the reeds, the shared output stage and the supply** run in circuitsim.
- **The 72 keys run as a compiled medium:**
  - Each key's divider output, band-pass, control tube and envelope are generated from
    the reference circuit.
  - The control tube's gain law and its distortion are tabulated.
  - The linear filters become small per-key IIRs.
  - The envelope capacitors are the state.
- **Media cost:** a key sleeps when cut off, so the medium's cost goes with the keys
  sounding, on worker threads.
- **Coupling:** the medium senses the supply node a sample late (the tape's precedent for
  sensing across a cut), so a big chord's load still sags the rails.
- **The dividers:** each locks to the octave above. Two candidates for live:
  - event kernels triggered by the master's crossings (the thyratron K technique);
  - a locked waveform per divider, compiled from the reference with its shape following
    the supply.

  Measure both against the literal dividers.

**The organic coupling** (memory: "most organic first"): one supply for the bank, the
keyers and the amp. A held chord loads B+ and pulls the bank's pitch and level a little.
Measure it in NV3; nothing hides it.

## Milestones

### NV0: sources

- **Work:** find the manual, the schematics and the patents. Digitize RCA's sheets for
  the 6C8-G, 6W7-G, 6J7 and 2A3. Record what is printed and what stays provisional, in
  `data/schematics/hammond_novachord/README.md`.
- **Done when** that README lists every block's source or provisional status.

### NV1: one note, offline, literal

- **Work:**
  - New device files `6C8G@1` (twin triode) and `6W7G@1` (Koren pentode), each fitted to
    its sheet.
  - One master oscillator, one divider stage, a band-pass, a control tube and the envelope
    with the ATTACK switch.
- **Done when:**
  - it idles at the drawing's voltages;
  - the divider locks over the master's range and supply tolerance;
  - the attack settings match the manual's descriptions (1 percussive ... 7 strings);
  - its cost per step is measured.

### NV2: the bank

- **Work:**
  - Twelve masters and five divider octaves.
  - The reeds: a cantilever reed driven and sustained electromagnetically, moving an
    inductor core. Its L(x) could come from the component editor's FEM (C2).
  - The STARTER lever.
- **Done when:**
  - all 72 pitches lock;
  - the reeds' rates and depths are measured against the sources;
  - the pitch spread between notes is measured.

### NV3: the whole instrument, rendered

- **Work:**
  - The tone controls and resonators, the BALANCER, BRIGHT / MELLOW and the sustain
    pedals.
  - The preamp with the expression capacitor, the 2A3 amp and the two 12-inch speakers
    (the speaker kind, C3).
  - The supply.
  - `config/circuits/novachord.yaml`; `scripts/novachord_render.py --midi F`.
- **Done when:**
  - it idles at the drawing's voltages;
  - production speed is measured;
  - chord sag is measured (1 to 20 keys);
  - the user hears a string pad and a percussive setting.

### NV4: the live tier

- **Work:** the per-key medium compiled from NV3's circuit (a component, like
  `MK1_HARP@1`) and the divider candidates.
- **Done when:**
  - the live tier is within a stated bound of production on chords and envelopes;
  - its load is measured with `examples/play.rs` (all keys held, the pedal down, chords
    re-struck);
  - at least 8 keys sound live without dropouts, and the most that do is reported.

### NV5: in the app

- **Work:** the device `novachord` with its panel (ATTACK, the six tone tabs, VIBRATO,
  BALANCER, BRIGHT / MELLOW, VOLUME), the expression and sustain pedals on MIDI, and MIDI
  takes (MIDI_TAKES_PLAN.md: proxy or device, renders behind).
- **Done when** the user plays it.

### NV6: deviations, after listening

- **Work:** the ensemble options above; the plate or EMT 240 as a chain end; three
  speakers in a Room-view room for width.

### NV7: bending

Memory: "realistic first, then bend". Out-of-range values as panel controls:

- a reed's depth and rate spread;
- the supply's stiffness (more chord sag);
- heater drift on the masters (B6);
- the dividers' lock margin, so a stage slips an octave.

## Open (the user's, when picked up)

- If no schematic is found, a provisional instrument from the manual's description plus
  period practice (as the Victorian synth plans), or wait?
- The live tier's divider technique (NV4's measurement decides; options to the user).
- How far into NV6 to go: the scanner chorus is the first candidate.
