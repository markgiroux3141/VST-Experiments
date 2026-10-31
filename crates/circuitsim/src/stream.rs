//! A run fed block by block: real-time processing (`docs/CIRCUIT_SIM_PLAN.md`,
//! M8), with parameter changes while it runs.
//!
//! A [`Stream`] is the same run as [`crate::simulate`] (or, with sections named
//! for other threads, [`crate::partition::simulate_partitioned`]): fed the same
//! input in blocks of any size, it gives the same output, bit for bit. Its
//! output lags its input by the input interpolation's lookahead (`(order - 1) / 2
//! + 1` samples past the step; 3 for order 5, 1 for linear): a step needs the
//! samples around it. [`Stream::finish`] steps the rest, as a run's end does.
//!
//! A partitioned stream keeps each partition past the first on a thread of its
//! own for its lifetime (stepping in lockstep with the caller's, as
//! `partition.rs` describes; idle, it waits without spinning after a few
//! milliseconds).
//!
//! [`Stream::update`] changes component values (a knob turned): applied at the
//! next sample boundary the stream reaches, in every partition at the same
//! sample. It needs every unknown at that point, so the stream computes them for
//! one sample first (the partitions step concurrently, so the others' commands
//! are queued before the first publishes the sample they apply at). Changes that
//! add or remove nodes are refused, as [`Transient::update`] refuses them; large
//! jumps can stall Newton, so callers ramp them.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crate::Error;
use crate::ir::{CircuitIr, Probe};
use crate::mna::Mna;
use crate::partition::{Coupling, Ring, SOURCE_PREFIX, Split, groups, split};
use crate::transient::{Options, StepInput, Transient};

/// Commands to a partition's thread, applied before it steps from a given sample.
enum Command {
    AllUnknowns(bool),
    Update(Box<CircuitIr>),
}

/// One coupling value a partition reads per sample: a value another partition
/// publishes (partition, slot), or the sum of several (the currents the users of
/// a node the partition owns draw from it).
#[derive(Debug, Clone)]
enum Feed {
    Value(usize, usize),
    Sum(Vec<(usize, usize)>),
}

/// What the threads share.
struct Shared {
    /// Each partition's coupling values per sample (index 0: the caller's).
    rings: Vec<Ring>,
    stop: AtomicBool,
    /// Per partition (index 0 unused).
    commands: Vec<Mutex<VecDeque<(usize, Command)>>>,
    /// Per partition (index 0 unused): its probes, per sample, not yet collected.
    probes: Vec<Mutex<Vec<Vec<f64>>>>,
    error: Mutex<Option<Error>>,
}

impl Shared {
    /// Wait until partition `p` has published sample `n`; false if stopped.
    /// Spins, then yields, then (idle for milliseconds: a paused stream) sleeps.
    fn wait(&self, p: usize, n: usize) -> bool {
        let ring = &self.rings[p];
        let mut spins = 0u32;
        let mut since: Option<Instant> = None;
        while !ring.published(n) {
            if self.stop.load(Ordering::Relaxed) {
                return false;
            }
            spins += 1;
            if spins < 1 << 14 {
                std::hint::spin_loop();
            } else if since.get_or_insert_with(Instant::now).elapsed() < Duration::from_millis(2) {
                std::thread::yield_now();
            } else {
                std::thread::sleep(Duration::from_micros(100));
            }
        }
        true
    }

