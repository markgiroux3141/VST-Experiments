# The Hohner Clavinet from physics

Drafted 2026-11-06 from a conversation with the user ("is a clavinet on our list of
instruments to make, and does it fit our methods?", then "let's put this into a plan doc").
Before this it was only a line in INSTRUMENT_PLAN.md's "Others worth noting (not planned)"
and in RHODES_PLAN.md's "The target" ("could follow cheaply once this exists").

**The user's decision (2026-11-06):** long-standing prerequisites, such as the BJT model,
are done **first, as part of this plan**, when the plan is picked up. They are not a reason
to postpone it. So CL0 below builds them unless another track has built them already.

Nothing is built. Milestones CL0-CL5, worked in order with the usual "done when"
discipline.

## Why it fits the project's methods

The Clavinet is a struck string read by magnetic pickups, through passive switches into a
small transistor amp. That is the Rhodes' structure, and the Rhodes is built (RH1-RH3,
RHODES_PLAN.md):

| Rhodes (built) | Clavinet (this plan) |
|---|---|
| Tine and tonebar as beam modes (`varimu/rhodes/beam.py`) | A stiff string as modes, in two polarizations |
| A brief hammer contact inside the step (`key.py`) | A tangent that strikes and **stays**: a held contact (new) |
| A damper's transfers on key up | Key up **changes the string**: the whole string speaks, a pitch drop, then the yarn kills it (new) |
| A 2D magnetostatic pickup map (`pickup.py`) | The same, on two bar pickups, one magnet under many strings |
| The harp medium in circuitsim (`harp.rs`, `media::NoteEvent`, voices on workers) | The same machinery, a string medium |
| The harp network into the 5E3 | Pickup selector and four tone switches (passive), then the D6's BJT amp |

The new physics is the held tangent and the release. Both are contacts folded into the
medium's port, which INSTRUMENT_PLAN.md already asks for.

**Fewer notes ring at once than on the Rhodes.** A Clavinet has no sustain pedal. Its yarn
mutes a string within milliseconds of release (Gabrielli et al. 2013, 2.3), so the voices
alive are the keys held plus short release tails.

## What is known (2026-11-06, web sources)

The two papers below measured a D6. They are the anchor until the service documents are in
hand.

