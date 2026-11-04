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
//! stream, and the take's `position` is where it was recorded less that. Takes are never
//! replaced: a new one is added to the track's lane and made the active one.
//!
//! **The mix** is a console's: each track's active take times its fader and balance
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

use crate::print::{Slot, key_control};
use crate::transport::{ClickMode, TransportSettings};

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

/// A take in the mix: where it starts on the timeline, its samples, its gains.
#[derive(Debug, Clone)]
pub struct MixClip {
    pub start: i64,
    pub audio: Arc<Vec<f32>>,
    pub gain: (f32, f32),
}

/// What the worker plays while the transport runs, and the live device's gains.
#[derive(Debug, Clone)]
pub struct Mix {
    pub clips: Vec<MixClip>,
    pub live: (f32, f32),
}

impl Default for Mix {
    fn default() -> Mix {
        Mix {
            clips: Vec::new(),
            live: (1.0, 1.0),
        }
    }
}

impl Mix {
    /// Add the clips sounding over `[at, at + out.len())`.
    pub fn add(&self, at: i64, out: &mut [Frame]) {
        let n = out.len() as i64;
        for c in &self.clips {
            let (a, b) = (
                at.max(c.start),
                (at + n).min(c.start + c.audio.len() as i64),
            );
            for p in a..b {
                let v = c.audio[(p - c.start) as usize];
                let o = &mut out[(p - at) as usize];
                o[0] += c.gain.0 * v;
                o[1] += c.gain.1 * v;
            }
        }
    }
}

/// A finished recording from the worker: the stream position of its first sample, the
/// latency to take off, the samples.
#[derive(Debug, Clone, PartialEq)]
pub struct Recorded {
    pub start: i64,
    pub latency: i64,
    pub samples: Vec<f32>,
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
}

#[derive(Debug)]
struct Active {
    start: i64,
    latency: i64,
    chunks: Vec<Vec<f32>>,
    len: usize,
}

impl Recorder {
    pub fn new(rate: u32) -> Recorder {
        Recorder {
            armed: false,
            chunk: rate.max(1) as usize,
            active: None,
            finished: std::collections::VecDeque::new(),
        }
    }

