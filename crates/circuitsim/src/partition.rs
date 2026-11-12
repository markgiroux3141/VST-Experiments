//! A circuit run as partitions on threads of their own, coupled through the
//! nodes they share with one sample of latency: a fast "draft" setting for real
//! time (`docs/CIRCUIT_SIM_PLAN.md`, M8). Off by default; the default is one
//! coupled solve of the whole circuit.
//!
//! The IR's sections are split by title: the named ones (`second`, e.g. the
//! power supplies; [`GROUP_BREAK`] separates groups, each a partition of its
//! own) and the rest (the "first" partition, which has the audio input and the
//! control inputs). A node two or more partitions have is owned by the
//! highest-numbered of them (so list the stiff drivers, the supplies, last):
//!
//! - the others see the node as a voltage source, the owner's voltage there;
//! - the owner sees a current injected into the node, the sum of the currents
//!   the others' sources take from their own sides.
//!
//! With one group this is the two-way split: the first partition sources every
//! shared node, the second owns them.
//!
//! All start at the DC operating point of the whole circuit, solved as one:
//! each partition's sources at those node voltages, their currents into the
//! owners (built in order, so a node's users are solved before its owner). Then
//! each sample, every partition steps at once on its own thread, with the
//! others' coupling values from the end of the previous sample: held, or
//! extrapolated linearly through the last two over the sample ([`Coupling`]).
//! They wait for each other once per sample, so the result doesn't depend on
//! timing (only the waits do).
//!
//! What it costs in accuracy is the lag: the coupling is explicit, first
//! order in the step (second with extrapolation), where the one solve is
//! implicit. Across supply rails with reservoir capacitors that is small;
//! measure it against the one solve (the draft study does).
//!
//! **Multi-rate parts.** A section with `substeps` m > 1 (the IR's `Section::substeps`)
//! runs as a part of its own (one per distinct m, after the named groups; or a named group
//! of multi-rate sections at one m, a part of its own: islands at the same rate on threads
//! of their own, the Minimoog's three oscillators) at m steps per
//! sample: what runs above the sample rate's Nyquist frequency (the Ampex 351's ~100 kc
//! bias oscillator). Within a sample it sees the others' values interpolated linearly over
//! its steps; it publishes the currents its sources take averaged over its steps (the
//! charge the sample moved, so what it draws at its own frequencies doesn't alias into the
//! slow parts' samples; a box filter, so it does alias: see the decimation below). It
//! owns no shared node unless it claims one (below): a node it has is owned by the
//! highest-numbered single-rate part with it (which must have one, with a DC path there).
//! It steps without local error control (its fixed fine step is the resolution; error
//! control's subdivisions there follow the fast signal's phase in a step and beat against
//! it: the 351's noise floor, docs/TAPE_PLAN.md "Speed").
//!
//! **A lagged multi-rate part** (its sections' `lag_samples` N; TAPE_SPEED_PLAN.md P2): one
//! that owns nothing, doesn't decimate and reads no other part's senses may read the others'
//! couplings N samples late, interpolated between published samples (the samples n - N and
//! n + 1 - N over step n -> n + 1), and so run up to N samples ahead of them. The others still
//! read it on time. For a cut through stiff rails only (the 351's record side meets the rest
//! at its supply's reservoirs); measured on the 351: no gain while its tape worker stalls the
//! audio part a block at a time.
//!
//! **Decimation and ownership (HYBRID_PHYSICS_PLAN.md H3a, M1).** A multi-rate section
//! with `decimate: fir` hands on everything through [`Decimator`] (an anti-alias low-pass
//! over its steps) instead: the currents, the voltages of nodes it owns and its probes,
//! ~6.4 samples late. Sections with the same substeps and decimation are one part. A
//! multi-rate section may claim shared nodes (`owns`): it publishes their voltages and is
//! fed their users' currents, interpolated over its steps like any other value it sees (an
//! island's low-impedance output into a high-impedance load: held from the other side, a
//! sample's lag diverged at a coupling capacitor into a grid). Ownership can then form a
//! loop (the island uses the supply, the supply's part uses the island's output), so the
//! DC start takes every part's currents from a solve with all its shared nodes held at the
//! whole circuit's DC voltages ([`crate::stream`]). Cut where little comes back: what a
//! part sees of the others is a sample (plus the decimator's delay) late, so a load that
//! draws a few percent of a fast loop's current from the other side detunes it (RCA's 884
//! sweep cut at its timing capacitor with the 6J7's 1 Mohm input outside: +7 cents at
//! 18.8 kHz). A grid the island owns returns nothing; so do stiff rails.
//!
//! **A single-rate claim.** A single-rate section may claim nodes too: a speaker's driver
//! keeping the radiating nodes its readout only senses, the readout a part of its own
//! (`varimu_circuit::speaker::readout_apart`; COMPONENT_EDITOR_PLAN.md C3's speed). The
//! readout sees the driver's voltages a sample late and draws nothing back (Vccs controls),
//! so the split costs only that lag. The DC start then solves with held nodes as for an
//! island's claim.
//!
//! **The audio input in a multi-rate part.** The input node may be a multi-rate part's
//! instead of the first's (a signal path cut through a capacitor into a high impedance
//! node isn't stable with a sample's lag: the Ampex 351's record side runs at the bias's
//! rate from its input on, coupled to the rest only through its supply rails). That
//! part reads the stream's input itself, the same samples and interpolation as the first
//! partition would, each of its steps a part of the sample's polynomial
//! ([`crate::transient::StepInput::sub`]); the first gets a stub input.
//!
//! **A tape's literal bias.** A `Tape` whose medium has `bias_substeps` m senses nodes
//! in the multi-rate part of m steps (the record head, with the oscillator's bias in its
//! current): they aren't shared nodes. That part publishes the sense after each of its
//! steps, and the tape's part gives them to its medium at its next step
//! ([`crate::transient::Transient::set_media_batch`]): a sample after they're computed,
//! as the medium's literal mode expects (`tape_stream.rs`).
//!
//! **A tape cut from its record head** (DELAY_PLAN.md, "partitioned at the medium"): a
//! `Tape` with the medium's own bias whose record head is in another single-rate part
//! senses it the same way, one value per sample, a sample late (the record gap's field at
//! t_n reaches the medium with step n + 1: ~10 us on a head distance of 133 ms). Its part
//! then holds the medium, the repro head and what follows, and meets the record side only
//! through the tape (and the shared nodes the rest of the circuit gives).

