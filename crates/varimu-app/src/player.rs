//! Real-time output: a [`Live`] session on a worker thread feeds a lock-free ring that
//! a cpal output stream's callback only copies out of (a callback it can't fill is a
//! dropout, counted).
//!
//! Two sources:
//!
//! - **a file's loop**: the worker keeps the ring `buffer_s` ahead of the output; a
//!   knob change reaches the ear after what the ring holds plus a build (a few ms) and
//!   the device's buffer;
//! - **an input device** (live input, monitored through the circuit): a cpal input
//!   stream fills a second ring with one channel; the worker brings it to the host rate
//!   ([`StreamResampler`]), runs it through the circuit block by block as it arrives and
//!   the output starts once `buffer_s` is queued. Input to output takes the input
//!   device's latency, a block, the compute, the queue and the output device's latency
//!   ([`Status::latency_s`], from cpal's timestamps). If the queue grows past the buffer
//!   by more than two blocks (the devices' clocks drifting apart, or a stall
//!   catching up), a block of input is skipped, counted. A take can be recorded while
//!   monitoring ([`Player::record`]): the input as it came in, at the device's rate.
//!
//! The output runs at the session's host rate (draft-1x: 48 kHz). On Windows, cpal
//! opens WASAPI outputs with automatic rate conversion, so a device mixing at another
//! rate still plays it; inputs open at their own (mix) rate.
//!
//! Every source runs the session's transport (`crate::transport`, RECORDING_PLAN.md T1):
//! the worker's [`Clock`] advances with each block it computes and mixes the click into
//! the output after the monitor, so the click never reaches the device or a take.
//!
//! The output is stereo (RECORDING_PLAN.md T2-T3): the device (mono, through the monitor
//! and the armed track's strip), the session's tracks while the transport runs
//! ([`Player::set_mix`], `crate::session::Mix`) and the click. While a take is armed
//! ([`Player::arm_take`]) the worker's `session::Recorder` keeps the device's output from
//! the start bar on, before the monitor.

use std::sync::atomic::{AtomicBool, AtomicU8, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{FromSample, Sample, SizedSample};

use crate::live::{Circuit, Live, Meter, Values};
use crate::midi::{Keys, TestOsc, Wave};
use crate::monitor::Monitor;
use crate::panel::{Feed, RangeMode};
use crate::resample::StreamResampler;
use crate::session::{Frame, Mix, Recorded, Recorder};
use crate::settings::Settings;
use crate::transport::{Clock, Grid, Phase, TransportSettings};

/// Samples per block the worker computes (10 ms at 48 kHz, as the web player).
pub const BLOCK: usize = 480;
/// Audio kept ahead of playback for a file's loop (s): absorbs the compute's jitter,
/// and is most of the time a knob takes to be heard. The default; a device can keep
/// more (`panel::Device::ahead_s`: the 670, for its bursts on HF-rich input).
pub const AHEAD_S: f64 = 0.1;
/// The output queue live input starts with (s): absorbs the compute's jitter.
pub const INPUT_BUFFER_S: f64 = 0.03;

/// Raise this process to the high priority class (Windows; elsewhere nothing), so other
/// programs' threads don't stall the player's: the draft 670 runs near real time and
/// its supply partition steps in lockstep on a second thread, so a stall on either
/// costs a block. Measured 2026-10-27 with ~30% of the CPU busy elsewhere: 152 dropouts
/// in 30 s at normal priority, 12 at high. Returns whether it was raised.
pub fn raise_priority() -> bool {
    #[cfg(windows)]
    {
        use windows_sys::Win32::System::Threading::{
            GetCurrentProcess, HIGH_PRIORITY_CLASS, SetPriorityClass,
        };
        // SAFETY: the pseudo handle of this process and a valid priority class.
        unsafe { SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS) != 0 }
    }
    #[cfg(not(windows))]
    false
}

/// Where the session's input comes from.
#[derive(Debug, Clone)]
pub enum Source {
    /// A clip at the project's rate, looped.
    Loop(Vec<f64>),
    /// An input device (by name; None: the default) and one of its channels.
    Input {
        device: Option<String>,
        channel: usize,
    },
    /// A MIDI keyboard's keys, and what they feed into the circuit's control inputs (in
    /// its order: `panel::key_feeds`). Without a pitch feed they play the test oscillator
    /// (`midi::TestOsc`) into the audio input, which keeps sounding the last key when a
    /// gate keys the circuit's own envelope. With one, the circuit is the oscillator: the
    /// last key's pitch goes on its control and the audio input stays silent.
    Keys(Arc<Keys>, Wave, Vec<Feed>),
}

/// An input device and its default (shared-mode mix) format.
#[derive(Debug, Clone, PartialEq)]
pub struct InputDevice {
    pub name: String,
    pub channels: u16,
    pub rate: u32,
}

fn device_name(d: &cpal::Device) -> String {
    d.description()
        .map_or_else(|_| "?".to_string(), |x| x.name().to_string())
}

/// The input devices, default first. Default formats only: cpal 0.18 overflows (a panic
/// in debug builds) listing every format of interfaces with many channels.
pub fn input_devices() -> Vec<InputDevice> {
    let host = cpal::default_host();
    let default = host.default_input_device().map(|d| device_name(&d));
    let mut v: Vec<InputDevice> = host
        .input_devices()
        .into_iter()
        .flatten()
        .filter_map(|d| {
            let c = d.default_input_config().ok()?;
            Some(InputDevice {
                name: device_name(&d),
                channels: c.channels(),
                rate: c.sample_rate(),
            })
        })
        .collect();
    v.sort_by_key(|d| Some(&d.name) != default.as_ref());
    v
}

