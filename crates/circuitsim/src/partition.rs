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
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};

use crate::Error;
use crate::ir::{CircuitIr, Element, GROUND, Probe, Resistor, Section, VoltageSource};
use crate::mna::Mna;
use crate::transient::{Options, Output, StepInput, Transient};

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
const SOURCE_PREFIX: &str = "VPART_";
/// The second partition's input node (it has no audio input).
const STUB_INPUT: &str = "partition_input";

/// The circuit split by section title: (first, second, shared nodes).
fn split(ir: &CircuitIr, second: &[String]) -> Result<(CircuitIr, CircuitIr, Vec<String>), Error> {
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
struct Ring {
    slots: Vec<AtomicU64>,
    width: usize,
    /// Samples published (sample n is in slot n % 3).
    done: AtomicUsize,
}

impl Ring {
    fn new(width: usize) -> Ring {
        Ring {
            slots: (0..3 * width).map(|_| AtomicU64::new(0)).collect(),
            width,
            done: AtomicUsize::new(0),
        }
    }

    fn publish(&self, n: usize, values: &[f64]) {
        let s = (n % 3) * self.width;
        for (slot, v) in self.slots[s..s + self.width].iter().zip(values) {
            slot.store(v.to_bits(), Ordering::Relaxed);
        }
        self.done.store(n + 1, Ordering::Release);
    }

    /// Wait until sample `n` is published (or `stop`); false if stopped.
    fn wait(&self, n: usize, stop: &AtomicBool) -> bool {
        let mut spins = 0u32;
        while self.done.load(Ordering::Acquire) <= n {
            if stop.load(Ordering::Relaxed) {
                return false;
            }
            spins += 1;
            if spins < 1 << 14 {
                std::hint::spin_loop();
            } else {
                std::thread::yield_now();
            }
        }
        true
    }

    fn read(&self, n: usize, out: &mut [f64]) {
        let s = (n % 3) * self.width;
        for (o, slot) in out.iter_mut().zip(&self.slots[s..s + self.width]) {
            *o = f64::from_bits(slot.load(Ordering::Relaxed));
        }
    }
}

/// The other partition's values over sample n -> n + 1 (`e0` at its start,
/// `e1` at its end) from that partition's samples n and n - 1.
fn ends(
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

/// One partition's run: its transient, the unknowns it publishes to the other
/// (the coupling values), and its probes over the run.
struct Part {
    tr: Transient,
    publish: Vec<usize>,
    probes: Vec<Vec<f64>>,
}

impl Part {
    fn record(&mut self) {
        for (v, y) in self
            .probes
            .iter_mut()
            .zip(self.tr.mna().probe_values(self.tr.x()))
        {
            v.push(y);
        }
    }

    fn published(&self, out: &mut [f64]) {
        for (o, &k) in out.iter_mut().zip(&self.publish) {
            *o = self.tr.x()[k];
        }
    }
}

/// Run `ir` partitioned (see the module docs): the sections titled in
/// `second` on a thread of their own. Same input, step and options as
/// [`crate::simulate_with_progress`] (DK solver and a diagonally implicit
/// method only); `progress` is called from the calling thread, which runs
/// the first partition. The output has the IR's probes in its order; the
/// stats are the first partition's.
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
    let (a_ir, b_ir, shared) = split(ir, second)?;
    let k = shared.len();

    // The DC operating point of the whole circuit: the shared nodes' voltages.
    let whole = Transient::new(Mna::from_ir(ir, opts.gmin)?, h, *opts, u0)?;
    let v_dc: Vec<f64> = shared
        .iter()
        .map(|n| whole.mna().node(n).map_or(0.0, |i| whole.x()[i]))
        .collect();
    drop(whole);

    // First partition: the shared nodes as sources (externals on their rows,
    // so the IR's 0 V plus the external is the voltage), publishing the
    // sources' currents (+: from the node into the source, i.e. what the
    // first partition delivers into the node).
    let mut ma = Mna::from_ir(&a_ir, opts.gmin)?;
    let src: Vec<usize> = shared
        .iter()
        .map(|n| ma.branch(&format!("{SOURCE_PREFIX}{n}")).expect("added"))
        .collect();
    ma.externals = src.clone();
    ma.outputs = src.clone();
    let mut a = Part {
        tr: Transient::with_externals(ma, h, *opts, u0, &v_dc)?,
        publish: src,
        probes: Vec::new(),
    };
    let i_dc: Vec<f64> = {
        let mut v = vec![0.0; k];
        a.published(&mut v);
        v
    };
    // Second partition: those currents injected into the shared nodes,
    // publishing the nodes' voltages.
    let mut mb = Mna::from_ir(&b_ir, opts.gmin)?;
    let nodes: Vec<usize> = shared.iter().map(|n| mb.node(n).expect("shared")).collect();
    mb.externals = nodes.clone();
    mb.outputs = nodes.clone();
    let mut b = Part {
        tr: Transient::with_externals(mb, h, *opts, 0.0, &i_dc)?,
        publish: nodes,
        probes: Vec::new(),
    };
    let series = |n: usize| (0..n).map(|_| Vec::with_capacity(input.len())).collect();
    a.probes = series(a.tr.mna().probes.len());
    b.probes = series(b.tr.mna().probes.len());
    a.record();
    b.record();

    // Sample 0 (DC) published by both; sample n (after n steps) in slot n % 3.
    let (ring_a, ring_b) = (Ring::new(k), Ring::new(k));
    let mut buf = vec![0.0; k];
    a.published(&mut buf);
    ring_a.publish(0, &buf);
    b.published(&mut buf);
    ring_b.publish(0, &buf);
    let stop = AtomicBool::new(false);
    let order = 5i64.min(opts.input_order as i64);
    let len = input.len() as i64;
    let steps = rest.len();

    let result_b = std::thread::scope(|scope| {
        let (ring_a, ring_b, stop) = (&ring_a, &ring_b, &stop);
        let handle = scope.spawn(move || -> Result<Part, Error> {
            let (mut e0, mut e1, mut prev) = (vec![0.0; k], vec![0.0; k], vec![0.0; k]);
            let mut out = vec![0.0; k];
            for n in 0..steps {
                if !ring_a.wait(n, stop) {
                    return Err(Error::new("stopped"));
                }
                ends(coupling, ring_a, n, &mut e0, &mut e1, &mut prev);
                b.tr.set_externals(&e0, &e1);
                if let Err(e) = b.tr.step_input(&StepInput::linear(0.0, 0.0)) {
                    stop.store(true, Ordering::Relaxed);
                    return Err(Error::new(format!("partition {:?}: {e}", second)));
                }
                b.record();
                b.published(&mut out);
                ring_b.publish(n + 1, &out);
            }
            Ok(b)
        });

        let run_a = (|| -> Result<(), Error> {
            let (mut e0, mut e1, mut prev) = (vec![0.0; k], vec![0.0; k], vec![0.0; k]);
            let mut out = vec![0.0; k];
            for (i, &u) in rest.iter().enumerate() {
                if !ring_b.wait(i, stop) {
                    return Err(Error::new("stopped"));
                }
                ends(coupling, ring_b, i, &mut e0, &mut e1, &mut prev);
                a.tr.set_externals(&e0, &e1);
                if order == 1 {
                    a.tr.step(u)?;
                } else {
                    let n = i as i64;
                    let lo = (n - (order - 1) / 2).max(0);
                    let hi = (n + 1 + (order - 1) / 2).min(len - 1);
                    let w = &input[lo as usize..=hi as usize];
                    a.tr.step_input(&StepInput::lagrange(w, (lo - n) as i32))?;
                }
                a.record();
                a.published(&mut out);
                ring_a.publish(i + 1, &out);
                if (i + 2) % every == 0 {
                    progress(i + 2)?;
                }
            }
            Ok(())
        })();
        if run_a.is_err() {
            stop.store(true, Ordering::Relaxed);
        }
        let b = handle
            .join()
            .map_err(|_| Error::new("partition thread panicked"))?;
        // The first failure: a partition that stopped because the other
        // failed reports "stopped".
        match (run_a, b) {
            (Err(e), Err(f)) if e.0 == "stopped" => Err(f),
            (Err(e), _) => Err(e),
            (Ok(()), b) => b,
        }
    })?;
    let b = result_b;

    // The IR's probes in its order, from whichever partition has them.
    let (mut names, mut values) = (Vec::new(), Vec::new());
    let (pa, pb) = (&a.tr.mna().probes, &b.tr.mna().probes);
    let (mut va, mut vb) = (a.probes, b.probes);
    for p in &ir.probes {
        let Probe::Voltage { node } = p;
        let name = format!("v({node})");
        let v = if let Some(j) = pb.iter().position(|(n, _)| *n == name) {
            std::mem::take(&mut vb[j])
        } else if let Some(j) = pa.iter().position(|(n, _)| *n == name) {
            std::mem::take(&mut va[j])
        } else {
            return Err(Error::new(format!("partition: probe {name} lost")));
        };
        names.push(name);
        values.push(v);
    }
    Ok(Output {
        names,
        values,
        stats: a.tr.stats().clone(),
    })
}