- **[G13]** L. Gabrielli, V. Välimäki, H. Penttinen, S. Squartini, S. Bilbao, "A digital
  waveguide-based approach for Clavinet modeling and synthesis", EURASIP J. Adv. Signal
  Process. 2013:103 (open access; web:
  https://www.ness.music.ed.ac.uk/wp-content/uploads/2013/06/Gabrielli.pdf).
- **[R12]** L. Remaggi, L. Gabrielli, R. C. D. de Paiva, V. Välimäki, S. Squartini, "A
  pickup model for the Clavinet", DAFx-12, York (web:
  https://dafx.de/paper-archive/2012/papers/dafx12_submission_62.pdf).

**The instrument** [G13, 2]:
- 60 keys, one string per key, F1 to E6.
- The first 23 strings are wound, the rest plain. The timbre steps between keys 23 and 24,
  near 150 Hz (its Fig. 6).
- The keyboard end of each string is on a tuning pin and wound with yarn. The far end is on
  a tailpiece.

**The tangent and the anvil** [G13, 2]:
- A class-2 lever per key pushes a rubber tip, the tangent, into the string. The tip traps
  the string against a metal stud, the anvil, for as long as the key is held.
- That splits the string into a speaking part (anvil to tailpiece) and a non-speaking part
  (the yarn side, heavily damped).
- Key velocity in [G13]'s excitation model varies linearly over 1-4 m/s (3.2).
- **On release** the two parts join: the whole string speaks briefly, **three semitones
  lower on every key** (2.3.1), and the yarn then damps it.
- The tangent hitting the anvil makes a **knock**, mostly below 1.2 kHz. The pickups hear it
  through the string (3.5).

**The tone** [G13, 2.3]:
- T60 of low and mid notes can be 20 s or more. High notes are shorter.
- The lowest 2-4 partials last much longer than the higher ones. T60 across partials
  ripples with a period of 2-3 times f0.
- The second partial is always >3 dB above the first, and often the third is above the
  second.
- Pitch drifts at most 1-2 cents during a note.
- **Beating:** some notes up to E4 show partials beating at 0.5-2 Hz, as deep as 15 dB peak
  to peak. It isn't always there, it depends a little on velocity, and both mic and pickup
  hear it. [G13] suspects termination yielding; it is not understood.
- **Inharmonicity B** [G13, Table 1]:

  | Key | F1 | A#1 | D3 | D#3 | F#5 | E6 |
  |---|---|---|---|---|---|---|
  | B | 5e-4 | 2e-4 | 9e-5 | 1e-4 | 9e-5 | 8e-5 |

**The pickups** [R12, G13 2.1, 2.3.5]:
- Two pickups, electrically identical, near the tailpiece end, single-coil, potted in epoxy.
  Instead of one coil per string, each pickup is a row of **metal-bar coils**, one magnet per
  group of strings.
  - [R12]: six bars of ten strings each, 0.5 cm wide, ~3.7 cm long (centre pickup) and
    3.3 cm (bridge pickup).
  - [G13]: "10 metal bar coils intended to transduce six strings each".
  - **The two papers disagree.** Settle it from the service documents or photos (CL0).
- **Positions** [R12]: the centre pickup sits 18.5 cm (lowest string) to 6.5 cm (highest)
  from the string termination. The bridge pickup sits a constant 4 cm from it, tilted ~30
  deg.
  - [R12] puts the centre pickup above the strings and the bridge pickup below. [G13] says
    the opposite. Settle it in CL0.
  - Example given: a 67.8 cm string at 161 Hz.
- **Flux** [R12, Vizimag 2D]:
  - Flux against vertical string distance is a falling exponential, ~0.0795 T at contact to
    ~0.0745 T at 1.5 cm.
  - Horizontal motion makes 25-30 dB less voltage than vertical, so the horizontal
    polarization is nearly silent at the pickup.
  - A string near the edge of a bar sees a different curve from one at its centre.
- The pickup's own response is flat within 1 dB (its measured impedance, [G13] Fig. 9).

**Switches** [R12 Table 1; till.com]:

| Switch 1 | Switch 2 | Result |
|---|---|---|
| A | C | centre pickup only |
| B | C | bridge pickup only |
| A | D | both, anti-phase (thin) |
| B | D | both, in phase (full) |

The tone switches are SOFT, MEDIUM, TREBLE and BRILLIANT, each a filter cell in parallel,
switched in [G13, Table 3]:

| Switch | Network | Components |
|---|---|---|
| SOFT | R \|\| C, low-pass | 30 kOhm, 0.1 uF |
| MEDIUM | R \|\| C, low-pass | 10 kOhm, 15 nF |
| TREBLE | L \|\| C | 2 H, 4.7 nF |
| BRILLIANT | L | 0.6 H |

**The amp** [G13, 2.1, 2.3.6, 3.4]:
- A two-stage BJT amplifier, then a volume pot.
- Without the tone switches its response is nearly flat: -3 dB shelf at 130 Hz, +3 dB at
  4 kHz (their SPICE of the published schematic).
- **Measured THD:** 1% at 1 kHz at 400 mV in (the pickups' largest in normal polyphonic
  playing), 3.6% at the peaks of fortissimo chords.
- Unshielded pickups and the transistor amp are noisy and pick up hum.

**The amp's schematic and power:**
- [G13] cites the schematic as public: clavinet.com's "Clavinet D6 amplifier schematic"
  (ref. 36, the gti.net link, now dead).
- Chicago Electric Piano has a translated D6 / E7 wiring diagram (web:
  https://chicagoelectricpiano.com/clavinet/hohner-clavinet-schematic-tone-controls/).
- Vintage Vibe's preamp rebuild kit (C, D6, E7) has schematics in its instructions (web:
  https://www.vintagevibe.com/products/clavinet-preamp-rebuild-kit).
- Power is a 9 V battery or an adapter (web: search summaries of seller listings; check in
  CL0).
- **The Clavinet C**, the D6's predecessor, used AC151 germanium PNP transistors (web:
  https://chicagoelectricpiano.com/clavinet/hohner-clavinet-schematic-tone-controls/).
  Whether the D6 is germanium or silicon, and which types, is read off its schematic in CL0.

**The mute bar** [G13 Fig. 1]: a slider moves felt against the strings near the tailpiece,
for the muted, pizzicato sound. Its geometry and felt are unknown.

**Not found yet:** string gauges, lengths and tensions per key (per-note string sets are
sold as replacements, so the gauges should be findable), the tangent rubber's hardness and
size, the anvil's geometry, coil turns and DC resistance, and the magnets.

## The model, part by part

### The string (the medium)

- **A stiff string per key** in two polarizations. Its modes come from the geometry (length
  anvil to tailpiece, gauge, core and wrap for the 23 wound strings, tension from the
  pitch). B follows from those; [G13]'s Table 1 is the check, not an input.
- **Losses per mode:**
  - from air and internal friction (the string's material);
  - from the ends (the tailpiece and the tangent's rubber against the anvil);
  - the non-speaking part's yarn, coupled through the anvil.
  
  One fit per unknown, each to a different published figure, as RH1 did. The ripple in T60
  over partials, period 2-3 f0, is what coupling to a lossy non-speaking segment of about
  that length ratio does: a check on the model, not a filter.
- **Beating:** the two polarizations see slightly different end impedances at the anvil and
  tangent, so their frequencies split, and the contact couples them. That is the physical
  hypothesis for [G13]'s 0.5-2 Hz beating. Test it in CL1. If it doesn't hold, the
  tailpiece's yield is the next candidate. Don't add a beating filter.

### The tangent: strike and hold (new)

- The key's lever drives the tangent's rubber tip into the string. The string is pushed
  onto the anvil and **held there**.
- The rubber is a nonlinear, lossy contact (a Hunt-Crossley law, as the Rhodes' neoprene),
  folded into the step as in `varimu/rhodes/key.py`. The difference: the contact persists.
  While held, the string's termination is the anvil plus the tip's rubber.
- **Key pressure** pushes the string further over the anvil and raises its tension: pitch
  up. That gives the Clavinet's vibrato by finger pressure (provisional: model knowledge;
  measure the size from the geometry). It maps to aftertouch, as tube_synth's PRESSURE does.
  Polyphonic or channel aftertouch: an open decision below.
- **The knock:** the tangent's impact on the anvil, felt through the stud and the keybed,
  reaches the string. Live, the impact's force drives a few keybed modes into the string's
  end. At production, the keybed is a small modal plate.

### The release (new)

- Key up: the tangent leaves the anvil. The speaking and non-speaking parts become **one
  string** (tuning pin to tailpiece), with the yarn along part of it.
- In the medium this is a change of mode set at the sample the contact opens. The state is
  projected from the held string's modes onto the whole string's (displacement and
  velocity along the string).
  - Both sets are compiled per key.
  - The whole string's modes carry the yarn's heavy damping, so they die in milliseconds.
  - Its fundamental is three semitones below the held note [G13]: a check on the
    geometry.
- A re-strike during the release tail projects back onto the held set.

### The pickups

- The existing 2D magnetostatic map (`varimu/rhodes/pickup.py`), per bar, with the string's
  place across the bar as a parameter. A string at a bar's edge sees a different flux curve
  [R12].
- Each pickup reads the string's vertical displacement at its own place along it (the
  centre pickup's distance varies across the keyboard, the bridge pickup's is constant).
  That gives the comb filtering [G13 Fig. 3]. The horizontal polarization enters 25 dB down,
  from the same map.
- The EMF of each bar coil, then the coils in series as the bars are wired. Two outputs,
  centre and bridge, each with both terminals, so the selector's anti-phase sum is a wiring.

### The circuit

`config/circuits/clavinet_d6.yaml` (the plan's first circuit file):
- the strings medium's two pickup outputs, each behind its coils' resistance and
  inductance;
- the A / B and C / D selector as `switch` parts;
- the four tone cells as `switch`ed R, C and L parts (Table 3's values: linear inductors to
  start; their cores matter only if a level check says so);
- the two-stage BJT amp from the schematic, and the volume pot;
- a 9 V battery as a source with internal resistance: a weak battery is a condition dial.

### Live and production tiers (as RHODES_PLAN.md's)

| Part | Live (draft) | Production (offline) |
|---|---|---|
| String | Modes compiled from geometry, both polarizations, both mode sets per key | A finite-difference stiff string with the contact in it (Bilbao & Rath, AES 128, 2010, did the Clavinet so), the reference the modes are checked against |
| Tangent | A fitted Hunt-Crossley contact in the port | Viscoelastic rubber; the lever's mechanics |
| Knock | A few keybed modes | The keybed as a modal plate |
| Pickups | Tables of flux against position per bar | A finer field solve, the magnet's pull on the string |
| Amp | Draft quality | Production quality |

**Live cost, an estimate to be measured:**
- Modes below 20 kHz summed over all 60 keys come to ~7,900 per polarization (20 kHz / f0
  summed from F1 at 43.65 Hz).
- That is ~130 per key on average, up to ~460 for F1.
- Ten keys held in the bass is ~6,000 complex modes at 96 kHz. Pruning the horizontal
  polarization above the partials that beat cuts that roughly in half.
- The Rhodes harp runs 73 keys at once. Here the held keys set the cost, not the keyboard.
  Measure with `examples/play.rs` (CL3).

## How it fits the code (a proposal)

- **Reference:** `varimu/clavinet/` in Python, outside the render cache key, like
  `varimu/rhodes/`. It reuses `pickup.py`, and the beam / contact helpers where they apply.
  `config/clavinet/d6.yaml` holds the geometry with sources.
- **Component:** the strings as a compiled component, kind `clav_strings` (e.g.
  `D6_STRINGS@1`, its data pinned by sha256 like `MK1_HARP@1`): per key both mode sets, the
  contact law, the pickup tables, the knock modes.
- **circuitsim:** a medium beside `harp.rs`, sharing its event queue, render-ahead chunks
  and worker voices. Generalize `harp.rs` rather than copy it, if the split is clean. New:
  the held contact, the mode-set switch at release, and a pressure event per key
  (`media::NoteEvent` grows one).
- **Part:** `clav_strings: [c_plus, c_minus, b_plus, b_minus]` in both builders. SPICE
  holds its outputs at 0 V, as for the harp and the plate.
- **App:** a device `clavinet_d6`, played from MIDI as `rhodes_stage_5e3` is, through Touch
  (`midi::Touch`). Its out goes to a session track, or into an amp chained after it.

## Proposed milestones (a recommendation, not decided)

0. **CL0: sources and prerequisites.** The user's rule: prerequisites first, inside this
   plan.
   - **Sources:** `data/schematics/hohner_clavinet_d6/README.md` with the amp schematic
     (clavinet.com, Chicago Electric Piano's translation, Vintage Vibe's kit instructions),
     the service documents (ManualsLib lists a D6 disassembly manual and "Clavinet D
     General Servicing Instructions"), string gauges per key, the pickup construction, and
     the papers above. Settle the two disagreements (bars x strings, which pickup is
     above). Login-walled pages: the user fetches them, each URL alone in a code block.
   - **The BJT model** (Gummel-Poon subset): a Python reference, SPICE's native model,
     circuitsim's port, the three-way test pattern (DEVICE_BUILDER_PLAN.md "New device
     types"). This is CHAINS_PLAN.md's **WP10**, also wanted by DRUM_PLAN.md D3,
     MIC_ROOM_PLAN.md A8, RHODES_PLAN.md's Suitcase and DISTORTION_PLAN.md's fuzzes.
     - If WP10 is done when this plan starts, use it and skip this step.
     - If not, build it here and mark WP10 done in CHAINS_PLAN.md.
     - Fit the D6's transistor types to their datasheets. If they are germanium (the C's
       AC151 are), include the leakage and its temperature dependence, which the Fuzz Face
       wants too.
   - *Done when:* the README lists every value the model needs with its source, or marks
     it provisional; the BJT model passes its three-way tests and matches the fitted
     transistors' published curves.
1. **CL1: one string, offline in Python.**
   - The stiff string with both polarizations, the tangent's strike and hold, the release's
     mode-set switch, the yarn, the pickups.
   - The finite-difference reference beside it, as RH1's time-domain beam.
   - Heard straight from the pickups, no amp.
   - *Done when:*
     - B within [G13]'s Table 1 for the keys it lists;
     - the release drop is three semitones;
     - a low note's T60 is on the order of 20 s;
     - the comb notches fall where the pickup distances put them;
     - the modes agree with the finite-difference reference within a measured bound;
     - the beating hypothesis is tested either way.
2. **CL2: the keyboard and the D6's electronics, offline.**
   - All 60 keys fitted (the wound / plain step at 23 / 24), the mute bar, the knock.
   - `clavinet_d6.yaml` with the switches and the BJT amp.
   - MIDI renders (`scripts/clavinet_render.py`, like `rhodes_render.py`).
   - *Done when:*
     - the tone switches' responses match [G13] Fig. 11 / Table 3;
     - the amp alone shows the -3 dB / 130 Hz and +3 dB / 4 kHz shelves and ~1% THD at
       400 mV, 1 kHz;
     - a MIDI file renders through the whole instrument.
3. **CL3: the medium in circuitsim, live.**
   - The component compiled, the medium in Rust, the part in both builders, the pressure
     event, the app's device.
   - *Done when:*
     - Rust matches Python within a tested bound;
     - it plays from a MIDI keyboard without dropouts with ten keys held in the bass (load
       from `examples/play.rs`);
     - key pressure bends the pitch audibly.
4. **CL4: the production tier.**
   - The finite-difference strings with the contact, the keybed plate, the magnet's pull.
   - Takes rendered behind (MIDI_TAKES_PLAN.md).
   - *Done when:* the live tier is checked against it with measured margins.
5. **CL5: condition dials** (realistic first, then bend):
   - tangent rubber hardened or worn (brighter, then buzzing or dead notes);
   - yarn worn thin (notes ring on after release);
   - old strings (more damping, more inharmonicity);
   - pickup height;
   - a tired 9 V battery (sag into the amp's clipping);
   - the mute bar's position and pressure;
   - per-instrument tolerance draws.

## Open decisions (the user's)

- **Which records it should sound like.** "Superstition" and "Higher Ground" are the ones
  named so far (RHODES_PLAN.md). Whether those are a C or a D6 is to be checked. The D6 is
  the documented one and is proposed first, the C as a variant (its germanium amp; the
  strings and action are close, provisional: model knowledge).
- **What it plays into:** the D6's own amp to a session track (DI), or on into an amp (the
  5E3 now; others later). Effects such as a wah are a separate device, not this plan.
- **Key pressure:** polyphonic aftertouch per key if the keyboard sends it, or channel
  aftertouch on every held key.
- **Where the track goes** relative to the chains (CHAINS_PLAN.md), the Rhodes' RH4-RH6 and
  the rest.