/// A recorded take: one input channel at the device's rate, full scale 1.0.
#[derive(Debug, Clone)]
pub struct Take {
    pub samples: Vec<f64>,
    pub rate: u32,
}

/// What the player is doing.
#[derive(Debug, Clone, PartialEq)]
pub enum State {
    /// Building the circuit and settling it (about a second).
    Starting,
    Playing,
    /// Stopped by an error (the message).
    Failed(String),
}

/// The player's state for the window, updated every block.
#[derive(Debug, Clone)]
pub struct Status {
    pub state: State,
    pub meter: Meter,
    /// The worker's load averaged over the last second (compute / audio time), and the
    /// worst block in it.
    pub load: f64,
    pub load_max: f64,
    pub restarts: usize,
    /// The last background build's error (the stream plays on unchanged).
    pub build_error: Option<String>,
    /// The loop's length and where playback is in it (s; 0 for live input).
    pub loop_s: f64,
    pub position_s: f64,
    /// The output device and the stream's rate; the input device (live input).
    pub device: String,
    pub input: Option<String>,
    pub rate: u32,
    /// Live input: input to output (s), averaged over the block's samples.
    pub latency_s: Option<f64>,
    /// The last knob change: from `Player::set` until the first block built with it
    /// starts playing (s; the block's compute counted in).
    pub knob_to_ear_s: Option<f64>,
    /// The gain compensation applied to the device's output now (dB).
    pub compensation_db: f64,
    pub transport: TransportStatus,
}

/// Where the transport is, as of the last block.
#[derive(Debug, Clone, PartialEq)]
pub struct TransportStatus {
    pub running: bool,
    pub grid: Option<Grid>,
    /// The position of the next sample the worker computes, and of the sample being
    /// heard now (the queue and the output device's latency behind it; cpal's estimate).
    pub computed: i64,
    pub heard: i64,
    pub phase: Option<Phase>,
    /// While running: the output sample (counted from the stream's first) that carries
    /// position 0. Exact, so a click at position `p` left the app as sample
    /// `origin + p` (`Player::output_clock` dates samples).
    pub origin: Option<i64>,
}

impl Status {
    fn new() -> Status {
        Status {
            state: State::Starting,
            meter: Meter::default(),
            load: 0.0,
            load_max: 0.0,
            restarts: 0,
            build_error: None,
            loop_s: 0.0,
            position_s: 0.0,
            device: String::new(),
            input: None,
            rate: 0,
            latency_s: None,
            knob_to_ear_s: None,
            compensation_db: 0.0,
            transport: TransportStatus {
                running: false,
                grid: None,
                computed: 0,
                heard: 0,
                phase: None,
                origin: None,
            },
        }
    }
}

/// The transport's settings and a pending play (true) or stop (false), for the worker.
#[derive(Debug, Default)]
struct TransportCtl {
    settings: Option<TransportSettings>,
    run: Option<bool>,
}

/// What the window, the worker and the audio callbacks share.
struct Shared {
    stop: AtomicBool,
    wanted: Mutex<Option<Values>>,
    /// A new circuit for the wanted values (the editor's drawing, edited).
    circuit: Mutex<Option<Circuit>>,
    /// When the newest wanted values were set.
    set_at: Mutex<Option<Instant>>,
    status: Mutex<Status>,
    /// The output starts once this many samples are queued (the buffer).
    prefill: usize,
    /// Samples the output has played, and callbacks it couldn't fill once playing.
    played: AtomicU64,
    dropouts: AtomicU64,
    /// Samples in the output ring (written by the worker).
    queued: AtomicUsize,
    /// The devices' latencies (us): callback to playback, capture to callback.
    out_latency_us: AtomicU64,
    in_latency_us: AtomicU64,
    /// Live input: input samples lost to a full ring, blocks skipped to bound latency.
    overflows: AtomicU64,
    skipped: AtomicU64,
    recording: AtomicBool,
    take: Mutex<Option<Take>>,
    /// Input gain (f64 bits), applied by the worker at every block.
    gain: AtomicU64,
    /// The device bypassed (its input played), and gain compensation on.
    bypass: AtomicBool,
    compensate: AtomicBool,
    /// The manual gain on the device's output (dB, f64 bits).
    output_db: AtomicU64,
    /// Where an oscillator's range switch is set (`RangeMode::index`; keys only).
    range_mode: AtomicU8,
    transport: Mutex<TransportCtl>,
    /// The last output callback: the first output sample it was asked for (counted from
    /// the stream's first) and when it ran.
    out_clock: Mutex<Option<(u64, Instant)>>,
    /// The session's tracks and the live device's gains; the take being recorded.
    mix: Mutex<Arc<Mix>>,
    recorder: Mutex<Recorder>,
}

/// A session playing out of the default output.
pub struct Player {
    shared: Arc<Shared>,
    worker: Option<JoinHandle<()>>,
    _output: cpal::Stream,
    _input: Option<cpal::Stream>,
    pub rate: u32,
}

impl Player {
    /// Start `source` through `circuit` with `values` at input `gain` (linear),
    /// `buffer_s` queued (a loop's lead, or live input's starting queue). Returns at
    /// once: the circuit settles on the worker (`State::Starting`).
    pub fn start(
        source: Source,
        values: Values,
        circuit: Circuit,
        s: Settings,
        gain: f64,
        buffer_s: f64,
    ) -> Result<Player, String> {
        Player::start_on(None, source, values, circuit, s, gain, buffer_s)
    }

