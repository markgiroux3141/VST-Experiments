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

/// The circuit split into parts: part 0 the sections no group names (it keeps the
/// audio input and the control inputs), part g + 1 group g's.
#[derive(Debug, Clone)]
pub(crate) struct Split {
    pub parts: Vec<CircuitIr>,
    pub shared: Vec<SharedNode>,
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
    let groups = groups(second);
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
    let n_parts = groups.len() + 1;
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
            .flat_map(|e| e.nodes())
            .filter(|n| *n != GROUND)
            .map(str::to_string)
            .collect()
    };
    let node_sets: Vec<HashSet<String>> = secs.iter().map(|s| nodes(s)).collect();
    if !node_sets[0].contains(&ir.input_node) {
        return Err(Error::new(
            "partition: the input node must stay in the first partition",
        ));
    }
    if let Some(c) = ir.controls.iter().find(|c| !node_sets[0].contains(&c.node)) {
        return Err(Error::new(format!(
            "partition: control {}'s node must stay in the first partition",
            c.name
        )));
    }
    // Shared nodes in order of first appearance in the IR.
    let mut shared: Vec<SharedNode> = Vec::new();
    for e in ir.elements() {
        for n in e.nodes() {
            if shared.iter().any(|s| s.name == n) {
                continue;
            }
            let with: Vec<usize> = (0..n_parts).filter(|&p| node_sets[p].contains(n)).collect();
            if with.len() >= 2 {
                let owner = *with.last().expect("two or more");
                shared.push(SharedNode {
                    name: n.to_string(),
                    owner,
                    users: with[..with.len() - 1].to_vec(),
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
        let mut sections: Vec<Section> = secs[p].iter().map(|s| (*s).clone()).collect();
        let sourced: Vec<&SharedNode> = shared.iter().filter(|s| s.users.contains(&p)).collect();
        if !sourced.is_empty() {
            sections.push(Section {
                title: "partition: the shared nodes' voltages".into(),
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
        if p > 0 {
            sections.push(Section {
                title: "partition: input stub".into(),
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
            input_node: if p == 0 {
                ir.input_node.clone()
            } else {
                STUB_INPUT.into()
            },
            controls: if p == 0 {
                ir.controls.clone()
            } else {
                Vec::new()
            },
            // Every part keeps the noise spec: streams are keyed by element name.
            noise: ir.noise.clone(),
            probes,
            models: used(&sections.iter().collect::<Vec<_>>()),
            sections,
        });
    }
    Ok(Split { parts, shared })
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
    if second.is_empty() {
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