    /// The feeds over sample n -> n + 1: `e0` at its start, `e1` at its end (held
    /// or extrapolated through n - 1). Waits until every partition has published
    /// sample n, not only those read: no partition gets more than a sample ahead
    /// of another, so a ring of three samples is never overwritten while read.
    /// False if stopped.
    fn feeds(
        &self,
        coupling: Coupling,
        feeds: &[Feed],
        n: usize,
        e0: &mut [f64],
        e1: &mut [f64],
    ) -> bool {
        let one = |p: usize, slot: usize| -> (f64, f64) {
            let x0 = self.rings[p].value(n, slot);
            match (coupling, n) {
                (Coupling::Extrapolate, 1..) => (x0, 2.0 * x0 - self.rings[p].value(n - 1, slot)),
                _ => (x0, x0),
            }
        };
        for p in 0..self.rings.len() {
            if !self.wait(p, n) {
                return false;
            }
        }
        for (k, f) in feeds.iter().enumerate() {
            (e0[k], e1[k]) = match f {
                Feed::Value(p, slot) => one(*p, *slot),
                Feed::Sum(v) => v.iter().fold((0.0, 0.0), |(a, b), &(p, slot)| {
                    let (x0, x1) = one(p, slot);
                    (a + x0, b + x1)
                }),
            };
        }
        true
    }

    fn fail(&self, e: Error) {
        self.error.lock().expect("error slot").get_or_insert(e);
        self.stop.store(true, Ordering::Relaxed);
    }
}

/// The partitions past the first: their threads, and what all share.
struct Parts {
    shared: Arc<Shared>,
    handles: Vec<Option<JoinHandle<()>>>,
    /// The titles that split the circuit (groups separated by GROUP_BREAK), and
    /// the shared nodes it gave (for updates).
    second: Vec<String>,
    nodes: Vec<(String, usize)>,
    /// The first partition's feeds.
    feeds: Vec<Feed>,
}

/// A partition's thread: step after the others' sample, applying commands
/// queued for the sample it steps from.
fn run_part(
    mut tr: Transient,
    shared: Arc<Shared>,
    coupling: Coupling,
    p: usize,
    feeds: Vec<Feed>,
    titles: Vec<String>,
) {
    let k = feeds.len();
    let (mut e0, mut e1) = (vec![0.0; k], vec![0.0; k]);
    let mut out = vec![0.0; tr.mna().outputs.len()];
    let mut n = 0usize;
    loop {
        // Every partition's sample n first: the first partition queues the commands
        // for sample n before it publishes it, so they are all here after this (read
        // before the wait, a partition running ahead missed them and never applied a
        // knob turned on its sections).
        if !shared.feeds(coupling, &feeds, n, &mut e0, &mut e1) {
            return;
        }
        // Commands for this sample.
        loop {
            let cmd = {
                let mut q = shared.commands[p].lock().expect("commands");
                match q.front() {
                    Some((at, _)) if *at <= n => q.pop_front().map(|c| c.1),
                    _ => None,
                }
            };
            let Some(cmd) = cmd else { break };
            let res = match cmd {
                Command::AllUnknowns(on) => {
                    tr.set_all_unknowns(on);
                    Ok(())
                }
                Command::Update(ir) => tr.update(&ir),
            };
            if let Err(e) = res {
                shared.fail(Error::new(format!("partition {titles:?}: {e}")));
                return;
            }
        }
        tr.set_externals(&e0, &e1);
        if let Err(e) = tr.step_input(&StepInput::linear(0.0, 0.0)) {
            shared.fail(Error::new(format!("partition {titles:?}: {e}")));
            return;
        }
        {
            let mut probes = shared.probes[p].lock().expect("probes");
            for (v, y) in probes.iter_mut().zip(tr.mna().probe_values(tr.x())) {
                v.push(y);
            }
        }
        for (o, &i) in out.iter_mut().zip(&tr.mna().outputs) {
            *o = tr.x()[i];
        }
        n += 1;
        shared.rings[p].publish(n, &out);
    }
}