use std::collections::HashSet;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use crate::Error;
use crate::ir::{CircuitIr, Decimate, Element, GROUND, Probe, Resistor, Section, VoltageSource};
use crate::stream::Stream;
use crate::transient::{Method, Options, Output};

/// How a partition sees the other's values within a sample.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Coupling {
    /// The value at the sample's start, held.
    Hold,
    /// Through the last two values, extrapolated linearly over the sample.
    Extrapolate,
}

impl Coupling {
    pub const NAMES: [&'static str; 2] = ["hold", "extrapolate"];

    pub fn parse(name: &str) -> Result<Coupling, Error> {
        match name {
            "hold" => Ok(Coupling::Hold),
            "extrapolate" => Ok(Coupling::Extrapolate),
            _ => Err(Error::new(format!(
                "unknown partition coupling {name:?} (one of {:?})",
                Coupling::NAMES
            ))),
        }
    }
}

/// Prefix of the elements a split adds.
pub(crate) const SOURCE_PREFIX: &str = "VPART_";
/// The second partition's input node (it has no audio input).
const STUB_INPUT: &str = "partition_input";

/// Separates groups in a list of section titles: `[a, b, "|", c]` runs a and b on
/// one thread and c on another.
pub const GROUP_BREAK: &str = "|";

/// The titles split at [`GROUP_BREAK`] into groups (empty ones dropped).
pub fn groups(titles: &[String]) -> Vec<Vec<String>> {
    titles
        .split(|t| t == GROUP_BREAK)
        .filter(|g| !g.is_empty())
        .map(<[String]>::to_vec)
        .collect()
}

/// A node two or more parts have: the part that owns it (the highest-numbered
/// one with it: it sees the current the others draw there) and the others (they
/// see it as a voltage source, the owner's voltage).
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct SharedNode {
    pub name: String,
    pub owner: usize,
    pub users: Vec<usize>,
}

/// A tape's literal bias: medium `medium` (an element name) of part `reader` senses
/// `pos` - `neg`, nodes of multi-rate part `source` (`m` steps per sample).
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct RemoteSense {
    pub reader: usize,
    pub medium: String,
    pub source: usize,
    pub pos: String,
    pub neg: String,
    pub m: usize,
}

/// The nodes an element joins for the split: a tape senses its record head without
/// joining it (its `out` and capstan supply only), in its part or remotely.
fn split_nodes(e: &Element) -> Vec<&str> {
    match e {
        Element::Tape(t) => {
            let mut v = vec![t.out.as_str()];
            v.extend(t.supply.as_deref());
            v.extend(t.sync_out.as_deref());
            v
        }
        _ => e.nodes(),
    }
}

/// The circuit split into parts: part 0 the sections no group names (it keeps the
/// audio input and the control inputs), part g + 1 group g's.
#[derive(Debug, Clone)]
pub(crate) struct Split {
    pub parts: Vec<CircuitIr>,
    pub shared: Vec<SharedNode>,
    /// Each part's steps per sample (1, or a multi-rate part's `substeps`).
    pub substeps: Vec<usize>,
    /// Each part's decimation (a multi-rate part's `decimate`; None: the average).
    pub decimate: Vec<Option<Decimate>>,
    /// Each part's lag (the largest `lag_samples` of its sections; 0: lockstep).
    pub lag: Vec<usize>,
    /// Each part's own method (its multi-rate sections' `method`; None: the run's).
    pub method: Vec<Option<Method>>,
    /// Each part's tube tables (its multi-rate sections' `tube_tables`; None: the run's).
    pub tube_tables: Vec<Option<bool>>,
    /// Each part's section titles (part 0: none, it's the rest).
    pub titles: Vec<Vec<String>>,
    /// Tapes sensing a multi-rate part (the literal bias), in IR order.
    pub remote: Vec<RemoteSense>,
    /// The part with the audio input (0, or a multi-rate part).
    pub input_part: usize,
    /// Each control input's part (IR order): 0, or the multi-rate part with an audio
    /// control's node (it reads its samples as it reads the input).
    pub control_part: Vec<usize>,
}

impl Split {
    /// Part `p`'s owned shared nodes (indices into `shared`, in its order): its
    /// externals' second half and its outputs' first.
    pub fn owned(&self, p: usize) -> Vec<usize> {
        (0..self.shared.len())
            .filter(|&i| self.shared[i].owner == p && !self.shared[i].users.is_empty())
            .collect()
    }

