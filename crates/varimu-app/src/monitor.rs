//! What the player sends to the speakers: the device's output or its input (bypass),
//! with optional gain compensation, so the device can be compared with itself off at
//! the same loudness (CLAUDE.md: "Loudness lies").
//!
//! - **Bypass** plays the input as it went into the device (after the input gain),
//!   delayed by the engine's lag so the two line up; switching crossfades over 10 ms.
//!   The circuit keeps running either way, so switching back is instant.
//! - **Gain compensation** tracks the loudness of input and output (K-weighted as in
//!   ITU-R BS.1770, mean square over ~3 s, BS.1770's short-term window) and applies
//!   the difference to the output, smoothed over ~1 s so it doesn't act as a second
//!   compressor. It holds while the input is below BS.1770's absolute gate (-70 LUFS).
//!   Monitoring only: renders are the device as it is.
//! - **Output gain** is a manual gain on the device's output (not the bypassed input),
//!   on top of the compensation. Monitoring only too.

/// BS.1770's K-weighting: a high shelf (the head) and a high pass (RLB), as biquads
/// designed for any rate (libebur128's formulas; at 48 kHz they give BS.1770's
/// published coefficients).
#[derive(Debug, Clone)]
pub struct KWeighting {
    stages: [Biquad; 2],
}

#[derive(Debug, Clone, Copy)]
struct Biquad {
    b: [f64; 3],
    a: [f64; 3],
    z: [f64; 2],
}

impl Biquad {
    fn run(&mut self, x: f64) -> f64 {
        // Transposed direct form II.
        let y = self.b[0] * x + self.z[0];
        self.z[0] = self.b[1] * x - self.a[1] * y + self.z[1];
        self.z[1] = self.b[2] * x - self.a[2] * y;
        y
    }
}

impl KWeighting {
    pub fn new(rate: u32) -> KWeighting {
        let rate = rate as f64;
        let pi = std::f64::consts::PI;
        // The shelf.
        let (f0, g, q) = (1681.974450955533, 3.999843853973347, 0.7071752369554196);
        let k = (pi * f0 / rate).tan();
        let vh = 10f64.powf(g / 20.0);
        let vb = vh.powf(0.4996667741545416);
        let a0 = 1.0 + k / q + k * k;
        let shelf = Biquad {
            b: [
                (vh + vb * k / q + k * k) / a0,
                2.0 * (k * k - vh) / a0,
                (vh - vb * k / q + k * k) / a0,
            ],
            a: [1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0],
            z: [0.0; 2],
        };
        // The high pass.
        let (f0, q) = (38.13547087602444, 0.5003270373238773);
        let k = (pi * f0 / rate).tan();
        let a0 = 1.0 + k / q + k * k;
        let hp = Biquad {
            b: [1.0, -2.0, 1.0],
            a: [1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0],
            z: [0.0; 2],
        };
        KWeighting {
            stages: [shelf, hp],
        }
    }

    pub fn run(&mut self, x: f64) -> f64 {
        let y = self.stages[0].run(x);
        self.stages[1].run(y)
    }
}

/// Loudness window (s): BS.1770's short-term.
const LOUDNESS_S: f64 = 3.0;
/// How fast the applied compensation follows its target (s).
const FOLLOW_S: f64 = 1.0;
/// Bypass crossfade (s).
const FADE_S: f64 = 0.01;
/// How fast the output gain follows its slider (s): no zipper noise.
const GLIDE_S: f64 = 0.02;
/// BS.1770's absolute gate: -70 LUFS (mean square of the K-weighted signal, with its
/// -0.691 dB offset).
const GATE_MS: f64 = 1.1724653e-7;
/// The compensation stays within this (dB).
const MAX_COMP_DB: f64 = 24.0;

/// Bypass and gain compensation on the way to the output (see the module docs).
#[derive(Debug, Clone)]
pub struct Monitor {
    pub bypass: bool,
    pub compensate: bool,
    /// The manual gain on the device's output (dB).
    pub output_db: f64,
    /// The dry input, delayed by the engine's lag.
    delay: Vec<f64>,
    at: usize,
    /// 0: the device, 1: bypassed (moving toward `bypass`).
    mix: f64,
    k_in: KWeighting,
    k_out: KWeighting,
    ms_in: f64,
    ms_out: f64,
    /// The compensation applied now and its target (dB).
    comp_db: f64,
    target_db: f64,
    /// The output gain applied now (dB, gliding toward `output_db`).
    out_db: f64,
    // Per-sample coefficients.
    a_loud: f64,
    a_follow: f64,
    a_glide: f64,
    step_mix: f64,
}

impl Monitor {
    /// For output at `rate`, the engine's output lagging its input by `lag` samples.
    pub fn new(rate: u32, lag: usize) -> Monitor {
        let r = rate as f64;
        Monitor {
            bypass: false,
            compensate: true,
            output_db: 0.0,
            delay: vec![0.0; lag.max(1)],
            at: 0,
            mix: 0.0,
            k_in: KWeighting::new(rate),
            k_out: KWeighting::new(rate),
            ms_in: 0.0,
            ms_out: 0.0,
            comp_db: 0.0,
            target_db: 0.0,
            out_db: 0.0,
            a_loud: 1.0 / (LOUDNESS_S * r),
            a_follow: 1.0 / (FOLLOW_S * r),
            a_glide: 1.0 / (GLIDE_S * r),
            step_mix: 1.0 / (FADE_S * r),
        }
    }

    /// The compensation applied to the device's output now (dB; 0 when off).
    pub fn compensation_db(&self) -> f64 {
        if self.compensate { self.comp_db } else { 0.0 }
    }

