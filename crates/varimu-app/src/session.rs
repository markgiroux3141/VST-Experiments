//! Recording sessions (docs/RECORDING_PLAN.md, T2-T3): tracks of takes on the transport's
//! timeline, the stereo mix the player's worker plays, and the recorder it fills.
//!
//! **The timeline** is the transport's: samples at the session's rate from bar 1 (the
//! player's host rate; a device at another rate doesn't play the session's tracks).
//!
//! **A take** is the device's output as it was played (before the monitor's bypass and
//! gain: those are the monitor's, not the take's), placed where the player heard the
//! click: the worker computes `latency` samples ahead of the ear (the queue and the output
//! device), so what is played in time with what's heard lands `latency` later in the
//! stream. A take is placed one of two ways ([`Take::heard`]): **as heard**, where it was
//! recorded, so it plays back against the click and the other tracks exactly as the monitor
//! played it (the click and the tracks were mixed into the same blocks); or **on the
//! click**, `latency` earlier, where a player who played to the click (not to the monitor)
//! meant it. New takes land as the session says ([`Session::place_heard`], as heard by
//! default); either can be switched afterwards, since a take keeps its latency. Takes are
//! never replaced: a new one is added to the track's lane and made the active one.
//!
//! **Clips** (docs/SESSION_EDITING_PLAN.md SE5): a track's lane is a list of [`Clip`]s,
//! stretches of its takes (the pool) placed on the timeline with a gain and fades; later
//! clips lie on top of earlier ones ([`Track::pieces`]). A recording or a render lays its take
//! whole on top. A session saved before clips (version 1) opens with each track's active take
//! as one clip, playing exactly as before; its old `session.json` is kept as
//! `session.v1.json` on the first save.
//!
//! **The mix** is a console's: each track's lane times its fader and balance
//! (center unity, a side down toward silence), mute and solo, summed; the device playing
//! live goes through the armed track's fader. Arithmetic, not a device (RECORDING_PLAN.md,
//! "Physical honesty").
//!
//! **On disk** (a folder the user owns, never the repo): `session.json` (rate, transport,
//! tracks, where each take sits now) and `takes/<id>/` with `take.json` (where it was
//! recorded, the latency used, the device, the code version) and `draft.wav` (mono float32
//! at the session's rate). A take moved on the timeline keeps its `take.json`; a take
//! deleted from a track leaves the session's lists but keeps its folder.
//!
//! **Nothing recorded is lost.** A take's folder is never deleted, so any earlier state of
//! the session can be rebuilt from its JSON ([`Session::state`], [`Session::restore`]):
//! the undo history is a list of them, kept in `history.json` beside `session.json`.
//! [`Session::copy_to`] copies the whole folder (every take, the history) to a new one.
//!
//! **Event takes** (docs/MIDI_TAKES_PLAN.md N1): a take played from keys keeps its
//! performance ([`Events`]: `events.json` in its folder) beside the audio heard. An edit
//! is a new revision (`events.<n>.json`), never written over an old one, and the session's
//! state names the revision each take plays, so undo brings any edit back. Renders of a
//! revision at a quality (`crate::take_render`, kept in the take's `renders/`) are
//! attached to the take ([`TakeRender`]); what the take plays ([`Take::sound`]) is its
//! revision's production render (unless the track plays drafts), else its draft render,
//! else the audio heard (revision 0: the device as played live, or the proxy's stand-in),
//! else an older revision's render, stale until the new one lands.
//!
//! **Inserts** (docs/SESSION_FX_PLAN.md, F2): a track's devices in a chain
//! ([`crate::print::Slot`]), saved with the track. The view prints the chain on the active
//! take in the background (`prints/` in the session's folder, [`crate::print`]) and hands
//! the result to [`Track::printed`]; the mix plays a track's print in place of its take
//! (a print of the same take with older settings while a new one renders: stale, shown),
//! the dry take while it has none.
//!
//! **Sidechains** (SIDECHAIN_PLAN.md, K3): an insert with a key input (the keyed 670) can
//! listen to another track ([`crate::print::KeyRoute`], by the track's stable `id`): what
//! that track plays (its print, else its active take; before its fader, muted or not) from
//! the keyed take's position ([`Session::sidechain`]). A keyed track's chain signature
//! includes what its key track plays ([`Session::chain_signature`]), so a change there
//! prints it again, and it prints only once its key tracks' prints are current
//! ([`Session::keys_ready`]). A route that would make a loop is refused
//! ([`Session::would_cycle`]).

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{Value, json};

use crate::performance::Performance;
use crate::print::{Slot, key_control};
use crate::settings::Quality;
use crate::transport::{ClickMode, Snap, TransportSettings};

/// A clip on the clipboard (SE6): its track from the copied range's first, the clip (its
/// position from the range's start), its take (so it pastes into any track).
#[derive(Debug, Clone)]
pub struct Copied {
    pub track: usize,
    pub clip: Clip,
    pub take: Take,
}

/// A named place on the timeline (SE2): M drops one at the cursor, a click jumps there.
#[derive(Debug, Clone, PartialEq)]
pub struct Marker {
    pub position: i64,
    pub name: String,
}

/// A stereo frame (left, right).
pub type Frame = [f32; 2];

/// A console channel's gains: the fader (dB) and the balance (-1 left .. 1 right), the
/// center at unity on both sides.
pub fn balance(volume_db: f64, pan: f64) -> (f32, f32) {
    let g = 10f64.powf(volume_db / 20.0);
    let p = pan.clamp(-1.0, 1.0);
    (
        (g * (1.0 - p).min(1.0)) as f32,
        (g * (1.0 + p).min(1.0)) as f32,
    )
}

/// A stretch of a take in the mix: `len` samples of `audio` from `from`, placed at timeline
/// position `start`, through its gains (the track's fader and pan, the clip's gain), with
/// linear fades of `fade_in` / `fade_out` samples at its ends (docs/SESSION_EDITING_PLAN.md
/// SE5), on track `track` (its meter; [`NO_TRACK`]: none).
#[derive(Debug, Clone)]
pub struct MixClip {
    pub start: i64,
    pub audio: Arc<Vec<f32>>,
    /// A stereo take's right channel (`audio` is then its left; docs/STEREO_PLAN.md ST2).
    pub right: Option<Arc<Vec<f32>>>,
    pub gain: (f32, f32),
    pub from: usize,
    pub len: usize,
    pub fade_in: usize,
    pub fade_out: usize,
    pub track: usize,
}

/// A clip on no track's meter.
pub const NO_TRACK: usize = usize::MAX;

impl MixClip {
    /// The whole of `audio` from `start`, no fades, on no meter.
    pub fn whole(start: i64, audio: Arc<Vec<f32>>, gain: (f32, f32)) -> MixClip {
        MixClip {
            start,
            len: audio.len(),
            audio,
            right: None,
            gain,
            from: 0,
            fade_in: 0,
            fade_out: 0,
            track: NO_TRACK,
        }
    }

    pub fn end(&self) -> i64 {
        self.start + self.len as i64
    }

    /// Its gain envelope at its sample `i` (0..len): the fades' ramps.
    fn fade(&self, i: usize) -> f32 {
        let mut g = 1.0f32;
        if i < self.fade_in {
            g *= (i as f32 + 0.5) / self.fade_in as f32;
        }
        let left = self.len - i;
        if left <= self.fade_out {
            g *= (left as f32 - 0.5) / self.fade_out as f32;
        }
        g
    }

    /// Add it over `[at, at + out.len())`; with `meter`, its post-fader peaks and sums of
    /// squares added there.
    fn add(&self, at: i64, out: &mut [Frame], meter: Option<&mut [f32; 4]>) {
        let n = out.len() as i64;
        let (a, b) = (at.max(self.start), (at + n).min(self.end()));
        if b <= a {
            return;
        }
        let avail = self.audio.len();
        let mut m = [0.0f32; 4];
        for p in a..b {
            let i = (p - self.start) as usize;
            let Some(&v) = self
                .audio
                .get(self.from + i)
                .filter(|_| self.from + i < avail)
            else {
                continue;
            };
            // A stereo clip's right channel (a mono clip plays `v` on both sides).
            let w = match &self.right {
                Some(r) => r.get(self.from + i).copied().unwrap_or(0.0),
                None => v,
            };
            let (v, w) = if self.fade_in > 0 || self.fade_out > 0 {
                let g = self.fade(i);
                (v * g, w * g)
            } else {
                (v, w)
            };
            let (l, r) = (self.gain.0 * v, self.gain.1 * w);
            let o = &mut out[(p - at) as usize];
            o[0] += l;
            o[1] += r;
            m[0] = m[0].max(l.abs());
            m[1] = m[1].max(r.abs());
            m[2] += l * l;
            m[3] += r * r;
        }
        if let Some(t) = meter {
            t[0] = t[0].max(m[0]);
            t[1] = t[1].max(m[1]);
            t[2] += m[2];
            t[3] += m[3];
        }
    }
}

/// What the worker plays while the transport runs, the live device's gains and the track it
/// plays on, and the master fader (linear, on the sum: SE4).
#[derive(Debug, Clone)]
pub struct Mix {
    pub clips: Vec<MixClip>,
    pub live: (f32, f32),
    pub live_track: Option<usize>,
    pub master: f32,
}

impl Default for Mix {
    fn default() -> Mix {
        Mix {
            clips: Vec::new(),
            live: (1.0, 1.0),
            live_track: None,
            master: 1.0,
        }
    }
}

/// The mix's levels since they were last read (SE4): per track and for the master, the
/// peak (left, right) and the sum of squares (left, right) over `frames` frames, post-fader.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Meters {
    pub tracks: Vec<[f32; 4]>,
    pub master: [f32; 4],
    pub frames: usize,
}

impl Meters {
    /// Track `t`'s entry (grown as needed).
    pub fn track(&mut self, t: usize) -> &mut [f32; 4] {
        if self.tracks.len() <= t {
            self.tracks.resize(t + 1, [0.0; 4]);
        }
        &mut self.tracks[t]
    }

    /// Another reading folded in (later frames).
    pub fn merge(&mut self, o: &Meters) {
        for (t, m) in o.tracks.iter().enumerate() {
            let e = self.track(t);
            e[0] = e[0].max(m[0]);
            e[1] = e[1].max(m[1]);
            e[2] += m[2];
            e[3] += m[3];
        }
        self.master[0] = self.master[0].max(o.master[0]);
        self.master[1] = self.master[1].max(o.master[1]);
        self.master[2] += o.master[2];
        self.master[3] += o.master[3];
        self.frames += o.frames;
    }
}

/// A level as dBFS (peak: of a sine's amplitude 1.0), with a floor.
pub fn to_dbfs(x: f32) -> f64 {
    20.0 * (x.max(1e-7) as f64).log10()
}

impl Mix {
    /// Add the clips sounding over `[at, at + out.len())` (the master fader not applied).
    pub fn add(&self, at: i64, out: &mut [Frame]) {
        for c in &self.clips {
            c.add(at, out, None);
        }
    }

    /// [`Mix::add`] with each clip's level added to its track's meter.
    pub fn add_metered(&self, at: i64, out: &mut [Frame], meters: &mut Meters) {
        for c in &self.clips {
            if c.track == NO_TRACK {
                c.add(at, out, None);
            } else {
                c.add(at, out, Some(meters.track(c.track)));
            }
        }
    }
}

/// A session's mixdown ([`Session::mixdown`]): `len` frames from timeline position
/// `start`, each audible track's clip with its name.
#[derive(Debug, Clone)]
pub struct Mixdown {
    pub rate: u32,
    pub start: i64,
    pub len: usize,
    pub tracks: Vec<(String, Vec<MixClip>)>,
    /// The master fader (linear): the mix and every stem through it.
    pub master: f32,
}

impl Mixdown {
    fn sum<'a>(&self, clips: impl Iterator<Item = &'a MixClip>) -> Vec<Frame> {
        let mix = Mix {
            clips: clips.cloned().collect(),
            live: (0.0, 0.0),
            ..Mix::default()
        };
        let mut out = vec![[0.0f32; 2]; self.len];
        mix.add(self.start, &mut out);
        if self.master != 1.0 {
            for f in &mut out {
                f[0] *= self.master;
                f[1] *= self.master;
            }
        }
        out
    }

    /// The mix, as ▶ plays it.
    pub fn mix(&self) -> Vec<Frame> {
        self.sum(self.tracks.iter().flat_map(|(_, c)| c.iter()))
    }

    /// Track `i`'s part of the mix (its fader and pan): the stems sum to the mix.
    pub fn stem(&self, i: usize) -> Vec<Frame> {
        self.sum(self.tracks.get(i).into_iter().flat_map(|(_, c)| c.iter()))
    }

    /// The mix to `path` (stereo float32 WAV) with `record` as `<path>.json`, and with
    /// `stems` each track's part to `<path stem> stems/NN name.wav`. Returns the mix's
    /// peak (dBFS, peak: above 0 a float file keeps it, fixed-point would clip).
    pub fn write(&self, path: &Path, stems: bool, record: &Value) -> Result<f64, String> {
        let mix = self.mix();
        crate::audio::write_wav_stereo(path, &mix, self.rate)?;
        let peak = mix
            .iter()
            .flat_map(|f| f.iter())
            .fold(0.0f32, |m, &v| m.max(v.abs()));
        let peak_dbfs = 20.0 * (peak.max(1e-12) as f64).log10();
        let mut stem_files = Vec::new();
        if stems {
            let base = path
                .file_stem()
                .map_or("mix".into(), |s| s.to_string_lossy().to_string());
            let dir = path.with_file_name(format!("{base} stems"));
            for (i, (name, _)) in self.tracks.iter().enumerate() {
                let safe: String = name
                    .chars()
                    .map(|c| {
                        if c.is_alphanumeric() || " -_".contains(c) {
                            c
                        } else {
                            '_'
                        }
                    })
                    .collect();
                let f = dir.join(format!("{:02} {safe}.wav", i + 1));
                crate::audio::write_wav_stereo(&f, &self.stem(i), self.rate)?;
                stem_files.push(f.to_string_lossy().to_string());
            }
        }
        let mut record = record.clone();
        record["start_s"] = json!(self.start as f64 / self.rate as f64);
        record["seconds"] = json!(self.len as f64 / self.rate as f64);
        record["peak_dbfs"] = json!(peak_dbfs);
        record["stems"] = json!(stem_files);
        let j = path.with_extension("json");
        std::fs::write(&j, serde_json::to_string_pretty(&record).unwrap())
            .map_err(|e| format!("{}: {e}", j.display()))?;
        Ok(peak_dbfs)
    }
}

/// A finished recording from the worker: the stream position of its first sample, the
/// latency to take off, the samples, and (a device played from keys) the performance it
/// came from with the performance's sample its first sample is.
#[derive(Debug, Clone, PartialEq)]
pub struct Recorded {
    pub start: i64,
    pub latency: i64,
    pub samples: Vec<f32>,
    /// A stereo device's right channel (`samples` its left; docs/STEREO_PLAN.md ST1).
    pub right: Option<Vec<f32>>,
    pub performance: Option<(Arc<Performance>, u64)>,
}

/// The worker's recorder: while armed and the transport is past the start bar, the
/// device's output goes into a take, in chunks of a second (no reallocation of a long take
/// on the audio thread). A jump in the positions (the loop going back to its start) ends
/// the take and starts the next one: loop recording, a take per pass.
#[derive(Debug)]
pub struct Recorder {
    pub armed: bool,
    chunk: usize,
    active: Option<Active>,
    finished: std::collections::VecDeque<Recorded>,
    /// The performance being recorded (the worker adds to it): each take ending while it
    /// runs keeps a snapshot. Dropped when recording ends.
    pub performance: Option<Arc<std::sync::Mutex<Performance>>>,
}

#[derive(Debug)]
struct Active {
    start: i64,
    latency: i64,
    chunks: Vec<Vec<f32>>,
    /// A stereo device's right channel, chunked alike (empty: mono).
    right: Vec<Vec<f32>>,
    len: usize,
    /// The performance's sample of its first sample.
    stream_from: Option<u64>,
}

impl Recorder {
    pub fn new(rate: u32) -> Recorder {
        Recorder {
            armed: false,
            chunk: rate.max(1) as usize,
            active: None,
            finished: std::collections::VecDeque::new(),
            performance: None,
        }
    }

    /// The device's output `raw` for positions `at..`: kept from `record_from` on while
    /// armed (`latency`: the queue and output device now, in samples; `stream_at`: the
    /// performance's sample of `raw[0]`, while one is recorded).
    pub fn capture(
        &mut self,
        at: i64,
        raw: &[f32],
        record_from: i64,
        latency: i64,
        stream_at: Option<u64>,
    ) {
        self.capture_until(at, raw, None, record_from, i64::MAX, latency, stream_at);
    }

