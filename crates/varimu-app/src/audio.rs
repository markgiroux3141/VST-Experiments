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

/// Stereo float32 WAV, frames of (left, right).
pub fn write_wav_stereo(path: &Path, x: &[[f32; 2]], sample_rate: u32) -> Result<(), String> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| err(path, e))?;
    }
    let spec = hound::WavSpec {
        channels: 2,
        sample_rate,
        bits_per_sample: 32,
        sample_format: hound::SampleFormat::Float,
    };
    let mut w = hound::WavWriter::create(path, spec).map_err(|e| err(path, e))?;
    for f in x {
        w.write_sample(f[0]).map_err(|e| err(path, e))?;
        w.write_sample(f[1]).map_err(|e| err(path, e))?;
    }
    w.finalize().map_err(|e| err(path, e))
}

/// The start and end (s) of `x`'s loudest stretch of `len_s` (by energy, in steps of
/// a tenth of it); the whole file if it is shorter.
pub fn loudest(x: &[f64], rate: u32, len_s: f64) -> (f64, f64) {
    let total = x.len() as f64 / rate as f64;
    if total <= len_s {
        return (0.0, total);
    }
    let n = (len_s * rate as f64) as usize;
    let hop = (n / 10).max(1);
    let energy: Vec<f64> = x
        .chunks(hop)
        .map(|c| c.iter().map(|v| v * v).sum())
        .collect();
    let k = n / hop;
    let mut best = (0, f64::MIN);
    let mut sum: f64 = energy[..k].iter().sum();
    for i in 0..=energy.len() - k {
        if sum > best.1 {
            best = (i, sum);
        }
        if i + k < energy.len() {
            sum += energy[i + k] - energy[i];
        }
    }
    let a = (best.0 * hop) as f64 / rate as f64;
    (a, (a + len_s).min(total))
}

/// The level of `x`'s loudest `len_s` (the Play view's normalization measures a file
/// this way): its rms as a sine's peak (dBFS), -240 for silence.
pub fn level_dbfs(x: &[f64], rate: u32, len_s: f64) -> f64 {
    if x.is_empty() {
        return -240.0;
    }
    let (a, b) = loudest(x, rate, len_s);
    let (i, j) = ((a * rate as f64) as usize, (b * rate as f64) as usize);
    let w = &x[i.min(x.len())..j.min(x.len())];
    let rms = (w.iter().map(|v| v * v).sum::<f64>() / w.len().max(1) as f64).sqrt();
    20.0 * (rms * 2f64.sqrt()).max(1e-12).log10()
}

/// Gains (dB) that bring each of `files` to `target_dbfs` by [`level_dbfs`] over
/// `len_s` (`together`: one gain for all, from their sum with every file starting
/// together, so their balance stays), within +-40 dB as the Play view's; silence gets 0 dB.
pub fn normalize_gains_db(
    files: &[Vec<f64>],
    rate: u32,
    len_s: f64,
    target_dbfs: f64,
    together: bool,
) -> Vec<f64> {
    let gain = |x: &[f64]| {
        let level = level_dbfs(x, rate, len_s);
        if level <= -240.0 + 1e-9 || x.iter().all(|&v| v == 0.0) {
            0.0
        } else {
            (target_dbfs - level).clamp(-40.0, 40.0)
        }
    };
    if !together {
        return files.iter().map(|x| gain(x)).collect();
    }
    let mut sum = vec![0.0; files.iter().map(Vec::len).max().unwrap_or(0)];
    for x in files {
        for (s, v) in sum.iter_mut().zip(x) {
            *s += v;
        }
    }
    vec![gain(&sum); files.len()]
}

#[cfg(test)]
mod tests {
    use super::{level_dbfs, loudest, normalize_gains_db};

    #[test]
    fn normalizing_each_or_together() {
        let rate = 1000;
        let sine = |a: f64, n: usize| -> Vec<f64> {
            (0..n)
                .map(|i| a * (2.0 * std::f64::consts::PI * 50.0 * i as f64 / rate as f64).sin())
                .collect()
        };
        // A full-scale sine is 0 dBFS (its rms as a sine's peak).
        assert!(level_dbfs(&sine(1.0, 2000), rate, 1.0).abs() < 1e-6);
        let files = vec![sine(0.5, 3000), sine(0.1, 2000), vec![0.0; 500]];
        let each = normalize_gains_db(&files, rate, 1.0, -18.0, false);
        assert!((each[0] - (-18.0 + 6.0206)).abs() < 1e-3, "{each:?}");
        assert!((each[1] - (-18.0 + 20.0)).abs() < 1e-3, "{each:?}");
        assert_eq!(each[2], 0.0);
        // Together: in phase, the sum is 0.6 for the first 2 s; one gain for all.
        let tog = normalize_gains_db(&files, rate, 1.0, -18.0, true);
        let want = -18.0 - 20.0 * 0.6f64.log10();
        assert!(tog.iter().all(|g| (g - want).abs() < 1e-3), "{tog:?}");
    }

    #[test]
    fn loudest_finds_the_loud_stretch() {
        let rate = 1000;
        let x: Vec<f64> = (0..60_000)
            .map(|i| {
                if (32_000..40_000).contains(&i) {
                    0.5
                } else {
                    0.001
                }
            })
            .collect();
        assert_eq!(loudest(&x, rate, 8.0), (32.0, 40.0)); // on the 0.8 s grid
        // At the very end, and a file shorter than the region.
        let y: Vec<f64> = (0..20_000)
            .map(|i| if i >= 12_000 { 0.5 } else { 0.0 })
            .collect();
        assert_eq!(loudest(&y, rate, 8.0), (12.0, 20.0));
        assert_eq!(loudest(&y[..5000], rate, 8.0), (0.0, 5.0));
    }
}
