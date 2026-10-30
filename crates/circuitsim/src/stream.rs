//! A run fed block by block: real-time processing (`docs/CIRCUIT_SIM_PLAN.md`,
//! M8), with parameter changes while it runs.
//!
//! A [`Stream`] is the same run as [`crate::simulate`] (or, with sections named
//! for a second thread, [`crate::partition::simulate_partitioned`]): fed the same
//! input in blocks of any size, it gives the same output, bit for bit. Its
//! output lags its input by the input interpolation's lookahead (`(order - 1) / 2
//! + 1` samples past the step; 3 for order 5, 1 for linear): a step needs the
//! samples around it. [`Stream::finish`] steps the rest, as a run's end does.
//!
//! A partitioned stream keeps its second partition on a thread of its own for
//! its lifetime (stepping in lockstep with the caller's, as `partition.rs`
//! describes; idle, it waits without spinning after a few milliseconds).
//!
//! [`Stream::update`] changes component values (a knob turned): applied at the
//! next sample boundary the stream reaches, in both partitions at the same
//! sample. It needs every unknown at that point, so the stream computes them for
//! one sample first (the partitions step concurrently, so the second's command
//! is queued before the first publishes the sample it applies at). Changes that
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
use crate::partition::{Coupling, Ring, SOURCE_PREFIX, ends, split};
use crate::transient::{Options, StepInput, Transient};

/// Commands to the second partition's thread, applied before it steps from a
/// given sample.
enum Command {
    AllUnknowns(bool),
    Update(Box<CircuitIr>),
}

/// What the two threads share.
struct Shared {
    /// Coupling values per sample, published by each side.
    ring_a: Ring,
    ring_b: Ring,
    stop: AtomicBool,
    commands: Mutex<VecDeque<(usize, Command)>>,
    /// The second partition's probes, per sample, not yet collected.
    probes: Mutex<Vec<Vec<f64>>>,
    error: Mutex<Option<Error>>,
}

