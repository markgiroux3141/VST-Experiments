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
//! runs as a part of its own (one per distinct m, after the named groups) at m steps per
//! sample: what runs above the sample rate's Nyquist frequency (the Ampex 351's ~100 kc
//! bias oscillator). Within a sample it sees the others' values interpolated linearly over
//! its steps; it publishes the currents its sources take averaged over its steps (the
//! charge the sample moved, so what it draws at its own frequencies doesn't alias into the
//! slow parts' samples). It owns no shared node: a node it has is owned by the
//! highest-numbered single-rate part with it (which must have one, with a DC path there).
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

use std::collections::HashSet;
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};

use crate::Error;
use crate::ir::{CircuitIr, Element, GROUND, Probe, Resistor, Section, VoltageSource};
use crate::stream::Stream;
use crate::transient::{Options, Output};

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

/// The nodes an element joins for the split: a tape with the literal bias senses its
/// record head remotely (its `out` only).
fn split_nodes(e: &Element) -> Vec<&str> {
    match e {
        Element::Tape(t) if t.medium.bias_substeps.is_some() => vec![t.out.as_str()],
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
    /// Each part's section titles (part 0: none, it's the rest).
    pub titles: Vec<Vec<String>>,
    /// Tapes sensing a multi-rate part (the literal bias), in IR order.
    pub remote: Vec<RemoteSense>,
    /// The part with the audio input (0, or a multi-rate part).
    pub input_part: usize,
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
    // Multi-rate sections: a part per distinct count of steps, after the named groups.
    let named = groups.len();
    let mut rates: Vec<usize> = Vec::new();
    for (i, s) in ir.sections.iter().enumerate() {
        let Some(m) = s.substeps.filter(|&m| m > 1) else {
            continue;
        };
        if part_of[i].is_some() {
            return Err(Error::new(format!(
                "partition: {:?} has substeps (a part of its own): don't name it",
                s.title
            )));
        }
        let g = rates.iter().position(|&r| r == m).unwrap_or_else(|| {
            rates.push(m);
            groups.push(Vec::new());
            rates.len() - 1
        });
        groups[named + g].push(s.title.clone());
        part_of[i] = Some(named + g + 1);
    }
    let n_parts = groups.len() + 1;
    let substeps: Vec<usize> = (0..n_parts)
        .map(|p| if p > named { rates[p - named - 1] } else { 1 })
        .collect();
    let part = |i: usize| part_of[i].unwrap_or(0);
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
    if let Some(c) = ir.controls.iter().find(|c| !node_sets[0].contains(&c.node)) {
        return Err(Error::new(format!(
            "partition: control {}'s node must stay in the first partition",
            c.name
        )));
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
            let Some(m) = t.medium.bias_substeps else {
                continue;
            };
            let has = |q: usize, n: &str| n == GROUND || node_sets[q].contains(n);
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
    // Shared nodes in order of first appearance in the IR.
    let mut shared: Vec<SharedNode> = Vec::new();
    for e in ir.elements() {
        for n in split_nodes(e) {
            if shared.iter().any(|s| s.name == n) {
                continue;
            }
            let with: Vec<usize> = (0..n_parts).filter(|&p| node_sets[p].contains(n)).collect();
            if with.len() >= 2 {
                // The highest-numbered single-rate part with it (a multi-rate part owns none).
                let Some(&owner) = with.iter().rev().find(|&&p| substeps[p] == 1) else {
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
                elements: s
                    .elements
                    .iter()
                    .map(|e| match e {
                        Element::Tape(t) if t.medium.bias_substeps.is_some() => {
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
            controls: if p == 0 {
                ir.controls.clone()
            } else {
                Vec::new()
            },
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
    let mut titles = vec![Vec::new()];
    titles.extend(groups);
    Ok(Split {
        parts,
        shared,
        substeps,
        titles,
        remote,
        input_part,
    })
}

/// Values one partition publishes per sample, read by the other: a ring of
/// three samples (the reader is at most one sample behind the writer).
pub(crate) struct Ring {
    slots: Vec<AtomicU64>,
    width: usize,
    /// Samples published (sample n is in slot n % 3).
    done: AtomicUsize,
}

impl Ring {
    pub(crate) fn new(width: usize) -> Ring {
        Ring {
            slots: (0..3 * width).map(|_| AtomicU64::new(0)).collect(),
            width,
            done: AtomicUsize::new(0),
        }
    }

    pub(crate) fn publish(&self, n: usize, values: &[f64]) {
        let s = (n % 3) * self.width;
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
        f64::from_bits(self.slots[(n % 3) * self.width + slot].load(Ordering::Relaxed))
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
    mut progress: impl FnMut(usize) -> Result<(), Error>,
) -> Result<Output, Error> {
    let every = every.max(1);
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
