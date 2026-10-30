//! Real-time playback: audio through a device's circuit while its front panel turns.
//! The Rust port of `varimu/sim/live.py` (the web Play page's engine).
//!
//! A [`Live`] session runs a circuitsim [`Stream`] at a quality fast enough for real
//! time (draft-1x: a 48 kHz host at 1x, the supplies on a second thread; the user's
//! choice for playing) and hands out its output in blocks at the host rate. The input
//! is a file's loop region (resampled to the host rate once, its seam crossfaded) or
//! blocks the caller passes in (live input, [`Live::process`]).
//!
//! Knob changes ([`Live::set`]) are built into a circuit IR on a thread of their own,
//! and the newest is handed to the stream at the next block: the same circuit with
//! other values updates it in place ([`Stream::update`]); a change of structure (the
//! 670's input pad at its 0 dB end, Time Constant 5-6, an EQP-1A selector that
//! rewires: other nodes or elements) starts a new stream in the background, settled
//! like a render's start, and the output crossfades to it over one block.
//!
//! A new circuit ([`Live::set_circuit`]: the editor's drawing, edited) takes the same
//! path: the same structure updates the stream, another one restarts it.
//!
//! At a quality with oversampling (draft-2x: the draft's 96 kHz behind a 48 kHz host),
//! each block's input is upsampled into the stream and each stream's output decimated
//! back (`StreamResampler`, scipy's `resample_poly` filter): the host and the audio
//! device stay at the host rate. At 1x both pass samples through unchanged.
//!
//! Blocks must keep up with real time on average; the caller's buffer absorbs the rest.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Condvar, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use circuitsim::ir::{CircuitIr, Element};
use circuitsim::stream::Stream;
use varimu_circuit::spec::{self, CircuitSpec, FullScale};
use varimu_circuit::yaml::Value;
use varimu_circuit::{Cores, Library, build_ir};

use crate::resample::{StreamResampler, resample};
use crate::settings::Settings;

/// The loop's seam: its end crossfades into its start over this long.
pub const LOOP_FADE_S: f64 = 0.01;

/// Values for a circuit's parameters (controls, values, device parameters), as a
/// render's overrides.
pub type Values = Vec<(String, Value)>;

/// A circuit file built into IRs: what [`Live`] and renders build from.
pub struct Circuit {
    lib: Arc<Library>,
    spec: CircuitSpec,
    cores: Cores,
}

impl Circuit {
    /// `config/circuits/<name>.yaml` (or a .yaml path), built with `cores`.
    pub fn load(config_dir: &Path, name: &str, cores: Cores) -> Result<Circuit, String> {
        let path = if name.ends_with(".yaml") {
            PathBuf::from(name)
        } else {
            spec::circuit_path(config_dir, name).map_err(|e| e.to_string())?
        };
        Ok(Circuit {
            lib: Arc::new(Library::new(config_dir)),
            spec: spec::load_circuit(&path).map_err(|e| e.to_string())?,
            cores,
        })
    }

    /// A circuit already read (the editor's compiled drawing), its device files and
    /// materials from `lib`.
    pub fn from_spec(lib: Arc<Library>, spec: CircuitSpec, cores: Cores) -> Circuit {
        Circuit { lib, spec, cores }
    }

    pub fn spec(&self) -> &CircuitSpec {
        &self.spec
    }

    /// Its volts at full scale in and out: the file's `full_scale`, or the settings'
    /// `full_scale_volts_peak` for both (`varimu.sim.io.full_scale`).
    pub fn full_scale(&self, s: &Settings) -> FullScale {
        self.spec.full_scale.unwrap_or(FullScale {
            input_v: s.full_scale_volts_peak,
            output_v: s.full_scale_volts_peak,
            output_pascals: false,
        })
    }

    pub fn build(&self, values: &Values) -> Result<CircuitIr, String> {
        let p = spec::resolve(&self.spec, values).map_err(|e| e.to_string())?;
        build_ir(&self.lib, &self.spec, &p, self.cores).map_err(|e| e.to_string())
    }
}

/// What a stream can't change in place: its elements (kind, name) and nodes
/// (`live.structure`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Structure {
    elements: BTreeSet<(&'static str, String)>,
    nodes: BTreeSet<String>,
}

