# Stereo tracks and stereo sources in the room

2026-11-07, the user's idea. **ST1-ST5 built 2026-11-08** (branch `stereo`; the stereo
compressor, ST3's LINK and ST3b, left for later: the user's call). "Status (2026-11-08)" at
the end says what was built, how it was checked and what is open.

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
  control (not something a period console had).
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

