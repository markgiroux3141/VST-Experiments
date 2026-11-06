//! The Nickel Organ's live tier (docs/NICKEL_ORGAN_PLAN.md, "The Rust voice"): `varimu/nickel/
//! voice.py` ported step for step, so a key is the same coupled system the Python reference
//! solves, at the same step (192 kHz: 2x the project's 96 kHz), only compiled.
//!
//! A [`Model`] is the organ's values as `scripts/compile_nickel_organ.py` writes them
//! (`config/nickel/organ.live.json`): the circuit's numbers, the amplifier's idle point, the
//! #327's table, and per key its bar's modes and voicing. A [`Voice`] is one key: its bar, the
//! coil and its dead twin, both strips' Jiles-Atherton magnetizations with the magnetoelastic
//! coupling, the bridge, the tube loop (V1a, V1b, V3, the triode-connected 6V6GT, the output
//! transformer), the lamp, the hammer and the damper. An [`Organ`] is the keyboard: a voice
//! per key made at its first strike, running from the strike until released and quiet, summed
//! through each key's mixing gain, with SUSTAIN and POLARIZE as the panel.
//!
//! Not a circuitsim circuit: like the harp and the clavinet it is a model with its own
//! stepping, no IR. Noise is the Python's Johnson noise at the input transformer's secondary
//! (a generator of its own here: the Python's numpy stream isn't reproduced; tests turn it off).

use std::sync::Arc;

use serde::Deserialize;

use crate::devices::core::{DEN_FLOOR, MU0, dlangevin, langevin};
use crate::fastmath;

const K_BOLTZMANN: f64 = 1.380649e-23;
/// A released key below this (rms over [`QUIET_S`]) stops running.
pub const QUIET_V: f64 = 0.02;
pub const QUIET_S: f64 = 0.02;
/// Power-on: POLARIZE's ramp, then settling (s).
pub const POWER_ON_S: (f64, f64) = (0.03, 0.02);
/// A POLARIZE change reaching a key that is already made ramps over this long (s).
pub const POLARIZE_RAMP_S: f64 = 0.02;
/// Keys sounding at once (the oldest released one, else the oldest, stops for a new one).
pub const MAX_RUNNING: usize = 12;

