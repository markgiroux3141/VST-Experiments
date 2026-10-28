//! Audio files: any file symphonia decodes (WAV, AIFF, FLAC, Ogg Vorbis, MP3, ...) as
//! mono float64 at the project's rate, as `varimu.sim.io.load_audio` reads them; and
//! mono float32 WAV out (`write_audio`, the project's convention).
//!
//! Loading equals Python's bit for bit for PCM and float files: integer samples are
//! scaled by powers of two (as libsndfile does), channels averaged as numpy's `mean`
//! does, and the rate converted by scipy's `resample_poly` (`crate::resample`).
//! Lossy formats decode with symphonia's decoders, not libsndfile's.

use std::fs::File;
use std::path::Path;

use symphonia::core::codecs::audio::AudioDecoderOptions;
use symphonia::core::errors::Error as SymphoniaError;
use symphonia::core::formats::probe::Hint;
use symphonia::core::formats::{FormatOptions, TrackType};
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;

use crate::resample::{Pad, resample_poly};

/// A decoded file: its channels and rate.
#[derive(Debug, Clone)]
pub struct Decoded {
    pub channels: Vec<Vec<f64>>,
    pub rate: u32,
}

impl Decoded {
    pub fn frames(&self) -> usize {
        self.channels.first().map_or(0, Vec::len)
    }

    /// The channels averaged (numpy's `x.mean(axis=1)`: summed in order, divided by
    /// their count).
    pub fn mono(&self) -> Vec<f64> {
        let n = self.channels.len() as f64;
        (0..self.frames())
            .map(|i| {
                let mut s = self.channels[0][i];
                for c in &self.channels[1..] {
                    s += c[i];
                }
                s / n
            })
            .collect()
    }
}

fn err(path: &Path, what: impl std::fmt::Display) -> String {
    format!("{}: {what}", path.display())
}

/// Decode every channel of the file's default audio track.
pub fn decode(path: &Path) -> Result<Decoded, String> {
    let file = File::open(path).map_err(|e| err(path, e))?;
    let mss = MediaSourceStream::new(Box::new(file), Default::default());
    let mut hint = Hint::new();
    if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
        hint.with_extension(ext);
    }
    let mut format = symphonia::default::get_probe()
        .probe(
            &hint,
            mss,
            FormatOptions::default(),
            MetadataOptions::default(),
        )
        .map_err(|e| err(path, format!("not an audio file symphonia reads ({e})")))?;
    let track = format
        .default_track(TrackType::Audio)
        .ok_or_else(|| err(path, "no audio track"))?;
    let params = track
        .codec_params
        .as_ref()
        .and_then(|p| p.audio())
        .ok_or_else(|| err(path, "no audio codec parameters"))?;
    let mut rate = params.sample_rate;
    let mut decoder = symphonia::default::get_codecs()
        .make_audio_decoder(params, &AudioDecoderOptions::default())
        .map_err(|e| err(path, e))?;
    let track_id = track.id;
    let mut channels: Vec<Vec<f64>> = Vec::new();
    let mut block: Vec<Vec<f64>> = Vec::new();
    loop {
        let packet = match format.next_packet() {
            Ok(Some(p)) => p,
            Ok(None) => break,
            Err(SymphoniaError::IoError(e)) if e.kind() == std::io::ErrorKind::UnexpectedEof => {
                break;
            }
            Err(e) => return Err(err(path, e)),
        };
        if packet.track_id != track_id {
            continue;
        }
        let buf = match decoder.decode(&packet) {
            Ok(b) => b,
            Err(SymphoniaError::DecodeError(_)) => continue, // a corrupt packet: skip it
            Err(e) => return Err(err(path, e)),
        };
        rate = rate.or(Some(buf.spec().rate()));
        buf.copy_to_vecs_planar::<f64>(&mut block);
        if channels.is_empty() {
            channels = vec![Vec::new(); block.len()];
        }
        for (c, b) in channels.iter_mut().zip(&block) {
            c.extend_from_slice(b);
        }
    }
    let rate = rate.ok_or_else(|| err(path, "unknown sample rate"))?;
    if channels.is_empty() || channels[0].is_empty() {
        return Err(err(path, "no audio in the file"));
    }
    Ok(Decoded { channels, rate })
}

/// The file as mono float64 at `sample_rate` (`varimu.sim.io.load_audio`).
pub fn load(path: &Path, sample_rate: u32) -> Result<Vec<f64>, String> {
    let d = decode(path)?;
    let x = d.mono();
    if d.rate == sample_rate {
        return Ok(x);
    }
    Ok(resample_poly(
        &x,
        sample_rate as usize,
        d.rate as usize,
        Pad::Zero,
    ))
}

/// Mono float32 WAV (`varimu.sim.io.write_audio`).
pub fn write_wav(path: &Path, x: &[f64], sample_rate: u32) -> Result<(), String> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| err(path, e))?;
    }
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate,
        bits_per_sample: 32,
        sample_format: hound::SampleFormat::Float,
    };
    let mut w = hound::WavWriter::create(path, spec).map_err(|e| err(path, e))?;
    for &v in x {
        w.write_sample(v as f32).map_err(|e| err(path, e))?;
    }
    w.finalize().map_err(|e| err(path, e))
}
