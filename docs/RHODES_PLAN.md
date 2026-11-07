# The Rhodes electric piano from physics

Drafted 2026-11-04 from a conversation with the user ("an electric piano, built the way
we've been doing the other synths with physics; it would sound like the one in most Stevie
Wonder songs. What would be reasonable given our CPU load and the fact that multiple notes
would have to sound at once?", and: "just like with the synths, we could have a production
setting that we could render offline that was much higher quality and more physically
accurate"). Picked up 2026-11-04 (the user: "let's build the rhodes"): RH1 is built, see
"Status". It expands INSTRUMENT_PLAN.md's section B (Rhodes) and its milestone I2; the
order below is a recommendation, and the open decisions are the user's.

## Status (2026-11-04): RH3 built, the harp in circuitsim, played live

The harp is a medium in the netlist, played by note events, compiled from RH1-RH2's Python
into a component, and it plays from a MIDI keyboard into the 5E3 in real time with every key
ringing.

- **The component** `MK1_HARP@1` (kind `ep_harp`; `varimu/rhodes/compile.py`,
  `scripts/compile_rhodes_harp.py [--check]`, 3 s): `config/components/mk1_harp/1.yaml` pins
  its data `1.harp.json` (3.7 MB) by sha256, both loaders checking it. Per key, the live
  tier (`key._System`) free and under the felt: the complex modes halved (the upper of each
  conjugate pair, outputs doubled), the strike point's and the tip's rows, the damper's
  transfer between the two systems, and the arc's quadratic form reduced to rank 3-4 (an SVD
  of the slopes weighted by a strike's displacement per mode: a struck key's EMF within
  -114 dB of the full forms; rank 2 was -76 dB). Once for all keys: the flux map's bicubic
  B-spline, the velocity law, the contact window, the sleep threshold, and the coils (1425
  ohm, 0.327 H, their sources moved here from the circuit). Compiling all 73 keys took 452 s
  until each worker had one BLAS thread.