    /// The device's output `raw` for positions `at..`: kept from `record_from` on while
    /// armed (`latency`: the queue and output device now, in samples).
    pub fn capture(&mut self, at: i64, raw: &[f32], record_from: i64, latency: i64) {
        if !self.armed {
            self.stop();
            return;
        }
        if self
            .active
            .as_ref()
            .is_some_and(|a| a.start + a.len as i64 != at)
        {
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
            len: 0,
        });
        let mut x = &raw[from..];
        while !x.is_empty() {
            if a.chunks.last().is_none_or(|c| c.len() == chunk) {
                a.chunks.push(Vec::with_capacity(chunk));
            }
            let c = a.chunks.last_mut().expect("a chunk");
            let k = (chunk - c.len()).min(x.len());
            c.extend_from_slice(&x[..k]);
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
            self.finished.push_back(Recorded {
                start: a.start,
                latency: a.latency,
                samples,
            });
        }
    }

    /// The oldest finished take not collected yet.
    pub fn take_finished(&mut self) -> Option<Recorded> {
        self.finished.pop_front()
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

/// One recorded take.
#[derive(Debug, Clone)]
pub struct Take {
    pub id: String,
    /// The timeline sample of its first sample (latency compensated).
    pub position: i64,
    pub latency: i64,
    /// The device it was played on (`panel::Device::id`, or a label).
    pub device: String,
    pub recorded_unix_s: u64,
    pub code: String,
    pub audio: Arc<Vec<f32>>,
    pub overview: Arc<Overview>,
    /// A take rendered from another through a chain of inserts (Render): the take, the
    /// inserts, the quality and the code version (None: recorded).
    pub rendered_from: Option<Value>,
}

impl Take {
    pub fn end(&self) -> i64 {
        self.position + self.audio.len() as i64
    }
}

/// A track's chain printed on one of its takes: what it was made from (the chain's
/// signature, [`Track::chain_signature`]), the take, the audio (from the take's position,
/// the tail past its end) and its outline.
#[derive(Debug, Clone)]
pub struct Printed {
    pub signature: String,
    pub take: String,
    pub audio: Arc<Vec<f32>>,
    pub overview: Arc<Overview>,
    /// Each insert's print, in order (the inserts not bypassed): the input of the one
    /// after it, which an audition plays into it.
    pub stages: Vec<Arc<Vec<f32>>>,
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

/// A track: its takes (the lane), the one playing, its channel strip.
#[derive(Debug, Clone)]
pub struct Track {
    /// Its id (saved; what a key route names: it survives renaming and reordering).
    pub id: String,
    pub name: String,
    pub takes: Vec<Take>,
    pub active: Option<usize>,
    pub volume_db: f64,
    pub pan: f64,
    pub mute: bool,
    pub solo: bool,
    /// Every take shown, stacked under the active one (a view setting, saved).
    pub show_takes: bool,
    /// Its inserts, in signal order.
    pub inserts: Vec<Slot>,
    /// The chain's latest print (not saved: found again in the cache).
    pub printed: Option<Printed>,
}

impl Track {
    pub fn new(name: &str) -> Track {
        Track {
            id: new_track_id(),
            name: name.to_string(),
            takes: Vec::new(),
            active: None,
            volume_db: 0.0,
            pan: 0.0,
            mute: false,
            solo: false,
            show_takes: false,
            inserts: Vec::new(),
            printed: None,
        }
    }

    pub fn active_take(&self) -> Option<&Take> {
        self.active.and_then(|i| self.takes.get(i))
    }

    pub fn gains(&self) -> (f32, f32) {
        balance(self.volume_db, self.pan)
    }

    /// What the chain's print of the active take is made from (the take, the rate, every
    /// insert that isn't bypassed); None when there's nothing to print.
    pub fn chain_signature(&self, rate: u32) -> Option<String> {
        let k = self.active_take()?;
        let on: Vec<Value> = self
            .inserts
            .iter()
            .filter(|s| !s.bypass)
            .map(Slot::to_json)
            .collect();
        (!on.is_empty()).then(|| format!("{}|{rate}|{}", k.id, Value::Array(on)))
    }

    /// The audio the mix plays and where it starts: the print of the active take (stale
    /// or not) while there's a chain to print, else the take.
    pub fn playing(&self, rate: u32) -> Option<(i64, &Arc<Vec<f32>>, bool)> {
        let k = self.active_take()?;
        if self.chain_signature(rate).is_some()
            && let Some(p) = self.printed.as_ref().filter(|p| p.take == k.id)
        {
            return Some((k.position, &p.audio, true));
        }
        Some((k.position, &k.audio, false))
    }

    /// Whether the print playing is the chain as it is now.
    pub fn print_current(&self, rate: u32) -> bool {
        match self.chain_signature(rate) {
            None => true,
            Some(s) => self.printed.as_ref().is_some_and(|p| p.signature == s),
        }
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
    /// Every take loaded or recorded in this session, by id, deleted ones too: a state
    /// restored by undo takes them from here before reading their folders.
    known: HashMap<String, Take>,
}

impl Session {
    pub fn new(dir: PathBuf, rate: u32, transport: TransportSettings) -> Session {
        Session {
            dir,
            rate,
            transport,
            tracks: vec![Track::new("Track 1")],
            armed: Some(0),
            known: HashMap::new(),
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
            .filter(|t| audible(t))
            .filter_map(|t| {
                t.playing(self.rate).map(|(start, audio, _)| MixClip {
                    start,
                    audio: audio.clone(),
                    gain: t.gains(),
                })
            })
            .collect();
        let live = self
            .armed
            .and_then(|i| self.tracks.get(i))
            .map_or(
                (1.0, 1.0),
                |t| if audible(t) { t.gains() } else { (0.0, 0.0) },
            );
        Mix { clips, live }
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
        if let Some((start, audio, _)) = track.playing(self.rate)
            && let Some(i) = m
                .clips
                .iter()
                .position(|c| c.start == start && Arc::ptr_eq(&c.audio, audio))
        {
            m.clips.remove(i);
        }
        m.live = if audible { track.gains() } else { (0.0, 0.0) };
        m
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
        let pos = track.active_take()?.position;
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

    /// What track `i` plays, as a key hears it: its active take, where it sits, its chain.
    fn plays_signature(&self, i: usize, seen: &mut Vec<usize>) -> String {
        match self.tracks[i].active_take() {
            None => "silence".to_string(),
            Some(k) => format!(
                "{}@{}[{}]",
                k.id,
                k.position,
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
    /// active take's position over the take and the slot's tail, silence where it has
    /// none; None without a route (or a device without a key input, or a route to itself).
    pub fn sidechain(&self, t: usize, slot: &Slot) -> Option<Arc<Vec<f32>>> {
        key_control(slot)?;
        let take = self.tracks.get(t)?.active_take()?;
        let i = self.track_index(&slot.key.as_ref()?.track)?;
        if i == t {
            return None;
        }
        let n = take.audio.len() + (slot.tail_s.max(0.0) * self.rate as f64).round() as usize;
        let mut out = vec![0f32; n];
        if let Some((start, audio, _)) = self.tracks[i].playing(self.rate) {
            for (j, o) in out.iter_mut().enumerate() {
                let p = take.position + j as i64 - start;
                if p >= 0
                    && let Some(&v) = audio.get(p as usize)
                {
                    *o = v;
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
        let pos = self
            .tracks
            .get(t)
            .and_then(Track::active_take)
            .map(|k| k.position);
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

    /// Where the last take ends (0: none).
    pub fn end(&self) -> i64 {
        self.tracks
            .iter()
            .flat_map(|t| t.takes.iter().map(Take::end))
            .max()
            .unwrap_or(0)
    }

    fn next_id(&self) -> String {
        let n = self
            .tracks
            .iter()
            .flat_map(|t| &t.takes)
            .filter_map(|k| k.id.strip_prefix('t').and_then(|s| s.parse::<u32>().ok()))
            .max()
            .unwrap_or(0);
        format!("t{:04}", n + 1)
    }

    /// A recording made into a take of `track` (now its active one), its files written.
    pub fn add_take(&mut self, track: usize, rec: Recorded, device: &str) -> Result<(), String> {
        let id = self.next_id();
        let take = Take {
            id,
            position: rec.start - rec.latency,
            latency: rec.latency,
            device: device.to_string(),
            recorded_unix_s: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |d| d.as_secs()),
            code: circuitsim::SOURCE_HASH.to_string(),
            overview: Arc::new(Overview::of(&rec.samples, OVERVIEW_BIN)),
            audio: Arc::new(rec.samples),
            rendered_from: None,
        };
        write_take(&self.dir, &take, self.rate)?;
        self.known.insert(take.id.clone(), take.clone());
        let t = self.tracks.get_mut(track).ok_or("no such track")?;
        t.takes.push(take);
        t.active = Some(t.takes.len() - 1);
        self.save()
    }

    /// A track's chain rendered into a new take of `track` (now its active one) at
    /// `position`, its files written; `from` says what it was rendered from (the take, the
    /// inserts, the quality). Returns its id.
    pub fn add_rendered_take(
        &mut self,
        track: usize,
        samples: Vec<f32>,
        position: i64,
        from: Value,
    ) -> Result<String, String> {
        let id = self.next_id();
        let take = Take {
            id: id.clone(),
            position,
            latency: 0,
            device: format!("render of {}", from["take"].as_str().unwrap_or("?")),
            recorded_unix_s: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |d| d.as_secs()),
            code: circuitsim::SOURCE_HASH.to_string(),
            overview: Arc::new(Overview::of(&samples, OVERVIEW_BIN)),
            audio: Arc::new(samples),
            rendered_from: Some(from),
        };
        write_take(&self.dir, &take, self.rate)?;
        self.known.insert(id.clone(), take.clone());
        let t = self.tracks.get_mut(track).ok_or("no such track")?;
        t.takes.push(take);
        t.active = Some(t.takes.len() - 1);
        self.save()?;
        Ok(id)
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
                    "active": t.active_take().map(|k| k.id.clone()),
                })
            })
            .collect();
        json!({
            "version": 1,
            "rate": self.rate,
            "transport": transport_json(&self.transport),
            "tracks": tracks,
            "armed": self.armed,
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
                track.takes.push(take);
            }
            let active = t["active"].as_str();
            track.active = track
                .takes
                .iter()
                .position(|k| Some(k.id.as_str()) == active);
            tracks.push(track);
        }
        self.armed = v["armed"]
            .as_u64()
            .map(|i| i as usize)
            .filter(|&i| i < tracks.len());
        self.rate = rate;
        self.transport = transport_from(&v["transport"]);
        // Prints carry over to the restored tracks: the one made from the same chain on the
        // same take, else any print of that take (stale until it is printed again).
        let prints: Vec<Printed> = self
            .tracks
            .iter()
            .filter_map(|t| t.printed.clone())
            .collect();
        self.tracks = tracks;
        for i in 0..self.tracks.len() {
            let sig = self.chain_signature(i);
            let t = &mut self.tracks[i];
            let Some(k) = t.active_take() else {
                continue;
            };
            let same = prints.iter().find(|p| Some(&p.signature) == sig.as_ref());
            t.printed = same
                .or_else(|| prints.iter().find(|p| p.take == k.id))
                .cloned();
        }
        Ok(())
    }

    pub fn save(&self) -> Result<(), String> {
        std::fs::create_dir_all(&self.dir).map_err(|e| format!("{}: {e}", self.dir.display()))?;
        let p = self.dir.join("session.json");
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
            known: HashMap::new(),
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
        "start_bar": s.start_bar,
        "left_beat": s.left_beat,
        "right_beat": s.right_beat,
        "loop_on": s.loop_on,
    })
}

pub fn transport_from(t: &Value) -> TransportSettings {
    let d = TransportSettings::default();
    let u = |k: &str, def: u32| t[k].as_u64().map_or(def, |x| x as u32);
    TransportSettings {
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
        start_bar: t["start_bar"].as_i64().unwrap_or(d.start_bar),
        left_beat: t["left_beat"].as_i64().unwrap_or(d.left_beat),
        right_beat: t["right_beat"].as_i64().unwrap_or(d.right_beat),
        loop_on: t["loop_on"].as_bool().unwrap_or(d.loop_on),
    }
    .clamped()
}

fn write_take(dir: &Path, k: &Take, rate: u32) -> Result<(), String> {
    let d = dir.join("takes").join(&k.id);
    std::fs::create_dir_all(&d).map_err(|e| format!("{}: {e}", d.display()))?;
    let x: Vec<f64> = k.audio.iter().map(|&v| v as f64).collect();
    crate::audio::write_wav(&d.join("draft.wav"), &x, rate)?;
    let v = json!({
        "id": k.id,
        "position": k.position,
        "latency": k.latency,
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
    let w = crate::audio::decode(&d.join("draft.wav"))?;
    if w.rate != rate {
        return Err(format!(
            "{}: {} Hz in a {rate} Hz session",
            d.display(),
            w.rate
        ));
    }
    let audio: Vec<f32> = w.mono().iter().map(|&v| v as f32).collect();
    Ok(Take {
        id: id.to_string(),
        position: v["position"].as_i64().unwrap_or(0),
        latency: v["latency"].as_i64().unwrap_or(0),
        device: v["device"].as_str().unwrap_or("").to_string(),
        recorded_unix_s: v["recorded_unix_s"].as_u64().unwrap_or(0),
        code: v["code"].as_str().unwrap_or("").to_string(),
        overview: Arc::new(Overview::of(&audio, OVERVIEW_BIN)),
        audio: Arc::new(audio),
        rendered_from: v.get("rendered_from").filter(|f| !f.is_null()).cloned(),
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
            r.capture(at, &raw, 0, 77);
            at += 300;
        }
        let (start, latency, len, tail) = r.tail(1000).expect("recording");
        assert_eq!((start, latency, len), (0, 77, expected.len()));
        assert_eq!(tail, expected[1000..]);
        r.armed = false;
        r.capture(at, &[0.0; 300], 0, 77);
        let rec = r.take_finished().expect("a take");
        assert_eq!(rec.start, 0);
        assert_eq!(rec.samples, expected);
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
                r.capture(pos, &vec![pos as f32; len], 100, 5);
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
            device: String::new(),
            recorded_unix_s: 0,
            code: String::new(),
            audio: Arc::new(vec![v; 10]),
            overview: Arc::new(Overview::default()),
            rendered_from: None,
        };
        s.tracks[0].takes.push(take(5, 1.0));
        s.tracks[0].active = Some(0);
        let mut t2 = Track::new("2");
        t2.takes.push(take(0, 0.5));
        t2.active = Some(0);
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
    fn a_session_survives_a_save_and_load() {
        let dir = std::env::temp_dir().join(format!("varimu_session_test_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let mut s = Session::new(dir.clone(), 48_000, TransportSettings::default());
        s.transport.bpm = 93.5;
        let rec = Recorded {
            start: 1000,
            latency: 240,
            samples: (0..4800).map(|i| (i as f32 * 0.01).sin() * 0.5).collect(),
        };
        s.add_take(0, rec.clone(), "tube_synth").expect("saved");
        s.tracks.push(Track::new("Bass"));
        s.tracks[1].pan = -0.5;
        s.add_take(1, rec, "fender_5e3").expect("saved");
        let t = Session::load(&dir).expect("loads");
        assert_eq!(t.transport.bpm, 93.5);
        assert_eq!(t.tracks.len(), 2);
        assert_eq!(t.tracks[1].pan, -0.5);
        let (a, b) = (&s.tracks[0].takes[0], &t.tracks[0].takes[0]);
        assert_eq!(b.position, 760);
        assert_eq!(a.audio, b.audio); // float32 on disk: bit for bit
        assert_eq!(
            t.tracks[1].active_take().map(|k| k.id.as_str()),
            Some("t0002")
        );
        // A take moved on the timeline stays where it was moved.
        let mut t = t;
        t.tracks[0].takes[0].position = 48_000;
        t.save().expect("saved");
        let u = Session::load(&dir).expect("loads");
        assert_eq!(u.tracks[0].takes[0].position, 48_000);
        let _ = std::fs::remove_dir_all(&dir);
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
            take: "t0001".into(),
            audio: Arc::new(vec![0.7; 150]),
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
            .add_rendered_take(0, vec![0.25; 120], pos, from.clone())
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
        s.tracks[1].takes[0].position = 130;
        let moved = s.chain_signature(0).unwrap();
        assert_ne!(sig, moved, "the kick moved");
        s.tracks[1].inserts.push(Slot::new("pultec_eqp1a"));
        let chained = s.chain_signature(0).unwrap();
        assert_ne!(moved, chained, "the kick has an insert");
        // ... and waits for the kick's print before printing.
        assert!(!s.keys_ready(0));
        s.tracks[1].printed = Some(Printed {
            signature: s.chain_signature(1).unwrap(),
            take: s.tracks[1].takes[0].id.clone(),
            audio: Arc::new(vec![0.5; 25]),
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