    /// [`Recorder::capture`] up to `record_to` (punching out: the take ends there; SE7);
    /// `right`: a stereo device's right channel beside `raw` (its left).
    #[allow(clippy::too_many_arguments)]
    pub fn capture_until(
        &mut self,
        at: i64,
        raw: &[f32],
        right: Option<&[f32]>,
        record_from: i64,
        record_to: i64,
        latency: i64,
        stream_at: Option<u64>,
    ) {
        if !self.armed {
            self.finish();
            return;
        }
        if at >= record_to {
            self.stop();
            return;
        }
        let raw = &raw[..(raw.len() as i64).min(record_to.saturating_sub(at)) as usize];
        // A take is mono or stereo throughout: a change (another device) starts the next.
        if self.active.as_ref().is_some_and(|a| {
            a.start + a.len as i64 != at || (a.len > 0 && a.right.is_empty() != right.is_none())
        }) {
            self.stop();
        }
        let end = at + raw.len() as i64;
        if end <= record_from {
            return;
        }
        let from = (record_from - at).max(0) as usize;
        let chunk = self.chunk;
        let a = self.active.get_or_insert_with(|| Active {
            start: at + from as i64,
            latency,
            chunks: Vec::new(),
            right: Vec::new(),
            len: 0,
            stream_from: stream_at.map(|s| s + from as u64),
        });
        let mut x = &raw[from..];
        let mut y = right.map(|r| &r[from.min(r.len())..raw.len().min(r.len())]);
        while !x.is_empty() {
            if a.chunks.last().is_none_or(|c| c.len() == chunk) {
                a.chunks.push(Vec::with_capacity(chunk));
                if y.is_some() {
                    a.right.push(Vec::with_capacity(chunk));
                }
            }
            let c = a.chunks.last_mut().expect("a chunk");
            let k = (chunk - c.len()).min(x.len());
            c.extend_from_slice(&x[..k]);
            if let (Some(r), Some(yy)) = (a.right.last_mut(), y.as_mut()) {
                let kk = k.min(yy.len());
                r.extend_from_slice(&yy[..kk]);
                r.resize(c.len(), 0.0);
                *yy = &yy[kk..];
            }
            a.len += k;
            x = &x[k..];
        }
    }

    /// End the take being recorded (it waits for [`Recorder::take_finished`]).
    pub fn stop(&mut self) {
        if let Some(a) = self.active.take() {
            let mut samples = Vec::with_capacity(a.len);
            for c in a.chunks {
                samples.extend_from_slice(&c);
            }
            let right = (!a.right.is_empty()).then(|| {
                let mut r = Vec::with_capacity(a.len);
                for c in a.right {
                    r.extend_from_slice(&c);
                }
                r.resize(samples.len(), 0.0);
                r
            });
            let performance = match (&self.performance, a.stream_from) {
                (Some(p), Some(from)) => {
                    Some((Arc::new(p.lock().expect("performance").clone()), from))
                }
                _ => None,
            };
            self.finished.push_back(Recorded {
                start: a.start,
                latency: a.latency,
                samples,
                right,
                performance,
            });
        }
    }

    /// End the take being recorded and the performance (recording stopped).
    pub fn finish(&mut self) {
        self.stop();
        self.performance = None;
    }

    /// The oldest finished take not collected yet.
    pub fn take_finished(&mut self) -> Option<Recorded> {
        self.finished.pop_front()
    }

    /// The take being recorded, when it records a performance: the performance's sample of
    /// its first sample and the notes played so far (the ones still held end now).
    pub fn notes(&self) -> Option<(u64, Vec<crate::performance::Note>)> {
        let from = self.active.as_ref()?.stream_from?;
        let p = self.performance.as_ref()?.lock().expect("performance");
        Some((from, p.notes()))
    }

    /// The take being recorded: its start, latency, length and its samples from `from` on.
    pub fn tail(&self, from: usize) -> Option<(i64, i64, usize, Vec<f32>)> {
        let a = self.active.as_ref()?;
        let mut out = Vec::with_capacity(a.len.saturating_sub(from));
        let mut i = 0;
        for c in &a.chunks {
            if i + c.len() > from {
                out.extend_from_slice(&c[from.saturating_sub(i)..]);
            }
            i += c.len();
        }
        Some((a.start, a.latency, a.len, out))
    }
}

/// A waveform's outline: the lowest and highest sample of each `bin` samples.
#[derive(Debug, Clone, Default)]
pub struct Overview {
    pub bin: usize,
    pub peaks: Vec<(f32, f32)>,
    /// Samples in a last, unfinished bin.
    partial: Vec<f32>,
}

impl Overview {
    pub fn new(bin: usize) -> Overview {
        Overview {
            bin: bin.max(1),
            peaks: Vec::new(),
            partial: Vec::new(),
        }
    }

    pub fn of(x: &[f32], bin: usize) -> Overview {
        let mut o = Overview::new(bin);
        o.extend(x);
        o
    }

    /// The outline of a left (or mono) channel and, stereo, its right: each bin the lowest
    /// and highest of either.
    pub fn of_lr(l: &[f32], r: Option<&[f32]>, bin: usize) -> Overview {
        let mut o = Overview::of(l, bin);
        if let Some(r) = r {
            let b = Overview::of(r, bin);
            for (p, q) in o.peaks.iter_mut().zip(&b.peaks) {
                *p = (p.0.min(q.0), p.1.max(q.1));
            }
        }
        o
    }

    /// More samples at the end.
    pub fn extend(&mut self, x: &[f32]) {
        for &v in x {
            self.partial.push(v);
            if self.partial.len() == self.bin {
                self.peaks.push(min_max(&self.partial));
                self.partial.clear();
            }
        }
    }

    /// The outline of samples `a..b` (min, max), None where there are none.
    pub fn range(&self, a: f64, b: f64) -> Option<(f32, f32)> {
        let bins = self.peaks.len() as f64;
        let (i, j) = ((a / self.bin as f64).floor(), (b / self.bin as f64).ceil());
        if j <= 0.0 || i >= bins {
            return None;
        }
        let (i, j) = (
            i.max(0.0) as usize,
            (j.min(bins) as usize).max(i.max(0.0) as usize + 1),
        );
        let s = &self.peaks[i..j.min(self.peaks.len())];
        if s.is_empty() {
            return None;
        }
        Some(s.iter().fold((f32::MAX, f32::MIN), |(lo, hi), &(a, b)| {
            (lo.min(a), hi.max(b))
        }))
    }
}

fn min_max(x: &[f32]) -> (f32, f32) {
    x.iter()
        .fold((f32::MAX, f32::MIN), |(lo, hi), &v| (lo.min(v), hi.max(v)))
}

/// The samples per overview bin (5 ms at 48 kHz).
pub const OVERVIEW_BIN: usize = 240;

/// What an event take was heard through while it was recorded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Monitor {
    /// The device itself, live: the take's audio is the device's, a draft.
    Device,
    /// The proxy (docs/MIDI_TAKES_PLAN.md N2): the take's audio is a stand-in until it is
    /// rendered.
    Proxy,
}

impl Monitor {
    pub fn name(self) -> &'static str {
        match self {
            Monitor::Device => "device",
            Monitor::Proxy => "proxy",
        }
    }

    pub fn from_name(s: &str) -> Option<Monitor> {
        match s {
            "device" => Some(Monitor::Device),
            "proxy" => Some(Monitor::Proxy),
            _ => None,
        }
    }
}

/// An event take's performance: the revision playing (0: as recorded), the performance's
/// sample of the take's first sample, what it was heard through.
#[derive(Debug, Clone)]
pub struct Events {
    pub perf: Arc<Performance>,
    pub rev: u32,
    pub from: u64,
    pub monitor: Monitor,
}

/// A render of an event take's revision at a quality, from the take's first sample.
#[derive(Debug, Clone)]
pub struct TakeRender {
    pub rev: u32,
    pub quality: Quality,
    /// The device's proxy played offline (`crate::proxy::render_performance`), a stand-in
    /// until the revision is rendered on the device (docs/SESSION_EDITING_PLAN.md decision
    /// 1); `quality` is then the performance's own.
    pub proxy: bool,
    pub audio: Arc<Vec<f32>>,
    /// A stereo device's right channel (`audio` its left).
    pub right: Option<Arc<Vec<f32>>>,
    pub overview: Arc<Overview>,
}

/// What a take plays ([`Take::sound`]).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Plays {
    /// A recorded take's audio (not an event take).
    Audio,
    /// An event take as heard live through its device (a draft).
    Heard,
    /// The proxy's stand-in, until a render lands.
    Proxy,
    /// Its revision rendered at a quality.
    Render(Quality),
    /// An older revision's render (or audio), until the new one lands.
    Stale,
}

impl Plays {
    /// A short badge for a lane.
    pub fn badge(self) -> &'static str {
        match self {
            Plays::Audio => "",
            Plays::Heard => "draft (live)",
            Plays::Proxy => "proxy",
            Plays::Render(Quality::Production) => "PROD",
            Plays::Render(_) => "draft",
            Plays::Stale => "stale",
        }
    }
}

/// One recorded take.
#[derive(Debug, Clone)]
pub struct Take {
    pub id: String,
    /// The timeline sample of its first sample.
    pub position: i64,
    /// How far ahead of the ear it was recorded (samples): the shift between its two
    /// placements.
    pub latency: i64,
    /// Placed as heard (where it was recorded), or on the click (`latency` earlier).
    pub heard: bool,
    /// The device it was played on (`panel::Device::id`, or a label).
    pub device: String,
    pub recorded_unix_s: u64,
    pub code: String,
    pub audio: Arc<Vec<f32>>,
    /// A stereo take's right channel (`audio` its left; docs/STEREO_PLAN.md ST1). Takes
    /// recorded before it are mono: a stereo device's mid.
    pub right: Option<Arc<Vec<f32>>>,
    pub overview: Arc<Overview>,
    /// A take rendered from another through a chain of inserts (Render): the take, the
    /// inserts, the quality and the code version (None: recorded).
    pub rendered_from: Option<Value>,
    /// An event take's performance (None: audio only).
    pub events: Option<Events>,
    /// Its renders found or made so far (every revision's).
    pub renders: Vec<TakeRender>,
}

impl Take {
    /// Place it as heard (`true`) or on the click: moved by its latency from wherever it
    /// sits now. Whether it moved.
    pub fn place(&mut self, heard: bool) -> bool {
        if self.heard == heard || self.latency == 0 {
            return false;
        }
        self.position += if heard { self.latency } else { -self.latency };
        self.heard = heard;
        true
    }

    /// Its length in samples: an event take's revision's, else its audio's.
    pub fn len(&self) -> usize {
        match &self.events {
            Some(e) => e.perf.end.saturating_sub(e.from) as usize,
            None => self.audio.len(),
        }
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    pub fn end(&self) -> i64 {
        self.position + self.len() as i64
    }

    /// What it plays and its outline (see the module docs); `drafts`: a draft render over a
    /// production one (to compare them). Stereo: the left channel ([`Take::sound_right`]).
    pub fn sound(&self, drafts: bool) -> (&Arc<Vec<f32>>, &Arc<Overview>, Plays) {
        match self.pick(drafts) {
            (Some(r), p) => (&r.audio, &r.overview, p),
            (None, p) => (&self.audio, &self.overview, p),
        }
    }

    /// The right channel of what it plays ([`Take::sound`]), None when that is mono.
    pub fn sound_right(&self, drafts: bool) -> Option<&Arc<Vec<f32>>> {
        match self.pick(drafts) {
            (Some(r), _) => r.right.as_ref(),
            (None, _) => self.right.as_ref(),
        }
    }

    /// Whether what it plays is stereo.
    pub fn is_stereo(&self, drafts: bool) -> bool {
        self.sound_right(drafts).is_some()
    }

    /// Which render it plays (None: its own audio) and what that is.
    fn pick(&self, drafts: bool) -> (Option<&TakeRender>, Plays) {
        let Some(e) = &self.events else {
            return (None, Plays::Audio);
        };
        let of = |rev: u32, prod: bool| {
            self.renders
                .iter()
                .rev()
                .find(|r| !r.proxy && r.rev == rev && (r.quality == Quality::Production) == prod)
        };
        let order = if drafts { [false, true] } else { [true, false] };
        for prod in order {
            if let Some(r) = of(e.rev, prod) {
                return (Some(r), Plays::Render(r.quality));
            }
        }
        if e.rev == 0 {
            let p = match e.monitor {
                Monitor::Device => Plays::Heard,
                Monitor::Proxy => Plays::Proxy,
            };
            return (None, p);
        }
        if let Some(r) = self
            .renders
            .iter()
            .rev()
            .find(|r| r.proxy && r.rev == e.rev)
        {
            return (Some(r), Plays::Proxy);
        }
        match self
            .renders
            .iter()
            .filter(|r| !r.proxy && r.rev < e.rev)
            .max_by_key(|r| r.rev)
        {
            Some(r) => (Some(r), Plays::Stale),
            None => (None, Plays::Stale),
        }
    }

    /// Whether its revision has a render at `quality`.
    pub fn has_render(&self, quality: Quality) -> bool {
        self.events.as_ref().is_some_and(|e| {
            self.renders
                .iter()
                .any(|r| !r.proxy && r.rev == e.rev && r.quality == quality)
        })
    }

    /// Whether its revision has the proxy's stand-in.
    pub fn has_proxy(&self) -> bool {
        self.events
            .as_ref()
            .is_some_and(|e| self.renders.iter().any(|r| r.proxy && r.rev == e.rev))
    }

    /// An event take edited (or recorded through the proxy) whose revision isn't rendered
    /// on the device: it plays the proxy's stand-in or an older render until it is
    /// (docs/SESSION_EDITING_PLAN.md SE1: renders are made when asked for).
    pub fn needs_render(&self, drafts: bool) -> bool {
        self.events.is_some() && matches!(self.sound(drafts).2, Plays::Proxy | Plays::Stale)
    }
}

/// A track's chain printed on its lane: what it was made from (the chain's signature,
/// [`Session::chain_signature`]), the lane it was made from ([`Track::lane_signature`]),
/// where the lane started, the audio (from there, the tail past its end) and its outline.
#[derive(Debug, Clone)]
pub struct Printed {
    pub signature: String,
    pub lane: String,
    pub start: i64,
    pub audio: Arc<Vec<f32>>,
    /// A stereo lane's print's right channel (each insert dual-mono, docs/STEREO_PLAN.md
    /// ST3; `audio` the left).
    pub right: Option<Arc<Vec<f32>>>,
    pub overview: Arc<Overview>,
    /// Each insert's print, in order (the inserts not bypassed): the input of the one
    /// after it, which an audition plays into it.
    pub stages: Vec<Arc<Vec<f32>>>,
    /// A stereo lane's: each insert's right channel's print (empty: mono).
    pub stages_right: Vec<Arc<Vec<f32>>>,
}

/// Tracks made in this process (with the clock, a new track's id).
static TRACKS_MADE: AtomicU64 = AtomicU64::new(0);

/// A new track's id: unique (the clock and a count), never reused.
fn new_track_id() -> String {
    let ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_millis());
    format!("k{ms:x}-{}", TRACKS_MADE.fetch_add(1, Ordering::Relaxed))
}

/// Clips made in this process (with the clock, a new clip's id).
static CLIPS_MADE: AtomicU64 = AtomicU64::new(0);

/// A new clip's id: unique (the clock and a count).
pub fn new_clip_id() -> String {
    let ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_millis());
    format!("c{ms:x}-{}", CLIPS_MADE.fetch_add(1, Ordering::Relaxed))
}

/// A cut's default fade (s): every edge a split or a trim makes gets it, so a cut never
/// clicks (docs/SESSION_EDITING_PLAN.md decision 5). A take's own ends get none, so a
/// session made before clips plays exactly as it did.
pub const DEFAULT_FADE_S: f64 = 0.002;

/// The default fade in samples at `rate`.
pub fn default_fade(rate: u32) -> usize {
    (DEFAULT_FADE_S * rate as f64).round() as usize
}

/// A stretch of a take placed in a lane (docs/SESSION_EDITING_PLAN.md SE5): `len` samples
/// of the take's sound from `src_start`, at timeline `position`, its gain and fades. A
/// lane's later clips lie on top of earlier ones (they win where they overlap; the earlier
/// one crossfades under the later one's fades).
#[derive(Debug, Clone, PartialEq)]
pub struct Clip {
    pub id: String,
    /// The take's id (in its track's takes).
    pub take: String,
    pub src_start: usize,
    pub len: usize,
    pub position: i64,
    pub gain_db: f64,
    pub fade_in: usize,
    pub fade_out: usize,
    pub muted: bool,
}

impl Clip {
    /// The whole of `take`, where it sits, no fades.
    pub fn whole(take: &Take) -> Clip {
        Clip {
            id: new_clip_id(),
            take: take.id.clone(),
            src_start: 0,
            len: take.len(),
            position: take.position,
            gain_db: 0.0,
            fade_in: 0,
            fade_out: 0,
            muted: false,
        }
    }

    pub fn end(&self) -> i64 {
        self.position + self.len as i64
    }

    /// The fades kept inside its length (each at most half of it).
    fn fades(&self) -> (usize, usize) {
        let half = self.len / 2;
        (self.fade_in.min(half), self.fade_out.min(half))
    }

    pub fn to_json(&self) -> Value {
        json!({
            "id": self.id,
            "take": self.take,
            "src": self.src_start,
            "len": self.len,
            "pos": self.position,
            "gain_db": self.gain_db,
            "fade_in": self.fade_in,
            "fade_out": self.fade_out,
            "muted": self.muted,
        })
    }

    pub fn from_json(v: &Value) -> Option<Clip> {
        Some(Clip {
            id: v["id"].as_str().map_or_else(new_clip_id, str::to_string),
            take: v["take"].as_str()?.to_string(),
            src_start: v["src"].as_u64().unwrap_or(0) as usize,
            len: v["len"].as_u64()? as usize,
            position: v["pos"].as_i64()?,
            gain_db: v["gain_db"].as_f64().unwrap_or(0.0),
            fade_in: v["fade_in"].as_u64().unwrap_or(0) as usize,
            fade_out: v["fade_out"].as_u64().unwrap_or(0) as usize,
            muted: v["muted"].as_bool().unwrap_or(false),
        })
    }
}

