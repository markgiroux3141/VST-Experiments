//! Printing (docs/SESSION_FX_PLAN.md, F1): a track's audio through a device offline, kept
//! as audio, as a studio prints a track through an outboard box. The session plays prints,
//! so a device on every track costs what plain audio costs; only the device being adjusted
//! plays live.
//!
//! **A print** of `input` (mono, at the session's rate) through an insert [`Slot`]: the
//! trim in front (a fader), `tail_s` of silence after (the box keeps sounding), to the
//! quality's rate, [`render::render`] (its settle, oversampling and partition, as any
//! render), back to the session's rate, the make-up gain, float32. A bypassed slot passes
//! its input through.
//!
//! **The key** is a sha256 over everything that changes a print: the input samples and
//! rate, the device's IR as built for the slot's values (so the circuit, its pinned
//! component versions and every value are in it), the quality's settings, the full scale,
//! the gains and tail, and circuitsim's `SOURCE_HASH`. In a chain, insert k's input is
//! insert k-1's print, so a change re-prints that insert and the ones after it only.
//!
//! **On disk**: `<session>/prints/<key>/print.wav` (mono float32 at the session's rate)
//! and `print.json` (what it was made from). A print is written to a temporary folder and
//! renamed into place, so a cancelled or failed one leaves nothing behind. Prints can be
//! made again from the session, unlike takes, so they may be cleaned up.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;

use serde_json::{Value as Json, json};
use sha2::{Digest, Sha256};
use varimu_circuit::yaml::Value;

use crate::live::{Circuit, Values};
use crate::panel::{DEVICES, Device};
use crate::render::render;
use crate::resample::resample;
use crate::settings::{Quality, Settings};

/// What a print runs past its input's end when the slot doesn't say (s).
pub const DEFAULT_TAIL_S: f64 = 0.5;

/// An insert: a device on a track (or an FX track), its panel and gains.
#[derive(Debug, Clone, PartialEq)]
pub struct Slot {
    /// A device's id (`panel::DEVICES`), or a circuit file's name.
    pub device: String,
    /// Its panel's values (the circuit's defaults for any it doesn't name).
    pub values: Values,
    /// The fader in front of it (dB).
    pub trim_db: f64,
    /// The gain after it (dB).
    pub makeup_db: f64,
    pub bypass: bool,
    /// The quality it prints at (its play quality while iterating; production on demand).
    pub quality: Quality,
    /// Seconds printed past the input's end.
    pub tail_s: f64,
    /// Its noise sources on (the circuit file's `noise` block; seeded, so reproducible).
    pub noise: bool,
}

impl Slot {
    /// `device` at its play quality with its circuit's default values, unity gains.
    pub fn new(device: &str) -> Slot {
        Slot {
            device: device.to_string(),
            values: Vec::new(),
            trim_db: 0.0,
            makeup_db: 0.0,
            bypass: false,
            quality: find_device(device).map_or(Quality::Draft1x, |d| d.quality),
            tail_s: DEFAULT_TAIL_S,
            noise: true,
        }
    }

    /// The slot as the session's JSON holds it.
    pub fn to_json(&self) -> Json {
        json!({
            "device": self.device,
            "values": self
                .values
                .iter()
                .map(|(k, v)| json!([k, value_json(v)]))
                .collect::<Vec<_>>(),
            "trim_db": self.trim_db,
            "makeup_db": self.makeup_db,
            "bypass": self.bypass,
            "quality": self.quality.name(),
            "tail_s": self.tail_s,
            "noise": self.noise,
        })
    }

    pub fn from_json(v: &Json) -> Result<Slot, String> {
        let device = v["device"].as_str().ok_or("an insert without a device")?;
        let mut s = Slot::new(device);
        for kv in v["values"].as_array().cloned().unwrap_or_default() {
            let k = kv[0]
                .as_str()
                .ok_or("an insert's value without a name")?
                .to_string();
            s.values.push((k, json_value(&kv[1])?));
        }
        s.trim_db = v["trim_db"].as_f64().unwrap_or(0.0);
        s.makeup_db = v["makeup_db"].as_f64().unwrap_or(0.0);
        s.bypass = v["bypass"].as_bool().unwrap_or(false);
        if let Some(q) = v["quality"].as_str() {
            s.quality = Quality::from_name(q).ok_or(format!("no quality {q}"))?;
        }
        s.tail_s = v["tail_s"].as_f64().unwrap_or(DEFAULT_TAIL_S);
        s.noise = v["noise"].as_bool().unwrap_or(true);
        Ok(s)
    }
}