    /// [`Player::start`] on the output device named `output` (None: the default).
    pub fn start_on(
        output: Option<&str>,
        source: Source,
        values: Values,
        circuit: Circuit,
        s: Settings,
        gain: f64,
        buffer_s: f64,
    ) -> Result<Player, String> {
        let rate = s.host();
        let buffer = ((buffer_s * rate as f64) as usize).max(BLOCK);
        let shared = Arc::new(Shared {
            stop: AtomicBool::new(false),
            wanted: Mutex::new(None),
            circuit: Mutex::new(None),
            set_at: Mutex::new(None),
            status: Mutex::new(Status::new()),
            // Both sources start once the buffer is queued: a loop's first blocks run
            // slow (warming up) and dropped out at the start when it started at one.
            prefill: buffer,
            played: AtomicU64::new(0),
            dropouts: AtomicU64::new(0),
            queued: AtomicUsize::new(0),
            out_latency_us: AtomicU64::new(0),
            in_latency_us: AtomicU64::new(0),
            overflows: AtomicU64::new(0),
            skipped: AtomicU64::new(0),
            recording: AtomicBool::new(false),
            take: Mutex::new(None),
            gain: AtomicU64::new(gain.to_bits()),
            bypass: AtomicBool::new(false),
            compensate: AtomicBool::new(true),
            output_db: AtomicU64::new(0f64.to_bits()),
            range_mode: AtomicU8::new(RangeMode::Auto.index()),
            transport: Mutex::new(TransportCtl::default()),
            out_clock: Mutex::new(None),
            mix: Mutex::new(Arc::new(Mix::default())),
            recorder: Mutex::new(Recorder::new(rate)),
        });
        // Room for the buffer, the drift allowance and a block in flight.
        let (producer, consumer) = rtrb::RingBuffer::<Frame>::new(buffer + 4 * BLOCK);
        let (output, device) = open_output(output, rate, consumer, shared.clone())?;
        let (input, worker_source) = match source {
            Source::Loop(x) => (None, WorkerSource::Loop(x)),
            Source::Input { device, channel } => {
                let (stream, ring, info) = open_input(device.as_deref(), channel, shared.clone())?;
                shared.status.lock().expect("status").input = Some(format!(
                    "{}, ch {} of {}, {} Hz",
                    info.name,
                    channel + 1,
                    info.channels,
                    info.rate
                ));
                (Some(stream), WorkerSource::Input(ring, info.rate))
            }
            Source::Keys(keys, wave, feeds) => {
                let gate = feeds.iter().any(|f| matches!(f, Feed::Gate(..)));
                let pitch = feeds.iter().any(|f| matches!(f, Feed::Pitch(..)));
                shared.status.lock().expect("status").input = Some(
                    match (pitch, gate) {
                        (true, true) => "MIDI keyboard: pitch and gate into the circuit",
                        (true, false) => "MIDI keyboard: pitch into the circuit's oscillator",
                        (false, true) => {
                            "MIDI keyboard: test oscillator, the gate into the circuit"
                        }
                        (false, false) => "MIDI keyboard: test oscillator",
                    }
                    .into(),
                );
                (None, WorkerSource::Keys(keys, wave, feeds))
            }
        };
        {
            let mut st = shared.status.lock().expect("status");
            st.device = device;
            st.rate = rate;
        }
        let worker = {
            let shared = shared.clone();
            std::thread::Builder::new()
                .name("player".into())
                .spawn(move || {
                    let fail =
                        |e: String| shared.status.lock().expect("status").state = State::Failed(e);
                    if let Err(e) =
                        work(worker_source, values, circuit, s, buffer, producer, &shared)
                    {
                        fail(e);
                    }
                })
                .map_err(|e| e.to_string())?
        };
        Ok(Player {
            shared,
            worker: Some(worker),
            _output: output,
            _input: input,
            rate,
        })
    }

    /// New values for every knob; the newest wins.
    pub fn set(&self, values: Values) {
        *self.shared.wanted.lock().expect("wanted") = Some(values);
        *self.shared.set_at.lock().expect("set_at") = Some(Instant::now());
    }

    /// Where the oscillator's range switch is set (a keyboard playing a device with one:
    /// LOW, HIGH, or AUTO, the keys choosing). Its circuit position follows from the
    /// keys, so it isn't among the values.
    pub fn set_range_mode(&self, mode: RangeMode) {
        self.shared
            .range_mode
            .store(mode.index(), Ordering::Relaxed);
    }

    /// A new circuit with its values (the editor's drawing, edited): the same structure
    /// updates the stream in place, another one restarts it with a crossfade.
    pub fn set_circuit(&self, circuit: Circuit, values: Values) {
        *self.shared.circuit.lock().expect("circuit") = Some(circuit);
        self.set(values);
    }

    pub fn status(&self) -> Status {
        self.shared.status.lock().expect("status").clone()
    }

    /// Output callbacks that couldn't be filled since playing started.
    pub fn dropouts(&self) -> u64 {
        self.shared.dropouts.load(Ordering::Relaxed)
    }

    /// Live input: input samples lost to a full ring, and blocks skipped to keep the
    /// latency bounded.
    pub fn input_losses(&self) -> (u64, u64) {
        (
            self.shared.overflows.load(Ordering::Relaxed),
            self.shared.skipped.load(Ordering::Relaxed),
        )
    }