    /// The device's output `wet` for its input `dry` (the same block, as the engine
    /// took and gave it): what to play.
    pub fn process(&mut self, dry: &[f64], wet: &[f32]) -> Vec<f32> {
        let target_mix = if self.bypass { 1.0 } else { 0.0 };
        let lag = self.delay.len();
        dry.iter()
            .zip(wet)
            .map(|(&d_in, &w)| {
                let d = std::mem::replace(&mut self.delay[self.at], d_in);
                self.at = (self.at + 1) % lag;
                let w = w as f64;
                let (ki, ko) = (self.k_in.run(d), self.k_out.run(w));
                self.ms_in += (ki * ki - self.ms_in) * self.a_loud;
                self.ms_out += (ko * ko - self.ms_out) * self.a_loud;
                if self.ms_in > GATE_MS && self.ms_out > 0.0 {
                    self.target_db = (10.0 * (self.ms_in / self.ms_out).log10())
                        .clamp(-MAX_COMP_DB, MAX_COMP_DB);
                }
                self.comp_db += (self.target_db - self.comp_db) * self.a_follow;
                self.out_db += (self.output_db - self.out_db) * self.a_glide;
                let g = 10f64.powf((self.compensation_db() + self.out_db) / 20.0);
                if self.mix < target_mix {
                    self.mix = (self.mix + self.step_mix).min(1.0);
                } else if self.mix > target_mix {
                    self.mix = (self.mix - self.step_mix).max(0.0);
                }
                (w * g * (1.0 - self.mix) + d * self.mix) as f32
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn k_weighting_at_48k_is_bs1770s() {
        // BS.1770-4, Tables 1 and 2.
        let k = KWeighting::new(48_000);
        let (s, h) = (k.stages[0], k.stages[1]);
        let want_s = (
            [1.53512485958697, -2.69169618940638, 1.19839281085285],
            [-1.69065929318241, 0.73248077421585],
        );
        let want_h = [-1.99004745483398, 0.99007225036621];
        let close = |a: &[f64], b: &[f64]| a.iter().zip(b).all(|(x, y)| (x - y).abs() < 1e-9);
        assert!(close(&s.b, &want_s.0), "shelf b {:?}", s.b);
        assert!(close(&s.a[1..], &want_s.1), "shelf a {:?}", s.a);
        assert!(close(&h.a[1..], &want_h), "high pass a {:?}", h.a);
    }

    fn sine(n: usize, amp: f64) -> Vec<f64> {
        (0..n)
            .map(|i| amp * (2.0 * std::f64::consts::PI * 1000.0 * i as f64 / 48_000.0).sin())
            .collect()
    }

    #[test]
    fn compensation_matches_loudness() {
        let mut m = Monitor::new(48_000, 3);
        let dry = sine(48_000 * 12, 0.1);
        // The device at -6 dB: compensated back up.
        let wet: Vec<f32> = dry.iter().map(|&v| (v * 0.5) as f32).collect();
        let mut out = Vec::new();
        for (d, w) in dry.chunks(480).zip(wet.chunks(480)) {
            out.extend(m.process(d, w));
        }
        assert!(
            (m.compensation_db() - 6.0206).abs() < 0.05,
            "{}",
            m.compensation_db()
        );
        let tail = &out[out.len() - 4800..];
        let peak = tail.iter().fold(0f32, |a, &v| a.max(v.abs()));
        assert!((peak - 0.1).abs() < 0.002, "peak {peak}");
        // Off: the device as it is.
        m.compensate = false;
        let y = m.process(&dry[..480], &wet[..480]);
        assert!(y.iter().zip(&wet[..480]).all(|(a, b)| a == b));
    }

    #[test]
    fn output_gain_scales_the_device_not_the_bypass() {
        let mut m = Monitor::new(48_000, 1);
        m.compensate = false;
        m.output_db = -6.0;
        let dry = sine(480, 0.1);
        let wet: Vec<f32> = dry.iter().map(|&v| v as f32).collect();
        // It glides there (no zipper noise): half a second is 25 time constants.
        let y = m.process(&dry, &wet);
        assert!(y[1].abs() > 0.99 * wet[1].abs());
        for _ in 0..50 {
            m.process(&dry, &wet);
        }
        let y = m.process(&dry, &wet);
        let g = 10f64.powf(-6.0 / 20.0);
        assert!(
            y.iter()
                .zip(&wet)
                .all(|(a, b)| (*a as f64 - *b as f64 * g).abs() < 1e-6)
        );
        // Bypassed (after the fade): the input as it is.
        m.bypass = true;
        m.process(&dry, &wet);
        let y = m.process(&dry, &wet);
        for (i, &v) in y.iter().enumerate().skip(1) {
            assert_eq!(v, dry[i - 1] as f32);
        }
    }

    #[test]
    fn bypass_plays_the_delayed_input_after_a_fade() {
        let mut m = Monitor::new(48_000, 3);
        m.compensate = false;
        let dry: Vec<f64> = (0..2000).map(|i| i as f64 * 1e-4).collect();
        let wet = vec![0f32; 2000];
        m.process(&dry[..1000], &wet[..1000]);
        m.bypass = true;
        let y = m.process(&dry[1000..], &wet[1000..]);
        // After the 480-sample fade: the input, 3 samples late.
        for (i, &v) in y.iter().enumerate().skip(480) {
            assert_eq!(v, dry[1000 + i - 3] as f32);
        }
        assert!(y[100] < (dry[1097] as f32) && y[100] > 0.0); // mid-fade
    }
}