fn value_json(v: &Value) -> Json {
    match v {
        Value::Null => Json::Null,
        Value::Bool(b) => json!(b),
        Value::Int(i) => json!(i),
        Value::Float(x) => json!(x),
        Value::Str(s) => json!(s),
        Value::List(l) => Json::Array(l.iter().map(value_json).collect()),
        Value::Map(m) => Json::Object(
            m.0.iter()
                .map(|(k, v)| (k.clone(), value_json(v)))
                .collect(),
        ),
    }
}

fn json_value(v: &Json) -> Result<Value, String> {
    Ok(match v {
        Json::Null => Value::Null,
        Json::Bool(b) => Value::Bool(*b),
        Json::Number(n) => match n.as_i64() {
            Some(i) => Value::Int(i),
            None => Value::Float(n.as_f64().ok_or("a value out of range")?),
        },
        Json::String(s) => Value::Str(s.clone()),
        Json::Array(l) => Value::List(l.iter().map(json_value).collect::<Result<_, _>>()?),
        Json::Object(_) => return Err("an insert's value can't be a mapping".into()),
    })
}

/// The device of `id` in `panel::DEVICES`.
pub fn find_device(id: &str) -> Option<&'static Device> {
    DEVICES.iter().find(|d| d.id == id)
}

/// A slot's device loaded: its circuit and its settings at the slot's quality.
pub struct Prepared {
    pub circuit: Circuit,
    pub settings: Settings,
}

impl Prepared {
    /// A device's circuit at `quality` (a draft with the device's own cores and
    /// partition, as it plays; production as the Play view's Render); a name that isn't a
    /// device is a circuit file at the quality's settings.
    pub fn load(
        config_dir: &Path,
        device: &str,
        quality: Quality,
        noise: bool,
    ) -> Result<Prepared, String> {
        let base = Settings::load(config_dir, quality)?;
        let (circuit, settings) = match find_device(device) {
            Some(d) if quality != Quality::Production => (d.circuit, d.play_settings(&base)),
            Some(d) => (d.circuit, base),
            None => (device, base),
        };
        let circuit = Circuit::load(config_dir, circuit, settings.cores()?)?.with_noise(noise);
        Ok(Prepared { circuit, settings })
    }
}

/// A finished print.
#[derive(Debug, Clone)]
pub struct Print {
    pub key: String,
    pub audio: Arc<Vec<f32>>,
    /// Found in the cache (nothing rendered).
    pub cached: bool,
    /// Seconds of wall clock per second of audio (0 when cached).
    pub realtime_factor: f64,
}

fn db(x: f64) -> f64 {
    10f64.powf(x / 20.0)
}

