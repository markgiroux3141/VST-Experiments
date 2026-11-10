//! Audio editing's signal work for the Session view's clips (docs/SESSION_EDITING_PLAN.md
//! SE8): where a sound starts (onsets, for splitting a drum take at its hits), where it is
//! silent (strip silence), the nearest zero crossing (a split that doesn't click), a tape
//! splice's crossfade, and varispeed (pitch and time together, as a tape machine's capstan
//! does it: no time-stretching).
//!
//! Everything here is plain arithmetic on a take's samples; the session lays the results
//! out as clips (`crate::session::Track`), and what changes the audio itself (reverse,
//! varispeed) is written as a new take, never over the old one.

use crate::resample::{Pad, resample_poly};

/// A 1/4-inch tape's width (m): what a splicing block cuts across.
pub const TAPE_WIDTH_M: f64 = 0.25 * 0.0254;

/// How long a splice made at `angle_deg` (between the cut and the tape's length; 90: a
/// butt splice) takes to pass a reproduce head at `speed_ips` (s). As the splice crosses
/// the head's gap, the share of the gap over the new tape grows linearly in time, so a
/// splice is a linear crossfade in amplitude of this length (the gap's own few
/// micrometres aside).
pub fn splice_s(angle_deg: f64, speed_ips: f64) -> f64 {
    let t = angle_deg.to_radians().tan();
    if !t.is_finite() || t > 1e6 || speed_ips <= 0.0 {
        return 0.0;
    }
    TAPE_WIDTH_M / t / (speed_ips * 0.0254)
}

/// The splicing blocks offered: (label, angle, speed).
pub const SPLICES: [(&str, f64, f64); 4] = [
    ("45° at 15 ips", 45.0, 15.0),
    ("60° at 15 ips", 60.0, 15.0),
    ("45° at 7.5 ips", 45.0, 7.5),
    ("60° at 7.5 ips", 60.0, 7.5),
];

/// The index of the zero crossing nearest `at` within `radius` samples (a sample where the
/// sign changes from the one before it, or an exact zero), else `at`. A cut there starts
/// and ends near silence.
pub fn nearest_zero_crossing(x: &[f32], at: usize, radius: usize) -> usize {
    if x.len() < 2 || at >= x.len() {
        return at;
    }
    let crossing =
        |i: usize| i >= 1 && i < x.len() && (x[i] == 0.0 || (x[i - 1] < 0.0) != (x[i] < 0.0));
    for d in 0..=radius {
        if crossing(at + d) {
            return at + d;
        }
        if d <= at && crossing(at - d) {
            return at - d;
        }
    }
    at
}

/// Short-time levels (dB of the mean square, full scale 0) of `x` in hops of `hop`
/// samples.
fn hop_levels(x: &[f32], hop: usize) -> Vec<f64> {
    x.chunks(hop.max(1))
        .map(|c| {
            let ms = c.iter().map(|&v| (v as f64) * (v as f64)).sum::<f64>() / c.len() as f64;
            10.0 * ms.max(1e-14).log10()
        })
        .collect()
}

/// Where the sounds in `x` start (sample indices, rising): a hop of 2.5 ms whose
/// high-passed level (the first difference: a hit's attack is brighter than its decay)
/// rises `sensitivity_db` above the quietest of the 30 ms before it, at least
/// `min_gap_s` after the last onset and above -60 dBFS; each placed at the first sample of
/// the attack reaching a quarter of its first 5 ms' peak.
pub fn onsets(x: &[f32], rate: u32, sensitivity_db: f64, min_gap_s: f64) -> Vec<usize> {
    let hop = ((rate as f64 * 0.0025).round() as usize).max(1);
    let d: Vec<f32> = std::iter::once(0.0)
        .chain(x.windows(2).map(|w| w[1] - w[0]))
        .collect();
    let lv = hop_levels(&d, hop);
    let back = ((0.030 * rate as f64) / hop as f64).ceil().max(1.0) as usize;
    let gap = (min_gap_s * rate as f64) as usize;
    let mut out: Vec<usize> = Vec::new();
    for k in 1..lv.len() {
        if lv[k] < -60.0 {
            continue;
        }
        let lo = lv[k.saturating_sub(back)..k]
            .iter()
            .copied()
            .fold(f64::INFINITY, f64::min);
        if lv[k] - lo < sensitivity_db {
            continue;
        }
        // The attack's first sample: from the hop before, the first reaching a quarter of
        // the peak in the 5 ms from there.
        let a = (k - 1) * hop;
        let b = (a + 3 * hop).min(x.len());
        let peak = x[a..b].iter().fold(0.0f32, |m, v| m.max(v.abs()));
        let at = x[a..b]
            .iter()
            .position(|v| v.abs() >= 0.25 * peak)
            .map_or(k * hop, |i| a + i);
        if out.last().is_some_and(|&p| at < p + gap) {
            continue;
        }
        out.push(at);
    }
    out
}