/// What a lane plays of a clip once the clips above it are taken out: a stretch of its
/// take's sound at a place, with fades (a cut edge crossfades under the clip that cut it).
#[derive(Debug, Clone, PartialEq)]
pub struct Piece {
    pub clip: usize,
    pub start: i64,
    pub from: usize,
    pub len: usize,
    pub fade_in: usize,
    pub fade_out: usize,
    pub gain: f32,
}

/// A lane's sum as cached: its signature, where it starts, its samples (left or mono, and
/// a stereo lane's right).
type LaneSum = (String, i64, Arc<Vec<f32>>, Option<Arc<Vec<f32>>>);

/// A sound placed on the timeline: where it starts, its left (or mono) channel and, stereo,
/// its right.
pub type Placed = (i64, Arc<Vec<f32>>, Option<Arc<Vec<f32>>>);

/// A track: its takes (the pool clips play from), its clips (the lane), the take last given
/// to the lane, its channel strip.
#[derive(Debug, Clone)]
pub struct Track {
    /// Its id (saved; what a key route names: it survives renaming and reordering).
    pub id: String,
    pub name: String,
    pub takes: Vec<Take>,
    /// The take last recorded, chosen or rendered into the lane (the take switcher's).
    pub active: Option<usize>,
    /// The lane: clips in the order they were laid (later on top).
    pub clips: Vec<Clip>,
    pub volume_db: f64,
    pub pan: f64,
    pub mute: bool,
    pub solo: bool,
    /// Every take shown, stacked under the lane (a view setting, saved).
    pub show_takes: bool,
    /// Its inserts, in signal order.
    pub inserts: Vec<Slot>,
    /// The chain's latest print (not saved: found again in the cache).
    pub printed: Option<Printed>,
    /// Its event takes play their draft renders over production ones (to compare them).
    pub drafts: bool,
    /// What it monitors a device played from keys through while armed: the device, or its
    /// proxy (docs/MIDI_TAKES_PLAN.md decision 1: chosen by hand, never automatically).
    pub monitor: Monitor,
    /// What a take from the keyboard records: its notes (an event take, with the audio heard
    /// as its first draft) or only its audio.
    pub midi: bool,
    /// The lane's sum, made once per arrangement (shared by clones: keyed by signature).
    lane_cache: Arc<std::sync::Mutex<Option<LaneSum>>>,
}

impl Track {
    pub fn new(name: &str) -> Track {
        Track {
            id: new_track_id(),
            name: name.to_string(),
            takes: Vec::new(),
            active: None,
            clips: Vec::new(),
            volume_db: 0.0,
            pan: 0.0,
            mute: false,
            solo: false,
            show_takes: false,
            inserts: Vec::new(),
            printed: None,
            drafts: false,
            monitor: Monitor::Device,
            midi: true,
            lane_cache: Arc::new(std::sync::Mutex::new(None)),
        }
    }

    pub fn active_take(&self) -> Option<&Take> {
        self.active.and_then(|i| self.takes.get(i))
    }

    /// The lane replaced by take `k` whole (the take switcher; a session from before clips).
    pub fn set_active(&mut self, k: usize) {
        if let Some(take) = self.takes.get(k) {
            self.clips = vec![Clip::whole(take)];
            self.active = Some(k);
        }
    }

    /// The take a clip plays.
    pub fn take_of(&self, c: &Clip) -> Option<&Take> {
        self.takes.iter().find(|k| k.id == c.take)
    }

    pub fn take_index(&self, id: &str) -> Option<usize> {
        self.takes.iter().position(|k| k.id == id)
    }

    /// The takes its unmuted clips play (each once, in the lane's order).
    pub fn lane_takes(&self) -> Vec<usize> {
        let mut v: Vec<usize> = Vec::new();
        for c in self.clips.iter().filter(|c| !c.muted) {
            if let Some(i) = self.take_index(&c.take)
                && !v.contains(&i)
            {
                v.push(i);
            }
        }
        v
    }

    pub fn gains(&self) -> (f32, f32) {
        balance(self.volume_db, self.pan)
    }

    /// What the lane plays: each unmuted clip less what later clips cover (their cores,
    /// inside their fades), each piece with its fades: a clip's own at its own edges, at an
    /// edge another clip cut the cutter's fade (a crossfade under it).
    pub fn pieces(&self) -> Vec<Piece> {
        let mut out = Vec::new();
        for (i, c) in self.clips.iter().enumerate() {
            if c.muted || c.len == 0 {
                continue;
            }
            let Some(take) = self.take_of(c) else {
                continue;
            };
            // What its take has from src_start on.
            let avail = take.sound(self.drafts).0.len().saturating_sub(c.src_start);
            let len = c.len.min(avail);
            if len == 0 {
                continue;
            }
            let (fi, fo) = c.fades();
            // Its stretches: (start, end, fade in, fade out).
            let mut parts: Vec<(i64, i64, usize, usize)> =
                vec![(c.position, c.position + len as i64, fi, fo.min(len / 2))];
            for d in self.clips[i + 1..].iter().filter(|d| !d.muted && d.len > 0) {
                if self.take_of(d).is_none() {
                    continue;
                }
                let (dfi, dfo) = d.fades();
                let (a, b) = (d.position + dfi as i64, d.end() - dfo as i64);
                if b <= a {
                    continue;
                }
                let mut next = Vec::new();
                for (s, e, f0, f1) in parts {
                    if b <= s || a >= e {
                        next.push((s, e, f0, f1));
                        continue;
                    }
                    if a > s {
                        next.push((s, a, f0, dfi));
                    }
                    if b < e {
                        next.push((b, e, dfo, f1));
                    }
                }
                parts = next;
            }
            let gain = 10f64.powf(c.gain_db / 20.0) as f32;
            for (s, e, f0, f1) in parts {
                let n = (e - s) as usize;
                out.push(Piece {
                    clip: i,
                    start: s,
                    from: c.src_start + (s - c.position) as usize,
                    len: n,
                    fade_in: f0.min(n / 2),
                    fade_out: f1.min(n / 2),
                    gain,
                });
            }
        }
        // Where two pieces of one take meet seamlessly (an untouched split), their fades
        // there come off: the take plays on as if never cut.
        for a in 0..out.len() {
            for b in 0..out.len() {
                let (p, q) = (&out[a], &out[b]);
                if a != b
                    && p.start + p.len as i64 == q.start
                    && p.from + p.len == q.from
                    && p.gain == q.gain
                    && self.clips[p.clip].take == self.clips[q.clip].take
                {
                    out[a].fade_out = 0;
                    out[b].fade_in = 0;
                }
            }
        }
        out
    }

    /// What the lane is made of: its clips and what their takes play (for prints: a
    /// change re-prints; and to find a print of the same lane).
    pub fn lane_signature(&self) -> String {
        let mut s = String::new();
        for c in self.clips.iter().filter(|c| !c.muted) {
            let Some(k) = self.take_of(c) else { continue };
            let (audio, _, plays) = k.sound(self.drafts);
            let mut what = match &k.events {
                Some(e) => format!("{}@{}:{plays:?}:{}", k.id, e.rev, audio.len()),
                None => k.id.clone(),
            };
            // A stereo sound (a mono one's signature is as it was, so its prints keep
            // their keys).
            if k.is_stereo(self.drafts) {
                what.push_str(":stereo");
            }
            s.push_str(&format!(
                "{what}[{},{},{},{},{},{}];",
                c.src_start, c.len, c.position, c.gain_db, c.fade_in, c.fade_out
            ));
        }
        s
    }

    /// The lane summed (before the strip; a stereo lane's left), from its first sound: a
    /// lone clip playing its whole take plainly is the take's own audio (so a print of it
    /// keeps its key).
    pub fn lane(&self) -> Option<(i64, Arc<Vec<f32>>)> {
        self.lane_lr().map(|(s, a, _)| (s, a))
    }

    /// Whether its lane is stereo: a clip of a stereo sound plays in it (its mono clips then
    /// play on both sides; docs/STEREO_PLAN.md ST2).
    pub fn is_stereo(&self) -> bool {
        self.clips
            .iter()
            .filter(|c| !c.muted && c.len > 0)
            .filter_map(|c| self.take_of(c))
            .any(|k| k.is_stereo(self.drafts))
    }

    /// [`Track::lane`] with a stereo lane's right channel.
    pub fn lane_lr(&self) -> Option<Placed> {
        let pieces = self.pieces();
        let start = pieces.iter().map(|p| p.start).min()?;
        let end = pieces.iter().map(|p| p.start + p.len as i64).max()?;
        if let [p] = pieces.as_slice()
            && let Some(k) = self.take_of(&self.clips[p.clip])
        {
            let audio = k.sound(self.drafts).0;
            if p.from == 0
                && p.len == audio.len()
                && p.fade_in == 0
                && p.fade_out == 0
                && p.gain == 1.0
            {
                return Some((p.start, audio.clone(), k.sound_right(self.drafts).cloned()));
            }
        }
        let sig = self.lane_signature();
        if let Ok(c) = self.lane_cache.lock()
            && let Some((s, st, a, r)) = c.as_ref()
            && *s == sig
        {
            return Some((*st, a.clone(), r.clone()));
        }
        let mut out = vec![[0.0f32; 2]; (end - start) as usize];
        for c in self.piece_clips(&pieces, (1.0, 1.0), NO_TRACK) {
            c.add(start, &mut out, None);
        }
        let stereo = self.is_stereo();
        let r: Option<Arc<Vec<f32>>> = stereo.then(|| Arc::new(out.iter().map(|f| f[1]).collect()));
        let a: Arc<Vec<f32>> = Arc::new(out.into_iter().map(|f| f[0]).collect());
        if let Ok(mut c) = self.lane_cache.lock() {
            *c = Some((sig, start, a.clone(), r.clone()));
        }
        Some((start, a, r))
    }

    /// The pieces as the mix's clips through `gain` (the strip's), on meter `track`.
    fn piece_clips(&self, pieces: &[Piece], gain: (f32, f32), track: usize) -> Vec<MixClip> {
        pieces
            .iter()
            .filter_map(|p| {
                let k = self.take_of(&self.clips[p.clip])?;
                Some(MixClip {
                    start: p.start,
                    audio: k.sound(self.drafts).0.clone(),
                    right: k.sound_right(self.drafts).cloned(),
                    gain: (gain.0 * p.gain, gain.1 * p.gain),
                    from: p.from,
                    len: p.len,
                    fade_in: p.fade_in,
                    fade_out: p.fade_out,
                    track,
                })
            })
            .collect()
    }

    /// Where its lane starts and ends (none: no clip sounds).
    pub fn lane_span(&self) -> Option<(i64, i64)> {
        let pieces = self.pieces();
        Some((
            pieces.iter().map(|p| p.start).min()?,
            pieces.iter().map(|p| p.start + p.len as i64).max()?,
        ))
    }

    /// What the chain's print of the lane is made from (the lane, the rate, every insert
    /// that isn't bypassed); None when there's nothing to print.
    pub fn chain_signature(&self, rate: u32) -> Option<String> {
        self.lane_span()?;
        let on: Vec<Value> = self
            .inserts
            .iter()
            .filter(|s| !s.bypass)
            .map(Slot::to_json)
            .collect();
        (!on.is_empty()).then(|| format!("{}|{rate}|{}", self.lane_signature(), Value::Array(on)))
    }

    /// The print that plays: of the lane as it is (current, or of older inserts: stale)
    /// while there's a chain to print.
    fn print_playing(&self, rate: u32) -> Option<&Printed> {
        self.chain_signature(rate)?;
        let lane = self.lane_signature();
        self.printed.as_ref().filter(|p| p.lane == lane)
    }

    /// The audio the mix plays and where it starts: the print of the lane (stale or not)
    /// while there's a chain to print, else the lane.
    pub fn playing(&self, rate: u32) -> Option<(i64, Arc<Vec<f32>>, bool)> {
        self.playing_lr(rate).map(|((s, a, _), p)| (s, a, p))
    }

    /// [`Track::playing`] with a stereo track's right channel.
    pub fn playing_lr(&self, rate: u32) -> Option<(Placed, bool)> {
        if let Some(p) = self.print_playing(rate) {
            return Some(((p.start, p.audio.clone(), p.right.clone()), true));
        }
        self.lane_lr().map(|l| (l, false))
    }

    /// What the mix plays of it, as track `index`: its print through its strip, else each
    /// piece of its lane (its stretch, offset, the clip's gain and fades; SE5).
    pub fn mix_clips(&self, rate: u32, index: usize) -> Vec<MixClip> {
        if let Some(p) = self.print_playing(rate) {
            return vec![MixClip {
                track: index,
                right: p.right.clone(),
                ..MixClip::whole(p.start, p.audio.clone(), self.gains())
            }];
        }
        self.piece_clips(&self.pieces(), self.gains(), index)
    }

    /// Whether the print playing is the chain as it is now.
    pub fn print_current(&self, rate: u32) -> bool {
        match self.chain_signature(rate) {
            None => true,
            Some(s) => self.printed.as_ref().is_some_and(|p| p.signature == s),
        }
    }

    /// Where its last clip ends (0: none).
    pub fn end(&self) -> i64 {
        self.clips.iter().map(Clip::end).max().unwrap_or(0)
    }

    /// Take `k` placed as heard or on the click, its clips moved with it. Whether it moved.
    pub fn place_take(&mut self, k: usize, heard: bool) -> bool {
        let Some(take) = self.takes.get_mut(k) else {
            return false;
        };
        let before = take.position;
        if !take.place(heard) {
            return false;
        }
        let (d, id) = (take.position - before, take.id.clone());
        for c in self.clips.iter_mut().filter(|c| c.take == id) {
            c.position += d;
        }
        true
    }

    /// Its clips' parts inside `[a, b)` (timeline), each cut at the range's edges (a cut
    /// edge with the default fade), muted ones too.
    pub fn clips_in(&self, a: i64, b: i64, rate: u32) -> Vec<Clip> {
        let fade = default_fade(rate);
        self.clips
            .iter()
            .filter(|c| c.position < b && c.end() > a)
            .map(|c| {
                let (s, e) = (c.position.max(a), c.end().min(b));
                let mut k = c.clone();
                k.src_start += (s - c.position) as usize;
                k.len = (e - s) as usize;
                k.position = s;
                if s > c.position {
                    k.fade_in = fade;
                }
                if e < c.end() {
                    k.fade_out = fade;
                }
                k
            })
            .collect()
    }

    /// Everything in `[a, b)` taken out of the lane (clips across its edges cut there, the
    /// parts outside kept). Whether anything changed.
    pub fn delete_range(&mut self, a: i64, b: i64, rate: u32) -> bool {
        if b <= a {
            return false;
        }
        let mut changed = false;
        for edge in [a, b] {
            let mut c = 0;
            while c < self.clips.len() {
                if self.split_clip(c, edge, rate).is_some() {
                    changed = true;
                }
                c += 1;
            }
        }
        let before = self.clips.len();
        self.clips.retain(|c| c.end() <= a || c.position >= b);
        changed || self.clips.len() != before
    }

    /// Take `from`'s bounce `to` (its render as audio, aligned with it) laid where `from`'s
    /// clips are, each with their stretch, gain and fades, and `from`'s clips muted beside
    /// them (decision 7). The whole clip a new take arrives with is replaced.
    pub fn bounce_clips(&mut self, from: &str, to: &str) {
        let copies: Vec<Clip> = self
            .clips
            .iter()
            .filter(|c| c.take == from && !c.muted)
            .map(|c| Clip {
                id: new_clip_id(),
                take: to.to_string(),
                ..c.clone()
            })
            .collect();
        if copies.is_empty() {
            return;
        }
        self.clips.retain(|c| c.take != to);
        for c in self.clips.iter_mut().filter(|c| c.take == from) {
            c.muted = true;
        }
        self.clips.extend(copies);
    }

    /// Clip `c` split at timeline position `at` (inside it): two clips, the cut edges with
    /// the default fade. The right half's index, or None.
    pub fn split_clip(&mut self, c: usize, at: i64, rate: u32) -> Option<usize> {
        let clip = self.clips.get(c)?.clone();
        if at <= clip.position || at >= clip.end() {
            return None;
        }
        let left_len = (at - clip.position) as usize;
        let fade = default_fade(rate);
        let mut right = clip.clone();
        right.id = new_clip_id();
        right.position = at;
        right.src_start += left_len;
        right.len = clip.len - left_len;
        right.fade_in = fade;
        let left = &mut self.clips[c];
        left.len = left_len;
        left.fade_out = fade;
        self.clips.insert(c + 1, right);
        Some(c + 1)
    }
}

/// A session: its folder, rate, transport and tracks.
#[derive(Debug, Clone)]
pub struct Session {
    pub dir: PathBuf,
    pub rate: u32,
    pub transport: TransportSettings,
    pub tracks: Vec<Track>,
    /// The track that records (and whose strip the live device plays through).
    pub armed: Option<usize>,
    /// New takes placed as heard (else on the click): [`Take::heard`].
    pub place_heard: bool,
    /// The markers, in timeline order.
    pub markers: Vec<Marker>,
    /// The master fader (dB, on the stereo sum: SE4).
    pub master_db: f64,
    /// Every take loaded or recorded in this session, by id, deleted ones too: a state
    /// restored by undo takes them from here before reading their folders.
    known: HashMap<String, Take>,
    /// Event takes' revisions read so far (take id, revision).
    revisions: HashMap<(String, u32), Arc<Performance>>,
}