/// Partition `p`'s couplings in `sp` (`Mna::externals` past the control inputs,
/// and `Mna::outputs`): the shared nodes it sources (their sources' rows; it
/// publishes their currents, + into the node) and the ones it owns (their nodes;
/// it publishes their voltages). Outputs: the owned nodes, then the sources.
fn couple(sp: &Split, p: usize, mna: &mut Mna) -> Vec<Feed> {
    let (owned, sourced) = (sp.owned(p), sp.sourced(p));
    let src: Vec<usize> = sourced
        .iter()
        .map(|&i| {
            mna.branch(&format!("{SOURCE_PREFIX}{}", sp.shared[i].name))
                .expect("added")
        })
        .collect();
    let nodes: Vec<usize> = owned
        .iter()
        .map(|&i| mna.node(&sp.shared[i].name).expect("shared"))
        .collect();
    mna.externals.truncate(mna.n_controls + mna.n_media);
    mna.externals.extend_from_slice(&src);
    mna.externals.extend_from_slice(&nodes);
    mna.outputs = nodes.iter().chain(&src).copied().collect();
    // A sourced node reads its owner's voltage slot; an owned one sums its users'
    // current slots.
    let slot_owned = |q: usize, i: usize| sp.owned(q).iter().position(|&j| j == i).expect("owned");
    let slot_source = |q: usize, i: usize| {
        sp.owned(q).len() + sp.sourced(q).iter().position(|&j| j == i).expect("sourced")
    };
    sourced
        .iter()
        .map(|&i| {
            let q = sp.shared[i].owner;
            Feed::Value(q, slot_owned(q, i))
        })
        .chain(owned.iter().map(|&i| {
            Feed::Sum(
                sp.shared[i]
                    .users
                    .iter()
                    .map(|&u| (u, slot_source(u, i)))
                    .collect(),
            )
        }))
        .collect()
}

/// A run fed block by block (see the module docs).
pub struct Stream {
    a: Transient,
    parts: Option<Parts>,
    coupling: Coupling,
    names: Vec<String>,
    /// Where each of the IR's probes comes from: (partition, its probe index).
    sources: Vec<(usize, usize)>,
    /// Input interpolation order (1, 3, 5).
    order: usize,
    /// Every input sample from `hist0` on (index = sample number - hist0).
    hist: Vec<f64>,
    hist0: usize,
    /// The control inputs' samples, indexed as `hist` (IR order; empty without
    /// control inputs).
    chist: Vec<Vec<f64>>,
    /// Samples stepped: the state is at sample `n`.
    n: usize,
    /// The input has ended ([`Stream::finish`]): `len` samples in all.
    len: Option<usize>,
    /// The other partitions' probes at sample 0 (index 0 unused).
    initial: Vec<Vec<f64>>,
    /// A parameter change waiting for the next sample boundary (the whole IR, and
    /// its partitions), and whether the last step computed every unknown for it.
    pending: Option<(CircuitIr, Option<Vec<CircuitIr>>)>,
    armed: bool,
    // Scratch.
    e0: Vec<f64>,
    e1: Vec<f64>,
    out: Vec<f64>,
}

impl Stream {
    /// A stream of `ir` at step `h` with `opts` (a partitioned one needs the DK
    /// solver and a diagonally implicit method), the sections titled in `second`
    /// on threads of their own (groups separated by
    /// [`crate::partition::GROUP_BREAK`]; none: one solve), at the DC operating
    /// point with input `u0` (sample 0; [`Stream::initial`] has its probes).
    pub fn new(
        ir: &CircuitIr,
        second: &[String],
        coupling: Coupling,
        h: f64,
        opts: &Options,
        u0: f64,
    ) -> Result<Stream, Error> {
        Stream::with_controls(ir, second, coupling, h, opts, u0, &[])
    }