/// The key of `slot`'s print of `input` (see the module docs).
pub fn key(prep: &Prepared, slot: &Slot, input: &[f32], rate: u32) -> Result<String, String> {
    let ir = prep.circuit.build(&slot.values)?;
    let mut h = Sha256::new();
    h.update(b"varimu print 1\n");
    h.update(circuitsim::SOURCE_HASH.as_bytes());
    h.update(rate.to_le_bytes());
    h.update((input.len() as u64).to_le_bytes());
    for v in input {
        h.update(v.to_le_bytes());
    }
    h.update(serde_json::to_vec(&ir).map_err(|e| e.to_string())?);
    h.update(format!("{:?}", prep.settings).as_bytes());
    h.update(format!("{:?}", prep.circuit.full_scale(&prep.settings)).as_bytes());
    for x in [slot.trim_db, slot.makeup_db, slot.tail_s] {
        h.update(x.to_bits().to_le_bytes());
    }
    Ok(h.finalize()[..16]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}

/// `input` through the slot's device (see the module docs), uncached.
pub fn print_uncached(
    prep: &Prepared,
    slot: &Slot,
    input: &[f32],
    rate: u32,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<(Vec<f32>, f64), String> {
    let s = &prep.settings;
    let trim = db(slot.trim_db);
    let tail = (slot.tail_s.max(0.0) * rate as f64).round() as usize;
    let mut x: Vec<f64> = input.iter().map(|&v| v as f64 * trim).collect();
    x.resize(input.len() + tail, 0.0);
    let n = x.len();
    let r = render(
        &prep.circuit,
        &slot.values,
        &resample(&x, rate, s.sample_rate),
        s,
        progress,
        cancel,
    )?;
    let mut y = resample(&r.out, s.sample_rate, rate);
    y.resize(n, 0.0);
    let g = db(slot.makeup_db);
    Ok((
        y.iter().map(|&v| (v * g) as f32).collect(),
        r.realtime_factor(),
    ))
}

/// `input` through the slot: from `cache` (a session folder's `prints/`) if it holds the
/// key, else rendered and kept there (`cache` None: rendered, not kept). A bypassed slot
/// returns its input.
pub fn print(
    prep: &Prepared,
    slot: &Slot,
    input: &Arc<Vec<f32>>,
    rate: u32,
    cache: Option<&Path>,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<Print, String> {
    if slot.bypass {
        return Ok(Print {
            key: String::new(),
            audio: input.clone(),
            cached: true,
            realtime_factor: 0.0,
        });
    }
    let key = key(prep, slot, input, rate)?;
    if let Some(dir) = cache
        && let Some(audio) = read_print(&dir.join(&key), rate)?
    {
        return Ok(Print {
            key,
            audio: Arc::new(audio),
            cached: true,
            realtime_factor: 0.0,
        });
    }
    let (audio, rtf) = print_uncached(prep, slot, input, rate, progress, cancel)?;
    if let Some(dir) = cache {
        write_print(dir, &key, slot, &audio, rate, rtf)?;
    }
    Ok(Print {
        key,
        audio: Arc::new(audio),
        cached: false,
        realtime_factor: rtf,
    })
}

fn read_print(dir: &Path, rate: u32) -> Result<Option<Vec<f32>>, String> {
    let wav = dir.join("print.wav");
    if !wav.is_file() {
        return Ok(None);
    }
    let w = crate::audio::decode(&wav)?;
    if w.rate != rate {
        return Err(format!("{}: {} Hz, not {rate}", wav.display(), w.rate));
    }
    Ok(Some(w.mono().iter().map(|&v| v as f32).collect()))
}

fn write_print(
    cache: &Path,
    key: &str,
    slot: &Slot,
    audio: &[f32],
    rate: u32,
    rtf: f64,
) -> Result<(), String> {
    let fin = cache.join(key);
    let tmp = cache.join(format!(
        "{key}.tmp{}-{:?}",
        std::process::id(),
        std::thread::current().id()
    ));
    let _ = std::fs::remove_dir_all(&tmp);
    let x: Vec<f64> = audio.iter().map(|&v| v as f64).collect();
    crate::audio::write_wav(&tmp.join("print.wav"), &x, rate)?;
    let meta = json!({
        "key": key,
        "slot": slot.to_json(),
        "rate": rate,
        "samples": audio.len(),
        "code": circuitsim::SOURCE_HASH,
        "realtime_factor": rtf,
        "printed_unix_s": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs()),
    });
    let p = tmp.join("print.json");
    std::fs::write(
        &p,
        serde_json::to_string_pretty(&meta).unwrap_or_default() + "\n",
    )
    .map_err(|e| format!("{}: {e}", p.display()))?;
    // Another job printing the same key may have finished first: theirs stays.
    if std::fs::rename(&tmp, &fin).is_err() {
        let _ = std::fs::remove_dir_all(&tmp);
        if !fin.join("print.wav").is_file() {
            return Err(format!("{}: couldn't keep the print", fin.display()));
        }
    }
    Ok(())
}

/// A chain's prints, insert by insert: each insert's input is the one before's print.
/// `progress(k, fraction)` reports insert k.
#[allow(clippy::too_many_arguments)]
pub fn print_chain(
    preps: &[Prepared],
    slots: &[Slot],
    input: &Arc<Vec<f32>>,
    rate: u32,
    cache: Option<&Path>,
    mut progress: impl FnMut(usize, f64),
    cancel: &AtomicBool,
) -> Result<Vec<Print>, String> {
    if preps.len() != slots.len() {
        return Err("a chain needs a prepared device per slot".into());
    }
    let mut out: Vec<Print> = Vec::with_capacity(slots.len());
    for (k, (p, s)) in preps.iter().zip(slots).enumerate() {
        let x = out.last().map_or(input, |q| &q.audio).clone();
        out.push(print(p, s, &x, rate, cache, |f| progress(k, f), cancel)?);
    }
    Ok(out)
}

/// This thread below normal priority (Windows; elsewhere nothing): prints yield to the
/// player's worker and the window (the process runs at the high class,
/// `player::raise_priority`). A draft's partition thread starts at normal priority.
fn lower_priority() {
    #[cfg(windows)]
    {
        use windows_sys::Win32::System::Threading::{
            GetCurrentThread, SetThreadPriority, THREAD_PRIORITY_BELOW_NORMAL,
        };
        // SAFETY: the pseudo handle of this thread and a valid priority.
        unsafe {
            SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
        }
    }
}

/// A chain's prints, or why there are none.
pub type ChainResult = Result<Vec<Print>, String>;

/// A chain printing on a thread of its own: its progress, a cancel, its result.
pub struct Job {
    /// The insert being printed (high 32 bits) and its fraction done (f32 bits).
    progress: Arc<AtomicU64>,
    cancel: Arc<AtomicBool>,
    handle: Mutex<Option<JoinHandle<ChainResult>>>,
}

impl Job {
    /// `slots` loaded from `config_dir` and printed on `input` in the background.
    pub fn spawn(
        config_dir: PathBuf,
        slots: Vec<Slot>,
        input: Arc<Vec<f32>>,
        rate: u32,
        cache: Option<PathBuf>,
    ) -> Job {
        let progress = Arc::new(AtomicU64::new(0));
        let cancel = Arc::new(AtomicBool::new(false));
        let (p, c) = (progress.clone(), cancel.clone());
        let handle = std::thread::spawn(move || {
            lower_priority();
            let preps = slots
                .iter()
                .map(|s| Prepared::load(&config_dir, &s.device, s.quality, s.noise))
                .collect::<Result<Vec<_>, _>>()?;
            print_chain(
                &preps,
                &slots,
                &input,
                rate,
                cache.as_deref(),
                |k, f| {
                    p.store(
                        ((k as u64) << 32) | (f as f32).to_bits() as u64,
                        Ordering::Relaxed,
                    )
                },
                &c,
            )
        });
        Job {
            progress,
            cancel,
            handle: Mutex::new(Some(handle)),
        }
    }

    /// The insert being printed and its fraction done.
    pub fn progress(&self) -> (usize, f64) {
        let v = self.progress.load(Ordering::Relaxed);
        ((v >> 32) as usize, f32::from_bits(v as u32) as f64)
    }

    pub fn cancel(&self) {
        self.cancel.store(true, Ordering::Relaxed);
    }

    pub fn is_finished(&self) -> bool {
        self.handle
            .lock()
            .map(|h| h.as_ref().is_none_or(JoinHandle::is_finished))
            .unwrap_or(true)
    }

    /// Its result (waits for it; None once taken).
    pub fn join(&self) -> Option<ChainResult> {
        let h = self.handle.lock().ok()?.take()?;
        Some(
            h.join()
                .unwrap_or_else(|_| Err("the print's thread panicked".into())),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
    }

    fn tone(rate: u32, s: f64, amp: f64) -> Arc<Vec<f32>> {
        let n = (s * rate as f64) as usize;
        Arc::new(
            (0..n)
                .map(|i| {
                    let t = i as f64 / rate as f64;
                    (amp * (2.0 * std::f64::consts::PI * 440.0 * t).sin() * (t * 40.0).min(1.0))
                        as f32
                })
                .collect(),
        )
    }

    fn stage(gain_db: f64) -> Slot {
        let mut s = Slot::new("triode_stage_drawn");
        s.quality = Quality::Draft1x;
        s.tail_s = 0.05;
        s.trim_db = gain_db;
        s
    }

    fn temp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("varimu_print_{name}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        d
    }

    #[test]
    fn a_print_is_a_render_and_reads_back_bit_for_bit() {
        let (rate, x) = (48_000, tone(48_000, 0.2, 0.3));
        let slot = stage(-6.0);
        let p = Prepared::load(&config(), &slot.device, slot.quality, slot.noise).unwrap();
        let no = AtomicBool::new(false);
        // By hand: trim, tail, the render at the quality's rate, back, float32.
        let s = &p.settings;
        let mut v: Vec<f64> = x.iter().map(|&a| a as f64 * db(-6.0)).collect();
        v.resize(x.len() + 2400, 0.0);
        let r = render(
            &p.circuit,
            &slot.values,
            &resample(&v, rate, s.sample_rate),
            s,
            |_| {},
            &no,
        )
        .unwrap();
        let mut want: Vec<f32> = resample(&r.out, s.sample_rate, rate)
            .iter()
            .map(|&a| a as f32)
            .collect();
        want.resize(v.len(), 0.0);
        let dir = temp("readback");
        let a = print(&p, &slot, &x, rate, Some(&dir), |_| {}, &no).unwrap();
        assert!(!a.cached);
        assert_eq!(*a.audio, want);
        assert!(
            want.iter().any(|&y| y.abs() > 1e-3),
            "the stage passes the tone"
        );
        let b = print(&p, &slot, &x, rate, Some(&dir), |_| {}, &no).unwrap();
        assert!(b.cached);
        assert_eq!(a.key, b.key);
        assert_eq!(*b.audio, want);
        assert!(dir.join(&a.key).join("print.json").is_file());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_key_follows_everything_that_changes_a_print() {
        let (rate, x) = (48_000, tone(48_000, 0.05, 0.3));
        let base = stage(0.0);
        let p = Prepared::load(&config(), &base.device, base.quality, true).unwrap();
        let k0 = key(&p, &base, &x, rate).unwrap();
        assert_eq!(k0, key(&p, &base, &x, rate).unwrap());
        let mut y = (*x).clone();
        y[100] += 1e-6;
        assert_ne!(k0, key(&p, &base, &y, rate).unwrap(), "the audio");
        assert_ne!(k0, key(&p, &base, &x, 44_100).unwrap(), "the rate");
        let mut s = base.clone();
        s.makeup_db = 1.0;
        assert_ne!(k0, key(&p, &s, &x, rate).unwrap(), "a gain");
        // A panel value (the drawn stage has none: the 670's, only keyed, not rendered).
        let fc = Slot::new("fairchild_670");
        let pf = Prepared::load(&config(), &fc.device, fc.quality, true).unwrap();
        let mut s = fc.clone();
        s.values = vec![("ac_threshold".into(), Value::Float(0.31))];
        assert_ne!(
            key(&pf, &fc, &x, rate).unwrap(),
            key(&pf, &s, &x, rate).unwrap(),
            "a value"
        );
        let prod = Prepared::load(&config(), &base.device, Quality::Production, true).unwrap();
        assert_ne!(k0, key(&prod, &base, &x, rate).unwrap(), "the quality");
        // Bypass and the quality field itself are not in the key: what was loaded is.
        let mut s = base.clone();
        s.bypass = true;
        assert_eq!(k0, key(&p, &s, &x, rate).unwrap());
    }

    #[test]
    fn a_chain_reprints_from_the_change_on() {
        let (rate, x) = (48_000, tone(48_000, 0.1, 0.2));
        let slots = vec![stage(-6.0), stage(-12.0), stage(-12.0)];
        let load = |s: &[Slot]| {
            s.iter()
                .map(|s| Prepared::load(&config(), &s.device, s.quality, s.noise).unwrap())
                .collect::<Vec<_>>()
        };
        let dir = temp("chain");
        let no = AtomicBool::new(false);
        let a = print_chain(&load(&slots), &slots, &x, rate, Some(&dir), |_, _| {}, &no).unwrap();
        assert!(a.iter().all(|p| !p.cached));
        let mut edited = slots.clone();
        edited[1].makeup_db = -1.0;
        let b = print_chain(
            &load(&edited),
            &edited,
            &x,
            rate,
            Some(&dir),
            |_, _| {},
            &no,
        )
        .unwrap();
        assert_eq!(
            b.iter().map(|p| p.cached).collect::<Vec<_>>(),
            [true, false, false]
        );
        assert_eq!(a[0].audio, b[0].audio);
        // Bypassing the middle insert feeds the first's print to the last.
        edited[1].bypass = true;
        let c = print_chain(
            &load(&edited),
            &edited,
            &x,
            rate,
            Some(&dir),
            |_, _| {},
            &no,
        )
        .unwrap();
        assert_eq!(c[1].audio, c[0].audio);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_cancelled_print_leaves_nothing() {
        let (rate, x) = (48_000, tone(48_000, 0.3, 0.3));
        let dir = temp("cancel");
        let job = Job::spawn(config(), vec![stage(0.0)], x, rate, Some(dir.clone()));
        job.cancel();
        let r = job.join().expect("a result");
        assert!(r.is_err());
        let left = std::fs::read_dir(&dir).map_or(0, |d| d.count());
        assert_eq!(left, 0);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn slots_survive_json() {
        let mut s = Slot::new("fairchild_670");
        s.values = vec![
            ("time_constant".into(), Value::Int(3)),
            ("ac_threshold".into(), Value::Float(0.7)),
        ];
        s.trim_db = -4.25;
        s.quality = Quality::Production;
        assert_eq!(Slot::from_json(&s.to_json()).unwrap(), s);
        assert_eq!(Slot::new("fairchild_670").quality, Quality::Draft1x);
    }
}
