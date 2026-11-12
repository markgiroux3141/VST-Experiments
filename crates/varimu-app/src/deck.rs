//! The session's multitrack tape deck (docs/PERIOD_GEAR_BACKLOG.md, PG1, MT6; decision 3:
//! the deck is a property of the session, not a track insert).
//!
//! **The deck**: a four-track machine (the Ampex 300-4, `config/circuits/ampex_300_4.yaml`),
//! its four tape tracks each assigned a session track (by id) or none, a record trim per
//! tape track (the fader in front of its channel's input), its panel values and its noise.
//! An engineer records each part so its loud passages hit 0 VU: a trim is set once, when a
//! track is assigned, from the lane's loudest 8 s ([`trim_for`]: the alignment level, as an
//! insert's first trim, plus [`DRIVE_DB`]: on Scotch 202 the deck's RECORD LEVEL runs out
//! 0.54 dB short of operating level at 0 VU, so the studio fed it that much hotter).
//!
//! **A tape print** records every assigned track at once, as one pass (decision 4): each
//! track's lane (its clips as they play, before its inserts and strip; a stereo lane's mid:
//! a tape track is mono) placed on one timeline from the earliest lane's start, through the
//! deck's channels (`in`, `in2` .. `in4`), at production, in pieces run at once
//! ([`render::render_pieces_controls`] at [`PRINT_PIECES`], TAPE_SPEED_PLAN.md P3), shifted
//! back by the head distance over the speed (as a tape insert's print), each channel's line
//! out brought back to its lane's level by the trim's inverse (the deck is aligned 0 VU in to
//! 0 VU out). The Sel-Sync readouts (`sy`, `sy_2` ..: the record heads' playback, MT4) are
//! kept beside it, advanced by the head distance as the playback is, for later overdubs. One crosstalk group: each tape
//! track hears its neighbours (MT3), so who sits next to whom matters.
//!
//! **Playing**: each assigned session track plays its tape track's playback in place of its
//! lane (its inserts then print the tape; [`crate::session::Track::tape`]) while the print
//! was made from the lane as it is; an edited lane plays raw until the deck prints again. A
//! print of older deck settings keeps playing (stale), as an insert's does.
//!
//! **On disk**: `<session>/prints/deck-<key>/` with `tape<k>.wav` and `sync<k>.wav` (mono
//! float32 at the session's rate, k = 1..4, only the assigned tracks) and `deck.json`; the
//! key a sha256 over the inputs, the deck as built, the settings, the trims and the pieces'
//! layout, circuitsim's `SOURCE_HASH`.

use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

use serde_json::{Value as Json, json};
use sha2::{Digest, Sha256};

use crate::live::Values;
use crate::prefs::ALIGNMENT_DBFS;
use crate::print::{Prepared, json_value, value_json};
use crate::render::{PRINT_PIECES, Pieces, render_controls, render_pieces_controls};
use crate::resample::resample;
use crate::settings::Quality;

/// The deck's circuit file.
pub const DECK_DEVICE: &str = "ampex_300_4";
/// Its tape tracks.
pub const TRACKS: usize = 4;
/// Each channel's audio input: channel 1 the circuit's input, the rest audio controls.
pub const INPUTS: [&str; TRACKS] = ["in", "in2", "in3", "in4"];
/// Each channel's line out and Sel-Sync readout (probes).
pub const OUTS: [&str; TRACKS] = ["v(out)", "v(out_2)", "v(out_3)", "v(out_4)"];
pub const SYNCS: [&str; TRACKS] = ["v(sy)", "v(sy_2)", "v(sy_3)", "v(sy_4)"];
/// How much hotter than the alignment level a part is recorded (dB): the deck's RECORD
/// LEVEL is 0.54 dB short of operating level at 0 VU on Scotch 202
/// (reports/multitrack/deck/channel_alignment.json).
pub const DRIVE_DB: f64 = 0.5;
/// Seconds printed past the last lane's end (the repro side's decay).
pub const TAIL_S: f64 = 0.5;
/// The stretch a trim measures (s), as an insert's first trim.
const TRIM_LOUDEST_S: f64 = 8.0;