    /// Audio queued ahead of the output (s).
    pub fn queued_s(&self) -> f64 {
        self.shared.queued.load(Ordering::Relaxed) as f64 / self.rate as f64
    }

    /// Seconds played since playing started.
    pub fn played_s(&self) -> f64 {
        self.shared.played.load(Ordering::Relaxed) as f64 / self.rate as f64
    }

    /// The output device's latency (callback to playback, s).
    pub fn output_latency_s(&self) -> f64 {
        self.shared.out_latency_us.load(Ordering::Relaxed) as f64 * 1e-6
    }

    /// The input gain (linear; 1: as recorded), from the next block on.
    /// Bypass the device (play its input) or not; crossfades over 10 ms.
    pub fn set_bypass(&self, on: bool) {
        self.shared.bypass.store(on, Ordering::Relaxed);
    }

    /// Match the device's output to its input's loudness (monitoring only).
    pub fn set_compensation(&self, on: bool) {
        self.shared.compensate.store(on, Ordering::Relaxed);
    }

    /// A manual gain (dB) on the device's output, on top of the compensation
    /// (monitoring only).
    pub fn set_output_db(&self, db: f64) {
        self.shared.output_db.store(db.to_bits(), Ordering::Relaxed);
    }

    pub fn set_gain(&self, gain: f64) {
        self.shared.gain.store(gain.to_bits(), Ordering::Relaxed);
    }

    /// Start or stop recording live input. A stopped take is collected by [`Player::take`].
    pub fn record(&self, on: bool) {
        self.shared.recording.store(on, Ordering::Relaxed);
    }

    pub fn recording(&self) -> bool {
        self.shared.recording.load(Ordering::Relaxed)
    }

    /// The last finished take, once.
    pub fn take(&self) -> Option<Take> {
        self.shared.take.lock().expect("take").take()
    }

    /// The transport's tempo, meter, click and start (from the next block on).
    pub fn set_transport(&self, s: &TransportSettings) {
        self.shared.transport.lock().expect("transport").settings = Some(s.clone());
    }

    /// Start the transport (from its start bar, count-in first) or stop it.
    pub fn transport_run(&self, on: bool) {
        self.shared.transport.lock().expect("transport").run = Some(on);
    }

    /// The last output callback: the first output sample it was asked for and when it
    /// ran (None before the output started).
    pub fn output_clock(&self) -> Option<(u64, Instant)> {
        *self.shared.out_clock.lock().expect("out_clock")
    }

    /// What plays with the device while the transport runs (the session's tracks) and the
    /// live device's gains.
    pub fn set_mix(&self, mix: Arc<Mix>) {
        *self.shared.mix.lock().expect("mix") = mix;
    }

    /// Record a take (from the start bar, while the transport runs) or stop recording it.
    pub fn arm_take(&self, on: bool) {
        self.shared.recorder.lock().expect("recorder").armed = on;
    }

    pub fn take_armed(&self) -> bool {
        self.shared.recorder.lock().expect("recorder").armed
    }

    /// The take being recorded: its stream start, latency, length, and its samples from
    /// `from` on (for its waveform as it grows).
    pub fn take_tail(&self, from: usize) -> Option<(i64, i64, usize, Vec<f32>)> {
        self.shared.recorder.lock().expect("recorder").tail(from)
    }

    /// The last take finished (the transport stopped, or recording disarmed), once.
    pub fn finished_take(&self) -> Option<Recorded> {
        self.shared
            .recorder
            .lock()
            .expect("recorder")
            .take_finished()
    }
}

impl Drop for Player {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::Relaxed);
        if let Some(h) = self.worker.take() {
            let _ = h.join();
        }
    }
}

enum WorkerSource {
    Loop(Vec<f64>),
    Input(rtrb::Consumer<f32>, u32),
    Keys(Arc<Keys>, Wave, Vec<Feed>),
}

/// The note a pitch feed holds until the first key (A3).
const START_NOTE: u8 = 57;

/// A feed's volts with `sounding` held (a key, or none), `last_note` the last key and
/// the oscillator's range switch at LOW (`low`) or HIGH.
fn feed_volts(f: &Feed, sounding: Option<(u8, u8)>, last_note: u8, low: bool) -> f64 {
    match f {
        Feed::Gate(up, down) => {
            if sounding.is_some() {
                *down
            } else {
                *up
            }
        }
        Feed::Pitch(p) => p.volts_in(TestOsc::note_hz(last_note), low),
    }
}

/// Write `y` into the ring (all of it; the callers leave room).
fn push<T: Copy>(ring: &mut rtrb::Producer<T>, y: &[T]) {
    if let Ok(mut chunk) = ring.write_chunk_uninit(y.len().min(ring.slots())) {
        let (a, b) = chunk.as_mut_slices();
        for (d, s) in a.iter_mut().chain(b.iter_mut()).zip(y) {
            d.write(*s);
        }
        // SAFETY: every slot of the chunk was written above (the chunk is no longer
        // than `y`).
        unsafe { chunk.commit_all() };
    }
}

/// The last second's block loads: mean and worst.
struct Loads(Vec<f64>, usize);

impl Loads {
    fn push(&mut self, x: f64) -> (f64, f64) {
        self.0.push(x);
        if self.0.len() > self.1 {
            self.0.remove(0);
        }
        let mean = self.0.iter().sum::<f64>() / self.0.len() as f64;
        (mean, self.0.iter().copied().fold(0.0, f64::max))
    }
}