- **The medium** (circuitsim's `harp.rs`; IR `Harp`, `media::NoteEvent`): it senses nothing,
  so it renders ahead in chunks of 256 steps, up to the last step whose events are known
  (`Transient::queue_note`, `Stream::queue_notes`, `simulate_notes`, Python `simulate(notes=)`
  and `fast.run_transient(notes=)`). The voices run at the step rate (in band within -72 to
  -110 dB of 8x it), the contact at 384 kHz (768 kHz changes nothing measurable). The
  hammer's window ends early once it is falling below the strike point's reach (exact). The
  flux map is evaluated as a bicubic polynomial per span (Horner, its span cached). Modes
  under 1e-100 are zeroed at sleep checks: decaying into subnormals, 73 keys ran 30x slower
  than real time after a second. With more than four voices awake, a chunk's voices are
  shared between the calling thread and up to three workers, each voice rendering into its
  own buffer and summed in order (the same bit for bit on any number of threads).
- **Agreement:** Rust against the Python reference (`harp.render`'s internal EMF, the
  voices at 2x, the contact at 4x) at -128 dB rms over strikes, a re-strike, the pedal and
  releases (`tests/test_rhodes_compiled.py`, bound -110 dB); the halved modes exactly, the
  reduced arc within 0.5% once the tine rings. `crates/circuitsim/tests/harp.rs`: the same on
  any number of threads, events landing at their step (a late one at the next), the felt,
  the pedal, a stream fed notes block by block equal to the whole run.
- **The part** `harp: [out]` (component, rate_hz, contact_rate_hz) in both builders, bit for
  bit (`tests/agreement.rs`: 43 cases, 7.3 M numbers; a case's harp names its model
  "default", the fixture keeping it once); a `Harp` symbol for the editors.
  `config/circuits/rhodes_stage_5e3.yaml` (regenerated) has the harp driving the Stage; its
  audio input is unused.
- **Live without the readout** (the user's choice below): `build_ir(..., speaker_readout=
  False)` / `build_ir_live` put a speaker's terminal voltage on its `out` (both builders, a
  fixture case for every speaker circuit); the app's `panel::Device::live_speaker_v` (20 V
  full scale: the 5E3's largest swing clipping hard, 18.5-19.3 V; 60 V, its full scale
  before C3, played it 10 dB down) plays the Rhodes so; the 5E3 device itself is unchanged
  (C3's question stays open).
- **The app:** `midi::Keys::take_events` (keys down and up, the sustain pedal, all notes
  off), placed in the next block at their spacing (`player::note_offsets`: a block late at
  most), `Live::process_notes`; the device `rhodes_stage_5e3` (draft-2x).
- **Load** (`examples/play.rs --device rhodes_stage_5e3 --strike-all [VEL] [--restrike S]`,
  2026-11-04, this desktop, 30 ms buffer): all 73 keys struck with the pedal down: 76-83%,
  0 dropouts in 20 s; all re-struck at velocity 127 every 4 s: 80-84%, worst block 139%, 0
  dropouts in 24 s; ~70 ms keys to ear. The harp alone (`examples/harp_bench.rs`): all 73
  ringing 0.22x real time, 0.51x on one thread.
- **Renders:** `scripts/rhodes_render.py` plays the MIDI through the medium (the demo's harp
  0.5 s for 18.3 s, was 67 s in Python; `--reference` writes the harp's WAV from the Python
  reference); the demo at production 7.6x real time.

**Open (RH3):** the user plays it from a MIDI keyboard; RH4 (the amp: hearing it against the
songs). Against a real Mk I Suitcase recording the harp was too dark and has no pan:
"Against a real recording (2026-11-06)" below; refitted to a real Mk I's single notes as
MK1_HARP@2 (2026-11-07, "Single notes: jRhodes3d"). Next: the Suitcase's electronics (the
1978 100 W "Janus" preamp with its LED / photocell vibrato, `data/schematics/rhodes_suitcase/`). Repeated notes sound alike (the user's first playing): why, and what varies on a real
Rhodes, is parked in [RHODES_VARIATION.md](RHODES_VARIATION.md) (future work).

## Against a real recording (2026-11-06): the gaps

The user: "our version isn't that close to this sound". The reference is a real Mk I (1978)
through its Suitcase electronics: `real instrument samples/Rhodes Mk I 1978 - with Suitcase
preamp by Tines and reeds.mp3` (untracked, not committed; a 14.2 s stereo mp3, 44.1
kHz, ~95 kb/s, so low-passed near 16 kHz; a comping phrase of chords with a sustained tail,
no isolated notes). The analysis was run once outside the repo (Welch spectra, STFTs, the
L / R envelopes); nothing built, no file changed but this one. The chords limit what it can
prove: the measurements below are firm, the causes are ranked suspicions.

**What it shows.**
- **The Suitcase "Vibrato" is the most obvious difference.** L and R swing in antiphase at
  **3.83 Hz**, ~16 dB peak to peak per channel (+-8 dB), phase between them 163 deg,
  nearly sinusoidal (the balance curve's 2nd harmonic 2%); side / mid -9.6 dB, L / R
  correlation 0.80. The Stage into the 5E3 is mono and static ("The side-to-side pan",
  below: nothing built).
- **The harp is far too dark before any amp.** Band energy normalized to 200-2000 Hz:

  | Band | Real | Our harp (`demo_rh3_harp.wav`) | Our 5E3 out (`demo_rh3.wav`) |
  |---|---|---|---|
  | 500 Hz-1 kHz | -8.8 dB | -21.1 dB | -21.8 dB |
  | 1-2 kHz | -18.6 dB | -46.5 dB | -42.5 dB |
  | 2-4 kHz | -37.2 dB | -62.0 dB | -48.5 dB |
  | 4-8 kHz | -46.5 dB | -77.5 dB | -70.9 dB |

  The real recording falls ~10 dB per octave from 1 to 8 kHz; ours collapses above ~1
  kHz, 12-30 dB short, and already at the pickup, so the 5E3 isn't the main cause. Per
  key (`reports/rhodes/key/audio/`, the harmonics re the strongest over 0.05-0.6 s): D#4
  (key 43) at 1 m/s 0 / -3 / -35 / -47 dB, at 2 m/s -4 / 0 / -25 / -31; G#5 (key 55) at
  2 m/s 0 / -5 / -39 / -53. The real tail (12.6-14.1 s) holds even partials near the 2nd
  (~622, ~1251 Hz within 2 dB of their fundamentals) and lines at 2.2-3 kHz ~33 dB under
  the fundamentals still audible 1.5 s on; ours has no partial, harmonic or inharmonic,
  above -100 dB re the fundamental after 0.1 s past the 5th harmonic. (The demo plays other
  notes, and the real partials can belong to other chord tones: strong evidence, not
  proof.)
- **What already matches:** the fundamentals' decay (real tail 2-6 dB/s; ours at key 43
  -5.6 dB/s, Shear's Q), and a strong 2nd harmonic (the centred voicing's).
- **Also seen:** the real recording is high-passed below ~80-90 Hz (the Suitcase or the
  capture; our demo carries far more 60-200 Hz, partly its notes). The attack couldn't be
  isolated (chords over ringing notes): the real onsets show broadband energy to ~8 kHz,
  but how much is mechanical noise is open.

**Likely causes, most confident first.**
1. **The pickup's nonlinearity is too gentle.** The 2D section (and the tip and pole's
   shapes, all provisional) gives too few harmonics past the 2nd-3rd. The real field is
   sharper near the tip-to-pole gap, which puts energy into harmonics 3-8. RH5's 3D solve
   and the magnet's and coil's real dimensions are where it is decided.
2. **The tine's bell partials are weak or damped too fast.** The second beam mode (~6.3x
   bare, moved by the spring) and up ring for hundreds of ms on a real tine; our losses
   are stiffness proportional (`beam.py`: "the bell partials die fast"), so the upper modes
   die faster than the fit to the fundamental's Q justifies. Their decay has no source yet.
3. **No mechanical noise.** The hammer's thump, the key bottoming, the damper and the rail
   aren't modelled (RHODES_VARIATION.md judged them barely at the pickup; the real attacks
   suggest checking).
4. **No Suitcase electronics.** The 5E3 and P12R are a guitar amp and speaker that roll off
   hard by design; the Suitcase is a transistor preamp and power amp into its own speakers,
   brighter, with the vibrato. The BJT model now exists (CL0), so this waits only on the
   Peterson schematic.

**Proposed next steps (the user's to pick).**
1. **Isolated notes:** a ladder of single notes (e.g. C3, C4, C5 at soft / medium / hard)
   from a real Mk I, so the harmonics per velocity and the bell partials' decay can be
   fitted rather than suspected.
2. **The stereo tremolo now:** a chain end at the measured 3.83 Hz, +-8 dB antiphase (the
   pan's option 2 below, or the Suitcase's own once its schematic is found).
3. **The pickup's harmonic series against the real one** on those notes: the gap, the tip
   and pole shapes, then the 3D solve; and the upper modes' damping.
4. **A brighter amp path:** the Suitcase, or the Stage without the 5E3's speaker readout,
   to compare like with like.

### Single notes: jRhodes3d (2026-11-06)

**The source.** Jeff Learman's jRhodes3d, a 1977 Mark I Stage 73 recorded from the harp
connector: 15 notes (F1-C7, every 4th white key), up to 5 velocity layers, 16-bit / 44.1 kHz
FLAC, up to 25 s unlooped (`real instrument samples/jrhodes3d_download/`, untracked; samples
CC-BY-NC-4.0, web: https://github.com/sfzinstruments/jlearman.jRhodes3d). **Caveats from
its README:** recorded through an EQ ("a treble boost and low-mid scoop", settings not given),
noise removed (CoolEdit), the layers level-normalized (their peaks lie within ~4 dB), and
the voicing the owner's. So only what an EQ can't change is firm: decays, partial
frequencies, pitch, and how the harmonic balance changes from layer to layer. Compared with
our harp (circuitsim's medium, `harp_render`, the same 15 notes at velocities 20-127; analysis
run outside the repo like the one above).

**What it shows.**
- **The pickup's nonlinearity, the main gap.** Harmonics 1-8 re the strongest, 0.05-0.35 s:

  | D4 | h1 | h2 | h3 | h4 | h5 | h6 |
  |---|---|---|---|---|---|---|
  | real, loudest layer | -4 | 0 | -2 | -21 | -10 | -21 |
  | real, softest layer | 0 | -22 | -35 | -59 | -72 | -106 |
  | ours, velocity 127 | 0 | -3 | -35 | -47 | -79 | -92 |
  | ours, velocity 40 | 0 | -34 | -96 | -151 | -161 | -166 |

  The real softest layer is richer than our velocity 127 from D3 up; the deficit grows
  with the harmonic's order (h3 ~30 dB, h5 ~60 dB), far beyond any EQ. The bass at 127 is
  closer (F1, B1) but still short at soft and middle velocities.
- **Why: the tine swings near the top of a wide field.** Our 2D map's Phi(y) is a bump
  whose slope peaks at +-3.1 mm (half-max +-7.2 mm), while a struck tine swings (the tip's
  peak) 0.02 mm at velocity 40, 0.05 mm at 64, 0.64 mm at 127 on D4 (A2: 0.16 / 0.40 /
  2.63 mm; B4: 0.01 / 0.04 / 0.45 mm), with velocity 127's hammer at 0.73 m/s. At those
  swings the field is nearly a parabola: the 2nd harmonic and little else.
- **A test, not a change** (the Python reference `key.strike` with the map scaled in y,
  Phi_s(y) = Phi(s y), and the hammer's speed multiplied; mean |dB| of harmonics 2-6 against
  the loudest, middle and softest layers):

  | Key | Today (s 1, x1, voicing 0.4 mm) | Best in the grid |
  |---|---|---|
  | A2 (key 25) | 28.5 dB | 2.9 dB: s 3, hammer x2, voicing 0.8 mm (swing 4.9 mm at 127) |
  | D4 (key 42) | 44.0 dB | 7.9 dB: s 4, hammer x4, voicing 0.4 mm (2.9 mm) |
  | B4 (key 51) | 37.4 dB | 12.4 dB: hammer x4 (the grid's edge: wants more) |

  A2's best reproduces every real layer within a few dB (loudest: real -11 0 -3 -2 -3 -8
  -5 -18, ours -16 0 -4 -2 -3 -8 -5 -21). So the real sound needs **a field ~3-4x narrower
  than the 2D section's and 2-4x more hammer speed** (ff ~1.5-3 m/s; grand-piano hammers
  reach several m/s at ff (provisional: model knowledge), ours 0.73 m/s, set by E1's 9.5 mm
  alone). Both are physical and plausible: a 3D tine end (a small cylinder, its
  perturbation falling off faster than a 2D slab's) is RH5's solve, and the velocity law's
  scale is provisional. The 30 dB range looks right (the real layers' h3 moves ~33 dB from
  softest to loudest; the scaled model's ~32).
- **Decay: our mid and treble notes die ~2x too fast.** Fundamentals in dB/s, real
  (loudest layer) vs ours (v110): D3 -2 / -6, G3 -3 / -7, B3 -4 / -7, D4 -3 / -8, F4 -4 /
  -7, B4 -5 / -8, D6 -9 / -18, G6 -18 / -26; harmonics 2-3 likewise (real -6 to -13, ours
  -12 to -18). The Suitcase recording's tail agrees (2-6 dB/s). Ours are fitted to Shear's Q
  (another piano), so the two real Mk Is here say Q is ~1.5-2.5x higher in the middle.
- **The bell partial: weaker, shorter, and in another place.** In the first 60 ms the real
  B3-B4 show an inharmonic mode with sidebands at +-f0 (the pickup mixing it with the
  fundamental): B3 3.38 / 4.38 / 6.38 x f0, D4 3.36 / 4.36 / 5.65, B4 6.15 / 7.15 / 8.15,
  at -9 to -23 dB re the fundamental, still -36 to -44 dB at 60-400 ms (D4 7.35 / 8.35, B4
  7.15 / 8.15). Ours: the same keys' mode at 6.51-6.58 / 7.52-7.57 x f0, at -38 to -54 dB
  early and -70 to -100 dB by 60-400 ms. So the tine's second mode sits elsewhere relative
  to the fundamental (the spring's mass and position, provisional) and is excited and kept
  too little; a narrower field would raise its sidebands too. The treble's (D6 6.52 / ours
  6.28, G6 6.31 / 6.24) is closer.
- **Pitch with velocity:** the real loudest layers sit sharper than the softest in the low
  bass only (F1 +20 cents, B1 +7; from E2 up within ~3 cents, mostly the tuning); ours has
  no amplitude-dependent pitch (linear modes; the magnet's pull and the large-swing
  nonlinearity are RH5's).
- **Attack:** the time to the envelope's peak matches (real 2.7-6 ms from G3 up, ours
  3.8-5 ms); not resolved further.

**Applied (2026-11-07, the user: "do whatever you need to so we can get close to the real
sound"): MK1_HARP@2**, `rhodes_stage_5e3` pinned to it. Each change is a provisional value
fitted to the real piano, or a better solve; mk1.yaml's sources have the numbers.
- **The pickup in 3D** (`varimu/rhodes/pickup3d.py`, `pickup.field: 3d`): the tine as cuboid
  cells magnetized by the magnet's surface charges (a volume integral, its self-interaction
  factored once), the coil's linkage by reciprocity (mu0 int M . h dV, the coil as current
  loops); `tests/test_pickup3d.py` checks it against closed forms and against the direct flux
  through the turns (2e-3). Its field is only ~20% narrower than the 2D section's (slope peak
  2.5 mm against 3.1) and its shape doesn't move with the tine's length or permeability. An
  iron frustum tip (Pfeifle & Muenster's pickup), tried in the 2D section, narrowed it ~10%:
  not the lever, not modelled. The map covers the tip's pull-back to 1.6 mm (was 0.35).
- **The swing, the real lever:** the velocity law fitted to jRhodes3d's layers (a hammer
  speed per key and layer, a voicing, one shared EQ curve; the scratch fit's EQ came out +1 /
  -3 / +2 / +7 / +6 dB at 0.1 / 0.3 / 1 / 3 / 8 kHz, the sample's README's "treble boost and
  low-mid scoop" found blind): **5.0 m/s at 127 (was 0.73), 21 dB of range (was 30)**,
  swings 10-14 mm in the bass and 2-5 mm in the middle at ff (Pfeifle's camera: ~+-1.5 cm).
  **Voicing 2.0 mm** (was 0.4; per key the fit wants 0.9-2.4 mm, one global value costs ~1
  dB rms).
- **The decays:** the tine's loss fitted to jRhodes3d's Q (a cubic in log f through 15 keys'
  medians, `anchors.q_fit`); D4 now decays at -3.15 dB/s (real -3.19), B4 -4.51 (real -4.51).
- **The bell partial:** the root's taper 11 mm (was 7) and the spring at 0.85 of the tine
  (was 0.7) put the tine's second mode at 7.0-7.7 x f0 over D3-E5 (real 7.17-7.41; was
  6.2-6.7); the springs now weigh ~0.1-0.4 g.
- **The arc's rank:** the larger swings pull the tip back far more, so `compile.py` keeps
  more of it (ARC_RANK_TOL 3e-3, rank 3-7): circuitsim against the Python reference -137 dB
  (at the old 1e-2: -107.5).

Result (`scripts/rhodes_vs_jrhodes.py` -> `reports/rhodes/jrhodes/`, per note and layer the
real sample, then @2, then @1, loudness matched): D4's harmonics 1-5, real loudest -4 / 0 /
-2 / -21 / -10 dB against @2 at 127 -7 / 0 / -2 / -10 / -7 (@1: 0 / -3 / -35 / -47 / -79);
real softest 0 / -22 / -35 / -59 / -72 against @2 at 20 0 / -25 / -34 / -59 / -85. A key's
EMF at ff is now 50-60 mV peak (was 25), ~10 mV at velocity 40 (was 0.4), even across the
keyboard. **Open:** the low bass (F1, B1) is too rich at soft velocities (real F1's softest
layer 0 / -14 / -45 dB, @2's at 24 -10 / 0 / -2: the fit's worst keys at any voicing; a
larger gap there, as the manual allows 1/16-1/8 in, is the first candidate); the treble's
decays above A5 (the cubic's Q ~3000 against the real 3900-4700); the iron tip and the
magnet's pull (RH5).

### The Suitcase (started 2026-11-07; the user: "real suitcase circuit")

**Sources** (`data/schematics/rhodes_suitcase/README.md`, the service manual's ch. 11): a 1978
Mk I Suitcase has the 100 W Haigler / "Janus" electronics (fig11-1 the preamp, transcribed
node by node there and checked against the drawing; fig11-3 the dual 50 W power amp; the
speaker data are forum-grade). The reference recording's name says "with Suitcase preamp":
likely the preamp's outputs, so the preamp and vibrato come first.

**Built: the optocoupler device** (the vibrato's LED / photocell pair, Rhodes P/N 013556,
unidentified; a VTL5C1 Vactrol stands in, provisional): `varimu/devices/opto.py` (an LED
whose light ~ I^2 / (I + I_eta), a CdS cell dg/dt = a L - g / tau0 - g|g| / kappa, the state
on a node s with a 1 F capacitor to rb; pins la, lk, s, ra, rb), its SPICE subcircuit, the
component `VTL5C1@1` (`varimu fit-devices --only VTL5C1`: fitted to PerkinElmer's sheet,
`scripts/digitize_vtl5c1.py` -> `data/datasheets/vtl5c1_{resistance,response}.csv`, steady
rms 25%, the dim turn-on's first ms missed: one state, no trap filling), the IR model in both
languages, circuitsim's `devices/opto.rs`, both builders, preflight; tests
`tests/test_opto.py`, `tests/test_spice_agreement.py::test_optocoupler_agrees`,
`crates/circuitsim/tests/devices.rs` (1e-12). A circuit places it as a generic part:
`XOPTO1: {device: [la, lk, s, ra, rb], model: OPTO1}` plus `C: [s, rb]` of 1 F.

**Built (2026-11-07, overnight; the user: "do whatever you need to so we can get close to the
real sound"): the preamp, its vibrato fitted to the reference recording, the app's device.**
- **The circuit** `config/circuits/rhodes_suitcase.yaml` (hand-written; every value from
  fig11-1 or marked): the harp (`MK1_HARP@2`, a 150 pF lead) through J1's normally closed
  contact into A1A (-22), VOLUME (5K audio), A1B's Baxandall (BASS / TREBLE), C16 into the
  panning network, A3A / A3B onto `out` (P2-4, CH 2) and `out_r` (P2-3, CH 1), each loaded by
  the power amp's input (fig11-3: 680 + 4.7K + 5 uF); the oscillator A2A / A2B onto `v`
  through S1 VIBRATO; the LED strings between VB+ / VB- (R21 / R19, C14 / C12 off ideal
  +-15 V). The MC1458s by the `opamp` macro from TI's sheet (now read:
  `data/datasheets/opamps/README.md`: 200 V/mV, 1 MHz, 2 Mohm, 75 ohm, +-14 V). C3 starts at
  +2 V over VB- (`v0`) so the oscillator leaves its balance. Left out (the file says why): VA+
  / VA- (the macro draws no supply current), Q1 / LED3, LED4, J2. ACCESSORY IN (`accessory_in`
  1) puts the audio input on the preamp in the harp's place: how test tones get in. Pre-flight
  clean at every switch (the LED strings' nodes, held only by junctions, have 1 GOhm
  numerical leaks).
- **The vibrato against the recording** (`scripts/suitcase_study.py [--calibrate]
  [--candidate ...]` -> `reports/rhodes/suitcase/vibrato.{json,png}`): both balances (L over R,
  20 ms rms) are fitted with a Fourier series and folded over one period; the shape error is
  their rms difference at the best phase. The recording's pan is not a sine: **a fast flip
  (~30 ms), then a creep over the whole half period** (3rd harmonic 0.17 of the fundamental,
  in quadrature: skewed), the signature of a cell that lights fast and darkens slowly. The
  VTL5C1 stand-in darkens in ~20 ms, so it flat-tops (shape error 1.51 dB at its best
  INTENSITY). So **the VTL5C2** (the same sheet's slow type: off to 100 kOhm in ~190 ms,
  `VTL5C2@1`, `varimu fit-devices --only VTL5C2`, digitized by `scripts/digitize_vtl5c1.py
  --part VTL5C2`; `opto.fit_vactrol` fits both, VTL5C1@1 unchanged) is the stand-in now:
  shape error **1.21 dB**, the flip and the creep both there. Its limit: **+-6.75 dB** of
  fundamental at full INTENSITY against the recording's +-7.8 (peak to peak ~18 dB against
  17.5: the shape spends its swing differently). The board revision's 1K LED resistors
  (fig11-2) fit worse (2.32 dB: a brighter cell darkens later). Defaults: SPEED 0.563 (3.83
  Hz), INTENSITY 1.0 (full).
- **The tone:** the demo through it (`scripts/rhodes_render.py --demo --circuit
  rhodes_suitcase`, stereo, 2.3x slower than real time at production) against the recording,
  band energy re 200-2000 Hz (other notes: coarse):

  | Band (Hz) | 80-200 | 200-500 | 500-1k | 1-2k | 2-4k | 4-8k | 8-16k |
  |---|---|---|---|---|---|---|---|
  | Recording | -12.6 | -0.7 | -8.7 | -18.3 | -37.1 | -46.8 | -66.8 |
  | Suitcase (MK1_HARP@2) | -12.5 | -1.8 | -5.1 | -14.8 | -30.8 | -58.2 | -82.9 |

  Within ~3.5 dB to 2 kHz (the 5E3 path was 28 dB short at 1-2 kHz before @2); 4-16 kHz is
  11-16 dB short, most of it already at the harp's EMF (C2 takes ~4 dB more above 6 kHz).
- **The app's device** `rhodes_suitcase` (Instruments; panel VOLUME, BASS, TREBLE, VIBRATO,
  SPEED, INTENSITY; draft-2x): every key struck and re-struck, 72% load, 0 dropouts (worst
  block 122%, absorbed by the buffer). Played devices can now be stereo
  (`Monitor::process_stereo`: one gain for both sides, compensation on their mid; the
  Emitter's `device_right`), a take keeps their mid as it does a stereo chain end's (the
  player and `take_render` alike). Tests: `tests/test_rhodes_suitcase.py`,
  `tests/test_opto.py`, varimu-app's (the Rhodes' velocity span test now expects @2's 21 dB).

**Built (2026-11-07, the user away: "work to completion, make the calls yourself"): the
power amp, the speakers, the whole Suitcase as one netlist.**
- **The transistors** (`library.build_2n5784` ...; sheets and provenance in
  `data/datasheets/transistors/README.md`): `2N5784@1` (Q1, Q2, Q3, Q5), `2N5781@1` (Q4),
  `2N6254@1` (Q8, Q9), `RCA29B@1` (Q6), `RCA30B@1` (Q7). None has a published SPICE card
  (Central has none of them), so each is fitted to the sheet's typical curve and limits and
  the rest is marked provisional: the 2N5784's dc beta read off RCA's Fig. 9 (61 at 10 mA, 85 at
  0.1 A, 21 at 1 A, 7 at 3 A: the model 61 / 59 / 20 / 8), hFE 20-100 at 1 A and 4 min at 3.2
  A; the 2N6254's limits (hFE 20-70 at 5 A, 5 min at 15 A: the model 33 and 16; VBE 1.5 V max
  at 5 A) with IKF 4 A, IS 1e-12 putting VBE near 0.65 V at 100 mA (no curve read); the
  RCA29B / RCA30B only from a reseller's limits (80 V, 3 A, hFE 15-150 at 1 A: the RCA sheet
  wasn't retrievable), so their junction numbers are model knowledge (TIP29 / TIP30 class).
  fT (1-4 MHz for the 2N5784) isn't in the model (no transit time): the amp is more stable in
  the model than the 2N5784's own loop gain would allow at the top. `tests/test_power_bjts.py`.
- **The amp, as one netlist with the preamp:** `config/circuits/rhodes_suitcase_100w.yaml`,
  GENERATED by `scripts/make_rhodes_suitcase_100w.py` from the preamp file. **Why generated,
  not added by hand:** the two boards are one circuit twice (one place to fix), and the
  preamp-only file stays as the fast test circuit for the pan's fit (~3x faster: no 11,000 uF
  reservoirs, no speaker networks). Read from fig11-3 at zoom and checked against the idle
  point (README, "As built"). Two things the drawing is read the other way from the
  README's first notes: R6 5.6K feeds the CR2 / CR3 string **from ground** (the string sits at
  -30 V + 1.4 V, so Q2's tail is ~2 mA and Q5's ~10 mA, not an 85 mA tail), and the lower
  output half is a **Sziklai pair** (Q7's emitter takes its current from the output through R14;
  CR8 across it is a clamp), so the bias string must cover ~2.5 V and the four diodes CR4-CR7
  clamp it there: the BIAS ADJ pot can only lower it from ~29 mA.
- **Calls made (each with its reason):**
  1. **R18-R21: two 0.2 ohm in series per output transistor, 0.4 ohm** (the schematic prints
     0.5 ohm 5 W for R18 / R21; the parts list has four 0.2 ohm 10 W nichrome, R18-R21, and
     the board shows R18 / R19 and R20 / R21 as pairs). The parts list is the assembly as
     built, two in series is the only pairing near 0.5 (parallel is 0.1), and 0.4 is inside
     the drawing's 20% room; the clipping power moves ~2%.
  2. **CR1's direction:** its triangle points from the emitter node to Q1's base node (read at
     zoom): a reverse-bias protection of Q1's base-emitter junction.
  3. **The supply:** T1 013579 as two mains-driven halves (22.2 V rms each, centre tap to
     ground) behind 0.5 ohm and 1 mH, a bridge across the ends, 11,000 uF each rail (the
     mains an IR SineSource: the sag and the 120 Hz ripple are in the one simulation). The
     secondary is provisional: chosen so the rails idle at fig11-3's +-30 V. The +-15 V
     regulator board stays ideal (the preamp's rails, as before).
  4. **The factory trims** (`scripts/rhodes_amp_trim.py`, a Newton step on the two pots per
     board): OFFSET ADJUST to 0 V at each output (rotation 0.2023: R8 = 20.2K), BIAS ADJ for
     **25 mA** through each output pair (rotation 0.8735: R12 = 437 ohm). The target is
     provisional (the manual publishes none): 10 mV across the 0.4 ohm pair, what a ~50 W
     class AB stage is usually set to; the circuit's own clamp tops out at ~29 mA.
  5. **The speakers:** the 1978 configuration is **four 8 ohm 12" ceramic drivers, two per
     channel in series (16 ohm)**: the Reverb listing of a 1978 pair ("50W 8 ohm"), ep-forum
     topic 6862 and unbrokenstring.com say series for 16 ohm, fig11-9 names 16 ohm for the
     80 W amp before it; the 32 ohm CTS pairs in parallel are the 1971-75 cabinets, and topic
     8862's 4 ohm is a single unverified post. `P12R@1` stands in (Jensen's 12", 8 ohm; maker
     unknown, provisional). Each channel's **front** speaker reads out as the player's pressure
     1 m on axis (`out` / `out_r`, the 5E3's readout: pascals as volts, `full_scale.
     output_pascals_peak` **25 Pa**: the clipping peaks measured 12.7 / 21.4 / 23.0 Pa at 100 Hz
     / 1 kHz / 3 kHz). **Each channel's pair is one speaker part with `series: 2`** (a macro
     option in both builders, added in the review the same day): two identical drivers in
     series carry one current, so one force and one velocity, and the pair is *exactly* one
     driver with every resistance and inductance doubled and every capacitance halved; its
     readout and its live terminal voltage are one driver's (`tests/test_rhodes_amp.py::
     test_a_series_pair_is_one_part`: two parts against one, 1e-9; n = 1 is bit for bit the
     old element list, so the 5E3 and the Stage didn't move). The rear driver (mirrored,
     directly behind the front one) isn't read out. Half the states of two parts (40 a
     channel to 20). The first version had two parts, the rear one `readout: 0` (also a
     macro option now: a driver as a load only), and before that four readouts: 80x real time
     at draft with four, 25x with two. The cabinet is the 48 x 27 x 14 in speaker section as an
     open baffle (open / closed back unknown, below).
- **The amp measured** (`scripts/rhodes_amp_study.py` -> `reports/rhodes/suitcase_amp/`,
  1 kHz at ACCESSORY IN, draft with Newton 1e-5, THD up to the 10th):
  gain **25.31 dB** from `pre_a` to the output (fig11-3's -100K / (680 + 4.7K) = 25.4), flat to
  -0.4 dB at 20 Hz and +0.7 dB at 40 kHz; THD 0.02-0.03% from 1 W to 6 W, 1.2% at 14 W (the
  onset of clipping), 16% at 20 W; **clips at 24.5 V peak, 22-24 W into the speaker pair**
  (the README's arithmetic said ~23 W into 16 ohm: the "50 W" rating is optimistic for 16 ohm,
  or the cabinets were lower); the pair's |Z| 15.8-16.5 ohm at 1 kHz; rails 29.6 / -29.6 V idle,
  26.2 / -26.4 V at clipping with 0.6 V of 120 Hz ripple.
- **The pan, refitted with the amp and speakers in** (`suitcase_study.py --circuit
  rhodes_suitcase_100w`): 3.835 Hz, +-6.76 dB, shape error **1.18 dB** (the preamp alone:
  3.83 Hz, +-6.75, 1.21): the amp and speakers don't move it.
- **The app's device** `rhodes_suitcase` plays the whole instrument now (the preamp-only
  circuit stays for the study). Live: speakers without their readouts (each channel's front
  speaker's terminal voltage, full scale 14 V), draft-2x, **five threads** (`panel::Device::
  partition`: the preamp with the harp | the speakers | each channel's output op-amp with its
  power amp | the mains supply). The cuts that held: at the output op-amps' inverting inputs
  (the later partition is a near virtual ground: stable at a sample's lag), at the amps'
  outputs (a stiff driver into 16 ohm) and across the rails; **a cut at the amp's own input
  diverged** (a 5K node behind a 100 ohm source: the lag's loop gain is Z / R = 54), found
  with `load_profile --partition`. Cost, `examples/load_profile` on a loud program through
  ACCESSORY IN (the amps near clipping, the worst case): one solve 13.9x real time (the
  preamp-only circuit played all keys at 72%), the supply split 8.0x, three amp threads 1.9x,
  with the speakers on their own threads 1.3x, then **Newton at (4e-3, 4e-2) V (the device's
  `newton`) 0.82-0.86x, 22% of blocks over 1.0** (the buffer absorbs it; the 1176's was 0.83x /
  10%). The tolerance costs accuracy: the amp's waveform against Newton 1e-5 is -70 dB at the
  draft's (1e-3, 1e-2), **-59 to -64 dB at (3e-3, 3e-2) and at the chosen (4e-3, 4e-2)** (a
  step looser, (1e-2, 5e-2), -36 to -55 dB: audibly noisy, rejected); the THD reads the same
  to 0.01% at all of them.
- **Every key struck and re-struck** (the review, 2026-11-07, with the user back: `play.rs
  --device rhodes_suitcase --strike-all 127 --restrike 3 --mute`; `--mute` is new, everything
  computes and the monitor's gain after the device is -300 dB, so nothing sounds; the stats
  line's `out` / `gain` are the circuit's own, before the monitor): **not clean. 6-62
  dropouts in 12-15 s, worst block 150-210%** (the preamp-only device in the same session: 0
  dropouts, worst 113-115%). Measured per thread (temporary instrumentation of circuitsim's
  `run_part`, not committed): each amp thread is busy **5.2-6.3 us a sample**, the speakers'
  2.0-2.4, the supply 1.2-1.6, against 10.4 us at 96 kHz; their maxima of 0.1-2.7 ms are the
  OS descheduling a spinning thread. So the compute fits; what drops out is scheduling: in
  this test, five partition threads in lockstep every sample, the harp's three voice workers
  and the audio thread on 8 cores (16 logical), with another session's pytest and
  explorer.exe each holding a core. Tried and worse: the speakers in the first partition
  (223%), the supply folded into amp B's group (129%), each channel's speakers on its amp's
  thread (113-150 dropouts against 12-62 for five threads, alternated three times); a 50 ms
  buffer instead of 30 doesn't help. The five threads stay. The runs vary 5x with what else
  runs on the desktop: CLAUDE.md's "Benchmarking on this desktop" applies.
- **Against the reference recording, redone** (`scripts/suitcase_bands.py`: each band's power
  re 200-2000 Hz, both channels; the recording is the preamp's output, so the fair row for
  the preamp is `pre_a`; the whole Suitcase adds the P12R's response at 1 m):

  | Band (Hz) | 80-200 | 200-500 | 500-1k | 1-2k | 2-4k | 4-8k | 8-16k |
  |---|---|---|---|---|---|---|---|
  | Recording | -12.6 | -0.7 | -8.6 | -18.1 | -36.6 | -46.7 | -66.7 |
  | The harp's EMF alone (MK1_HARP@2) | -10.6 | -1.8 | -5.2 | -14.5 | -29.4 | -54.1 | -77.2 |
  | Preamp output (the 2026-11-07 table) | -12.5 | -1.8 | -5.1 | -14.8 | -30.8 | -58.2 | -80.9 |
  | The whole Suitcase, 1 m in front (draft) | -11.4 | -3.9 | -4.0 | -7.2 | -17.5 | -52.1 | -93.4 |

  The last row is not comparable with the recording (which is the preamp's output, before any
  speaker): it shows what the speakers add to the preamp's row, **+7.6 dB at 1-2 kHz, +13.3 dB at
  2-4 kHz, +6 dB at 4-8 kHz and -12.5 dB at 8-16 kHz** (the P12R stand-in's rising
  pressure response and its roll-off above ~5 kHz; draft quality: the production render of
  the same demo, was stopped after 95 minutes unfinished, over 280x real
  time for the whole instrument at 192 kHz, so the table's last row and the note set are at
  draft, ~25x). The preamp row is the same demo as before (the table's 8-16k entry read -82.9 with a coarser
  window). The 4-8 kHz deficit is 7 dB at the harp and 11.5 dB at the preamp's output (A1A's
  C2 120 pF takes ~4 dB there, fig11-1's own value); 8-16 kHz 10.5 and 14 dB.
- **The listening set** (`scripts/rhodes_suitcase_notes.py` -> `reports/rhodes/suitcase_notes/`,
  git-ignored): jRhodes3d's notes F1, E2, D3, C4, B4, A5, G6 at velocities 30 / 75 / 120, one
  stereo WAV each (the vibrato on, the pressure 1 m in front of the front speakers, 0 dBFS =
  25 Pa), 21 files, the peaks 0.005-0.17 of full scale (0.1-4.2 Pa; the loudest single note is far from
  the amp's clipping, chords reach ~7 Pa), 24 dB from velocity 30 to 120; at draft (Newton
  1e-3), `--quality production` renders the same set more than 10x slower.

**Next:**
1. The user listens: Play's Rhodes Suitcase (the whole instrument now: preamp, amp, speakers),
   `reports/rhodes/renders/suitcase_100w_demo_draft.wav`, the single-note set.
2. **The user's calls, with numbers:**
   - **The vibrato's last dB and the creep's curve.** Against the recording: depth +-6.76 dB
     at full INTENSITY against +-7.82 (0.9-1.0 dB, 13% short; the peak to peak is right, 17.96
     dB against 17.45, so the shape spends it differently), shape error 1.18 dB; our 3rd
     harmonic 0.28 of the fundamental against the recording's 0.17 (flatter tops, a creep that
     bends upward where the recording's is straight), the 5th 0.12 against 0.06. Cells tried:
     VTL5C1 1.51 dB, VTL5C2 1.21, the board revision's 1K LED resistors 2.32 (the same shape
     error with the amp in: 1.18). Options: (a) a cell between the two types (a hand-fitted
     time constant: the part, Rhodes P/N 013556, is unidentified, so any such cell is a fit to
     this one recording, not to a sheet); (b) the cell's second state (trap filling: the
     VTL5C1's dim turn-on's first milliseconds are missed for the same reason); (c) leave it:
     1.18 dB of rms shape error on a gesture most players won't A/B against this recording.
     My recommendation: (c), then (a) if the pan sounds too square when played.
   - **The 4-16 kHz deficit** (7 dB / 10.5 dB at the harp, 11.5 / 14 at the preamp's output).
     It starts at the harp, not the amp: the attack's mechanical noise (the hammer's tick, not
     modelled: RH5's contact with a felt, or a measured transient) and the pickup's higher
     harmonics (a narrower field than the 3D section's, RH5). The preamp's own C2 is drawn
     from the schematic. An EQ would hide it (the user's rule: not a listening aid), so: build
     the hammer's tick into the contact (the first candidate, one parameter per key's
     hardness) or leave it.
   - **The cabinet's back.** The speakers are an open baffle in the model; if the 48 x 27 x 14 in
     section is sealed, each of the four drivers (~74 L if the box is open inside) sees a
     compliance: the P12R's Vas is ~52 L (Sd 0.0491 m2, Cms 0.157 mm/N), so its resonance moves
     from 80 Hz to ~104 Hz and the bass response changes shape. Needs a cabinet volume in the
     speaker macro (a model change: its radiation is the front wave plus the back wave round
     the edges today). No source says open or closed yet.
   - **Provisional values worth sourcing first** (the audibility order, my estimate): the
     speakers (the maker's drivers: a measured response would replace the P12R stand-in; the
     biggest change to the sound), T1's secondary and resistance (the sag at full power: ours
     ~3.5 V of rail at clipping), the bias current (25 mA, no published setting), the RCA29B /
     RCA30B model (the RCA sheet wasn't retrievable; a 1966-69 RCA Transistor Manual has it).
3. The power amp's step response and its high-frequency stability against the real 2N5784's
   fT of 1-4 MHz: the model has no transit time, so it can't say (the amp is clean in the
   model; the sheet's loop would be the check if a bench measurement turned up).
4. **The live device's worst case (the user's call):** every key at 127 re-struck every 3 s
   drops out (above). Options: (a) keep it: a stress test far past playing (all 73 keys
   ringing at ff, the amps clipping), and the per-thread compute fits; (b) offer the
   preamp-only circuit as a second Play device ("Suitcase preamp", 0 dropouts in the same
   test) beside the whole instrument, the whole one for takes and renders; (c) engine work:
   the partition threads spin in lockstep every sample, so a thread the OS deschedules for a
   millisecond stalls all of them; a looser coupling (a block of lag on the rails, where only
   slow sag crosses) would let the supply and speakers run ahead (TAPE_SPEED_PLAN.md P2's
   "decoupled by a block of lag" is the same idea). My recommendation: (b) now, (c) if the
   whole instrument should be the one played.
5. **Renders' cost (the user's call).** At production (one solve, 0.2 s of a tone, no
   settle): the preamp alone 4x real time, the whole Suitcase **30x with the speakers as
   loads (terminal voltages) and 158x with the two pressure readouts** (the demo with its 1 s
   settle measured 455x; the readouts' delay lines for the back wave are most of the states,
   and DK's cost grows with their square; halving the drivers with `series: 2` didn't change
   that). The readout draws no current from the circuit (every coupling is a Vccs), so it is
   exactly separable: simulate with the coil's radiating nodes probed, then run the readout
   network as a linear filter on them afterwards, the same discretization. Option: build that
   (a render option in both engines' callers, `parts.speaker_readout` as the filter; it would
   speed up the 5E3's renders the same way); without it, a 3-minute song through the whole
   Suitcase takes ~8 h at production, ~1.3 h at draft.

**Options (model changes: the user's call, numbers before renders change).**
1. **The pickup's field and the hammer's speed** (the biggest win): fit the velocity law's
   scale and the pickup's width (provisional magnet width, wedge, the tine's 2D slab) to
   jRhodes' layer patterns key by key; then RH5's 3D solve replaces the stand-in scale.
2. **The decays:** refit the tine's loss to these two pianos' Q instead of (or beside)
   Shear's; check that the damper fit still holds.
3. **The bell mode:** the spring's position or mass (provisional) so the second mode lands
   where jRhodes puts it, and its loss (constant loss factor instead of stiffness
   proportional) so it rings 0.4 s and more.
4. **Pitch with swing (bass):** the magnet's pull as a force (RH5).

## Touch (2026-11-04): a keyboard's sensitivity

The user had to hammer the keys to get the full sound. The velocity law spans 30 dB of hammer
speed from 127 down to 1, linear in dB (velocity 64 strikes at -15 dB, 0.12 m/s), and a
normal touch on a controller sends roughly 40-90. The loud Rhodes sound is the bark (a big
tine swing through the pickup's nonlinear field, the harder contact, the 5E3 driven), so it
needs the hammer's speed: output gain can't give it. The user's choices: the touch at the
MIDI input (A: the player's and the controller's, not a part of the instrument), a take
keeping the velocities it played, two sliders.

- **`midi::Touch`**: Sensitivity (`curve`, 0-1) and Range (`range_db`: how far below full
  velocity 1 plays, on a device whose law spans `native_db`). With x the velocity sent from 0
  to 1, a key plays `range_db` x (1 - x)^p under full, p from 1 (the law's own line) to 5: an
  ease-out, the middle velocities up and the curve flattening into full without a corner
  (the user's ask after a first version whose `full_at` knee was abrupt). At 100% on the
  harp, velocity 64 plays -0.9 dB, 40 -4.7 dB (the line: -15, -20.7). At the defaults (0%,
  the device's own range) every velocity is unchanged. Without a `native_db` only the curve
  acts, on the velocity: the sampler, the test oscillator, and tube_synth, whose Range stays
  the Play view's velocity range (applied at its gate, kept in a take's `Playing`).
- **Where it acts:** `Keys::message` remaps a key down's velocity as it arrives, so the
  harp, the Performer, a take's events, the piano roll, the sampler and the proxy all get the
  velocity heard (a later change of touch leaves a take alone). `Keys::last_sent` keeps the
  velocity as sent.
- **The harp's own law** is read from its build (`live::key_velocity_span_db`: the
  component's `velocity.range_db`, 30 dB) when the keys start; the Range slider spans it.
- **The Play view** (MIDI keyboard and the sampler): Sensitivity, Range (the harp's, with
  "own" back to its 30 dB; tube_synth's velocity range), a curve of the level per velocity
  sent (the keyboard's own faint, the touch's in the accent) with the last key on it. Saved
  per keyboard by its port's name in `app.json` (`prefs::KeyTouch`).
- Tests: `midi`'s (identity at the defaults, the curve's values and smoothness, range,
  monotonic, the keys' remap),
  `prefs`' round trip, `tests/live.rs` (the Rhodes' span 30 dB, none for the EQP-1A).

**Open:** the user tries it on the Rhodes.

## Status (2026-11-04): RH2 built, through the 5E3; the user listens

The whole 73-key harp in Python, played from MIDI through the Stage's controls into the 5E3
(the user's decisions below). Tests: `tests/test_rhodes.py`, `tests/test_rhodes_harp.py`
(21, ~30 s).

- **The keys** (`spec.py`): all 73 fitted (`scripts/rhodes_fit_keys.py`, ~1 min on 6
  workers; cached per key in `cache/rhodes/keys_*`, keyed by mk1.yaml, the tine lengths,
  spec.py and beam.py). Two changes from RH1 to tune all 73: the chart's key 54 reads 2.2 mm
  longer than key 55 (every other step ~1 mm shorter), read as a drafting irregularity and
  interpolated (`tine.chart_outliers`); and the tine's root, now 3.0 mm over 7 mm, so every
  key is 4-19% above its note bare (the least key 57: the chart's ~+-0.3 mm reading error is
  ~1.4% there). The spring's fit scans upward (a 50 g spring made another mode the tine's).
- **The damper and pedal**: the felt as a dashpot at half the tine (provisional), fitted per
  key so a released fundamental dies in 0.15 s (provisional; released Q 2.8 at E1 to 180 at
  E7); a key's damped and free systems swap with the physical state carried across.
- **The voice** (`harp.py`): one key over a timeline: free motion in closed form between
  events (the modes' rotations tabulated once, the arc's quadratic forms taken to the
  modes), a strike from wherever the tine is (`key.contact`, now reusable), sleep under 1 nm.
  3.7x slower than real time for the demo's 20 keys in Python (the reference; RH3's Rust is
  the live one).
- **The wiring**: the manual's Fig. 10-4 (later pianos; Fig. 10-3 the original, a quarter
  of the output): pickups 1-4 a group, then threes, 24 groups in series; the open-circuit EMF
  is each pickup's EMF over its group's size, summed (all in phase: provisional).
- **The Stage into the 5E3**: `config/circuits/rhodes_stage_5e3.yaml`, GENERATED by
  `scripts/derive_rhodes_5e3.py` (`--check`) from `fender_5e3.yaml`: `in` the harp's EMF,
  then its coils (1425 ohm: 180 ohm per coil; 0.327 H from the manual's ~2500 ohm output
  impedance, read at 1 kHz, Wheeler's formula on the provisional bobbin agreeing within 20%),
  the 1973-on Stage controls (.047 uF and a 50K reverse-taper BASS across it into the 10K
  audio VOLUME: a printed Fender schematic as quoted on the EP Forum), a cable, the 5E3's
  jack. One coupled netlist: the pickups drive it one way.
- **Velocity**: MIDI velocity to hammer speed over 30 dB (provisional), velocity 127 set so
  E1 swings 9.5 mm (provisional: the bass tines' swing nearly reaching their bars); 0.69 m/s.
- **MIDI**: `midi.py` (no dependency: notes, CC 64, tempo). `scripts/rhodes_render.py
  (--midi FILE | --demo) [--quality] [--set ...]` -> `reports/rhodes/renders/` (the amp's
  WAV at 50 Pa full scale, the harp's straight at 0.5 V): the demo (18.3 s) renders in ~3.5
  min (the harp 67 s, the 5E3 at production 130 s, 7.1x real time).
- **The survey** (`scripts/rhodes_keyboard_survey.py` -> `reports/rhodes/keyboard/`): every
  key within 0.002 cent; the fundamental's Q on Shear's points but keys 46-49, where the
  balanced bar alone sits 19-30% above the note and the mount's rubber damps them more
  (Q 22% / 9% / 4% under at keys 46 / 47 / 49); the bar's mode on its mount along Muenster &
  Pfeifle's line; the contact 8-10 ms in the bass to 2-3 ms in the top, stepping at the
  hammer tips' hardness changes; the swing at 127 from 9.5 mm (E1) to 0.5 mm (E7).

**Open (RH2):** the user's listening; the harp's absolute level (36 mV peak in the demo: the
2D pickup section's, RH5's 3D solve sets it; the 5E3's volume at 0.5 gives a quiet render);
keys 18-30 hold the hammer longer at velocity 127 than at 64 (up to 12.9 ms: the soft tips
and the whipping bass tines); keys 46-49's Q; every velocity, damper and wiring-polarity
value above marked provisional.

## Status (2026-11-04): RH1 built; the user: "sounding pretty good"

One key, offline in Python: `varimu/rhodes/` (outside the render cache key, like the drums
and the phono), `config/rhodes/mk1.yaml`, `tests/test_rhodes.py` (14, ~35 s),
`scripts/rhodes_key_study.py` -> `reports/rhodes/key/` (plots, summary.json; WAVs of the
open-circuit EMF in audio/, 0 dBFS = 0.5 V: per key at 0.5 / 1 / 2 / 3 m/s, `scale.wav`,
`voicing.wav`; ~5 min). Sources: `data/schematics/rhodes/README.md`.

**Sources found.** The 1979 service manual (web, OCR'd): the tine cutting chart (Fig. 6-2,
full size: digitized by `scripts/digitize_rhodes_tines.py` ->
`data/datasheets/rhodes_tine_lengths.csv`, 156.8 mm at keys 1-8 to 18.5 mm at key 88,
matching Shear's 157 / 18 mm), the hammer tips' hardness and height per key, the striking
line, the pickup gap, voicing, tuning. Shear 2011 (MS thesis): tines 1.5 mm, the
fundamental's Q per note, the voicing finding, the 88's lowest seven bare. Muenster &
Pfeifle (ISMA 2014): the hammer's contact (6.42 ms), the bar's own resonance far below the
note (nine keys), the tine sinusoidal after ~10-14 ms. Not found: the bars' dimensions, the
tine root's taper, spring masses, hammer mass, the pickup's magnet and coil, grommets.

**The model.**
- `beam.py`: the tone bar assembly as Euler-Bernoulli finite elements in the vertical
  plane: the tine (tapered root, then 1.5 mm), its spring as a short sleeve of mass, the bar,
  the block (a rigid body) on two grommets. Losses: the grommets' rubber, the steel, the
  tine's own (its root, air), each stiffness proportional (the bell partials die fast).
- `spec.py` builds key n with one fit per unknown, each to a different source: the spring's
  mass tunes the note (equal temperament, A440); the bar's length **balances the fork** (the
  tine's fundamental storing least energy in the grommets): that alone puts the bar,
  clamped, within 1-5% of its note on six of seven keys checked (the manual's "alike only
  in pitch", not imposed; key 49 +28%); the grommets' stiffness puts the struck bar's
  lowest mode on its mount at Muenster & Pfeifle's resonance (their line in log f; outside
  their keys 19-75 their end's ratio to the note); the tine's own loss sets the
  fundamental's exact damped Q to Shear's (the grommets can't: it took ~200x critical
  damping in the bass). The tine's root (2.7 mm tapering over 6 mm) is calibrated so every
  key from 8 up is 2-15% above its note bare (a uniform 1.5 mm tine is 26% flat at key 88,
  and the spring only lowers). Keys 1-7 (no bar) sit on a stiff mount (provisional).
- `pickup.py`: the pickup's flux by a 2D planar magnetostatic FE solve (A_z, bilinear
  rectangles; a chisel-ended ferrite magnet, the coil's two sides, the tine's end 1/16 in
  away): a map over the tine's height (whole cells of d / 16, so the geometry is exact at
  every sample; +-18 mm) and its pull-back from the gap, splined; ~2 min with 6 workers,
  cached in `cache/rhodes/`. The absolute level is the 2D section's (depth = the magnet's
  width): RH5's 3D solve sets it.
- `key.py`: a strike. Live tier: the damped system's complex modes below 20 kHz
  (non-proportional damping kept: the diagonal approximation was off by -11 dB near the
  bar's mode); reference: the full system in physical coordinates at 4x the rate. The
  Hunt-Crossley contact is solved inside each step with the instantaneous response folded
  in; after 30 ms the motion continues in closed form. The EMF is -(dPhi/dy y' + dPhi/ddg
  dg') with dg the tine's arc (its shortening), at 4x and decimated.

**Results** (`reports/rhodes/key/`, keys 8-88):
- pitch: within 0.1 cent of the note (the tuning);
- Q: Shear's (the fit; the tip's decay reads 7-37% high at keys 80 / 88, where it beats);
- the contact: 6.0-6.9 ms in the middle (keys 31-35) against Muenster & Pfeifle's 6.42 ms
  average (not fitted), 12 ms at key 19, 1.4-2.8 ms in the top two octaves; key 8 strikes
  twice at 1 m/s and up (the tine's whip in the bass, the manual's ch.4);
- the voicing (G3, Shear's 196 Hz figure; not fitted): centred, the second harmonic
  dominates and the fundamental cancels (-127 dB: the section is symmetric); 1 mm off,
  the fundamental is 6.5 dB over the second, Shear's finding;
- the bark: the second harmonic over the fundamental rises with the strike everywhere
  (G3: -4.4 dB at 0.5 m/s to +13.3 dB at 3 m/s);
- live vs reference: -50 to -67 dB from key 8 to 43, -32 to -44 dB from key 55 up (their
  1.4-2.8 ms contacts, stepped at 4x against 16x).

**Open.**
- **The hammer's speed isn't calibrated:** at 2-3 m/s the bass tines swing 16-40 mm (the bar
  is ~9.5 mm above; nothing stops them, and past +-18 mm the pickup map holds its edge), so
  1 m/s is already forte in the bass. A key velocity to hammer speed law (the action's
  ratio, a sourced hammer mass) is RH2's.
- Provisional values (mk1.yaml) to source: the bars' dimensions (patent 3,644,656 may give
  them), the pickup's magnet, coil and turns, the hammer's mass, the grommets.
- Left for RH5 as planned: the second polarization, the 3D pickup, the magnet's pull on the
  tine, the large-swing nonlinearity, the bar's twist.

## The target

- **The instrument:** a Fender Rhodes Mark I, the electric piano on Stevie Wonder's 1970s
  records. It is often associated with the **Suitcase** model and its stereo "vibrato" (a
  side-to-side pan) (provisional: model knowledge, to be checked against the songs the user
  picks).
- **Not the clavinet:** "Superstition" and "Higher Ground" are a Hohner Clavinet, a struck
  string read by magnetic pickups. Its structure is the same as this plan's (a modal
  resonator into a field-solved pickup into a passive network), so it could follow cheaply
  once this exists. Planned since 2026-11-06: [CLAVINET_PLAN.md](CLAVINET_PLAN.md).
- **Stage and Suitcase share the action, the hammers, the tines and the pickups (the
  harp).** Only the amp differs:
  - **The Stage** is passive and plugs into an amp. The project's tube amps (the 5E3 and the
    P12R speaker) are there, so it can be built now.
  - **The Suitcase** has a transistor preamp, vibrato and power amp (the Peterson
    electronics; provisional: model knowledge). It needs the **BJT model**, a shared
    prerequisite that DRUM_PLAN.md and MIC_ROOM_PLAN.md also list.

## Why many notes at once are cheap

A tube synth voice is expensive because it is a nonlinear circuit: `tube_synth` takes ~62%
of the desktop for one voice, which is why MIDI_TAKES_PLAN.md plans four voices behind a
proxy. In a Rhodes, everything that happens per key is mechanical and almost linear. The
nonlinear parts are either brief or memoryless:

| Per key | Physics | Live cost |
|---|---|---|
| Tine + tonebar | An uneven tuning fork: a few beam modes each, the tuning spring as a point mass, in both planes | ~8-12 two-pole resonators |
| Hammer | A neoprene tip, a nonlinear contact with loss | Only during the ~1-3 ms of a strike |
| Damper, grommets | Extra damping on the modes when the key comes up; the mounts' loss | Free (a coefficient change) |
| Pickup | The flux through the coil, a nonlinear function of the tine tip's position | One table lookup per sample |

- **An estimate, to be measured:** 88 keys x ~10 modes x 96 kHz is ~85 M resonator updates
  a second. With SIMD that is a few percent of one core, even with the sustain pedal down
  and every key ringing. Keys that have died away sleep (below a threshold of their own
  energy).
- **Everything after the pickups is shared:** coils in series and parallel, the volume and
  tone controls, the cable, then the amp. That costs the same for one note or 88.
- **So the amp is the bottleneck, not the number of notes.** The 5E3 with its speaker
  readout runs at 1.61x real time at draft-2x, and how Play handles that is still open
  (COMPONENT_EDITOR_PLAN.md, C3's status). Live, the amp would run without the speaker
  (0.48x), and the speaker would come in at production. No proxy is needed: unlike the
  synth's, the live model is the real one, reduced.

## Two tiers from the same physics

Like the tape (the reduced tape live, the literal machine for prints), not like the synth's
proxy: the live tier is the same physics reduced, and the production tier is the reference
it is checked against. Takes follow MIDI_TAKES_PLAN.md: play on the draft, keep the notes,
velocity and pedal as events, render the take at production behind.

| Part | Live (draft) | Production (offline) |
|---|---|---|
| Tine + tonebar | Modes computed once from the geometry, fixed damping per mode | A time-domain beam (finite differences or FEM) of tine and tonebar in both planes: the clamp's coupling between them, the spring as a mass on the rod, the large-swing nonlinearity if it measures audible |
| Hammer | A fitted nonlinear contact, folded into the medium's port | Viscoelastic neoprene (rate dependent: velocity changes the contact time and so the brightness); the action's mechanics from key to hammer |
| Pickup | A precomputed table of flux against tine position | A finer field solve (3D), including the magnet's pull on the tine as a nonlinear force (pitch and sustain then depend on the voicing) |
| Harp | Keys independent | Sympathetic coupling between tines through the rail; magnetic crosstalk between neighbouring pickups |
| Bank's rate | Oversampled (2x-4x), behind M1's FIR decimator | Higher oversampling |
| Amp | Draft quality, no speaker | Production quality, with the speaker and cabinet; a room later (MIC_ROOM_PLAN.md) |

The production tier is also the check: each key's partials and decays from the live modes
against the time-domain beam, and the pickup table's harmonics against the full solve, with
measured margins, as the tape's reduction is checked against the full stream.

## The model, part by part

### Action and hammer

- Key velocity to hammer velocity through the action. The service manual's adjustments
  (escapement, strike line, hammer height; provisional: model knowledge, to be checked) are
  the physical values.
- **Neoprene tips graded in hardness across the keyboard** (provisional: model knowledge;
  the service manual should give it). A nonlinear contact with loss (Hunt-Crossley type) at
  first, fitted to whatever can be sourced.
- **The contact can't be a sample late.** The force depends on the tine's displacement now,
  so the tine's instantaneous response at the strike point is folded into the port and the
  contact's small Newton sees it (INSTRUMENT_PLAN.md's "Contacts inside the solve", shared
  with the drums' beaters).

### Tine, tuning spring and tonebar

- The tine is a steel rod clamped at one end. A uniform clamped-free beam's second mode
  sits at 6.27x its first (the beam's eigenvalues 1.875^2 and 4.694^2). The tuning spring,
  a mass wound onto the rod, moves that ratio. This inharmonic partial is part of the
  attack's bell.
- The tonebar is the fork's other, heavier arm, tuned near the tine's fundamental.
  Coupled through the clamp, the pair trade energy, which sets the sustain.
- **Geometry from the service manual:** tine lengths and diameters, spring positions,
  tonebar dimensions per key. Steel's and brass's constants are published. The modes are
  computed offline into a component version, like `EMT140@1`.
- **Losses:** the clamp, the grommets (the rubber mounts) and air. They start provisional
  and genome-bounded until a source or a published decay measurement replaces them.

### Damper

- Felt pressed onto the tine when the key comes up: extra damping on the modes and a brief
  contact. The sustain pedal (MIDI CC 64) lifts the damper rail.
- The production tier can model the felt's contact; the draft changes the damping.

### Pickup (the character)

- The tine tip vibrates in front of a magnet's pole with a coil around it. The flux through
  the coil depends nonlinearly on the tip's position, and the EMF is the coil's turns times
  dPhi/dx times the tip's velocity.
- **The tine's offset from the pole (the voicing) sets the balance of even and odd
  harmonics:** from mellow to the "bark" of hard playing. That offset and the distance are
  the service manual's voicing adjustments.
- **The field:** a 2D cross-section first (the tip as a permeable cylinder moving past the
  pole), on varimu-components' FEM (`varimu-components fem`, extended from linear windings
  to a permanent magnet and a permeable moving part). Then a 3D solve as the production
  tier's map and the check on the 2D one.
- **The magnet's static pull** on the tine acts as a negative spring: it lowers the pitch a
  little and depends on the voicing. The draft folds it into the tine's stiffness at rest;
  the production tier carries it as a force.
- **Back-reaction:** the force of the coil's current on the tine is negligible (a
  high-impedance load), so the pickup drives the circuit one way. Like the plate's
  exciter-to-pickup path, this stays one coupled simulation: the medium is stepped inside
  the circuit's run (`Transient::step_media`), not chained after it.

### The harp network

- Pickups in series and parallel groups (the wiring from the service manual), each a coil's
  inductance and resistance. The Stage's volume and bass controls, then the cable's
  capacitance. Together they form a resonance that shapes the top end.
- Linear and small: a few elements in the circuit's IR, driven by the medium's EMFs.

### The amp

- **Stage:** into a tube amp. The 5E3 is there now. A blackface Twin Reverb, with its
  optical tremolo (a neon lamp and an LDR), is a candidate; it would need a photoresistor
  model (CdS: slow, its attack and release asymmetric).
- **Suitcase:** the Peterson preamp, the stereo vibrato and the power amp, after the BJT
  model. Its speakers and cabinet are another speaker component like `P12R@1`.

### The side-to-side pan (future, 2026-11-04; nothing built)

The user asked about the Rhodes' "rotary" left-right pan. The Stage (built) has none: it is
passive. The pan is the **Suitcase's "Vibrato"**, despite its name a stereo tremolo (no pitch
change): an oscillator turns the left side up as the right goes down and back, with speed
and depth controls (provisional: model knowledge, to be checked against the Suitcase's
schematics and the songs the user picks). A **rotary** is a Leslie, a different sound (a
spinning horn and drum: Doppler pitch wobble and a tone that changes as the horn turns, as
well as movement), mostly the Hammond's, sometimes a Rhodes'. Three ways, the user's to pick
when this is picked up:

1. **The Suitcase itself** (the faithful one): the Peterson preamp, vibrato and power amp,
   two speakers. Waits on the BJT model (shared with DRUM_PLAN.md and MIC_ROOM_PLAN.md).
2. **A tube stereo panner of our own** (recommended first, the Suitcase replacing it later):
   a chain end after the 5E3 (`panel::CHAIN_ENDS`; stereo chain ends exist since the 351-2's
   ping-pong, a circuit's `out_r` probe): an oscillator like tube_synth's lamp-held Wien
   bridge (`LAMP327@1`) driving two tube VCAs in antiphase (tube_synth's 6386 VCA), SPEED
   and DEPTH. An invented device, not the Rhodes' own.
3. **A Leslie from physics**: the rotating horn and drum, Doppler and directivity, heard at a
   mic or listening position (MIC_ROOM_PLAN.md's room); good for any instrument, the largest
   (INSTRUMENT_PLAN.md, "Others worth noting").

## How it would fit the code (a proposal)

- **The reference:** `varimu/rhodes/` in Python (outside the render cache key, like
  `varimu/drums/` and `varimu/phono/`): the beam models, the contact, the pickup map. Its
  circuitsim port is a medium beside the plate and the tape (`media.rs`).
- **Components:** the harp as a component (kind e.g. `ep_harp`: per-key geometry, modes,
  the pickup map), compiled offline. Its versions are immutable and pinned like every
  component, so a revoiced harp is a new version.
- **Circuits:** a part (e.g. `harp: [out_plus, out_minus]`) in both builders, and
  `config/circuits/rhodes_stage.yaml` (the harp, the Stage's controls, the cable), chained
  into an amp or composed with one.
- **Notes into the medium:** 88 keys with velocity and a pedal are events, not the synth's
  control-input voltages. They need a new feed in varimu-app (beside `Feed::Key` and
  `Feed::Pressure`) carrying note-on velocity, note-off and the pedal into the medium at
  the sample they land.
- **SPICE:** holds the harp's output at 0 V, as for the plate. The medium's agreement is
  Python against Rust.

## Condition dials (realistic first, then bend)

Each one is a physical condition, realistic by default:
- the voicing (the tine's offset from the pickup): mellow to all bark;
- the pickup's distance;
- neoprene hardened with age (brighter, harder attacks);
- hardened grommets;
- worn damper felts (notes that don't stop cleanly);
- tuning springs moved (out of tune, the bell partial shifted);
- a weakened magnet;
- per-instrument variation through seeded tolerance draws (every Rhodes a different one).

## Proposed milestones (a recommendation, not decided)

1. **RH1: one key, offline in Python.** Tine, spring and tonebar from service-manual
   dimensions; the hammer contact; the 2D pickup map. The time-domain beam as the
   reference. Heard straight out, without an amp. Done when: the key's partials match the
   service manual's figures or published measurements, and moving the pickup offset moves
   the even / odd balance as published.
2. **RH2: the harp in Python.** All 73 keys, the damper and pedal, the harp network, a key
   velocity to hammer speed law, into the 5E3. Done when: the keyboard's pitch and decay
   across the range are plausible against published measurements, and a played MIDI file
   renders through the 5E3.
3. **RH3: the harp in circuitsim.** The medium in Rust, matching the Python reference; the
   harp part in both builders; the note feed in varimu-app. Done when: Rust matches Python
   within a tested bound, and it plays from a MIDI keyboard in real time with every key
   ringing (the load measured with `examples/play.rs`).
4. **RH4: the amp.** A Stage into the 5E3 (live without its speaker readout, production
   with it), or the Suitcase once the BJT model exists. Done when: it plays live through the
   amp, and the user has heard it against the songs they chose.
5. **RH5: the production tier.** The time-domain beams, the 3D pickup map with the magnet's
   force, sympathetic coupling, the speaker, the takes rendered behind
   (MIDI_TAKES_PLAN.md). Done when: the draft is checked against it with measured margins.
6. **RH6: the condition dials.**

## Sources to find

- The Rhodes service manual (tine, spring and tonebar dimensions; hammer tips; voicing,
  escapement and strike-line adjustments; the harp's wiring).
- Published Rhodes pickup and tine studies. Pfeifle and Münster published on the Rhodes
  around 2014-2017 (provisional: from memory; check titles and venues before citing).
- The Suitcase's schematics (the Peterson preamp, vibrato and power amp), for the
  Suitcase.
- Fletcher and Rossing on beams and tuning forks; Bilbao (2009) on finite-difference beams
  and contacts.

## Decisions (the user's, 2026-11-04)

- **The full plan in order** (RH2 before RH3), not a shortcut to the app.
- **73 keys** (keys 8-80 of the 88's numbering, E1-E7).
- **Out of the 5E3 from the start:** a Stage into the 5E3 (`fender_5e3`) from RH2's renders
  on; straight out of the pickup stays a check, not the product.
- **The amp's speaker live (RH3):** live without the speaker's readout (Play hears the
  terminal voltage; the speaker stays as the load, its pressure at production), as RH4
  proposed. The one-way partition can still come later for the 5E3 itself (C3).

## Open decisions (the user's)

- **Which songs it should sound like.**
- **Where the track goes** relative to the synth, the tape and echoes, the sidechain, the
  drums, the mics and rooms (INSTRUMENT_PLAN.md proposes the bell before it).
- **How deep the production tier goes** (finite differences or FEM for the beams; whether
  it moves to the GPU).