impl Session {
    pub fn new(dir: PathBuf, rate: u32, transport: TransportSettings) -> Session {
        Session {
            dir,
            rate,
            transport,
            tracks: vec![Track::new("Track 1")],
            armed: Some(0),
            place_heard: true,
            markers: Vec::new(),
            master_db: 0.0,
            known: HashMap::new(),
            revisions: HashMap::new(),
        }
    }

    /// The mix: each audible track's active take (solo wins over mute), the live device
    /// through the armed track's strip.
    pub fn mix(&self) -> Mix {
        let any_solo = self.tracks.iter().any(|t| t.solo);
        let audible = |t: &Track| if any_solo { t.solo } else { !t.mute };
        let clips = self
            .tracks
            .iter()
            .enumerate()
            .filter(|(_, t)| audible(t))
            .flat_map(|(i, t)| t.mix_clips(self.rate, i))
            .collect();
        let live = self
            .armed
            .and_then(|i| self.tracks.get(i))
            .map_or(
                (1.0, 1.0),
                |t| if audible(t) { t.gains() } else { (0.0, 0.0) },
            );
        Mix {
            clips,
            live,
            live_track: self.armed,
            master: self.master_gain(),
        }
    }

    /// The master fader's gain (linear).
    pub fn master_gain(&self) -> f32 {
        10f64.powf(self.master_db / 20.0) as f32
    }

    /// The mix while track `t`'s insert is auditioned: its own audio comes from the live
    /// device (through its strip), so it leaves the tracks.
    pub fn mix_audition(&self, t: usize) -> Mix {
        let mut m = self.mix();
        let any_solo = self.tracks.iter().any(|x| x.solo);
        let Some(track) = self.tracks.get(t) else {
            return m;
        };
        let audible = if any_solo { track.solo } else { !track.mute };
        m.clips.retain(|c| c.track != t);
        m.live = if audible { track.gains() } else { (0.0, 0.0) };
        m.live_track = Some(t);
        m
    }

    /// Why the session can't be exported yet, a line per track (empty: it can): a print
    /// behind its chain, an event take playing the proxy or an older revision's render;
    /// `fin` (a final): every insert at production and every event take on its production
    /// render (not playing drafts). Only audible tracks count.
    pub fn export_problems(&self, fin: bool) -> Vec<String> {
        let any_solo = self.tracks.iter().any(|t| t.solo);
        let mut out = Vec::new();
        for (i, t) in self.tracks.iter().enumerate() {
            if (any_solo && !t.solo) || (!any_solo && t.mute) {
                continue;
            }
            if t.lane_span().is_none() {
                continue;
            }
            let plays: Vec<(&Take, Plays)> = t
                .lane_takes()
                .into_iter()
                .map(|k| (&t.takes[k], t.takes[k].sound(t.drafts).2))
                .collect();
            let why = if !self.print_current(i) {
                Some("its inserts aren't printed as they are now".to_string())
            } else if plays.iter().any(|p| p.1 == Plays::Proxy) {
                Some("it plays the proxy: its take isn't rendered on the device".into())
            } else if plays.iter().any(|p| p.1 == Plays::Stale) {
                Some("its latest edit isn't rendered".into())
            } else if fin
                && plays
                    .iter()
                    .any(|(k, p)| k.events.is_some() && *p != Plays::Render(Quality::Production))
            {
                Some("its take has no production render playing".into())
            } else if fin
                && let Some(s) = t
                    .inserts
                    .iter()
                    .find(|s| !s.bypass && s.quality != Quality::Production)
            {
                Some(format!("its insert {} isn't at production", s.device))
            } else {
                None
            };
            if let Some(w) = why {
                out.push(format!("{}: {w}", t.name));
            }
        }
        out
    }

    /// The mixdown: what ▶ plays (each audible track's sound through its fader and pan;
    /// no click, no live device), from bar 1 (or the earliest take, if one starts before
    /// it) to the end of the longest sound.
    pub fn mixdown(&self) -> Mixdown {
        let any_solo = self.tracks.iter().any(|t| t.solo);
        let tracks: Vec<(String, Vec<MixClip>)> = self
            .tracks
            .iter()
            .enumerate()
            .filter(|(_, t)| if any_solo { t.solo } else { !t.mute })
            .map(|(i, t)| (t.name.clone(), t.mix_clips(self.rate, i)))
            .filter(|(_, c)| !c.is_empty())
            .collect();
        let clips = || tracks.iter().flat_map(|(_, c)| c.iter());
        let start = clips().map(|c| c.start).min().unwrap_or(0).min(0);
        let end = clips().map(MixClip::end).max().unwrap_or(0);
        Mixdown {
            rate: self.rate,
            start,
            len: (end - start).max(0) as usize,
            master: self.master_gain(),
            tracks,
        }
    }