    /// [`Stream::new`] with the control inputs at `c0` for sample 0 (IR order;
    /// empty: all 0 V).
    pub fn with_controls(
        ir: &CircuitIr,
        second: &[String],
        coupling: Coupling,
        h: f64,
        opts: &Options,
        u0: f64,
        c0: &[f64],
    ) -> Result<Stream, Error> {
        if !u0.is_finite() {
            return Err(Error::new("input sample 0 is not finite"));
        }
        let c0: Vec<f64> = if c0.is_empty() {
            vec![0.0; ir.controls.len()]
        } else {
            c0.to_vec()
        };
        let streams: Vec<&[f64]> = c0.iter().map(std::slice::from_ref).collect();
        crate::transient::check_controls(ir, &streams, 1)?;
        // A transient on `mna` at the DC point with the controls at c0, then `ext`.
        let start = |mna: Mna, ext: &[f64], u: f64| {
            let mut all = c0.clone();
            all.extend_from_slice(ext);
            if all.is_empty() {
                Transient::new(mna, h, *opts, u)
            } else {
                Transient::with_externals(mna, h, *opts, u, &all)
            }
        };
        let names: Vec<String> = ir
            .probes
            .iter()
            .map(|p| {
                let Probe::Voltage { node } = p;
                format!("v({node})")
            })
            .collect();
        let base = |tr: Transient, parts, sources, k| Stream {
            a: tr,
            parts,
            coupling,
            names: names.clone(),
            sources,
            order: opts.input_order.max(1),
            hist: vec![u0],
            hist0: 0,
            chist: c0.iter().map(|&c| vec![c]).collect(),
            n: 0,
            len: None,
            initial: Vec::new(),
            pending: None,
            armed: false,
            e0: vec![0.0; k],
            e1: vec![0.0; k],
            out: Vec::new(),
        };
        if groups(second).is_empty() {
            let tr = start(Mna::from_ir(ir, opts.gmin)?, &[], u0)?;
            let sources = (0..names.len()).map(|j| (0, j)).collect();
            return Ok(base(tr, None, sources, 0));
        }

        let sp = split(ir, second)?;
        let n_parts = sp.parts.len();
        // The shared nodes at the whole circuit's DC operating point.
        let whole = start(Mna::from_ir(ir, opts.gmin)?, &[], u0)?;
        let v_dc: Vec<f64> = sp
            .shared
            .iter()
            .map(|s| whole.mna().node(&s.name).map_or(0.0, |i| whole.x()[i]))
            .collect();
        drop(whole);
        // Each partition at the DC point, in order: its sources at the shared
        // nodes' voltages, its owned nodes fed the currents its users' sources
        // deliver (the users are lower-numbered, so already solved).
        let mut trs: Vec<Transient> = Vec::with_capacity(n_parts);
        let mut feeds: Vec<Vec<Feed>> = Vec::with_capacity(n_parts);
        let mut dc_out: Vec<Vec<f64>> = Vec::with_capacity(n_parts);
        for p in 0..n_parts {
            let mut mna = Mna::from_ir(&sp.parts[p], opts.gmin)?;
            let f = couple(&sp, p, &mut mna);
            let ext: Vec<f64> = f
                .iter()
                .map(|f| match f {
                    Feed::Value(q, slot) => {
                        // A sourced node: its voltage at DC.
                        let i = sp.owned(*q)[*slot];
                        v_dc[i]
                    }
                    Feed::Sum(v) => v.iter().map(|&(u, slot)| dc_out[u][slot]).sum(),
                })
                .collect();
            let tr = if p == 0 {
                start(mna, &ext, u0)?
            } else {
                Transient::with_externals(mna, h, *opts, 0.0, &ext)?
            };
            dc_out.push(tr.mna().outputs.iter().map(|&i| tr.x()[i]).collect());
            trs.push(tr);
            feeds.push(f);
        }

        // The IR's probes from the partition that has them (a shared node's, its
        // owner: the others copy its voltage).
        let mut sources = Vec::new();
        for name in &names {
            let found = (0..n_parts).rev().find_map(|p| {
                trs[p]
                    .mna()
                    .probes
                    .iter()
                    .position(|(q, _)| q == name)
                    .map(|j| (p, j))
            });
            sources.push(found.ok_or_else(|| Error::new(format!("partition: probe {name} lost")))?);
        }
        let shared = Arc::new(Shared {
            rings: dc_out.iter().map(|o| Ring::new(o.len())).collect(),
            stop: AtomicBool::new(false),
            commands: (0..n_parts).map(|_| Mutex::new(VecDeque::new())).collect(),
            probes: trs
                .iter()
                .map(|t| Mutex::new(vec![Vec::new(); t.mna().probes.len()]))
                .collect(),
            error: Mutex::new(None),
        });
        // Sample 0 (DC), published by all.
        for (ring, o) in shared.rings.iter().zip(&dc_out) {
            ring.publish(0, o);
        }
        let initial: Vec<Vec<f64>> = trs
            .iter()
            .map(|t| t.mna().probe_values(t.x()).collect())
            .collect();
        let group_titles = groups(second);
        let mut handles = vec![None];
        let mut trs = trs.into_iter();
        let a = trs.next().expect("the first partition");
        for (p, tr) in trs.enumerate().map(|(i, t)| (i + 1, t)) {
            let (shared, f, titles) = (
                Arc::clone(&shared),
                feeds[p].clone(),
                group_titles[p - 1].clone(),
            );
            handles.push(Some(
                std::thread::Builder::new()
                    .name(format!("circuitsim partition {p}"))
                    .spawn(move || run_part(tr, shared, coupling, p, f, titles))
                    .map_err(|e| Error::new(format!("partition thread: {e}")))?,
            ));
        }
        let k = feeds[0].len();
        let parts = Parts {
            shared,
            handles,
            second: second.to_vec(),
            nodes: sp
                .shared
                .iter()
                .map(|s| (s.name.clone(), s.owner))
                .collect(),
            feeds: feeds[0].clone(),
        };
        let out_len = a.mna().outputs.len();
        let mut stream = base(a, Some(parts), sources, k);
        stream.initial = initial;
        stream.out = vec![0.0; out_len];
        Ok(stream)
    }