pub fn structure(ir: &CircuitIr) -> Structure {
    let mut elements = BTreeSet::new();
    let mut nodes = BTreeSet::new();
    for e in ir.sections.iter().flat_map(|s| &s.elements) {
        let (kind, name, ns): (&'static str, &str, Vec<&String>) = match e {
            Element::Resistor(r) => ("Resistor", &r.name, vec![&r.a, &r.b]),
            Element::Capacitor(c) => ("Capacitor", &c.name, vec![&c.a, &c.b]),
            Element::Inductor(l) => ("Inductor", &l.name, vec![&l.a, &l.b]),
            Element::Coupling(k) => ("Coupling", &k.name, vec![]),
            Element::VoltageSource(v) => ("VoltageSource", &v.name, vec![&v.pos, &v.neg]),
            Element::SineSource(v) => ("SineSource", &v.name, vec![&v.pos, &v.neg]),
            Element::Winding(w) => ("Winding", &w.name, vec![&w.a, &w.b]),
            Element::Vccs(g) => (
                "Vccs",
                &g.name,
                vec![&g.pos, &g.neg, &g.ctrl_pos, &g.ctrl_neg],
            ),
            Element::NoiseCurrent(n) => ("NoiseCurrent", &n.name, vec![&n.a, &n.b]),
            Element::TubeNoise(t) => ("TubeNoise", &t.name, vec![]),
            Element::Device(d) => ("Device", &d.name, d.nodes.iter().collect()),
        };
        elements.insert((kind, name.to_string()));
        nodes.extend(ns.into_iter().cloned());
    }
    Structure { elements, nodes }
}

/// numpy's `linspace(0.0, 1.0, n)`: `i * (1 / (n - 1))`, the last point exactly 1.
pub fn linspace01(n: usize) -> Vec<f64> {
    if n < 2 {
        return vec![0.0; n];
    }
    let step = 1.0 / (n - 1) as f64;
    let mut w: Vec<f64> = (0..n).map(|i| i as f64 * step + 0.0).collect();
    w[n - 1] = 1.0;
    w
}

/// `x` as a loop: its last LOOP_FADE_S crossfaded into its start (`live.make_loop`).
pub fn make_loop(x: &[f64], rate: u32) -> Vec<f64> {
    let n = ((LOOP_FADE_S * rate as f64) as usize).min(x.len() / 4);
    if n < 2 {
        return x.to_vec();
    }
    let mut y = x[..x.len() - n].to_vec();
    let tail = &x[x.len() - n..];
    for (i, w) in linspace01(n).into_iter().enumerate() {
        y[i] = x[i] * w + tail[i] * (1.0 - w);
    }
    y
}

/// One block's levels.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct Meter {
    /// The circuit's gain, output volts (or pascals) vs input volts, dB (rms).
    pub gain_db: f64,
    /// Output level, dBFS (rms of a sine of that peak: rms * sqrt 2).
    pub out_dbfs: f64,
    /// The sound pressure level, dB SPL (rms re 20 uPa), when the output is a pressure
    /// (a speaker's readout: the file's `output_pascals_peak`).
    pub spl_db: Option<f64>,
    /// The 670's control voltage (mean over the block), V.
    pub cv_v: Option<f64>,
    /// Compute time / audio time of the block.
    pub load: f64,
}

/// A stream and where its probes are.
struct Running {
    stream: Stream,
    structure: Structure,
    out: usize,
    cv: Option<usize>,
    /// Its circuit's volts at full scale.
    fs: FullScale,
    /// Its output from the simulation's rate to the host's (1x: unchanged).
    down: StreamResampler,
}