/// The first sample of `x` reaching a quarter of the peak of its first `window_s` (a
/// clip's attack: what Quantize puts on the grid), or 0 for silence.
pub fn attack(x: &[f32], rate: u32, window_s: f64) -> usize {
    let n = ((window_s * rate as f64) as usize).min(x.len());
    let peak = x[..n].iter().fold(0.0f32, |m, v| m.max(v.abs()));
    if peak <= 1e-6 {
        return 0;
    }
    x[..n]
        .iter()
        .position(|v| v.abs() >= 0.25 * peak)
        .unwrap_or(0)
}

/// The stretches of `x` that sound (sample ranges, rising): 10 ms windows above
/// `threshold_dbfs` (rms as a sine's peak, as the session's levels read), silences shorter
/// than `min_silence_s` bridged, each stretch padded by `pad_s` both ways.
pub fn sounding(
    x: &[f32],
    rate: u32,
    threshold_dbfs: f64,
    min_silence_s: f64,
    pad_s: f64,
) -> Vec<(usize, usize)> {
    let hop = ((rate as f64 * 0.010).round() as usize).max(1);
    // A sine's peak is its rms + 3 dB.
    let lv: Vec<f64> = hop_levels(x, hop).into_iter().map(|l| l + 3.01).collect();
    let mut runs: Vec<(usize, usize)> = Vec::new();
    for (k, &l) in lv.iter().enumerate() {
        if l < threshold_dbfs {
            continue;
        }
        let (a, b) = (k * hop, ((k + 1) * hop).min(x.len()));
        match runs.last_mut() {
            Some(r) if a <= r.1 + (min_silence_s * rate as f64) as usize => r.1 = b,
            _ => runs.push((a, b)),
        }
    }
    let pad = (pad_s * rate as f64) as usize;
    let mut out: Vec<(usize, usize)> = Vec::new();
    for (a, b) in runs {
        let (a, b) = (a.saturating_sub(pad), (b + pad).min(x.len()));
        match out.last_mut() {
            Some(r) if a <= r.1 => r.1 = b,
            _ => out.push((a, b)),
        }
    }
    out
}

/// The speed ratio for `semitones` (2: an octave up, twice as fast).
pub fn varispeed_ratio(semitones: f64) -> f64 {
    2f64.powf(semitones / 12.0)
}

/// `r` as a fraction p / q, both at most `max` (continued fractions: the best there is).
pub fn fraction(r: f64, max: u64) -> (u64, u64) {
    let (mut h0, mut h1, mut k0, mut k1) = (0u64, 1u64, 1u64, 0u64);
    let mut x = r;
    let mut best = (r.round().max(1.0) as u64, 1u64);
    for _ in 0..64 {
        let a = x.floor();
        let ai = a as u64;
        let (h2, k2) = (
            ai.saturating_mul(h1).saturating_add(h0),
            ai.saturating_mul(k1).saturating_add(k0),
        );
        if h2 > max || k2 > max || k2 == 0 {
            break;
        }
        best = (h2, k2);
        (h0, h1, k0, k1) = (h1, h2, k1, k2);
        let f = x - a;
        if f < 1e-12 {
            break;
        }
        x = 1.0 / f;
    }
    best
}

