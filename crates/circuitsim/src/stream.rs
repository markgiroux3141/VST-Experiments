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
//! milliseconds). A multi-rate part whose sections have `lag_samples` reads the others
//! that many samples late and runs ahead of them (TAPE_SPEED_PLAN.md P2); such a stream
//! refuses updates.
//!
//! Environment switches for measurements (TAPE_SPEED_PLAN.md; nothing sets them by
//! default): `CIRCUITSIM_PART_TIMING` prints each part's busy and waiting time and the tape
//! worker's when a partitioned stream ends; `CIRCUITSIM_MULTIRATE_METHOD` (a method name) and
//! `CIRCUITSIM_MULTIRATE_TABLES` give the multi-rate parts their own method and tube tables
//! (P4's experiment; a render with them isn't production's).
//!
//! [`Stream::update`] changes component values (a knob turned): applied at the
//! next sample boundary the stream reaches, in every partition at the same
//! sample. It needs every unknown at that point, so the stream computes them for
//! one sample first (the partitions step concurrently, so the others' commands
//! are queued before the first publishes the sample they apply at). Changes that
//! add or remove nodes are refused, as [`Transient::update`] refuses them; large
//! jumps can stall Newton, so callers ramp them.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use crate::Error;
use crate::ir::{CircuitIr, Element, GROUND, Probe, Resistor, Section, VoltageSource};
use crate::mna::Mna;
use crate::partition::{Coupling, Decimator, Ring, SOURCE_PREFIX, Split, groups, split};
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