impl Shared {
    /// Wait until `ring` has published sample `n`; false if stopped. Spins,
    /// then yields, then (idle for milliseconds: a paused stream) sleeps.
    fn wait(&self, ring: &Ring, n: usize) -> bool {
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

    fn fail(&self, e: Error) {
        self.error.lock().expect("error slot").get_or_insert(e);
        self.stop.store(true, Ordering::Relaxed);
    }
}

/// The second partition: its thread, and what it shares with the first.
struct Second {
    shared: Arc<Shared>,
    handle: Option<JoinHandle<()>>,
    /// Titles of its sections, and the shared nodes (for updates).
    titles: Vec<String>,
    nodes: Vec<String>,
}

/// The second partition's thread: step after the first partition's sample,
/// applying commands queued for the sample it steps from.
fn run_second(mut tr: Transient, shared: Arc<Shared>, coupling: Coupling, titles: Vec<String>) {
    let k = tr.mna().outputs.len();
    let (mut e0, mut e1, mut prev, mut out) =
        (vec![0.0; k], vec![0.0; k], vec![0.0; k], vec![0.0; k]);
    let mut n = 0usize;
    loop {
        // Commands for this sample: queued before the first partition publishes it.
        loop {
            let cmd = {
                let mut q = shared.commands.lock().expect("commands");
                match q.front() {
                    Some((at, _)) if *at == n => q.pop_front().map(|c| c.1),
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
        if !shared.wait(&shared.ring_a, n) {
            return;
        }
        ends(coupling, &shared.ring_a, n, &mut e0, &mut e1, &mut prev);
        tr.set_externals(&e0, &e1);
        if let Err(e) = tr.step_input(&StepInput::linear(0.0, 0.0)) {
            shared.fail(Error::new(format!("partition {titles:?}: {e}")));
            return;
        }
        {
            let mut probes = shared.probes.lock().expect("probes");
            for (v, y) in probes.iter_mut().zip(tr.mna().probe_values(tr.x())) {
                v.push(y);
            }
        }
        for (o, &i) in out.iter_mut().zip(&tr.mna().outputs) {
            *o = tr.x()[i];
        }
        n += 1;
        shared.ring_b.publish(n, &out);
    }
}

/// Where each of the IR's probes comes from.
#[derive(Debug, Clone, Copy)]
enum Source {
    First(usize),
    Second(usize),
}

/// A run fed block by block (see the module docs).
pub struct Stream {
    a: Transient,
    second: Option<Second>,
    coupling: Coupling,
    names: Vec<String>,
    sources: Vec<Source>,
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
    /// The second partition's probes at sample 0.
    initial_b: Vec<f64>,
    /// A parameter change waiting for the next sample boundary, and whether the
    /// last step computed every unknown for it.
    pending: Option<(CircuitIr, Option<(CircuitIr, CircuitIr)>)>,
    armed: bool,
    // Scratch.
    e0: Vec<f64>,
    e1: Vec<f64>,
    prev: Vec<f64>,
    out: Vec<f64>,
}

impl Stream {
    /// A stream of `ir` at step `h` with `opts` (a partitioned one needs the DK
    /// solver and a diagonally implicit method), the sections titled in `second`
    /// on a thread of their own (none: one solve), at the DC operating point
    /// with input `u0` (sample 0; [`Stream::initial`] has its probes).
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
        let base = |tr: Transient, second, sources, k| Stream {
            a: tr,
            second,
            coupling,
            names: names.clone(),
            sources,
            order: opts.input_order.max(1),
            hist: vec![u0],
            hist0: 0,
            chist: c0.iter().map(|&c| vec![c]).collect(),
            n: 0,
            len: None,
            initial_b: Vec::new(),
            pending: None,
            armed: false,
            e0: vec![0.0; k],
            e1: vec![0.0; k],
            prev: vec![0.0; k],
            out: vec![0.0; k],
        };
        if second.is_empty() {
            let tr = start(Mna::from_ir(ir, opts.gmin)?, &[], u0)?;
            let sources = (0..names.len()).map(Source::First).collect();
            return Ok(base(tr, None, sources, 0));
        }

        let (a_ir, b_ir, shared_nodes) = split(ir, second)?;
        let k = shared_nodes.len();
        // The shared nodes at the whole circuit's DC operating point.
        let whole = start(Mna::from_ir(ir, opts.gmin)?, &[], u0)?;
        let v_dc: Vec<f64> = shared_nodes
            .iter()
            .map(|n| whole.mna().node(n).map_or(0.0, |i| whole.x()[i]))
            .collect();
        drop(whole);
        // First partition: the shared nodes as sources (externals on their rows,
        // the IR's 0 V plus the external), publishing the sources' currents (+:
        // from the node into the source, what it delivers into the node).
        let mut ma = Mna::from_ir(&a_ir, opts.gmin)?;
        let src: Vec<usize> = shared_nodes
            .iter()
            .map(|n| ma.branch(&format!("{SOURCE_PREFIX}{n}")).expect("added"))
            .collect();
        ma.externals.truncate(ma.n_controls);
        ma.externals.extend_from_slice(&src);
        ma.outputs = src.clone();
        let a = start(ma, &v_dc, u0)?;
        let i_dc: Vec<f64> = src.iter().map(|&i| a.x()[i]).collect();
        // Second: those currents injected into the shared nodes, publishing the
        // nodes' voltages.
        let mut mb = Mna::from_ir(&b_ir, opts.gmin)?;
        let nodes: Vec<usize> = shared_nodes
            .iter()
            .map(|n| mb.node(n).expect("shared"))
            .collect();
        mb.externals = nodes.clone();
        mb.outputs = nodes.clone();
        let b = Transient::with_externals(mb, h, *opts, 0.0, &i_dc)?;

        // The IR's probes from whichever partition has them (the second's
        // first: on a shared node its voltage is the one the first copies).
        let (pa, pb) = (&a.mna().probes, &b.mna().probes);
        let mut sources = Vec::new();
        for name in &names {
            sources.push(if let Some(j) = pb.iter().position(|(p, _)| p == name) {
                Source::Second(j)
            } else if let Some(j) = pa.iter().position(|(p, _)| p == name) {
                Source::First(j)
            } else {
                return Err(Error::new(format!("partition: probe {name} lost")));
            });
        }
        let shared = Arc::new(Shared {
            ring_a: Ring::new(k),
            ring_b: Ring::new(k),
            stop: AtomicBool::new(false),
            commands: Mutex::new(VecDeque::new()),
            probes: Mutex::new(vec![Vec::new(); pb.len()]),
            error: Mutex::new(None),
        });
        // Sample 0 (DC), published by both.
        shared.ring_a.publish(0, &i_dc);
        let b_out: Vec<f64> = nodes.iter().map(|&i| b.x()[i]).collect();
        shared.ring_b.publish(0, &b_out);
        let initial_b: Vec<f64> = b.mna().probe_values(b.x()).collect();
        let titles = second.to_vec();
        let handle = {
            let (shared, titles) = (Arc::clone(&shared), titles.clone());
            std::thread::Builder::new()
                .name("circuitsim partition".into())
                .spawn(move || run_second(b, shared, coupling, titles))
                .map_err(|e| Error::new(format!("partition thread: {e}")))?
        };
        let second = Second {
            shared,
            handle: Some(handle),
            titles,
            nodes: shared_nodes,
        };
        let mut stream = base(a, Some(second), sources, k);
        stream.initial_b = initial_b;
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
        let b = &self.initial_b;
        self.sources
            .iter()
            .map(|s| match *s {
                Source::First(j) => a[j],
                Source::Second(j) => b[j],
            })
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
        let parts = match &self.second {
            None => None,
            Some(s) => {
                let (a, b, nodes) = split(ir, &s.titles)?;
                if nodes != s.nodes {
                    return Err(Error::new(
                        "update: the partitions' shared nodes changed (only values may)",
                    ));
                }
                Some((a, b))
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
        let b_vals: Vec<Vec<f64>> = match &self.second {
            None => Vec::new(),
            Some(s) => {
                // The second partition's samples up to `until`.
                if !s.shared.wait(&s.shared.ring_b, self.n) {
                    return Err(self.first_error(Error::new("stopped")));
                }
                let mut probes = s.shared.probes.lock().expect("probes");
                probes
                    .iter_mut()
                    .map(|v| v.drain(..self.n - first).collect())
                    .collect()
            }
        };
        Ok(self
            .sources
            .iter()
            .map(|s| match *s {
                Source::First(j) => std::mem::take(&mut a_vals[j]),
                Source::Second(j) => b_vals[j].clone(),
            })
            .collect())
    }

    /// The error to report: the second partition's, if it failed first.
    fn first_error(&mut self, e: Error) -> Error {
        if let Some(s) = &self.second {
            s.shared.stop.store(true, Ordering::Relaxed);
            if let Some(f) = s.shared.error.lock().expect("error slot").take() {
                return f;
            }
        }
        e
    }

    /// Step n -> n + 1. A pending update is handled at the end of a step,
    /// before the step's sample is published (the second partition, stepping
    /// concurrently, takes its commands before it steps from that sample): the
    /// first such step arms it (the next step computes every unknown in both
    /// partitions), the next applies it in both at the same boundary.
    fn step_one(&mut self, a_vals: &mut [Vec<f64>]) -> Result<(), Error> {
        let n = self.n;
        // The second partition's values over this sample.
        if let Some(s) = &self.second {
            if !s.shared.wait(&s.shared.ring_b, n) {
                return Err(Error::new("stopped"));
            }
            ends(
                self.coupling,
                &s.shared.ring_b,
                n,
                &mut self.e0,
                &mut self.e1,
                &mut self.prev,
            );
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
        if let Some(s) = &self.second {
            for (o, &i) in self.out.iter_mut().zip(&self.a.mna().outputs) {
                *o = self.a.x()[i];
            }
            s.shared.ring_a.publish(self.n, &self.out);
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
            // The next step computes every unknown, in both partitions.
            self.armed = true;
            self.a.set_all_unknowns(true);
            if let Some(s) = &self.second {
                let mut q = s.shared.commands.lock().expect("commands");
                q.push_back((n, Command::AllUnknowns(true)));
            }
            return Ok(());
        }
        // The last step computed every unknown: apply, in both.
        let (ir, parts) = self.pending.take().expect("pending");
        self.armed = false;
        match (&self.second, parts) {
            (Some(s), Some((a_ir, b_ir))) => {
                {
                    let mut q = s.shared.commands.lock().expect("commands");
                    q.push_back((n, Command::Update(Box::new(b_ir))));
                    q.push_back((n, Command::AllUnknowns(false)));
                }
                self.a.update(&a_ir)?;
            }
            _ => self.a.update(&ir)?,
        }
        self.a.set_all_unknowns(false);
        Ok(())
    }
}

impl Drop for Stream {
    fn drop(&mut self) {
        if let Some(s) = &mut self.second {
            s.shared.stop.store(true, Ordering::Relaxed);
            if let Some(h) = s.handle.take() {
                let _ = h.join();
            }
        }
    }
}