/// The worker: build the session, then feed the output ring from the source.
fn work(
    source: WorkerSource,
    values: Values,
    circuit: Circuit,
    s: Settings,
    buffer: usize,
    mut ring: rtrb::Producer<Frame>,
    shared: &Shared,
) -> Result<(), String> {
    let clip = match &source {
        WorkerSource::Loop(x) => x.as_slice(),
        WorkerSource::Input(..) | WorkerSource::Keys(..) => &[],
    };
    let gain = f64::from_bits(shared.gain.load(Ordering::Relaxed));
    // A gate starts up (no key), a pitch at START_NOTE.
    let c0: Vec<f64> = match &source {
        WorkerSource::Keys(_, _, feeds) => feeds
            .iter()
            .map(|f| feed_volts(f, None, START_NOTE, false))
            .collect(),
        _ => Vec::new(),
    };
    let mut live = Live::with_controls(clip, values, circuit, s, gain, &c0)
        .map_err(|e| format!("can't start: {e}"))?;
    let rate = live.rate;
    let capacity = ring.buffer().capacity();
    let mut monitor = Monitor::new(rate, live.lag());
    // A circuit with an oscillator of its own has a silent input: nothing to compensate
    // against (the compensation ran to +260 dB).
    let own_oscillator = matches!(&source, WorkerSource::Keys(_, wave, feeds)
        if *wave == Wave::Off || feeds.iter().any(|f| matches!(f, Feed::Pitch(..))));
    // The device's output on its way out: bypass and gain compensation.
    let mut monitored = |live: &Live, y: &[f32]| {
        monitor.bypass = shared.bypass.load(Ordering::Relaxed);
        monitor.compensate = shared.compensate.load(Ordering::Relaxed) && !own_oscillator;
        monitor.output_db = f64::from_bits(shared.output_db.load(Ordering::Relaxed));
        let out = monitor.process(live.last_input(), y);
        shared.status.lock().expect("status").compensation_db = if own_oscillator {
            0.0
        } else {
            monitor.compensation_db()
        };
        out
    };
    // The block on its way to the ring: the device's output `raw` recorded into a take
    // (armed), the monitored `y` through the armed track's strip, the session's tracks
    // and the transport's click mixed in.
    let mut clock = Clock::new(rate, TransportSettings::default());
    let mut pushed: u64 = 0;
    let mut click: Vec<f32> = Vec::with_capacity(BLOCK);
    let mut emit = |ring: &mut rtrb::Producer<Frame>, raw: &[f32], y: Vec<f32>| {
        {
            let mut t = shared.transport.lock().expect("transport");
            if let Some(s) = t.settings.take() {
                clock.configure(&s);
            }
            match t.run.take() {
                Some(true) => clock.start(),
                Some(false) => clock.stop(),
                None => {}
            }
        }
        let (at, running) = (clock.position(), clock.running());
        // How far ahead of the ear this block is: the queue ahead of it, the output
        // device, and (live input) the input device.
        let queued = (ring.buffer().capacity() - ring.slots()) as i64;
        let devices_s = (shared.out_latency_us.load(Ordering::Relaxed)
            + shared.in_latency_us.load(Ordering::Relaxed)) as f64
            * 1e-6;
        let latency = queued + (devices_s * rate as f64).round() as i64;
        {
            let mut r = shared.recorder.lock().expect("recorder");
            if running {
                r.capture(at, raw, clock.record_from(), latency);
            } else {
                r.stop();
            }
        }
        let mix = shared.mix.lock().expect("mix").clone();
        click.clear();
        click.resize(y.len(), 0.0);
        clock.process(&mut click);
        let mut out: Vec<Frame> = y
            .iter()
            .map(|&v| [mix.live.0 * v, mix.live.1 * v])
            .collect();
        if running {
            mix.add(at, &mut out);
        }
        for (o, &c) in out.iter_mut().zip(&click) {
            o[0] += c;
            o[1] += c;
        }
        push(ring, &out);
        let origin = running.then(|| pushed as i64 - at);
        pushed += out.len() as u64;
        let computed = clock.position();
        let heard = if running {
            let queued = (ring.buffer().capacity() - ring.slots()) as i64;
            let out_s = shared.out_latency_us.load(Ordering::Relaxed) as f64 * 1e-6;
            computed - queued - (out_s * rate as f64).round() as i64
        } else {
            computed
        };
        shared.status.lock().expect("status").transport = TransportStatus {
            running,
            grid: Some(clock.grid()),
            computed,
            heard,
            phase: running.then(|| clock.phase_at(heard)),
            origin,
        };
    };
    let mut loads = Loads(Vec::new(), (rate as usize / BLOCK).max(1));
    {
        let mut st = shared.status.lock().expect("status");
        st.state = State::Playing;
        st.loop_s = live.loop_len() as f64 / rate as f64;
    }
    let forward_values = |live: &mut Live| {
        if let Some(v) = shared.wanted.lock().expect("wanted").take() {
            match shared.circuit.lock().expect("circuit").take() {
                Some(c) => live.set_circuit(c, v),
                None => live.set(v),
            }
        }
        live.gain = f64::from_bits(shared.gain.load(Ordering::Relaxed));
    };
    // The values playing, to see a change applied (a block built with them).
    let mut playing = live.values.clone();
    let mut heard = |live: &Live, queued_before: usize| {
        if live.values == playing {
            return;
        }
        playing = live.values.clone();
        if let Some(t) = shared.set_at.lock().expect("set_at").take() {
            let out = shared.out_latency_us.load(Ordering::Relaxed) as f64 * 1e-6;
            let ear = t.elapsed().as_secs_f64() + queued_before as f64 / rate as f64 + out;
            shared.status.lock().expect("status").knob_to_ear_s = Some(ear);
        }
    };
    let report = |live: &Live, meter: Meter, (load, load_max): (f64, f64)| {
        let mut st = shared.status.lock().expect("status");
        st.meter = meter;
        st.load = load;
        st.load_max = load_max;
        st.restarts = live.restarts;
        st.build_error = live.error();
    };
    match source {
        WorkerSource::Loop(_) => {
            let len = live.loop_len();
            while !shared.stop.load(Ordering::Relaxed) {
                forward_values(&mut live);
                let queued = capacity - ring.slots();
                shared.queued.store(queued, Ordering::Relaxed);
                if queued >= buffer || ring.slots() < BLOCK {
                    std::thread::sleep(Duration::from_millis(1));
                    continue;
                }
                let (y, meter) = live
                    .next_block(BLOCK)
                    .map_err(|e| format!("the circuit stopped: {e}"))?;
                let before = capacity - ring.slots();
                emit(&mut ring, &y, monitored(&live, &y));
                heard(&live, before);
                report(&live, meter, loads.push(meter.load));
                let pos = (live.position() + len - (capacity - ring.slots()) % len) % len;
                shared.status.lock().expect("status").position_s = pos as f64 / rate as f64;
            }
        }
        WorkerSource::Input(mut input, in_rate) => {
            // What came in while the circuit settled is late already: drop it.
            if let Ok(c) = input.read_chunk(input.slots()) {
                c.commit_all();
            }
            let mut rs = StreamResampler::new(rate as usize, in_rate as usize);
            let (mut raw, mut pending) = (Vec::new(), Vec::new());
            let mut take: Vec<f64> = Vec::new();
            while !shared.stop.load(Ordering::Relaxed) {
                forward_values(&mut live);
                let n = input.slots();
                if n == 0 {
                    std::thread::sleep(Duration::from_micros(300));
                    continue;
                }
                raw.clear();
                if let Ok(c) = input.read_chunk(n) {
                    let (a, b) = c.as_slices();
                    raw.extend(a.iter().chain(b).map(|&v| v as f64));
                    c.commit_all();
                }
                if shared.recording.load(Ordering::Relaxed) {
                    take.extend_from_slice(&raw);
                } else if !take.is_empty() {
                    let samples = std::mem::take(&mut take);
                    *shared.take.lock().expect("take") = Some(Take {
                        samples,
                        rate: in_rate,
                    });
                }
                rs.process(&raw, &mut pending);
                let mut used = 0;
                while pending.len() - used >= BLOCK {
                    let block = &pending[used..used + BLOCK];
                    used += BLOCK;
                    let queued = capacity - ring.slots();
                    if queued > buffer + 2 * BLOCK {
                        shared.skipped.fetch_add(1, Ordering::Relaxed);
                        continue;
                    }
                    let (y, meter) = live
                        .process(block)
                        .map_err(|e| format!("the circuit stopped: {e}"))?;
                    let before = capacity - ring.slots();
                    emit(&mut ring, &y, monitored(&live, &y));
                    heard(&live, before);
                    let queued = capacity - ring.slots();
                    shared.queued.store(queued, Ordering::Relaxed);
                    report(&live, meter, loads.push(meter.load));
                    // A block's samples wait half a block on average to fill it, then
                    // the compute, the queue ahead of them, and the devices.
                    let block_s = BLOCK as f64 / rate as f64;
                    let latency = shared.in_latency_us.load(Ordering::Relaxed) as f64 * 1e-6
                        + input.slots() as f64 / in_rate as f64
                        + block_s / 2.0
                        + meter.load * block_s
                        + (queued - y.len()) as f64 / rate as f64
                        + shared.out_latency_us.load(Ordering::Relaxed) as f64 * 1e-6;
                    shared.status.lock().expect("status").latency_s = Some(latency);
                }
                pending.drain(..used);
            }
        }
        WorkerSource::Keys(keys, wave, feeds) => {
            // Blocks are made as the queue drains, each from the keys held as it starts:
            // a key is heard within the queue, a block and the output's latency.
            let mut osc = TestOsc::new(rate as f64);
            osc.wave = wave;
            osc.steady = feeds.iter().any(|f| matches!(f, Feed::Gate(..)));
            let mut block = vec![0.0; BLOCK];
            let mut ctl = vec![vec![0.0; BLOCK]; feeds.len()];
            let mut last_note = START_NOTE;
            // The oscillator's range switch: the panel's values (its position is the
            // keys'), the position asked for, and (in `live.values`) the one applied.
            let range = feeds.iter().find_map(|f| match f {
                Feed::Pitch(p) => p.range,
                Feed::Gate(..) => None,
            });
            let mut panel_values = live.values.clone();
            let mut asked_low = range.is_some_and(|r| r.is_low(&live.values));
            while !shared.stop.load(Ordering::Relaxed) {
                match range {
                    // The panel's values go on with the switch where the keys put it.
                    Some(r) => {
                        if let Some(v) = shared.wanted.lock().expect("wanted").take() {
                            panel_values = v;
                            let v = r.with_position(&panel_values, asked_low);
                            match shared.circuit.lock().expect("circuit").take() {
                                Some(c) => live.set_circuit(c, v),
                                None => live.set(v),
                            }
                        }
                        live.gain = f64::from_bits(shared.gain.load(Ordering::Relaxed));
                    }
                    None => forward_values(&mut live),
                }
                let queued = capacity - ring.slots();
                shared.queued.store(queued, Ordering::Relaxed);
                if queued >= buffer || ring.slots() < BLOCK {
                    std::thread::sleep(Duration::from_micros(300));
                    continue;
                }
                let mut sounding = keys.sounding();
                let mut low = false;
                if let Some(r) = range {
                    let mode = RangeMode::from_index(shared.range_mode.load(Ordering::Relaxed));
                    let hz = sounding.map(|(n, _)| TestOsc::note_hz(n));
                    let want = r.low_for(mode, hz, asked_low);
                    if want != asked_low {
                        asked_low = want;
                        live.set(r.with_position(&panel_values, want));
                    }
                    // A key waits (gate up, the last pitch held) until the switch has
                    // moved: a block or two after a key that crosses the split.
                    low = r.is_low(&live.values);
                    if want != low {
                        sounding = None;
                    }
                }
                if let Some((note, _)) = sounding {
                    last_note = note;
                }
                if own_oscillator {
                    block.fill(0.0);
                } else {
                    osc.fill(sounding, &mut block);
                }
                for (c, f) in ctl.iter_mut().zip(&feeds) {
                    c.fill(feed_volts(f, sounding, last_note, low));
                }
                let refs: Vec<&[f64]> = ctl.iter().map(Vec::as_slice).collect();
                let (y, meter) = live
                    .process_with(&block, &refs)
                    .map_err(|e| format!("the circuit stopped: {e}"))?;
                let before = capacity - ring.slots();
                emit(&mut ring, &y, monitored(&live, &y));
                heard(&live, before);
                report(&live, meter, loads.push(meter.load));
                let block_s = BLOCK as f64 / rate as f64;
                let latency = block_s * (1.0 + meter.load)
                    + before as f64 / rate as f64
                    + shared.out_latency_us.load(Ordering::Relaxed) as f64 * 1e-6;
                shared.status.lock().expect("status").latency_s = Some(latency);
            }
        }
    }
    Ok(())
}