/// The session's deck (see the module docs).
#[derive(Debug, Clone, PartialEq)]
pub struct Deck {
    pub device: String,
    /// Each tape track's session track (its id), or none.
    pub tracks: [Option<String>; TRACKS],
    /// Each tape track's record trim (dB).
    pub trims_db: [f64; TRACKS],
    /// Its panel's values (the circuit's defaults for any it doesn't name).
    pub values: Values,
    /// Its noise sources on (tubes, resistors, the tape's grain; seeded).
    pub noise: bool,
}

impl Default for Deck {
    fn default() -> Self {
        Deck {
            device: DECK_DEVICE.to_string(),
            tracks: Default::default(),
            trims_db: [0.0; TRACKS],
            values: Vec::new(),
            noise: true,
        }
    }
}

impl Deck {
    pub fn to_json(&self) -> Json {
        json!({
            "device": self.device,
            "tracks": self.tracks,
            "trim_db": self.trims_db,
            "values": self
                .values
                .iter()
                .map(|(k, v)| json!([k, value_json(v)]))
                .collect::<Vec<_>>(),
            "noise": self.noise,
        })
    }

    pub fn from_json(v: &Json) -> Result<Deck, String> {
        let mut d = Deck {
            device: v["device"].as_str().unwrap_or(DECK_DEVICE).to_string(),
            noise: v["noise"].as_bool().unwrap_or(true),
            ..Deck::default()
        };
        for k in 0..TRACKS {
            d.tracks[k] = v["tracks"][k].as_str().map(str::to_string);
            d.trims_db[k] = v["trim_db"][k].as_f64().unwrap_or(0.0);
        }
        for kv in v["values"].as_array().cloned().unwrap_or_default() {
            let k = kv[0].as_str().ok_or("a deck value without a name")?;
            d.values.push((k.to_string(), json_value(&kv[1])?));
        }
        Ok(d)
    }

    /// The tape track a session track is on.
    pub fn track_of(&self, id: &str) -> Option<usize> {
        self.tracks.iter().position(|t| t.as_deref() == Some(id))
    }
}

/// A track's record trim from its lane (dB): its loudest 8 s to the alignment level, plus
/// [`DRIVE_DB`] (see the module docs).
pub fn trim_for(lane: &[f32], rate: u32) -> f64 {
    let x: Vec<f64> = lane.iter().map(|&v| v as f64).collect();
    let level = crate::audio::level_dbfs(&x, rate, TRIM_LOUDEST_S);
    ((ALIGNMENT_DBFS - level + DRIVE_DB).clamp(-40.0, 40.0) * 10.0).round() / 10.0
}

/// What a print records: each tape track's lane (its signature and its mono audio) on one
/// timeline from `start` (samples at the session's rate).
#[derive(Debug, Clone)]
pub struct DeckInput {
    pub start: i64,
    pub lanes: [Option<(String, Arc<Vec<f32>>)>; TRACKS],
}

