# The virtual head: binaural recording from simulated ears

The user's idea (2026-11-22): in the Room view, a special stereo "mic" that is a human head,
an ear on each side, rendered to a stereo track (left ear hard left, right ear hard right),
for headphones; and the physics and shape of the ear simulated, so the cues the brain uses
to place sounds (including behind you) come out of it. Placed in the middle of a room with
sounds all around, does each sound seem to come from where it is?

The user's calls: the most physical option, **HRTFs simulated from a head's 3D shape** (not
a measured dataset, not a sphere), treated as a **spike**; renders to listen to and
**variations to pick from** ("which of these sounds behind me?").

## What limits it (said before starting)

- **Ears are personal.** Front / back and up / down come mostly from the pinna's spectral
  cues, and they are learned for one's own ears. Through someone else's ears, listeners
  typically reverse 20-40% of front / back judgments and lose elevation; a frontal source
  often lands behind or inside the head. Remedies: pick the head that works best for you
  (a listening test over many heads: B3), or your own ears (a scan: later).
- **No head movement.** In life a small turn of the head resolves front / back. A static
  render can't; head tracking can (later, B6).
- **Headphones colour it.** The renders are diffuse-field equalized (as a recording dummy
  head is): neutral on headphones tuned near the diffuse field. HUTUBS has measured
  HD800S / HD650 responses if you use those.
- **The room helps.** Reflections and a decorrelated tail push sounds out of the head.

## How it works

**Reciprocity on the GPU.** The pressure at the blocked ear canal from a source far away in
direction u equals the pressure far away in direction u from a source at the ear. One
simulation per ear, a source at the ear and receivers on a sphere round the head, gives that
ear's response to every direction (and, by the spherical-harmonic extrapolation, every
distance: near-field HRTFs come with it).

- **The solver** (crates/roomsim `fdtd::head`, B1): the room wave solver's finite-volume
  scheme on a 1 mm grid of 811^3 = 533 M cells (the most one 2 GiB GPU buffer binds: cell
  codes one byte each, 9 bytes a cell), the head voxelized from its mesh as rigid cells, a
  sponge at the faces, ~12,000 pressure receivers on a Gauss grid at 18.5 cm. ~32 s per ear
  on the RTX 3080; an f64 CPU reference (`run_cpu`) and a test that they agree (-90 dB).
- **Gating instead of a perfect absorber.** A sponge layer reflected tenths of a dB at the
  top and several dB at the bottom of the band. So the grid is as big as fits and each
  receiver's record ends (raised cosine) before the first wave could come back from the
  faces, as a measurement in a room is gated.
