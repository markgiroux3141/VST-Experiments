# Stereo tracks and stereo sources in the room

2026-11-07, the user's idea. **ST1-ST5 built 2026-11-08** (branch `stereo`; the stereo
compressor, ST3's LINK and ST3b, left for later: the user's call). "Status (2026-11-08)" at
the end says what was built, how it was checked and what is open. **ST6-ST7** (2026-11-09,
a brainstorm with the user, planned for the future, nothing built): placing a stereo track in
the mix the way period consoles did, with pan pots, and a mid / side matrix in iron as the
analog "stereo imager".

Instruments with their own stereo, the Rhodes Suitcase first (its side-to-side pan),
should reach the mix and the room as two channels, and in the Room view as two speakers
with a spacing between them. The session is mono today, so stereo tracks come first
(ST1-ST3, with the stereo 670 as ST3b later), then the room (ST4-ST5).

## Where stereo is lost today

- **Takes keep the mid.** A stereo device (its circuit probes `out_r`) plays its left and
  right apart live. Its take keeps (L + R) / 2:
  - `player::device_mid` (player.rs, "What a take keeps of a device's raw output", used at
    every capture);
  - a stereo chain end's mid (player.rs, "A take keeps a stereo end's mid");
  - `take_render.rs` ("A stereo device's take is its mid"), so MIDI renders do the same.

  The Suitcase's pan is complementary, so the mid cancels most of it.
