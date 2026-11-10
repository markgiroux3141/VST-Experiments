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
//! **A sidechain**: a slot whose device has a key input (`panel::Device::key`, the keyed
//! 670) and a [`KeyRoute`] prints with another track's audio on that control input, beside
//! its input from the same start (`sidechain`, at the session's rate): the route's trim, in
//! circuit volts on the input's full scale, through the same render. The session makes the
//! sidechain (SIDECHAIN_PLAN.md K3); a print only takes it.
//!
//! **The key** is a sha256 over everything that changes a print: the input samples and
//! rate, the device's IR as built for the slot's values (so the circuit, its pinned
//! component versions and every value are in it), the quality's settings, the full scale,
//! the gains and tail, circuitsim's `SOURCE_HASH`, and a sidechain's samples and trim when
//! there is one (so a print without one keeps its key). In a chain, insert k's input is
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
use crate::render::{PRINT_PIECES, render_controls, render_pieces};
use crate::resample::resample;
use crate::settings::{Quality, Settings};

/// A lookup's answer when the cache doesn't hold a print ([`Job::lookup`]).
pub const NOT_PRINTED: &str = "not printed";

/// What a print runs past its input's end when the slot doesn't say (s).
pub const DEFAULT_TAIL_S: f64 = 0.5;
/// A reverb's tail: the plate's longest decay (about 10 s at 100 Hz, undamped) down 60 dB.
pub const REVERB_TAIL_S: f64 = 8.0;

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
    /// The device's share of the output, the rest the input before the trim (a console's
    /// wet / dry: 1 is the device only; a reverb starts at [`REVERB_WET`]).
    pub wet: f64,
    /// Where its key input listens (a device with one: `panel::Device::key`; None: no
    /// sidechain, the key input at 0 V).
    pub key: Option<KeyRoute>,
}

/// A slot's sidechain route: another track's audio (after its inserts, before its fader,
/// muted or not) on the device's key input (SIDECHAIN_PLAN.md decisions 2-3).
#[derive(Debug, Clone, PartialEq)]
pub struct KeyRoute {
    /// The key track's id (`session::Track::id`).
    pub track: String,
    /// The fader in front of the key input (dB): set once from the key's loudest stretch.
    pub trim_db: f64,
}

/// A reverb's wet share when it's added as an insert (the dry signal passes too).
pub const REVERB_WET: f64 = 0.3;

/// Devices whose output is an effect only (a reverb's return): added with [`REVERB_WET`].
pub const WET_ONLY: [&str; 2] = ["plate_reverb", "foil_reverb"];

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
            tail_s: if WET_ONLY.contains(&device) {
                REVERB_TAIL_S
            } else {
                DEFAULT_TAIL_S
            },
            noise: true,
            wet: if WET_ONLY.contains(&device) {
                REVERB_WET
            } else {
                1.0
            },
            key: None,
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
            "wet": self.wet,
            "key": self.key.as_ref().map(|k| json!({"track": k.track, "trim_db": k.trim_db})),
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
        s.wet = v["wet"].as_f64().unwrap_or(1.0);
        s.key = match &v["key"] {
            Json::Null => None,
            k => Some(KeyRoute {
                track: k["track"]
                    .as_str()
                    .ok_or("a key route without a track")?
                    .to_string(),
                trim_db: k["trim_db"].as_f64().unwrap_or(0.0),
            }),
        };
        Ok(s)
    }
}

pub(crate) fn value_json(v: &Value) -> Json {
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

pub(crate) fn json_value(v: &Json) -> Result<Value, String> {
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
        let circuit = Circuit::load(config_dir, circuit, settings.cores()?)?
            .with_events(settings.events)
            .with_noise(noise);
        Ok(Prepared { circuit, settings })
    }
}

/// A finished print.
#[derive(Debug, Clone)]
pub struct Print {
    pub key: String,
    pub audio: Arc<Vec<f32>>,
    /// A stereo input's right channel through the same insert, printed apart with the
    /// same panel (dual-mono, docs/STEREO_PLAN.md ST3; `audio` the left's print).
    pub right: Option<Arc<Vec<f32>>>,
    /// Found in the cache (nothing rendered).
    pub cached: bool,
    /// Seconds of wall clock per second of audio (0 when cached).
    pub realtime_factor: f64,
}

fn db(x: f64) -> f64 {
    10f64.powf(x / 20.0)
}

/// The key input a slot's print drives (the device's, when the slot has a route).
pub fn key_control(slot: &Slot) -> Option<&'static str> {
    slot.key.as_ref()?;
    find_device(&slot.device)?.key
}