    /// The shared nodes part `p` sees as sources (in `shared`'s order): its
    /// externals' first half and its outputs' second.
    pub fn sourced(&self, p: usize) -> Vec<usize> {
        (0..self.shared.len())
            .filter(|&i| self.shared[i].users.contains(&p))
            .collect()
    }
}

/// The circuit split by section title (`second`: groups separated by
/// [`GROUP_BREAK`]; one group is the two-way split).
pub(crate) fn split(ir: &CircuitIr, second: &[String]) -> Result<Split, Error> {
    let mut groups = groups(second);
    let mut part_of: Vec<Option<usize>> = vec![None; ir.sections.len()];
    for (g, titles) in groups.iter().enumerate() {
        for t in titles {
            let Some(i) = ir.sections.iter().position(|s| &s.title == t) else {
                return Err(Error::new(format!("partition: no section titled {t:?}")));
            };
            if part_of[i].is_some() {
                return Err(Error::new(format!("partition: {t:?} is in two groups")));
            }
            part_of[i] = Some(g + 1);
        }
    }
    // A named group of multi-rate sections is a multi-rate part of its own (its sections at
    // one count of steps and decimation: the Minimoog's oscillators, an island each); the
    // multi-rate sections no group names: a part per distinct count of steps and decimation,
    // after the named groups.
    let rate_of = |s: &crate::ir::Section| match s.substeps.filter(|&m| m > 1) {
        Some(m) => (m, s.decimate),
        None => (1, None),
    };
    let named = groups.len();
    let mut rates: Vec<(usize, Option<Decimate>)> = Vec::with_capacity(named);
    for titles in &groups {
        let mut r: Option<(usize, Option<Decimate>)> = None;
        for t in titles {
            let s = ir
                .sections
                .iter()
                .find(|s| &s.title == t)
                .expect("named above");
            let q = rate_of(s);
            if r.is_some_and(|r| r != q) {
                return Err(Error::new(format!(
                    "partition: {t:?} runs at another rate than its group's other sections"
                )));
            }
            r = Some(q);
        }
        rates.push(r.unwrap_or((1, None)));
    }
    for (i, s) in ir.sections.iter().enumerate() {
        let rate = rate_of(s);
        if rate.0 == 1 || part_of[i].is_some() {
            continue;
        }
        let g = rates[named..]
            .iter()
            .position(|&r| r == rate)
            .unwrap_or_else(|| {
                rates.push(rate);
                groups.push(Vec::new());
                rates.len() - named - 1
            });
        groups[named + g].push(s.title.clone());
        part_of[i] = Some(named + g + 1);
    }
    let n_parts = groups.len() + 1;
    let substeps: Vec<usize> = (0..n_parts)
        .map(|p| if p > 0 { rates[p - 1].0 } else { 1 })
        .collect();
    let decimate: Vec<Option<Decimate>> = (0..n_parts)
        .map(|p| if p > 0 { rates[p - 1].1 } else { None })
        .collect();
    let part = |i: usize| part_of[i].unwrap_or(0);
    let mut lag = vec![0usize; n_parts];
    for (i, s) in ir.sections.iter().enumerate() {
        let l = &mut lag[part(i)];
        *l = (*l).max(s.lag_samples.unwrap_or(0));
    }
    // A part's own method and tube tables: its sections' (they must agree).
    let mut method: Vec<Option<Method>> = vec![None; n_parts];
    let mut tube_tables: Vec<Option<bool>> = vec![None; n_parts];
    for (i, s) in ir.sections.iter().enumerate() {
        let p = part(i);
        if let Some(m) = &s.method {
            let m = Method::parse(m)?;
            if method[p].is_some_and(|q| q != m) {
                return Err(Error::new(format!(
                    "partition: {:?}'s method differs from its part's other sections'",
                    s.title
                )));
            }
            method[p] = Some(m);
        }
        if let Some(t) = s.tube_tables {
            if tube_tables[p].is_some_and(|q| q != t) {
                return Err(Error::new(format!(
                    "partition: {:?}'s tube_tables differ from its part's other sections'",
                    s.title
                )));
            }
            tube_tables[p] = Some(t);
        }
    }
    let secs: Vec<Vec<&Section>> = (0..n_parts)
        .map(|p| {
            ir.sections
                .iter()
                .enumerate()
                .filter(|(i, _)| part(*i) == p)
                .map(|(_, s)| s)
                .collect()
        })
        .collect();
    let nodes = |secs: &[&Section]| -> HashSet<String> {
        secs.iter()
            .flat_map(|s| s.elements.iter())
            .flat_map(split_nodes)
            .filter(|n| *n != GROUND)
            .map(str::to_string)
            .collect()
    };
    let node_sets: Vec<HashSet<String>> = secs.iter().map(|s| nodes(s)).collect();
    let input_part = if node_sets[0].contains(&ir.input_node) {
        0
    } else {
        let with: Vec<usize> = (1..n_parts)
            .filter(|&p| node_sets[p].contains(&ir.input_node))
            .collect();
        match with[..] {
            [q] if substeps[q] > 1 => q,
            _ => {
                return Err(Error::new(
                    "partition: the input node must stay in the first partition (or be one multi-rate part's alone)",
                ));
            }
        }
    };
    // Each control input's part: the first, or (an audio control: a second channel's
    // audio, read as the input is) the one multi-rate part with its node.
    let mut control_part = Vec::with_capacity(ir.controls.len());
    for c in &ir.controls {
        if node_sets[0].contains(&c.node) {
            control_part.push(0);
            continue;
        }
        let with: Vec<usize> = (1..n_parts)
            .filter(|&p| node_sets[p].contains(&c.node))
            .collect();
        match with[..] {
            [q] if c.audio && substeps[q] > 1 => control_part.push(q),
            _ => {
                return Err(Error::new(format!(
                    "partition: control {}'s node must stay in the first partition (an audio \
                     control's may be one multi-rate part's alone)",
                    c.name
                )));
            }
        }
    }
    // Tapes with the literal bias: their senses in the multi-rate part of their steps.
    let mut remote = Vec::new();
    for (p, ss) in secs.iter().enumerate() {
        for t in ss
            .iter()
            .flat_map(|s| s.elements.iter())
            .filter_map(|e| match e {
                Element::Tape(t) => Some(t),
                _ => None,
            })
        {
            let has = |q: usize, n: &str| n == GROUND || node_sets[q].contains(n);
            let Some(m) = t.medium.bias_substeps else {
                // The medium's own bias: in its part, or a single-rate part's, a sample late.
                if has(p, &t.sense_pos) && has(p, &t.sense_neg) {
                    continue;
                }
                let Some(q) = (0..n_parts)
                    .find(|&q| substeps[q] == 1 && has(q, &t.sense_pos) && has(q, &t.sense_neg))
                else {
                    return Err(Error::new(format!(
                        "partition: tape {}'s record head is in no single-rate part",
                        t.name
                    )));
                };
                if substeps[p] != 1 {
                    return Err(Error::new(format!(
                        "partition: tape {} must be in a single-rate part",
                        t.name
                    )));
                }
                remote.push(RemoteSense {
                    reader: p,
                    medium: t.name.clone(),
                    source: q,
                    pos: t.sense_pos.clone(),
                    neg: t.sense_neg.clone(),
                    m: 1,
                });
                continue;
            };
            let Some(q) = (0..n_parts)
                .find(|&q| substeps[q] == m && has(q, &t.sense_pos) && has(q, &t.sense_neg))
            else {
                return Err(Error::new(format!(
                    "partition: tape {}'s literal bias ({m} steps) senses no multi-rate part of {m} steps",
                    t.name
                )));
            };
            if substeps[p] != 1 {
                return Err(Error::new(format!(
                    "partition: tape {} must be in a single-rate part",
                    t.name
                )));
            }
            remote.push(RemoteSense {
                reader: p,
                medium: t.name.clone(),
                source: q,
                pos: t.sense_pos.clone(),
                neg: t.sense_neg.clone(),
                m,
            });
        }
    }
    // Nodes a multi-rate part claims (`Section::owns`).
    let mut claims: Vec<(String, usize)> = Vec::new();
    for (i, s) in ir.sections.iter().enumerate() {
        let p = part(i);
        for n in s.owns.iter().flatten() {
            if !node_sets[p].contains(n) {
                return Err(Error::new(format!(
                    "partition: {:?} owns {n}, a node it doesn't have",
                    s.title
                )));
            }
            if claims.iter().any(|(m, q)| m == n && *q != p) {
                return Err(Error::new(format!(
                    "partition: node {n} is owned by two multi-rate parts"
                )));
            }
            claims.push((n.clone(), p));
        }
    }
    // Shared nodes in order of first appearance in the IR.
    let mut shared: Vec<SharedNode> = Vec::new();
    for e in ir.elements() {
        for n in split_nodes(e) {
            if shared.iter().any(|s| s.name == n) {
                continue;
            }
            let with: Vec<usize> = (0..n_parts).filter(|&p| node_sets[p].contains(n)).collect();
            if with.len() >= 2 {
                // The multi-rate part claiming it, or the highest-numbered single-rate part
                // with it (a multi-rate part owns only what it claims).
                let claimed = claims.iter().find(|(m, _)| m == n).map(|&(_, q)| q);
                let Some(owner) =
                    claimed.or_else(|| with.iter().rev().copied().find(|&p| substeps[p] == 1))
                else {
                    return Err(Error::new(format!(
                        "partition: node {n} is shared by multi-rate parts only"
                    )));
                };
                shared.push(SharedNode {
                    name: n.to_string(),
                    owner,
                    users: with.iter().copied().filter(|&p| p != owner).collect(),
                });
            }
        }
    }
    // A claimed node no other part has stays the claimant's own (a switch can leave an
    // island's output unused: the Minimoog's rectangle with its waveform switch elsewhere);
    // one the claimant doesn't have is a mistake.
    if let Some((n, _)) = claims
        .iter()
        .find(|(n, q)| !shared.iter().any(|s| &s.name == n) && !node_sets[*q].contains(n))
    {
        return Err(Error::new(format!(
            "partition: node {n} is owned (`owns`) but its part doesn't have it"
        )));
    }
    for p in 1..n_parts {
        if !shared.iter().any(|s| s.owner == p || s.users.contains(&p)) {
            return Err(Error::new(format!(
                "partition: {:?} shares no node with the rest",
                groups[p - 1]
            )));
        }
    }
    // Models a part's devices use (unused ones are harmless, but keep it tidy).
    let used = |secs: &[&Section]| -> Vec<_> {
        let names: HashSet<&str> = secs
            .iter()
            .flat_map(|s| s.elements.iter())
            .filter_map(|e| match e {
                Element::Device(d) => Some(d.model.as_str()),
                _ => None,
            })
            .collect();
        ir.models
            .iter()
            .filter(|m| names.contains(m.name()))
            .cloned()
            .collect()
    };
    let mut parts = Vec::with_capacity(n_parts);
    for p in 0..n_parts {
        // A part runs at its own step: its sections' substeps are spent. A tape's literal
        // bias is sensed in another part (ground here; the part feeds it).
        let mut sections: Vec<Section> = secs[p]
            .iter()
            .map(|s| Section {
                substeps: None,
                decimate: None,
                owns: None,
                lag_samples: None,
                method: None,
                tube_tables: None,
                elements: s
                    .elements
                    .iter()
                    .map(|e| match e {
                        Element::Tape(t) if remote.iter().any(|r| r.medium == t.name) => {
                            Element::Tape(crate::ir::Tape {
                                sense_pos: GROUND.into(),
                                sense_neg: GROUND.into(),
                                ..t.clone()
                            })
                        }
                        _ => e.clone(),
                    })
                    .collect(),
                ..(*s).clone()
            })
            .collect();
        let sourced: Vec<&SharedNode> = shared.iter().filter(|s| s.users.contains(&p)).collect();
        if !sourced.is_empty() {
            sections.push(Section {
                title: "partition: the shared nodes' voltages".into(),
                substeps: None,
                decimate: None,
                owns: None,
                lag_samples: None,
                method: None,
                tube_tables: None,
                elements: sourced
                    .iter()
                    .map(|s| {
                        Element::VoltageSource(VoltageSource {
                            name: format!("{SOURCE_PREFIX}{}", s.name),
                            pos: s.name.clone(),
                            neg: GROUND.into(),
                            dc_v: 0.0,
                        })
                    })
                    .collect(),
            });
        }
        if p != input_part {
            sections.push(Section {
                title: "partition: input stub".into(),
                substeps: None,
                decimate: None,
                owns: None,
                lag_samples: None,
                method: None,
                tube_tables: None,
                elements: vec![Element::Resistor(Resistor {
                    name: "RPART_INPUT".into(),
                    a: STUB_INPUT.into(),
                    b: GROUND.into(),
                    r_ohm: 1e3,
                })],
            });
        }
        // A probe comes from the part with its node; a shared node's from its owner.
        let probes = ir
            .probes
            .iter()
            .filter(|pr| {
                let Probe::Voltage { node } = pr;
                if node == GROUND {
                    return true;
                }
                match shared.iter().find(|s| &s.name == node) {
                    Some(s) => s.owner == p,
                    None => node_sets[p].contains(node),
                }
            })
            .cloned()
            .collect();
        parts.push(CircuitIr {
            version: ir.version,
            title: format!("{} (partition {p})", ir.title),
            input_node: if p == input_part {
                ir.input_node.clone()
            } else {
                STUB_INPUT.into()
            },
            controls: ir
                .controls
                .iter()
                .zip(&control_part)
                .filter(|(_, q)| **q == p)
                .map(|(c, _)| c.clone())
                .collect(),
            heaters: ir.heaters.clone(),
            // Every part keeps the noise spec (streams are keyed by element name), with the
            // mains wander on the mains sources it has.
            noise: ir.noise.as_ref().map(|n| {
                let has = |m: &String| {
                    sections
                        .iter()
                        .flat_map(|s| s.elements.iter())
                        .any(|e| matches!(e, Element::SineSource(v) if &v.name == m))
                };
                let mains: Vec<String> =
                    n.mains_sources.iter().filter(|m| has(m)).cloned().collect();
                // The wander's rms stays (heated cathodes follow it in every part).
                crate::ir::NoiseSpec {
                    mains_sources: mains,
                    ..n.clone()
                }
            }),
            probes,
            models: used(&sections.iter().collect::<Vec<_>>()),
            sections,
        });
    }
    // A tape's tracks read each other (crosstalk, `crate::media::crosstalk_pairs`): one
    // part holds every track of a group.
    let mut group_part: Vec<(&str, usize)> = Vec::new();
    for (q, part) in parts.iter().enumerate() {
        for e in part.elements() {
            let Element::Tape(t) = e else { continue };
            let Some(x) = &t.medium.crosstalk else {
                continue;
            };
            match group_part.iter().find(|(g, _)| *g == x.group) {
                Some(&(_, q0)) if q0 != q => {
                    return Err(Error::new(format!(
                        "partition: the tracks of tape {} are in different parts (keep a \
                         crosstalk group's repro heads together)",
                        x.group
                    )));
                }
                Some(_) => {}
                None => group_part.push((&x.group, q)),
            }
        }
    }
    let mut titles = vec![Vec::new()];
    titles.extend(groups);
    Ok(Split {
        parts,
        shared,
        substeps,
        decimate,
        lag,
        method,
        tube_tables,
        titles,
        remote,
        input_part,
        control_part,
    })
}

/// A multi-rate part's decimation (`Decimate::Fir`): a linear-phase low-pass over its
/// steps, evaluated once per sample, for every value it hands on (its couplings, its
/// probes). Kaiser-windowed sinc at the part's rate (m steps per sample): the passband to
/// a quarter of the sample rate, the stopband from three quarters (what folds into the
/// passband at the sample rate), [`Decimator::ATTENUATION_DB`] down; the taps sum to 1
/// (DC passes exactly: the charge a current moves is kept). Its delay is (taps - 1) / 2
/// steps, ~6.4 samples at any m.
#[derive(Debug, Clone)]
pub struct Decimator {
    /// Taps, `h[0]` on the newest step.
    h: Vec<f64>,
    /// Per channel, the last `h.len()` steps (a ring at `pos`).
    hist: Vec<Vec<f64>>,
    pos: usize,
}

impl Decimator {
    pub const ATTENUATION_DB: f64 = 100.0;