- **Prints keep `out`.** `render.rs` returns the `out` probe, so a stereo insert (the
  351-2's ping-pong) prints only its left channel.
- **Tracks are mono throughout.**
  - `Take::audio` is one `Arc<Vec<f32>>`, and so are `Track::lane` / `playing`, `Printed`
    and `MixClip::audio`.
  - A track's pan is a balance (`session::balance`), placing a mono signal.
  - The mix, the meters and the export are already stereo after the pan.
- **Room sources are points.** Each `RoomSource` has one position, directivity and aim,
  and one mono `clip` handed to `room_print.py` (`room.rs`, `varimu/rooms/scene.py`).

Since the player is already stereo, playing live needs nothing.

## Milestones

### ST1: stereo takes

- `Take` gets an optional right channel (`right: Option<Arc<Vec<f32>>>`). Mono takes, and
  every code path that only reads `audio`, stay as they are.
- The capture paths keep L and R wherever `live.right()` exists: the device, a stereo chain
  end, and `take_render`'s replay. `device_mid` remains only where a mono value is
  genuinely needed (a sidechain key, a mono insert's input under ST3's sum option).
- Files: a stereo take's `draft.wav` (and `proxy.wav`, its renders) become 2-channel WAVs.
  The overview is drawn as the mid, or as two halves.
- Old sessions: their stereo-device takes are already mid. An event take can be re-rendered
  in stereo from its events (Render). A recorded audio take can't, and it stays mono.

**Done when:**
- a Suitcase take records both channels;
- `take_render` replays them bit for bit with what the player heard;
- mono takes are unchanged;
- `session::tests::every_session_opens_to_the_same_mix` passes on the 24 sessions.

### ST2: stereo through the session

- **A track is stereo when its lane holds a stereo take.**
  - `Track::lane` / `playing`, `pieces` and `Printed` carry the right channel.
  - Every clip edit (trim, fades, crossfades, gain, split, comp, copy / paste, time edits)
    applies the same samples to both channels.
  - A mono clip on a stereo track plays the same in both channels.
- `MixClip` gets a right channel, used in the mix and the stems; the meters show L and R
  for real.
- **The strip's pan on a stereo track** is a balance, like a console's stereo channel (the
  same `session::balance` law: each side loses gain only past the centre). Width isn't a
  control here. (Corrected 2026-11-09: period consoles did have width, on mid / side
  matrices. ST6-ST7 plan the pan and the width.)
- Export and stems are stereo as they are now; a stereo track's stem carries its two
  channels.
- Proxies stay mono and play in both channels (stand-ins only).
- `sounding_rms` (`room.rs` and `scene.py`) measures the louder channel. This matches ST4's
  level rule.

**Done when:**
- a stereo track's mix equals its L / R through the balance;
- the clip-edit tests pass for stereo and mono lanes alike;
- the 24 sessions still play bit for bit.

### ST3: inserts on stereo tracks

Every insert we have (the EQP-1A, the 670, the 1176, the SSL, the V76, the 5E3, ...) is a
mono circuit.

**Prints: dual-mono.**
- A mono insert on a stereo track prints twice with the same panel, one print per channel,
  keyed apart in the print cache. That's what a studio would patch with two units.
- Prints are background jobs, so the two channels print side by side on separate cores
  (about one print's wall-clock time when cores are free).
- A knob change reprints both; undo finds both in the cache.
- A stretch where L = R (a mono clip on a stereo track) prints once and plays the result in
  both channels.
- The alternative (sum to mono with a warning) is under "Decisions".

**Live: what to hear while setting the knobs.**
- The insert panel gets a selector **Hear: L | R | mid | stereo**. It is picked by hand,
  never switched automatically (the rule from MIDI_TAKES_PLAN.md's proxy decision).
- Two live instances don't fit for the heavy devices. The 670 alone takes ~53-85% of the
  machine at draft-1x (two cores); the EQP-1A takes 25-30%.
- **L or R, played up the middle:** one instance, fed exactly what that channel prints.
  This is the default (L), and the panel says which side is playing.
- **Mid, (L + R) / 2 up the middle:** also one instance, but exactly neither channel.
  - Fine for near-linear devices (the EQP-1A at sane levels).
  - Misleading for level-dependent ones (compressors, anything that saturates). The mid of
    a wide source peaks lower than its louder side, so a threshold set on the mid
    compresses the sides harder than heard.
  - On the Suitcase the pan is complementary, so the mid cancels most of the movement the
    compressor will see.
  - The panel says so when mid is picked on a level-dependent device ("mid: the print
    will differ").
- **Stereo:** two live instances (two `Live`s on their own threads), with the load shown.
  It may drop out on the heavy devices and is fine on light ones.
- An L / R flip before printing catches a source whose sides want different settings.
  After the print, the track plays in stereo, the real image.

**Compressors and the image.**
- Dual-mono compression acts on each side's own level. The louder side is pushed down
  more, so the image drifts toward the centre, and on the Suitcase the compressor fights
  and flattens the pan.
- Real stereo compressors link their sidechains, so a compressing insert on a stereo track
  has a **LINK** choice:
  - **independent:** dual-mono as above, what two patched mono units do; sometimes the
    sound wanted;
  - **key-linked:** each channel's sidechain fed the mid of both sides.
- Key-linked works on keyed circuits (the keyed 670, the SSL G with its key; K1-K2's
  `render_controls` and `print::Slot::key` already route a key to a print). Both channels
  hear the same key. Each is still its own unit, so their gain reduction matches only as
  far as the units are identical (nominal units are).
- A compressor with no key input offers only independent until it gets one (a KEY INT /
  EXT switch, as `derive_keyed_670.py` did).
- Live, key-linked hears L, R or mid like any insert. "Hear L" is exact for the left print
  only when the key is fed too (the key is the stereo mid, which the audition computes).
- The real stereo unit is ST3b.

**Other inserts.**
- **A stereo insert** (its circuit probes `out_r`) prints both channels. `render.rs`
  returns the `out_r` probe beside `out`. A mono track through it becomes stereo from that
  insert on.
- **A keyed insert whose key track is stereo** keys from the key's mid.
- Wet / dry and Render / Draft bake keep the channels.

**Done when:**
- a dual-mono print equals two mono prints of the two channels, bit for bit;
- a key-linked pair's two prints each equal a keyed print fed that channel and the mid as
  its key;
- each of Hear L / R / mid plays one instance, and stereo plays two;
- the 351-2 as an insert prints its ping-pong in both channels;
- the chain signatures of mono tracks are unchanged.

### ST3b: the stereo 670 (later, after ST3)

- **The 670 is a two-channel unit.** Our circuit models channel 1 with channel 2 as an idle
  load lumped onto the shared supply (`varimu/circuit/fairchild_670.py`). The project
  plan's Phase 1 lists "second channel and lateral/vertical (mid/side) mode" for later.
- **This milestone makes channel 2 real** (a generated `fairchild_670_stereo.yaml`).
  - Both channels sag the same supply ("most organic first").
  - Its **LAT / VERT** mode, the period's mid / side made for disc cutting, compresses
    L + R and L − R separately. On a panning source it behaves differently from L / R mode.
- **Costs and caveats:**
  - Prints: one larger solve. Hearing it live costs about two channels.
  - "Hear L" means channel 2 fed silence. That isn't exact, since the shared supply couples
    the channels.
  - Its profile and the `--verify` bounds need re-measuring for the new circuit.
- **Sources first:**
  - the manual's description of the mode switch and of whether the sidechains can be
    linked (not in `data/schematics/fairchild_670/` yet);
  - the second channel's wiring off the drawing.
- The SSL G bus compressor is stereo-linked in reality too; its stereo version would be the
  same kind of milestone.

**Done when:** the stereo 670 in L / R mode with identical inputs equals the mono 670 in
both channels, up to the supply's coupling (measured, a bound written down). LAT / VERT is
tested on a hard-panned source.

### ST4: stereo sources in the room (the engine)

The room is linear and its sources independent, so **a stereo source is two mono sources
expanded at load**. Image sources, rays, the wave solver, diffraction and directivity are
untouched.

- **The scene format:**
  ```yaml
  sources:
    - name: rhodes
      position_m: [2.0, 2.5, 1.0]      # the pair's centre
      aim: {azimuth_deg: 90}           # where the pair faces; its axis is perpendicular
      directivity: amp_1x12            # each side's, unless a side overrides it
      stereo: {spacing_m: 0.6}         # L at -spacing/2 along the axis, R at +spacing/2
      clip: rhodes.L.wav
      clip_r: rhodes.R.wav
  ```
  Each side may override its `directivity` and `aim` (toe-in, `stereo.sides: {L: {...},
  R: {...}}`). Load expands it to `rhodes.L` / `rhodes.R`.
- **One level for the pair:**
  - `spl_db` sets the louder channel's sounding rms at 1 m.
  - The other side keeps its relative level, so the instrument's own L / R balance
    survives.
  - The track's balance knob isn't applied (like pan for mono sources today: in a room,
    left / right come from places).
- **Solo and the bleed matrix** treat the pair as one source (`solo=True` renders the
  pair).
- **BALANCE's stems** sum both sides through each mic's `chain_proxy`, one stem per pair.
  `levels_from_mix` measures the pair as ST2 says.
- **Responses** are cached per side by geometry, as now. Moving the pair recomputes both
  sides; a change of level or audio skips the physics.
- **The app's hand-off** (`room.rs`, `RoomSource`, the scene JSON) writes `clip` and
  `clip_r` as two mono WAVs (Python's `load_audio` stays mono).
- **Cost:** the room's physics for that source doubles (with the wave solver, ~6.5 s per
  side at 500 Hz in 123 m^3).

**Done when:**
- a pair at zero spacing fed L / R equals a mono source fed L + R, to float rounding (the
  room is linear);
- the level rule is tested;
- a Suitcase render with a spaced omni pair keeps the pan's image;
- a mono mic hears the pan as level and comb motion. This is checked by measurement:
  modulation depth at 3.8 Hz, and notch motion against the pair's path difference.

### ST5: stereo sources in the Room view

- **A stereo track's source is drawn as two boxes** with:
  - a centre handle (drag);
  - a rotation (the pair's aim, as a mono source's);
  - a spacing handle (a drag along the axis, or a value).
- **Per side:** the directivity and an optional toe-in.
- **The default spacing comes from the device** (a table in `room.rs` keyed by
  `panel::Device::id`). It is a physical value with a source (Hard rules). Anything else
  falls back to a provisional 1.5 m (two monitors on a desk), editable.
- Pulling the sides beyond the instrument's real spacing is allowed: the user's "realistic
  first, then bend".
- A stereo track can be placed as a mono source (the mid at one point) by a checkbox, for
  comparison.

**Done when:** a scratch scene's pair is placed, turned, spread and rendered from the view.
It is looked at with a scratch `APPDATA` and session, as usual.

### ST6: placing a stereo track (pan pots, the pan law)

2026-11-09, the user's question: "now that we have stereo tracks, how do we pan them; do we
need a stereo imager; was there an analog version?" Planned for the future, nothing built.

**The problem.** A stereo track's knob is a balance (`session::balance`). Turned right, it
fades the left channel down. At hard right the left channel's content is gone; the image
doesn't move. That is a console's stereo-channel balance, but it isn't panning.

**What period engineers did.** Until stereo channels were common on consoles (into the
1980s on many desks), a stereo source came in on **two adjacent mono channels, each with
its own pan pot**:
- narrowed: L to about 10 o'clock, R to about 2 o'clock;
- moved: both turned towards one side;
- collapsed: both at the centre.

No imager is involved. The pan pot (Disney's "panoramic potentiometer", Fantasound, 1940) is
a passive dual-gang pot. This is the strip's control to build: faithful to the period and
nearly free (two gain pairs per stereo track instead of one).

**The control.**
- A stereo track's strip gets **two pans**, `pan` (the left channel's) and `pan_r` (the
  right's), drawn as two small knobs or as one knob with a second ring.
- Optionally the same two as **POSITION + SPREAD**: the centre and the distance between the
  two pans. This is only a different way to turn the same two pots; the mix is the same
  either way.
- The balance stays available (a stereo channel's `BAL`). Which is the default is a
  decision below.
- A mono track keeps one pan.
- The Mixer's strip, the Session view's strip, the session file (a new field, absent = the
  old balance), and the stems all follow.

**The pan law (a finding, 2026-11-09).** A mono track uses the same balance law. Centred, it
plays at unity on both sides; hard left, at unity on one side. So a sound panned to the
centre is about 3 dB louder in power than the same sound panned hard. Real pan pots dip at
the centre to hold the level steady through a sweep:
- -3 dB: constant power;
- -4.5 dB: the compromise many large consoles used;
- -6 dB: constant voltage, so a mono sum keeps a steady level.

A passive pan pot's real law also depends on its taper and on how it loads the mix bus's
summing resistor. Options:
- a. Keep the current law: the 24 sessions play bit for bit.
- b. A console-wide pan law setting (0 / -3 / -4.5 / -6 dB), new sessions at a dip, old
  sessions opened at 0 dB, so they don't change.
- c. The law from a drawn period pan pot into a summing bus (its taper and loading),
  tabulated once. It needs a sourced pan pot and bus. Later, if at all.

Proposed: b, at -3 dB for new sessions. The law is a table or a formula, so it stays free in
the mix.

**Not here:** width as a matrix (ST7); Haas delays and pseudo-stereo boxes (they widen a
mono source rather than place a stereo one; parked); the room (ST4-ST5 already place a
stereo source physically: two speakers moved and spread in the Room view, which is re-amping,
period practice too).

**Done when:**
- a stereo track with both pans at the centre plays its mid on both sides, scaled by the
  pan law;
- with pans at hard left and hard right, it plays exactly as before (L on the left, R on the
  right);
- POSITION and SPREAD drive the same two pans as the two knobs, so the mix is identical;
- at the 0 dB law, the 24 sessions in `sessions/` play bit for bit
  (`every_session_opens_to_the_same_mix`);
- the stems sum to the mix.

### ST7: two-input inserts and the mid / side matrix (the analog imager)

2026-11-09, planned for the future, nothing built.

**History.** Width is real analog history (ST2's "not something a period console had" was
wrong):
- **Blumlein's stereo patent** (GB 394,325, filed 1931) is built on the sum / difference
  (mid / side) matrix. His **"shuffler"** is a frequency-dependent network in the
  difference channel that converts a coincident pair's phase differences into level
  differences, widening the bass.
- **EMI's Stereosonic** recording chain and **BBC** stereo desks matrixed M/S with
  transformers (provisional: model knowledge; to source).
- **German broadcast consoles** had a *Richtungsmischer* (direction mixer) and a
  *Basisbreitensteller* (width control) (provisional: model knowledge; to source, e.g. from
  a Neumann, Siemens or Telefunken broadcast console's manual or the IRT drawings that gave
  us the V76).

**The device.** It is a circuit like any other, so the width comes from physics, not a
formula:
- an **M/S matrix in iron**: two transformers wired as sum and difference (L + R into M,
  L - R into S), on our JA cores, designed and compiled in the transformer designer (C2);
- **WIDTH** a pot or stepped attenuator in the S leg (0 = mono, the nominal at unity, past
  it wider), then the inverse matrix back to L / R;
- optionally **the Blumlein shuffler**: an LC network in the S leg, with its corner as a
  part value;
- optionally the direction mixer's **POSITION** (a rotation of M against S), if the sources
  show how the period did it;
- iron colours both legs (saturation, bass at level, the windings' HF): this is the
  character a digital imager doesn't have.

**The prerequisite: inserts with two inputs.** Today a stereo track's insert prints
dual-mono: two independent runs of a mono circuit. A matrix needs both channels in one
netlist. The machinery mostly exists:
- the keyed 670's KEY carries a second audio signal into a circuit as a control input
  (`render::render_controls`, `print::Slot::key`, K2);
- a circuit already probes `out_r` (the 351-2, the Suitcase);
- so a two-input circuit could declare its right input as a control input (`in_r`, say)
  behind a source impedance, fed from the track's right channel. Its print and live hear
  would then be one run, not two.

This is the same prerequisite as ST3's LINK and ST3b's stereo 670 (whose LAT / VERT mode is
itself an M/S matrix around two compressors). Built once, all three use it. The master
inserts (RECORDING_PLAN.md T5) could take it too: an M/S matrix on the mix bus.

**Sources first:** the period matrix and width-control circuits (the transformers' ratios,
the width pot's network, a shuffler's values) before any values are invented; provisional
values carry their sources, as always.

**Done when:**
- a stereo insert with a two-input circuit prints in one run and plays live in one run;
- the matrix at nominal WIDTH returns L / R within its iron's measured colouring (bound
  written down), at WIDTH 0 equal channels, and with the S leg inverted, swapped channels;
- a hard-panned and a centred source show the expected width change (S / M ratio in dB per
  WIDTH step);
- mono inserts' and dual-mono prints' keys are unchanged.

## The Suitcase's numbers (to source)

RHODES_PLAN.md "The Suitcase" has:
- the speaker section, 48 x 27 x 14 in;
- per channel, two 12" drivers in series: the front one read out as `out` / `out_r` (the
  pressure 1 m on axis), the rear one mirrored directly behind it;
- an open baffle; open or closed back unknown.

**Spacing.** The front drivers' centre-to-centre spacing isn't recorded anywhere yet.
- Two 12 in drivers across a 1.22 m baffle puts it near **0.6 m**. That number is
  provisional (model knowledge).
- Measure it from the service manual's cabinet figure or a dimensioned photo before it
  becomes the default.

**Feeding the room.** `out` / `out_r` are already pressure at 1 m (the driver's response
included). They feed the room as each side's signal; the room's directivity is normalized
on axis, so nothing is counted twice.

**Directivity.** A rear driver directly behind the front one makes each side radiate front
and back. The presets are caps on a sphere, which radiate forward. Start each side as
`amp_1x12`. A back-radiating preset (open baffle, front and rear in antiphase or in phase,
per how the rear driver is wired) is an option once the back's construction is known.

## Not in this plan

- **A Leslie:** a moving directional source (rotating horn and drum, Doppler). It is a
  different and larger feature (moving image sources), and is in RHODES_PLAN.md "The
  side-to-side pan" as one of the user's options.
- **Stereo effects as room sources** (the 351-2, a reverb return). They belong on the
  console after the mics. A stereo send into a chamber room is the same machinery as ST4
  (HEADLESS_MIX_PLAN.md H2's echo chamber), so it comes free once ST4 exists.
- **Spatially extended acoustic sources** (a grand piano's soundboard as many points). Two
  points are a speaker model, not an instrument body.

## Decisions (the user's, when picked up)

1. **The file format** of a stereo take: a 2-channel WAV (proposed) or a mono `draft.wav`
   plus a `draft.R.wav` sidecar (mono readers keep working, at the cost of two files per
   render).
2. **A mono insert on a stereo track:** dual-mono prints (proposed, 2x print cost) or a
   sum to mono with a warning.
3. **The pan of a stereo track:** a balance (proposed) or a per-channel pan / width
   control.
4. **The pair's level:** the louder channel at `spl_db` (proposed) or the sum on the
   pair's centre axis.
5. **Compressors on stereo tracks:** independent by default (proposed: what patching two
   units gives) or key-linked by default. And whether ST3b (the stereo 670, LAT / VERT)
   comes right after ST3 or waits.
6. **Hear's default:** L (proposed: exact for one channel) or mid (closer to the whole on
   linear devices).
7. **Old stereo-device event takes:** re-rendered in stereo when the session is opened,
   offered per track, or left until the user renders them (proposed: left; ST1's Render
   does it).

ST6-ST7's (2026-11-09; open until they are picked up):

8. **A stereo track's default control:** two pans, starting hard left and hard right
   (proposed: it plays like today's balance at the centre), or the balance with the two pans
   behind a toggle.
9. **How the two pans are drawn:** two knobs, or POSITION + SPREAD, or both with a toggle
   (proposed: POSITION + SPREAD on the strip, the two pans in its hover / right-click).
10. **The pan law:** ST6's options a-c (proposed: b, -3 dB for new sessions, old sessions at
    0 dB).
11. **ST7's order:** two-input inserts with the M/S matrix first, or with ST3's LINK / ST3b
    first (the same prerequisite; proposed: whichever the user wants to hear first).
12. **The matrix's sources:** which period unit to follow (Blumlein / EMI, BBC, a German
    broadcast console's width control), once one with a published circuit is found.

## Status (2026-11-08)

Built in one session, the user's ask: "record instruments like the Rhodes in the session and
place it in a room, and use the EQ, applied separately to each channel; compression after".
The decisions went as proposed (1-4, 6, 7; 5 is the compressor, not built).

**ST1, stereo takes: built.**
- The recorder keeps a right channel beside the left (`session::Recorder::capture_until`'s
  `right`; a take is mono or stereo throughout: a change starts the next take).
- The player passes a stereo device's raw right channel (`Emitter::raw_right`; `device_mid`
  is gone), a stereo chain end's too.
- `take_render::render` returns both channels (`Channels`); a stereo device's render key
  adds `stereo` (its old mid renders aren't found; mono devices' keys are unchanged).
- Files: a stereo take's `draft.wav`, and its renders' `audio.wav`, are 2-channel float32.
- Old takes of stereo devices stay their mid. An event take is re-rendered in stereo by its
  Render.

**ST2, stereo through the session: built.**
- `Take::right`, `TakeRender::right`, `Printed::right` / `stages_right`, `MixClip::right`;
  `Take::sound_right`, `Track::is_stereo`, `Track::lane_lr`, `Track::playing_lr`.
- A lane is stereo when one of its clips plays a stereo sound; its mono clips play on both
  sides. The lane signature marks stereo sounds only, so mono prints keep their keys.
- The strip's pan on a stereo track is the same balance law (the Mixer labels it `BAL`);
  the meters, export and stems carry both channels; the take line says `stereo`.
- `session::tests::every_session_opens_to_the_same_mix`: the 24 sessions in `sessions/`
  play bit for bit.

**ST3, inserts on stereo tracks: built, except LINK (the compressor).**
- `print::Job::spawn` / `lookup` take the right channel: the same chain on a thread of its
  own, `Print::right` (a right equal to the left prints once).
- Prints and ⤓ Render / ⤓ Draft of a stereo lane are stereo.
- The insert panel's **hear L | R | mid** on a stereo track (L by default; the mid made once
  per input); a stereo key track keys from its mid.
- Not built: Hear "stereo" (two live instances), LINK (independent / key-linked), ST3b.

**ST4, stereo room sources: built.**
- A scene source with `clip_r` and `stereo: {spacing_m, sides?}` expands at load into
  `<name>.L` / `<name>.R` (varimu/rooms/scene.py), its left at the facing direction's left.
- One gain from the louder channel's sounding rms.
- **The tail:** both sides share one diffuse field (the scene source's seed), each shifted to
  where it sits (`shoebox.responses`' `tail_offsets`), so they cohere as the diffuse field's
  sinc(k d). Independent seeds made a pair at zero spacing two different rooms.
- Sources after a pair keep their seeds (`SourceSpec.seed_index`); mono scenes' response keys
  are unchanged (the code's hash still moves every key once, as any edit of varimu/rooms does).
- Solos (the bleed matrix) are per side, not per pair (a deviation from the plan: simpler,
  and informative). BALANCE's stems are per pair (one fader).
- Tests: `tests/test_rooms.py::test_a_stereo_source_is_two_speakers_with_one_gain` (the
  expansion, the gain, zero spacing equal to the mono source),
  `test_a_stereo_pairs_tails_cohere_as_the_diffuse_field_says`.
- End to end (a 3.8 Hz complementary pan, 0.6 m apart, `amp_1x12`, 7 x 5.5 m room, the clean
  omni chain at draft): the mono mic 1.5 m in front hears a 2.3 dB swing, a spaced pair's
  mics 3.5 / 4.1 dB.

**ST5, the Room view: built.**
- A source whose track is stereo draws its two speakers (L, R) across its facing direction;
  its form has "speakers N m apart" and "as one point" (the mid), and faces for any pair.
- The spacing defaults from `room::STEREO_SPACINGS` (the Suitcase's provisional 0.6 m), else
  1.5 m; kept in the scene state (`spacing_m`, `as_mono`).
- The render writes `<name>.L.wav` / `.R.wav` and the pair (`Scene::render_json_lr`);
  "Levels from the mix" measures a stereo track's louder channel.

**Open.**
- The stereo compressor: LINK, ST3b (the user: after).
- Hear "stereo" (two live instances).
- Imported stereo files still import as their mid (`import_files` uses `audio::load`).
- The Suitcase's real spacing (to source).
- The user's first try.
- ST6 (pan pots on stereo tracks, the pan law) and ST7 (two-input inserts, the M/S matrix in
  iron): planned 2026-11-09, nothing built; decisions 8-12.