    /// The probes' names (`v(node)`), in the IR's order.
    pub fn names(&self) -> &[String] {
        &self.names
    }

    /// Samples stepped so far (outputs given, sample 0 not counted).
    pub fn steps(&self) -> usize {
        self.n
    }

    /// The probes at sample 0 (the DC operating point), in the IR's order.
    pub fn initial(&self) -> Vec<f64> {
        let a: Vec<f64> = self.a.mna().probe_values(self.a.x()).collect();
        self.sources
            .iter()
            .map(|&(p, j)| if p == 0 { a[j] } else { self.initial[p][j] })
            .collect()
    }

    /// The first partition's run (its devices, per-device counters).
    pub fn transient(&self) -> &crate::transient::Transient {
        &self.a
    }

    /// The first partition's solver statistics.
    pub fn stats(&self) -> &crate::transient::Stats {
        self.a.stats()
    }

    /// Change component values to those of `ir` (the same circuit: the same
    /// nodes, sources, devices and split) at the next sample boundary the
    /// stream steps across. Checked now as far as it can be; the rest is
    /// reported by the step that applies it.
    pub fn update(&mut self, ir: &CircuitIr) -> Result<(), Error> {
        let parts = match &self.parts {
            None => None,
            Some(s) => {
                let sp = split(ir, &s.second)?;
                let nodes: Vec<(String, usize)> = sp
                    .shared
                    .iter()
                    .map(|n| (n.name.clone(), n.owner))
                    .collect();
                if nodes != s.nodes {
                    return Err(Error::new(
                        "update: the partitions' shared nodes changed (only values may)",
                    ));
                }
                Some(sp.parts)
            }
        };
        self.pending = Some((ir.clone(), parts));
        Ok(())
    }

    /// Feed input samples (volts at the input node, continuing the input);
    /// returns the probes' values (IR order) at every sample stepped, which lag
    /// the input by the interpolation's lookahead.
    pub fn process(&mut self, input: &[f64]) -> Result<Vec<Vec<f64>>, Error> {
        self.process_with(input, &[])
    }

