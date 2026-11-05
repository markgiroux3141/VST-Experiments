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

- **Chains available:** 8 of 51 (the built matrix: U47, SM57, SM58, omni x V76, clean;
  `uv run python scripts/chain_status.py`).
- **Done:** WP0 (2026-11-05): the list is `config/chains.yaml`, read by compose, the tests,
  `chain_status.py` and the app.
- **In progress:** none.
- **Next:** WP1 (the Telefunken V72), Start step 4: write its steps here, sources first
  (the V72's schematic and the Braunbuch's figures; BV 191 is compiled: `BV191@2`, fitted
  to the V72's figures in COMPONENT_EDITOR_PLAN.md C2 step 5).
- **Waiting on the user:** nothing.

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
| 1 | Telefunken V72 (two EF804S; BV 191 is its input transformer, already compiled) | U47 -> V72 | M | next |
| 2 | Universal Audio 610 | U47 -> 610 | M | |
| 3 | AKG C12 (CK12 on `capsule_dual`; 6072 = `12AY7@1`; its transformer) | C12 -> clean, C12 -> 610 | L | |
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

### WP1-WP31

Steps are written when a WP starts (step 4 of "Start"). Pointers for each:
the mic's or preamp's sources (schematic, datasheet curves, service documents) first, as
in `data/schematics/neumann_u47/README.md` and `data/schematics/shure_sm57/README.md`.

## Owed

Batched checks (the targeted-tests rule): none (WP0 touched no circuit, device or
fixture; its targeted tests and `cargo test -p varimu-app --lib room::` passed).

## Decisions (the user's)

1. **Commits** (2026-11-05): every session commits its work at the end (see End, step 5).
2. **Where** (2026-11-05): on main, no branch or worktree.

## Session log

- 2026-11-05: the list curated (MIC_ROOM_PLAN.md "The chain list"), this plan and the
  `/chains` skill written; commits on main decided.
- 2026-11-05: WP0 done: `config/chains.yaml` + `varimu/chains.py`, `chain_status.py`,
  compose / test_chain_matrix / the Room view read it (the `use` note under the picker);
  8 of 51 available, the 8 files byte-identical.
