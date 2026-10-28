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

use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{FromSample, Sample, SizedSample};

use crate::live::{Circuit, Live, Meter, Values};
use crate::monitor::Monitor;
use crate::resample::StreamResampler;
use crate::settings::Settings;

/// Samples per block the worker computes (10 ms at 48 kHz, as the web player).
pub const BLOCK: usize = 480;
/// Audio kept ahead of playback for a file's loop (s): absorbs the compute's jitter,
/// and is most of the time a knob takes to be heard. 0.1 s: on an idle desktop the
/// draft 670's worst second stayed under 100% load (2026-10-28).
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
        }
    }
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
        });
        // Room for the buffer, the drift allowance and a block in flight.
        let (producer, consumer) = rtrb::RingBuffer::<f32>::new(buffer + 4 * BLOCK);
        let (output, device) = open_output(rate, consumer, shared.clone())?;
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
}

/// Write `y` into the ring (all of it; the callers leave room).
fn push(ring: &mut rtrb::Producer<f32>, y: &[f32]) {
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
    mut ring: rtrb::Producer<f32>,
    shared: &Shared,
) -> Result<(), String> {
    let clip = match &source {
        WorkerSource::Loop(x) => x.as_slice(),
        WorkerSource::Input(..) => &[],
    };
    let gain = f64::from_bits(shared.gain.load(Ordering::Relaxed));
    let mut live =
        Live::with_gain(clip, values, circuit, s, gain).map_err(|e| format!("can't start: {e}"))?;
    let rate = live.rate;
    let capacity = ring.buffer().capacity();
    let mut monitor = Monitor::new(rate, live.lag());
    // The device's output on its way out: bypass and gain compensation.
    let mut monitored = |live: &Live, y: &[f32]| {
        monitor.bypass = shared.bypass.load(Ordering::Relaxed);
        monitor.compensate = shared.compensate.load(Ordering::Relaxed);
        let out = monitor.process(live.last_input(), y);
        shared.status.lock().expect("status").compensation_db = monitor.compensation_db();
        out
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
                push(&mut ring, &monitored(&live, &y));
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
                    push(&mut ring, &monitored(&live, &y));
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
    }
    Ok(())
}

/// The default output device at `rate`, playing from `ring` (mono to every channel).
fn open_output(
    rate: u32,
    ring: rtrb::Consumer<f32>,
    shared: Arc<Shared>,
) -> Result<(cpal::Stream, String), String> {
    let host = cpal::default_host();
    let device = host
        .default_output_device()
        .ok_or("no audio output device")?;
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
    mut ring: rtrb::Consumer<f32>,
    shared: Arc<Shared>,
) -> Result<cpal::Stream, cpal::Error> {
    let channels = config.channels as usize;
    let mut started = false;
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
            let have = if started { ring.slots().min(frames) } else { 0 };
            let mut n = 0;
            if let Ok(chunk) = ring.read_chunk(have) {
                let (a, b) = chunk.as_slices();
                for (frame, &s) in data.chunks_mut(channels).zip(a.iter().chain(b)) {
                    frame.fill(T::from_sample(s));
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