impl Running {
    /// A stream at the DC point with input `u0` and the control inputs at `c0` (IR
    /// order; empty: 0 V), settled for `settle_s` with both held at the simulation's
    /// rate (its decimator primed with that output).
    fn new(
        ir: &CircuitIr,
        u0: f64,
        c0: &[f64],
        s: &Settings,
        fs: FullScale,
    ) -> Result<Running, String> {
        let v = fs.input_v;
        let k = s.oversample as usize;
        let opts = s.stream_options()?;
        let second = s.partition_sections(ir);
        let h = 1.0 / s.sim_rate() as f64;
        let c0 = if c0.len() == ir.controls.len() {
            c0
        } else {
            &[]
        };
        let mut stream = Stream::with_controls(ir, &second, s.coupling()?, h, &opts, u0 * v, c0)
            .map_err(|e| e.to_string())?;
        let find = |name: &str| stream.names().iter().position(|n| n == name);
        let out = find("v(out)").ok_or("the circuit has no `out` probe")?;
        let cv = find("v(cv)");
        let mut down = StreamResampler::new(1, k);
        let n0 = (s.settle_s * s.host() as f64) as usize;
        if n0 > 0 {
            let o = stream
                .process(&vec![u0 * v; n0 * k])
                .map_err(|e| e.to_string())?;
            down.process(&o[out], &mut Vec::new());
        }
        Ok(Running {
            stream,
            structure: structure(ir),
            out,
            cv,
            fs,
            down,
        })
    }
}

/// Host samples a stream's output lags its input: the input interpolation's lookahead
/// (`Stream`'s docs, `l_sim` samples at the simulation's rate) and, oversampled, the
/// resamplers' (each output is index-aligned; the lag is what hasn't come out yet).
/// Counts samples through the chain as [`Live`] runs it: `n0` settling samples held
/// (the upsampler primed, the stream fed at its own rate), then a block.
fn chain_lag(k: usize, l_sim: usize, n0: usize) -> usize {
    let (mut up, mut down) = (StreamResampler::new(k, 1), StreamResampler::new(1, k));
    let (mut u, mut y) = (Vec::new(), Vec::new());
    let (mut held, mut pending) = (0.0, 0.0);
    let mut first = true;
    let mut stream_out = |n: usize| {
        let lost = if first { l_sim.min(n) } else { 0 };
        first = false;
        n - lost
    };
    if n0 > 0 {
        up.process(&vec![0.0; n0], &mut u);
        pending = (n0 * k - u.len()) as f64 / k as f64; // in the upsampler, host samples
        down.process(&vec![0.0; stream_out(n0 * k)], &mut y);
        held = n0 as f64 - y.len() as f64;
    }
    let n = 4096;
    u.clear();
    y.clear();
    up.process(&vec![0.0; n], &mut u);
    down.process(&vec![0.0; stream_out(u.len())], &mut y);
    (held + pending + n.saturating_sub(y.len()) as f64).round() as usize
}

enum Ready {
    Update(Box<CircuitIr>, Values),
    Restart(Box<Running>, Values),
}

/// What the caller and the builder thread share.
struct Shared {
    wanted: Mutex<Option<Values>>,
    /// A new circuit to build the wanted values with.
    circuit: Mutex<Option<Circuit>>,
    wake: Condvar,
    closed: AtomicBool,
    /// The next input sample (f64 bits): a restarted stream starts there.
    u0: AtomicU64,
    /// The control inputs' latest values: a restarted stream starts at them.
    c0: Mutex<Vec<f64>>,
    error: Mutex<Option<String>>,
}

/// Audio through a circuit in real time, its values changeable (see the module docs).
pub struct Live {
    s: Settings,
    /// The host rate: input and output samples per second.
    pub rate: u32,
    looped: Vec<f64>,
    pos: usize,
    run: Running,
    fade: Option<Box<Running>>,
    shared: Arc<Shared>,
    ready: Receiver<Ready>,
    builder: Option<JoinHandle<()>>,
    /// Streams restarted for changes of structure.
    pub restarts: usize,
    /// Input gain (linear): the source's level into the unit, as a console's fader
    /// sets it (1: as recorded). Applied before everything else, so it changes at once.
    pub gain: f64,
    /// The last block's input as the circuit took it (after the gain).
    last_input: Vec<f64>,
    /// The values playing now.
    pub values: Values,
    /// The input from the host's rate to the simulation's (1x: unchanged), shared by a
    /// stream and the one fading in.
    up: StreamResampler,
    lag: usize,
    /// The control inputs' last values (IR order): where their next block starts.
    controls: Vec<f64>,
}

impl Live {
    /// A session on `circuit` with `values`, looping `clip` (at the project's rate,
    /// `s.sample_rate`; empty for live input, fed through [`Live::process`]).
    pub fn new(
        clip: &[f64],
        values: Values,
        circuit: Circuit,
        s: Settings,
    ) -> Result<Live, String> {
        Live::with_gain(clip, values, circuit, s, 1.0)
    }