    /// [`Stream::process`] with the control inputs' samples over the same span
    /// (IR order, each as long as `input`; empty: each holds its last value).
    pub fn process_with(
        &mut self,
        input: &[f64],
        controls: &[&[f64]],
    ) -> Result<Vec<Vec<f64>>, Error> {
        if self.len.is_some() {
            return Err(Error::new("the stream is finished"));
        }
        if !controls.is_empty() {
            if controls.len() != self.chist.len() {
                return Err(Error::new(format!(
                    "{} control streams for {} control inputs",
                    controls.len(),
                    self.chist.len()
                )));
            }
            if let Some(i) = controls
                .iter()
                .position(|c| c.len() != input.len() || c.iter().any(|v| !v.is_finite()))
            {
                return Err(Error::new(format!(
                    "control stream {i}: not as long as the input, or not finite"
                )));
            }
        }
        if let Some(i) = input.iter().position(|u| !u.is_finite()) {
            return Err(Error::new(format!(
                "input sample {} is not finite",
                self.hist0 + self.hist.len() + i
            )));
        }
        self.hist.extend_from_slice(input);
        for (k, h) in self.chist.iter_mut().enumerate() {
            match controls.get(k) {
                Some(c) => h.extend_from_slice(c),
                None => {
                    let last = *h.last().expect("sample 0");
                    h.resize(h.len() + input.len(), last);
                }
            }
        }
        let ahead = (self.order - 1) / 2 + 1;
        let known = self.hist0 + self.hist.len(); // samples 0..known have arrived
        let until = known.saturating_sub(ahead);
        self.run_until(until)
    }

    /// The input has ended: step the samples the lookahead held back (their
    /// interpolation windows shortened at the end, as a whole run's are).
    pub fn finish(&mut self) -> Result<Vec<Vec<f64>>, Error> {
        let known = self.hist0 + self.hist.len();
        self.len = Some(known);
        self.run_until(known.saturating_sub(1))
    }

    /// Step to sample `until` (if not there yet), collecting the probes.
    fn run_until(&mut self, until: usize) -> Result<Vec<Vec<f64>>, Error> {
        let first = self.n;
        let mut a_vals: Vec<Vec<f64>> =
            vec![Vec::with_capacity(until.saturating_sub(first)); self.a.mna().probes.len()];
        while self.n < until {
            if let Err(e) = self.step_one(&mut a_vals) {
                return Err(self.first_error(e));
            }
        }
        // The other partitions' samples up to `until`.
        let mut others: Vec<Vec<Vec<f64>>> = vec![Vec::new()];
        if let Some(s) = &self.parts {
            for p in 1..s.shared.rings.len() {
                if !s.shared.wait(p, self.n) {
                    return Err(self.first_error(Error::new("stopped")));
                }
                let mut probes = s.shared.probes[p].lock().expect("probes");
                others.push(
                    probes
                        .iter_mut()
                        .map(|v| v.drain(..self.n - first).collect())
                        .collect(),
                );
            }
        }
        Ok(self
            .sources
            .iter()
            .map(|&(p, j)| {
                if p == 0 {
                    std::mem::take(&mut a_vals[j])
                } else {
                    others[p][j].clone()
                }
            })
            .collect())
    }

    /// The error to report: another partition's, if it failed first.
    fn first_error(&mut self, e: Error) -> Error {
        if let Some(s) = &self.parts {
            s.shared.stop.store(true, Ordering::Relaxed);
            if let Some(f) = s.shared.error.lock().expect("error slot").take() {
                return f;
            }
        }
        e
    }