    /// What an export was made from, for its JSON beside the audio: per audible track its
    /// take, what plays (the print, a render at a quality, the take) and the strip.
    pub fn export_record(&self) -> Value {
        let any_solo = self.tracks.iter().any(|t| t.solo);
        let tracks: Vec<Value> = self
            .tracks
            .iter()
            .enumerate()
            .filter(|(_, t)| if any_solo { t.solo } else { !t.mute })
            .filter_map(|(i, t)| {
                t.lane_span()?;
                let printed = t.playing(self.rate).is_some_and(|p| p.2);
                let clips: Vec<Value> = t
                    .clips
                    .iter()
                    .filter(|c| !c.muted)
                    .filter_map(|c| {
                        let k = t.take_of(c)?;
                        let mut v = c.to_json();
                        v["revision"] = json!(k.events.as_ref().map(|e| e.rev));
                        v["plays"] = json!(format!("{:?}", k.sound(t.drafts).2));
                        Some(v)
                    })
                    .collect();
                Some(json!({
                    "id": t.id,
                    "name": t.name,
                    "clips": clips,
                    "print": printed.then(|| self.chain_signature(i)),
                    "inserts": t.inserts.iter().filter(|s| !s.bypass).map(Slot::to_json).collect::<Vec<_>>(),
                    "volume_db": t.volume_db,
                    "pan": t.pan,
                }))
            })
            .collect();
        json!({
            "session": self.dir.to_string_lossy(),
            "rate": self.rate,
            "code": circuitsim::SOURCE_HASH,
            "exported_unix_s": std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |d| d.as_secs()),
            "tracks": tracks,
        })
    }

    /// The track whose id is `id`.
    pub fn track_index(&self, id: &str) -> Option<usize> {
        self.tracks.iter().position(|t| t.id == id)
    }

    /// What track `t`'s chain is printed from: its own ([`Track::chain_signature`]) and,
    /// for each keyed insert (not bypassed), what its key track plays and where the take
    /// sits against it. None when there's nothing to print.
    pub fn chain_signature(&self, t: usize) -> Option<String> {
        self.signature_of(t, &mut Vec::new())
    }

    fn signature_of(&self, t: usize, seen: &mut Vec<usize>) -> Option<String> {
        let track = self.tracks.get(t)?;
        let mut sig = track.chain_signature(self.rate)?;
        let pos = track.lane_span()?.0;
        seen.push(t);
        for s in track.inserts.iter().filter(|s| !s.bypass) {
            let (Some(_), Some(route)) = (key_control(s), &s.key) else {
                continue;
            };
            let what = match self.track_index(&route.track) {
                None => "missing".to_string(),
                Some(i) if seen.contains(&i) => "loop".to_string(),
                Some(i) => self.plays_signature(i, seen),
            };
            sig.push_str(&format!("|key {}@{pos}={what}", route.track));
        }
        seen.pop();
        Some(sig)
    }

    /// The clips in `[a, b)` on tracks `tracks` (cut at the range's edges) as clipboard
    /// items, their positions from `a` and their tracks from the first (SE6).
    pub fn copy_range(
        &self,
        a: i64,
        b: i64,
        tracks: std::ops::RangeInclusive<usize>,
    ) -> Vec<Copied> {
        let first = *tracks.start();
        let mut out = Vec::new();
        for t in tracks {
            let Some(track) = self.tracks.get(t) else {
                continue;
            };
            for mut c in track.clips_in(a, b, self.rate) {
                let Some(take) = track.take_of(&c).cloned() else {
                    continue;
                };
                c.position -= a;
                out.push(Copied {
                    track: t - first,
                    clip: c,
                    take,
                });
            }
        }
        out
    }

    /// Clipboard items laid at `at` from track `track` down (each on its track offset; past
    /// the last track, new tracks), on top of what's there; their takes added to the
    /// tracks' pools where they aren't (audio is never copied: clips share their take).
    /// Returns the new clips (track, index).
    pub fn paste(&mut self, items: &[Copied], at: i64, track: usize) -> Vec<(usize, usize)> {
        let mut out = Vec::new();
        for it in items {
            let t = track + it.track;
            while self.tracks.len() <= t {
                let n = self.tracks.len() + 1;
                self.tracks.push(Track::new(&format!("Track {n}")));
            }
            let dest = &mut self.tracks[t];
            if dest.take_index(&it.take.id).is_none() {
                dest.takes.push(it.take.clone());
            }
            let mut c = it.clip.clone();
            c.id = new_clip_id();
            c.position += at;
            dest.clips.push(c);
            out.push((t, dest.clips.len() - 1));
        }
        out
    }

    /// Time inserted at `at` (`len` samples) across every track: clips across `at` split
    /// there, clips and markers from `at` on moved later (SE6).
    pub fn insert_time(&mut self, at: i64, len: i64) {
        let rate = self.rate;
        for t in &mut self.tracks {
            let mut c = 0;
            while c < t.clips.len() {
                t.split_clip(c, at, rate);
                c += 1;
            }
            for c in t.clips.iter_mut().filter(|c| c.position >= at) {
                c.position += len;
            }
        }
        for m in self.markers.iter_mut().filter(|m| m.position >= at) {
            m.position += len;
        }
    }

    /// The time `[a, b)` deleted across every track: what's in it removed, clips and
    /// markers after it moved earlier by its length.
    pub fn delete_time(&mut self, a: i64, b: i64) {
        if b <= a {
            return;
        }
        let rate = self.rate;
        for t in &mut self.tracks {
            t.delete_range(a, b, rate);
            for c in t.clips.iter_mut().filter(|c| c.position >= b) {
                c.position -= b - a;
            }
        }
        self.markers.retain(|m| m.position < a || m.position >= b);
        for m in self.markers.iter_mut().filter(|m| m.position >= b) {
            m.position -= b - a;
        }
    }

    /// What track `i` plays, as a key hears it: its lane, where it sits, its chain.
    fn plays_signature(&self, i: usize, seen: &mut Vec<usize>) -> String {
        let t = &self.tracks[i];
        match t.lane_span() {
            None => "silence".to_string(),
            Some((start, _)) => format!(
                "{}@{start}[{}]",
                t.lane_signature(),
                self.signature_of(i, seen).unwrap_or_default()
            ),
        }
    }

    /// Whether track `t`'s print is its chain as it is now (session-wide: its keys too).
    pub fn print_current(&self, t: usize) -> bool {
        match self.chain_signature(t) {
            None => true,
            Some(s) => self.tracks[t]
                .printed
                .as_ref()
                .is_some_and(|p| p.signature == s),
        }
    }

    /// The tracks keying track `t`'s chain (its keyed inserts not bypassed), not `t`.
    pub fn key_tracks(&self, t: usize) -> Vec<usize> {
        let Some(track) = self.tracks.get(t) else {
            return Vec::new();
        };
        track
            .inserts
            .iter()
            .filter(|s| !s.bypass && key_control(s).is_some())
            .filter_map(|s| s.key.as_ref().and_then(|r| self.track_index(&r.track)))
            .filter(|&i| i != t)
            .collect()
    }

    /// Whether every track keying track `t`'s chain plays what it will (its print
    /// current): only then does `t` print, so it prints once per change of a key.
    pub fn keys_ready(&self, t: usize) -> bool {
        let Some(track) = self.tracks.get(t) else {
            return true;
        };
        track
            .inserts
            .iter()
            .filter(|s| !s.bypass && key_control(s).is_some())
            .filter_map(|s| s.key.as_ref().and_then(|r| self.track_index(&r.track)))
            .all(|i| i == t || self.print_current(i))
    }

    /// Insert `slot`'s sidechain on track `t`: its key track's playing audio from the
    /// lane's start over the lane and the slot's tail, silence where it has none; None
    /// without a route (or a device without a key input, or a route to itself).
    pub fn sidechain(&self, t: usize, slot: &Slot) -> Option<Arc<Vec<f32>>> {
        key_control(slot)?;
        let (lane_start, lane_end) = self.tracks.get(t)?.lane_span()?;
        let i = self.track_index(&slot.key.as_ref()?.track)?;
        if i == t {
            return None;
        }
        let n = (lane_end - lane_start) as usize
            + (slot.tail_s.max(0.0) * self.rate as f64).round() as usize;
        let mut out = vec![0f32; n];
        // A stereo key track keys from its mid (docs/STEREO_PLAN.md ST3).
        if let Some(((start, audio, right), _)) = self.tracks[i].playing_lr(self.rate) {
            for (j, o) in out.iter_mut().enumerate() {
                let p = lane_start + j as i64 - start;
                if p >= 0
                    && let Some(&v) = audio.get(p as usize)
                {
                    *o = match right.as_ref().and_then(|r| r.get(p as usize)) {
                        Some(&w) => 0.5 * (v + w),
                        None => v,
                    };
                }
            }
        }
        Some(Arc::new(out))
    }

    /// The sidechains of track `t`'s chain, insert by insert (those not bypassed, as
    /// prints take them: [`crate::print::print_chain`]).
    pub fn sidechains(&self, t: usize) -> Vec<Option<Arc<Vec<f32>>>> {
        self.tracks.get(t).map_or(Vec::new(), |track| {
            track
                .inserts
                .iter()
                .filter(|s| !s.bypass)
                .map(|s| self.sidechain(t, s))
                .collect()
        })
    }

    /// What insert `slot`'s sidechain on track `t` is made from (a live audition restarts
    /// when it changes): its route, its trim and what the key track plays.
    pub fn key_signature(&self, t: usize, slot: &Slot) -> String {
        let (Some(_), Some(route)) = (key_control(slot), &slot.key) else {
            return String::new();
        };
        let what = match self.track_index(&route.track) {
            Some(i) if i != t => self.plays_signature(i, &mut vec![t]),
            _ => "none".to_string(),
        };
        let pos = self.tracks.get(t).and_then(Track::lane_span).map(|s| s.0);
        format!("{}|{}|{pos:?}|{what}", route.track, route.trim_db)
    }

    /// Whether track `t` keyed from track `key` would make a loop: `key` is `t`, or is
    /// keyed (through any chain of key routes, bypassed inserts too) from `t`.
    pub fn would_cycle(&self, t: usize, key: usize) -> bool {
        let mut stack = vec![key];
        let mut seen = HashSet::new();
        while let Some(i) = stack.pop() {
            if i == t {
                return true;
            }
            if !seen.insert(i) {
                continue;
            }
            for s in self.tracks.get(i).map_or(&[][..], |x| &x.inserts) {
                if let Some(j) = s.key.as_ref().and_then(|r| self.track_index(&r.track)) {
                    stack.push(j);
                }
            }
        }
        false
    }

    /// Where the last clip ends (0: none).
    pub fn end(&self) -> i64 {
        self.tracks.iter().map(Track::end).max().unwrap_or(0)
    }

    /// A take id never used in this session: past every take a track holds, every take it
    /// has known (deleted ones too: undo brings them back) and every take folder on disk.
    fn next_id(&self) -> String {
        let num = |id: &str| id.strip_prefix('t').and_then(|s| s.parse::<u32>().ok());
        let on_disk: Vec<String> = std::fs::read_dir(self.dir.join("takes"))
            .map(|d| {
                d.flatten()
                    .map(|e| e.file_name().to_string_lossy().into_owned())
                    .collect()
            })
            .unwrap_or_default();
        let n = self
            .tracks
            .iter()
            .flat_map(|t| &t.takes)
            .map(|k| k.id.as_str())
            .chain(self.known.keys().map(String::as_str))
            .chain(on_disk.iter().map(String::as_str))
            .filter_map(num)
            .max()
            .unwrap_or(0);
        format!("t{:04}", n + 1)
    }

    /// A recording made into a take of `track` (now its active one), its files written.
    pub fn add_take(&mut self, track: usize, rec: Recorded, device: &str) -> Result<(), String> {
        self.add_take_heard(track, rec, device, Monitor::Device)
            .map(|_| ())
    }

    /// [`Session::add_take`] for a recording heard through `monitor` (an event take's
    /// audio is the device's, or the proxy's stand-in). Returns its id.
    pub fn add_take_heard(
        &mut self,
        track: usize,
        rec: Recorded,
        device: &str,
        monitor: Monitor,
    ) -> Result<String, String> {
        let id = self.next_id();
        let events = rec.performance.map(|(perf, from)| {
            // The performance up to the take's last sample.
            let mut p = (*perf).clone();
            p.end = p.end.min(from + rec.samples.len() as u64);
            Events {
                perf: Arc::new(p),
                rev: 0,
                from,
                monitor,
            }
        });
        let heard = self.place_heard || rec.latency == 0;
        let take = Take {
            id: id.clone(),
            position: if heard {
                rec.start
            } else {
                rec.start - rec.latency
            },
            latency: rec.latency,
            heard,
            device: device.to_string(),
            recorded_unix_s: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |d| d.as_secs()),
            code: circuitsim::SOURCE_HASH.to_string(),
            overview: Arc::new(Overview::of_lr(
                &rec.samples,
                rec.right.as_deref(),
                OVERVIEW_BIN,
            )),
            audio: Arc::new(rec.samples),
            right: rec.right.map(Arc::new),
            rendered_from: None,
            events,
            renders: Vec::new(),
        };
        write_take(&self.dir, &take, self.rate)?;
        if let Some(e) = &take.events {
            write_revision(&self.dir, &take.id, 0, &e.perf)?;
            self.revisions.insert((take.id.clone(), 0), e.perf.clone());
        }
        self.known.insert(take.id.clone(), take.clone());
        let t = self.tracks.get_mut(track).ok_or("no such track")?;
        t.clips.push(Clip::whole(&take));
        t.takes.push(take);
        t.active = Some(t.takes.len() - 1);
        self.save()?;
        Ok(id)
    }

    /// Take `k` of `track` edited: `perf` saved as its next revision (the old ones stay),
    /// now the one it plays. Returns the revision.
    pub fn revise(&mut self, track: usize, k: usize, perf: Performance) -> Result<u32, String> {
        let take = self
            .tracks
            .get(track)
            .and_then(|t| t.takes.get(k))
            .ok_or("no such take")?;
        let id = take.id.clone();
        let e = take.events.as_ref().ok_or("not an event take")?;
        let rev = next_revision(&self.dir, &id).max(e.rev + 1);
        let perf = Arc::new(perf);
        write_revision(&self.dir, &id, rev, &perf)?;
        self.revisions.insert((id.clone(), rev), perf.clone());
        for t in self.tracks.iter_mut().flat_map(|t| t.takes.iter_mut()) {
            if t.id == id
                && let Some(e) = &mut t.events
            {
                e.perf = perf.clone();
                e.rev = rev;
            }
        }
        if let Some(t) = self.known.get_mut(&id)
            && let Some(e) = &mut t.events
        {
            e.perf = perf.clone();
            e.rev = rev;
        }
        self.save()?;
        Ok(rev)
    }

    /// A render of take `id`'s revision `rev` at `quality` (`audio`: the whole
    /// performance's; `right`: a stereo device's right channel), attached wherever the take
    /// is (undo keeps it).
    pub fn attach_render(
        &mut self,
        id: &str,
        rev: u32,
        quality: Quality,
        audio: &[f32],
        right: Option<&[f32]>,
    ) {
        let Some(from) = self
            .known
            .get(id)
            .and_then(|k| k.events.as_ref())
            .map(|e| e.from as usize)
        else {
            return;
        };
        let a: Vec<f32> = audio.get(from..).unwrap_or(&[]).to_vec();
        let b: Option<Vec<f32>> = right.map(|r| r.get(from..).unwrap_or(&[]).to_vec());
        let r = TakeRender {
            rev,
            quality,
            proxy: false,
            overview: Arc::new(Overview::of_lr(&a, b.as_deref(), OVERVIEW_BIN)),
            audio: Arc::new(a),
            right: b.map(Arc::new),
        };
        self.attach(id, r);
    }

    /// The proxy's stand-in for take `id`'s revision `rev` (`audio`: the whole
    /// performance's), attached wherever the take is.
    pub fn attach_proxy(&mut self, id: &str, rev: u32, audio: &[f32]) {
        let Some((from, quality)) = self
            .known
            .get(id)
            .and_then(|k| k.events.as_ref())
            .map(|e| (e.from as usize, e.perf.quality))
        else {
            return;
        };
        let a: Vec<f32> = audio.get(from..).unwrap_or(&[]).to_vec();
        let r = TakeRender {
            rev,
            quality,
            proxy: true,
            overview: Arc::new(Overview::of(&a, OVERVIEW_BIN)),
            audio: Arc::new(a),
            right: None,
        };
        self.attach(id, r);
    }

    fn attach(&mut self, id: &str, r: TakeRender) {
        let takes = self
            .tracks
            .iter_mut()
            .flat_map(|t| t.takes.iter_mut())
            .chain(self.known.get_mut(id));
        for t in takes {
            if t.id == id {
                t.renders
                    .retain(|x| !(x.rev == r.rev && x.quality == r.quality && x.proxy == r.proxy));
                t.renders.push(r.clone());
            }
        }
    }

    /// A revision of take `id` (read once).
    fn revision(&mut self, id: &str, rev: u32) -> Result<Arc<Performance>, String> {
        if let Some(p) = self.revisions.get(&(id.to_string(), rev)) {
            return Ok(p.clone());
        }
        let p = Arc::new(read_revision(&self.dir, id, rev)?);
        self.revisions.insert((id.to_string(), rev), p.clone());
        Ok(p)
    }

    /// A track's chain rendered into a new take of `track` (now its active one) at
    /// `position`, its files written; `from` says what it was rendered from (the take, the
    /// inserts, the quality; or its `device` label, as an imported file's). `right`: a
    /// stereo take's right channel (`samples` its left). Returns its id.
    pub fn add_rendered_take(
        &mut self,
        track: usize,
        samples: Vec<f32>,
        right: Option<Vec<f32>>,
        position: i64,
        from: Value,
    ) -> Result<String, String> {
        let id = self.next_id();
        let take = Take {
            id: id.clone(),
            position,
            latency: 0,
            heard: true,
            device: from["device"].as_str().map_or_else(
                || format!("render of {}", from["take"].as_str().unwrap_or("?")),
                str::to_string,
            ),
            recorded_unix_s: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |d| d.as_secs()),
            code: circuitsim::SOURCE_HASH.to_string(),
            overview: Arc::new(Overview::of_lr(&samples, right.as_deref(), OVERVIEW_BIN)),
            audio: Arc::new(samples),
            right: right.map(Arc::new),
            rendered_from: Some(from),
            events: None,
            renders: Vec::new(),
        };
        write_take(&self.dir, &take, self.rate)?;
        self.known.insert(id.clone(), take.clone());
        let t = self.tracks.get_mut(track).ok_or("no such track")?;
        t.clips.push(Clip::whole(&take));
        t.takes.push(take);
        t.active = Some(t.takes.len() - 1);
        self.save()?;
        Ok(id)
    }

    /// Every take with a latency placed as heard (`true`) or on the click, its clips with
    /// it. Whether any moved.
    pub fn place_all(&mut self, heard: bool) -> bool {
        let mut moved = false;
        for t in &mut self.tracks {
            for k in 0..t.takes.len() {
                moved |= t.place_take(k, heard);
            }
        }
        moved
    }

    /// The session as `session.json` holds it: rate, transport, tracks (their takes by id,
    /// where each sits, the active one), the armed track.
    pub fn state(&self) -> Value {
        let tracks: Vec<Value> = self
            .tracks
            .iter()
            .map(|t| {
                json!({
                    "id": t.id,
                    "name": t.name,
                    "volume_db": t.volume_db,
                    "pan": t.pan,
                    "mute": t.mute,
                    "solo": t.solo,
                    "show_takes": t.show_takes,
                    "inserts": t.inserts.iter().map(Slot::to_json).collect::<Vec<_>>(),
                    "takes": t.takes.iter().map(|k| k.id.clone()).collect::<Vec<_>>(),
                    "positions": t
                        .takes
                        .iter()
                        .map(|k| (k.id.clone(), json!(k.position)))
                        .collect::<serde_json::Map<_, _>>(),
                    "placed": t
                        .takes
                        .iter()
                        .filter(|k| k.latency != 0)
                        .map(|k| (k.id.clone(), json!(if k.heard { "heard" } else { "click" })))
                        .collect::<serde_json::Map<_, _>>(),
                    "active": t.active_take().map(|k| k.id.clone()),
                    "clips": t.clips.iter().map(Clip::to_json).collect::<Vec<_>>(),
                    "revisions": t
                        .takes
                        .iter()
                        .filter_map(|k| k.events.as_ref().map(|e| (k.id.clone(), json!(e.rev))))
                        .collect::<serde_json::Map<_, _>>(),
                    "drafts": t.drafts,
                    "monitor": t.monitor.name(),
                    "record": if t.midi { "midi" } else { "audio" },
                })
            })
            .collect();
        json!({
            "version": 2,
            "rate": self.rate,
            "transport": transport_json(&self.transport),
            "tracks": tracks,
            "armed": self.armed,
            "place_new": if self.place_heard { "heard" } else { "click" },
            "master_db": self.master_db,
            "markers": self
                .markers
                .iter()
                .map(|m| json!([m.position, m.name]))
                .collect::<Vec<_>>(),
        })
    }

    /// Back to a state from [`Session::state`] (its takes from memory, else from their
    /// folders).
    pub fn restore(&mut self, v: &Value) -> Result<(), String> {
        let rate = v["rate"].as_u64().ok_or("session state: no rate")? as u32;
        let mut tracks = Vec::new();
        for (i, t) in v["tracks"]
            .as_array()
            .cloned()
            .unwrap_or_default()
            .iter()
            .enumerate()
        {
            let mut track = Track::new(t["name"].as_str().unwrap_or("Track"));
            // A session saved before tracks had ids: one by place, kept from the next save.
            track.id = t["id"]
                .as_str()
                .map_or_else(|| format!("track{}", i + 1), str::to_string);
            track.volume_db = t["volume_db"].as_f64().unwrap_or(0.0);
            track.pan = t["pan"].as_f64().unwrap_or(0.0);
            track.mute = t["mute"].as_bool().unwrap_or(false);
            track.solo = t["solo"].as_bool().unwrap_or(false);
            track.show_takes = t["show_takes"].as_bool().unwrap_or(false);
            track.drafts = t["drafts"].as_bool().unwrap_or(false);
            track.monitor = t["monitor"]
                .as_str()
                .and_then(Monitor::from_name)
                .unwrap_or(Monitor::Device);
            track.midi = t["record"].as_str() != Some("audio");
            for s in t["inserts"].as_array().cloned().unwrap_or_default() {
                track.inserts.push(Slot::from_json(&s)?);
            }
            for id in t["takes"].as_array().cloned().unwrap_or_default() {
                let id = id.as_str().ok_or("session state: a take id isn't text")?;
                let mut take = match self.known.get(id) {
                    Some(k) => k.clone(),
                    None => {
                        let k = read_take(&self.dir, id, rate)?;
                        self.known.insert(id.to_string(), k.clone());
                        k
                    }
                };
                if let Some(p) = t["positions"][id].as_i64() {
                    take.position = p;
                }
                if let Some(h) = t["placed"][id].as_str() {
                    take.heard = h == "heard";
                }
                let rev = t["revisions"][id].as_u64().unwrap_or(0) as u32;
                if take.events.as_ref().is_some_and(|e| e.rev != rev) {
                    let perf = self.revision(id, rev)?;
                    if let Some(e) = &mut take.events {
                        e.perf = perf;
                        e.rev = rev;
                    }
                }
                track.takes.push(take);
            }
            let active = t["active"].as_str();
            track.active = track
                .takes
                .iter()
                .position(|k| Some(k.id.as_str()) == active);
            // The lane: its clips; a session from before clips, its active take whole
            // (it plays as it did: SE5's migration).
            match t["clips"].as_array() {
                Some(clips) => {
                    track.clips = clips
                        .iter()
                        .filter_map(Clip::from_json)
                        .filter(|c| track.take_of(c).is_some())
                        .collect();
                }
                None => {
                    if let Some(k) = track.active {
                        track.set_active(k);
                    }
                }
            }
            tracks.push(track);
        }
        self.armed = v["armed"]
            .as_u64()
            .map(|i| i as usize)
            .filter(|&i| i < tracks.len());
        self.rate = rate;
        self.place_heard = v["place_new"].as_str() != Some("click");
        self.transport = transport_from(&v["transport"], rate);
        self.master_db = v["master_db"].as_f64().unwrap_or(0.0);
        self.markers = v["markers"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|m| {
                        Some(Marker {
                            position: m[0].as_i64()?,
                            name: m[1].as_str().unwrap_or("").to_string(),
                        })
                    })
                    .collect()
            })
            .unwrap_or_default();
        self.markers.sort_by_key(|m| m.position);
        // Prints carry over to the restored tracks: the one made from the same chain on the
        // same lane, else any print of that lane (stale until it is printed again).
        let prints: Vec<Printed> = self
            .tracks
            .iter()
            .filter_map(|t| t.printed.clone())
            .collect();
        self.tracks = tracks;
        for i in 0..self.tracks.len() {
            let sig = self.chain_signature(i);
            let t = &mut self.tracks[i];
            let lane = t.lane_signature();
            let same = prints.iter().find(|p| Some(&p.signature) == sig.as_ref());
            t.printed = same
                .or_else(|| prints.iter().find(|p| p.lane == lane))
                .cloned();
        }
        Ok(())
    }

    pub fn save(&self) -> Result<(), String> {
        std::fs::create_dir_all(&self.dir).map_err(|e| format!("{}: {e}", self.dir.display()))?;
        let p = self.dir.join("session.json");
        // A session from before clips keeps its file beside the new one (SE5).
        let old = self.dir.join("session.v1.json");
        if !old.exists()
            && let Ok(text) = std::fs::read_to_string(&p)
            && serde_json::from_str::<Value>(&text)
                .is_ok_and(|v| v["version"].as_u64().unwrap_or(1) < 2)
        {
            let _ = std::fs::write(&old, text);
        }
        std::fs::write(
            &p,
            serde_json::to_string_pretty(&self.state()).unwrap_or_default() + "\n",
        )
        .map_err(|e| format!("{}: {e}", p.display()))
    }

    pub fn load(dir: &Path) -> Result<Session, String> {
        let p = dir.join("session.json");
        let text = std::fs::read_to_string(&p).map_err(|e| format!("{}: {e}", p.display()))?;
        let v: Value = serde_json::from_str(&text).map_err(|e| format!("{}: {e}", p.display()))?;
        let mut s = Session {
            dir: dir.to_path_buf(),
            rate: v["rate"].as_u64().ok_or("session.json: no rate")? as u32,
            transport: TransportSettings::default(),
            tracks: Vec::new(),
            armed: None,
            place_heard: true,
            markers: Vec::new(),
            master_db: 0.0,
            known: HashMap::new(),
            revisions: HashMap::new(),
        };
        s.restore(&v)?;
        Ok(s)
    }

    /// The undo history saved with the session (oldest first; none: empty).
    pub fn load_history(&self) -> Vec<Value> {
        std::fs::read_to_string(self.dir.join("history.json"))
            .ok()
            .and_then(|t| serde_json::from_str::<Value>(&t).ok())
            .and_then(|v| v["undo"].as_array().cloned())
            .unwrap_or_default()
    }

    pub fn save_history(&self, undo: &[Value]) -> Result<(), String> {
        let p = self.dir.join("history.json");
        std::fs::write(
            &p,
            serde_json::to_string(&json!({ "undo": undo })).unwrap_or_default(),
        )
        .map_err(|e| format!("{}: {e}", p.display()))
    }

    /// The session in a new folder `dir` (which must not exist): every take recorded in
    /// this one (deleted ones too, so its history still works) and the history, copied.
    /// The copy is returned; this one is left as it is.
    pub fn copy_to(&self, dir: &Path) -> Result<Session, String> {
        if dir.exists() {
            return Err(format!("{} exists already", dir.display()));
        }
        std::fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
        let takes = self.dir.join("takes");
        if takes.is_dir() {
            copy_dir(&takes, &dir.join("takes"))?;
        }
        let history = self.dir.join("history.json");
        if history.is_file() {
            std::fs::copy(&history, dir.join("history.json"))
                .map_err(|e| format!("{}: {e}", history.display()))?;
        }
        let mut copy = self.clone();
        copy.dir = dir.to_path_buf();
        copy.save()?;
        Ok(copy)
    }
}

/// Copy a folder and everything in it.
fn copy_dir(from: &Path, to: &Path) -> Result<(), String> {
    std::fs::create_dir_all(to).map_err(|e| format!("{}: {e}", to.display()))?;
    for e in std::fs::read_dir(from).map_err(|e| format!("{}: {e}", from.display()))? {
        let e = e.map_err(|e| e.to_string())?;
        let (src, dst) = (e.path(), to.join(e.file_name()));
        if src.is_dir() {
            copy_dir(&src, &dst)?;
        } else {
            std::fs::copy(&src, &dst).map_err(|e| format!("{}: {e}", src.display()))?;
        }
    }
    Ok(())
}

pub fn transport_json(s: &TransportSettings) -> Value {
    json!({
        "bpm": s.bpm,
        "beats_per_bar": s.beats_per_bar,
        "beat_unit": s.beat_unit,
        "click": s.click.id(),
        "click_db": s.click_db,
        "count_in_bars": s.count_in_bars,
        "pre_roll_bars": s.pre_roll_bars,
        "punch": s.punch,
        "cursor": s.cursor,
        "snap": s.snap.id(),
        "return_to_cursor": s.return_to_cursor,
        "left_beat": s.left_beat,
        "right_beat": s.right_beat,
        "loop_on": s.loop_on,
    })
}

