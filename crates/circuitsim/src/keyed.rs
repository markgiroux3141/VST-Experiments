//! A medium played by keys (the Rhodes harp, `crate::harp`; the Clavinet's strings,
//! `crate::clavinet`): one voice per key, struck by note events, the voices' outputs summed
//! per channel and decimated to the step rate. The machinery the media share:
//!
//! **One way.** The voices sense nothing in the circuit, so they render ahead: up to the
//! last sample whose events are known ([`Medium::known_until`]), in chunks of up to
//! [`CHUNK`] steps, voice by voice. An event lands at the sample it is queued for, or at
//! the first sample not yet rendered if it comes too late.
//!
//! **Threads.** A chunk with more than a few voices awake renders on worker threads beside
//! the calling one, each taking voices until none is left; the voices are summed in their
//! order afterwards, so the result is the same bit for bit on any number of threads.
//!
//! **Rates.** The voices run at `k` internal samples per step; the internal outputs are
//! decimated to the step rate by [`crate::partition::Decimator`]'s taps (none at k = 1).

use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Condvar, Mutex};

use crate::media::NoteEvent;

/// Base samples rendered at a time when the events are known that far.
pub const CHUNK: usize = 256;
/// Voices awake (or struck) up to which a chunk renders on the calling thread alone, by
/// default ([`Medium::set_inline_voices`]).
const INLINE_VOICES: usize = 4;

/// One key's voice.
pub trait KeyVoice: Send + 'static {
    /// What every voice reads (shared, read-only).
    type Ctx: Send + Sync + 'static;
    /// Asleep: silent until an event of its own wakes it.
    fn asleep(&self) -> bool;
    /// An event at the current sample: its key's, or every key's (the pedal, pressure).
    fn event(&mut self, ev: NoteEvent, ctx: &Self::Ctx);
    /// Add internal samples `from..to` of its outputs into `buf`: channel c's sample i at
    /// `c * n + i`.
    fn render(&mut self, buf: &mut [f64], n: usize, from: usize, to: usize, ctx: &Self::Ctx);
    /// Stop sounding at once (asleep from now on), for another voice: a medium with a cap
    /// on its voices awake ([`Medium::set_max_awake`]). Nothing by default.
    fn silence(&mut self) {}
}

/// A voice and the internal samples it rendered in the chunk (`silent`: none, asleep).
#[derive(Debug)]
struct Slot<V> {
    voice: V,
    buf: Vec<f64>,
    silent: bool,
}

/// A chunk to render: its internal samples and its events (internal offset, event).
#[derive(Debug, Default)]
struct Job {
    round: u64,
    n: usize,
    events: Arc<Vec<(usize, NoteEvent)>>,
}

/// Whether `ev` is note `note`'s own (a key down or up for it).
fn own(ev: &NoteEvent, note: u8) -> bool {
    match *ev {
        NoteEvent::On { note: q, .. } | NoteEvent::Off { note: q } => q == note,
        _ => false,
    }
}

/// Whether `ev` goes to every voice.
fn broadcast(ev: &NoteEvent) -> bool {
    matches!(ev, NoteEvent::Pedal { .. } | NoteEvent::Pressure { .. })
}

/// What every thread rendering voices sees.
struct Shared<V: KeyVoice> {
    slots: Vec<Mutex<Slot<V>>>,
    notes: Vec<u8>,
    channels: usize,
    ctx: V::Ctx,
    job: Mutex<Job>,
    wake: Condvar,
    /// The next voice to take, the voices rendered, the workers inside a job.
    next: AtomicUsize,
    done: AtomicUsize,
    active: AtomicUsize,
    stop: AtomicBool,
}

impl<V: KeyVoice> Shared<V> {
    /// Render voice i's share of the job into its buffer.
    fn render_slot(&self, i: usize, job: &Job) {
        let mut slot = self.slots[i].lock().expect("voice");
        let Slot { voice, buf, silent } = &mut *slot;
        let note = self.notes[i];
        let mine = |ev: &NoteEvent| own(ev, note) || broadcast(ev);
        let touched = job.events.iter().any(|(_, ev)| own(ev, note));
        if voice.asleep() && !touched {
            // Asleep through the chunk: only every key's events move it.
            for (_, ev) in job.events.iter() {
                if broadcast(ev) {
                    voice.event(*ev, &self.ctx);
                }
            }
            *silent = true;
            return;
        }
        *silent = false;
        let n = job.n;
        buf.clear();
        buf.resize(n * self.channels, 0.0);
        let mut t = 0;
        for &(at, ev) in job.events.iter() {
            if !mine(&ev) {
                continue;
            }
            voice.render(buf, n, t, at, &self.ctx);
            t = at;
            voice.event(ev, &self.ctx);
        }
        voice.render(buf, n, t, n, &self.ctx);
    }