    /// Step n -> n + 1. A pending update is handled at the end of a step,
    /// before the step's sample is published (the other partitions, stepping
    /// concurrently, take their commands before they step from that sample):
    /// the first such step arms it (the next step computes every unknown in
    /// every partition), the next applies it in all at the same boundary.
    fn step_one(&mut self, a_vals: &mut [Vec<f64>]) -> Result<(), Error> {
        let n = self.n;
        // The other partitions' values over this sample.
        if let Some(s) = &self.parts {
            if !s
                .shared
                .feeds(self.coupling, &s.feeds, n, &mut self.e0, &mut self.e1)
            {
                return Err(Error::new("stopped"));
            }
            self.a.set_externals(&self.e0, &self.e1);
        }
        // The control inputs over the step, as simulate's loop takes them.
        if !self.chist.is_empty() {
            let i = n - self.hist0;
            let c0: Vec<f64> = self.chist.iter().map(|h| h[i]).collect();
            let c1: Vec<f64> = self.chist.iter().map(|h| h[i + 1]).collect();
            self.a.set_controls(&c0, &c1);
        }
        // The input around the step, as simulate's loop takes it.
        if self.order == 1 {
            let (u0, u1) = (self.hist[n - self.hist0], self.hist[n + 1 - self.hist0]);
            self.a.step_input(&StepInput::linear(u0, u1))?;
        } else {
            let half = (self.order - 1) / 2;
            let lo = n.saturating_sub(half);
            let hi = match self.len {
                Some(len) => (n + 1 + half).min(len - 1),
                None => n + 1 + half,
            };
            let w = &self.hist[lo - self.hist0..=hi - self.hist0];
            self.a
                .step_input(&StepInput::lagrange(w, lo as i32 - n as i32))?;
        }
        self.n = n + 1;
        for (v, y) in a_vals.iter_mut().zip(self.a.mna().probe_values(self.a.x())) {
            v.push(y);
        }
        if self.pending.is_some() {
            self.handle_update()?;
        }
        if let Some(s) = &self.parts {
            for (o, &i) in self.out.iter_mut().zip(&self.a.mna().outputs) {
                *o = self.a.x()[i];
            }
            s.shared.rings[0].publish(self.n, &self.out);
        }
        // Drop input no longer needed (the next step reads from n + 1 - half).
        let keep_from = self.n.saturating_sub((self.order - 1) / 2 + 1);
        if keep_from > self.hist0 + 4096 {
            self.hist.drain(..keep_from - self.hist0);
            for h in &mut self.chist {
                h.drain(..keep_from - self.hist0);
            }
            self.hist0 = keep_from;
        }
        Ok(())
    }

    /// A pending update at sample `self.n`, before it is published.
    fn handle_update(&mut self) -> Result<(), Error> {
        let n = self.n;
        if !self.armed {
            // The next step computes every unknown, in every partition.
            self.armed = true;
            self.a.set_all_unknowns(true);
            if let Some(s) = &self.parts {
                for q in &s.shared.commands[1..] {
                    q.lock()
                        .expect("commands")
                        .push_back((n, Command::AllUnknowns(true)));
                }
            }
            return Ok(());
        }
        // The last step computed every unknown: apply, in all.
        let (ir, parts) = self.pending.take().expect("pending");
        self.armed = false;
        match (&self.parts, parts) {
            (Some(s), Some(mut irs)) => {
                let first = irs.remove(0);
                for (q, b_ir) in s.shared.commands[1..].iter().zip(irs) {
                    let mut q = q.lock().expect("commands");
                    q.push_back((n, Command::Update(Box::new(b_ir))));
                    q.push_back((n, Command::AllUnknowns(false)));
                }
                self.a.update(&first)?;
            }
            _ => self.a.update(&ir)?,
        }
        self.a.set_all_unknowns(false);
        Ok(())
    }
}

impl Drop for Stream {
    fn drop(&mut self) {
        if let Some(s) = &mut self.parts {
            s.shared.stop.store(true, Ordering::Relaxed);
            for h in s.handles.iter_mut() {
                if let Some(h) = h.take() {
                    let _ = h.join();
                }
            }
        }
    }
}