impl DeckInput {
    /// The timeline's length: the longest lane from `start`.
    pub fn len(&self) -> usize {
        self.lanes
            .iter()
            .flatten()
            .map(|(_, a)| a.len())
            .max()
            .unwrap_or(0)
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}

/// A lane as [`place`] takes it: its signature, where it starts, its left and a stereo
/// lane's right.
pub type LaneIn<'a> = (String, i64, &'a [f32], Option<&'a [f32]>);

/// The lanes `lanes` (each a lane's signature, where it starts, its left and a stereo
/// lane's right) placed for the deck: each mono (a stereo lane's mid), from the earliest
/// start. None when no lane sounds.
pub fn place(lanes: [Option<LaneIn<'_>>; TRACKS]) -> Option<DeckInput> {
    let start = lanes.iter().flatten().map(|l| l.1).min()?;
    let mut out: [Option<(String, Arc<Vec<f32>>)>; TRACKS] = Default::default();
    for (k, l) in lanes.into_iter().enumerate() {
        let Some((sig, at, left, right)) = l else {
            continue;
        };
        let off = (at - start) as usize;
        let mut x = vec![0.0f32; off];
        match right {
            Some(r) => x.extend(
                left.iter()
                    .enumerate()
                    .map(|(i, &v)| 0.5 * (v + r.get(i).copied().unwrap_or(0.0))),
            ),
            None => x.extend_from_slice(left),
        }
        out[k] = Some((sig, Arc::new(x)));
    }
    Some(DeckInput { start, lanes: out })
}

/// A finished tape print (see the module docs).
#[derive(Debug, Clone)]
pub struct DeckPrint {
    pub key: String,
    /// The deck and lanes it was made from ([`signature`]).
    pub signature: String,
    /// Each tape track's lane signature when it was recorded (none: not assigned).
    pub lanes: [Option<String>; TRACKS],
    /// Where the tape starts on the timeline.
    pub start: i64,
    /// Each assigned tape track's playback (its lane's level), from `start`.
    pub tape: [Option<Arc<Vec<f32>>>; TRACKS],
    /// Each assigned tape track's Sel-Sync readout (the record head's playback, in time
    /// with `tape`), as `tape`'s level.
    pub sync: [Option<Arc<Vec<f32>>>; TRACKS],
    pub cached: bool,
    /// Seconds of wall clock per second of audio (0 when cached).
    pub realtime_factor: f64,
}

/// What a print of `deck` on `input` at `rate` is made from: the deck and each tape track's
/// lane (for the session: a print plays while its lanes are the lanes, and is current while
/// this is the same).
pub fn signature(deck: &Deck, input: Option<&DeckInput>, rate: u32) -> String {
    let lanes: Vec<Json> = (0..TRACKS)
        .map(|k| match input.and_then(|i| i.lanes[k].as_ref()) {
            Some((sig, _)) => json!(sig),
            None => Json::Null,
        })
        .collect();
    format!(
        "{}|{rate}|{}|{}",
        deck.to_json(),
        input.map_or(0, |i| i.start),
        Json::Array(lanes)
    )
}

fn sha_hex(h: Sha256) -> String {
    h.finalize()[..16]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// The print's key (see the module docs).
pub fn key(prep: &Prepared, deck: &Deck, input: &DeckInput, rate: u32) -> Result<String, String> {
    let ir = prep.circuit.build(&deck.values)?;
    let mut h = Sha256::new();
    h.update(b"varimu deck print 1\n");
    h.update(circuitsim::SOURCE_HASH.as_bytes());
    h.update(rate.to_le_bytes());
    for lane in &input.lanes {
        match lane {
            Some((_, a)) => {
                h.update((a.len() as u64).to_le_bytes());
                for v in a.iter() {
                    h.update(v.to_le_bytes());
                }
            }
            None => h.update(b"empty\n"),
        }
    }
    h.update(serde_json::to_vec(&ir).map_err(|e| e.to_string())?);
    h.update(format!("{:?}", prep.settings).as_bytes());
    h.update(format!("{:?}", prep.circuit.full_scale(&prep.settings)).as_bytes());
    for x in deck.trims_db.iter().chain([&TAIL_S]) {
        h.update(x.to_bits().to_le_bytes());
    }
    h.update(format!("pieces {PRINT_PIECES:?}\n").as_bytes());
    Ok(sha_hex(h))
}

/// The deck loaded at production (its circuit file; the tape's kernel on the GPU when one is
/// found, `Settings::tape_gpu`).
pub fn prepare(config_dir: &Path, deck: &Deck) -> Result<Prepared, String> {
    Prepared::load(config_dir, &deck.device, Quality::Production, deck.noise)
}

/// The deck's latency (s): its head distance over its speed.
pub fn latency_s(prep: &Prepared, deck: &Deck) -> Result<f64, String> {
    let p = varimu_circuit::spec::resolve(prep.circuit.spec(), &deck.values)
        .map_err(|e| e.to_string())?;
    let num = |k: &str| {
        p.get(k)
            .and_then(|v| v.as_f64())
            .ok_or_else(|| format!("{}: no number `{k}`", deck.device))
    };
    Ok(num("head_distance_m")? / num("speed_m_s")?)
}

fn db(x: f64) -> f64 {
    10f64.powf(x / 20.0)
}

/// How many pieces run at once: the cores less two, at most six (as an insert's print).
pub fn piece_workers() -> usize {
    std::thread::available_parallelism()
        .map_or(1, |c| c.get())
        .saturating_sub(2)
        .clamp(1, 6)
}

/// `input` through the deck, from `cache` (a session's `prints/`) when it holds the key,
/// else (with `render`) printed and kept there; without `render` only from the cache
/// ([`crate::print::NOT_PRINTED`] when it isn't there).
#[allow(clippy::too_many_arguments)]
pub fn print(
    prep: &Prepared,
    deck: &Deck,
    input: &DeckInput,
    rate: u32,
    cache: Option<&Path>,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
    render: bool,
) -> Result<DeckPrint, String> {
    if input.is_empty() {
        return Err("no assigned track has a sound".into());
    }
    let key = key(prep, deck, input, rate)?;
    let sig = signature(deck, Some(input), rate);
    let lanes: [Option<String>; TRACKS] =
        std::array::from_fn(|k| input.lanes[k].as_ref().map(|(s, _)| s.clone()));
    let dir = cache.map(|c| c.join(format!("deck-{key}")));
    if let Some(d) = &dir
        && let Some((tape, sync)) = read(d, rate, input)?
    {
        return Ok(DeckPrint {
            key,
            signature: sig,
            lanes,
            start: input.start,
            tape,
            sync,
            cached: true,
            realtime_factor: 0.0,
        });
    }
    if !render {
        return Err(crate::print::NOT_PRINTED.into());
    }
    let (tape, sync, rtf) = print_uncached(prep, deck, input, rate, progress, cancel)?;
    if let (Some(c), Some(d)) = (cache, &dir) {
        write(c, d, &key, deck, &tape, &sync, rate, rtf)?;
    }
    Ok(DeckPrint {
        key,
        signature: sig,
        lanes,
        start: input.start,
        tape,
        sync,
        cached: false,
        realtime_factor: rtf,
    })
}

/// Each tape track's playback and Sel-Sync readout.
type Tracks = [Option<Arc<Vec<f32>>>; TRACKS];

/// The print itself (see the module docs): (playback, Sel-Sync, realtime factor).
pub fn print_uncached(
    prep: &Prepared,
    deck: &Deck,
    input: &DeckInput,
    rate: u32,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<(Tracks, Tracks, f64), String> {
    print_uncached_with(
        prep,
        deck,
        input,
        rate,
        Some(PRINT_PIECES),
        progress,
        cancel,
    )
}

/// [`print_uncached`] in pieces laid out as `pieces` (None: one run; for measuring the
/// pieces' seams against it, examples/tape_print.rs).
pub fn print_uncached_with(
    prep: &Prepared,
    deck: &Deck,
    input: &DeckInput,
    rate: u32,
    pieces: Option<Pieces>,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<(Tracks, Tracks, f64), String> {
    let s = &prep.settings;
    let fsc = prep.circuit.full_scale(s);
    let tail = (TAIL_S * rate as f64).round() as usize;
    let late = (latency_s(prep, deck)? * rate as f64).round() as usize;
    let n = input.len() + tail;
    // Each channel's input at the session's rate, trimmed, `late` longer (dropped after).
    let chan = |k: usize| -> Vec<f64> {
        let mut x: Vec<f64> = match &input.lanes[k] {
            Some((_, a)) => a.iter().map(|&v| v as f64 * db(deck.trims_db[k])).collect(),
            None => Vec::new(),
        };
        x.resize(n + late, 0.0);
        resample(&x, rate, s.sample_rate)
    };
    let x = chan(0);
    // Controls in circuit volts (render_controls takes them so), on the input's full scale.
    let ctl: Vec<Vec<f64>> = (1..TRACKS)
        .map(|k| chan(k).into_iter().map(|v| v * fsc.input_v).collect())
        .collect();
    let controls: Vec<(&str, &[f64])> = (1..TRACKS)
        .map(|k| (INPUTS[k], ctl[k - 1].as_slice()))
        .collect();
    let r = match pieces {
        Some(p) => render_pieces_controls(
            &prep.circuit,
            &deck.values,
            &x,
            &controls,
            s,
            p,
            piece_workers(),
            progress,
            cancel,
        )?,
        None => render_controls(
            &prep.circuit,
            &deck.values,
            &x,
            &controls,
            s,
            progress,
            cancel,
        )?,
    };
    let probe = |name: &str| -> Result<&[f64], String> {
        r.probes
            .iter()
            .find(|(k, _)| k == name)
            .map(|(_, v)| v.as_slice())
            .ok_or_else(|| format!("{}: no probe {name}", deck.device))
    };
    // A probe (circuit volts) back at the session's rate, from where its input started, at
    // its lane's level, float32 (as an insert's print keeps it).
    let back = |v: &[f64], k: usize, drop: usize| -> Vec<f32> {
        let g = db(-deck.trims_db[k]) / fsc.output_v;
        let scaled: Vec<f64> = v.iter().map(|&y| (y as f32 as f64) * g).collect();
        let mut y = resample(&scaled, s.sample_rate, rate);
        y.drain(..drop.min(y.len()));
        y.resize(n, 0.0);
        y.into_iter().map(|u| u as f32).collect()
    };
    let mut tape: Tracks = Default::default();
    let mut sync: Tracks = Default::default();
    for k in 0..TRACKS {
        if input.lanes[k].is_none() {
            continue;
        }
        tape[k] = Some(Arc::new(back(probe(OUTS[k])?, k, late)));
        // The readout `sy` is the record head's reading of the stretch the repro head reads
        // (MT4): advanced by the head distance it is the Sel-Sync monitor, in time with what
        // was recorded, as a later pass hears it in SYNC.
        sync[k] = Some(Arc::new(back(probe(SYNCS[k])?, k, late)));
    }
    Ok((tape, sync, r.realtime_factor()))
}

/// A cached print's tracks (None: not there or incomplete).
fn read(dir: &Path, rate: u32, input: &DeckInput) -> Result<Option<(Tracks, Tracks)>, String> {
    if !dir.join("deck.json").is_file() {
        return Ok(None);
    }
    let mut tape: Tracks = Default::default();
    let mut sync: Tracks = Default::default();
    for k in 0..TRACKS {
        if input.lanes[k].is_none() {
            continue;
        }
        for (what, out) in [("tape", &mut tape), ("sync", &mut sync)] {
            let wav = dir.join(format!("{what}{}.wav", k + 1));
            if !wav.is_file() {
                return Ok(None);
            }
            let w = crate::audio::decode(&wav)?;
            if w.rate != rate {
                return Err(format!("{}: {} Hz, not {rate}", wav.display(), w.rate));
            }
            out[k] = Some(Arc::new(w.mono().iter().map(|&v| v as f32).collect()));
        }
    }
    Ok(Some((tape, sync)))
}

#[allow(clippy::too_many_arguments)]
fn write(
    cache: &Path,
    fin: &Path,
    key: &str,
    deck: &Deck,
    tape: &Tracks,
    sync: &Tracks,
    rate: u32,
    rtf: f64,
) -> Result<(), String> {
    let tmp = cache.join(format!(
        "deck-{key}.tmp{}-{:?}",
        std::process::id(),
        std::thread::current().id()
    ));
    let _ = std::fs::remove_dir_all(&tmp);
    for k in 0..TRACKS {
        for (what, t) in [("tape", tape), ("sync", sync)] {
            if let Some(a) = &t[k] {
                let x: Vec<f64> = a.iter().map(|&v| v as f64).collect();
                crate::audio::write_wav(&tmp.join(format!("{what}{}.wav", k + 1)), &x, rate)?;
            }
        }
    }
    let meta = json!({
        "key": key,
        "deck": deck.to_json(),
        "rate": rate,
        "code": circuitsim::SOURCE_HASH,
        "realtime_factor": rtf,
        "printed_unix_s": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs()),
    });
    let p = tmp.join("deck.json");
    std::fs::write(
        &p,
        serde_json::to_string_pretty(&meta).unwrap_or_default() + "\n",
    )
    .map_err(|e| format!("{}: {e}", p.display()))?;
    if std::fs::rename(&tmp, fin).is_err() {
        let _ = std::fs::remove_dir_all(&tmp);
        if !fin.join("deck.json").is_file() {
            return Err(format!("{}: couldn't keep the print", fin.display()));
        }
    }
    Ok(())
}

/// A tape print running on a thread of its own (below normal priority, as prints are).
/// Its pieces run on threads of their own.
pub struct DeckJob {
    /// The deck signature it prints.
    pub signature: String,
    progress: Arc<AtomicU64>,
    cancel: Arc<AtomicBool>,
    handle: Mutex<Option<JoinHandle<Result<DeckPrint, String>>>>,
}

impl DeckJob {
    /// Print `input` through `deck` (or find it in `cache` when `render` is false).
    pub fn spawn(
        config_dir: &Path,
        deck: Deck,
        input: DeckInput,
        rate: u32,
        cache: Option<std::path::PathBuf>,
        render: bool,
    ) -> DeckJob {
        let progress = Arc::new(AtomicU64::new(0));
        let cancel = Arc::new(AtomicBool::new(false));
        let (p, c) = (progress.clone(), cancel.clone());
        let config_dir = config_dir.to_path_buf();
        let signature = signature(&deck, Some(&input), rate);
        let handle = std::thread::spawn(move || {
            crate::print::lower_priority();
            let prep = prepare(&config_dir, &deck)?;
            print(
                &prep,
                &deck,
                &input,
                rate,
                cache.as_deref(),
                |f| p.store(f.to_bits(), Ordering::Relaxed),
                &c,
                render,
            )
        });
        DeckJob {
            signature,
            progress,
            cancel,
            handle: Mutex::new(Some(handle)),
        }
    }

    pub fn progress(&self) -> f64 {
        f64::from_bits(self.progress.load(Ordering::Relaxed))
    }

    pub fn cancel(&self) {
        self.cancel.store(true, Ordering::Relaxed);
    }

    pub fn is_finished(&self) -> bool {
        self.handle
            .lock()
            .ok()
            .and_then(|h| h.as_ref().map(JoinHandle::is_finished))
            .unwrap_or(true)
    }

    /// Its result once finished (taken: None after the first call).
    pub fn join(&self) -> Option<Result<DeckPrint, String>> {
        let h = self.handle.lock().ok()?.take()?;
        Some(
            h.join()
                .unwrap_or_else(|_| Err("the tape print panicked".into())),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_deck_round_trips_through_json() {
        let mut d = Deck::default();
        d.tracks[0] = Some("bass".into());
        d.tracks[3] = Some("harmonies".into());
        d.trims_db = [1.5, 0.0, -2.0, 3.25];
        d.noise = false;
        d.values.push((
            "record_level".into(),
            varimu_circuit::yaml::Value::Float(0.9),
        ));
        let back = Deck::from_json(&d.to_json()).unwrap();
        assert_eq!(back, d);
        assert_eq!(back.track_of("harmonies"), Some(3));
        assert_eq!(back.track_of("guitar"), None);
    }

    #[test]
    fn lanes_are_placed_mono_from_the_earliest_start() {
        let (a, b, br) = (vec![1.0f32; 4], vec![0.5f32; 3], vec![-0.5f32, 0.5, 1.5]);
        let p = place([
            Some(("a".into(), 10, a.as_slice(), None)),
            None,
            Some(("b".into(), 7, b.as_slice(), Some(br.as_slice()))),
            None,
        ])
        .unwrap();
        assert_eq!(p.start, 7);
        assert_eq!(
            *p.lanes[0].as_ref().unwrap().1,
            vec![0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
        );
        assert_eq!(*p.lanes[2].as_ref().unwrap().1, vec![0.0, 0.5, 1.0]);
        assert_eq!(p.len(), 7);
        assert!(place([None, None, None, None]).is_none());
    }

    #[test]
    fn a_trim_brings_the_loudest_stretch_to_the_alignment_level_plus_the_drive() {
        let rate = 48000;
        // A sine at -30 dBFS peak: its rms as a sine's peak is -30 dBFS.
        let a = 10f64.powf(-30.0 / 20.0);
        let x: Vec<f32> = (0..rate * 2)
            .map(|i| {
                (a * (2.0 * std::f64::consts::PI * 440.0 * i as f64 / rate as f64).sin()) as f32
            })
            .collect();
        let t = trim_for(&x, rate);
        assert!((t - (ALIGNMENT_DBFS + 30.0 + DRIVE_DB)).abs() < 0.11, "{t}");
    }
}