    /// Take voices until none is left.
    fn take(&self, job: &Job) {
        loop {
            let i = self.next.fetch_add(1, Ordering::AcqRel);
            if i >= self.slots.len() {
                return;
            }
            self.render_slot(i, job);
            self.done.fetch_add(1, Ordering::AcqRel);
        }
    }
}

/// A worker: each new job's voices taken until none is left.
fn worker<V: KeyVoice>(sh: Arc<Shared<V>>) {
    let mut seen = 0;
    loop {
        let (round, n, events) = {
            let mut job = sh.job.lock().expect("job");
            while job.round == seen && !sh.stop.load(Ordering::Acquire) {
                job = sh.wake.wait(job).expect("job");
            }
            if sh.stop.load(Ordering::Acquire) {
                return;
            }
            sh.active.fetch_add(1, Ordering::AcqRel);
            (job.round, job.n, job.events.clone())
        };
        seen = round;
        sh.take(&Job { round, n, events });
        sh.active.fetch_sub(1, Ordering::AcqRel);
    }
}

/// Workers beside the calling thread: none with few cores; at most three, leaving four
/// logical cores to the circuit's own threads (as the tape's stream does).
pub fn workers() -> usize {
    std::thread::available_parallelism()
        .map_or(1, |n| n.get())
        .saturating_sub(4)
        .min(3)
}

/// Voices beside the circuit at step rate `fs`, `k` internal samples a step (see the
/// module docs).
pub struct Medium<V: KeyVoice> {
    pub k: usize,
    fs: f64,
    channels: usize,
    shared: Arc<Shared<V>>,
    threads: Vec<std::thread::JoinHandle<()>>,
    /// MIDI note -> voice.
    by_note: Vec<Option<usize>>,
    pedal: bool,
    /// Voices awake after the last chunk (the chunk renders on the workers only past a
    /// few).
    awake: usize,
    /// Events by the step they land at (queued in order).
    events: VecDeque<(usize, NoteEvent)>,
    /// The last step whose events are all queued (None: none yet).
    known: Option<usize>,
    /// The next push's step.
    pos: usize,
    /// Steps rendered: the internal outputs through k * rendered.
    rendered: usize,
    /// Decimated values for steps pos + 1 ..= rendered, `channels` a step.
    out: VecDeque<f64>,
    taps: Vec<f64>,
    /// Per channel the last taps.len() internal samples, newest at `ring_at - 1`.
    ring: Vec<Vec<f64>>,
    ring_at: usize,
    chunk: Vec<f64>,
    /// Every internal sample rendered, per channel (tests: `keep_raw`).
    raw: Option<Vec<Vec<f64>>>,
    /// At most this many voices awake ([`Medium::set_max_awake`]); per voice whether its
    /// key is down and when it was last struck (a count of strikes), from the events.
    max_awake: Option<usize>,
    /// Voices awake (or struck) up to which a chunk renders on the calling thread alone.
    inline_voices: usize,
    held: Vec<bool>,
    struck_at: Vec<u64>,
    strikes: u64,
}

impl<V: KeyVoice> std::fmt::Debug for Medium<V> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("keyed::Medium")
            .field("k", &self.k)
            .field("fs", &self.fs)
            .field("channels", &self.channels)
            .field("pos", &self.pos)
            .field("threads", &self.threads.len())
            .finish()
    }
}

impl<V: KeyVoice> Medium<V> {
    /// `voices` (MIDI note, voice) at `k` internal samples a step of rate `fs`, with
    /// `channels` outputs and `n` worker threads (the result is the same with any number).
    pub fn new(
        voices: Vec<(u8, V)>,
        ctx: V::Ctx,
        fs: f64,
        k: usize,
        channels: usize,
        n: usize,
    ) -> Medium<V> {
        let mut by_note = vec![None; 128];
        for (i, (note, _)) in voices.iter().enumerate() {
            by_note[*note as usize] = Some(i);
        }
        let notes: Vec<u8> = voices.iter().map(|(n, _)| *n).collect();
        let n_voices = notes.len();
        let shared = Arc::new(Shared {
            slots: voices
                .into_iter()
                .map(|(_, voice)| {
                    Mutex::new(Slot {
                        voice,
                        buf: Vec::new(),
                        silent: true,
                    })
                })
                .collect(),
            notes,
            channels,
            ctx,
            job: Mutex::new(Job::default()),
            wake: Condvar::new(),
            next: AtomicUsize::new(0),
            done: AtomicUsize::new(0),
            active: AtomicUsize::new(0),
            stop: AtomicBool::new(false),
        });
        let threads = (0..n)
            .filter_map(|i| {
                let sh = shared.clone();
                std::thread::Builder::new()
                    .name(format!("keys {i}"))
                    .spawn(move || worker(sh))
                    .ok()
            })
            .collect();
        let taps = if k > 1 {
            crate::partition::Decimator::taps(k)
        } else {
            vec![1.0]
        };
        Medium {
            k,
            fs,
            channels,
            shared,
            threads,
            by_note,
            pedal: false,
            awake: 0,
            events: VecDeque::new(),
            known: None,
            pos: 0,
            rendered: 0,
            out: VecDeque::new(),
            ring: vec![vec![0.0; taps.len()]; channels],
            taps,
            ring_at: 0,
            chunk: Vec::new(),
            raw: None,
            max_awake: None,
            inline_voices: INLINE_VOICES,
            held: vec![false; n_voices],
            struck_at: vec![0; n_voices],
            strikes: 0,
        }
    }