/// The key of `slot`'s print of `input` with `sidechain` (see the module docs).
pub fn key(
    prep: &Prepared,
    slot: &Slot,
    input: &[f32],
    sidechain: Option<&[f32]>,
    rate: u32,
) -> Result<String, String> {
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
    for x in [slot.trim_db, slot.makeup_db, slot.tail_s, slot.wet] {
        h.update(x.to_bits().to_le_bytes());
    }
    if in_pieces(slot) {
        h.update(format!("pieces {PRINT_PIECES:?}\n").as_bytes());
    }
    if let (Some(c), Some(side), Some(route)) = (key_control(slot), sidechain, &slot.key) {
        h.update(b"sidechain\n");
        h.update(c.as_bytes());
        h.update(route.trim_db.to_bits().to_le_bytes());
        h.update((side.len() as u64).to_le_bytes());
        for v in side {
            h.update(v.to_le_bytes());
        }
    }
    Ok(h.finalize()[..16]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}

/// Devices that play their input a fixed time late: a tape machine's repro head a head
/// distance behind its record head. A print is shifted back by it so the track stays in time
/// (the live audition is heard late, as off a real machine's repro head).
pub const TAPE_MACHINES: [&str; 2] = ["ampex_351_insert", "ampex_351_2_insert"];

/// Whether the slot's device prints in pieces run at once ([`render_pieces`] at
/// [`PRINT_PIECES`]): the tape machines, whose literal print is long and bounded by one
/// core per run, and whose memory P3's warm-up covers (TAPE_SPEED_PLAN.md P3).
pub fn in_pieces(slot: &Slot) -> bool {
    TAPE_MACHINES.contains(&slot.device.as_str())
}

/// How many pieces run at once: the cores less two for the desktop, at most six (P3's
/// measurement: one core per piece; more at once gained nothing).
fn piece_workers() -> usize {
    std::thread::available_parallelism()
        .map_or(1, |c| c.get())
        .saturating_sub(2)
        .clamp(1, 6)
}

/// The slot's device's latency in seconds: a tape machine's head distance over the speed its
/// `speed` switch picks (1 its `speed_m_s`, 0 its `speed_lo_m_s`); 0 for the rest.
pub fn latency_s(circuit: &Circuit, slot: &Slot) -> Result<f64, String> {
    if !TAPE_MACHINES.contains(&slot.device.as_str()) {
        return Ok(0.0);
    }
    let p =
        varimu_circuit::spec::resolve(circuit.spec(), &slot.values).map_err(|e| e.to_string())?;
    let num = |k: &str| {
        p.get(k)
            .and_then(|v| v.as_f64())
            .ok_or_else(|| format!("{}: no number `{k}`", slot.device))
    };
    let speed = if num("speed")? >= 0.5 {
        num("speed_m_s")?
    } else {
        num("speed_lo_m_s")?
    };
    Ok(num("head_distance_m")? / speed)
}

/// Whether the slot prints stereo from one input (docs/REVERB_PLAN.md, "Stereo"): its
/// device's circuit probes `out_r` and its STEREO switch (`stereo`) is on, as the reverbs'.
/// Such a print takes the mid of a stereo input (the EMT 140 TS's "M" channel) and gives
/// both channels, on a mono track too.
pub fn stereo_out(prep: &Prepared, slot: &Slot) -> Result<bool, String> {
    if slot.bypass || !prep.circuit.spec().probes.iter().any(|p| p == "out_r") {
        return Ok(false);
    }
    let p = varimu_circuit::spec::resolve(prep.circuit.spec(), &slot.values)
        .map_err(|e| e.to_string())?;
    Ok(p.get("stereo")
        .and_then(|v| v.as_f64())
        .is_some_and(|v| v >= 0.5))
}

/// A two-input device's right input (an audio control input, STEREO_PLAN.md ST7): the
/// stereo 670's channel 2.
pub const RIGHT_INPUT: &str = "in_r";

/// Whether the slot's device takes both channels of a stereo input in one run (its circuit
/// has the audio input [`RIGHT_INPUT`] and probes `out_r`, as the stereo 670): its print is
/// stereo, the left into `in` and the right into `in_r` (a mono input into both).
pub fn two_inputs(prep: &Prepared, slot: &Slot) -> bool {
    let spec = prep.circuit.spec();
    !slot.bypass
        && spec.audio_inputs.iter().any(|(n, _)| n == RIGHT_INPUT)
        && spec.probes.iter().any(|p| p == "out_r")
}

/// A two-input slot's print ([`two_inputs`]) of `left` and `right` (`left` when mono),
/// uncached: one run, its `out` and `out_r` each mixed with its own side's dry input.
#[allow(clippy::too_many_arguments)]
pub fn print_uncached_two(
    prep: &Prepared,
    slot: &Slot,
    left: &[f32],
    right: Option<&[f32]>,
    sidechain: Option<&[f32]>,
    rate: u32,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<(Vec<f32>, Vec<f32>, f64), String> {
    let r = right.unwrap_or(left);
    let (y, yr, rtf) = device_out(prep, slot, left, Some(r), sidechain, rate, progress, cancel)?;
    let yr = yr.ok_or_else(|| format!("{}: no right output (out_r)", slot.device))?;
    Ok((mixed(slot, &y, left), mixed(slot, &yr, r), rtf))
}

/// A two-input slot's print key: the left's print key (the device, values and gains) with
/// both inputs in it.
fn two_key(base: &str, left: &[f32], right: Option<&[f32]>) -> String {
    stereo_key(&format!("two inputs {base}"), left, right)
}

/// A stereo print's key: the key of its mid input's print (the device, values and gains)
/// with both channels of the input in it (each side's dry is mixed in).
fn stereo_key(base: &str, left: &[f32], right: Option<&[f32]>) -> String {
    let mut h = Sha256::new();
    h.update(b"varimu stereo print 1\n");
    h.update(base.as_bytes());
    for side in [Some(left), right] {
        match side {
            Some(x) => {
                h.update((x.len() as u64).to_le_bytes());
                for v in x {
                    h.update(v.to_le_bytes());
                }
            }
            None => h.update(b"mono\n"),
        }
    }
    h.finalize()[..16]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// The mid of a stereo input (its left alone when mono).
fn mid(left: &[f32], right: Option<&[f32]>) -> Vec<f32> {
    match right {
        Some(r) => left
            .iter()
            .enumerate()
            .map(|(i, &l)| 0.5 * (l + r.get(i).copied().unwrap_or(0.0)))
            .collect(),
        None => left.to_vec(),
    }
}

/// `input` through the slot's device with `sidechain` (see the module docs), uncached.
pub fn print_uncached(
    prep: &Prepared,
    slot: &Slot,
    input: &[f32],
    sidechain: Option<&[f32]>,
    rate: u32,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<(Vec<f32>, f64), String> {
    let (y, _, rtf) = device_out(prep, slot, input, None, sidechain, rate, progress, cancel)?;
    Ok((mixed(slot, &y, input), rtf))
}

/// A stereo slot's print ([`stereo_out`]), uncached: the mid of `left` and `right` (`left`
/// when mono) through the device once, its `out` and `out_r` each mixed with its own side's
/// dry input (a mono input's in both). Returns (left, right, realtime factor).
#[allow(clippy::too_many_arguments)]
pub fn print_uncached_stereo(
    prep: &Prepared,
    slot: &Slot,
    left: &[f32],
    right: Option<&[f32]>,
    sidechain: Option<&[f32]>,
    rate: u32,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<(Vec<f32>, Vec<f32>, f64), String> {
    let m = mid(left, right);
    let (y, yr, rtf) = device_out(prep, slot, &m, None, sidechain, rate, progress, cancel)?;
    let yr = yr.ok_or_else(|| format!("{}: no right output (out_r)", slot.device))?;
    Ok((
        mixed(slot, &y, left),
        mixed(slot, &yr, right.unwrap_or(left)),
        rtf,
    ))
}

/// The device's share after its make-up, the rest `dry` as it came (the input before the
/// trim), as float32.
fn mixed(slot: &Slot, y: &[f64], dry: &[f32]) -> Vec<f32> {
    let (g, wet) = (db(slot.makeup_db), slot.wet.clamp(0.0, 1.0));
    y.iter()
        .enumerate()
        .map(|(i, &v)| {
            let d = dry.get(i).map_or(0.0, |&u| u as f64);
            (wet * v * g + (1.0 - wet) * d) as f32
        })
        .collect()
}

/// A device's output, a stereo circuit's right output, the render's realtime factor.
type DeviceOut = (Vec<f64>, Option<Vec<f64>>, f64);

/// The slot's device's output for `input` at the session's rate (the input's length plus
/// the tail, a tape machine's latency taken off), before the wet / dry mix; a stereo
/// circuit's right output beside it; the render's realtime factor. `right`: a two-input
/// device's right input ([`two_inputs`]: its audio input `in_r`, through the same trim).
#[allow(clippy::too_many_arguments)]
fn device_out(
    prep: &Prepared,
    slot: &Slot,
    input: &[f32],
    right: Option<&[f32]>,
    sidechain: Option<&[f32]>,
    rate: u32,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<DeviceOut, String> {
    let s = &prep.settings;
    let trim = db(slot.trim_db);
    let tail = (slot.tail_s.max(0.0) * rate as f64).round() as usize;
    let late = (latency_s(&prep.circuit, slot)? * rate as f64).round() as usize;
    let mut x: Vec<f64> = input.iter().map(|&v| v as f64 * trim).collect();
    let n = input.len() + tail;
    // Run `late` longer, then drop the first `late` samples of the output.
    x.resize(n + late, 0.0);
    let side_v: Option<(&str, Vec<f64>)> = match (key_control(slot), sidechain, &slot.key) {
        (Some(c), Some(side), Some(route)) => {
            let v = db(route.trim_db) * prep.circuit.full_scale(s).input_v;
            let mut k: Vec<f64> = side.iter().take(n + late).map(|&u| u as f64 * v).collect();
            k.resize(n + late, 0.0);
            Some((c, resample(&k, rate, s.sample_rate)))
        }
        _ => None,
    };
    let right_v: Option<Vec<f64>> = right.map(|r| {
        let v = trim * prep.circuit.full_scale(s).input_v;
        let mut xr: Vec<f64> = r.iter().take(n + late).map(|&u| u as f64 * v).collect();
        xr.resize(n + late, 0.0);
        resample(&xr, rate, s.sample_rate)
    });
    let mut controls: Vec<(&str, &[f64])> =
        side_v.iter().map(|(c, k)| (*c, k.as_slice())).collect();
    if let Some(xr) = &right_v {
        controls.push((RIGHT_INPUT, xr.as_slice()));
    }
    let xs = resample(&x, rate, s.sample_rate);
    let r = if in_pieces(slot) && controls.is_empty() {
        render_pieces(
            &prep.circuit,
            &slot.values,
            &xs,
            s,
            PRINT_PIECES,
            piece_workers(),
            progress,
            cancel,
        )?
    } else {
        render_controls(
            &prep.circuit,
            &slot.values,
            &xs,
            &controls,
            s,
            progress,
            cancel,
        )?
    };
    let back = |out: &[f64]| {
        let mut y = resample(out, s.sample_rate, rate);
        y.drain(..late.min(y.len()));
        y.resize(n, 0.0);
        y
    };
    Ok((
        back(&r.out),
        r.out_r.as_deref().map(back),
        r.realtime_factor(),
    ))
}

/// `input` (with `sidechain`) through the slot: from `cache` (a session folder's
/// `prints/`) if it holds the key, else rendered and kept there (`cache` None: rendered,
/// not kept). A bypassed slot returns its input.
#[allow(clippy::too_many_arguments)]
pub fn print(
    prep: &Prepared,
    slot: &Slot,
    input: &Arc<Vec<f32>>,
    sidechain: Option<&[f32]>,
    rate: u32,
    cache: Option<&Path>,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
) -> Result<Print, String> {
    print_or_find(
        prep, slot, input, sidechain, rate, cache, progress, cancel, true,
    )
}

/// [`print`], or with `render` false only from the cache ([`NOT_PRINTED`] when it isn't
/// there).
#[allow(clippy::too_many_arguments)]
fn print_or_find(
    prep: &Prepared,
    slot: &Slot,
    input: &Arc<Vec<f32>>,
    sidechain: Option<&[f32]>,
    rate: u32,
    cache: Option<&Path>,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
    render: bool,
) -> Result<Print, String> {
    if slot.bypass {
        return Ok(Print {
            key: String::new(),
            audio: input.clone(),
            right: None,
            cached: true,
            realtime_factor: 0.0,
        });
    }
    let key = key(prep, slot, input, sidechain, rate)?;
    if let Some(dir) = cache
        && let Some((audio, _)) = read_print(&dir.join(&key), rate)?
    {
        return Ok(Print {
            key,
            audio: Arc::new(audio),
            right: None,
            cached: true,
            realtime_factor: 0.0,
        });
    }
    if !render {
        return Err(NOT_PRINTED.into());
    }
    let (audio, rtf) = print_uncached(prep, slot, input, sidechain, rate, progress, cancel)?;
    if let Some(dir) = cache {
        write_print(dir, &key, slot, &audio, None, rate, rtf)?;
    }
    Ok(Print {
        key,
        audio: Arc::new(audio),
        right: None,
        cached: false,
        realtime_factor: rtf,
    })
}

/// A stereo slot's print ([`stereo_out`]) of `left` and `right`, as [`print_or_find`]:
/// its [`Print::right`] always there, its cache file two channels.
#[allow(clippy::too_many_arguments)]
fn print_or_find_stereo(
    prep: &Prepared,
    slot: &Slot,
    left: &Arc<Vec<f32>>,
    right: Option<&Arc<Vec<f32>>>,
    sidechain: Option<&[f32]>,
    rate: u32,
    cache: Option<&Path>,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
    render: bool,
) -> Result<Print, String> {
    let r = right.map(|r| r.as_slice());
    let m = mid(left, r);
    let key = stereo_key(&key(prep, slot, &m, sidechain, rate)?, left, r);
    if let Some(dir) = cache
        && let Some((audio, Some(audio_r))) = read_print(&dir.join(&key), rate)?
    {
        return Ok(Print {
            key,
            audio: Arc::new(audio),
            right: Some(Arc::new(audio_r)),
            cached: true,
            realtime_factor: 0.0,
        });
    }
    if !render {
        return Err(NOT_PRINTED.into());
    }
    let (audio, audio_r, rtf) =
        print_uncached_stereo(prep, slot, left, r, sidechain, rate, progress, cancel)?;
    if let Some(dir) = cache {
        write_print(dir, &key, slot, &audio, Some(&audio_r), rate, rtf)?;
    }
    Ok(Print {
        key,
        audio: Arc::new(audio),
        right: Some(Arc::new(audio_r)),
        cached: false,
        realtime_factor: rtf,
    })
}

/// A two-input slot's print ([`two_inputs`]) of `left` and `right`, as
/// [`print_or_find_stereo`].
#[allow(clippy::too_many_arguments)]
fn print_or_find_two(
    prep: &Prepared,
    slot: &Slot,
    left: &Arc<Vec<f32>>,
    right: Option<&Arc<Vec<f32>>>,
    sidechain: Option<&[f32]>,
    rate: u32,
    cache: Option<&Path>,
    progress: impl FnMut(f64),
    cancel: &AtomicBool,
    render: bool,
) -> Result<Print, String> {
    let r = right.map(|r| r.as_slice());
    let key = two_key(&key(prep, slot, left, sidechain, rate)?, left, r);
    if let Some(dir) = cache
        && let Some((audio, Some(audio_r))) = read_print(&dir.join(&key), rate)?
    {
        return Ok(Print {
            key,
            audio: Arc::new(audio),
            right: Some(Arc::new(audio_r)),
            cached: true,
            realtime_factor: 0.0,
        });
    }
    if !render {
        return Err(NOT_PRINTED.into());
    }
    let (audio, audio_r, rtf) =
        print_uncached_two(prep, slot, left, r, sidechain, rate, progress, cancel)?;
    if let Some(dir) = cache {
        write_print(dir, &key, slot, &audio, Some(&audio_r), rate, rtf)?;
    }
    Ok(Print {
        key,
        audio: Arc::new(audio),
        right: Some(Arc::new(audio_r)),
        cached: false,
        realtime_factor: rtf,
    })
}

/// A cached print: its left (or mono) channel and a stereo print's right.
type Kept = (Vec<f32>, Option<Vec<f32>>);

fn read_print(dir: &Path, rate: u32) -> Result<Option<Kept>, String> {
    let wav = dir.join("print.wav");
    if !wav.is_file() {
        return Ok(None);
    }
    let w = crate::audio::decode(&wav)?;
    if w.rate != rate {
        return Err(format!("{}: {} Hz, not {rate}", wav.display(), w.rate));
    }
    let f32s = |x: &[f64]| x.iter().map(|&v| v as f32).collect::<Vec<f32>>();
    Ok(Some(match w.channels.as_slice() {
        [l, r] => (f32s(l), Some(f32s(r))),
        _ => (f32s(&w.mono()), None),
    }))
}

#[allow(clippy::too_many_arguments)]
fn write_print(
    cache: &Path,
    key: &str,
    slot: &Slot,
    audio: &[f32],
    right: Option<&[f32]>,
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
    match right {
        // A stereo print: one 2-channel file.
        Some(r) => {
            let frames: Vec<[f32; 2]> = audio.iter().zip(r).map(|(&a, &b)| [a, b]).collect();
            crate::audio::write_wav_stereo(&tmp.join("print.wav"), &frames, rate)?;
        }
        None => {
            let x: Vec<f64> = audio.iter().map(|&v| v as f64).collect();
            crate::audio::write_wav(&tmp.join("print.wav"), &x, rate)?;
        }
    }
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

/// A chain's prints, insert by insert: each insert's input is the one before's print, its
/// sidechain `sidechains[k]` (none past the list's end). `progress(k, fraction)` reports
/// insert k.
#[allow(clippy::too_many_arguments)]
pub fn print_chain(
    preps: &[Prepared],
    slots: &[Slot],
    sidechains: &[Option<Arc<Vec<f32>>>],
    input: &Arc<Vec<f32>>,
    rate: u32,
    cache: Option<&Path>,
    progress: impl FnMut(usize, f64),
    cancel: &AtomicBool,
) -> Result<Vec<Print>, String> {
    chain(
        preps, None, slots, sidechains, input, None, rate, cache, progress, cancel, true,
    )
}

/// The right channel's devices, loaded when a chain first needs them.
type LoadRight<'a> = &'a dyn Fn() -> Result<Vec<Prepared>, String>;

/// A chain's prints of `input` and a stereo input's `right`, insert by insert: a two-input
/// insert ([`two_inputs`], the stereo 670) prints both in one run; a stereo
/// insert ([`stereo_out`]) prints their mid once into both channels; any other prints each
/// channel apart once the chain is stereo (dual-mono, the right on a thread of its own with
/// `load_right`'s devices: a tape machine's second track; None: the left's).
#[allow(clippy::too_many_arguments)]
fn chain(
    preps: &[Prepared],
    load_right: Option<LoadRight>,
    slots: &[Slot],
    sidechains: &[Option<Arc<Vec<f32>>>],
    input: &Arc<Vec<f32>>,
    right: Option<Arc<Vec<f32>>>,
    rate: u32,
    cache: Option<&Path>,
    mut progress: impl FnMut(usize, f64),
    cancel: &AtomicBool,
    render: bool,
) -> Result<Vec<Print>, String> {
    if preps.len() != slots.len() {
        return Err("a chain needs a prepared device per slot".into());
    }
    let mut preps_r: Option<Vec<Prepared>> = None;
    let mut out: Vec<Print> = Vec::with_capacity(slots.len());
    let (mut x, mut xr) = (input.clone(), right);
    for (k, (p, s)) in preps.iter().zip(slots).enumerate() {
        let side = sidechains
            .get(k)
            .and_then(|c| c.as_deref())
            .map(Vec::as_slice);
        let print = if two_inputs(p, s) {
            print_or_find_two(
                p,
                s,
                &x,
                xr.as_ref(),
                side,
                rate,
                cache,
                |f| progress(k, f),
                cancel,
                render,
            )?
        } else if stereo_out(p, s)? {
            print_or_find_stereo(
                p,
                s,
                &x,
                xr.as_ref(),
                side,
                rate,
                cache,
                |f| progress(k, f),
                cancel,
                render,
            )?
        } else if let Some(r) = &xr {
            if preps_r.is_none()
                && let Some(load) = load_right
            {
                preps_r = Some(load()?);
            }
            let pr = preps_r.as_ref().map_or(p, |v| &v[k]);
            let (left, right) = std::thread::scope(|scope| {
                let other = scope.spawn(|| {
                    lower_priority();
                    print_or_find(pr, s, r, side, rate, cache, |_| {}, cancel, render)
                });
                let left = print_or_find(
                    p,
                    s,
                    &x,
                    side,
                    rate,
                    cache,
                    |f| progress(k, f),
                    cancel,
                    render,
                );
                if left.is_err() {
                    cancel.store(true, Ordering::Relaxed);
                }
                let right = other
                    .join()
                    .unwrap_or_else(|_| Err("the print's thread panicked".into()));
                (left, right)
            });
            let mut left = left?;
            left.right = Some(right?.audio);
            left
        } else {
            print_or_find(
                p,
                s,
                &x,
                side,
                rate,
                cache,
                |f| progress(k, f),
                cancel,
                render,
            )?
        };
        x = print.audio.clone();
        xr = print.right.clone();
        out.push(print);
    }
    Ok(out)
}

/// This thread below normal priority (Windows; elsewhere nothing): prints yield to the
/// player's worker and the window (the process runs at the high class,
/// `player::raise_priority`). A draft's partition thread starts at normal priority.
pub(crate) fn lower_priority() {
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
    /// `slots` loaded from `config_dir` and printed on `input` (each with its sidechain,
    /// `print_chain`'s) in the background; `right`: a stereo input's right channel, printed
    /// through the same chain beside it (dual-mono: [`Print::right`]).
    pub fn spawn(
        config_dir: PathBuf,
        slots: Vec<Slot>,
        sidechains: Vec<Option<Arc<Vec<f32>>>>,
        input: Arc<Vec<f32>>,
        right: Option<Arc<Vec<f32>>>,
        rate: u32,
        cache: Option<PathBuf>,
    ) -> Job {
        Job::start(
            config_dir, slots, sidechains, input, right, rate, cache, true,
        )
    }

    /// The chain's prints looked up in `cache` only, none rendered: its result is
    /// [`NOT_PRINTED`] unless every insert's print is there (docs/SESSION_EDITING_PLAN.md
    /// SE1: prints are made when asked for, found in the cache whenever they exist).
    pub fn lookup(
        config_dir: PathBuf,
        slots: Vec<Slot>,
        sidechains: Vec<Option<Arc<Vec<f32>>>>,
        input: Arc<Vec<f32>>,
        right: Option<Arc<Vec<f32>>>,
        rate: u32,
        cache: PathBuf,
    ) -> Job {
        Job::start(
            config_dir,
            slots,
            sidechains,
            input,
            right,
            rate,
            Some(cache),
            false,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn start(
        config_dir: PathBuf,
        slots: Vec<Slot>,
        sidechains: Vec<Option<Arc<Vec<f32>>>>,
        input: Arc<Vec<f32>>,
        right: Option<Arc<Vec<f32>>>,
        rate: u32,
        cache: Option<PathBuf>,
        render: bool,
    ) -> Job {
        let progress = Arc::new(AtomicU64::new(0));
        let cancel = Arc::new(AtomicBool::new(false));
        let (p, c) = (progress.clone(), cancel.clone());
        let handle = std::thread::spawn(move || {
            lower_priority();
            let load = || {
                slots
                    .iter()
                    .map(|s| Prepared::load(&config_dir, &s.device, s.quality, s.noise))
                    .collect::<Result<Vec<_>, _>>()
            };
            let preps = load()?;
            // A right channel equal to the left (mono clips on a stereo lane) prints once.
            let right = right.filter(|r| **r != *input);
            // The right channel's devices: a tape machine's second track (its own grain,
            // the left's transport).
            let load_right = || -> Result<Vec<Prepared>, String> {
                Ok(load()?
                    .into_iter()
                    .map(|p| Prepared {
                        circuit: p.circuit.with_track(Some("r")),
                        ..p
                    })
                    .collect())
            };
            chain(
                &preps,
                Some(&load_right),
                &slots,
                &sidechains,
                &input,
                right,
                rate,
                cache.as_deref(),
                |k, f| {
                    p.store(
                        ((k as u64) << 32) | (f as f32).to_bits() as u64,
                        Ordering::Relaxed,
                    )
                },
                &c,
                render,
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
    use crate::render::render;

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
    fn a_tape_machine_prints_a_head_distance_early() {
        let mut slot = Slot::new("ampex_351_insert");
        let p = Prepared::load(&config(), &slot.device, slot.quality, slot.noise).unwrap();
        // 2 in between the heads at 15 ips (the manual's 133 ms), twice that at 7-1/2.
        let hi = latency_s(&p.circuit, &slot).unwrap();
        assert!((hi - 2.0 / 15.0).abs() < 1e-3, "{hi}");
        slot.values = vec![("speed".to_string(), Value::Int(0))];
        let lo = latency_s(&p.circuit, &slot).unwrap();
        assert!((lo - 2.0 * hi).abs() < 1e-9, "{lo}");
        let stage = stage(0.0);
        let q = Prepared::load(&config(), &stage.device, stage.quality, stage.noise).unwrap();
        assert_eq!(latency_s(&q.circuit, &stage).unwrap(), 0.0);
    }

    #[test]
    fn a_second_track_has_its_own_grain_and_key() {
        let x = tone(48_000, 0.05, 0.3);
        let slot = Slot::new("ampex_351_insert");
        let left = Prepared::load(&config(), &slot.device, slot.quality, slot.noise).unwrap();
        let right = Prepared::load(&config(), &slot.device, slot.quality, slot.noise).unwrap();
        let right = Prepared {
            circuit: right.circuit.with_track(Some("r")),
            ..right
        };
        let (a, b) = (
            left.circuit.build(&slot.values).unwrap(),
            right.circuit.build(&slot.values).unwrap(),
        );
        let tapes = |ir: &circuitsim::ir::CircuitIr| -> Vec<String> {
            ir.elements()
                .filter_map(|e| match e {
                    circuitsim::ir::Element::Tape(t) => Some(t.name.clone()),
                    _ => None,
                })
                .collect()
        };
        let (ta, tb) = (tapes(&a), tapes(&b));
        assert!(!ta.is_empty());
        assert_eq!(tb, ta.iter().map(|n| format!("{n}_r")).collect::<Vec<_>>());
        // Everything else is the same circuit.
        let mut b2 = b.clone();
        for (e, n) in b2
            .sections
            .iter_mut()
            .flat_map(|s| s.elements.iter_mut())
            .filter_map(|e| match e {
                circuitsim::ir::Element::Tape(t) => Some(t),
                _ => None,
            })
            .zip(&ta)
        {
            e.name = n.clone();
        }
        assert_eq!(
            serde_json::to_string(&a).unwrap(),
            serde_json::to_string(&b2).unwrap()
        );
        assert_ne!(
            key(&left, &slot, &x, None, 48_000).unwrap(),
            key(&right, &slot, &x, None, 48_000).unwrap()
        );
        // No tape: the track changes nothing.
        let st = stage(0.0);
        let p = Prepared::load(&config(), &st.device, st.quality, st.noise).unwrap();
        let k = key(&p, &st, &x, None, 48_000).unwrap();
        let q = Prepared {
            circuit: p.circuit.with_track(Some("r")),
            ..p
        };
        assert_eq!(k, key(&q, &st, &x, None, 48_000).unwrap());
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
        let a = print(&p, &slot, &x, None, rate, Some(&dir), |_| {}, &no).unwrap();
        assert!(!a.cached);
        assert_eq!(*a.audio, want);
        assert!(
            want.iter().any(|&y| y.abs() > 1e-3),
            "the stage passes the tone"
        );
        let b = print(&p, &slot, &x, None, rate, Some(&dir), |_| {}, &no).unwrap();
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
        let k0 = key(&p, &base, &x, None, rate).unwrap();
        assert_eq!(k0, key(&p, &base, &x, None, rate).unwrap());
        let mut y = (*x).clone();
        y[100] += 1e-6;
        assert_ne!(k0, key(&p, &base, &y, None, rate).unwrap(), "the audio");
        assert_ne!(k0, key(&p, &base, &x, None, 44_100).unwrap(), "the rate");
        let mut s = base.clone();
        s.makeup_db = 1.0;
        assert_ne!(k0, key(&p, &s, &x, None, rate).unwrap(), "a gain");
        // A panel value (the drawn stage has none: the 670's, only keyed, not rendered).
        let fc = Slot::new("fairchild_670");
        let pf = Prepared::load(&config(), &fc.device, fc.quality, true).unwrap();
        let mut s = fc.clone();
        s.values = vec![("ac_threshold".into(), Value::Float(0.31))];
        assert_ne!(
            key(&pf, &fc, &x, None, rate).unwrap(),
            key(&pf, &s, &x, None, rate).unwrap(),
            "a value"
        );
        let prod = Prepared::load(&config(), &base.device, Quality::Production, true).unwrap();
        assert_ne!(
            k0,
            key(&prod, &base, &x, None, rate).unwrap(),
            "the quality"
        );
        // Bypass and the quality field itself are not in the key: what was loaded is.
        let mut s = base.clone();
        s.bypass = true;
        assert_eq!(k0, key(&p, &s, &x, None, rate).unwrap());
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
        let a = print_chain(
            &load(&slots),
            &slots,
            &[],
            &x,
            rate,
            Some(&dir),
            |_, _| {},
            &no,
        )
        .unwrap();
        assert!(a.iter().all(|p| !p.cached));
        let mut edited = slots.clone();
        edited[1].makeup_db = -1.0;
        let b = print_chain(
            &load(&edited),
            &edited,
            &[],
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
            &[],
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
    fn a_stereo_input_prints_dual_mono() {
        // Each channel through its own copy of the chain with the same panel: the right's
        // print is the chain's print of the right alone (docs/STEREO_PLAN.md ST3).
        let rate = 48_000;
        let (l, r) = (tone(48_000, 0.1, 0.2), tone(48_000, 0.05, 0.2));
        let slots = vec![stage(-6.0)];
        let dir = temp("dual");
        let job = Job::spawn(
            config(),
            slots.clone(),
            vec![],
            l.clone(),
            Some(r.clone()),
            rate,
            Some(dir.clone()),
        );
        let p = job.join().expect("a result").expect("printed");
        let prep: Vec<Prepared> = slots
            .iter()
            .map(|s| Prepared::load(&config(), &s.device, s.quality, s.noise).unwrap())
            .collect();
        let no = AtomicBool::new(false);
        let alone = |x: &Arc<Vec<f32>>| {
            print_chain(&prep, &slots, &[], x, rate, None, |_, _| {}, &no).unwrap()
        };
        assert_eq!(p[0].audio, alone(&l)[0].audio);
        assert_eq!(p[0].right.as_ref(), Some(&alone(&r)[0].audio));
        // A right channel equal to the left prints once (none apart).
        let same = Job::spawn(
            config(),
            slots,
            vec![],
            l.clone(),
            Some(Arc::new((*l).clone())),
            rate,
            Some(dir.clone()),
        );
        let q = same.join().expect("a result").expect("printed");
        assert!(q[0].cached && q[0].right.is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// The 6G15 fully wet with its STEREO switch at `on` (the split tank), a short tail.
    fn spring(on: i64) -> Slot {
        let mut s = Slot::new("fender_6g15");
        s.values = vec![
            ("stereo".into(), Value::Int(on)),
            ("mixer".into(), Value::Float(1.0)),
        ];
        s.tail_s = 0.1;
        s
    }

    #[test]
    fn a_stereo_reverb_prints_both_channels_from_the_mid() {
        // docs/REVERB_PLAN.md "Stereo": a stereo insert takes the mid of its input and
        // gives both channels; inserts after it print dual-mono; STEREO off stays mono.
        let rate = 48_000;
        let no = AtomicBool::new(false);
        let (l, r) = (tone(rate, 0.1, 0.2), tone(rate, 0.1, 0.05));
        let on = spring(1);
        let prep = Prepared::load(&config(), &on.device, on.quality, on.noise).unwrap();
        assert!(stereo_out(&prep, &on).unwrap());
        assert!(!stereo_out(&prep, &spring(0)).unwrap());
        let off_bypassed = Slot {
            bypass: true,
            ..spring(1)
        };
        assert!(!stereo_out(&prep, &off_bypassed).unwrap());
        // A mono track: both channels, unlike each other (the tank's two springs).
        let dir = temp("stereo_reverb");
        let slots = vec![on.clone(), stage(-6.0)];
        let job = Job::spawn(
            config(),
            slots.clone(),
            vec![],
            l.clone(),
            None,
            rate,
            Some(dir.clone()),
        );
        let p = job.join().expect("a result").expect("printed");
        let right = p[0].right.as_ref().expect("a stereo print");
        assert_eq!(right.len(), p[0].audio.len());
        let diff: f32 = right
            .iter()
            .zip(p[0].audio.iter())
            .map(|(a, b)| (a - b).abs())
            .sum();
        assert!(diff > 0.0);
        // The insert after it printed each side apart (the stage alone on the right).
        let stage_alone = |x: &Arc<Vec<f32>>| {
            let pr = vec![
                Prepared::load(&config(), "triode_stage_drawn", Quality::Draft1x, true).unwrap(),
            ];
            print_chain(&pr, &slots[1..], &[], x, rate, None, |_, _| {}, &no).unwrap()
        };
        assert_eq!(p[1].right.as_ref(), Some(&stage_alone(right)[0].audio));
        // Cached as two channels.
        let again = Job::spawn(
            config(),
            slots,
            vec![],
            l.clone(),
            None,
            rate,
            Some(dir.clone()),
        )
        .join()
        .expect("a result")
        .expect("printed");
        assert!(again[0].cached && again[0].right.as_ref() == Some(right));
        // A stereo input: its mid through the tank, each side's dry its own (fully wet:
        // the device's outputs alone, the mid's).
        let (a, b, _) =
            print_uncached_stereo(&prep, &on, &l, Some(&r), None, rate, |_| {}, &no).unwrap();
        let m: Vec<f32> = l.iter().zip(r.iter()).map(|(x, y)| 0.5 * (x + y)).collect();
        let (am, bm, _) =
            print_uncached_stereo(&prep, &on, &m, None, None, rate, |_| {}, &no).unwrap();
        assert_eq!((a, b), (am, bm));
        // STEREO off: a mono print, as before.
        let off = print_chain(&[prep], &[spring(0)], &[], &l, rate, None, |_, _| {}, &no).unwrap();
        assert!(off[0].right.is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_cancelled_print_leaves_nothing() {
        let (rate, x) = (48_000, tone(48_000, 0.3, 0.3));
        let dir = temp("cancel");
        let job = Job::spawn(
            config(),
            vec![stage(0.0)],
            vec![],
            x,
            None,
            rate,
            Some(dir.clone()),
        );
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
        let mut k = Slot::new("fairchild_670_keyed");
        k.key = Some(KeyRoute {
            track: "t2".into(),
            trim_db: -3.5,
        });
        assert_eq!(Slot::from_json(&k.to_json()).unwrap(), k);
    }

    /// A kick every 0.25 s from `t0_s` (a decaying sine falling from 150 to 50 Hz).
    fn kicks(rate: u32, s: f64, t0_s: f64, amp: f64) -> Arc<Vec<f32>> {
        let n = (s * rate as f64) as usize;
        let mut phase = 0.0;
        Arc::new(
            (0..n)
                .map(|i| {
                    let t = i as f64 / rate as f64;
                    if t < t0_s {
                        return 0.0;
                    }
                    let u = (t - t0_s) % 0.25;
                    phase += 2.0 * std::f64::consts::PI * (50.0 + 100.0 * (-u / 0.03).exp())
                        / rate as f64;
                    (amp * phase.sin() * (-u / 0.12).exp()) as f32
                })
                .collect(),
        )
    }

    fn keyed(trim_db: f64) -> Slot {
        let mut s = Slot::new("fairchild_670_keyed");
        s.values = vec![
            ("key_mode".into(), Value::Int(1)),
            ("time_constant".into(), Value::Int(1)),
            ("key_depth".into(), Value::Float(1.0)), // no limit: the keyed 670 as it is
        ];
        s.tail_s = 0.0;
        s.key = Some(KeyRoute {
            track: "kick".into(),
            trim_db,
        });
        s
    }

    #[test]
    fn the_key_follows_the_sidechain() {
        let (rate, x) = (48_000, tone(48_000, 0.05, 0.1));
        let side = kicks(rate, 0.05, 0.0, 0.3);
        let s = keyed(0.0);
        let p = Prepared::load(&config(), &s.device, s.quality, true).unwrap();
        let none = key(&p, &s, &x, None, rate).unwrap();
        let k0 = key(&p, &s, &x, Some(&side), rate).unwrap();
        assert_ne!(none, k0, "a sidechain");
        let mut louder = (*side).clone();
        louder[10] += 1e-6;
        assert_ne!(
            k0,
            key(&p, &s, &x, Some(&louder), rate).unwrap(),
            "its audio"
        );
        assert_ne!(
            k0,
            key(&p, &keyed(-1.0), &x, Some(&side), rate).unwrap(),
            "its trim"
        );
        // Without a route the sidechain isn't heard, so it isn't keyed either.
        let mut off = s.clone();
        off.key = None;
        assert_eq!(
            key(&p, &off, &x, None, rate).unwrap(),
            key(&p, &off, &x, Some(&side), rate).unwrap()
        );
    }

    #[test]
    fn a_keyed_print_ducks_under_its_sidechain() {
        // A bass tone (110 Hz at -18 dBFS) through the keyed 670 at EXT, kicks from 0.3 s.
        let rate = 48_000;
        let n = (0.8 * rate as f64) as usize;
        let x: Arc<Vec<f32>> = Arc::new(
            (0..n)
                .map(|i| {
                    let t = i as f64 / rate as f64;
                    (0.126 * (2.0 * std::f64::consts::PI * 110.0 * t).sin() * (t * 20.0).min(1.0))
                        as f32
                })
                .collect(),
        );
        let side = kicks(rate, 0.8, 0.3, 0.5);
        let s = keyed(0.0);
        let p = Prepared::load(&config(), &s.device, s.quality, true).unwrap();
        let no = AtomicBool::new(false);
        let rms = |y: &[f32], a: f64, b: f64| {
            let w = &y[(a * rate as f64) as usize..(b * rate as f64) as usize];
            (w.iter().map(|&v| (v as f64).powi(2)).sum::<f64>() / w.len() as f64).sqrt()
        };
        let plain = print(&p, &s, &x, None, rate, None, |_| {}, &no).unwrap();
        let ducked = print(&p, &s, &x, Some(&side), rate, None, |_| {}, &no).unwrap();
        let before = rms(&ducked.audio, 0.2, 0.3);
        assert!((rms(&plain.audio, 0.2, 0.3) - before).abs() < 1e-6 * before);
        let during = rms(&ducked.audio, 0.31, 0.36);
        let unkeyed = rms(&plain.audio, 0.31, 0.36);
        assert!(
            during < 0.3 * before,
            "a kick ducks the bass ({during} vs {before})"
        );
        assert!(unkeyed > 0.9 * before, "without the key it doesn't");
    }

    /// The stereo 670 (STEREO_PLAN.md ST3b) on a track: one run with the left on `in` and the
    /// right on its audio input `in_r`, a mono track's into both.
    #[test]
    fn the_stereo_670_prints_both_channels_in_one_run() {
        let rate = 48_000;
        let mut slot = Slot::new("fairchild_670_stereo");
        slot.tail_s = 0.05;
        let prep = Prepared::load(&config(), &slot.device, slot.quality, slot.noise).unwrap();
        assert!(two_inputs(&prep, &slot));
        let bypassed = Slot {
            bypass: true,
            ..slot.clone()
        };
        assert!(!two_inputs(&prep, &bypassed));
        let print = |slot: &Slot, l: &Arc<Vec<f32>>, r: Option<Arc<Vec<f32>>>| {
            Job::spawn(
                config(),
                vec![slot.clone()],
                vec![],
                l.clone(),
                r,
                rate,
                None,
            )
            .join()
            .expect("a result")
            .expect("printed")
            .remove(0)
        };
        let rms = |x: &[f32]| {
            (x.iter().map(|v| (*v as f64).powi(2)).sum::<f64>() / x.len() as f64).sqrt()
        };
        let (l, r) = (tone(rate, 0.15, 0.3), tone(rate, 0.15, 0.03));
        // A mono track into both: the two channels alike.
        let mono = print(&slot, &l, None);
        let right = mono.right.as_ref().expect("a stereo print");
        let d: Vec<f32> = mono
            .audio
            .iter()
            .zip(right.iter())
            .map(|(a, b)| a - b)
            .collect();
        assert!(
            rms(&d) < 1e-3 * rms(&mono.audio),
            "{} vs {}",
            rms(&d),
            rms(&mono.audio)
        );
        // A stereo track: each channel its own side, in one run.
        let st = print(&slot, &l, Some(r.clone()));
        let right = st.right.as_ref().expect("a stereo print");
        assert!(rms(right) < 0.3 * rms(&st.audio));
        assert_eq!(st.audio.len(), mono.audio.len());
        // LATERAL & VERTICAL: the left alone comes back on the left only (the matrix's
        // cancellation; the manual's separation).
        let mut lv = slot.clone();
        lv.values = vec![("mode".into(), Value::Int(2))];
        let silent = Arc::new(vec![0.0f32; l.len()]);
        let p = print(&lv, &l, Some(silent));
        let right = p.right.as_ref().expect("a stereo print");
        assert!(
            rms(right) < 1e-4 * rms(&p.audio),
            "{} vs {}",
            rms(right),
            rms(&p.audio)
        );
    }
}