/// The default output device at `rate`, playing from `ring` (mono to every channel).
fn open_output(
    name: Option<&str>,
    rate: u32,
    ring: rtrb::Consumer<Frame>,
    shared: Arc<Shared>,
) -> Result<(cpal::Stream, String), String> {
    let host = cpal::default_host();
    let device = match name {
        None => host.default_output_device(),
        Some(n) => host
            .output_devices()
            .into_iter()
            .flatten()
            .find(|d| device_name(d) == n),
    }
    .ok_or_else(|| format!("no output device {}", name.unwrap_or("(default)")))?;
    let name = device_name(&device);
    let def = device
        .default_output_config()
        .map_err(|e| format!("{name}: {e}"))?;
    let config = cpal::StreamConfig {
        channels: def.channels(),
        sample_rate: rate,
        buffer_size: cpal::BufferSize::Default,
    };
    use cpal::SampleFormat as F;
    let stream = match def.sample_format() {
        F::F32 => build_output::<f32>(&device, &config, ring, shared),
        F::F64 => build_output::<f64>(&device, &config, ring, shared),
        F::I16 => build_output::<i16>(&device, &config, ring, shared),
        F::I32 => build_output::<i32>(&device, &config, ring, shared),
        F::U16 => build_output::<u16>(&device, &config, ring, shared),
        f => return Err(format!("{name}: sample format {f} isn't supported")),
    }
    .map_err(|e| format!("{name}: {e}"))?;
    stream.play().map_err(|e| format!("{name}: {e}"))?;
    Ok((stream, format!("{name}, {} ch", config.channels)))
}