    /// [`Live::new`] at an input gain: the circuit settles at the gained first sample.
    pub fn with_gain(
        clip: &[f64],
        values: Values,
        circuit: Circuit,
        s: Settings,
        gain: f64,
    ) -> Result<Live, String> {
        Live::with_controls(clip, values, circuit, s, gain, &[])
    }

    /// [`Live::with_gain`] with the circuit's control inputs at `c0` to start (IR order;
    /// empty: 0 V), fed through [`Live::process_with`].
    pub fn with_controls(
        clip: &[f64],
        values: Values,
        circuit: Circuit,
        s: Settings,
        gain: f64,
        c0: &[f64],
    ) -> Result<Live, String> {
        let rate = s.host();
        let looped = if clip.is_empty() {
            Vec::new()
        } else {
            let x = resample(clip, s.sample_rate, rate);
            if x.len() < (rate / 10) as usize {
                return Err("the loop is shorter than 0.1 s".into());
            }
            make_loop(&x, rate)
        };
        let u0 = looped.first().copied().unwrap_or(0.0) * gain;
        let ir = circuit.build(&values)?;
        let c0: Vec<f64> = if c0.len() == ir.controls.len() {
            c0.to_vec()
        } else {
            vec![0.0; ir.controls.len()]
        };
        let run = Running::new(&ir, u0, &c0, &s, circuit.full_scale(&s))?;
        // The upsampler continues from the settling's held input.
        let k = s.oversample as usize;
        let mut up = StreamResampler::new(k, 1);
        let n0 = (s.settle_s * rate as f64) as usize;
        up.process(&vec![u0; n0], &mut Vec::new());
        let lag = chain_lag(k, (s.input_order.max(1) - 1) / 2 + 1, n0);
        let shared = Arc::new(Shared {
            wanted: Mutex::new(None),
            circuit: Mutex::new(None),
            wake: Condvar::new(),
            closed: AtomicBool::new(false),
            u0: AtomicU64::new(u0.to_bits()),
            c0: Mutex::new(c0.clone()),
            error: Mutex::new(None),
        });
        let (tx, ready) = mpsc::channel();
        let builder = {
            let (shared, s, current) = (shared.clone(), s.clone(), run.structure.clone());
            std::thread::Builder::new()
                .name("live builds".into())
                .spawn(move || build_loop(circuit, s, shared, tx, current))
                .map_err(|e| e.to_string())?
        };
        Ok(Live {
            s,
            rate,
            looped,
            pos: 0,
            run,
            fade: None,
            shared,
            ready,
            builder: Some(builder),
            restarts: 0,
            gain,
            last_input: Vec::new(),
            values,
            up,
            lag,
            controls: c0,
        })
    }

    /// The loop's length in samples at the host rate (0: live input).
    /// The last block's input, after the gain: what the device was fed.
    pub fn last_input(&self) -> &[f64] {
        &self.last_input
    }

    /// Samples the output lags the input by (the input interpolation's lookahead,
    /// `Stream`'s docs; oversampled, the resamplers' too: [`chain_lag`]).
    pub fn lag(&self) -> usize {
        self.lag
    }

    pub fn loop_len(&self) -> usize {
        self.looped.len()
    }

    /// Where the loop is (the next input sample).
    pub fn position(&self) -> usize {
        self.pos
    }

    /// New values (all of them, as for a render): built in the background, the newest
    /// applied at a coming block.
    pub fn set(&self, values: Values) {
        *self.shared.wanted.lock().expect("wanted") = Some(values);
        self.shared.wake.notify_one();
    }

    /// A new circuit and its values: built in the background like [`Live::set`], the
    /// stream updated in place when the structure is the same, else restarted.
    pub fn set_circuit(&self, circuit: Circuit, values: Values) {
        *self.shared.circuit.lock().expect("circuit") = Some(circuit);
        self.set(values);
    }

    /// The last background build's error, if it failed (the stream plays on unchanged).
    pub fn error(&self) -> Option<String> {
        self.shared.error.lock().expect("error").clone()
    }