    /// The taps for m steps per sample.
    pub fn taps(m: usize) -> Vec<f64> {
        // Kaiser's formulas land up to ~1 dB short at the stopband's edge: 3 dB of margin.
        let a = Self::ATTENUATION_DB + 3.0;
        // Transition from 0.25 to 0.75 of the sample rate, in cycles per step.
        let width = 0.5 / m as f64;
        let mut n = ((a - 8.0) / (2.285 * 2.0 * std::f64::consts::PI * width)).ceil() as usize + 1;
        n |= 1; // odd: a whole-step delay
        let beta = 0.1102 * (a - 8.7);
        let fc = 0.5 / m as f64; // half the sample rate, in cycles per step
        let mid = (n - 1) as f64 / 2.0;
        let i0 = |x: f64| {
            // Bessel I0 by its series (converges fast for the beta here)
            let (mut sum, mut term, mut k) = (1.0f64, 1.0f64, 1.0f64);
            loop {
                term *= (x / (2.0 * k)).powi(2);
                sum += term;
                if term < 1e-17 * sum {
                    return sum;
                }
                k += 1.0;
            }
        };
        let w0 = i0(beta);
        let mut h: Vec<f64> = (0..n)
            .map(|i| {
                let t = i as f64 - mid;
                let sinc = if t == 0.0 {
                    2.0 * fc
                } else {
                    (2.0 * std::f64::consts::PI * fc * t).sin() / (std::f64::consts::PI * t)
                };
                let r = t / mid;
                sinc * i0(beta * (1.0 - r * r).max(0.0).sqrt()) / w0
            })
            .collect();
        let sum: f64 = h.iter().sum();
        for x in &mut h {
            *x /= sum;
        }
        h
    }

