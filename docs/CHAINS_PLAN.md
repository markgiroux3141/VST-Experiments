# The chains build-out: every mic -> preamp chain on the list

Started 2026-11-05 (the user's: "build everything we need to have all these chains
available", over many sessions). The list itself is
[MIC_ROOM_PLAN.md](MIC_ROOM_PLAN.md)'s "The chain list" (51 chains, 8 built); after WP0 its
source is `config/chains.yaml`. This plan is the order of the work and its state.

**To resume:** `/chains` (the project skill `.claude/skills/chains/`), or say "pick up the
chains where we left off". The session reads **Status** below and follows **How a session
runs**.

## Status

*Updated at the end of every session. The next session starts here.*

- **Chains available:** 15 of 51 (the built matrix: U47, SM57, SM58, omni x V76, clean;
  U47 -> V72, U47 -> UA 610, C12 -> clean, C12 -> UA 610, SM58 -> SSL, SM57 / SM58 ->
  Portastudio; `uv run python scripts/chain_status.py`).
- **Done:** WP0 (2026-11-05): the list is `config/chains.yaml`, read by compose, the tests,
  `chain_status.py` and the app. WP1 (2026-11-05): the Telefunken V72
  (`config/circuits/telefunken_v72.yaml`, 8 of 14 of the Braunbuch's specs, the misses
  within 0.06 dB / 7% and traced; WP1's Notes). WP2 (2026-11-05): the UA 610-A
  (`config/circuits/ua_610.yaml` from Hinson's redraw of UA C-10068; WP2's Notes). WP3
  (2026-11-05): the AKG C12 (`config/circuits/akg_c12.yaml` from AKG's 1957 drawing, the
  capsule `CK12@1` fitted to AKG's curves, nine patterns; WP3's Notes). WP4 (2026-11-05):
  the SSL 4000 E's 82E01 mic amp with the Jensen JT-115K-E fitted to Jensen's sheet
  (`config/circuits/ssl_4000e.yaml`) and the Tascam 424's mic input
  (`config/circuits/tascam_portastudio.yaml`), op-amps only; WP4's Notes. WP5
  (2026-11-05): the ribbon kind `ribbon_motor` (`varimu/devices/ribbon.py`, compiled to
  moving_coil's format), its first instance `RIBBON_44BX@1` and the 44-BX's step-up
  transformer `RCA44BX_OT@1` as a design, in `config/circuits/ribbon_test.yaml`; WP5's Notes.
- **In progress:** none.
- **Next:** WP6 (the RCA 44-BX), Start step 4: write its steps here. The sources are
  already in `data/schematics/rca_44bx/README.md` (RCA's instruction book with its
  response, polars and schematics); WP5's Notes, "For WP6", list what to digitize, build
  and fit. The user fetches login-walled files on request: give each URL alone in a code
  block (WP2's Notes).
- **Waiting on the user:** listening to U47 -> UA 610, the C12's chains, SM58 -> SSL and
  the Portastudio chains in the Room view (optional). One call of theirs: the JT-115K-E's
  20 Hz THD at -20 dBu is 0.44% against Jensen's 0.065% (the fitted mumetall's low-field
  hysteresis; WP4's Notes): leave it, or refit / add a nickel material (moves every render).

## How a session runs

**Start**
1. Read this file's Status, then the section of the WP it names (and its "Notes" left by
   the last session). After WP0: `uv run python scripts/chain_status.py` (which chains are
   available, which are blocked and by what).
2. `git status` on main (the work is on main, the user's call). Every session ends with
   a commit, so uncommitted changes at the start are another session's work in progress:
   leave them alone, don't build on them, and never stage them.
3. Say in one line which WP and step this session takes, then work. The next WP in order
   unless the user names another; the order may be changed by the user at any time (edit
   the table, not just the session).
4. A WP with no detailed steps yet starts by writing them here (sources first).

**During**
- Follow CLAUDE.md's Hard rules (sources on every value; two implementations per device
  model with an agreement test). Physics refits that move existing renders: bring options
  and numbers, the user decides. Other calls: decide, record them under the WP's
  "Decisions".
- Targeted tests per step (the user's rule); the full suite is batched (see "Owed").

**End** (when the WP is done, or before the context runs low: stop at a clean step)
1. The WP's targeted tests pass; anything owed (fixtures, full suite, `--verify`) goes in
   "Owed" below.
2. Update **Status** (chains available, done, in progress with its *exact* next step, what
   waits on the user) and the WP's "Notes" (what a fresh session must know: files touched,
   numbers, dead ends).
3. One line in the **Session log**.
4. CLAUDE.md: keep its one paragraph on the chains build-out current (a pointer and the
   state, not the details; those live here and in the WP's own plan if it grows one).
5. **Commit on main** (the user's call): stage only this session's files, by path
   (`git add <paths>`, never `-A` or `.`). A file another session also changed (often
   CLAUDE.md) gets only this session's hunks: stage a copy of HEAD's version with this
   session's edits applied (`git hash-object -w` + `git update-index --cacheinfo`), then
   check `git diff --cached`. Message `Chains WPn: <what>` with the attribution line; no
   push.

A WP that outgrows a few steps gets its own plan file (like [SM57_PLAN.md](SM57_PLAN.md))
and this table points to it.

## What "done" means

**A preamp:** sources in `data/schematics/<name>/README.md` (provenance per value); the
circuit file in `config/circuits/`; it idles near the drawing's printed voltages (a test,
the drawing's tolerance or +-20%); its profile (`varimu unit --circuit NAME`, gain,
response, THD against published figures where they exist; `preamp_suite.py` if it fits);
a `PORTS` entry; its chains compose and pass `test_chain_matrix.py`; the Room view offers
them; app fixtures re-exported if the app plays it.

**A mic:** sources in `data/schematics/<name>/`; its capsule or cartridge as a component
version (fitted one figure per unknown, like SM57_PLAN.md's table); its circuit file;
on-axis response and polars against the published ones (the SM57's bar: +-2 dB to 10 kHz,
polars within 3 dB, or the reason it can't be met); its entry table computes
(`varimu/rooms/entries.py`); its chains compose, build and render once through a scene
(`room_print.py`, draft).

**A device model** (BJT, JFET, a tube fit, a transducer kind): a Python reference,
SPICE, circuitsim's port and both builders, the agreement tests, fitted to a datasheet
with the digitized curves' provenance; fixtures regenerated.

## The work packages

In order of chains opened per piece of work (MIC_ROOM_PLAN.md's "What each prerequisite
unlocks"). "Opens" counts chains that become available when the WP is done, given the WPs
before it. Sizes are rough: S one session, M one or two, L several.

| WP | What | Opens | Size | State |
|---|---|---|---|---|
| 0 | The list as data: `config/chains.yaml`, `chain_status.py`, compose / test / app read it | 0 | S | done 2026-11-05 |
| 1 | Telefunken V72 (two EF804S; BV 191 is its input transformer, already compiled) | U47 -> V72 | M | done 2026-11-05 |
| 2 | Universal Audio 610 | U47 -> 610 | M | done 2026-11-05 |
| 3 | AKG C12 (CK12 on `capsule_dual`; 6072 = `12AY7@1`; its transformer) | C12 -> clean, C12 -> 610 | L | done 2026-11-05 |
| 4 | The op-amp preamps: SSL 4000 E channel (82E01, JT-115K-E), Tascam Portastudio (the 424 mk1) | SM57 / SM58 -> Portastudio, SM58 -> SSL | M | done 2026-11-05 |
| 5 | The ribbon kind `ribbon_motor` (ribbon in a gap compiled to R / L / C and a gyrator, like `moving_coil`; the step-up transformer as a design) | 0 | M | done 2026-11-05 |
| 6 | RCA 44-BX | 44-BX -> V76, 44-BX -> 610 | L | next |
| 7 | RCA 77-DX (the shutter labyrinth) and the Ampex 351's record amp as a preamp | 77-DX -> 351, 77-DX -> 610 | L | |
| 8 | Coles 4038 | 4038 -> V72 | M | |
| 9 | AKG D112 (moving_coil; its bass chamber) | D112 -> SSL (if WP4 built the SSL) | L | |
| 10 | **The BJT model** (Gummel-Poon subset; DEVICE_BUILDER_PLAN.md "New device types") | 0 | L | |
| 11 | Neve 1073 (Marinair transformers as designs; 300 / 1200 ohm) | 44-BX, SM57, U47 -> 1073 | L | |
| 12 | API 312 (the 2520) | SM57 -> API | L | |
| 13 | Electro-Voice RE20 (Variable-D: rear entries along the body) | RE20 -> API, RE20 -> 1073 | L | |
| 14 | Sennheiser MD421 (its bass switch) | MD421 -> API | L | |
| 15 | Shure SM7 | SM7 -> 1073 | L | |
| 16 | Royer R-121 (offset ribbon) | R-121 -> API | M | |
| 17 | Beyer M160 (two ribbons, hypercardioid) | M160 -> 1073 | M | |
| 18 | Telefunken ELA M 251 (the C12's capsule, its own electronics) | 251 -> 1073 | M | |
| 19 | Helios | SM57 -> Helios | M | |
| 20 | EMI TG12345 | 4038 -> TG | M | |
| 21 | **The JFET model** | 0 | L | |
| 22 | Neumann U87 (dual capsule, pattern by polarization) | U87 -> 1073, SSL, TG | L | |
| 23 | AKG C414 | C414 -> SSL, C414 -> clean | L | |
| 24 | Neumann KM84 | KM84 -> 1073, KM84 -> TG | L | |
| 25 | Neumann U47 fet (the K47 exists) | U47 fet -> API | M | |
| 26 | Crown PZM and a mic placed on a surface in scenes | PZM -> clean, PZM -> SSL | L | |
| 27 | The Cloudlifter, and three-stage chains in `compose_chain.py` | 44-BX / SM7 -> Cloudlifter -> clean | M | |
| 28 | The EF86 fit; Neumann U67; EMI REDD.47 | U67 -> REDD.47, U67 -> 1073 | L | |
| 29 | The AC701 fit; Neumann M49 | M49 -> V76 | L | |
| 30 | The crystal kind; the Shure Green Bullet into the 5E3 (an instrument, a source in the room) | Green Bullet -> 5E3 | L | |
| 31 | The carbon kind; a carbon transmitter | Carbon -> clean | M | |

### WP0. The list as data

Steps:
1. `config/chains.yaml`: per circuit its tag, ports and panel settings (what `PORTS` and
   the app's `room::CHAINS` settings hold today), and per chain: id, stages (mic, an
   optional booster, preamp), label, `use` (the "most likely used to record" note), `needs`.
   The 51 chains of MIC_ROOM_PLAN.md, its tables then pointing here.
2. `scripts/chain_status.py`: per chain available (every stage's circuit exists) or
   blocked, and by which `needs`; the count. Exit 0 always (a report).
3. `compose_chain.py --all` composes the listed, available chains (not MICS x PREAMPS);
   `test_chain_matrix.py` reads the list (the count from the file, not 8).
4. The app reads the list (its label, settings, and the `use` note shown under the chain
   picker; only available chains offered), `room::CHAINS` gone.
5. Done when: the 8 built chains come out byte-identical (`--check`), the tests pass, the
   Room view shows the notes (seen on a scratch APPDATA, the memory rule).

Notes (2026-11-05, done):
- `config/chains.yaml` (its header is the format): `needs` (token -> what, WP),
  `circuits` (every mic / booster / preamp on the list by circuit file name: kind, tag,
  label; built ones their port, `drop`, `pattern` (mics) and `settings`; unbuilt ones their
  `wp`), `chains` (id = the stages' tags joined by "_", checked; mic, optional booster,
  pre; `use`; `needs`, `needs_note`; `defaults` in chain keys). Labels are derived (stage
  labels joined by " → "), not stored.
- `varimu/chains.py` is the reference reader and checker (built = the circuit file exists
  and has its port; available = every stage built). `fender_5e3`'s file exists but it has
  no `input` port until WP30, so it counts as unbuilt.
- `scripts/compose_chain.py`: `PORTS` is built from the list; `--all` = `listed_pairs()`,
  the available chains (a booster raises NotImplementedError until WP27). `MICS` /
  `PREAMPS` are gone. The 8 files come out byte-identical (`--check`).
- `chain_status.py` prints available, blocked (missing circuits with their WP, needs),
  and what each WP opens: it matches the WP table's "Opens" column exactly (43 blocked).
- The app: `room::load_chains` / `chains()` / `chain()` read the list once (a `OnceLock`;
  `RoomView::new` calls `init_chains(root/config)`, a load error shows with the preset
  errors), offering chains whose composed file exists; `RoomMic::pattern` comes from the
  mic's `pattern` (no tags hard-coded). The `use` note is a faint line under the add-mic
  picker and the mic's Chain, and each entry's hover text. Seen on a scratch APPDATA.
- When a WP builds a circuit: give its entry the port, `drop`, `pattern` (a mic) and
  `settings`, remove its `wp`, run `compose_chain.py --all`, then `chain_status.py`.
- Tests: `tests/test_chain_matrix.py` (11), varimu-app `room::tests::chain_list_reads`.

### WP1. The Telefunken V72

The V76's predecessor (1952, NWDR design, made by Maihak and Siemens): two EF804S, a fixed
34 dB, BV 191 (CT V72/1) in, a choke-loaded V2 parafeeding an output transformer, a
selenium bridge into an RC chain. Sources: `data/schematics/telefunken_v72/README.md`.

Steps:
1. Sources: the IRT Braunbuch V 72 (1953: text, acceptance specs, drawing S 843 in its two
   versions; the model is sheet 2, "from unit 1001"), the Siemens datasheet, the wound
   parts' figures from what's published (Sowter's reproductions, GroupDIY measurements).
   The drawing prints no voltages.
2. `config/circuits/telefunken_v72.yaml`: BV 191 as `component: BV191@3` (primaries in
   series through C30, the 40 Hz network; shield S at ground); the choke CK V72/1 and the
   output transformer CT V72/2 as provisional macro transformers; the supply calibrated to
   the published B+. R20 (5 k "abgegl.") trimmed to 34 dB, C40 (~40 pF trimmer) to the
   15 kHz spec, as the factory did.
3. `tests/test_telefunken_v72.py`: idle against what is published (B+ ~245 V, V1's bias
   ~2.7 V) and the EF804S ratings; the nominal gain.
4. Its profile `varimu/measure/v72_suite.py` (`varimu unit --circuit telefunken_v72`): the
   Braunbuch's specs (gain 34 +-0.2 dB, response 60 Hz-10 kHz +-0.3 dB, 40 Hz -0.3..-1 dB,
   15 kHz 0..-0.6 dB, k at +12 / +17 dB, output impedance <= 35 ohm, max output 5.5 V at
   0.3% THD).
5. The list: `telefunken_v72`'s entry (port, drop, settings), `compose_chain.py --all`
   (u47_v72), `test_chain_matrix.py`, app fixtures, `chain_status.py` 9 of 51.

Notes (2026-11-05, done):
- Sources: `data/schematics/telefunken_v72/README.md` (the Braunbuch V 72's sheets 1-6
  and both S 843 sheets as PNGs, the Siemens datasheet; the parts' web figures). The model
  is S 843 sheet 2 (from unit 1001). The drawing prints **no voltages**, and no original
  V72's were found: the idle test checks the two forum figures (B+ ~245 V, V41's bias
  ~2.7 V: 254 / 2.65 in the model) and the currents' plausibility.
- `config/circuits/telefunken_v72.yaml`: T1 is `component: BV191@3` (p1 [ia, ap1], p2
  [ap2, 0], C30 between, s [g1, 0], `shields: {S: "0"}`); the choke L3 (750 H, 18.4 k:
  Sowter's CK V72/1 equivalent; 22,264 turns on the V76's L86 core, CJ counted 22,500 on
  an original) and T2 (11.2:1, 960 / 12.1 ohm: Sowter, GroupDIY) provisional; the selenium
  bridge is the V76's `B450C80@1` standing in for AEG's. The tube model's suppressor is its
  cathode; the V72's go to 0 V (V41's ~2.7 V below its cathode): not modelled.
- `scripts/v72_trim.py [--check]` sets three values: R20 (the factory's gain trim, 5 k
  "abgegl." drawn: 2.19 k for 34.0 dB; the drawn 5 k gives 34.3), C40 (the 15 kHz
  trimmer, "ca. 40 pF": 28.7 pF for -0.3 dB at 15 kHz), and the HV winding (no data:
  247.5 V rms, calibrated to the maximum output, 0.3% THD at +17 dB, the Braunbuch's and
  the datasheet's; B+ then lands at 254 V against CJ's "245"). They interact; it runs
  the three in turn twice (~10 min). A first calibration of the HV to B+ 245 V left V42
  too close to cutoff for +17 dB (1.2% THD): its class-A current into 37.6 k sets the
  clipping.
- T2's turns: 3500 (~450 H): 1490 (81 H, sized for 0.7 T at 40 Hz) resonated with C33
  near 12 Hz and peaked +0.5 dB at 50 Hz.
- The profile `varimu/measure/v72_suite.py` (`varimu unit --circuit telefunken_v72`;
  ~20 s warm; reports/units/v72_nominal/): meets 8 of 14. Met: gain 34.00, 15 kHz -0.28
  at both levels, THD at +12 dB 0.10 / 0.07 / 0.08% (40 Hz, 1 k, 5 k), +17 dB 0.29%,
  output impedance <= 30.1 ohm. Missed: flat 60 Hz-10 kHz 0.32 / 0.36 dB (+6 / -34 dB out;
  limit 0.3) and 40 Hz -0.26 / -0.14 dB (limit -0.3..-1): both C30's resonance with BV
  191's primary (BV191@3: 23.4 H against 25 published; the low level's lower mumetall
  permeability peaks more); the input impedance 1862 ohm at 15 kHz (>= 2 k: BV 191's
  compiled ~45 pF on the grid side, reflected x100; >= 2 k up to ~14 kHz); the maximum
  output 16.99 dB (17.0: the trim's tolerance). Not modelled: noise, hum fields.
- The chain: `config/chains.yaml`'s `telefunken_v72` (input `ia`, drop RSRC, no settings:
  a fixed 34 dB), `u47_v72.yaml` composed (the 8 others unchanged). 94 dB SPL at 1 kHz:
  1.41 V rms out, as U47 -> V76 at 34 dB (`mic_print.py --draft`: 1.16x real time against
  the V76 chain's 1.85x).
- Tests: `tests/test_telefunken_v72.py` (6: builds, preflight, BV 191's pin, the idle,
  the currents, the trims), `test_chain_matrix.py`, `test_app_fixtures.py` (fixtures for
  `telefunken_v72` and `u47_v72` exported, nothing else moved), varimu-circuit's
  `tests/agreement.rs`, varimu-app `room::`.

### WP2. The Universal Audio 610

The microphone preamplifier of Bill Putnam's 610 console (1960): the "Modular Amplifier
Model 610-A", a 12AX7 pair with feedback, the LEVEL pot, a 12AY7 pair driving a gapped
output transformer with the module's EQ in the output stage's feedback; the console's B+.
Sources: `data/schematics/ua_610/README.md`.

Steps:
1. Sources: the drawing (Hinson's redraw of UA C-10068, from two original modules; a
   GroupDIY attachment the user fetched), UTC's Ouncer catalog and 1952 terminal sheet
   (the O-1's taps), a clone's measured voltages; the 2-610 reissue's specs as a
   reference only.
2. `config/circuits/ua_610.yaml`: traced from the PDF's vector paths; the mic input only,
   the console's B+ as an ideal rail behind a provisional resistance; the O-1 and the
   PA-5946 as provisional macro transformers sized from their published figures.
3. `tests/test_ua_610.py`: builds, preflight, the switches' rewiring, idle against the
   clone (at its 298 V), the gain structure (the link's step, the LEVEL law).
4. Its profile `varimu/measure/ua610_suite.py` (`varimu unit --circuit ua_610`): gain
   (links, LEVEL law), response per HF / LF position, input and output impedance, THD
   against level; the 2-610's figures reported, never checked against.
5. The list: `ua_610`'s entry (port, drop, settings), `compose_chain.py --all`
   (u47_ua610), `test_chain_matrix.py`, app fixtures, `chain_status.py` 10 of 51.

Notes (2026-11-05, done):
- Sources: `data/schematics/ua_610/README.md` (the drawing in two copies, the input-stage
  variation, UTC's catalog page and terminal sheet, the clone's voltages, the 2-610's
  manual pages). The GroupDIY attachments need the forum's login and worldradiohistory
  refuses scripts: the user fetched them (each URL given alone in a code block: the
  user can't copy them from inline text). The auto-mode classifier refuses archive copies
  of walled files and spoofed user agents: ask the user instead. The drawing prints no
  voltages.
- The drawing was traced from the PDF's vector paths (a scratch script: horizontal /
  vertical segments joined at endpoints and T's, not at crossings; nets listed with the
  nearest labels), then read by eye. The O-1's 50 ohm tap is pins 3-4 (UTC's terminal
  sheet), where the 610 wires the mic: 1:31.6.
- `config/circuits/ua_610.yaml`: controls `level` (R13 250K, audio taper_mid 0.1,
  provisional; default 0.2 = 35 dB at Hi), `gain_link` (0 Lo / 1 Hi, the internal link),
  `hf_eq` (-6 / 0 / +3 / +6), `lf_eq` (-6 / 0 / +6), `b_plus_v` (275 V, Hinson's
  original desk). T1 (O-1): mumetall for UTC's Hipermalloy, a 1/4 x 1/4 in core fitting
  the Ouncer case, 292 turns on the 50 ohm section (+8 dBm at 30 Hz at 0.4 T), ratio
  31.623, primary DCR 16.4 ohm (52 x 0.316); its gap and secondary capacitance genome
  parameters (`ua_610.t1.*` in genome_bounds.yaml). T2 (PA-5946): 7000 turns (a
  reproduction's), gap 170 um for 55 H in the linear limit (B_dc 0.31 T at 6 mA), ratio
  1 / 7.07, 826 / 50 ohm. The drawing's two C10s: `C10` (100 pF, the EQ) and `C10S`
  (10 uF, the supply).
- Idle (at the clone's 298 V): rails, V1-B, V2-A, V2-B within 10% of the clone's; V1-A
  0.30 mA, self-consistent (the clone's V1-A readings disagree with each other: left
  out). At 275 V: the B+ terminal 274.3 V, V2-B 5.5 mA.
- The profile (reports/units/ua610_nominal/, ~30 s warm): 69.65 dB at full LEVEL, Hi;
  61.52 at Lo (an 8.13 dB step; the forum's "about 9"); the LEVEL law = full gain + taper
  within 0.01 dB. Response at 40 dB (level 0.3) re 1 kHz: 20 Hz -2.6, 50 Hz -1.0, 10 kHz
  -0.3, 20 kHz -1.1 dB (T1's: with a 50 ohm source the 610 is flat within 0.2 dB). EQ re
  flat: HF -6 -5.0 dB at 10 kHz, +3 +4.4, +6 +6.4 (and +0.8 at 1 kHz); LF -6 -5.9 at
  50 Hz, +6 +5.5. Input impedance 1240 ohm at 1 kHz (the 50 ohm tap reflecting R26 1M2),
  280 at 40 Hz, 700 at 10 kHz. Output impedance 105 ohm at 1 kHz. THD at 1 kHz: 0.22% at
  +4 dBu out, 1% at +13.9 dBu, then hard clipping (V2-B's grid swing reaches its 3.3 V
  bias; the 2-610's +20 dBm is another output stage). 40 Hz: 0.49% at +2.6, 0.99% at
  +10.6 dBu. Against the 2-610 reissue's figures (a reference): 0 of 4 (maximum gain 61,
  flat +-1 dB, 60 ohm, +20 dBm).
- The chain: `config/chains.yaml`'s `ua_610` (input `ia`, drop RSRC; settings LEVEL as
  rotations labelled by their Hi gains, the link, HF, LF); `u47_ua610.yaml` composed (the
  9 others byte-identical). 94 dB SPL at 1 kHz: -17.6 dBFS peak, 1.52 V rms out at the
  default 35 dB (`mic_print.py --draft`, ~1x real time; U47 -> V72: -18.8 dBFS).
- Not modelled: the line input, the console's supply (an ideal rail), noise, the echo
  send's output, the input-stage variation (Hinson's "Alternative 610 Input scheme").
- Tests: `tests/test_ua_610.py` (5), `test_chain_matrix.py`, `test_app_fixtures.py`
  (fixtures for `ua_610` and `u47_ua610` exported, nothing else moved), varimu-circuit's
  `tests/agreement.rs`, varimu-app `room::`.

Decisions:
- T1's joint gap and secondary capacitance (the user's, 2026-11-05: option B, 2.5 um /
  15 pF; A, 5 um / 30 pF, gave 50 Hz -2.9 and 20 kHz -2.8 dB; C, 1.2 um / 15 pF, 50 Hz
  -0.2; UTC's catalog is met by all three): genome parameters, bounds 1-6 um, 10-40 pF.
- The console's B+ is an ideal source behind 100 ohm (provisional): the module's own RC
  decoupling is drawn, the console's supply isn't (the precedent: sideman_bd's rails).
- LEVEL's default in the circuit file equals the chain list's (0.2), as the V76's: the
  composed chain and `mic_print.py` use the file's.

### WP3. The AKG C12

AKG's multi-pattern tube condenser (1953-63): the CK12 dual-diaphragm capsule, its
backplate the signal electrode (C13 1000 pF to the grid), the front diaphragm grounded and
the rear diaphragm's DC voltage set from the remote unit S12 (nine positions on a resistor
ladder, 0 V omni to ~120 V figure-8, cardioid at the backplate's 60 V); a 6072 (= 12AY7)
section with its grid biased from the supply's return (N12K: R7 1k), T14/1 to 50 / 200 ohm.
Sources: `data/schematics/akg_c12/README.md`.

Steps:
1. Sources: the drawing "C12 + Power Supply C12" with the N12K and the S12 (U2), ~1959
   (coutant.org, courtesy John Warshaw); AKG's English brochure (cieri.net: the 6072
   version's data, response curves omni / cardioid-and-8 at 0 deg with cardioid 180 deg
   and 8 at 90 deg, polars of the three basic patterns); the early bilingual description
   (coutant.org: the 12AY7 version, 40 / 250 / 500 ohm); Haufe's T14/1 specification
   (11.5:1, 3.08 k / 61 ohm, 20.5 x 12 x 13 mm; its 400 kOhm / 350 mH at 1 kHz disputed on
   the forums); Austrian Audio's "The CK12 Capsule Demystified" (the 1954 patent's
   structure, membrane resonance 800-1500 Hz, gap 30-50 um, a ~50 um slit between the two
   resistance disks as the gradient resistance, a tuned capsule's ~-46 dBV/Pa). The
   brochure's response curves digitized to `data/datasheets/akg_c12_response.csv` with a
   provenance sidecar (its polars not: Notes).
2. The capsule `CK12@1` (kind `capsule`, form `dual`: the slit is the through resistance,
   the electrode's drilled holes the blind holes; its `body` for the entries): geometry in
   `published_points.yaml`, the unknowns bounded and fitted by `scripts/fit_ck12.py` (on
   `fit_k47.py`'s method) to AKG's curves and polars, the patterns by the rear's
   polarization (a C12 wiring in `varimu/mics/networks.py`: the backplate the output, both
   diaphragms AC-grounded, E_rear / E_front = 1 omni, 0 cardioid, -1 figure-8), into the
   C12's grid load; the sensitivity 1.0 mV/ubar unloaded over the amplifier's gain;
   `varimu fit-devices --only CK12`.
3. `config/circuits/akg_c12.yaml` from the drawing: the mic (R11-R17, C10-C13), the 12AY7's
   one section (the second's heater unpowered: 6.3 V at 175 mA, the brochure), T14/1 as a
   macro transformer sized from Haufe's figures at the 200 ohm strapping; the N12K's HV as
   a source behind its last RC section with its return through R7 1k (the grid bias, R10 /
   C6), its heater supply not drawn (DC); the S12 ladder, R20 / C20, R16 / C11 drawn; the
   pattern a nine-position switch of capsule instances, each with its rear polarization
   from the ladder (`derived:` values, checked against the DC solution in the test).
4. `tests/test_akg_c12.py`: builds, preflight, idle against the brochure (120 V at 0.7 mA,
   the backplate 60 V, the ladder's rear voltages, the bias by arithmetic), the
   sensitivity per pattern (1.0 mV/ubar +-1.5 dB, "equally high at all patterns"), the
   cardioid's front to back (>= 15 dB, the brochure; "better than 20").
5. The mic's checks (What "done" means): on-axis responses and polars against AKG's (the
   SM57's bar, or why not), its entry table computes (`varimu/rooms/entries.py`).
6. The list and the Room view: a mic's pattern as a first-order figure (a + (1 - a) cos;
   `varimu/chains.py` PATTERNS and varimu-app's `room::Pattern` gain figure-8 and the
   C12's intermediate positions); `akg_c12`'s entry (output, drop, the nine-position
   pattern, default cardioid); `compose_chain.py --all` (c12_clean, c12_ua610),
   `test_chain_matrix.py`, app fixtures, one draft render through a scene;
   `chain_status.py` 12 of 51.

Notes (2026-11-05, done):
- Sources: `data/schematics/akg_c12/README.md` (the drawing, AKG's English brochure with
  its curves and data, the early 12AY7 description, Haufe's T14/1 sheet, Austrian Audio's
  CK12 article; PNGs of each, the PDFs not committed). The drawing is 990 px wide: every
  value legible, the wiring read by eye on zooms; it prints **no voltages**. The 1953
  patent on the brochure (AT 180313) has no text on Google Patents and DEPATISnet refuses
  scripts: not read. The brochure's polar diagrams are not digitized (four line styles
  overlapping on a 876 px page; the on-axis direction is their 20 ring): the rear curves
  of the response chart (cardioid 180 deg, figure-8 90 deg) carry the directivity instead.
- `data/datasheets/akg_c12_response.csv` (+ `akg_c12.provenance.yaml`): omni 0 deg,
  cardioid / 8 0 deg (one curve, written for both), cardioid 180 deg, figure-8 90 deg,
  40 Hz-15 kHz, read from the page image (the rear curves told apart by course and by the
  labels' leaders; they cross near 400 Hz and 4 kHz).
- `config/circuits/akg_c12.yaml`: the capsule a nine-position switch of `capsule_dual`
  instances (`KC0`-`KC8`), each with its rear polarization `pol_rear_k*_v` = B+ / 2 x (1 -
  k / 4) (the model is linear in polarization); the DC network drawn too (the ladder RL1-
  RL8, 8 x 50 k, the wiper RW*, R20 / C20, R16 / C11), and the test checks the DC
  solution puts those polarizations on the electrodes. The supply: `VHV` (155 V, set for
  br's B+ 120 V) at C4's last capacitor, R6, C5, R8, C5 to B+; its return through R7 1 k
  gives the grid -1.08 V via R10 / C6, R11 / C10, R15. Idle: B+ 120.0, anode 56.5 V,
  0.65 mA (br: 0.7), the backplate 60.0 V. The 6072 is `12AY7@1` (one section; the second
  unheated per br's 175 mA heater).
- T14/1: haufe's 11.5 : 1, 3.08 k / 61 ohm; 8000 turns (provisional, from the DCR) on a
  provisional mumetall core; its primary inductance is disputed (haufe's 400 kOhm at 1 kHz
  = 64 H; a reproduction's ~160 H): the gap (`akg_c12.t14.gap_m`, genome, 4.8-26.6 um) is
  fitted to the omni curve's last octave, 9 um = 113 H (64 H gave -5.7 dB at 40 Hz, 160 H
  -0.8; AKG -2.8). The whole mic then reads -1.2 dB at 40 Hz: the published curve is
  steeper than one inductance gives.
- The capsule `CK12@1` (`scripts/fit_ck12.py` on fit_k47.py's helpers; reports/mics/
  ck12_fit.{png,json}): the C12's wiring as `varimu.mics.networks.backplate_response`
  (the backplate the output into C13 + the grid's Miller input, 42.7 pF || 125 MOhm).
  Fitted: tension 20.8 N/m (bounds from Austrian Audio's membrane resonance 800-1500 Hz
  on the 10 um Styroflex film: 1333 Hz), the gap 50 um (its bound, Austrian Audio's 30-50),
  the slit 1.59e7, the film 4.19e6 Pa s/m^3, 228 drilled holes per side 1.89 mm deep (the
  ~4 mm backplate's half), the stray capacitance 40 pF (its bound: the backplate to the
  grounded membrane rings, its leads; it brings the sensitivity down to AKG's). Body:
  radius 15.5 / rim 17 mm, spacing 4.1 mm (the backplates plus the gaps; 3.5 mm fit 0.04
  dB better), the rings flush. Fit rms 1.1 dB: omni 0 deg 0.9 rms (max 1.9 at 8 kHz),
  cardioid 0 deg 1.0 (2.0 at 14 kHz), cardioid 180 deg 2.9 (6.3 at 250 Hz, AKG's bump to
  -16 dB). Dead ends: tension up to 200 N/m fitted ~50 N/m and lost the low-frequency rear
  rejection (-8 dB at 50 Hz: the stiff rear diaphragm closes the gradient path), the K47's
  slack regime; blind holes deeper than half the backplate were unphysical.
- **The figure-8's side rejection is a known miss:** the model's halves are equal, so its
  90 deg null is exact (the plot: below -40 dB), AKG's -17 to -23 dB comes from the halves'
  differences (Austrian Audio: the two resistance disks differ). Not fitted, reported
  (`figure8_90_rms_db` ~20). Modelling it needs unequal halves in `dual_lumped`.
- The whole mic (tests/test_akg_c12.py, 2026-11-05): 10.2 / 10.5 / 10.9 / 11.2 / 11.5 mV/Pa
  at 1 kHz from omni to figure-8 (br: 10 +-1.5 dB, 'equally high at all patterns'); the
  cardioid's front / back 17.8 / 23.8 / 17.3 dB at 100 Hz / 1 kHz / 5 kHz (br: 15, 'better
  than 20'); on axis re 1 kHz within +-2 dB of AKG's curves from 40 Hz to 15 kHz (omni:
  40 Hz -1.2 vs -2.8, 8 kHz +0.5 vs +2.4, 10 kHz +2.5 vs +3.8; cardioid: 40 Hz -1.9 vs
  -3.8, 8 kHz +0.2 vs +2.0, 15 kHz +1.1 vs -0.7). The entry table computes
  (`varimu/rooms/entries.py`, ~3 min, cached).
- The list and the app: `varimu/chains.py` PATTERNS and varimu-app's
  `room::PATTERN_NAMES` are first-order figures by name (omni, wide omni, wide cardioid,
  broad cardioid, cardioid, supercardioid, hypercardioid, narrow figure-8, figure-8;
  `room::Pattern` the coefficient in eighths, `gain`); the Room view draws a figure-8
  family's lobes apart. `akg_c12`'s entry: output `out`, drop RLOAD, the nine positions,
  default cardioid. `c12_clean`, `c12_ua610` composed (the 10 others byte-identical). 94 dB
  SPL at 1 kHz: -23.5 dBFS peak into the 610 at its default 35 dB, -16.1 into clean; one
  draft render through a scratch scene (both chains, cardioid and figure-8) ran. The Room
  view's new drawing wasn't seen on a screen (clippy and the room tests only).
- Tests: `tests/test_akg_c12.py` (6), `test_chain_matrix.py`, `test_app_fixtures.py`
  (fixtures for `akg_c12`, `c12_clean`, `c12_ua610`; nothing else moved), varimu-circuit's
  `tests/agreement.rs`, varimu-app `room::` (the C12's patterns in `chain_list_reads`),
  `test_versions.py`, `test_capsule.py`.

Decisions:
- The pattern as nine capsule instances, each at its position's polarization, the DC
  network drawn and checked against them (the model is linear in polarization); a
  position change rebuilds, where the real unit fades over R20 / C20's 2 s.
- The model is the 1957 drawing's (6072, T14/1, 50 / 200 ohm), with the later brochure's
  data and curves; the first 12AY7 version (40 / 250 / 500 ohm) isn't modelled.
- The film is the first CK12's 10 um Styroflex (the C12 of 1957 may have had 9 um Mylar;
  the fit's tension absorbs the difference).
- T14/1's inductance fitted to the omni curve's low end (a genome parameter); the
  figure-8's side rejection left as a known miss.

### WP4. The op-amp preamps: the SSL 4000 E channel and the Tascam Portastudio

Both are op-amps only in the versions chosen (Decisions): no BJT, no JFET. The `opamp`
macro (single pole from A0 / GBW, clamp diodes at the swing) carries them.

**The SSL 4000 E** is the channel amplifier card 82E01 (SSL drawing T82001·71, rev. 16,
11-84): the mic XLR across the phantom feed R1 / R2 6K81, a pad (SW1: R3 13K7, R4 649,
R5 645, R6 165), the Jensen JT-115K-E (1:10; the drawing's lead colours Y / OR / BR / R and
its 150K load R7 are Jensen's), T1 (5534, non-inverting) and T9 (5534, inverting) with the
MIC GAIN pot 10K LIN between them (T1's feedback is the wiper-to-19 part over R9 619R, T9's
input the wiper-to-33 part plus R69 619R into R71 10K7: 0 to +50 dB, +20 more from the
transformer), then R46 100R, a J112 (RC1) as the input select, PHASE, and T4 (5534, the
channel input select, unity) into the channel. +-18 V rails.

**The Portastudio** is the Tascam 424 (mk1, 1991): the MIC/LINE jack (unbalanced 1/4",
-50 to -10 dBV) through R101 1k / R102 100k / C101 1500p on the IN PCB, then the mix PCB's
channel: C101 10u, R101 100k to the half-rail, U101A (uPC4570HA) non-inverting with R102
470k / C102 100p and the TRIM pot R103 10K (RD) with R104 100R; S101 (MIC/LINE / TAPE),
the EQ (U102B, HIGH 10 kHz / LOW 100 Hz shelves), the INPUT FADER R113 10K (A) into U102A.
One +10 V rail (M5237L), the op-amps referenced to its +5 V half (U703): about +-4 V of
swing, so it clips early.

Steps:
1. Sources: `data/schematics/ssl_4000e/README.md` (the 82E01 drawing, its two sheets, from
   ka-electronics; Jensen's JT-115K-E60 sheet, "electrically identical to our standard
   JT-115K-E", via the Wayback Machine; SSL's Revival 4000 "JT-115K-E, identical to the
   original 4000 E"; the 5534 from data/datasheets/opamps/), `data/schematics/tascam_424/
   README.md` (the 424 mk1 service manual from r-massive; the 144's and 244's drawings
   kept as the later discrete versions' sources; the uPC4570's figures added to
   data/datasheets/opamps/README.md).
2. The JT-115K-E as a macro transformer fitted to Jensen's figures (in test circuit 1,
   150 ohm source, 150k load): 19.75 dB of gain, 1.40 kOhm input, -0.26 dB at 20 Hz, -0.13
   at 20 kHz, -3 dB at 2.5 Hz and 90 kHz, 1% THD at 20 Hz at -2.5 dBu, 0.065% at -20 dBu,
   DCR 19.7 / 2465 ohm, Zo 17 kOhm (one figure per unknown: turns / gap, leakage,
   capacitance; `scripts/fit_jt115k.py`, the fit in the circuit file's sources).
3. `config/circuits/ssl_4000e.yaml` from 82E01: the controls `mic_gain` (rotation),
   `pad` (SW1), `phase`; `tests/test_ssl_4000e.py` (builds, preflight, the gain law against
   the arithmetic above, the pad's attenuation, the transformer standalone against
   Jensen's figures, PHASE's polarity).
4. Its profile (`varimu unit --circuit ssl_4000e`; preamp_suite.py if it fits, else
   `varimu/measure/ssl_suite.py`): gain range, response, THD against level, clip, input
   impedance.
5. `config/circuits/tascam_portastudio.yaml` from the 424 mk1 (the IN PCB, the channel to
   U102A's output, EQ and fader controls, TRIM; the +5 V half-rail as the op-amps'
   reference), `tests/test_tascam_portastudio.py`, its profile.
6. The list: both entries in `config/chains.yaml` (input, drop, settings),
   `compose_chain.py --all` (sm58_ssl, sm57_porta, sm58_porta), `test_chain_matrix.py`,
   app fixtures, one draft render through a scene; `chain_status.py` 15 of 51.

Notes (2026-11-05, done):
- Sources: `data/schematics/ssl_4000e/README.md` (the 82E01 drawing's parts by reference,
  Jensen's figures, the Revival 4000's; no file committed: SSL's notice on the drawing,
  URLs and sha256 there). ka-electronics also has `ssl_82E02.pdf` (the 02 EQ) and
  `ssl_82E10.pdf`; its directory listing is forbidden, so other cards are guesses by name.
  Jensen's own JT-115K-E pdf is gone from their site (404); the E60's is on the Wayback
  Machine (`web/2020id_/` gives the raw file).
- The JT-115K-E: `config/circuits/jt115k_test.yaml` (Jensen's test circuit 1) carries the
  same `jt_*` values as `ssl_4000e.yaml` (a test checks they are equal; change both).
  `scripts/fit_jt115k.py` (~5 min; `--hf` the high end alone) fits on
  `varimu/measure/transformer_sheet.py`: turns 1300 provisional (from the DCRs: 0.17 /
  0.063 mm wire), area 7.654e-6 m^2 (1% at 20 Hz at -2.5 dBu), gap 1.309 um (-3 dB at 2.5
  Hz from the 150 ohm EMF), leakage 165.7 uH and c_sec 134.5 pF (-0.13 dB at 20 kHz, -3 dB
  at 90 kHz). 90 kHz is past the 96 kHz grid's Nyquist: the high end is fitted on
  `varimu/measure/ac.py`, which now takes `Winding`s (a linear-core build; it agrees with
  the transient within 0.011 dB at 20 kHz; the transient reads 0.29 dB low at 40 kHz).
  Not targeted: gain 19.75 dB (= jensen), 20 Hz -0.19 dB (-0.26), Zin 1534 ohm (1400:
  the reflected 150k; the 1.4k may include the test fixture's loading), **20 Hz THD at
  -20 dBu 0.44% (jensen 0.065%): a known miss**: the fitted mumetall's low-field
  hysteresis makes the 20 Hz THD nearly level-independent (0.3-0.45% from -20 to -6 dBu);
  no turns / area / gap inside the DCRs and the 2.5 Hz corner gets near 0.065%. A refit of
  the material would move every render (the user's call, not made). 1 kHz THD 0.002%
  (0.001).
- `config/circuits/ssl_4000e.yaml`: the cold pin at ground (a chain's mic drives one
  side), so the phantom feed's C1 is left out (it would short R2; with a floating mic it
  carries only common mode); R1 + R2 (13.6k) load the mic. PAD per the drawing (R3 across
  the input, R4 / R5 in series, R6 across the primary): -18.2 dB. PHASE 0 = into T4's -
  (the whole in phase: T9 and T4 invert; the drawn position isn't legible). RC1 (J112) a
  50 ohm resistor. The 5534s: clean_pre's macro values, swing 15.4 V (+-18 V rails).
- The profile `varimu/measure/opamp_pre_suite.py` (one suite, a `PREAMPS` entry per
  circuit; `varimu unit --circuit ssl_4000e`, ~15 s warm; reports/units/ssl_nominal/):
  gain from a 150 ohm EMF 18.8-68.7 dB (the law + 18.72 dB of input stage within 0.01 dB
  at all 11 points), pad -18.2, response 20 Hz -0.35 / 20 kHz -0.28 dB at 37 dB, input
  impedance 1379 ohm at 1 kHz (1110 at 40 Hz, 903 at 10 kHz), output 9.7 ohm, THD 0.0002%
  at +4 dBu, 1% at +23.4 dBu (hard clip), 20 Hz at the least gain 0.44% / 0.60% at -20 /
  -2.5 dBu in. vs the Revival's (a reference): 3 of 5 (the pad's 20 dB and +-0.175 dB
  flatness missed).
- The chain: `ssl_4000e`'s entry (input `ia`, drop RSRC; MIC GAIN as rotations labelled by
  gain, default 0.3; PAD), sm58_ssl composed with `mic_gain_ssl: 0.9` (59 dB): 94 dB SPL
  1 kHz -18.45 dBFS peak (`mic_print.py --draft`); the 12 others byte-identical; a draft
  render through a scratch scene ran. Fixtures for `ssl_4000e`, `sm58_ssl`, `jt115k_test`
  exported (nothing else moved).
- The Portastudio: `data/schematics/tascam_424/README.md` (the 424 mk1 service manual's
  IN / MIX PCB and supply by part reference; the 144's and 244's drawings described for
  WP21; nothing committed), the uPC4570 in data/datasheets/opamps/README.md (Renesas'
  current sheet). `config/circuits/tascam_portastudio.yaml`: the jack's tip (`ia`) through
  the IN PCB's 1k / 100k || 1500p, U101A with TRIM, S101 at MIC/LINE onto R114 10k and the
  EQ's R106 22k (its far end as AC ground, provisional): the channel's output is the EQ's
  input; the EQ, the fader and U102A aren't modelled (flat at centre; the mic input is the
  Portastudio's character: its single +9.3 V rail). Every node about the half rail (an AC
  ground); the uPC4570 swing 2.44 V (+-4.64 V less the sheet's 1.6 V and the clamp diode):
  1% THD at +8.2 dBu, hard. Its own full scale: 0 dBFS = 3.081 V peak (+9 dBu), so a print
  reaches the machine's ceiling (on the V76's +24 dBu it would sit 15 dB down).
- TRIM (R103 10k "RD") is a reverse audio taper (provisional, taper_mid 0.1): the pot
  macro gained `reverse` (both builders, `parts.pot` / `parts::pot`; the taper read from
  end_b; absent = every existing pot bit for bit: fixtures and goldens unmoved). Gain from
  a 150 ohm EMF -0.2 to +39.7 dB, the law within 0.01 dB at 11 points (+18.9 at half);
  input impedance 49 kOhm at 1 kHz (10.6 k at 10 kHz: C101 1500p); response at -10 dBV out
  -0.25 dB at 20 kHz (nominal), -0.47 at +40 dB. Profile `varimu unit --circuit
  tascam_portastudio` (opamp_pre_suite's second entry: response at -8 dBu; ~7 s warm;
  reports/units/porta424_nominal/); vs the jack's -50 to -10 dBV: 2 of 2.
- The chains: `tascam_portastudio`'s entry (TRIM as rotations labelled by gain, default
  0.5); sm57_porta and sm58_porta with `trim_porta: 1.0` (40 dB): 94 dB SPL 1 kHz at -23.0
  / -22.2 dBFS peak. A chain's `defaults` are applied by scenes and the Room view, not
  written into the composed file (its controls keep the circuit's default): `mic_print.py`
  needs `--set`. A draft scene render of both ran. Fixtures for `tascam_portastudio`,
  `sm57_porta`, `sm58_porta` exported (nothing else moved).
- Tests: `tests/test_ssl_4000e.py` (9), `tests/test_tascam_portastudio.py` (5, the reverse
  pot included), `test_chain_matrix.py` (18), `test_app_fixtures.py` (60), varimu-circuit's
  tests (agreement included), varimu-app `room::` (12), clippy and fmt.

Decisions:
- The SSL's cold pin at ground with the phantom's C1 left out (above); PHASE 0 the
  in-phase position; RC1 a 50 ohm resistor; its 5534s on clean_pre's macro values.
- The JT-115K-E's 20 Hz low-level THD left as a known miss (mumetall's fit is the user's
  call; the options: a refit with a weaker Rayleigh region, or a second nickel material).
- The Portastudio's model ends at the EQ's input; its print scale is its own (+9 dBu).
- The Portastudio is the 424 mk1, not the 144 (1979: a 2SK68A JFET and two 2SA970 PNPs
  ahead of a 4558) or the 244 (1982: a JFET differential pair into a 4558): those need
  WP21's JFET (and the 144 WP10's BJT); the 424's mic input is one op-amp. A 144 / 244 can
  come after WP21 as a second Portastudio (the sources are kept).
- The SSL is the E-series 82E01 (transformer input), not the G-series' transformerless
  mic amp (its drawing isn't public here).

### WP5. The ribbon kind `ribbon_motor`

A ribbon is Olson's velocity microphone: a corrugated aluminium foil, loosely suspended
between two pole pieces, driven by the pressure difference between its faces; it is the
conductor itself (EMF = B l v), a fraction of an ohm, stepped up by a transformer. Olson's
complete mechanical circuit (SBE handbook Fig. 4.1.11, the RCA BK-11A): F1 -> R_L/2 ->
M_L/2 -> [the ribbon M_R + C_R || the slits M_S + R_S] -> M_L/2 -> R_L/2 -> F2 (R_L / M_L
the air load and the damping screens on both faces, the slits the ribbon's edge clearance
to the pole pieces, "nominally 0.005 in", a leak). Above resonance the ribbon is mass
controlled, v = (P1 - P2) A / (j w (M_R + M_L)) (Eq. 4.1.6). That is a moving-coil network
with a different diaphragm: the kind reuses `moving_coil`'s element kinds and its lumped
format, so both builders expand a ribbon with the moving-coil code they already agree on.

What is new: the moving element from the foil's geometry (mass, resistance, B l, the
tuning), the ribbon's length modes (a limp strip clamped at both ends: odd modes n couple to
a uniform pressure and a uniform field, mass M n^2 pi^2 / 8 each, in parallel through one
gyrator: their velocities sum into the EMF and the volume velocity, and above every mode
the bank is the whole mass), the pole-piece channel (a wide parallel-plate duct: plug-flow
mass and Crandall's boundary-layer resistance, `slit` with `wide_at_hz`), and the part
`ribbon_motor`. Its first instance is the RCA 44-BX's ribbon (AEA's R44 sheet gives the
original's ribbon: 1.8 um pure aluminium, 4.7 mm x 59.7 mm), provisional where nothing is
published and refitted in WP6 against the 44-BX's curves.

Steps:
1. Sources: `data/schematics/rca_44bx/README.md` (RCA IB-24267-5, the 44-BX's technical
   data: 30 / 150 / 250 ohm, -55 dBm at 10 dyn/cm^2; AEA's R44 sheet: the ribbon, 2.25 mV/Pa
   open circuit, 270 ohm; SBE handbook 4.1.3: Olson's circuit, the BK-11A's 0.65 T in a
   3.2 mm gap, 0.56 mg/cm^2, 0.2 ohm, ~30 Hz, 125 um clearance; Leckschat & David, DAGA
   2010: the motional impedance up to ~5x the DCR at resonance; emrr's strapping table).
2. `varimu/devices/ribbon.py`: geometry -> lumped (moving_coil's block: bl_tm, sd_m2,
   re_ohm, le_h, elements); moving_coil's element compile factored out and shared (R57 /
   R59 compile bit for bit unchanged); `slit` gains `wide_at_hz`; the element kind `ribbon`
   (the moving system, its modes in parallel, one gyrator).
3. The component `RIBBON_44BX@1` (`varimu fit-devices --only RIBBON_44BX`, a builder in
   library.py), the loaders (`load_ribbon_motor`; varimu-circuit's devices.rs), the part
   `ribbon_motor: [front, rear, plus, minus]` in both builders and symbol tables.
4. The step-up transformer as a design, `config/designs/rca_44bx_ot.yaml` (the ratio from
   the ribbon's resistance to the 250 ohm strapping; the 30 / 150 / 250 straps as
   windings), compiled and saved by varimu-components.
5. A test circuit `config/circuits/ribbon_test.yaml` (the ribbon, its transformer at 250
   ohm, a load); `tests/test_ribbon.py`: the formulas, Eq. 4.1.6 and E = B l v above
   resonance, the mode bank against the whole mass, the slit's leak, the motional
   impedance at resonance, circuitsim's transient against the AC solution; app fixtures
   (agreement in varimu-circuit).

Notes (2026-11-05, done):
- Sources: `data/schematics/rca_44bx/README.md`. RCA's whole instruction book is on
  coutant.org in two PDFs (44bx.pdf, the technical data; jumpers.pdf, Figs. 3-8: the
  polars, the M / V1 / V2 response, the schematics of the -H / -J / -K with the reactor, the
  parts): WP6's curves are there. Olson's own texts weren't readable online (the 1931 JASA
  paper; Elements 1940's OCR copies cut off before sec. 9.3): the SBE handbook's Fig.
  4.1.11 is the circuit used.
- The kind: `varimu/devices/ribbon.py` compiles `ribbon` / `magnet` / `leads` / `network`
  to moving_coil's lumped block, so the part `ribbon_motor` expands through
  `parts.moving_coil` (Python) and `moving_coil.rs` (Rust): nothing new to port, the
  builders' agreement is the existing code's (`ribbon_test.json` in varimu-circuit's
  fixtures passes). Loaders `load_ribbon_motor` / `Library::ribbon_motor`
  (`moving_coil_from_data(..., kind)`, `moving_coil::from_data_of`). moving_coil.py's
  per-element compile is `compile_element` now (shared); R57 / R59 compile byte for byte
  as before (checked on their published geometries). New element kinds for every
  transducer: `slit` with `wide_at_hz` (plug flow and Crandall's wall loss: the pole
  channel) and `radiation` (an opening's mass from the Rayleigh self-integral,
  `rectangle_self_integral`, checked against quadrature, || rho c / S).
- `RIBBON_44BX@1` (published_points.yaml "RIBBON_44BX"): foil 1.50 mg, 0.206 ohm (+0.01
  leads), B l 0.0388 T m, gyrator 138 ohm; the air load (radiation + half channel per face)
  86 kg/m^4 against the foil's 19, so the foil's 18 Hz rings at ~8 Hz in place (Olson's
  limp ribbon ~10 Hz); the motional impedance peaks at 6.3x the DC resistance at 8.4 Hz
  (Leckschat & David: "up to five times"); within 2 dB of Eq. 4.1.6 from 100 Hz to 20 kHz.
  Five odd length modes (to 162 Hz) plus the rest lumped: they move the response only
  below ~200 Hz.
- `RCA44BX_OT@1` (`config/designs/rca_44bx_ot.yaml`): EI-75 mumetall, 10 : 101 + 209
  turns (31:1; the tap B puts the 30 / 150 ohm straps at 26 / 114 ohm), primary 0.018 ohm
  9.6 mH, secondary 0.80 + 1.95 ohm; the formula's leakage (a negative star branch:
  coupled series leakages).
- `config/circuits/ribbon_test.yaml`: the ribbon into the transformer at 250 ohm (ib's
  cable table: out = C, the red lead; A grounded), open circuit; the primary's sense chosen
  by ib's "Phasing" (the drawing shows none: the first wiring was inverted, the test caught
  it). With a 20 mm front-to-back path: 2.3 mV/Pa at 300 Hz (aea's 2.25; ib's -55 dBm is
  1.78 mV/Pa open circuit, derived).
- `varimu/measure/ac.py` takes `Coupling` now (mutual inductance between branches; the
  transformer's coupled leakages): its transient-vs-AC test passes on ribbon_test.
- Symbols `RibbonMotor` ("MR") in both tables; `kicad/varimu.kicad_sym` and the editor's
  `symbols.json` regenerated (nothing else moved).
- Tests: `tests/test_ribbon.py` (13: formulas, Olson's mass-controlled ribbon with and
  without the air load, the modes, the slit's leak, the motional impedance, phasing and the
  31:1 step-up, noise skipping the leaks, kinds checked, circuitsim's transient against AC,
  ngspice's AC against ac.py within 1e-6); test_moving_coil, test_sm57 / sm58, test_kicad,
  test_editor, test_app_fixtures, test_capsule, test_ssl_4000e, test_clean_chain,
  test_versions (170 passed); varimu-circuit's tests (agreement included), clippy, fmt;
  varimu-app checks.
- For WP6: the 44-BX's M curve (ib Fig. 4: about +3 dB at ~65 Hz, a dip near 9 kHz to -4.5,
  a peak at ~12 kHz, -6 at 15 kHz; sbe: dips and peaks up there from "pole-piece shape or
  transverse resonances of the ribbon") and Fig. 3's polars to digitize; its body (the pole
  pieces as the baffle: the path D; the guards); the reactor and the V1 / V2 jumpers (ib
  Figs. 5-7); then fit the provisional unknowns one figure each (B to ib's -55 dBm; the
  tuning to the bass; the pole depth and D to the top; the slit's length; the screens).

Decisions:
- The ribbon reuses moving_coil's lumped format and part expansion (no third expansion to
  keep in agreement); a ribbon is a part of its own (`ribbon_motor`) for what it says.
- `resonance_hz` is the foil's own tuning (in vacuo, its mass alone); the air load is the
  network's, so the resonance in place comes out of it.
- The length modes as a limp string's (f_n = n f_1, odd modes only, the rest of the mass on
  the next one); no transverse modes (WP6 may need one for the 9 kHz dip).
- The radiation load as mass || rho c / S (a lumped approximation, within ~45% of the
  piston's low-frequency real part); the leads' inductance 50 nH (provisional).
- The transformer's tap at the least-squares compromise of the nominal 30 / 150 ohm labels.

### WP6-WP31

Steps are written when a WP starts (step 4 of "Start"). Pointers for each:
the mic's or preamp's sources (schematic, datasheet curves, service documents) first, as
in `data/schematics/neumann_u47/README.md` and `data/schematics/shure_sm57/README.md`.

## Owed

Batched checks (the targeted-tests rule): the full `pytest` (WP1-WP4 added thirteen
circuits and their app fixtures; WP3 added the device builder `build_ck12` to
`varimu/devices/library.py`, WP4 the pot's `reverse` to `varimu/circuit/{parts,builder}.py`
and windings to `varimu/measure/ac.py`, WP5 `varimu/devices/ribbon.py`, moving_coil.py's
shared `compile_element` and the `ribbon_motor` macro in `varimu/circuit/builder.py`: these
move every render's cache key, so the full suite re-renders; no device model, engine or existing circuit changed, every
fixture and golden unmoved, so `--verify` isn't due). Note: `ruff check .` reports one E501 in `varimu/phono/cylinder.py`, committed
before this session (not the chains' work), and `ruff format --check` one file, `scripts/derive_rhodes_5e3.py` (also not the chains').

## Decisions (the user's)

1. **Commits** (2026-11-05): every session commits its work at the end (see End, step 5).
2. **Where** (2026-11-05): on main, no branch or worktree.

## Session log

- 2026-11-05: the list curated (MIC_ROOM_PLAN.md "The chain list"), this plan and the
  `/chains` skill written; commits on main decided.
- 2026-11-05: WP0 done: `config/chains.yaml` + `varimu/chains.py`, `chain_status.py`,
  compose / test_chain_matrix / the Room view read it (the `use` note under the picker);
  8 of 51 available, the 8 files byte-identical.
- 2026-11-05: WP1 done: the Telefunken V72 from the Braunbuch V 72 and S 843 sheet 2 (BV
  191 pinned as `BV191@3`; choke and output transformer from Sowter's figures); the
  factory's trims and the supply by `scripts/v72_trim.py`; 8 of 14 specs met, the misses
  traced (WP1's Notes); U47 -> V72 composed: 9 of 51 available.
- 2026-11-05: WP2 done: the UA 610-A from Hinson's redraw of UA C-10068 (fetched by the
  user from GroupDIY), the UTC O-1 on its 50 ohm tap (UTC's catalog and terminal sheet),
  the PA-5946 from forum figures; T1's gap / capacitance the user's option B; its profile
  against the 2-610's figures as a reference; U47 -> UA 610 composed: 10 of 51 available.
- 2026-11-05: WP3 done: the AKG C12 from AKG's 1957 drawing (coutant.org) and brochure
  (cieri.net), its curves digitized; the capsule `CK12@1` fitted to them (`fit_ck12.py`,
  bounded by Austrian Audio's CK12 figures), T14/1 from Haufe's sheet, the nine patterns
  as capsule instances; the Room view's patterns now first-order figures; C12 -> clean
  and C12 -> UA 610 composed: 12 of 51 available.
- 2026-11-05: WP4 done: the SSL 4000 E's 82E01 channel amplifier card (ka-electronics)
  with the Jensen JT-115K-E fitted to Jensen's E60 sheet (`fit_jt115k.py`; the high end on
  `ac.py`, which now takes windings; the 20 Hz low-level THD a known miss), and the Tascam
  424 mk1's mic input (its service manual; the 144 / 244 need the JFET); one profile suite
  for both (`opamp_pre_suite.py`), the pot's `reverse` taper in both builders; SM58 -> SSL
  and SM57 / SM58 -> Portastudio composed: 15 of 51 available.
- 2026-11-05: WP5 done: the ribbon kind `ribbon_motor` after Olson's circuit (the SBE
  handbook's Fig. 4.1.11), compiled to moving_coil's format with the foil's odd length
  modes in parallel; `RIBBON_44BX@1` from AEA's ribbon figures and `RCA44BX_OT@1` (31:1,
  tapped as RCA's cable table); RCA's 44-BX instruction book found whole (coutant.org) for
  WP6; still 15 of 51 available.