/// The transport from its JSON at `rate` (a session saved before the cursor: its start bar
/// as the cursor, SE2 decision 3).
pub fn transport_from(t: &Value, rate: u32) -> TransportSettings {
    let d = TransportSettings::default();
    let u = |k: &str, def: u32| t[k].as_u64().map_or(def, |x| x as u32);
    let mut s = TransportSettings {
        bpm: t["bpm"].as_f64().unwrap_or(d.bpm),
        beats_per_bar: u("beats_per_bar", d.beats_per_bar),
        beat_unit: u("beat_unit", d.beat_unit),
        click: t["click"]
            .as_str()
            .and_then(ClickMode::from_id)
            .unwrap_or(d.click),
        click_db: t["click_db"].as_f64().unwrap_or(d.click_db),
        count_in_bars: u("count_in_bars", d.count_in_bars),
        pre_roll_bars: u("pre_roll_bars", d.pre_roll_bars),
        cursor: 0,
        snap: t["snap"].as_str().and_then(Snap::from_id).unwrap_or(d.snap),
        return_to_cursor: t["return_to_cursor"]
            .as_bool()
            .unwrap_or(d.return_to_cursor),
        punch: t["punch"].as_bool().unwrap_or(false),
        left_beat: t["left_beat"].as_i64().unwrap_or(d.left_beat),
        right_beat: t["right_beat"].as_i64().unwrap_or(d.right_beat),
        loop_on: t["loop_on"].as_bool().unwrap_or(d.loop_on),
    };
    s.cursor = match (t["cursor"].as_i64(), t["start_bar"].as_i64()) {
        (Some(c), _) => c,
        (None, Some(bar)) => crate::transport::Grid::new(rate, &s).bar(bar.max(1)),
        (None, None) => 0,
    };
    s.clamped()
}

/// A take's folder in the session's.
pub fn take_dir(dir: &Path, id: &str) -> PathBuf {
    dir.join("takes").join(id)
}

fn revision_path(dir: &Path, id: &str, rev: u32) -> PathBuf {
    let d = take_dir(dir, id);
    if rev == 0 {
        d.join("events.json")
    } else {
        d.join(format!("events.{rev}.json"))
    }
}

/// The next free revision number in take `id`'s folder.
fn next_revision(dir: &Path, id: &str) -> u32 {
    (1..)
        .find(|&r| !revision_path(dir, id, r).exists())
        .expect("a free revision")
}

fn write_revision(dir: &Path, id: &str, rev: u32, perf: &Performance) -> Result<(), String> {
    let p = revision_path(dir, id, rev);
    if p.exists() {
        return Err(format!(
            "{} exists: revisions are never written over",
            p.display()
        ));
    }
    std::fs::create_dir_all(take_dir(dir, id)).map_err(|e| e.to_string())?;
    std::fs::write(
        &p,
        serde_json::to_string(&perf.to_json()).unwrap_or_default() + "\n",
    )
    .map_err(|e| format!("{}: {e}", p.display()))
}

fn read_revision(dir: &Path, id: &str, rev: u32) -> Result<Performance, String> {
    let p = revision_path(dir, id, rev);
    let text = std::fs::read_to_string(&p).map_err(|e| format!("{}: {e}", p.display()))?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("{}: {e}", p.display()))?;
    Performance::from_json(&v).map_err(|e| format!("{}: {e}", p.display()))
}

/// The audio file a take keeps what was heard in: the device's (`draft.wav`), or the
/// proxy's stand-in (`proxy.wav`: never a take's audio once it is rendered).
fn heard_file(k: &Take) -> &'static str {
    match &k.events {
        Some(e) if e.monitor == Monitor::Proxy => "proxy.wav",
        _ => "draft.wav",
    }
}

fn write_take(dir: &Path, k: &Take, rate: u32) -> Result<(), String> {
    let d = take_dir(dir, &k.id);
    // A new take's folder is new: nothing recorded is ever written over.
    std::fs::create_dir_all(dir.join("takes")).map_err(|e| format!("{}: {e}", dir.display()))?;
    std::fs::create_dir(&d)
        .map_err(|e| format!("{}: {e} (takes are never written over)", d.display()))?;
    match &k.right {
        // A stereo take: one 2-channel file (docs/STEREO_PLAN.md ST1).
        Some(r) => {
            let frames: Vec<[f32; 2]> = k
                .audio
                .iter()
                .zip(r.iter())
                .map(|(&a, &b)| [a, b])
                .collect();
            crate::audio::write_wav_stereo(&d.join(heard_file(k)), &frames, rate)?;
        }
        None => {
            let x: Vec<f64> = k.audio.iter().map(|&v| v as f64).collect();
            crate::audio::write_wav(&d.join(heard_file(k)), &x, rate)?;
        }
    }
    let v = json!({
        "id": k.id,
        "position": k.position,
        "latency": k.latency,
        "placed": if k.heard { "heard" } else { "click" },
        "rate": rate,
        "samples": k.audio.len(),
        "device": k.device,
        "recorded_unix_s": k.recorded_unix_s,
        "code": k.code,
    });
    let mut v = v;
    if let Some(from) = &k.rendered_from {
        v["rendered_from"] = from.clone();
    }
    if let Some(e) = &k.events {
        v["events"] = json!({"from": e.from, "monitor": e.monitor.name()});
    }
    let p = d.join("take.json");
    std::fs::write(
        &p,
        serde_json::to_string_pretty(&v).unwrap_or_default() + "\n",
    )
    .map_err(|e| format!("{}: {e}", p.display()))
}