- **The far field** (varimu/binaural/sphere.py): the records' spectra, a spherical-harmonic
  transform on the Gauss grid (separable: an FFT round each ring, then Gauss-Legendre; exact
  to the grid's order, kR + 8 = 76 at 22 kHz), extrapolated outward by spherical Hankel
  functions to any distance or to infinity.
- **Normalization as a measurement's**: each ear's field over the field of the same grid
  with no head and the source at the head's centre (one reference run, shared by every head:
  the receivers' radius is fixed). The grid's dispersion divides out.
- **Rooms** (varimu/binaural/room.py): the ears are two mics of the room engine whose table
  takes the whole arrival direction (`HeadEar.directional`; varimu/rooms/shoebox.py's
  `_entries`, capsules unchanged bit for bit): every image source, diffracted path and plane
  wave of the diffuse tail reaches each ear through its HRTF from its own direction; arrivals
  within 2 m get the near-field HRTF at their distance.

## Status (2026-11-22, the spike)

**B1, the solver, checked against the exact rigid sphere** (`varimu/binaural/analytic.py`,
the classic series; at the sphere's side, 1 mm):

| band | ear's side | far side (shadow) |
| --- | --- | --- |
| 0.2-6 kHz | <= 0.04-0.5 dB | 0.3 dB |
| 6-10 kHz | 0.11 dB rms | 1.05 dB rms |
| 10-14 kHz | 0.15 dB rms | 2.2 dB rms |
| 14-20 kHz | 0.29 dB rms | 3.8 dB rms (too loud) |

The staircase surface lets too much into the deep shadow at the top (the far ear, already
10-15 dB down). Cut cells (a conformal boundary) would fix it; not done.

**B2, against reality** (HUTUBS, data/hrtf/hutubs/README.md: 58 head meshes with the same
people's measured HRTFs; `scripts/binaural_validate.py` -> reports/binaural/validate/).
Spectral distance in ERB bands 0.2-16 kHz (equalized per band), ITD and ILD over the 440
measured directions. FABIAN (subject 1, a dummy head):

| ours vs | spectral | ITD | ILD |
| --- | --- | --- | --- |
| HUTUBS' BEM on the same mesh | 1.32 dB (<= 0.4 dB to 6 kHz) | 7.5 us | 1.6 dB |
| the measured HRTFs | 2.85 dB | 36 us | 3.4 dB |
| (HUTUBS' BEM vs measured) | 2.93 dB | 41 us | 3.3 dB |

So the simulation is as close to the real head as the published simulation is; the rest is
the mesh (no torso: the meshes are head and neck; the scan) and the measurement.

**All 58 heads** (`--subject all`, ~2.5 h on the 3080; `reports/binaural/validate/summary_all.json`),
medians over subjects:

| ours vs | spectral | ITD | ILD |
| --- | --- | --- | --- |
| the measured HRTFs | 4.27 dB | 59 us | 5.2 dB |
| HUTUBS' BEM on the same mesh | 1.42 dB | 7.3 us | 2.0 dB |

Per subject, HUTUBS' BEM is as far from the measurement as ours (within ~0.1 dB, checked on
pp1-pp10): the human scans are further from their measured heads than FABIAN's is, and that
is the scan (hair, the canal blocked differently, no torso), not the solver.

**Front / back cues per head** (`scripts/binaural_rank.py` -> `ranking.json`, `ranking.png`):
`variants.front_back_contrast` on our HRTFs against the same person's measured ones, r = 0.63
over 58 heads (medians 7.7 dB simulated, 7.2 measured). The simulation ranks heads roughly as
reality does. Strongest simulated: pp4 11.4 dB, pp69 10.6, pp77 10.2, pp81 10.0, pp8 9.8;
weakest: pp5 3.7, pp6 5.6, pp23 6.0; FABIAN (pp1) 6.4. The sphere has none (0).

**B3, listening** (`scripts/binaural_demo.py` -> reports/binaural/listen/<head>/, README
there): tours of positions, a source circling, front / back pairs; heads `sphere` (the
control: no ears, front and back identical), `pp1` (FABIAN simulated), `pp1_measured` (its
measured HRTFs: simulation against reality), and any simulated subject `pp<N>`.
`scripts/binaural_listen.py`: a blind front / back test, four directions (30 deg either side
of front and of back: the same ITD and ILD, only the ear tells them apart) per head in
random order, scored per head (data/judgments/binaural/).

**B4, rooms** (`scripts/binaural_room.py` -> reports/binaural/listen/rooms/): the noise tour
and "Did she mention my name"'s stems placed round the head (vocal front, guitar back-left,
harmonies behind, bass right) in the treated studio and the stone chapel.

**B5 started: variants** (`scripts/binaural_variants.py` -> `hutubs_<subj>-pinna<SSS>` heads,
`reports/binaural/validate/variants.json`): the pinnae scaled 0.8x / 1.3x about the canal
point on pp1, pp4 and pp5 (a 1.4x map folds space; 0.045 / 0.075 m radii). Front / back
contrast (dB, 4-16 kHz):

| head | 0.8x | 1x | 1.3x |
| --- | --- | --- | --- |
| pp1 (FABIAN) | 5.93 | 6.41 | 5.69 |
| pp4 (strongest) | 9.75 | 11.38 | 10.41 |
| pp5 (weakest) | 4.24 | 3.68 | 3.08 |

Scaling doesn't make the cue stronger on this measure: it moves the pinna's notches (bigger
ears lower), partly across the measure's fixed band; the measure is no perceptual model,
so the blind test decides (reports/binaural/LISTEN.md's "suggested round").

The user's pick after listening (2026-11-22): **pp4 with its ears 1.3x** (`pp4-pinna130`),
the default head from here on; fine-tuning later.

**B7 built (2026-11-22): the head in the Room view.**
- **The scene format** (varimu/rooms/scene.py's docstring): a mic's `head: NAME`
  (varimu/binaural/heads.py: `sphere`, `ppN`, `ppN-pinnaSSS`, `ppN_measured`; a head not
  cached is simulated on the GPU the first time) expands at load into the mics `<name>.L` /
  `.R`, panned hard, at its centre, facing its azimuth, upright. Each ear's table is
  `HeadEar` (the room engine's directional entries), and its chain is the ear's capsule:
  only pressure (fixed omni) chains (`omni_clean` by default: the 4134 in the blocked ear
  canal into the clean preamp). The responses' cache key hashes the head's HRTFs
  (`heads.digest`, `HeadEar.key_bytes`); capsules' keys are unchanged. render.json marks
  the ears (`head`, `head_model`, `ear`). A source within 0.2 m of the head's centre is
  refused (`HEAD_CLEAR_M`).
- **The app** (varimu_app::room `RoomMic::head`, `HEADS`, `Chain::pressure`; room_view.rs):
  "+ Head" under MICS (the default head and chain, facing the first source), drawn on the
  plan as a head seen from above (nose and ears); its panel has Head (the list), Ears' chain
  (omni chains only), Facing and "Face <source>"; no tilt, pan or surface. A render adds
  its ears as **one stereo track** (left ear left). The render runs `uv run --extra fast
  --extra binaural` (h5py for the measured heads).
- Checked: a source front-left of the head is 8.3 dB louder in the left ear in the treated
  studio, with the wave solver (500 Hz) within 0.4 dB of without; BALANCE works on heads.
  Tests: `tests/test_binaural.py` (the expansion, the pressure check), varimu-app's
  `room::tests::a_head_mic`. The app's panel wasn't driven by hand.

## Next (options, the user's)

- **B5 your head.** The batch's best head for you (B3's test over many heads), then
  variations of it: pinnae scaled (bigger ears), a torso (the shoulder reflection, an
  elevation cue the meshes lack: SONICOM's scans have one), your own ears from a phone scan.
- **B6 head tracking.** Render the room to the head's position as directional arrivals (or
  Ambisonics) and rotate live; a webcam or an IMU as the tracker; the chains as their linear
  stand-ins live (`chain_proxy`).
- **B7 the Room view.** Built (above).
- **B8 cut cells** (the far ear's top octave), and the solver at 0.75 mm in two buffers.
- Headphone compensation for the user's headphones (HUTUBS' HD800S / HD650 HpIRs).

## Commands

```sh
cargo test -p roomsim --release head            # the body solver: GPU vs f64, the sponge
uv run --extra fast --extra binaural pytest tests/test_binaural.py
uv run --extra fast --extra binaural python scripts/binaural_validate.py --subject pp1 [all]
uv run --extra fast --extra binaural python scripts/binaural_rank.py           # front / back cues, sim vs measured
uv run --extra fast --extra binaural python scripts/binaural_variants.py [--subjects pp1 pp4] [--scales 0.8 1.3]
uv run --extra binaural --extra listen python scripts/binaural_demo.py [--heads sphere pp1 pp1_measured pp<N> ...]
uv run --extra binaural --extra listen --with sounddevice python scripts/binaural_listen.py [--heads ...] [--stimulus noise]
uv run --extra fast --extra binaural --extra listen python scripts/binaural_room.py [--scenes band tour] [--rooms ...] [--heads pp1]
```

HRTF sets are cached in cache/binaural/heads/ (by mesh, grid and `hrtf.CODE_VERSION`), the
no-head reference in cache/binaural/reference/.
