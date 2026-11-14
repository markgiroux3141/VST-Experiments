//! A played device's speakers heard after it (docs/INSTRUMENT_REALISM_FABLE.md, SC1).
//!
//! Live, a device with `live_speaker_v` plays its speakers' terminal voltage: the speakers
//! stay in the circuit as loads, their pressure readouts out (their states cost Play more
//! than the amp). A speaker part without a field winding is linear, and its readout draws no
//! current, so the pressure 1 m in front is a fixed linear filter of that voltage whatever
//! the amp does: `scripts/suitcase_speaker_filter.py` measures it from the circuit file by AC
//! analysis and saves `config/speaker_filters/<circuit>.json` (per channel, an impulse
//! response in pascals per terminal volt at each host rate, the circuit file's sha256, the
//! filter's latency in samples). [`SpeakerFilter::load`] refuses a filter whose circuit
//! changed since (stale, as a tape reduction is), or that has no impulse at the host rate.
//!
//! Heard so, the device's output is the circuit file's own pressure (its `full_scale`, as
//! a render's): [`crate::live::Circuit::full_scale`] reports it and the stream's output,
//! normalised to it, goes through [`Speakers`] (circuitsim's zero-latency partitioned
//! [`Convolver`]) after the host-rate resampler and any restart's crossfade, so the cones'
//! state carries across knob rebuilds.

use std::path::{Path, PathBuf};

use circuitsim::convolve::Convolver;
use sha2::{Digest, Sha256};

/// Device id -> the circuit whose filter it may play (the file's name in
/// `config/speaker_filters/`).
pub const DEVICES: &[(&str, &str)] = &[("rhodes_suitcase", "rhodes_suitcase_100w")];

/// The convolvers' block: taps 1..=BLOCK direct, the rest by FFTs of twice it.
const BLOCK: usize = 128;

/// The filter of `device` id, if it has one.
pub fn circuit_of(device: &str) -> Option<&'static str> {
    DEVICES.iter().find(|(d, _)| *d == device).map(|(_, c)| *c)
}

/// The saved filter of a circuit file.
pub fn path_for(circuit_file: &Path) -> Option<PathBuf> {
    let stem = circuit_file.file_stem()?.to_str()?;
    let config = circuit_file.parent()?.parent()?;
    Some(config.join("speaker_filters").join(format!("{stem}.json")))
}

/// A circuit's speaker filter at one host rate.
#[derive(Debug, Clone, PartialEq)]
pub struct SpeakerFilter {
    /// Impulse responses, pascals per terminal volt, `out` then `out_r` (when stereo).
    pub channels: Vec<Vec<f64>>,
    /// Samples the filtered output lags the terminal voltage (the band-limited onset's
    /// pre-ring kept ahead of it).
    pub latency: usize,
}

impl SpeakerFilter {
    /// The filter saved for `circuit_file` at `rate` Hz.
    pub fn load(circuit_file: &Path, rate: u32) -> Result<SpeakerFilter, String> {
        let path = path_for(circuit_file)
            .ok_or_else(|| format!("{}: no speaker filter path", circuit_file.display()))?;
        let text = std::fs::read_to_string(&path).map_err(|e| {
            format!(
                "{}: {e} (run scripts/suitcase_speaker_filter.py)",
                path.display()
            )
        })?;
        let v: serde_json::Value =
            serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
        let bytes =
            std::fs::read(circuit_file).map_err(|e| format!("{}: {e}", circuit_file.display()))?;
        // CRLF read as LF: a checkout's line endings aren't a change of circuit.
        let mut lf = Vec::with_capacity(bytes.len());
        for (i, &b) in bytes.iter().enumerate() {
            if !(b == b'\r' && bytes.get(i + 1) == Some(&b'\n')) {
                lf.push(b);
            }
        }
        let sha = format!("{:x}", Sha256::digest(&lf));
        if v["circuit_sha256"].as_str() != Some(sha.as_str()) {
            return Err(format!(
                "{}: stale (its circuit changed): rerun scripts/suitcase_speaker_filter.py",
                path.display()
            ));
        }
        let key = rate.to_string();
        let latency = v["latency_samples"][&key]
            .as_u64()
            .ok_or_else(|| format!("{}: no filter at {rate} Hz", path.display()))?
            as usize;
        let mut channels = Vec::new();
        for ch in ["out", "out_r"] {
            let Some(ir) = v["channels"][ch]["impulse_pa_per_v"][&key].as_array() else {
                continue;
            };
            let h: Option<Vec<f64>> = ir.iter().map(|x| x.as_f64()).collect();
            channels.push(h.ok_or_else(|| format!("{}: {ch} isn't numbers", path.display()))?);
        }
        if channels.is_empty() {
            return Err(format!("{}: no channel at {rate} Hz", path.display()));
        }
        Ok(SpeakerFilter { channels, latency })
    }
}

/// The filter running on a device's output, one convolver per channel.
pub struct Speakers {
    conv: Vec<Convolver>,
}

impl Speakers {
    pub fn new(f: &SpeakerFilter) -> Speakers {
        // Convolver::push(x[n]) returns sum_{k >= 1} h[k] x[n + 1 - k]: with h = [0, g..]
        // that is sum_{j >= 0} g[j] x[n - j], the output at n, no extra latency.
        let conv = f
            .channels
            .iter()
            .map(|g| {
                let mut h = Vec::with_capacity(g.len() + 1);
                h.push(0.0);
                h.extend_from_slice(g);
                Convolver::new(&h, BLOCK)
            })
            .collect();
        Speakers { conv }
    }

    /// Channel `ch`'s block through its filter, in place (a channel without a filter of its
    /// own takes the first's).
    pub fn process(&mut self, ch: usize, y: &mut [f64]) {
        let i = ch.min(self.conv.len() - 1);
        let c = &mut self.conv[i];
        for v in y.iter_mut() {
            *v = c.push(*v);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_convolver_is_the_direct_sum_without_latency() {
        let g: Vec<f64> = (0..300)
            .map(|k| ((k as f64) * 0.37).sin() / (1.0 + k as f64))
            .collect();
        let f = SpeakerFilter {
            channels: vec![g.clone()],
            latency: 0,
        };
        let mut s = Speakers::new(&f);
        let x: Vec<f64> = (0..1000)
            .map(|n| ((n * 7919) % 101) as f64 / 50.0 - 1.0)
            .collect();
        let mut y = x.clone();
        // In uneven blocks, as a stream's.
        let mut at = 0;
        for n in [17usize, 64, 1, 200, 718] {
            s.process(0, &mut y[at..at + n]);
            at += n;
        }
        for (n, &yn) in y.iter().enumerate() {
            let direct: f64 = (0..=n.min(g.len() - 1)).map(|j| g[j] * x[n - j]).sum();
            assert!((yn - direct).abs() < 1e-12, "sample {n}: {yn} vs {direct}");
        }
    }

    #[test]
    fn the_suitcase_filter_is_current_and_has_both_channels() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let circuit = root.join("config/circuits/rhodes_suitcase_100w.yaml");
        for rate in [44_100, 48_000, 96_000] {
            let f = SpeakerFilter::load(&circuit, rate).expect("current filter");
            assert_eq!(f.channels.len(), 2);
            assert!(f.latency > 0 && f.latency < rate as usize / 1000);
        }
        assert!(SpeakerFilter::load(&circuit, 22_050).is_err());
    }
}