    /// Its delay in steps (whole: the taps are odd in number).
    pub fn delay_steps(m: usize) -> usize {
        (Self::taps(m).len() - 1) / 2
    }

    /// For m steps per sample, its channels starting at `init` (the DC point: the filter
    /// as if it had run there forever).
    pub(crate) fn new(m: usize, init: &[f64]) -> Decimator {
        let h = Self::taps(m);
        let hist = init.iter().map(|&v| vec![v; h.len()]).collect();
        Decimator { h, hist, pos: 0 }
    }

    /// One step's values, a value per channel.
    pub(crate) fn push(&mut self, values: impl IntoIterator<Item = f64>) {
        for (c, v) in self.hist.iter_mut().zip(values) {
            c[self.pos] = v;
        }
        self.pos = (self.pos + 1) % self.h.len();
    }

    /// Channel `ch`'s output at the latest step.
    pub(crate) fn output(&self, ch: usize) -> f64 {
        let (c, n) = (&self.hist[ch], self.h.len());
        // newest at pos - 1
        let mut acc = 0.0;
        let mut j = (self.pos + n - 1) % n;
        for &t in &self.h {
            acc += t * c[j];
            j = if j == 0 { n - 1 } else { j - 1 };
        }
        acc
    }
}

/// Values one partition publishes per sample, read by the others: a ring of `depth`
/// samples (three in lockstep: the reader is at most one sample behind the writer; more
/// when a part reads the others late, `Options::multirate_lag`).
pub(crate) struct Ring {
    slots: Vec<AtomicU64>,
    width: usize,
    depth: usize,
    /// Samples published (sample n is in slot n % depth).
    done: AtomicUsize,
}

impl Ring {
    pub(crate) fn new(width: usize, depth: usize) -> Ring {
        Ring {
            slots: (0..depth * width).map(|_| AtomicU64::new(0)).collect(),
            width,
            depth,
            done: AtomicUsize::new(0),
        }
    }