    /// The next `n` samples of the loop through the circuit.
    pub fn next_block(&mut self, n: usize) -> Result<(Vec<f32>, Meter), String> {
        if self.looped.is_empty() {
            return Err("no loop: feed live input through `process`".into());
        }
        let mut x = Vec::with_capacity(n);
        for _ in 0..n {
            x.push(self.looped[self.pos]);
            self.pos = (self.pos + 1) % self.looped.len();
        }
        self.shared.u0.store(
            (self.looped[self.pos] * self.gain).to_bits(),
            Ordering::Relaxed,
        );
        self.process(&x)
    }

    /// `x` (full scale 1.0, at the host rate) through the circuit: as many output
    /// samples (float32, full scale 1.0; the first block's start is padded with the
    /// stream's lag).
    pub fn process(&mut self, x: &[f64]) -> Result<(Vec<f32>, Meter), String> {
        self.process_with(x, &[])
    }

    /// [`Live::process`] with the control inputs' samples over the block (IR order,
    /// volts, at the host rate, as long as `x`; empty: each holds its last value).
    /// Linear between samples at every rate, as the engine takes them.
    pub fn process_with(
        &mut self,
        x: &[f64],
        controls: &[&[f64]],
    ) -> Result<(Vec<f32>, Meter), String> {
        let t0 = Instant::now();
        let k = self.s.oversample as usize;
        // The controls at the simulation's rate: linear from each block's previous
        // last value (k = 1: as given).
        let ctl: Vec<Vec<f64>> = if controls.len() == self.controls.len() && !controls.is_empty() {
            controls
                .iter()
                .zip(self.controls.iter_mut())
                .map(|(c, last)| {
                    let mut up = Vec::with_capacity(c.len() * k);
                    for &v in c.iter() {
                        for j in 1..=k {
                            up.push(*last + (v - *last) * j as f64 / k as f64);
                        }
                        *last = v;
                    }
                    up
                })
                .collect()
        } else {
            Vec::new()
        };
        if !ctl.is_empty() {
            *self.shared.c0.lock().expect("c0") = self.controls.clone();
        }
        let ctl_refs: Vec<&[f64]> = ctl.iter().map(Vec::as_slice).collect();
        while let Ok(r) = self.ready.try_recv() {
            match r {
                Ready::Update(ir, values) => {
                    // The builder compares with the last structure it built (live.py
                    // with the one playing), so an update is for the newest: a stream
                    // waiting to fade in has it, the one playing may not.
                    let target = match &mut self.fade {
                        Some(new) => &mut new.stream,
                        None => &mut self.run.stream,
                    };
                    target.update(&ir).map_err(|e| e.to_string())?;
                    self.values = values;
                }
                Ready::Restart(run, values) => {
                    self.fade = Some(run);
                    self.values = values;
                }
            }
        }
        let scaled: Vec<f64>;
        let x = if self.gain == 1.0 {
            x
        } else {
            scaled = x.iter().map(|u| u * self.gain).collect();
            &scaled
        };
        if let Some(&last) = x.last()
            && self.looped.is_empty()
        {
            self.shared.u0.store(last.to_bits(), Ordering::Relaxed);
        }
        self.last_input.clear();
        self.last_input.extend_from_slice(x);
        let mut xu = Vec::with_capacity(x.len() * self.s.oversample as usize);
        self.up.process(x, &mut xu);
        let volts = |fs: FullScale| xu.iter().map(|u| u * fs.input_v).collect::<Vec<f64>>();
        // A stream's `v(out)` at the host rate, over its full scale.
        let heard = |run: &mut Running, out: &[Vec<f64>]| {
            let mut y = Vec::with_capacity(x.len());
            run.down.process(&out[run.out], &mut y);
            y.iter_mut().for_each(|o| *o /= run.fs.output_v);
            y
        };
        let fs = self.run.fs;
        let out = self
            .run
            .stream
            .process_with(&volts(fs), &ctl_refs)
            .map_err(|e| e.to_string())?;
        let mut y = heard(&mut self.run, &out);
        let mut cv = self.run.cv.map(|i| out[i].clone());
        if let Some(new) = self.fade.take() {
            let mut new = *new;
            let o2 = new
                .stream
                .process_with(&volts(new.fs), &ctl_refs)
                .map_err(|e| e.to_string())?;
            let y2 = heard(&mut new, &o2);
            let m = y.len().min(y2.len());
            let (a, b) = (&y[y.len() - m..], &y2[y2.len() - m..]);
            y = linspace01(m)
                .into_iter()
                .enumerate()
                .map(|(i, w)| a[i] * (1.0 - w) + b[i] * w)
                .collect();
            cv = new.cv.map(|i| o2[i].clone());
            self.run = new;
            self.restarts += 1;
        }
        // A stream's output lags its input by a few samples (the input's
        // interpolation); pad its first block to keep the block size.
        if y.len() < x.len() {
            let mut p = vec![0.0; x.len() - y.len()];
            p.extend_from_slice(&y);
            y = p;
        }
        let rms = |a: &[f64]| (a.iter().map(|t| t * t).sum::<f64>() / a.len().max(1) as f64).sqrt();
        let (rms_in, rms_out) = (rms(x) + 1e-12, rms(&y) + 1e-12);
        // The circuit's gain, V/V or Pa/V (0 dB more when the scales in and out differ).
        let fs = self.run.fs;
        let meter = Meter {
            gain_db: 20.0 * (rms_out * fs.output_v / (rms_in * fs.input_v)).log10(),
            out_dbfs: 20.0 * (rms_out * 2f64.sqrt()).log10(),
            spl_db: fs
                .output_pascals
                .then(|| 20.0 * (rms_out * fs.output_v / 20e-6).log10()),
            cv_v: cv
                .filter(|c| !c.is_empty())
                .map(|c| c.iter().sum::<f64>() / c.len() as f64),
            load: t0.elapsed().as_secs_f64() / (x.len().max(1) as f64 / self.rate as f64),
        };
        Ok((y.iter().map(|&t| t as f32).collect(), meter))
    }
}