    /// At most `n` voices awake (None: no cap): a chunk whose strikes would wake more
    /// silences ([`KeyVoice::silence`]) as many of the others at its start, keys up before
    /// keys down, each the one struck longest ago. Decided on the calling thread from the
    /// voices' state and the events, so the same on any number of threads.
    pub fn set_max_awake(&mut self, n: Option<usize>) {
        self.max_awake = n;
    }

    /// Render a chunk on the calling thread alone while at most `n` voices are awake or
    /// struck in it (4 by default: cheap voices; a costly voice wants 1). The result is the
    /// same either way.
    pub fn set_inline_voices(&mut self, n: usize) {
        self.inline_voices = n;
    }

    /// The cap on the voices awake: silence the ones a chunk's strikes `evs` push over it,
    /// then note the chunk's keys down and up.
    fn steal(&mut self, evs: &[(usize, NoteEvent)]) {
        let Some(cap) = self.max_awake else { return };
        let sh = &self.shared;
        let n = sh.slots.len();
        let mut struck = vec![false; n];
        for (_, ev) in evs {
            if let NoteEvent::On { note, .. } = *ev
                && let Some(i) = self.voice_of(note)
            {
                struck[i] = true;
            }
        }
        if struck.iter().any(|&s| s) {
            let awake: Vec<bool> = sh
                .slots
                .iter()
                .map(|s| !s.lock().expect("voice").voice.asleep())
                .collect();
            let total = (0..n).filter(|&i| awake[i] || struck[i]).count();
            if total > cap {
                let mut others: Vec<usize> = (0..n).filter(|&i| awake[i] && !struck[i]).collect();
                others.sort_by_key(|&i| (self.held[i], self.struck_at[i]));
                for &i in others.iter().take(total - cap) {
                    sh.slots[i].lock().expect("voice").voice.silence();
                }
            }
        }
        for (_, ev) in evs {
            match *ev {
                NoteEvent::On { note, .. } => {
                    if let Some(i) = self.voice_of(note) {
                        self.strikes += 1;
                        self.held[i] = true;
                        self.struck_at[i] = self.strikes;
                    }
                }
                NoteEvent::Off { note } => {
                    if let Some(i) = self.voice_of(note) {
                        self.held[i] = false;
                    }
                }
                _ => {}
            }
        }
    }

    /// The shared context the voices read.
    pub fn ctx(&self) -> &V::Ctx {
        &self.shared.ctx
    }

    /// Keep every internal sample rendered from now on ([`Medium::raw`]; tests).
    pub fn keep_raw(&mut self) {
        self.raw = Some(vec![Vec::new(); self.channels]);
    }

    /// Channel c's internal samples kept since [`Medium::keep_raw`].
    pub fn raw(&self, c: usize) -> &[f64] {
        self.raw.as_ref().map_or(&[], |r| &r[c])
    }

    /// The decimation's delay in steps.
    pub fn delay_steps(&self) -> f64 {
        (self.taps.len() - 1) as f64 / 2.0 / self.k as f64
    }

    /// The next push's step (events for it and later land on time).
    pub fn position(&self) -> usize {
        self.pos
    }

    /// An event at step `at` (in order with the others queued; one for a step already
    /// rendered lands at the first one that isn't). A key down at velocity 0 is a key up.
    pub fn queue(&mut self, at: usize, ev: NoteEvent) {
        let ev = match ev {
            NoteEvent::On { note, velocity: 0 } => NoteEvent::Off { note },
            e => e,
        };
        self.events.push_back((at, ev));
    }