    pub(crate) fn publish(&self, n: usize, values: &[f64]) {
        let s = (n % self.depth) * self.width;
        for (slot, v) in self.slots[s..s + self.width].iter().zip(values) {
            slot.store(v.to_bits(), Ordering::Relaxed);
        }
        self.done.store(n + 1, Ordering::Release);
    }

    /// Whether sample `n` is published.
    pub(crate) fn published(&self, n: usize) -> bool {
        self.done.load(Ordering::Acquire) > n
    }

    /// Slot `slot` of sample `n`.
    pub(crate) fn value(&self, n: usize, slot: usize) -> f64 {
        f64::from_bits(self.slots[(n % self.depth) * self.width + slot].load(Ordering::Relaxed))
    }
}

/// Run `ir` partitioned (see the module docs): the sections titled in
/// `second` on a thread of their own. Same input, step and options as
/// [`crate::simulate_with_progress`] (DK solver and a diagonally implicit
/// method only): a [`Stream`] fed the whole input. `progress` is called from
/// the calling thread, which runs the first partition. The output has the IR's
/// probes in its order; the stats are the first partition's.
#[allow(clippy::too_many_arguments)]
pub fn simulate_partitioned(
    ir: &CircuitIr,
    second: &[String],
    coupling: Coupling,
    input: &[f64],
    h: f64,
    opts: &Options,
    every: usize,
    progress: impl FnMut(usize) -> Result<(), Error>,
) -> Result<Output, Error> {
    simulate_partitioned_controls(ir, second, coupling, input, &[], h, opts, every, progress)
}

/// [`simulate_partitioned`] with the control inputs' samples (IR order, each as
/// long as `input`).
#[allow(clippy::too_many_arguments)]
pub fn simulate_partitioned_controls(
    ir: &CircuitIr,
    second: &[String],
    coupling: Coupling,
    input: &[f64],
    controls: &[&[f64]],
    h: f64,
    opts: &Options,
    every: usize,
    progress: impl FnMut(usize) -> Result<(), Error>,
) -> Result<Output, Error> {
    simulate_partitioned_notes(
        ir,
        second,
        coupling,
        input,
        controls,
        &[],
        h,
        opts,
        every,
        progress,
    )
}

/// [`simulate_partitioned_controls`] with a keyboard's events for the media played by keys
/// (a harp, in the first part): (input sample, event) in order, as
/// [`crate::transient::simulate_notes`] takes them.
#[allow(clippy::too_many_arguments)]
pub fn simulate_partitioned_notes(
    ir: &CircuitIr,
    second: &[String],
    coupling: Coupling,
    input: &[f64],
    controls: &[&[f64]],
    notes: &[(usize, crate::media::NoteEvent)],
    h: f64,
    opts: &Options,
    every: usize,
    mut progress: impl FnMut(usize) -> Result<(), Error>,
) -> Result<Output, Error> {
    let every = every.max(1);
    crate::transient::check_notes(notes)?;
    crate::transient::check_controls(ir, controls, input.len())?;
    if let Some(i) = input.iter().position(|u| !u.is_finite()) {
        return Err(Error::new(format!("input sample {i} is not finite")));
    }
    let Some((&u0, rest)) = input.split_first() else {
        return Err(Error::new("partition: empty input"));
    };
    if second.is_empty() && !ir.multirate() {
        return Err(Error::new(
            "partition: no sections named for the second thread",
        ));
    }
    let c0: Vec<f64> = controls.iter().map(|c| c[0]).collect();
    let mut stream = Stream::with_controls(ir, second, coupling, h, opts, u0, &c0)?;
    // Each chunk's notes at their offsets into it (the chunk starts at sample a).
    let mut notes = notes.iter().peekable();
    let mut values: Vec<Vec<f64>> = stream
        .initial()
        .into_iter()
        .map(|v| {
            let mut s = Vec::with_capacity(input.len());
            s.push(v);
            s
        })
        .collect();
    let mut add = |vals: Vec<Vec<f64>>| {
        for (v, mut x) in values.iter_mut().zip(vals) {
            v.append(&mut x);
        }
    };
    for (j, chunk) in rest.chunks(every).enumerate() {
        let (a, b) = (1 + j * every, 1 + j * every + chunk.len());
        let ctl: Vec<&[f64]> = controls.iter().map(|c| &c[a..b]).collect();
        let mut here = Vec::new();
        while let Some(&&(at, ev)) = notes.peek() {
            if at >= b {
                break;
            }
            here.push((at.saturating_sub(a), ev));
            notes.next();
        }
        stream.queue_notes(&here)?;
        add(stream.process_with(chunk, &ctl)?);
        if every < input.len() {
            progress(((j + 1) * every + 1).min(input.len()))?;
        }
    }
    add(stream.finish()?);
    Ok(Output {
        names: stream.names().to_vec(),
        values,
        stats: stream.stats().clone(),
    })
}

#[cfg(test)]
mod tests {
    use super::Decimator;