// --- the model as data -----------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
pub struct Triode {
    pub mu: f64,
    pub ex: f64,
    pub kg1: f64,
    pub kp: f64,
    pub kvb: f64,
    pub g_perv: f64,
    pub g_contact: f64,
    pub g_smooth: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Pentode {
    pub mu: f64,
    pub ex: f64,
    pub kg1: f64,
    pub kg2: f64,
    pub kp: f64,
    pub kvb: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Nickel {
    pub ms: f64,
    pub a: f64,
    pub k: f64,
    pub c: f64,
    pub alpha: f64,
    pub lambda_s: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Lamp {
    pub t0: f64,
    pub dt: f64,
    pub r: Vec<f64>,
    pub loss: Vec<f64>,
    pub mc: Vec<f64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Params {
    pub turns: f64,
    pub area_m2: f64,
    pub l_g: f64,
    pub l_sigma: f64,
    pub r_arm: f64,
    pub r_b: f64,
    pub e_strip: f64,
    pub fb_max: f64,
    pub r_shunt: f64,
    pub n_in: f64,
    pub noise_ohm: f64,
    pub b_plus: f64,
    pub ra: f64,
    pub rk: f64,
    pub cc: f64,
    pub rg: f64,
    pub rk6: f64,
    pub r_lad: f64,
    pub lad_ratio: f64,
    pub lad_max_hz: f64,
    pub n_ot: f64,
    pub l_m: f64,
    pub r_d: f64,
    pub r_out: f64,
    pub c_out: f64,
    pub drv_ra: f64,
    pub drv_rk: f64,
    pub drv_cc: f64,
    pub rg6: f64,
    pub hammer_kg: f64,
    pub felt_k: f64,
    pub felt_p: f64,
    pub felt_loss: f64,
    pub v_min: f64,
    pub v_max: f64,
    pub damper_t60: f64,
    pub relay_s: f64,
    pub polarity: f64,
    pub lamp_t_max_k: f64,
    pub t_room_k: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Idle {
    pub vk1: f64,
    pub vp1: f64,
    pub vk3: f64,
    pub vp3: f64,
    pub vk6: f64,
    pub ip6: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Panel {
    pub sustain: f64,
    pub polarize: f64,
}

/// One key's bar and voicing.
#[derive(Debug, Clone, Deserialize)]
pub struct Key {
    pub note: u8,
    pub freq_hz: Vec<f64>,
    pub sigma_per_s: Vec<f64>,
    pub s_strip: Vec<f64>,
    pub phi_strike: Vec<f64>,
    pub phi_damper: Vec<f64>,
    pub phi_tip: Vec<f64>,
    pub strip_volume_m3: f64,
    pub strip_m: f64,
    pub c_lad: f64,
    pub trim: f64,
    pub mix: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Model {
    pub fs_hz: f64,
    pub panel: Panel,
    pub nickel: Nickel,
    pub params: Params,
    pub pre: Triode,
    pub drv: Triode,
    pub pwr: Pentode,
    pub lamp: Lamp,
    pub idle: Idle,
    pub keys: Vec<Key>,
}

impl Model {
    pub fn from_json(text: &str) -> Result<Model, String> {
        serde_json::from_str(text).map_err(|e| format!("the Nickel Organ's model: {e}"))
    }

    pub fn key(&self, note: u8) -> Option<&Key> {
        self.keys.iter().find(|k| k.note == note)
    }

    pub fn lowest(&self) -> u8 {
        self.keys.iter().map(|k| k.note).min().unwrap_or(0)
    }

    pub fn highest(&self) -> u8 {
        self.keys.iter().map(|k| k.note).max().unwrap_or(0)
    }
}

// --- the tubes and the lamp ---------------------------------------------------------------

/// The audio-taper pot's wiper fraction: 10% at half travel, two straight segments.
pub fn taper_audio(x: f64) -> f64 {
    let x = x.clamp(0.0, 1.0);
    if x < 0.5 {
        0.2 * x
    } else {
        0.1 + 1.8 * (x - 0.5)
    }
}

#[inline]
fn softplus(x: f64) -> f64 {
    if x > 0.0 {
        x + fastmath::ln_1p_unit(fastmath::exp(-x))
    } else {
        fastmath::ln_1p_unit(fastmath::exp(x))
    }
}

/// `a^b` for a >= 0 (0 below the smallest normal).
#[inline]
fn pow(a: f64, b: f64) -> f64 {
    if a >= f64::MIN_POSITIVE {
        fastmath::exp(b * fastmath::ln(a))
    } else {
        0.0
    }
}

impl Triode {
    #[inline]
    fn ip(&self, vgk: f64, vpk: f64) -> f64 {
        if vpk <= 0.0 {
            return 0.0;
        }
        let x = self.kp * (1.0 / self.mu + vgk / (self.kvb + vpk * vpk).sqrt());
        let e1 = vpk / self.kp * softplus(x);
        if e1 > 0.0 {
            2.0 / self.kg1 * pow(e1, self.ex)
        } else {
            0.0
        }
    }

    #[inline]
    fn ig(&self, vgk: f64) -> f64 {
        let x = self.g_smooth * softplus((vgk - self.g_contact) / self.g_smooth);
        self.g_perv * x * x.sqrt()
    }
}

impl Pentode {
    #[inline]
    fn a(&self, vg1k: f64, vg2k: f64) -> f64 {
        let e1 = vg2k / self.kp * softplus(self.kp * (1.0 / self.mu + vg1k / vg2k));
        if e1 > 0.0 {
            2.0 / self.kg1 * pow(e1, self.ex)
        } else {
            0.0
        }
    }

    #[inline]
    fn ig2(&self, vg1k: f64, vg2k: f64) -> f64 {
        let x = vg1k + vg2k / self.mu;
        if x > 0.0 {
            x * x.sqrt() / self.kg2
        } else {
            0.0
        }
    }

    /// The triode-connected plate current (screen on the plate).
    #[inline]
    fn triode_ip(&self, vg1k: f64, vpk: f64) -> f64 {
        self.a(vg1k, vpk) * (vpk / self.kvb).atan() + self.ig2(vg1k, vpk)
    }
}

impl Lamp {
    /// (R, heat out, heat capacity) at filament temperature `tk`.
    #[inline]
    fn at(&self, tk: f64) -> (f64, f64, f64) {
        let x = (tk - self.t0) / self.dt;
        let i = (x as i64).clamp(0, self.r.len() as i64 - 2) as usize;
        let f = (x - i as f64).clamp(0.0, 1.0);
        let g = 1.0 - f;
        (
            g * self.r[i] + f * self.r[i + 1],
            g * self.loss[i] + f * self.loss[i + 1],
            g * self.mc[i] + f * self.mc[i + 1],
        )
    }
}

impl Nickel {
    #[inline]
    fn dm_dhe(&self, he: f64, m: f64, delta: f64) -> f64 {
        let x = he / self.a;
        let d = self.ms * langevin(x) - m;
        let mut chi = self.c * (self.ms / self.a) * dlangevin(x);
        if delta * d > 0.0 {
            chi += d.abs() / self.k;
        }
        chi
    }
}

/// Exact step of q'' + 2 sigma q' + omega^2 q = f with f held: (a11, a12, a21, a22, b1, b2).
fn mode_step(omega: f64, sigma: f64, h: f64) -> [f64; 6] {
    let wd = (omega * omega - sigma * sigma).max(1e-12).sqrt();
    let e = (-sigma * h).exp();
    let (s, c) = (wd * h).sin_cos();
    let a11 = e * (c + sigma / wd * s);
    let a12 = e * s / wd;
    let a21 = -e * omega * omega / wd * s;
    let a22 = e * (c - sigma / wd * s);
    let w2 = omega * omega;
    [a11, a12, a21, a22, (1.0 - a11) / w2, -a21 / w2]
}

// --- noise -----------------------------------------------------------------------------

/// splitmix64 into Box-Muller: Gaussian samples, a stream per voice.
#[derive(Debug, Clone)]
struct Gauss {
    s: u64,
    spare: Option<f64>,
}

impl Gauss {
    fn new(seed: u64) -> Gauss {
        Gauss {
            s: seed,
            spare: None,
        }
    }

    fn next_u64(&mut self) -> u64 {
        self.s = self.s.wrapping_add(0x9E3779B97F4A7C15);
        let mut z = self.s;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58476D1CE4E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D049BB133111EB);
        z ^ (z >> 31)
    }

    fn uniform(&mut self) -> f64 {
        ((self.next_u64() >> 11) as f64 + 0.5) / (1u64 << 53) as f64
    }

    fn next(&mut self) -> f64 {
        if let Some(x) = self.spare.take() {
            return x;
        }
        let (u, v) = (self.uniform(), self.uniform());
        let r = (-2.0 * u.ln()).sqrt();
        let (s, c) = (2.0 * std::f64::consts::PI * v).sin_cos();
        self.spare = Some(r * s);
        r * c
    }
}

// --- one key ---------------------------------------------------------------------------

/// One key: its bar and loop, with state that persists between notes (the strip's
/// magnetization remembers).
#[derive(Debug, Clone)]
pub struct Voice {
    model: Arc<Model>,
    key: usize,
    /// The step (s) and the steps per 96 kHz output sample.
    h: f64,
    os: usize,
    /// The key's voicing trim (the wiper's share past SUSTAIN).
    pub trim: f64,
    noise: Option<Gauss>,
    steps_free: Vec<[f64; 6]>,
    steps_damped: Vec<[f64; 6]>,
    l_tot: f64,
    q: Vec<f64>,
    v: Vec<f64>,
    i1: f64,
    i2: f64,
    m1: f64,
    m2: f64,
    d1: f64,
    d2: f64,
    fb: f64,
    fb_target: f64,
    ramp_left: usize,
    fb_rate: f64,
    vp1: f64,
    uc1: f64,
    vp2: f64,
    uc2: f64,
    vp6: f64,
    im: f64,
    tl: f64,
    uco: f64,
    la: f64,
    vp3: f64,
    uc3: f64,
    lb: f64,
    hammer: bool,
    xh: f64,
    vh: f64,
    loop_closed: bool,
    damper: bool,
    relay_count: i64,
    pub peak_stress_pa: f64,
    pub steps_done: u64,
}

impl Voice {
    /// The key for `note` (None outside the compass), at `oversample` x 96 kHz.
    pub fn new(
        model: &Arc<Model>,
        note: u8,
        oversample: usize,
        noise_seed: Option<u64>,
    ) -> Option<Voice> {
        let key = model.keys.iter().position(|k| k.note == note)?;
        let kd = &model.keys[key];
        let p = &model.params;
        let h = 1.0 / (model.fs_hz * oversample as f64);
        let nm = kd.freq_hz.len();
        let om: Vec<f64> = kd
            .freq_hz
            .iter()
            .map(|f| 2.0 * std::f64::consts::PI * f)
            .collect();
        // the damper: a dashpot at its point whose fundamental's t60 is damper_t60
        let sig_d1 = 1000f64.ln() / p.damper_t60;
        let c_d = 2.0 * sig_d1 / (kd.phi_damper[0] * kd.phi_damper[0]);
        let steps_free = (0..nm)
            .map(|k| mode_step(om[k], kd.sigma_per_s[k], h))
            .collect();
        let steps_damped = (0..nm)
            .map(|k| {
                let s = kd.sigma_per_s[k] + 0.5 * c_d * kd.phi_damper[k] * kd.phi_damper[k];
                mode_step(om[k], s, h)
            })
            .collect();
        let id = &model.idle;
        Some(Voice {
            model: model.clone(),
            key,
            h,
            os: oversample,
            trim: kd.trim,
            noise: noise_seed
                .map(|s| Gauss::new(s ^ (note as u64).wrapping_mul(0x9E3779B97F4A7C15))),
            steps_free,
            steps_damped,
            l_tot: kd.strip_m + p.l_g,
            q: vec![0.0; nm],
            v: vec![0.0; nm],
            i1: 0.0,
            i2: 0.0,
            m1: 0.0,
            m2: 0.0,
            d1: 1.0,
            d2: 1.0,
            fb: 0.0,
            fb_target: 0.0,
            ramp_left: 0,
            fb_rate: 0.0,
            vp1: id.vp1,
            uc1: id.vp1,
            vp2: id.vp1,
            uc2: id.vp1,
            vp6: p.b_plus,
            im: id.ip6,
            tl: p.t_room_k,
            uco: 0.0,
            la: 0.0,
            vp3: id.vp3,
            uc3: id.vp3,
            lb: 0.0,
            hammer: false,
            xh: 0.0,
            vh: 0.0,
            loop_closed: false,
            damper: true,
            relay_count: -1,
            peak_stress_pa: 0.0,
            steps_done: 0,
        })
    }

    pub fn note(&self) -> u8 {
        self.model.keys[self.key].note
    }

    pub fn strike(&mut self, velocity: u8) {
        let p = &self.model.params;
        let kd = &self.model.keys[self.key];
        let x = (velocity.clamp(1, 127) as f64 - 1.0) / 126.0;
        let v0 = p.v_min * (p.v_max / p.v_min).powf(x);
        let ws: f64 = kd.phi_strike.iter().zip(&self.q).map(|(f, q)| f * q).sum();
        self.hammer = true;
        self.xh = ws;
        self.vh = v0;
        self.damper = false;
        self.relay_count = (p.relay_s / self.h).round() as i64;
    }

    pub fn release(&mut self) {
        self.loop_closed = false;
        self.damper = true;
        self.relay_count = -1;
    }

    /// The strip's magnetization (A/m) and the lamp's temperature (K).
    pub fn m1(&self) -> f64 {
        self.m1
    }

    pub fn lamp_k(&self) -> f64 {
        self.tl
    }

    /// The tip's displacement (m).
    pub fn tip_m(&self) -> f64 {
        let kd = &self.model.keys[self.key];
        kd.phi_tip.iter().zip(&self.q).map(|(f, x)| f * x).sum()
    }

    /// Power on: POLARIZE ramped up from zero, then settling, out of the timeline.
    pub fn power_on(&mut self, polarize: f64) {
        let mut buf = vec![0.0; (POWER_ON_S.0 * self.model.fs_hz) as usize];
        self.run(&mut buf, 0.0, polarize, POWER_ON_S.0);
        let mut buf = vec![0.0; (POWER_ON_S.1 * self.model.fs_hz) as usize];
        self.run(&mut buf, 0.0, polarize, 0.0);
    }

    /// `out.len()` samples at 96 kHz of the line out (V1b's plate, AC, volts). POLARIZE moves
    /// from its present MMF to the knob's over `ramp_s` (0: at once); a ramp longer than the
    /// call carries on in the next.
    pub fn run(&mut self, out: &mut [f64], sustain: f64, polarize: f64, ramp_s: f64) {
        let model = self.model.clone();
        let m: &Model = &model;
        let p = &m.params;
        let kd = &m.keys[self.key];
        let h = self.h;
        let os = self.os;
        let n = out.len() * os;
        let nm = self.q.len();
        let ni = &m.nickel;
        let ms2 = ni.ms * ni.ms;
        let (lam_s, alpha) = (ni.lambda_s, ni.alpha);
        let ddlam = 2.0 * lam_s / ms2;
        let e_s = p.e_strip;
        let e_v = e_s * kd.strip_volume_m3;
        let (nt, ar) = (p.turns, p.area_m2);
        let nam = nt * ar * MU0;
        let l_n = kd.strip_m;
        let (l_g, l_tot) = (p.l_g, self.l_tot);
        let lsig = p.l_sigma;
        let (r1, r2) = (p.r_arm, p.r_arm);
        let rb = p.r_b;
        let rsh = p.r_shunt;
        let n_ot = p.n_ot;
        let bp = p.b_plus;
        let (ra, cc, rg) = (p.ra, p.cc, p.rg);
        let (pre, pwr, drv) = (&m.pre, &m.pwr, &m.drv);
        let (vk1, vk6, vk3) = (m.idle.vk1, m.idle.vk6, m.idle.vk3);
        let idle = m.idle.vp1;
        let g_wiper = taper_audio(sustain) * self.trim;
        let pol_nin = p.polarity * p.n_in;
        let (felt_k, felt_p, felt_loss, hammer_kg) = (p.felt_k, p.felt_p, p.felt_loss, p.hammer_kg);
        let k_lad = h / (p.r_lad * kd.c_lad);
        let sd = (4.0 * K_BOLTZMANN * p.t_room_k * p.noise_ohm * 0.5 / h).sqrt();
        let steps = if self.damper {
            &self.steps_damped
        } else {
            &self.steps_free
        }
        .clone();
        let s_k = &kd.s_strip;
        let phs = &kd.phi_strike;

        // POLARIZE's ramp
        let fb_target = polarize * p.fb_max;
        if self.ramp_left == 0 || fb_target != self.fb_target {
            let n_ramp = ((ramp_s / h).round() as usize).max(1);
            let rate = (fb_target - self.fb) / (n_ramp as f64 * h);
            self.fb_rate = rate;
            self.ramp_left = if rate != 0.0 { n_ramp } else { 0 };
            self.fb_target = fb_target;
        }

        let (mut i1, mut i2, mut m1, mut m2, mut d1, mut d2) =
            (self.i1, self.i2, self.m1, self.m2, self.d1, self.d2);
        let mut fb = self.fb;
        let (mut vp1, mut uc1, mut vp2, mut uc2, mut vp6, mut im, mut tl, mut uco) = (
            self.vp1, self.uc1, self.vp2, self.uc2, self.vp6, self.im, self.tl, self.uco,
        );
        let (mut la, mut lb, mut vp3, mut uc3) = (self.la, self.lb, self.vp3, self.uc3);
        let (mut hammer, mut xh, mut vh) = (self.hammer, self.xh, self.vh);
        let mut loop_closed = self.loop_closed;
        let mut relay = self.relay_count;
        let mut peak = self.peak_stress_pa;
        let mut ramp_left = self.ramp_left;
        let fb_rate = self.fb_rate;
        let mut noise = self.noise.take();

        for j in 0..n {
            // --- POLARIZE's ramp
            let fbd = if ramp_left > 0 {
                fb += fb_rate * h;
                ramp_left -= 1;
                if ramp_left == 0 {
                    fb = self.fb_target;
                }
                fb_rate
            } else {
                0.0
            };
            // --- the bar's strain at the strip
            let (mut eps, mut epsd) = (0.0, 0.0);
            for ((s, q), v) in s_k.iter().zip(&self.q).zip(&self.v) {
                eps += s * q;
                epsd += s * v;
            }
            // --- the amplifier, from the bridge at the step's start
            let nz = match noise.as_mut() {
                Some(g) => g.next() * sd,
                None => 0.0,
            };
            let vg1 = pol_nin * rb * (i2 - i1) + nz;
            // V1a
            for _ in 0..2 {
                let vgn = vp1 - uc1;
                let f0 =
                    (bp - vp1) / ra - pre.ip(vg1 - vk1, vp1 - vk1) - vgn / rg - pre.ig(vgn - vk1);
                let dv = 1e-3;
                let vgn2 = vgn + dv;
                let f1 = (bp - vp1 - dv) / ra
                    - pre.ip(vg1 - vk1, vp1 + dv - vk1)
                    - vgn2 / rg
                    - pre.ig(vgn2 - vk1);
                vp1 -= f0 * dv / (f1 - f0);
            }
            let vgn = vp1 - uc1;
            let ic1 = vgn / rg + pre.ig(vgn - vk1);
            uc1 += h * ic1 / cc;
            // V1b
            for _ in 0..2 {
                let f0 = (bp - vp2) / ra - pre.ip(vgn - vk1, vp2 - vk1) - (vp2 - uc2) / rg;
                let dv = 1e-3;
                let f1 = (bp - vp2 - dv) / ra
                    - pre.ip(vgn - vk1, vp2 + dv - vk1)
                    - (vp2 + dv - uc2) / rg;
                vp2 -= f0 * dv / (f1 - f0);
            }
            let vtop = vp2 - uc2;
            uc2 += h * (vtop / rg) / cc;
            // the line out
            let vo = vp2 - idle - uco;
            uco += h * (vo / p.r_out) / p.c_out;
            // the key's contact
            if relay >= 0 {
                relay -= 1;
                if relay < 0 {
                    loop_closed = true;
                }
            }
            let vw = if loop_closed { g_wiper * vtop } else { 0.0 };
            // the drive ladder
            let ia_ = (vw - la) * k_lad;
            let ib_ = (la - lb) * k_lad;
            la += ia_ - ib_;
            lb += ib_;
            // V3
            for _ in 0..2 {
                let f0 = (bp - vp3) / p.drv_ra - drv.ip(lb - vk3, vp3 - vk3) - (vp3 - uc3) / p.rg6;
                let f1 = (bp - vp3 - 1e-3) / p.drv_ra
                    - drv.ip(lb - vk3, vp3 + 1e-3 - vk3)
                    - (vp3 + 1e-3 - uc3) / p.rg6;
                vp3 -= f0 * 1e-3 / (f1 - f0);
            }
            let vg6 = vp3 - uc3;
            uc3 += h * (vg6 / p.rg6) / p.drv_cc;
            // V2 and the OT
            let i12 = i1 + i2;
            let (rl, loss, mc) = m.lamp.at(tl);
            let rls = rl + rsh;
            let vg1k6 = vg6 - vk6;
            let mut gg = 0.0;
            for _ in 0..3 {
                let vpk = vp6 - vk6;
                let ip0 = pwr.triode_ip(vg1k6, vpk);
                let ip1 = pwr.triode_ip(vg1k6, vpk + 1e-3);
                let gp = (ip1 - ip0) * 1e3;
                let il = ((bp - vp6) / n_ot + rsh * i12) / rls;
                let f0 = ip0 - im - il / n_ot - (bp - vp6) / p.r_d;
                gg = gp + 1.0 / (n_ot * n_ot * rls) + 1.0 / p.r_d;
                vp6 -= f0 / gg;
            }
            let vs = (bp - vp6) / n_ot;
            let il = (vs + rsh * i12) / rls;
            let va = vs - rl * il;
            let dvs = -(rsh / (n_ot * rls * gg)) / n_ot;
            let zz = 0.5 * (dvs - rl * (dvs + rsh) / rls);
            // --- the two coils and their strips
            let lam1 = lam_s * m1 * m1 / ms2;
            let dl1 = ddlam * m1;
            let sig1 = e_s * (eps - lam1);
            if sig1.abs() > peak {
                peak = sig1.abs();
            }
            let he1 = (nt * i1 + fb - m1 * l_g) / l_tot + alpha * m1 + sig1 * dl1 / MU0;
            let g1 = (sig1 * ddlam - e_s * dl1 * dl1) / MU0;
            let x1 = fbd / l_tot + e_s * epsd * dl1 / MU0;
            let lam2 = lam_s * m2 * m2 / ms2;
            let dl2 = ddlam * m2;
            let sig2 = -e_s * lam2;
            let he2 = (nt * i2 + fb - m2 * l_g) / l_tot + alpha * m2 + sig2 * dl2 / MU0;
            let g2 = (sig2 * ddlam - e_s * dl2 * dl2) / MU0;
            let x2 = fbd / l_tot;
            let rr1 = va - r1 * i1;
            let rr2 = va - r2 * i2;
            let (mut t1, mut t2) = (d1, d2);
            let (mut di1, mut di2, mut dm1, mut dm2) = (0.0, 0.0, 0.0, 0.0);
            for _ in 0..4 {
                let chi1 = ni.dm_dhe(he1, m1, t1);
                let den = (1.0 - chi1 * (alpha + g1) + chi1 * l_g / l_tot).max(DEN_FLOOR);
                let ca1 = chi1 * nt / (l_tot * den);
                let c01 = chi1 * x1 / den;
                let chi2 = ni.dm_dhe(he2, m2, t2);
                let den = (1.0 - chi2 * (alpha + g2) + chi2 * l_g / l_tot).max(DEN_FLOOR);
                let ca2 = chi2 * nt / (l_tot * den);
                let c02 = chi2 * x2 / den;
                let a1 = (lsig + nam * (nt / l_tot + ca1 * l_n / l_tot)) / h + 0.5 * r1;
                let a2 = (lsig + nam * (nt / l_tot + ca2 * l_n / l_tot)) / h + 0.5 * r2;
                let b1 = rr1 - nam * (fbd / l_tot + c01 * l_n / l_tot);
                let b2 = rr2 - nam * (fbd / l_tot + c02 * l_n / l_tot);
                let det = a1 * a2 - zz * (a1 + a2);
                di1 = (b1 * (a2 - zz) + zz * b2) / det;
                di2 = (b2 * (a1 - zz) + zz * b1) / det;
                dm1 = ca1 * di1 + c01 * h;
                dm2 = ca2 * di2 + c02 * h;
                let ok1 = t1 == 0.0 || dm1 * t1 >= 0.0;
                let ok2 = t2 == 0.0 || dm2 * t2 >= 0.0;
                if ok1 && ok2 {
                    break;
                }
                if !ok1 {
                    t1 = if t1 == d1 { -t1 } else { 0.0 };
                }
                if !ok2 {
                    t2 = if t2 == d2 { -t2 } else { 0.0 };
                }
            }
            if t1 != 0.0 {
                d1 = t1;
            }
            if t2 != 0.0 {
                d2 = t2;
            }
            let m1_old = m1;
            m1 += dm1;
            m2 += dm2;
            i1 += di1;
            i2 += di2;
            // --- the lamp, the OT's magnetizing current
            tl = (tl + h * (rl * il * il - loss) / mc).min(p.lamp_t_max_k);
            im += h * n_ot * vs / p.l_m;
            // --- the bar
            let mm = 0.5 * (m1 + m1_old);
            let fmag = e_v * lam_s * mm * mm / ms2;
            let mut fc = 0.0;
            if hammer {
                let (mut ws, mut wv) = (0.0, 0.0);
                for ((f, q), v) in phs.iter().zip(&self.q).zip(&self.v) {
                    ws += f * q;
                    wv += f * v;
                }
                let dl = xh - ws;
                if dl > 0.0 {
                    fc = felt_k * pow(dl, felt_p) * (1.0 + felt_loss * (vh - wv)).max(0.0);
                } else if vh < wv {
                    hammer = false; // it has left the bar
                }
                vh -= h * fc / hammer_kg;
                xh += h * vh;
            }
            for k in 0..nm {
                let [a11, a12, a21, a22, b1, b2] = steps[k];
                let f = s_k[k] * fmag + phs[k] * fc;
                let (qk, vk) = (self.q[k], self.v[k]);
                self.q[k] = a11 * qk + a12 * vk + b1 * f;
                self.v[k] = a21 * qk + a22 * vk + b2 * f;
            }
            if (j + 1) % os == 0 {
                out[j / os] = vo;
            }
        }

        self.i1 = i1;
        self.i2 = i2;
        self.m1 = m1;
        self.m2 = m2;
        self.d1 = d1;
        self.d2 = d2;
        self.fb = fb;
        self.vp1 = vp1;
        self.uc1 = uc1;
        self.vp2 = vp2;
        self.uc2 = uc2;
        self.vp6 = vp6;
        self.im = im;
        self.tl = tl;
        self.uco = uco;
        self.la = la;
        self.lb = lb;
        self.vp3 = vp3;
        self.uc3 = uc3;
        self.hammer = hammer;
        self.xh = xh;
        self.vh = vh;
        self.loop_closed = loop_closed;
        self.relay_count = relay;
        self.peak_stress_pa = peak;
        self.ramp_left = ramp_left;
        self.noise = noise;
        self.steps_done += n as u64;
    }
}

// --- the keyboard ----------------------------------------------------------------------

struct Slot {
    voice: Voice,
    /// The POLARIZE it last ran at (a change reaches a frozen key when it next runs).
    pol_of: f64,
    running: bool,
    released: bool,
    age: u64,
    /// The line out's squares over the last [`QUIET_S`] (a ring and its sum).
    ring: Vec<f64>,
    ring_at: usize,
    ring_sum: f64,
}

impl Slot {
    /// Run the key over `buf` and decide whether a released key has gone quiet.
    fn advance(&mut self, buf: &mut [f64], sustain: f64, polarize: f64) {
        let ramp = if self.pol_of != polarize {
            self.pol_of = polarize;
            POLARIZE_RAMP_S
        } else {
            0.0
        };
        self.voice.run(buf, sustain, polarize, ramp);
        let n = self.ring.len();
        for y in buf.iter() {
            let sq = y * y;
            self.ring_sum += sq - self.ring[self.ring_at];
            self.ring[self.ring_at] = sq;
            self.ring_at = (self.ring_at + 1) % n;
        }
        if self.released && (self.ring_sum.max(0.0) / n as f64).sqrt() < QUIET_V {
            self.running = false;
        }
    }
}

/// A key's block handed to a worker and back.
struct Job {
    index: usize,
    slot: Box<Slot>,
    buf: Vec<f64>,
    sustain: f64,
    polarize: f64,
}

/// Worker threads for the keys: every key is independent within a block, so the blocks run
/// in parallel and are summed in key order (the same bits on any number of threads).
struct Pool {
    jobs: Option<std::sync::mpsc::Sender<Job>>,
    done: std::sync::mpsc::Receiver<Job>,
    handles: Vec<std::thread::JoinHandle<()>>,
}

impl Pool {
    fn new(threads: usize) -> Pool {
        use std::sync::{Mutex, mpsc};
        let (jobs, rx) = mpsc::channel::<Job>();
        let (tx_done, done) = mpsc::channel::<Job>();
        let rx = Arc::new(Mutex::new(rx));
        let handles = (0..threads)
            .map(|k| {
                let (rx, tx) = (rx.clone(), tx_done.clone());
                std::thread::Builder::new()
                    .name(format!("nickel {k}"))
                    .spawn(move || {
                        loop {
                            let job = rx.lock().expect("jobs").recv();
                            let Ok(mut j) = job else { return };
                            j.slot.advance(&mut j.buf, j.sustain, j.polarize);
                            if tx.send(j).is_err() {
                                return;
                            }
                        }
                    })
                    .expect("thread")
            })
            .collect();
        Pool {
            jobs: Some(jobs),
            done,
            handles,
        }
    }
}

impl Drop for Pool {
    fn drop(&mut self) {
        self.jobs = None;
        for h in self.handles.drain(..) {
            let _ = h.join();
        }
    }
}

/// The keyboard: voices made at their first strike, run until released and quiet, summed
/// through each key's mixing gain.
pub struct Organ {
    model: Arc<Model>,
    slots: Vec<Option<Box<Slot>>>,
    oversample: usize,
    noise_seed: Option<u64>,
    pub sustain: f64,
    pub polarize: f64,
    clock: u64,
    pool: Option<Pool>,
    spare: Vec<Vec<f64>>,
}

impl Organ {
    /// `threads` workers run the sounding keys (0: on the caller's thread).
    pub fn new(
        model: Arc<Model>,
        oversample: usize,
        noise_seed: Option<u64>,
        threads: usize,
    ) -> Organ {
        let n = model.highest() as usize + 1 - model.lowest() as usize;
        Organ {
            sustain: model.panel.sustain,
            polarize: model.panel.polarize,
            slots: (0..n).map(|_| None).collect(),
            model,
            oversample,
            noise_seed,
            clock: 0,
            pool: (threads > 0).then(|| Pool::new(threads)),
            spare: Vec::new(),
        }
    }

    pub fn model(&self) -> &Arc<Model> {
        &self.model
    }

    fn index(&self, note: u8) -> Option<usize> {
        let lo = self.model.lowest();
        (note >= lo && note <= self.model.highest()).then(|| (note - lo) as usize)
    }

    /// Keys sounding now.
    pub fn running(&self) -> usize {
        self.slots.iter().flatten().filter(|s| s.running).count()
    }

    pub fn note_on(&mut self, note: u8, velocity: u8) {
        let Some(i) = self.index(note) else { return };
        // a voice's first strike: it powers on at the knob, out of the timeline
        if self.slots[i].is_none() {
            let Some(mut v) = Voice::new(&self.model, note, self.oversample, self.noise_seed)
            else {
                return;
            };
            v.power_on(self.polarize);
            let n = (QUIET_S * self.model.fs_hz) as usize;
            self.slots[i] = Some(Box::new(Slot {
                voice: v,
                pol_of: self.polarize,
                running: false,
                released: false,
                age: 0,
                ring: vec![0.0; n],
                ring_at: 0,
                ring_sum: 0.0,
            }));
        }
        // stop one for this if too many sound: a released one first, the oldest
        if !self.slots[i].as_ref().is_some_and(|s| s.running) && self.running() >= MAX_RUNNING {
            let pick = self
                .slots
                .iter()
                .enumerate()
                .filter_map(|(k, s)| s.as_ref().filter(|s| s.running).map(|s| (k, s)))
                .min_by_key(|(_, s)| (!s.released, s.age))
                .map(|(k, _)| k);
            if let Some(k) = pick
                && let Some(s) = self.slots[k].as_mut()
            {
                s.running = false;
                s.voice.release();
            }
        }
        let (sustain, polarize) = (self.sustain, self.polarize);
        self.clock += 1;
        let age = self.clock;
        let s = self.slots[i].as_mut().expect("slot");
        if s.pol_of != polarize {
            let mut buf = vec![0.0; (POLARIZE_RAMP_S * self.model.fs_hz) as usize];
            s.voice.run(&mut buf, sustain, polarize, POLARIZE_RAMP_S);
            s.pol_of = polarize;
        }
        s.voice.strike(velocity);
        s.running = true;
        s.released = false;
        s.age = age;
    }

    pub fn note_off(&mut self, note: u8) {
        if let Some(i) = self.index(note)
            && let Some(s) = self.slots[i].as_mut()
        {
            s.voice.release();
            s.released = true;
        }
    }

    /// The summed line out for the next `out.len()` samples at 96 kHz.
    pub fn render(&mut self, out: &mut [f64]) {
        out.fill(0.0);
        let (sustain, polarize) = (self.sustain, self.polarize);
        let n = out.len();
        let lo = self.model.lowest();
        let running: Vec<usize> = (0..self.slots.len())
            .filter(|&i| self.slots[i].as_ref().is_some_and(|s| s.running))
            .collect();
        if running.is_empty() {
            return;
        }
        let mut results: Vec<(usize, Vec<f64>)> = Vec::with_capacity(running.len());
        match &self.pool {
            Some(pool) if running.len() > 1 => {
                let tx = pool.jobs.as_ref().expect("jobs");
                for &i in &running {
                    let mut buf = self.spare.pop().unwrap_or_default();
                    buf.resize(n, 0.0);
                    let slot = self.slots[i].take().expect("slot");
                    let job = Job {
                        index: i,
                        slot,
                        buf,
                        sustain,
                        polarize,
                    };
                    tx.send(job).expect("workers");
                }
                for _ in 0..running.len() {
                    let j = pool.done.recv().expect("workers");
                    self.slots[j.index] = Some(j.slot);
                    results.push((j.index, j.buf));
                }
                results.sort_by_key(|r| r.0);
            }
            _ => {
                for &i in &running {
                    let mut buf = self.spare.pop().unwrap_or_default();
                    buf.resize(n, 0.0);
                    self.slots[i]
                        .as_mut()
                        .expect("slot")
                        .advance(&mut buf, sustain, polarize);
                    results.push((i, buf));
                }
            }
        }
        for (i, buf) in results {
            let mix = self.model.key(lo + i as u8).map_or(1.0, |k| k.mix);
            for (o, y) in out.iter_mut().zip(&buf) {
                *o += mix * y;
            }
            self.spare.push(buf);
        }
    }
}