impl Drop for Live {
    fn drop(&mut self) {
        self.shared.closed.store(true, Ordering::Relaxed);
        self.shared.wake.notify_one();
        if let Some(h) = self.builder.take() {
            let _ = h.join();
        }
    }
}

/// The builder thread: the newest wanted values into an update or a settled new stream.
fn build_loop(
    mut circuit: Circuit,
    s: Settings,
    shared: Arc<Shared>,
    tx: Sender<Ready>,
    mut current: Structure,
) {
    let mut current_fs = circuit.full_scale(&s);
    loop {
        let wanted = {
            let mut w = shared.wanted.lock().expect("wanted");
            if w.is_none() && !shared.closed.load(Ordering::Relaxed) {
                w = shared
                    .wake
                    .wait_timeout(w, Duration::from_millis(200))
                    .expect("wanted")
                    .0;
            }
            w.take()
        };
        if shared.closed.load(Ordering::Relaxed) {
            return;
        }
        let Some(values) = wanted else { continue };
        if let Some(c) = shared.circuit.lock().expect("circuit").take() {
            circuit = c;
        }
        let result = circuit.build(&values).and_then(|ir| {
            let st = structure(&ir);
            let fs = circuit.full_scale(&s);
            if st == current && fs == current_fs {
                Ok(Ready::Update(Box::new(ir), values))
            } else {
                let u0 = f64::from_bits(shared.u0.load(Ordering::Relaxed));
                let c0 = shared.c0.lock().expect("c0").clone();
                let run = Running::new(&ir, u0, &c0, &s, fs)?;
                current = st;
                current_fs = fs;
                Ok(Ready::Restart(Box::new(run), values))
            }
        });
        match result {
            Ok(r) => {
                *shared.error.lock().expect("error") = None;
                if tx.send(r).is_err() {
                    return;
                }
            }
            Err(e) => *shared.error.lock().expect("error") = Some(e),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::chain_lag;

    #[test]
    fn lag_at_1x_is_the_interpolation_lookahead() {
        for l in 1..4 {
            assert_eq!(chain_lag(1, l, 48_000), l);
            assert_eq!(chain_lag(1, l, 0), l);
        }
        // 2x: the upsampler's and decimator's filters (10 samples each side at the
        // host rate) on top.
        let lag = chain_lag(2, 1, 48_000);
        assert!((15..=30).contains(&lag), "{lag}");
    }
}