fn read_take(dir: &Path, id: &str, rate: u32) -> Result<Take, String> {
    let d = dir.join("takes").join(id);
    let p = d.join("take.json");
    let text = std::fs::read_to_string(&p).map_err(|e| format!("{}: {e}", p.display()))?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("{}: {e}", p.display()))?;
    let wav = ["draft.wav", "proxy.wav"]
        .iter()
        .map(|f| d.join(f))
        .find(|p| p.is_file())
        .unwrap_or_else(|| d.join("draft.wav"));
    let w = crate::audio::decode(&wav)?;
    if w.rate != rate {
        return Err(format!(
            "{}: {} Hz in a {rate} Hz session",
            d.display(),
            w.rate
        ));
    }
    // A 2-channel file is a stereo take (more channels: their mean, as before).
    let (audio, right): (Vec<f32>, Option<Vec<f32>>) = match w.channels.as_slice() {
        [l, r] => (
            l.iter().map(|&v| v as f32).collect(),
            Some(r.iter().map(|&v| v as f32).collect()),
        ),
        _ => (w.mono().iter().map(|&v| v as f32).collect(), None),
    };
    let events = match &v["events"] {
        Value::Null => None,
        e => Some(Events {
            perf: Arc::new(read_revision(dir, id, 0)?),
            rev: 0,
            from: e["from"].as_u64().unwrap_or(0),
            monitor: e["monitor"]
                .as_str()
                .and_then(Monitor::from_name)
                .unwrap_or(Monitor::Device),
        }),
    };
    Ok(Take {
        id: id.to_string(),
        position: v["position"].as_i64().unwrap_or(0),
        latency: v["latency"].as_i64().unwrap_or(0),
        // Takes recorded before placements were placed on the click.
        heard: v["placed"].as_str() == Some("heard") || v["latency"].as_i64().unwrap_or(0) == 0,
        device: v["device"].as_str().unwrap_or("").to_string(),
        recorded_unix_s: v["recorded_unix_s"].as_u64().unwrap_or(0),
        code: v["code"].as_str().unwrap_or("").to_string(),
        overview: Arc::new(Overview::of_lr(&audio, right.as_deref(), OVERVIEW_BIN)),
        audio: Arc::new(audio),
        right: right.map(Arc::new),
        rendered_from: v.get("rendered_from").filter(|f| !f.is_null()).cloned(),
        events,
        renders: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_recorder_starts_at_the_start_bar_and_keeps_every_sample() {
        let mut r = Recorder::new(1000);
        r.armed = true;
        // Blocks of 300 from position -700: recording starts at 0.
        let mut at = -700;
        let mut expected = Vec::new();
        for b in 0..12 {
            let raw: Vec<f32> = (0..300).map(|i| (b * 300 + i) as f32).collect();
            for (i, &v) in raw.iter().enumerate() {
                if at + i as i64 >= 0 {
                    expected.push(v);
                }
            }
            r.capture(at, &raw, 0, 77, None);
            at += 300;
        }
        let (start, latency, len, tail) = r.tail(1000).expect("recording");
        assert_eq!((start, latency, len), (0, 77, expected.len()));
        assert_eq!(tail, expected[1000..]);
        r.armed = false;
        r.capture(at, &[0.0; 300], 0, 77, None);
        let rec = r.take_finished().expect("a take");
        assert_eq!(rec.start, 0);
        assert_eq!(rec.samples, expected);
        assert!(r.take_finished().is_none());
    }

    #[test]
    fn punching_records_only_between_the_locators() {
        let mut r = Recorder::new(1000);
        r.armed = true;
        let mut at = 0;
        for _ in 0..10 {
            let raw: Vec<f32> = (0..100).map(|i| (at + i) as f32).collect();
            r.capture_until(at, &raw, None, 250, 640, 0, None);
            at += 100;
        }
        let rec = r.take_finished().expect("a take");
        assert_eq!((rec.start, rec.samples.len()), (250, 390));
        assert_eq!((rec.samples[0], rec.samples[389]), (250.0, 639.0));
        assert!(r.take_finished().is_none());
    }

    #[test]
    fn a_loop_records_a_take_per_pass() {
        let mut r = Recorder::new(1000);
        r.armed = true;
        // Passes over 100..400 in blocks of 150, the jump inside a block's segments.
        let mut pos = 100;
        for _ in 0..7 {
            let mut left = 150;
            while left > 0 {
                let len = left.min((400 - pos) as usize);
                r.capture(pos, &vec![pos as f32; len], 100, 5, None);
                pos += len as i64;
                left -= len;
                if pos == 400 {
                    pos = 100;
                }
            }
        }
        r.stop();
        let takes: Vec<Recorded> = std::iter::from_fn(|| r.take_finished()).collect();
        // 7 * 150 = 1050 samples: three full passes of 300 and 150 more.
        assert_eq!(takes.len(), 4);
        assert!(takes.iter().all(|t| t.start == 100 && t.latency == 5));
        assert_eq!(
            takes.iter().map(|t| t.samples.len()).collect::<Vec<_>>(),
            vec![300, 300, 300, 150]
        );
        assert_eq!(takes[1].samples[0], 100.0);
    }

    #[test]
    fn the_mix_follows_faders_mute_and_solo() {
        let mut s = Session::new(PathBuf::from("unused"), 1000, TransportSettings::default());
        let take = |pos: i64, v: f32| Take {
            id: "t".into(),
            position: pos,
            latency: 0,
            heard: true,
            device: String::new(),
            recorded_unix_s: 0,
            code: String::new(),
            audio: Arc::new(vec![v; 10]),
            overview: Arc::new(Overview::default()),
            right: None,
            rendered_from: None,
            events: None,
            renders: Vec::new(),
        };
        s.tracks[0].takes.push(take(5, 1.0));
        s.tracks[0].set_active(0);
        let mut t2 = Track::new("2");
        t2.takes.push(take(0, 0.5));
        t2.set_active(0);
        t2.pan = 1.0;
        s.tracks.push(t2);
        let mut out = vec![[0.0f32; 2]; 20];
        s.mix().add(0, &mut out);
        assert_eq!(out[0], [0.0, 0.5]); // track 2 only, hard right
        assert_eq!(out[7], [1.0, 1.5]);
        assert_eq!(out[14], [1.0, 1.0]);
        assert_eq!(out[15], [0.0, 0.0]);
        s.tracks[1].solo = true;
        let mut out = vec![[0.0f32; 2]; 20];
        s.mix().add(0, &mut out);
        assert_eq!(out[7], [0.0, 0.5]);
        // The live device plays through the armed track's strip: off while another solos.
        assert_eq!(s.mix().live, (0.0, 0.0));
        s.tracks[1].solo = false;
        s.tracks[0].volume_db = -6.0;
        let (l, r) = s.mix().live;
        assert!((l - 0.501).abs() < 1e-3 && l == r);
    }

    #[test]
    fn the_meters_read_the_mix_post_fader_and_the_master_moves_the_export() {
        let mut s = Session::new(
            PathBuf::from("unused"),
            48_000,
            TransportSettings::default(),
        );
        // A -6 dBFS sine on track 0 at 0 dB, centred; silence on track 1.
        let sine: Vec<f32> = (0..48_000)
            .map(|i| 0.5 * (2.0 * std::f32::consts::PI * 1000.0 * i as f32 / 48_000.0).sin())
            .collect();
        let take = |audio: Vec<f32>| Take {
            id: "t".into(),
            position: 0,
            latency: 0,
            heard: true,
            device: String::new(),
            recorded_unix_s: 0,
            code: String::new(),
            overview: Arc::new(Overview::default()),
            audio: Arc::new(audio),
            right: None,
            rendered_from: None,
            events: None,
            renders: Vec::new(),
        };
        s.tracks[0].takes.push(take(sine));
        s.tracks[0].set_active(0);
        let mut t2 = Track::new("2");
        t2.takes.push(take(vec![0.0; 48_000]));
        t2.set_active(0);
        s.tracks.push(t2);
        let mix = s.mix();
        assert_eq!(
            mix.clips.iter().map(|c| c.track).collect::<Vec<_>>(),
            vec![0, 1]
        );
        let mut out = vec![[0.0f32; 2]; 4800];
        let mut m = Meters {
            frames: out.len(),
            ..Meters::default()
        };
        mix.add_metered(0, &mut out, &mut m);
        let peak = to_dbfs(m.tracks[0][0]);
        assert!((peak - -6.02).abs() < 0.01, "{peak}");
        assert_eq!(m.tracks[0][0], m.tracks[0][1]); // centred: the balance law's unity
        assert_eq!(m.tracks[1][0], 0.0);
        // The fader moves the meter (post-fader): -6 dB more.
        s.tracks[0].volume_db = -6.0;
        let mut m2 = Meters::default();
        s.mix()
            .add_metered(0, &mut vec![[0.0f32; 2]; 4800], &mut m2);
        assert!((to_dbfs(m2.tracks[0][0]) - -12.04).abs() < 0.02);
        // The master on the export: -6 dB halves the mix and its stems.
        s.tracks[0].volume_db = 0.0;
        let before = s.mixdown().mix();
        s.master_db = -20.0 * 2f64.log10();
        let md = s.mixdown();
        let after = md.mix();
        assert!((md.master - 0.5).abs() < 1e-6);
        for (a, b) in before.iter().zip(&after).take(1000) {
            assert!((a[0] * 0.5 - b[0]).abs() < 1e-6);
        }
        assert_eq!(s.mix().master, md.master);
    }

    fn plain_take(id: &str, position: i64, audio: Vec<f32>) -> Take {
        Take {
            id: id.into(),
            position,
            latency: 0,
            heard: true,
            device: String::new(),
            recorded_unix_s: 0,
            code: String::new(),
            overview: Arc::new(Overview::default()),
            audio: Arc::new(audio),
            right: None,
            rendered_from: None,
            events: None,
            renders: Vec::new(),
        }
    }

    fn render_mix(s: &Session, at: i64, n: usize) -> Vec<Frame> {
        let mut out = vec![[0.0f32; 2]; n];
        s.mix().add(at, &mut out);
        out
    }

    #[test]
    fn a_split_plays_seamlessly_and_a_cut_moved_away_never_clicks() {
        let rate = 48_000;
        let mut s = Session::new(PathBuf::from("unused"), rate, TransportSettings::default());
        let sine: Vec<f32> = (0..48_000)
            .map(|i| 0.5 * (2.0 * std::f32::consts::PI * 1000.0 * i as f32 / 48_000.0).sin())
            .collect();
        s.tracks[0]
            .takes
            .push(plain_take("t0001", 1000, sine.clone()));
        s.tracks[0].set_active(0);
        let whole = render_mix(&s, 0, 50_000);
        // Split: the same samples, bit for bit (the cut's fades come off where it's seamless).
        let r = s.tracks[0]
            .split_clip(0, 1000 + 20_000, rate)
            .expect("split");
        assert_eq!(r, 1);
        assert_eq!(s.tracks[0].clips[0].fade_out, default_fade(rate));
        assert_eq!(render_mix(&s, 0, 50_000), whole);
        // The right half moved a little: its edges fade, no step above the sine's own.
        s.tracks[0].clips[1].position += 7;
        let y = render_mix(&s, 0, 50_000);
        let own = sine
            .windows(2)
            .map(|w| (w[1] - w[0]).abs())
            .fold(0.0f32, f32::max);
        let worst = y
            .windows(2)
            .map(|w| (w[1][0] - w[0][0]).abs())
            .fold(0.0f32, f32::max);
        assert!(worst <= own * 1.1, "{worst} vs the sine's own {own}");
        // Trimmed (a clip shorter than its take) and muted.
        s.tracks[0].clips[1].len = 1000;
        assert_eq!(s.tracks[0].end(), 1000 + 20_007 + 1000);
        s.tracks[0].clips[1].muted = true;
        assert_eq!(s.tracks[0].pieces().len(), 1);
    }

    #[test]
    fn a_later_clip_wins_and_the_earlier_crossfades_under_its_fade() {
        let mut s = Session::new(PathBuf::from("unused"), 1000, TransportSettings::default());
        s.tracks[0].takes.push(plain_take("a", 0, vec![1.0; 1000]));
        s.tracks[0].takes.push(plain_take("b", 0, vec![0.5; 1000]));
        s.tracks[0].set_active(0);
        let b = Clip {
            src_start: 0,
            len: 300,
            position: 400,
            fade_in: 100,
            fade_out: 50,
            ..Clip::whole(&s.tracks[0].takes[1])
        };
        s.tracks[0].clips.push(b);
        let p = s.tracks[0].pieces();
        // A before B (fading out under B's fade in), A after B, B whole.
        assert_eq!(
            p.iter()
                .map(|p| (p.clip, p.start, p.len, p.fade_in, p.fade_out))
                .collect::<Vec<_>>(),
            vec![
                (0, 0, 500, 0, 100),
                (0, 650, 350, 50, 0),
                (1, 400, 300, 100, 50)
            ]
        );
        // In the crossfade the two sum to the level between them; under B, B alone.
        let y = render_mix(&s, 0, 1000);
        assert!(
            (y[450][0] - (1.0 * 0.495 + 0.5 * 0.505)).abs() < 0.02,
            "{}",
            y[450][0]
        );
        assert_eq!(y[550][0], 0.5);
        assert_eq!(y[900][0], 1.0);
        // The lane's sum is what the track plays (a print's input), from its start.
        let (start, lane) = s.tracks[0].lane().unwrap();
        assert_eq!((start, lane.len()), (0, 1000));
        assert_eq!(lane[550], 0.5);
        // A print of it follows the clips: moving one changes the chain's signature.
        s.tracks[0].inserts.push(Slot::new("pultec_eqp1a"));
        let sig = s.tracks[0].chain_signature(1000).unwrap();
        s.tracks[0].clips[1].position += 10;
        assert_ne!(s.tracks[0].chain_signature(1000).unwrap(), sig);
    }

    #[test]
    fn a_session_from_before_clips_plays_as_it_did() {
        // A version-1 state: no clips, each track's active take whole.
        let mut s = Session::new(PathBuf::from("unused"), 1000, TransportSettings::default());
        s.tracks[0].takes.push(plain_take(
            "t0001",
            5,
            (0..100).map(|i| i as f32 * 0.01).collect(),
        ));
        s.tracks[0]
            .takes
            .push(plain_take("t0002", -20, vec![0.25; 300]));
        s.tracks[0].active = Some(1);
        s.tracks[0].volume_db = -3.0;
        s.tracks[0].pan = 0.4;
        let mut v = s.state();
        v["version"] = json!(1);
        for t in v["tracks"].as_array_mut().unwrap() {
            t.as_object_mut().unwrap().remove("clips");
        }
        for (id, k) in [("t0001", 0), ("t0002", 1)] {
            s.known.insert(id.into(), s.tracks[0].takes[k].clone());
        }
        let mut u = s.clone();
        u.restore(&v).expect("restored");
        assert_eq!(u.tracks[0].clips.len(), 1);
        assert_eq!(u.tracks[0].clips[0].take, "t0002");
        // The old mix: the active take whole through the strip.
        let k = &s.tracks[0].takes[1];
        let old = Mix {
            clips: vec![MixClip::whole(
                k.position,
                k.audio.clone(),
                s.tracks[0].gains(),
            )],
            ..Mix::default()
        };
        let mut want = vec![[0.0f32; 2]; 400];
        old.add(-50, &mut want);
        assert_eq!(render_mix(&u, -50, 400), want);
        // The lane is the take's own audio (a print's key stays what it was).
        assert!(Arc::ptr_eq(&u.tracks[0].lane().unwrap().1, &k.audio));
    }

    #[test]
    fn copy_paste_duplicate_and_time_edits_keep_the_audio_shared() {
        let mut s = Session::new(PathBuf::from("unused"), 1000, TransportSettings::default());
        s.tracks[0].takes.push(plain_take("a", 0, vec![0.5; 1000]));
        s.tracks[0].set_active(0);
        let mut t2 = Track::new("2");
        t2.takes.push(plain_take("b", 200, vec![0.25; 400]));
        t2.set_active(0);
        s.tracks.push(t2);
        // A range across both tracks, cut at its edges.
        let items = s.copy_range(100, 300, 0..=1);
        assert_eq!(items.len(), 2);
        assert_eq!(
            (
                items[0].clip.position,
                items[0].clip.src_start,
                items[0].clip.len
            ),
            (0, 100, 200)
        );
        assert_eq!(
            (items[1].track, items[1].clip.position, items[1].clip.len),
            (1, 100, 100)
        );
        // Pasted at 2000: the same offsets; the takes shared, not copied.
        let new = s.paste(&items, 2000, 0);
        assert_eq!(new, vec![(0, 1), (1, 1)]);
        assert_eq!(s.tracks[1].clips[1].position, 2100);
        assert_eq!(s.tracks[0].takes.len(), 1);
        assert!(Arc::ptr_eq(
            &s.tracks[0].takes[0].audio,
            &items[0].take.audio
        ));
        let y = render_mix(&s, 2000, 300);
        assert_eq!((y[50][0], y[150][0]), (0.5, 0.75));
        // Pasted below the last track: a new track with the take in its pool.
        s.paste(&items[1..], 0, 2);
        assert_eq!(s.tracks.len(), 4);
        assert_eq!(s.tracks[3].takes[0].id, "b");
        // Delete a range: the clip across it cut, the part outside kept.
        assert!(s.tracks[0].delete_range(400, 600, 1000));
        let spans: Vec<(i64, i64)> = s.tracks[0]
            .clips
            .iter()
            .map(|c| (c.position, c.end()))
            .collect();
        assert_eq!(spans, vec![(0, 400), (600, 1000), (2000, 2200)]);
        // Insert time at 500, then delete it: back where they were; markers follow.
        s.markers.push(Marker {
            position: 700,
            name: "m".into(),
        });
        s.insert_time(500, 250);
        assert_eq!(s.tracks[0].clips[1].position, 850);
        assert_eq!(s.markers[0].position, 950);
        s.delete_time(500, 750);
        assert_eq!(s.tracks[0].clips[1].position, 600);
        assert_eq!(s.markers[0].position, 700);
    }

    #[test]
    fn a_bounce_lies_where_the_midi_clips_were_and_mutes_them() {
        let mut t = Track::new("x");
        t.takes.push(plain_take("m", 0, vec![0.1; 1000]));
        t.set_active(0);
        t.clips[0].src_start = 100;
        t.clips[0].len = 500;
        t.clips[0].position = 100;
        t.takes.push(plain_take("audio", 0, vec![0.2; 1000]));
        t.clips.push(Clip::whole(&t.takes[1]));
        t.bounce_clips("m", "audio");
        assert_eq!(t.clips.len(), 2);
        assert!(t.clips[0].muted && t.clips[0].take == "m");
        let c = &t.clips[1];
        assert_eq!(
            (c.take.as_str(), c.src_start, c.len, c.position),
            ("audio", 100, 500, 100)
        );
    }

    /// Every session in `$VARIMU_SESSIONS` (a folder of session folders, read only) plays
    /// the same mix as before clips: each track's active take whole. Run by hand:
    /// `VARIMU_SESSIONS=../../sessions cargo test -p varimu-app --lib -- --ignored every_session`.
    #[test]
    #[ignore]
    fn every_session_opens_to_the_same_mix() {
        let Ok(root) = std::env::var("VARIMU_SESSIONS") else {
            return;
        };
        let mut checked = 0;
        for e in std::fs::read_dir(&root)
            .expect("a sessions folder")
            .flatten()
        {
            let dir = e.path();
            if !dir.join("session.json").is_file() {
                continue;
            }
            let text = std::fs::read_to_string(dir.join("session.json")).unwrap();
            let v: Value = serde_json::from_str(&text).unwrap();
            if v["version"].as_u64().unwrap_or(1) >= 2 {
                continue;
            }
            let s = match Session::load(&dir) {
                Ok(s) => s,
                Err(err) => {
                    println!("{}: doesn't load ({err})", dir.display());
                    continue;
                }
            };
            // Before clips: each audible track's active take's sound, whole, at its place.
            let any_solo = s.tracks.iter().any(|t| t.solo);
            let old = Mix {
                clips: s
                    .tracks
                    .iter()
                    .filter(|t| if any_solo { t.solo } else { !t.mute })
                    .filter_map(|t| {
                        let k = t.active_take()?;
                        Some(MixClip::whole(
                            k.position,
                            k.sound(t.drafts).0.clone(),
                            t.gains(),
                        ))
                    })
                    .collect(),
                ..Mix::default()
            };
            let end = s.end();
            let start = s
                .tracks
                .iter()
                .filter_map(Track::lane_span)
                .map(|x| x.0)
                .min()
                .unwrap_or(0)
                .min(0);
            let n = (end - start).max(0) as usize;
            let mut want = vec![[0.0f32; 2]; n];
            old.add(start, &mut want);
            assert_eq!(render_mix(&s, start, n), want, "{}", dir.display());
            println!(
                "{}: {} tracks, {n} frames, the same",
                dir.display(),
                s.tracks.len()
            );
            checked += 1;
        }
        println!("{checked} sessions checked");
    }

    #[test]
    fn a_stereo_recording_keeps_both_channels() {
        let mut r = Recorder::new(100);
        r.armed = true;
        let mut at = 0;
        for _ in 0..5 {
            let l: Vec<f32> = (0..70).map(|i| (at + i) as f32).collect();
            let rr: Vec<f32> = l.iter().map(|v| -v).collect();
            r.capture_until(at, &l, Some(&rr), 30, i64::MAX, 0, None);
            at += 70;
        }
        // A mono block after it: a take of its own (a take is mono or stereo throughout).
        r.capture_until(at, &[9.0; 70], None, 30, i64::MAX, 0, None);
        r.armed = false;
        r.capture(at + 70, &[0.0; 10], 0, 0, None);
        let a = r.take_finished().expect("the stereo take");
        assert_eq!((a.start, a.samples.len()), (30, 320));
        let right = a.right.expect("stereo");
        assert_eq!(right.len(), 320);
        assert!(a.samples.iter().zip(&right).all(|(l, r)| *r == -*l));
        let b = r.take_finished().expect("the mono take");
        assert_eq!((b.start, b.samples.len(), b.right), (350, 70, None));
    }

    #[test]
    fn a_stereo_take_saves_loads_and_mixes_through_the_balance() {
        let dir = std::env::temp_dir().join(format!("varimu_stereo_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let mut s = Session::new(dir.clone(), 1000, TransportSettings::default());
        let l: Vec<f32> = (0..400).map(|i| (i as f32 * 0.07).sin() * 0.5).collect();
        let r: Vec<f32> = (0..400).map(|i| (i as f32 * 0.11).cos() * 0.25).collect();
        let rec = Recorded {
            start: 100,
            latency: 0,
            samples: l.clone(),
            right: Some(r.clone()),
            performance: None,
        };
        s.add_take(0, rec, "rhodes_suitcase").expect("saved");
        let t = Session::load(&dir).expect("loads");
        let k = &t.tracks[0].takes[0];
        assert_eq!(*k.audio, l);
        assert_eq!(k.right.as_deref(), Some(&r)); // one 2-channel float file, bit for bit
        assert!(t.tracks[0].is_stereo());
        // The mix: left on the left, right on the right; the balance turns one side down.
        let mut t = t;
        let mix = |t: &Session| {
            let mut out = vec![[0.0f32; 2]; 600];
            t.mix().add(0, &mut out);
            out
        };
        let out = mix(&t);
        assert_eq!(out[150], [l[50], r[50]]);
        t.tracks[0].pan = 0.5;
        let out = mix(&t);
        assert_eq!(out[150], [0.5 * l[50], r[50]]);
        // The lane's right channel; a mono clip on it plays on both sides.
        let (start, a, b) = t.tracks[0].lane_lr().expect("a lane");
        assert_eq!(
            (start, a.len(), b.as_ref().map(|b| b.len())),
            (100, 400, Some(400))
        );
        let mono = Recorded {
            start: 600,
            latency: 0,
            samples: vec![0.3; 50],
            right: None,
            performance: None,
        };
        t.add_take(0, mono, "test").expect("saved");
        let t0 = &mut t.tracks[0];
        let first = t0.takes[0].clone();
        t0.clips.insert(0, Clip::whole(&first));
        let (start, a, b) = t0.lane_lr().expect("a lane");
        let b = b.expect("still stereo");
        assert_eq!((start, a.len(), b.len()), (100, 550, 550));
        assert_eq!((a[520], b[520]), (0.3, 0.3));
        assert_eq!((a[10], b[10]), (l[10], r[10]));
        // A mono lane keeps no right channel and its signature as before.
        let mut m = Track::new("m");
        m.takes.push(t.tracks[0].takes[1].clone());
        m.set_active(0);
        assert!(!m.is_stereo() && m.lane_lr().expect("a lane").2.is_none());
        assert!(!m.lane_signature().contains("stereo"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_session_survives_a_save_and_load() {
        let dir = std::env::temp_dir().join(format!("varimu_session_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let mut s = Session::new(dir.clone(), 48_000, TransportSettings::default());
        s.transport.bpm = 93.5;
        let rec = Recorded {
            start: 1000,
            latency: 240,
            samples: (0..4800).map(|i| (i as f32 * 0.01).sin() * 0.5).collect(),
            right: None,
            performance: None,
        };
        s.add_take(0, rec.clone(), "tube_synth").expect("saved");
        s.tracks.push(Track::new("Bass"));
        s.tracks[1].pan = -0.5;
        s.tracks[1].midi = false;
        s.tracks[0].monitor = Monitor::Proxy;
        let rec_click = rec.clone();
        s.add_take(1, rec, "fender_5e3").expect("saved");
        let t = Session::load(&dir).expect("loads");
        assert_eq!(t.transport.bpm, 93.5);
        assert_eq!(t.tracks.len(), 2);
        assert_eq!(t.tracks[1].pan, -0.5);
        assert!(!t.tracks[1].midi && t.tracks[0].midi);
        assert_eq!(
            (t.tracks[0].monitor, t.tracks[1].monitor),
            (Monitor::Proxy, Monitor::Device)
        );
        let (a, b) = (&s.tracks[0].takes[0], &t.tracks[0].takes[0]);
        // Placed as heard: where it was recorded.
        assert_eq!((b.position, b.heard), (1000, true));
        assert_eq!(a.audio, b.audio); // float32 on disk: bit for bit
        // On the click: its latency earlier; back as heard; kept by a save.
        let mut t = t;
        assert!(t.tracks[0].takes[0].place(false));
        assert!(!t.tracks[0].takes[0].place(false));
        assert_eq!(t.tracks[0].takes[0].position, 760);
        t.save().expect("saved");
        let v = Session::load(&dir).expect("loads");
        assert_eq!(
            (v.tracks[0].takes[0].position, v.tracks[0].takes[0].heard),
            (760, false)
        );
        assert!(t.place_all(true));
        assert_eq!(t.tracks[0].takes[0].position, 1000);
        assert!(!t.place_all(true));
        // New takes on the click when the session says so.
        t.place_heard = false;
        t.save().expect("saved");
        let mut v = Session::load(&dir).expect("loads");
        assert!(!v.place_heard);
        v.add_take(1, rec_click.clone(), "fender_5e3")
            .expect("saved");
        let k = v.tracks[1].active_take().unwrap();
        assert_eq!((k.position, k.heard), (760, false));
        // A take recorded before placements: on the click.
        let id = k.id.clone();
        let tj = dir.join("takes").join(&id).join("take.json");
        let mut j: Value = serde_json::from_str(&std::fs::read_to_string(&tj).unwrap()).unwrap();
        j.as_object_mut().unwrap().remove("placed");
        std::fs::write(&tj, j.to_string()).unwrap();
        assert!(!read_take(&dir, &id, 48_000).unwrap().heard);
        assert_eq!(
            t.tracks[1].active_take().map(|k| k.id.as_str()),
            Some("t0002")
        );
        // A take moved on the timeline stays where it was moved.
        t.tracks[0].takes[0].position = 48_000;
        t.save().expect("saved");
        let u = Session::load(&dir).expect("loads");
        assert_eq!(u.tracks[0].takes[0].position, 48_000);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_mixdown_is_what_plays_and_its_stems_sum_to_it() {
        let base = std::env::temp_dir().join(format!("varimu_export_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        let mut s = Session::new(base.join("s"), 1000, TransportSettings::default());
        s.tracks.push(Track::new("B"));
        s.tracks.push(Track::new("muted"));
        let rec = |start: i64, v: f32, n: usize| Recorded {
            start,
            latency: 0,
            samples: vec![v; n],
            right: None,
            performance: None,
        };
        s.add_take(0, rec(0, 0.25, 300), "x").expect("saved");
        s.add_take(1, rec(-50, 0.5, 100), "x").expect("saved"); // a pickup before bar 1
        s.add_take(2, rec(0, 0.9, 1000), "x").expect("saved");
        s.tracks[1].pan = 1.0;
        s.tracks[1].volume_db = -6.0;
        s.tracks[2].mute = true;
        assert!(s.export_problems(false).is_empty());
        let md = s.mixdown();
        // From the pickup to the longest audible take's end; the muted take isn't in it.
        assert_eq!((md.start, md.len, md.tracks.len()), (-50, 350, 2));
        let mix = md.mix();
        let g = 10f32.powf(-6.0 / 20.0);
        assert_eq!(mix[0], [0.0, 0.5 * g]); // B alone, panned right
        assert_eq!(mix[60], [0.25, 0.25 + 0.5 * g]);
        assert_eq!(mix[200], [0.25, 0.25]);
        assert_eq!(mix[349], [0.25, 0.25]);
        let (a, b) = (md.stem(0), md.stem(1));
        for i in 0..md.len {
            assert_eq!([a[i][0] + b[i][0], a[i][1] + b[i][1]], mix[i]);
        }
        // Written: the mix, the stems, the record.
        let path = base.join("out/s mix.wav");
        let peak = md.write(&path, true, &s.export_record()).expect("written");
        assert!((peak - 20.0 * (0.25 + 0.5 * g).log10() as f64).abs() < 1e-6);
        let d = crate::audio::decode(&path).expect("reads");
        assert_eq!((d.rate, d.channels.len(), d.frames()), (1000, 2, 350));
        assert!(base.join("out/s mix stems/02 B.wav").is_file());
        let j: Value =
            serde_json::from_str(&std::fs::read_to_string(base.join("out/s mix.json")).unwrap())
                .unwrap();
        assert_eq!(j["start_s"], json!(-0.05));
        assert_eq!(j["tracks"].as_array().map(Vec::len), Some(2));
        // A final waits for production; audio takes without inserts are already final.
        assert!(s.export_problems(true).is_empty());
        // An insert not printed yet: the export waits for it (a final for production too).
        s.tracks[1].inserts.push(Slot::new("plate_reverb"));
        assert_eq!(
            s.export_problems(false),
            vec!["B: its inserts aren't printed as they are now"]
        );
        s.tracks[1].mute = true;
        assert!(s.export_problems(false).is_empty()); // only audible tracks count
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn any_earlier_state_comes_back_and_copies_keep_everything() {
        let base = std::env::temp_dir().join(format!("varimu_undo_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        let mut s = Session::new(base.join("a"), 1000, TransportSettings::default());
        let rec = |v: f32| Recorded {
            start: 0,
            latency: 0,
            samples: vec![v; 100],
            right: None,
            performance: None,
        };
        s.add_take(0, rec(0.1), "x").expect("saved");
        let one = s.state();
        s.add_take(0, rec(0.2), "x").expect("saved");
        // Delete both takes; the first state comes back with its audio.
        s.tracks[0].takes.clear();
        s.tracks[0].active = None;
        s.restore(&one).expect("restored");
        assert_eq!(s.tracks[0].takes.len(), 1);
        assert_eq!(s.tracks[0].takes[0].audio[0], 0.1);
        // A copy holds every take (the deleted second one too) and the history.
        s.save_history(std::slice::from_ref(&one)).expect("saved");
        let mut c = s.copy_to(&base.join("b")).expect("copied");
        assert!(base.join("b/takes/t0002/draft.wav").is_file());
        assert_eq!(c.load_history().len(), 1);
        let two = {
            let mut t = c.state();
            t["tracks"][0]["takes"] = json!(["t0001", "t0002"]);
            t["tracks"][0]["active"] = json!("t0002");
            t
        };
        let mut fresh = Session::load(&base.join("b")).expect("loads");
        fresh
            .restore(&two)
            .expect("restored from the copy's folder");
        assert_eq!(fresh.tracks[0].active_take().map(|k| k.audio[0]), Some(0.2));
        c.tracks.clear();
        assert!(s.copy_to(&base.join("b")).is_err()); // never over an existing folder
        let _ = std::fs::remove_dir_all(&base);
    }

    #[test]
    fn inserts_are_saved_and_the_mix_plays_their_print() {
        let dir = std::env::temp_dir().join(format!("varimu_inserts_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let mut s = Session::new(dir.clone(), 1000, TransportSettings::default());
        let rec = |v: f32| Recorded {
            start: 10,
            latency: 0,
            samples: vec![v; 100],
            right: None,
            performance: None,
        };
        s.add_take(0, rec(0.1), "x").expect("saved");
        assert_eq!(s.tracks[0].chain_signature(1000), None);
        let mut slot = Slot::new("pultec_eqp1a");
        slot.trim_db = -3.0;
        s.tracks[0].inserts.push(slot.clone());
        let sig = s.tracks[0].chain_signature(1000).expect("a chain");
        // No print yet: the dry take plays.
        let mut out = vec![[0.0f32; 2]; 200];
        s.mix().add(0, &mut out);
        assert_eq!(out[50][0], 0.1);
        s.tracks[0].printed = Some(Printed {
            signature: sig.clone(),
            lane: s.tracks[0].lane_signature(),
            start: s.tracks[0].lane_span().unwrap().0,
            audio: Arc::new(vec![0.7; 150]),
            right: None,
            stages_right: Vec::new(),
            overview: Arc::new(Overview::default()),
            stages: Vec::new(),
        });
        assert!(s.tracks[0].print_current(1000));
        let mut out = vec![[0.0f32; 2]; 200];
        s.mix().add(0, &mut out);
        assert_eq!((out[50][0], out[150][0]), (0.7, 0.7)); // the tail past the take
        // Another setting: the old print plays, stale.
        s.tracks[0].inserts[0].makeup_db = 2.0;
        assert!(!s.tracks[0].print_current(1000));
        assert_eq!(s.tracks[0].playing(1000).map(|p| p.2), Some(true));
        // Bypassed: nothing to print, the take plays.
        s.tracks[0].inserts[0].bypass = true;
        assert_eq!(s.tracks[0].playing(1000).map(|p| p.2), Some(false));
        s.tracks[0].inserts[0].bypass = false;
        // Another take: its own print is due, the take plays meanwhile.
        s.add_take(0, rec(0.2), "x").expect("saved");
        assert_eq!(s.tracks[0].playing(1000).map(|p| p.2), Some(false));
        // Saved, loaded, undone: the inserts come back.
        let state = s.state();
        let u = Session::load(&dir).expect("loads");
        assert_eq!(u.tracks[0].inserts.len(), 1);
        assert_eq!(u.tracks[0].inserts[0].makeup_db, 2.0);
        s.tracks[0].inserts.clear();
        s.restore(&state).expect("restored");
        assert_eq!(s.tracks[0].inserts[0].trim_db, -3.0);
        // A render into a new take: placed where its source is, saved with what it came
        // from, read back with it.
        let pos = s.tracks[0]
            .active_take()
            .map(|k| k.position)
            .expect("a take");
        let from = json!({"take": "t0002", "quality": "production"});
        let id = s
            .add_rendered_take(0, vec![0.25; 120], None, pos, from.clone())
            .expect("saved");
        assert_eq!(
            s.tracks[0].active_take().map(|k| k.id.clone()),
            Some(id.clone())
        );
        let u = Session::load(&dir).expect("loads");
        let k = u.tracks[0].active_take().expect("the render");
        assert_eq!((k.id.clone(), k.position), (id, pos));
        assert_eq!(k.rendered_from, Some(from));
        assert_eq!(k.audio.len(), 120);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_key_route_feeds_the_kick_into_the_bass_and_follows_it() {
        use crate::print::KeyRoute;

        let dir = std::env::temp_dir().join(format!("varimu_key_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let mut s = Session::new(dir.clone(), 1000, TransportSettings::default());
        s.tracks[0].name = "Bass".into();
        s.tracks.push(Track::new("Kick"));
        let rec = |start: i64, x: Vec<f32>| Recorded {
            start,
            latency: 0,
            samples: x,
            right: None,
            performance: None,
        };
        s.add_take(0, rec(100, vec![0.1; 50]), "x").expect("saved");
        s.add_take(1, rec(120, (0..20).map(|i| i as f32).collect()), "x")
            .expect("saved");
        assert_ne!(s.tracks[0].id, s.tracks[1].id);
        let mut slot = Slot::new("fairchild_670_keyed");
        slot.tail_s = 0.01; // 10 samples at 1 kHz
        slot.key = Some(KeyRoute {
            track: s.tracks[1].id.clone(),
            trim_db: -2.0,
        });
        s.tracks[0].inserts.push(slot.clone());
        // The kick from the bass take's start (100), over the take and the tail: silence,
        // the kick's 20 samples from 120, silence.
        let side = s.sidechain(0, &slot).expect("a sidechain");
        assert_eq!(side.len(), 60);
        assert_eq!(side[19], 0.0);
        assert_eq!((side[20], side[39]), (0.0, 19.0));
        assert_eq!(side[40], 0.0);
        assert_eq!(s.sidechains(0).len(), 1);
        // Muted, the kick still keys.
        s.tracks[1].mute = true;
        assert_eq!(s.sidechain(0, &slot), Some(side.clone()));
        // The bass's signature follows what the kick plays.
        let sig = s.chain_signature(0).expect("a chain");
        assert!(sig.starts_with(&s.tracks[0].chain_signature(1000).unwrap()));
        s.tracks[1].clips[0].position = 130;
        let moved = s.chain_signature(0).unwrap();
        assert_ne!(sig, moved, "the kick moved");
        s.tracks[1].inserts.push(Slot::new("pultec_eqp1a"));
        let chained = s.chain_signature(0).unwrap();
        assert_ne!(moved, chained, "the kick has an insert");
        // ... and waits for the kick's print before printing.
        assert!(!s.keys_ready(0));
        s.tracks[1].printed = Some(Printed {
            signature: s.chain_signature(1).unwrap(),
            lane: s.tracks[1].lane_signature(),
            start: s.tracks[1].lane_span().unwrap().0,
            audio: Arc::new(vec![0.5; 25]),
            right: None,
            stages_right: Vec::new(),
            overview: Arc::new(Overview::default()),
            stages: Vec::new(),
        });
        assert!(s.keys_ready(0) && s.print_current(1));
        // The kick's print is what keys now (from 130).
        let side = s.sidechain(0, &slot).unwrap();
        assert_eq!(
            (side[29], side[30], side[54], side[55]),
            (0.0, 0.5, 0.5, 0.0)
        );
        // Loops are refused: the kick keyed from the bass, a track keyed from itself.
        assert!(s.would_cycle(1, 0));
        assert!(s.would_cycle(0, 0));
        assert!(!s.would_cycle(0, 1));
        // Saved and loaded: the ids and the route.
        let ids = (s.tracks[0].id.clone(), s.tracks[1].id.clone());
        s.save().expect("saved");
        let u = Session::load(&dir).expect("loads");
        assert_eq!((u.tracks[0].id.clone(), u.tracks[1].id.clone()), ids);
        assert_eq!(u.tracks[0].inserts[0].key, slot.key);
        assert_eq!(u.chain_signature(0), s.chain_signature(0));
        // A session saved before tracks had ids: ids by place.
        let mut old = s.state();
        for t in old["tracks"].as_array_mut().unwrap() {
            t.as_object_mut().unwrap().remove("id");
        }
        s.restore(&old).expect("restored");
        assert_eq!(
            (s.tracks[0].id.as_str(), s.tracks[1].id.as_str()),
            ("track1", "track2")
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn event_takes_keep_every_revision_and_play_their_best_render() {
        use crate::performance::{Ev, Playing};
        let dir = std::env::temp_dir().join(format!("varimu_events_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let mut s = Session::new(dir.clone(), 1000, TransportSettings::default());
        let perf = Performance {
            device: "tube_voice".into(),
            quality: Quality::Draft1x,
            rate: 1000,
            values: Vec::new(),
            playing: Playing::default(),
            gain: 1.0,
            noise: false,
            start_note: 57,
            start_low: false,
            events: vec![
                (
                    120,
                    Ev::On {
                        note: 60,
                        velocity: 90,
                    },
                ),
                (300, Ev::Off { note: 60 }),
            ],
            knobs: Vec::new(),
            knobs_applied: true,
            end: 900,
        };
        let rec = Recorded {
            start: 500,
            latency: 20,
            samples: vec![0.25; 400],
            right: None,
            performance: Some((Arc::new(perf.clone()), 100)),
        };
        let id = s
            .add_take_heard(0, rec, "tube_voice", Monitor::Device)
            .expect("saved");
        let k = s.tracks[0].active_take().unwrap();
        // The performance ends with the take; the take plays its audio as heard.
        assert_eq!((k.len(), k.events.as_ref().unwrap().perf.end), (400, 500));
        assert_eq!(k.sound(false).2, Plays::Heard);
        let before = s.state();
        // An edit: a new revision, stale until it is rendered.
        let mut notes = k.events.as_ref().unwrap().perf.notes();
        notes[0].note = 62;
        let edited = k.events.as_ref().unwrap().perf.edited(&notes, None);
        assert_eq!(s.revise(0, 0, edited).expect("revised"), 1);
        assert!(dir.join("takes").join(&id).join("events.1.json").is_file());
        assert_eq!(
            s.tracks[0].active_take().unwrap().sound(false).2,
            Plays::Stale
        );
        assert!(s.tracks[0].active_take().unwrap().needs_render(false));
        // The proxy's stand-in plays until it's rendered, and doesn't count as a render.
        s.attach_proxy(&id, 1, &vec![0.1; 500]);
        let k = s.tracks[0].active_take().unwrap();
        assert_eq!(k.sound(false).2, Plays::Proxy);
        assert_eq!(k.sound(false).0.len(), 400);
        assert!(k.has_proxy() && !k.has_render(Quality::Draft1x) && k.needs_render(false));
        s.attach_render(&id, 1, Quality::Draft1x, &vec![0.5; 500], None);
        let k = s.tracks[0].active_take().unwrap();
        assert_eq!(k.sound(false).2, Plays::Render(Quality::Draft1x));
        assert!(!k.needs_render(false));
        assert_eq!(k.sound(false).0.len(), 400); // from the take's first sample
        s.attach_render(&id, 1, Quality::Production, &vec![0.75; 500], None);
        let k = s.tracks[0].active_take().unwrap();
        assert_eq!(k.sound(false).2, Plays::Render(Quality::Production));
        assert_eq!(k.sound(true).2, Plays::Render(Quality::Draft1x));
        // Undo: revision 0 again, its renders kept for a redo.
        let after = s.state();
        s.restore(&before).expect("restored");
        let k = s.tracks[0].active_take().unwrap();
        assert_eq!(
            (k.events.as_ref().unwrap().rev, k.sound(false).2),
            (0, Plays::Heard)
        );
        assert_eq!(k.events.as_ref().unwrap().perf.notes()[0].note, 60);
        s.restore(&after).expect("redone");
        let k = s.tracks[0].active_take().unwrap();
        assert_eq!(k.sound(false).2, Plays::Render(Quality::Production));
        // Saved and loaded: the revision playing (renders are found again by the view).
        let u = Session::load(&dir).expect("loads");
        let k = u.tracks[0].active_take().unwrap();
        let e = k.events.as_ref().unwrap();
        assert_eq!((e.rev, e.from, e.monitor), (1, 100, Monitor::Device));
        assert_eq!(e.perf.notes()[0].note, 62);
        assert_eq!(k.audio.len(), 400);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn an_old_sessions_start_bar_is_its_cursor_and_markers_are_kept() {
        let mut v = json!({
            "rate": 48_000,
            "transport": {"bpm": 120.0, "start_bar": 3},
            "tracks": [],
        });
        let t = transport_from(&v["transport"], 48_000);
        assert_eq!(t.cursor, 2 * 4 * 24_000);
        assert_eq!((t.snap, t.return_to_cursor), (Snap::Beat, true));
        let mut s = Session::new(
            PathBuf::from("unused"),
            48_000,
            TransportSettings::default(),
        );
        v["markers"] = json!([[96_000, "chorus"], [10, "intro"]]);
        s.restore(&v).expect("restored");
        assert_eq!(s.transport.cursor, 192_000);
        assert_eq!(
            s.markers
                .iter()
                .map(|m| m.name.as_str())
                .collect::<Vec<_>>(),
            vec!["intro", "chorus"]
        );
        // Saved again: the cursor and the markers as they are.
        let state = s.state();
        assert_eq!(state["transport"]["cursor"], json!(192_000));
        assert_eq!(state["markers"][1], json!([96_000, "chorus"]));
    }

    #[test]
    fn a_deleted_takes_id_is_never_reused() {
        let dir = std::env::temp_dir().join(format!("varimu_ids_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let rec = |v: f32| Recorded {
            start: 0,
            latency: 0,
            samples: vec![v; 50],
            right: None,
            performance: None,
        };
        let mut s = Session::new(dir.clone(), 1000, TransportSettings::default());
        s.add_take(0, rec(0.1), "x").expect("saved");
        s.tracks[0].takes.clear();
        s.tracks[0].active = None;
        s.add_take(0, rec(0.2), "x").expect("saved");
        assert_eq!(s.tracks[0].takes[0].id, "t0002");
        // A session opened afresh (nothing known) still skips the folders on disk.
        s.save().expect("saved");
        let mut u = Session::load(&dir).expect("loads");
        u.tracks[0].takes.clear();
        u.add_take(0, rec(0.3), "x").expect("saved");
        assert_eq!(u.tracks[0].takes[0].id, "t0003");
        let first = crate::audio::decode(&dir.join("takes/t0001/draft.wav")).expect("kept");
        assert_eq!(first.mono()[0] as f32, 0.1);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn overviews_outline_any_range() {
        let x: Vec<f32> = (0..1000)
            .map(|i| if i == 555 { 0.9 } else { 0.0 })
            .collect();
        let o = Overview::of(&x, 100);
        assert_eq!(o.peaks.len(), 10);
        assert_eq!(o.range(500.0, 600.0), Some((0.0, 0.9)));
        assert_eq!(o.range(0.0, 500.0), Some((0.0, 0.0)));
        assert_eq!(o.range(2000.0, 3000.0), None);
    }
}