/// The stream's input, for a multi-rate part with the input node (`partition.rs`): every
/// sample from `hist0` on, and the input's length once it has ended.
#[derive(Default)]
struct InputHist {
    hist: Vec<f64>,
    hist0: usize,
    len: Option<usize>,
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
    /// The input, when a multi-rate part has the input node.
    input: Mutex<InputHist>,
    /// Per partition: nanoseconds spent waiting for the others (or the input), for
    /// `CIRCUITSIM_PART_TIMING` (TAPE_SPEED_PLAN.md P1).
    waited_ns: Vec<AtomicU64>,
    /// When the stream started (the timing's wall clock).
    created: Instant,
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
    ///
    /// A part reading `lag` > 0 samples late (`Options::multirate_lag`) takes the
    /// published samples n - lag and n + 1 - lag instead (sample 0 before them), and
    /// waits only for those: it runs up to `lag` samples ahead. The others still wait
    /// for its sample n, so it is never behind them, and a ring of 2 lag + 3 samples
    /// is never overwritten while read. False if stopped.
    #[allow(clippy::too_many_arguments)]
    fn feeds(
        &self,
        me: usize,
        coupling: Coupling,
        lag: usize,
        feeds: &[Feed],
        n: usize,
        e0: &mut [f64],
        e1: &mut [f64],
    ) -> bool {
        let (a0, a1) = (n.saturating_sub(lag), (n + 1).saturating_sub(lag));
        let one = |p: usize, slot: usize| -> (f64, f64) {
            if lag > 0 {
                return (self.rings[p].value(a0, slot), self.rings[p].value(a1, slot));
            }
            let x0 = self.rings[p].value(n, slot);
            match (coupling, n) {
                (Coupling::Extrapolate, 1..) => (x0, 2.0 * x0 - self.rings[p].value(n - 1, slot)),
                _ => (x0, x0),
            }
        };
        let t0 = Instant::now();
        let target = if lag > 0 { a1 } else { n };
        for p in 0..self.rings.len() {
            if p != me && !self.wait(p, target) {
                return false;
            }
        }
        self.waited_ns[me].fetch_add(t0.elapsed().as_nanos() as u64, Ordering::Relaxed);
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

    /// Medium feed `f`'s senses over sample n -> n + 1: the source part's, published
    /// with sample n (the sample before: the literal bias's lag). Call after `feeds`.
    fn batch(&self, f: &MediaFeed, n: usize, buf: &mut Vec<f64>) {
        buf.clear();
        buf.extend((0..f.m).map(|j| self.rings[f.part].value(n, f.slot + j)));
    }

    /// The input over step n -> n + 1 (interpolation `order`), as the first partition
    /// takes it (`Stream::step_one`), once the samples it needs are in; None if stopped or
    /// the input has ended before it.
    fn input_window(&self, me: usize, n: usize, order: usize) -> Option<StepInput> {
        let half = (order - 1) / 2;
        let t0 = Instant::now();
        let mut spins = 0u32;
        let mut since: Option<Instant> = None;
        loop {
            if self.stop.load(Ordering::Relaxed) {
                return None;
            }
            {
                let mut g = self.input.lock().expect("input");
                if g.len.is_some_and(|len| n + 1 >= len) {
                    return None;
                }
                let known = g.hist0 + g.hist.len();
                let hi = match g.len {
                    Some(len) => (n + 1 + half).min(len - 1),
                    None => n + 1 + half,
                };
                if hi < known {
                    let at = |k: usize| g.hist[k - g.hist0];
                    let inp = if order == 1 {
                        StepInput::linear(at(n), at(n + 1))
                    } else {
                        let lo = n.saturating_sub(half);
                        let w = &g.hist[lo - g.hist0..=hi - g.hist0];
                        StepInput::lagrange(w, lo as i32 - n as i32)
                    };
                    // Samples no later step reads.
                    let keep = n.saturating_sub(half + 1);
                    if keep > g.hist0 + 4096 {
                        let d = keep - g.hist0;
                        g.hist.drain(..d);
                        g.hist0 = keep;
                    }
                    self.waited_ns[me].fetch_add(t0.elapsed().as_nanos() as u64, Ordering::Relaxed);
                    return Some(inp);
                }
            }
            spins += 1;
            if spins < 1 << 10 {
                std::hint::spin_loop();
            } else if since.get_or_insert_with(Instant::now).elapsed() < Duration::from_millis(2) {
                std::thread::yield_now();
            } else {
                std::thread::sleep(Duration::from_micros(100));
            }
        }
    }

    fn fail(&self, e: Error) {
        self.error.lock().expect("error slot").get_or_insert(e);
        self.stop.store(true, Ordering::Relaxed);
    }
}

/// A medium of this part fed another part's senses (a tape's literal bias): its index
/// in `Mna::media`, the part publishing them and its first slot, m per sample.
#[derive(Debug, Clone)]
struct MediaFeed {
    medium: usize,
    part: usize,
    slot: usize,
    m: usize,
}

/// What a part publishes and reads besides its couplings' externals.
#[derive(Debug, Clone, Default)]
struct PartIo {
    /// Steps per sample.
    substeps: usize,
    /// Its owned nodes, then its sources: the couplings it publishes.
    n_owned: usize,
    n_coupling: usize,
    /// A multi-rate part: the senses it publishes after each step (unknowns; None:
    /// ground), each `substeps` slots after the couplings.
    senses: Vec<(Option<usize>, Option<usize>)>,
    /// Its media fed other parts' senses.
    feeds: Vec<MediaFeed>,
    /// A multi-rate part with the audio input: the input's interpolation order.
    input_order: Option<usize>,
    /// A multi-rate part handing on its values through a [`Decimator`].
    decimate: bool,
    /// Samples late it reads the others (`Options::multirate_lag`; 0: lockstep).
    lag: usize,
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
    /// The first partition's media fed other parts' senses.
    media_feeds: Vec<MediaFeed>,
    /// A multi-rate part has the input: it reads the stream's input (`InputHist`).
    shares_input: bool,
    /// The first partition's senses for tapes elsewhere (unknowns; None: ground),
    /// published after its couplings.
    senses: Vec<(Option<usize>, Option<usize>)>,
    /// A part reads the others late (`Options::multirate_lag`): it may be ahead of a
    /// sample boundary when a command for it is queued, so updates are refused.
    lagged: bool,
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
    io: PartIo,
) {
    let (substeps, n_owned, n_coupling) = (io.substeps, io.n_owned, io.n_coupling);
    let k = feeds.len();
    let (mut e0, mut e1) = (vec![0.0; k], vec![0.0; k]);
    let (mut ea, mut eb) = (vec![0.0; k], vec![0.0; k]);
    let mut out = vec![0.0; n_coupling + substeps * io.senses.len()];
    let mut buf = Vec::new();
    // Its couplings, then its probes, through the decimator (started at the DC point).
    let mut dec = io.decimate.then(|| {
        let x = tr.x();
        let init: Vec<f64> = tr.mna().outputs[..n_coupling]
            .iter()
            .map(|&i| x[i])
            .chain(tr.mna().probe_values(x))
            .collect();
        Decimator::new(substeps, &init)
    });
    let mut n = 0usize;
    loop {
        // Every partition's sample n first: the first partition queues the commands
        // for sample n before it publishes it, so they are all here after this (read
        // before the wait, a partition running ahead missed them and never applied a
        // knob turned on its sections).
        if !shared.feeds(p, coupling, io.lag, &feeds, n, &mut e0, &mut e1) {
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
        for f in &io.feeds {
            shared.batch(f, n, &mut buf);
            tr.set_media_batch(f.medium, &buf);
        }
        let inp = match io.input_order {
            Some(order) => match shared.input_window(p, n, order) {
                Some(inp) => inp,
                // Stopped, or the input has ended: nothing more to step.
                None => return,
            },
            None => StepInput::linear(0.0, 0.0),
        };
        if substeps == 1 {
            tr.set_externals(&e0, &e1);
            if let Err(e) = tr.step_input(&inp) {
                shared.fail(Error::new(format!("partition {titles:?}: {e}")));
                return;
            }
            // Its senses for tapes elsewhere (a tape cut from its record head).
            let at = |u: Option<usize>| u.map_or(0.0, |i| tr.x()[i]);
            for (r, &(a, b)) in io.senses.iter().enumerate() {
                out[n_coupling + r] = at(a) - at(b);
            }
        } else {
            // A multi-rate part: its steps across the sample, the others' values
            // interpolated over each; its sources' currents averaged over them.
            let m = substeps as f64;
            let mut sum = vec![0.0; n_coupling];
            for j in 0..substeps {
                let (fa, fb) = (j as f64 / m, (j + 1) as f64 / m);
                for i in 0..k {
                    ea[i] = e0[i] + (e1[i] - e0[i]) * fa;
                    eb[i] = e0[i] + (e1[i] - e0[i]) * fb;
                }
                tr.set_externals(&ea, &eb);
                if let Err(e) = tr.step_input(&inp.sub(j, substeps)) {
                    shared.fail(Error::new(format!("partition {titles:?}: {e}")));
                    return;
                }
                for (s, &i) in sum.iter_mut().zip(&tr.mna().outputs) {
                    *s += tr.x()[i];
                }
                if let Some(d) = dec.as_mut() {
                    let x = tr.x();
                    let outs = tr.mna().outputs[..n_coupling].iter().map(|&i| x[i]);
                    d.push(outs.chain(tr.mna().probe_values(x)));
                }
                let at = |u: Option<usize>| u.map_or(0.0, |i| tr.x()[i]);
                for (r, &(a, b)) in io.senses.iter().enumerate() {
                    out[n_coupling + r * substeps + j] = at(a) - at(b);
                }
            }
            match &dec {
                Some(d) => {
                    for (k, o) in out.iter_mut().enumerate().take(n_coupling) {
                        *o = d.output(k);
                    }
                }
                None => {
                    for (o, s) in out.iter_mut().zip(&sum).skip(n_owned) {
                        *o = s / m;
                    }
                }
            }
        }
        {
            let mut probes = shared.probes[p].lock().expect("probes");
            match &dec {
                Some(d) => {
                    for (k, v) in probes.iter_mut().enumerate() {
                        v.push(d.output(n_coupling + k));
                    }
                }
                None => {
                    for (v, y) in probes.iter_mut().zip(tr.mna().probe_values(tr.x())) {
                        v.push(y);
                    }
                }
            }
        }
        // Owned nodes at the sample's end; a single-rate part's sources' currents too (a
        // decimating part's are all the decimator's, above).
        let ends = match (substeps, &dec) {
            (1, _) => n_coupling,
            (_, Some(_)) => 0,
            _ => n_owned,
        };
        for (o, &i) in out.iter_mut().zip(&tr.mna().outputs).take(ends) {
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
    batch: Vec<f64>,
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
            batch: Vec::new(),
        };
        if groups(second).is_empty() && !ir.multirate() {
            let tr = start(Mna::from_ir(ir, opts.gmin)?, &[], u0)?;
            let sources = (0..names.len()).map(|j| (0, j)).collect();
            return Ok(base(tr, None, sources, 0));
        }

        let sp = split(ir, second)?;
        // A harp's events go to the first part's transient (`Stream::queue_notes`).
        if let Some(e) = sp.parts[1..]
            .iter()
            .flat_map(CircuitIr::elements)
            .find(|e| {
                matches!(
                    e,
                    Element::Harp(_) | Element::ClavStrings(_) | Element::NovaKeys(_)
                )
            })
        {
            return Err(Error::new(format!(
                "partition: the keys' medium {} must stay in the first part (its keys are played there)",
                e.name()
            )));
        }
        let n_parts = sp.parts.len();
        // The shared nodes at the whole circuit's DC operating point.
        let whole = start(Mna::from_ir(ir, opts.gmin)?, &[], u0)?;
        let v_dc: Vec<f64> = sp
            .shared
            .iter()
            .map(|s| whole.mna().node(&s.name).map_or(0.0, |i| whole.x()[i]))
            .collect();
        drop(whole);
        // Each partition at the DC point: its sources at the shared nodes'
        // voltages, its owned nodes fed the currents its users' sources deliver.
        // Users are solved before their owners: the multi-rate parts first (they own
        // nothing), then the others in order (a single-rate part's users are
        // lower-numbered).
        // A multi-rate part owning nodes can close a loop of ownership (it uses the
        // supply, the supply's part uses its output: users can't all be solved before
        // their owners). Then every part's currents come from a solve with all its shared
        // nodes held at the whole circuit's DC voltages, laid out as its outputs. An owned
        // node is held through 1 mOhm (a source of its own may already hold it: two in
        // parallel are singular); the currents it gives are the same to that resistance.
        let loops = (0..n_parts).any(|p| sp.substeps[p] > 1 && !sp.owned(p).is_empty());
        let mut held_dc: Vec<Vec<f64>> = Vec::new();
        if loops {
            for p in 0..n_parts {
                let (owned, sourced) = (sp.owned(p), sp.sourced(p));
                let mut ir_p = sp.parts[p].clone();
                ir_p.sections.push(Section {
                    title: "partition: the DC start's held nodes".into(),
                    substeps: None,
                    decimate: None,
                    owns: None,
                    lag_samples: None,
                    elements: owned
                        .iter()
                        .flat_map(|&i| {
                            let n = &sp.shared[i].name;
                            let held = format!("partition_held:{n}");
                            [
                                Element::VoltageSource(VoltageSource {
                                    name: format!("{SOURCE_PREFIX}{n}"),
                                    pos: held.clone(),
                                    neg: GROUND.into(),
                                    dc_v: 0.0,
                                }),
                                Element::Resistor(Resistor {
                                    name: format!("RPART_HELD_{n}"),
                                    a: held,
                                    b: n.clone(),
                                    r_ohm: 1e-3,
                                }),
                            ]
                        })
                        .collect(),
                });
                let mut mna = Mna::from_ir(&ir_p, opts.gmin)?;
                let held: Vec<usize> = owned.iter().chain(&sourced).copied().collect();
                let br: Vec<usize> = held
                    .iter()
                    .map(|&i| {
                        mna.branch(&format!("{SOURCE_PREFIX}{}", sp.shared[i].name))
                            .expect("added")
                    })
                    .collect();
                mna.externals.truncate(mna.n_controls + mna.n_media);
                mna.externals.extend_from_slice(&br);
                let ext: Vec<f64> = held.iter().map(|&i| v_dc[i]).collect();
                let tr = if p == 0 {
                    start(mna, &ext, u0)?
                } else {
                    let u = if p == sp.input_part { u0 } else { 0.0 };
                    Transient::with_externals(mna, h, *opts, u, &ext)?
                };
                let mut o: Vec<f64> = owned.iter().map(|&i| v_dc[i]).collect();
                o.extend(br[owned.len()..].iter().map(|&b| tr.x()[b]));
                held_dc.push(o);
            }
        }
        let mut slots: Vec<Option<(Transient, Vec<Feed>)>> = (0..n_parts).map(|_| None).collect();
        let mut dc_out: Vec<Vec<f64>> = vec![Vec::new(); n_parts];
        let mut ios: Vec<PartIo> = vec![PartIo::default(); n_parts];
        let order: Vec<usize> = (0..n_parts)
            .filter(|&p| sp.substeps[p] > 1)
            .chain((0..n_parts).filter(|&p| sp.substeps[p] == 1))
            .collect();
        for &p in &order {
            let mut mna = Mna::from_ir(&sp.parts[p], opts.gmin)?;
            let f = couple(&sp, p, &mut mna);
            // A multi-rate part's senses for tapes elsewhere: computed every step.
            let n_coupling = mna.outputs.len();
            let senses: Vec<(Option<usize>, Option<usize>)> = sp
                .remote
                .iter()
                .filter(|r| r.source == p)
                .map(|r| (mna.node(&r.pos), mna.node(&r.neg)))
                .collect();
            for &(a, b) in &senses {
                mna.outputs.extend(a.into_iter().chain(b));
            }
            ios[p] = PartIo {
                substeps: sp.substeps[p],
                n_owned: sp.owned(p).len(),
                n_coupling,
                senses,
                feeds: Vec::new(),
                input_order: (p == sp.input_part && p > 0).then_some(opts.input_order.max(1)),
                decimate: sp.decimate[p].is_some(),
                lag: 0,
            };
            let ext: Vec<f64> = f
                .iter()
                .map(|f| match f {
                    Feed::Value(q, slot) => {
                        // A sourced node: its voltage at DC.
                        let i = sp.owned(*q)[*slot];
                        v_dc[i]
                    }
                    Feed::Sum(v) => v
                        .iter()
                        .map(|&(u, slot)| {
                            if loops {
                                held_dc[u][slot]
                            } else {
                                dc_out[u][slot]
                            }
                        })
                        .sum(),
                })
                .collect();
            let tr = if p == 0 {
                start(mna, &ext, u0)?
            } else {
                let u = if p == sp.input_part { u0 } else { 0.0 };
                // A multi-rate part steps at a fixed fine step chosen for its fast
                // dynamics, without local error control: there its subdivisions follow
                // where the fast signal's peaks fall in a step and beat against it (the
                // Ampex 351's bias: a line near 96 kHz - f_osc in the noise, 18 dB lower
                // without; docs/TAPE_PLAN.md "Speed").
                let mut o = *opts;
                if sp.substeps[p] > 1 {
                    o.error_abstol = 0.0;
                    // P4's experiment switches (the module docs): the fast part's method and
                    // tube tables.
                    if let Ok(m) = std::env::var("CIRCUITSIM_MULTIRATE_METHOD") {
                        o.method = crate::transient::Method::parse(&m)?;
                    }
                    if std::env::var_os("CIRCUITSIM_MULTIRATE_TABLES").is_some() {
                        o.tube_tables = true;
                    }
                }
                Transient::with_externals(mna, h / sp.substeps[p] as f64, o, u, &ext)?
            };
            let mut o: Vec<f64> = tr.mna().outputs[..n_coupling]
                .iter()
                .map(|&i| tr.x()[i])
                .collect();
            let at = |u: Option<usize>| u.map_or(0.0, |i| tr.x()[i]);
            for &(a, b) in &ios[p].senses {
                o.extend(std::iter::repeat_n(at(a) - at(b), sp.substeps[p]));
            }
            dc_out[p] = o;
            slots[p] = Some((tr, f));
        }
        let (mut trs, mut feeds): (Vec<Transient>, Vec<Vec<Feed>>) = (Vec::new(), Vec::new());
        for s in slots {
            let (tr, f) = s.expect("every part solved");
            trs.push(tr);
            feeds.push(f);
        }
        // Each tape's literal bias: the source's slots for it.
        for r in &sp.remote {
            let medium = trs[r.reader]
                .mna()
                .media
                .iter()
                .position(|m| m.element.name() == r.medium)
                .expect("the tape is in its part");
            let k = sp
                .remote
                .iter()
                .filter(|q| q.source == r.source)
                .position(|q| q == r)
                .expect("its source serves it");
            let src = &ios[r.source];
            let feed = MediaFeed {
                medium,
                part: r.source,
                slot: src.n_coupling + k * src.substeps,
                m: r.m,
            };
            ios[r.reader].feeds.push(feed);
        }
        // The parts that read the others late (their sections' `lag_samples`;
        // TAPE_SPEED_PLAN.md P2): multi-rate, owning nothing, not decimating (the IR checks
        // those), reading no senses.
        for (p, io) in ios.iter_mut().enumerate() {
            if sp.lag[p] > 0 {
                if !io.feeds.is_empty() || !sp.owned(p).is_empty() {
                    return Err(Error::new(format!(
                        "partition {:?}: lag_samples in a part that owns shared nodes or \
                         reads another part's senses",
                        sp.titles[p]
                    )));
                }
                io.lag = sp.lag[p];
            }
        }
        let max_lag = ios.iter().map(|io| io.lag).max().unwrap_or(0);
        let lagged = max_lag > 0;
        let depth = 2 * max_lag + 3;

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
            rings: dc_out.iter().map(|o| Ring::new(o.len(), depth)).collect(),
            stop: AtomicBool::new(false),
            commands: (0..n_parts).map(|_| Mutex::new(VecDeque::new())).collect(),
            probes: trs
                .iter()
                .map(|t| Mutex::new(vec![Vec::new(); t.mna().probes.len()]))
                .collect(),
            error: Mutex::new(None),
            input: Mutex::new(InputHist {
                hist: vec![u0],
                hist0: 0,
                len: None,
            }),
            waited_ns: (0..n_parts).map(|_| AtomicU64::new(0)).collect(),
            created: Instant::now(),
        });
        // Sample 0 (DC), published by all.
        for (ring, o) in shared.rings.iter().zip(&dc_out) {
            ring.publish(0, o);
        }
        let initial: Vec<Vec<f64>> = trs
            .iter()
            .map(|t| t.mna().probe_values(t.x()).collect())
            .collect();
        let mut handles = vec![None];
        let mut trs = trs.into_iter();
        let a = trs.next().expect("the first partition");
        for (p, tr) in trs.enumerate().map(|(i, t)| (i + 1, t)) {
            let (shared, f, titles) = (Arc::clone(&shared), feeds[p].clone(), sp.titles[p].clone());
            let io = ios[p].clone();
            handles.push(Some(
                std::thread::Builder::new()
                    .name(format!("circuitsim partition {p}"))
                    .spawn(move || run_part(tr, shared, coupling, p, f, titles, io))
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
            media_feeds: ios[0].feeds.clone(),
            shares_input: sp.input_part > 0,
            senses: ios[0].senses.clone(),
            lagged,
        };
        let out_len = ios[0].n_coupling + ios[0].senses.len();
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
            Some(s) if s.lagged => {
                return Err(Error::new(
                    "update: a part reads the others late (multirate_lag): renders only",
                ));
            }
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
        self.a.notes_known_until(self.hist0 + self.hist.len() - 1);
        if let Some(s) = self.parts.as_ref().filter(|s| s.shares_input) {
            s.shared
                .input
                .lock()
                .expect("input")
                .hist
                .extend_from_slice(input);
        }
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

    /// A keyboard's events for the media played by keys (a harp), each at an offset into
    /// the next [`Stream::process_with`]'s input (in order): it lands at that sample.
    /// Without any, the media play on (a harp renders ahead to the input's last sample).
    pub fn queue_notes(&mut self, notes: &[(usize, crate::media::NoteEvent)]) -> Result<(), Error> {
        crate::transient::check_notes(notes)?;
        let next = self.hist0 + self.hist.len();
        for &(offset, ev) in notes {
            self.a.queue_note(next + offset, ev);
        }
        Ok(())
    }

    /// Whether a medium is played by keys (a harp: [`Stream::queue_notes`]).
    pub fn has_keys(&self) -> bool {
        self.a.has_keys()
    }

    /// The input has ended: step the samples the lookahead held back (their
    /// interpolation windows shortened at the end, as a whole run's are).
    pub fn finish(&mut self) -> Result<Vec<Vec<f64>>, Error> {
        let known = self.hist0 + self.hist.len();
        self.len = Some(known);
        if let Some(s) = self.parts.as_ref().filter(|s| s.shares_input) {
            s.shared.input.lock().expect("input").len = Some(known);
        }
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
                .feeds(0, self.coupling, 0, &s.feeds, n, &mut self.e0, &mut self.e1)
            {
                return Err(Error::new("stopped"));
            }
            self.a.set_externals(&self.e0, &self.e1);
            for f in &s.media_feeds {
                s.shared.batch(f, n, &mut self.batch);
                self.a.set_media_batch(f.medium, &self.batch);
            }
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
            let n_coupling = self.out.len() - s.senses.len();
            for (o, &i) in self
                .out
                .iter_mut()
                .zip(&self.a.mna().outputs)
                .take(n_coupling)
            {
                *o = self.a.x()[i];
            }
            let x = self.a.x();
            let at = |u: Option<usize>| u.map_or(0.0, |i| x[i]);
            for (r, &(a, b)) in s.senses.iter().enumerate() {
                self.out[n_coupling + r] = at(a) - at(b);
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
            if std::env::var_os("CIRCUITSIM_PART_TIMING").is_some() {
                let wall = s.shared.created.elapsed().as_secs_f64();
                let waits: Vec<String> = s
                    .shared
                    .waited_ns
                    .iter()
                    .enumerate()
                    .map(|(p, w)| {
                        let w = w.load(Ordering::Relaxed) as f64 * 1e-9;
                        format!("part {p} busy {:.2} s wait {:.2} s", wall - w, w)
                    })
                    .collect();
                eprintln!(
                    "circuitsim partition timing: wall {wall:.2} s, {} samples; {}; {}",
                    self.n,
                    waits.join("; "),
                    crate::tape_stream::timing_line()
                );
            }
            s.shared.stop.store(true, Ordering::Relaxed);
            for h in s.handles.iter_mut() {
                if let Some(h) = h.take() {
                    let _ = h.join();
                }
            }
        }
    }
}