    /// |H(f)| of taps `h` at `f` cycles per step.
    fn gain(h: &[f64], f: f64) -> f64 {
        let (mut re, mut im) = (0.0, 0.0);
        for (i, &t) in h.iter().enumerate() {
            let w = 2.0 * std::f64::consts::PI * f * i as f64;
            re += t * w.cos();
            im -= t * w.sin();
        }
        (re * re + im * im).sqrt()
    }

    #[test]
    fn the_decimator_passes_the_band_and_stops_what_folds_into_it() {
        for m in [4usize, 8, 16, 32] {
            let h = Decimator::taps(m);
            assert_eq!(h.len() % 2, 1);
            assert!((h.iter().sum::<f64>() - 1.0).abs() < 1e-14, "m {m}: DC");
            assert!(
                h.iter()
                    .zip(h.iter().rev())
                    .all(|(a, b)| (a - b).abs() < 1e-18),
                "symmetric"
            );
            // f in fractions of the sample rate: cycles per step = f / m
            for k in 0..=100 {
                let f = 0.25 * k as f64 / 100.0;
                let g = gain(&h, f / m as f64);
                assert!((g - 1.0).abs() < 2e-5, "m {m}: passband {f} fs: {g}");
            }
            for k in 0..=2000 {
                let f = 0.75 + (m as f64 / 2.0 - 0.75) * k as f64 / 2000.0;
                let db = 20.0 * gain(&h, f / m as f64).log10();
                assert!(
                    db < -Decimator::ATTENUATION_DB + 1.0,
                    "m {m}: stopband {f} fs: {db} dB"
                );
            }
            // ~6.4 samples late at any m
            let d = Decimator::delay_steps(m) as f64 / m as f64;
            assert!((6.0..7.0).contains(&d), "m {m}: delay {d} samples");
        }
    }

    #[test]
    fn the_decimator_starts_at_its_initial_values() {
        let mut d = Decimator::new(8, &[3.0, -1.0]);
        assert!((d.output(0) - 3.0).abs() < 1e-14 && (d.output(1) + 1.0).abs() < 1e-14);
        for _ in 0..1000 {
            d.push([5.0, 2.0]);
        }
        assert!((d.output(0) - 5.0).abs() < 1e-13 && (d.output(1) - 2.0).abs() < 1e-13);
    }
}
