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

- **Chains available:** 10 of 51 (the built matrix: U47, SM57, SM58, omni x V76, clean;
  U47 -> V72, U47 -> UA 610; `uv run python scripts/chain_status.py`).
- **Done:** WP0 (2026-11-05): the list is `config/chains.yaml`, read by compose, the tests,
  `chain_status.py` and the app. WP1 (2026-11-05): the Telefunken V72
  (`config/circuits/telefunken_v72.yaml`, 8 of 14 of the Braunbuch's specs, the misses
  within 0.06 dB / 7% and traced; WP1's Notes). WP2 (2026-11-05): the UA 610-A
  (`config/circuits/ua_610.yaml` from Hinson's redraw of UA C-10068; WP2's Notes).
- **In progress:** none.
- **Next:** WP3 (the AKG C12), Start step 4: write its steps here, sources first (the C12's
  schematic and the CK12 capsule's published figures; the 6072 = `12AY7@1` exists; its
  transformer). The user fetches login-walled files on request: give each URL alone in a
  code block (WP2's Notes).
- **Waiting on the user:** listening to U47 -> UA 610 in the Room view (optional; the
  610's T1 bass / top end is the user's option B, both values genome parameters).

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
| 3 | AKG C12 (CK12 on `capsule_dual`; 6072 = `12AY7@1`; its transformer) | C12 -> clean, C12 -> 610 | L | next |
| 4 | The op-amp preamps: SSL 4000 E channel, Tascam Portastudio (sources decide: op-amps only, or wait for the BJT) | SM57 / SM58 -> Portastudio, SM58 -> SSL | M | |
| 5 | The ribbon kind `ribbon_motor` (ribbon in a gap compiled to R / L / C and a gyrator, like `moving_coil`; the step-up transformer as a design) | 0 | M | |
| 6 | RCA 44-BX | 44-BX -> V76, 44-BX -> 610 | L | |
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

### WP3-WP31

Steps are written when a WP starts (step 4 of "Start"). Pointers for each:
the mic's or preamp's sources (schematic, datasheet curves, service documents) first, as
in `data/schematics/neumann_u47/README.md` and `data/schematics/shure_sm57/README.md`.

## Owed

Batched checks (the targeted-tests rule): the full `pytest` (WP1 and WP2 added four
circuits and their app fixtures; they touched no device, engine or existing circuit, so
`--verify` isn't due). Note: `ruff check .` reports one E501 in `varimu/phono/cylinder.py`, committed
before this session (not the chains' work).

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