fn build_output<T: SizedSample + FromSample<f32>>(
    device: &cpal::Device,
    config: &cpal::StreamConfig,
    mut ring: rtrb::Consumer<Frame>,
    shared: Arc<Shared>,
) -> Result<cpal::Stream, cpal::Error> {
    let channels = config.channels as usize;
    let mut started = false;
    // A stereo frame onto the device's channels: left and right on the first two (a
    // mono device gets their mean), silence on the rest.
    let write = move |frame: &mut [T], s: Frame| {
        if channels == 1 {
            frame[0] = T::from_sample(0.5 * (s[0] + s[1]));
        } else {
            frame[0] = T::from_sample(s[0]);
            frame[1] = T::from_sample(s[1]);
            for x in &mut frame[2..] {
                *x = T::from_sample(0.0f32);
            }
        }
    };
    device.build_output_stream(
        *config,
        move |data: &mut [T], info: &cpal::OutputCallbackInfo| {
            let ts = info.timestamp();
            shared.out_latency_us.store(
                ts.playback.duration_since(ts.callback).as_micros() as u64,
                Ordering::Relaxed,
            );
            let frames = data.len() / channels;
            if !started && ring.slots() >= shared.prefill.min(ring.buffer().capacity()) {
                started = true;
            }
            if started && let Ok(mut c) = shared.out_clock.try_lock() {
                *c = Some((shared.played.load(Ordering::Relaxed), Instant::now()));
            }
            let have = if started { ring.slots().min(frames) } else { 0 };
            let mut n = 0;
            if let Ok(chunk) = ring.read_chunk(have) {
                let (a, b) = chunk.as_slices();
                for (frame, &s) in data.chunks_mut(channels).zip(a.iter().chain(b)) {
                    write(frame, s);
                    n += 1;
                }
                chunk.commit_all();
            }
            for frame in data.chunks_mut(channels).skip(n) {
                frame.fill(T::from_sample(0.0f32));
            }
            if started {
                shared.played.fetch_add(n as u64, Ordering::Relaxed);
                if n < frames {
                    shared.dropouts.fetch_add(1, Ordering::Relaxed);
                }
            }
        },
        |e| eprintln!("audio output: {e}"),
        None,
    )
}

