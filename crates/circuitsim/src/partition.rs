//! A circuit run as two partitions on two threads, coupled through the nodes
//! they share with one sample of latency: a fast "draft" setting for real
//! time (`docs/CIRCUIT_SIM_PLAN.md`, M8). Off by default; the default is one
//! coupled solve of the whole circuit.
//!
//! The IR's sections are split in two: the named ones (`second`, e.g. the
//! power supplies) and the rest (the "first" partition, which has the audio
//! input). At each node they share:
//!
//! - the first partition sees the node as a voltage source, the second
//!   partition's voltage there;
//! - the second sees a current injected into the node, the current the first
//!   partition's source takes from its own side.
//!
//! Both start at the DC operating point of the whole circuit, solved as one:
//! the first partition's sources at those node voltages, its currents into
//! the second. Then each sample, both partitions step at once on their own
//! threads, each with the other's coupling values from the end of the
//! previous sample: held, or extrapolated linearly through the last two over
//! the sample ([`Coupling`]). They wait for each other once per sample, so the
//! result doesn't depend on timing (only the waits do).
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

/// The circuit split by section title: (first, second, shared nodes).
pub(crate) fn split(
    ir: &CircuitIr,
    second: &[String],
) -> Result<(CircuitIr, CircuitIr, Vec<String>), Error> {
    for t in second {
        if !ir.sections.iter().any(|s| &s.title == t) {
            return Err(Error::new(format!("partition: no section titled {t:?}")));
        }
    }
    let (b_secs, a_secs): (Vec<&Section>, Vec<&Section>) =
        ir.sections.iter().partition(|s| second.contains(&s.title));
    let nodes = |secs: &[&Section]| -> HashSet<String> {
        secs.iter()
            .flat_map(|s| s.elements.iter())
            .flat_map(|e| e.nodes())
            .filter(|n| *n != GROUND)
            .map(str::to_string)
            .collect()
    };
    let (na, nb) = (nodes(&a_secs), nodes(&b_secs));
    if !na.contains(&ir.input_node) {
        return Err(Error::new(
            "partition: the input node must stay in the first partition",
        ));
    }
    // Shared nodes in order of first appearance in the IR.
    let mut shared: Vec<String> = Vec::new();
    for e in ir.elements() {
        for n in e.nodes() {
            if na.contains(n) && nb.contains(n) && !shared.iter().any(|s| s == n) {
                shared.push(n.to_string());
            }
        }
    }
    if shared.is_empty() {
        return Err(Error::new("partition: the two parts share no node"));
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
    let probes = |nodes: &HashSet<String>| -> Vec<Probe> {
        ir.probes
            .iter()
            .filter(|p| {
                let Probe::Voltage { node } = p;
                nodes.contains(node) || node == GROUND
            })
            .cloned()
            .collect()
    };
    let mut a_sections: Vec<Section> = a_secs.into_iter().cloned().collect();
    a_sections.push(Section {
        title: "partition: the shared nodes' voltages".into(),
        elements: shared
            .iter()
            .map(|n| {
                Element::VoltageSource(VoltageSource {
                    name: format!("{SOURCE_PREFIX}{n}"),
                    pos: n.clone(),
                    neg: GROUND.into(),
                    dc_v: 0.0,
                })
            })
            .collect(),
    });
    let a = CircuitIr {
        version: ir.version,
        title: format!("{} (first partition)", ir.title),
        input_node: ir.input_node.clone(),
        probes: probes(&na),
        models: used(&a_sections.iter().collect::<Vec<_>>()),
        sections: a_sections,
    };
    let mut b_sections: Vec<Section> = b_secs.into_iter().cloned().collect();
    b_sections.push(Section {
        title: "partition: input stub".into(),
        elements: vec![Element::Resistor(Resistor {
            name: "RPART_INPUT".into(),
            a: STUB_INPUT.into(),
            b: GROUND.into(),
            r_ohm: 1e3,
        })],
    });
    // Probes on shared nodes come from the second partition (its voltage is
    // the one the first partition's source copies).
    let only_a: HashSet<String> = na.difference(&nb).cloned().collect();
    let b = CircuitIr {
        version: ir.version,
        title: format!("{} (second partition)", ir.title),
        input_node: STUB_INPUT.into(),
        probes: probes(&nb)
            .into_iter()
            .filter(|p| {
                let Probe::Voltage { node } = p;
                !only_a.contains(node)
            })
            .collect(),
        models: used(&b_sections.iter().collect::<Vec<_>>()),
        sections: b_sections,
    };
    Ok((a, b, shared))
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

    pub(crate) fn read(&self, n: usize, out: &mut [f64]) {
        let s = (n % 3) * self.width;
        for (o, slot) in out.iter_mut().zip(&self.slots[s..s + self.width]) {
            *o = f64::from_bits(slot.load(Ordering::Relaxed));
        }
    }
}

/// The other partition's values over sample n -> n + 1 (`e0` at its start,
/// `e1` at its end) from that partition's samples n and n - 1.
pub(crate) fn ends(
    coupling: Coupling,
    ring: &Ring,
    n: usize,
    e0: &mut [f64],
    e1: &mut [f64],
    prev: &mut [f64],
) {
    ring.read(n, e0);
    match (coupling, n) {
        (Coupling::Extrapolate, 1..) => {
            ring.read(n - 1, prev);
            for ((e1, &x0), &xm) in e1.iter_mut().zip(&*e0).zip(&*prev) {
                *e1 = 2.0 * x0 - xm;
            }
        }
        _ => e1.copy_from_slice(e0),
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
    mut progress: impl FnMut(usize) -> Result<(), Error>,
) -> Result<Output, Error> {
    let every = every.max(1);
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
    let mut stream = Stream::new(ir, second, coupling, h, opts, u0)?;
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
        add(stream.process(chunk)?);
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
