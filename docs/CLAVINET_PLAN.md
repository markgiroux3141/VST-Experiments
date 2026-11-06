# The Hohner Clavinet from physics

Drafted 2026-11-06 from a conversation with the user ("is a clavinet on our list of
instruments to make, and does it fit our methods?", then "let's put this into a plan doc").
Before this it was only a line in INSTRUMENT_PLAN.md's "Others worth noting (not planned)"
and in RHODES_PLAN.md's "The target" ("could follow cheaply once this exists").

**The user's decision (2026-11-06):** long-standing prerequisites, such as the BJT model,
are done **first, as part of this plan**, when the plan is picked up. They are not a reason
to postpone it. So CL0 below builds them unless another track has built them already.

Milestones CL0-CL5, worked in order with the usual "done when" discipline. **Built
overnight 2026-11-06 (the user: "let's build this now ... be self reliant, make decisions
yourself"), branch `clavinet` in the worktree `VST-Experiments-clavinet`:** CL0 and CL1
done, CL2 built (the amp provisional until the D6 schematic is read), CL3 in progress (its
own status section below, when written). Every decision below was Claude's; each is marked
provisional where it rests on model knowledge.

## Status (2026-11-06): CL0-CL2

**CL0.**
- **Sources:** `data/schematics/hohner_clavinet_d6/README.md`. The two papers that measured
  a D6 ([G13], [R12]), string gauges and types from sellers and forums, the D6's front end
  (a BC 413C, clavinet.com), the E7 / C preamp notes.
- **Not found:** the D6 schematic itself (its known copies are images and login-walled
  attachments; the README lists them). The user fetches these:

  ```
  https://chicagoelectricpiano.com/hohner/clavinet-schematic-wiring/
  ```
  ```
  https://www.vintagevibe.com/products/clavinet-preamp-rebuild-kit
  ```
  ```
  https://groupdiy.com/threads/clavinet-e7.38507
  ```
- **Settled:** six bars of ten strings ([R12]'s dimensioned figure) and the bridge pickup
  above the strings ([G13]).
- **The BJT model** (commit f6646ac; CHAINS_PLAN.md WP10 marked done):
  - the Gummel-Poon DC subset: a Python reference, ngspice's native model, circuitsim's
    `devices/bjt.rs`;
  - the part `bjt: [c, b, e]` in both builders, with its RB / RC / RE and CJE / CJC as
    linear elements;
  - `BC550C@1` and `BC560C@1` (NXP's cards), and `BC413C@1` (the BC550C's card,
    provisional);
  - agreement: Python vs ngspice `.op` to 2e-8; Rust bit-equal; the `bjt_stage` transient
    vs ngspice -85 dB.

**CL1, one string offline in Python** (`varimu/clavinet/`, `config/clavinet/d6.yaml`,
`tests/test_clavinet.py` 29 tests, `scripts/clavinet_key_study.py` -> `reports/clavinet/key/`):

- **Geometry:**
  - The plain strings (keys 24-60, one 0.008 in gauge) run L ~ f^-1/2, from [G13] Fig. 6's
    flat B. Key 60's length (18.5 cm) is solved from B(E6) = 8e-5; E6 then stands at 62% of
    the wire's tensile strength (the forums: the originals "break easily").
  - Tensions run 7.5 N (E3) to 60 N (E6): slack low plain strings, the largest pressure
    bends.
  - The wound strings (three types, copper wrap) run linearly from 0.80 m at F1. Each
    type's core is fitted to [G13]'s B: the model gives 1.0-3.4e-4 against 1-5e-4.
- **The string** (`strings.py`):
  - The speaking and non-speaking segments are Hermite beam elements, reduced to their
    fixed-interface modes plus the constraint modes of the anvil's deflection *and slope*
    and the tailpiece end's deflection. Both polarizations are modelled.
  - Released and held share these coordinates, so the key's release is an exact
    projection.
  - The pinch (anvil, rubber, sideways grip tilted 8 deg, the tangent's mass) is
    linearized about the static press.
  - The first version used analytic sines with the anvil as a hinge. The plain FE
    reference (`reference.py`) showed that the hinge cut the bending path into the pinch
    and the yarn: decays up to 100x short of loss sideways.
  - Now the held ringing modes match the plain FE within 0.01 cents and 0.92-1.09 in decay,
    and the released fundamental matches within 5 cents.
- **Fits, one unknown per figure** (`fit.py`, cached in `cache/clavinet/`, ~5 min cold):
  - the non-speaking fraction 0.168 and the yarn's dashpot 4.6 N s/m^2 (scaled with the
    string's diameter): release drop 3 semitones at E4, gone in 0.1 s ([G13] 2.3.1,
    Fig. 5);
  - the rubber's wrap compliance 6.4 kN/m (the finger vibrato: +20 cents at E3 from 1 to
    5 N, a provisional target);
  - the tailpiece as a resistive termination (the case as a large plate) of 805 N s/m:
    A2's fundamental 22 s ([G13] Fig. 7a);
  - the wound strings' wrap friction 3.8e-4: A2's partials 2-5;
  - the steel's bending loss went to its floor once the slope was carried through the
    pinch;
  - the mute felt's dashpot 0.08 N s/m (muted E4 0.3 s, provisional).
- **Checks against [G13], not fitted:**
  - the release drop is 2.4-3.2 semitones over the keyboard ("three semitones for the
    whole keyboard");
  - plain B 7.4e-5 measured from the partials as [G13] does (Table 1: 8-9e-5);
  - A2's partial T60s 22 / 14 / 10.3 / 8.1 / 6.7 s (read 22 / 16 / 10.5 / 9.7 / 4.9);
  - E4's 10.6 / 8.0 / 6.4 / 6.1 / 5.5 s (read 8.1 / 9.0 / 7.0 / 8.6 / 6.5);
  - E6 ~5 s, F1 ~50 s.
  - Bass releases ring 0.3-0.6 s, the plain strings' 0.09-0.14 s.
  - The beating hypothesis: the pinch's anisotropy splits each partial into two
    polarizations ~0.4 Hz apart at E4, the slow end of [G13]'s 0.5-2 Hz. Whether that
    beating reaches [G13]'s 15 dB depth isn't measured yet.
- **The pickups** (`pickup.py`):
  - The model is the section *along* the string (each bar a 5 mm pole there), by
    reciprocity, the wire magnetized along its axis and across it.
  - Every string over a bar is equally sensitive, and horizontal motion is invisible to
    first order ([R12]: 25-30 dB down).
  - The linkage falls with height somewhat faster than [R12]'s Vizimag curve.
  - The sections across the strings (two tried) put the gradient at the bars' ends, with
    mid-bar strings 20-40 dB quieter, which [R12] doesn't report.
  - The level factor is 0.80 (E4 forte 0.2 V on the centre pickup). The keyboard's mf
    peaks run 0.07-0.25 V on the plain strings and up to ~1 V on the bass (the bridge
    pickup).
- **A played key** (`note.py`):
  - The strike: three contacts solved inside each step on the released modes (a 3x3
    Newton): the rubber's push, the anvil's push, and the rubber's shear grip sideways,
    stuck where it first touched.
    - Without the grip, the anvil's tilted face slid the string millimetres sideways and
      past the anvil. The held model saw a huge vibration; the tension modulation's absurd
      glide exposed it.
    - The pinch closes 12-15 ms after first contact, at ~35 N peak.
  - The hold in closed form on the held modes.
  - The release: the contacts again while the key's return force pulls the tangent away.
    Releasing at once snapped the bent string back in one step, a full-band click.

**CL2, the keyboard and the electronics offline:**
- **`varimu/clavinet/keyboard.py`:** MIDI notes summed per pickup; every key has its own
  string, so the sum is exact.
- **`config/circuits/clavinet_d6.yaml`:** the pickups as control inputs, the selector, the
  tone rockers and a provisional two-stage BC413C amp on its 9 V battery. `varimu check`
  is clean over all 64 switch combinations.
- **The tone chain's topology** follows from [G13] Fig. 11: a switched series chain to
  ground.
  - TREBLE's peak lands at 1645 Hz and ALL's notch at 3675 Hz (Fig. 11: ~1.6 and
    ~3.5 kHz).
  - All rockers off is silent (-140 dB): the D6's known quirk.
  - The levels are within 2-4 dB of Fig. 11.
- **The amp's three fitted values** (`scripts/clavinet_amp_study.py --fit` ->
  `reports/clavinet/amp/`):
  - Q1's emitter resistor 46.6 Ohm: THD 1.0% at 400 mV;
  - its bypass 16.4 uF: -3.0 dB at 130 Hz;
  - the high shelf's 41 nF: +3.0 dB at 4 kHz.
  - `tests/test_clavinet_amp.py` keeps all of these.
- **MIDI renders** (`scripts/clavinet_render.py (--midi F | --demo)` ->
  `reports/clavinet/renders/`):
  - the demo (an original funk phrase, 107 notes, 12 s) renders in 80 s of strings plus
    11 s of circuit at production;
  - its EMF peaks 0.52 V ([G13]: ~400 mV).
- **Not done:**
  - the knock (CL4 as planned);
  - aftertouch in renders (the bend is modelled statically: `fit.bend_cents`);
  - the user hasn't listened.

**CL4, started (the production tier's extras, in the Python reference):**
- **The knock** (`knock.py`, `note.play(knock=True)`, the default):
  - the anvil's contact force during the strike rings the board the anvils stand on (a
    12 mm plywood plate, 0.80 x 0.30 m, simply supported, provisional; 29 modes to 4 kHz,
    the lowest 263 Hz);
  - its motion under each key's anvil pushes the pinched string for the hold's first
    0.4 s;
  - measured -29 to -37 dB under the note in its first 200 ms;
  - in the treble the pickups hear it mostly as the string's own partials. [G13] isolated a
    knock below 1.2 kHz, so the board is probably too stiff (open: its dimensions and
    mount).
- **The beating, measured** (`scripts/clavinet_beating.py` ->
  `reports/clavinet/beating/summary.json`):
  - the pinch's anisotropy splits every partial into two polarizations 0.08-1.8 Hz apart
    up to E4 ([G13]: 0.5-2 Hz, up to E4);
  - the weaker mode carries -17 dB at the provisional 8 deg tilt;
  - the envelopes measured on rendered notes ripple mostly 1-5 dB at 0.2-0.8 Hz (larger
    near the comb's notches), against [G13]'s up to 15 dB;
  - the lever is the tilt (a fit to [G13] Fig. 7b is the obvious next step: one unknown,
    one figure).
- **A listening set:** `scripts/clavinet_listen_set.py` -> `reports/clavinet/listen/`
  (LISTEN.md lists the files):
  - single notes over the keyboard;
  - E3 at three velocities;
  - the demo phrase through every pickup setting and tone rocker, and muted.
- **Tension modulation** (`note.play(tension_mod=True)`, the default):
  - the hold's ringing modes follow the tension their energies add (the string's
    elongation through the geometric stiffness, both planes);
  - the stiff, heavily damped modes are left out: the damped system's modes aren't
    orthogonal, and their cancelling amplitudes aren't energy;
  - E3 ff starts +16 cents and glides to pitch (+2 by 1.5 s), E3 pp +7, E2 ff +32 (+8 at
    1.5 s), E4 ff +4, E6 none (`test_tension_modulation`).
- **Not done:**
  - the magnet's pull;
  - takes rendered behind (MIDI_TAKES_PLAN.md);
  - the live tier's check against this tier.

**Found, worth hearing (2026-11-06):** velocity changes the attack more than the
loudness.
- From 1 to 4 m/s at the tangent, the rubber's peak force rises 21 -> 57 N, but the
  sustained level (E3, E4, C5) moves by under 2 dB, and the spectral centroid isn't
  monotonic in velocity.
- In this model the press's fixed displacement (the string pushed 1.5 mm onto the anvil)
  sets the fundamental; the speed of the push mostly shapes the attack.
- A real D6 is called touch sensitive. If it sounds too flat, the levers are physical: the
  anvil gap (provisional 1.5 mm), the rubber (Shore 60, 2 mm tip), the hold force.
- **The magnet's pull** (not built): the along-the-string model's field energy suggests a
  negative stiffness of order 10 N/m at each pickup (against a string's few hundred N/m
  there). The tuner tunes most of it out; it would mostly stretch the partials slightly.

**Open (the user's):**
- the listening (`reports/clavinet/listen/LISTEN.md`);
- the D6 schematic (fetch the links above);
- whether the strings' few provisional geometry choices need sources: the wound lengths'
  bottom (0.80 m), the anvil gap (1.5 mm), the pickup clearance (3 mm), the tangent's
  rubber.

## CL3 status (2026-11-06, overnight; the decisions delegated)

**Built:** the strings compiled, their Python twin, the circuitsim medium, the part in both
builders, the live circuit, the app's device. Commits 07a8a58, 820ff15, fc3f50f and the
data's.

- **The compile** (`varimu/clavinet/compile.py`, `scripts/compile_clavinet_strings.py
  [--check]`): the component `D6_STRINGS@1`, kind `clav_strings`. Per key, at a 12 kHz live
  band (`LIVE_BAND_HZ`):
  - the released and held systems' modes, halved as the Rhodes harp's (pairs' upper modes,
    the rows doubled; 28-276 released modes a key);
  - the contacts' constants: the rubber (K, p, alpha) and its sideways grip, the anvil, the
    tangent's mass, travel, hold and return forces;
  - the two switches as transfers `z = A z + B conj(z) + c` (the strike's end takes the
    tangent's position and velocity too; the release's `c` is the static press);
  - each pickup's dLambda/dh(h) table (4096 points, linear), the level factor folded in.
    The "along" map is blind to x, and the compile refuses a map that isn't;
  - the bend table (cents against the hold force, `fit.bend_cents`) and the velocity law.
- **The data:** a 134 kB JSON header and a 50.5 MB little-endian sidecar, both pinned by
  sha256 in the version.
  - 93% of the data is the four transfer matrices, stored float32. Float64 was 94 MB; float32
    moves nothing measurable against the -125 dB port bound.
  - Folding the transfers through the physical coordinates, with M and C kept sparse,
    would halve it again. Not done.
  - **Reproducible byte for byte** only since the compile seeds scipy's `eigsh` while a key
    compiles (`compile._seeded`). strings.py leaves its v0 random, and scipy 1.18 draws it
    from OS entropy on every call. The bases then differed at rounding, so did the modes'
    phases and the real / complex split of near-critical pairs (key 36: 85 or 86 kept
    modes), and with them the bytes (not the physics).
  - Passing `rng=0` to strings.py's `eigsh` would make the patch unneeded.
  - The workers each run one BLAS thread. A compile in one process (`workers=1`) rounds
    differently.
- **The twin** (`varimu/clavinet/live.py`): `note.py` ported sample by sample.
  - The contact stepper runs both the strike and the release: a 3x3 Newton on a
    forward-difference Jacobian, the grip included.
  - A flight sample (no force yet) is stepped whole.
  - The hold and the free ring are per-sample rotations; sleep is checked every 1024
    samples.
  - Against `note.play` at the same band (knock and tension modulation off: production
    items): **-124 to -135 dB** per pickup over a 0.6 s note (keys 1, 24, 36, 60; 1 and
    4 m/s; `tests/test_clavinet_live.py` asserts -110).
  - The 12 kHz band itself, against note.play's default 24 kHz, measured before the grip
    went in: the waveform differs by -10.5 to -39 dB over a note (treble worst). The
    partials' frequencies move by 0.24 cents at most (key 60), the levels below 3.2 kHz by
    0.2 dB, the 8-32 kHz band by -0.6 to -4.5 dB.
- **circuitsim:**
  - `keyed.rs` is the harp's voice / worker / render-ahead machinery made generic: a
    `KeyVoice` trait with any number of output channels. `harp.rs` runs on it, bit for bit
    as before (a dump compared before and after).
  - `clavinet.rs` is the medium. The IR element `ClavStrings` names the header by its path
    relative to the repo root (`$VARIMU_ROOT`, else the crate's checkout) and pins the
    sidecar's sha256. The model is loaded once per process.
  - Media can now drive several outputs: the strings drive `centre`, `bridge` and
    `bridge_neg`.
  - `NoteEvent::Pressure` (channel aftertouch) is new, and Python's notes take
    `"pressure"`.
  - **Rust against the twin: -225 / -232 dB** (centre / bridge) on a run of chords, a
    release mid-strike, re-strikes, pressure and releases, at k = 1 and k = 2. It is the same
    on any number of threads (`tests/test_clavinet_compiled.py`,
    `crates/circuitsim/tests/clavinet.rs`).
- **Builders:**
  - The part `clav_strings: [centre, bridge, bridge_neg]` builds bit for bit in both
    builders (agreement.rs), with a `ClavStrings` symbol and SPICE holding the nodes at 0 V.
  - `config/circuits/clavinet_d6_live.yaml` is generated by `scripts/derive_clavinet_live.py
    [--check]`.
  - A note through the medium in that circuit equals the offline path (the strings
    rendered alone, then driving `clavinet_d6.yaml`'s control inputs) **bit for bit**.
- **The app:** the device `clavinet_d6` (Instruments, draft-2x as the Rhodes; panel:
  pickups, SOFT, MEDIUM, TREBLE, BRILLIANT, volume). Channel pressure reaches the strings,
  and the touch reads the tangent's 12 dB law. `examples/play.rs --hold-bass N [--from
  NOTE] [--restrike S]` measures it.

**Load (this desktop, draft-2x, 30 ms buffer, `--set volume=0`):**

| Case | Load | Worst block | Dropouts |
|---|---|---|---|
| Nothing played (the amp alone) | 18% | 26% | 0 |
| Ten bass keys held (F1-D2), after their strikes | 29% | 37% | 0 |
| The ten bass strikes, one a ms | | 684% | 14 |
| Ten held, ten more struck at once every 2 s | 40-50% | 800-920% | ~5 a strike |
| One key struck every 0.5 s | 39% | 350-368% | ~3 a strike |
| A three-note chord every 1 s | 29% | 241-678% | |

- **Holding is cheap. Striking is over budget:**
  - One voice alone (Python's `clav_render`, one thread) costs 2.3x real time during a bass
    key's strike (F1) and 0.67x for the top key's, for the strike's ~16 ms.
  - Over a 1 s hold that falls to 0.03-0.10x.
  - So the done-when is not met: it plays without dropouts only once the keys are down.
- **The levers, measured:**
  - **The contact's substeps** (`strings_contact_rate_hz`, 16 per sample now, as
    `note.py`):
    - At 8 per sample the note differs by -40 to -90 dB from 16, at half the contact's
      cost. Ten held plus ten struck: worst block 419% (from ~900%). Not enough alone.
    - At 4 the treble's contact goes wrong (+3 to +28 dB).
  - **The strike's 10 ms minimum window** (`STRIKE_WINDOW_S`): switching to the held modes
    as soon as the pinch has settled changes the note entirely (-1 to +9 dB). The held
    linearization isn't yet where the stepped contact is at ~5 ms. This needs work, not a
    setting.
  - The Newton's forward-difference Jacobian is 4 residuals an iteration; an analytic one
    would roughly halve a treble key's strike. The modal loops are AVX2 already.
  - A lower live band would cut a bass key's modes, for the strike and the hold alike.
  - Caching strikes from rest per (key, velocity) is possible: a strike from rest is
    deterministic. It would cost memory (~28 kB a strike at F1).
  - Running the strikes on worker threads doesn't help one voice.

**Decisions made (delegated):**
- The live band is 12 kHz (the brief's default).
- The pickups' tables are 1-D in h, valid because the "along" map is x-blind (checked at
  compile).
- The transfers are float32.
- Conjugate pairs are halved as the harp's are; real modes are kept once.
- The release keeps every released mode, since the release's contacts run on all of them.
- Aftertouch scales only the held modes' frequencies, by the bend table's ratio; the
  press's static shift and the new shapes are left out.
- A key-up during the strike waits for its end.
- A key-down while held releases the state to the released modes and strikes again from
  there, the tangent thrown from its travel.
- A key-down during a release re-strikes from the ringing state.
- The knock and the tension modulation stay out of the live tier (CL4, the parent's call).
- The IR names the data by path and sha256, not inline (50 MB): circuitsim reads files.
- `D6_STRINGS@1` holds the transfers as float32.

**Open:**
- the strike's cost (above);
- strings.py's `eigsh` seeded at the source (above);
- `tests/test_rhodes_compiled.py`'s saved-harp check failed in this worktree (2026-11-06).
  Neither varimu/rhodes nor the harp's arithmetic changed (`harp.rs` on `keyed.rs` is the
  same bit for bit); not looked into;
- the knock and the tension modulation live;
- the sidecar's size;
- polyphonic aftertouch (only channel pressure reaches the strings; the app's keyboard
  sends one pressure);
- the user plays it.

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