/// An input device (`name`, or the default) at its default format, `channel` into a
/// ring of a second of audio.
fn open_input(
    name: Option<&str>,
    channel: usize,
    shared: Arc<Shared>,
) -> Result<(cpal::Stream, rtrb::Consumer<f32>, InputDevice), String> {
    let host = cpal::default_host();
    let device = match name {
        None => host.default_input_device(),
        Some(n) => host
            .input_devices()
            .into_iter()
            .flatten()
            .find(|d| device_name(d) == n),
    }
    .ok_or_else(|| format!("no input device {}", name.unwrap_or("(default)")))?;
    let dname = device_name(&device);
    let def = device
        .default_input_config()
        .map_err(|e| format!("{dname}: {e}"))?;
    let info = InputDevice {
        name: dname.clone(),
        channels: def.channels(),
        rate: def.sample_rate(),
    };
    if channel >= info.channels as usize {
        return Err(format!("{dname} has {} channels", info.channels));
    }
    let (producer, consumer) = rtrb::RingBuffer::<f32>::new(info.rate as usize);
    let config: cpal::StreamConfig = def.config();
    use cpal::SampleFormat as F;
    let stream = match def.sample_format() {
        F::F32 => build_input::<f32>(&device, &config, channel, producer, shared),
        F::F64 => build_input::<f64>(&device, &config, channel, producer, shared),
        F::I16 => build_input::<i16>(&device, &config, channel, producer, shared),
        F::I32 => build_input::<i32>(&device, &config, channel, producer, shared),
        F::U16 => build_input::<u16>(&device, &config, channel, producer, shared),
        f => return Err(format!("{dname}: sample format {f} isn't supported")),
    }
    .map_err(|e| format!("{dname}: {e}"))?;
    stream.play().map_err(|e| format!("{dname}: {e}"))?;
    Ok((stream, consumer, info))
}

fn build_input<T: SizedSample>(
    device: &cpal::Device,
    config: &cpal::StreamConfig,
    channel: usize,
    mut ring: rtrb::Producer<f32>,
    shared: Arc<Shared>,
) -> Result<cpal::Stream, cpal::Error>
where
    f32: FromSample<T>,
{
    let channels = config.channels as usize;
    device.build_input_stream(
        *config,
        move |data: &[T], info: &cpal::InputCallbackInfo| {
            let ts = info.timestamp();
            shared.in_latency_us.store(
                ts.callback.duration_since(ts.capture).as_micros() as u64,
                Ordering::Relaxed,
            );
            let frames = data.len() / channels;
            let n = frames.min(ring.slots());
            if n < frames {
                shared
                    .overflows
                    .fetch_add((frames - n) as u64, Ordering::Relaxed);
            }
            if let Ok(mut chunk) = ring.write_chunk_uninit(n) {
                let (a, b) = chunk.as_mut_slices();
                for (d, frame) in a.iter_mut().chain(b.iter_mut()).zip(data.chunks(channels)) {
                    d.write(f32::from_sample(frame[channel]));
                }
                // SAFETY: the chunk is `n` <= frames long and every slot was written.
                unsafe { chunk.commit_all() };
            }
        },
        |e| eprintln!("audio input: {e}"),
        None,
    )
}

/// A finished render looping out of the default output (no circuit: the samples as
/// they are), to compare with the live draft.
pub struct Playback {
    _stream: cpal::Stream,
    pos: Arc<AtomicUsize>,
    len: usize,
    pub rate: u32,
}

impl Playback {
    pub fn start(samples: &[f64], rate: u32) -> Result<Playback, String> {
        if samples.is_empty() {
            return Err("nothing to play".into());
        }
        let data: Arc<Vec<f32>> = Arc::new(samples.iter().map(|&x| x as f32).collect());
        let pos = Arc::new(AtomicUsize::new(0));
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or("no audio output device")?;
        let def = device.default_output_config().map_err(|e| e.to_string())?;
        let config = cpal::StreamConfig {
            channels: def.channels(),
            sample_rate: rate,
            buffer_size: cpal::BufferSize::Default,
        };
        let channels = config.channels as usize;
        let (d, p) = (data.clone(), pos.clone());
        let stream = device
            .build_output_stream(
                config,
                move |out: &mut [f32], _: &cpal::OutputCallbackInfo| {
                    let mut i = p.load(Ordering::Relaxed);
                    for frame in out.chunks_mut(channels) {
                        frame.fill(d[i]);
                        i = (i + 1) % d.len();
                    }
                    p.store(i, Ordering::Relaxed);
                },
                |e| eprintln!("audio output: {e}"),
                None,
            )
            .map_err(|e| e.to_string())?;
        stream.play().map_err(|e| e.to_string())?;
        Ok(Playback {
            _stream: stream,
            pos,
            len: data.len(),
            rate,
        })
    }

    /// Where playback is (s).
    pub fn position_s(&self) -> f64 {
        (self.pos.load(Ordering::Relaxed) % self.len) as f64 / self.rate as f64
    }
}