/// `x` played `semitones` faster (slower below 0), pitch and time together, as a tape
/// played at another speed: resampled by the ratio as a fraction of numbers up to 1000
/// (within ~0.01 cent), with scipy's Kaiser low-pass (`crate::resample`), so speeding up
/// doesn't alias.
pub fn varispeed(x: &[f32], semitones: f64) -> Vec<f32> {
    let (p, q) = fraction(varispeed_ratio(semitones), 1000);
    if p == q {
        return x.to_vec();
    }
    let y: Vec<f64> = x.iter().map(|&v| v as f64).collect();
    resample_poly(&y, q as usize, p as usize, Pad::Zero)
        .into_iter()
        .map(|v| v as f32)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Decaying noise bursts at `at` (a drum take's hits).
    fn hits(rate: u32, at: &[usize], len: usize) -> Vec<f32> {
        let mut x = vec![0.0f32; len];
        let mut seed = 12345u64;
        for &a in at {
            for i in 0..(rate as usize / 5).min(len - a) {
                seed = seed
                    .wrapping_mul(6364136223846793005)
                    .wrapping_add(1442695040888963407);
                let n = ((seed >> 33) as f32 / (1u64 << 31) as f32) * 2.0 - 1.0;
                x[a + i] += 0.6 * n * (-(i as f32) / (0.03 * rate as f32)).exp();
            }
        }
        x
    }

    #[test]
    fn onsets_find_each_hit_within_a_millisecond() {
        let rate = 48_000;
        let at = [4_800, 20_000, 31_111, 52_000];
        let x = hits(rate, &at, 70_000);
        let found = onsets(&x, rate, 9.0, 0.05);
        assert_eq!(found.len(), at.len(), "{found:?}");
        for (f, a) in found.iter().zip(at) {
            assert!((*f as i64 - a as i64).abs() <= 48, "{f} vs {a}");
        }
        // Silence has none.
        assert!(onsets(&vec![0.0; 10_000], rate, 9.0, 0.05).is_empty());
    }

    #[test]
    fn silence_is_stripped_and_short_gaps_bridged() {
        let rate = 1000;
        let mut x = vec![0.0f32; 3000];
        for v in &mut x[500..800] {
            *v = 0.5;
        }
        for v in &mut x[850..900] {
            *v = 0.5; // 50 ms after: bridged at 100 ms
        }
        for v in &mut x[2000..2100] {
            *v = 0.5;
        }
        let r = sounding(&x, rate, -40.0, 0.1, 0.02);
        assert_eq!(r, vec![(480, 920), (1980, 2120)]);
    }

    #[test]
    fn a_zero_crossing_is_found_nearby() {
        let x: Vec<f32> = (0..1000).map(|i| (i as f32 * 0.05).sin()).collect();
        let z = nearest_zero_crossing(&x, 70, 40);
        // sin crosses zero every pi / 0.05 = 62.8 samples: 62.8 -> 63.
        assert_eq!(z, 63);
        assert!(x[z - 1] > 0.0 && x[z] < 0.0);
        assert_eq!(nearest_zero_crossing(&vec![1.0; 100], 50, 10), 50);
    }

    #[test]
    fn varispeed_moves_pitch_and_length_together() {
        let rate = 48_000;
        let x: Vec<f32> = (0..rate)
            .map(|i| (2.0 * std::f32::consts::PI * 440.0 * i as f32 / rate as f32).sin())
            .collect();
        let y = varispeed(&x, 12.0);
        assert_eq!(y.len(), x.len() / 2);
        // An octave up: 880 Hz (zero crossings in the middle second half).
        let mid = &y[2000..y.len() - 2000];
        let n = mid
            .windows(2)
            .filter(|w| (w[0] < 0.0) != (w[1] < 0.0))
            .count();
        let f = n as f64 / 2.0 / (mid.len() as f64 / rate as f64);
        assert!((f - 880.0).abs() < 2.0, "{f}");
        let (p, q) = fraction(varispeed_ratio(1.0), 1000);
        let cents = 1200.0 * (p as f64 / q as f64 / varispeed_ratio(1.0)).log2();
        assert!(cents.abs() < 0.01, "{cents}");
        assert_eq!(varispeed(&x, 0.0), x);
    }

    #[test]
    fn a_splice_crossfades_for_its_angle_and_speed() {
        assert!((splice_s(45.0, 15.0) - 1.0 / 60.0).abs() < 1e-9);
        assert!((splice_s(45.0, 7.5) - 1.0 / 30.0).abs() < 1e-9);
        assert!(splice_s(60.0, 15.0) < splice_s(45.0, 15.0));
        assert_eq!(splice_s(90.0, 15.0), 0.0);
    }

    #[test]
    fn an_attack_is_found_after_a_quiet_lead() {
        let mut x = vec![0.001f32; 1000];
        x[300] = 0.5;
        x[301] = -0.8;
        assert_eq!(attack(&x, 1000, 0.5), 300);
    }
}