    /// Every event up to step `at` is queued (`usize::MAX`: all of them).
    pub fn known_until(&mut self, at: usize) {
        self.known = Some(self.known.map_or(at, |k| k.max(at)));
    }

    /// The outputs at the next step (the push at step p gives step p + 1's), into `y`
    /// (`channels` long).
    pub fn push_into(&mut self, y: &mut [f64]) {
        let p = self.pos;
        if self.rendered <= p {
            let ahead = match self.known {
                Some(k) if k >= p => (k - p).min(CHUNK - 1),
                _ => 0,
            };
            self.render(p + 1 + ahead);
        }
        self.pos += 1;
        for v in y.iter_mut().take(self.channels) {
            *v = self.out.pop_front().expect("rendered ahead");
        }
    }

    /// Render steps `rendered .. end` (their events applied as they land).
    fn render(&mut self, end: usize) {
        let start = self.rendered;
        let k = self.k;
        let n = (end - start) * k;
        // The chunk's events (late ones at its start), at their internal offsets.
        let mut evs = Vec::new();
        while let Some(&(at, ev)) = self.events.front() {
            if at >= end {
                break;
            }
            self.events.pop_front();
            evs.push((at.saturating_sub(start) * k, ev));
        }
        self.steal(&evs);
        let struck = evs
            .iter()
            .filter(|e| matches!(e.1, NoteEvent::On { .. }))
            .count();
        let sh = &self.shared;
        let job = Job {
            round: 0,
            n,
            events: Arc::new(evs),
        };
        if self.threads.is_empty() || self.awake + struck <= self.inline_voices {
            for i in 0..sh.slots.len() {
                sh.render_slot(i, &job);
            }
        } else {
            // Published once no worker is inside the last job (one that woke late must not
            // take from this one with the last one's events).
            loop {
                let mut j = sh.job.lock().expect("job");
                if sh.active.load(Ordering::Acquire) == 0 {
                    sh.next.store(0, Ordering::Release);
                    sh.done.store(0, Ordering::Release);
                    j.round += 1;
                    j.n = n;
                    j.events = job.events.clone();
                    sh.wake.notify_all();
                    break;
                }
                drop(j);
                std::hint::spin_loop();
            }
            sh.take(&job);
            while sh.done.load(Ordering::Acquire) < sh.slots.len() {
                std::hint::spin_loop();
            }
        }
        // The voices summed in order (the same on any number of threads).
        let c = self.channels;
        self.chunk.clear();
        self.chunk.resize(n * c, 0.0);
        let mut awake = 0;
        for slot in &sh.slots {
            let slot = slot.lock().expect("voice");
            if !slot.silent {
                for (x, b) in self.chunk.iter_mut().zip(&slot.buf) {
                    *x += b;
                }
            }
            awake += usize::from(!slot.voice.asleep());
        }
        self.awake = awake;
        for (_, ev) in job.events.iter() {
            if let NoteEvent::Pedal { down } = *ev {
                self.pedal = down;
            }
        }
        if let Some(r) = &mut self.raw {
            for (ch, rc) in r.iter_mut().enumerate() {
                rc.extend_from_slice(&self.chunk[ch * n..(ch + 1) * n]);
            }
        }
        // Decimate: one value per step and channel, at its last internal sample.
        let l = self.taps.len();
        for i in 0..n {
            for ch in 0..c {
                self.ring[ch][self.ring_at] = self.chunk[ch * n + i];
            }
            self.ring_at = (self.ring_at + 1) % l;
            if (i + 1) % k == 0 {
                for ch in 0..c {
                    let ring = &self.ring[ch];
                    let mut y = 0.0;
                    for (j, h) in self.taps.iter().enumerate() {
                        y += h * ring[(self.ring_at + l - 1 - j) % l];
                    }
                    self.out.push_back(y);
                }
            }
        }
        self.rendered = end;
    }

    /// Voices awake after the last chunk.
    pub fn sounding(&self) -> usize {
        self.awake
    }

    /// The sustain pedal's state after the last chunk.
    pub fn pedal(&self) -> bool {
        self.pedal
    }

    pub fn fs(&self) -> f64 {
        self.fs
    }

    /// Which voice plays MIDI `note` (None: no key for it).
    pub fn voice_of(&self, note: u8) -> Option<usize> {
        self.by_note.get(note as usize).copied().flatten()
    }
}

impl<V: KeyVoice> Drop for Medium<V> {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::Release);
        {
            let _j = self.shared.job.lock().expect("job");
            self.shared.wake.notify_all();
        }
        for t in self.threads.drain(..) {
            let _ = t.join();
        }
    }
}
