//! Circuit IR: the netlist both engines simulate.
//!
//! Python builds it (`varimu/circuit/ir.py`) and writes it as JSON; this module
//! reads the same JSON. The two definitions must stay field-for-field identical,
//! which the round-trip tests check (fixtures exported from Python in
//! `tests/fixtures/`).
//!
//! Conventions, shared with Python:
//! - nodes are strings; `"0"` is ground;
//! - element and model names are the SPICE names (`R103`, `XVA`, `LT101_sa`),
//!   unique ignoring case, and an element name starts with its SPICE letter;
//! - values are SI, with the unit in the field name;
//! - pots, pads and switch positions are already resolved into plain elements.
//!
//! Mutual inductance is a [`Coupling`] per inductor pair, like a SPICE `K`
//! element. The linear engine (M2) groups connected inductors and stamps the
//! inductance matrix `M[i][j] = k_ij * sqrt(L_i * L_j)` directly, so a
//! k = 0.999 transformer never needs the ill-conditioned inverse.
//!
//! A transformer on a nonlinear core (main plan Phase 2) is [`Winding`]s on a
//! core node, whose voltage is the flux density (1 V = 1 mT,
//! [`TESLA_PER_V`]), and a [`MagneticCore`] device from that node to ground.
//!
//! A [`SineSource`] is SPICE's `SIN` source (the mains, main plan Phase 3):
//! the DC operating point takes it at its t = 0 value, as ngspice's
//! transient operating point does.
//!
//! A [`Vccs`] is SPICE's `G` (component editor C3: a speaker's pressure
//! readout, which senses the cone's motion without loading it). It is a new
//! element kind, not a new schema: circuits without one write the same JSON.
//!
//! Noise (device builder B5, `varimu/devices/noise.py`, [`crate::noise`]): the
//! circuit's [`NoiseSpec`] and the elements [`NoiseCurrent`] (a resistor's Johnson
//! noise) and [`TubeNoise`] (a tube instance's shot, grid-current shot and flicker
//! noise), all optional: an IR without noise reads and writes as before.
//!
//! Heated cathodes (device builder B6, `varimu/devices/cathode.py`, [`crate::cathode`]):
//! the circuit's [`HeaterSpec`] and a [`HeatedCathode`] per tube instance; optional as noise.
//!
//! A [`ThyratronEvents`] is a gas thyratron as technique K's event kernels
//! (HYBRID_PHYSICS_PLAN.md H3; [`crate::events`]): a new element kind, as `Vccs`.

use std::collections::{HashMap, HashSet};
use std::fmt;

use serde::{Deserialize, Serialize};

/// JSON schema version. Bump it (in Python too) on any incompatible change.
pub const IR_VERSION: u32 = 3;

/// Flux density per volt on a core node (`varimu.devices.core.TESLA_PER_V`).
pub const TESLA_PER_V: f64 = 1e-3;

/// The ground node.
pub const GROUND: &str = "0";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitIr {
    pub version: u32,
    pub title: String,
    /// Driven by the audio input, relative to ground.
    pub input_node: String,
    /// Control inputs ([`Control`]), each driven by its own samples. Optional: an
    /// IR without any reads and writes as before.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub controls: Vec<Control>,
    /// Noise (B5): absent, none.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub noise: Option<NoiseSpec>,
    /// Heated cathodes (B6): absent, none.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub heaters: Option<HeaterSpec>,
    pub probes: Vec<Probe>,
    pub models: Vec<DeviceModel>,
    pub sections: Vec<Section>,
}

/// A control input (a gate, a pitch voltage; the tube synth's S3): `node` to
/// ground driven by its own samples beside the audio input, linear between
/// samples (a step stays a ramp over one sample instead of ringing).
///
/// `audio`: a second audio input (a stereo unit's right channel; STEREO_PLAN.md ST7):
/// its samples interpolated as the input's are (`Options::input_order`'s polynomial), so
/// two channels fed the same samples see the same waveform. Absent: false.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Control {
    pub name: String,
    pub node: String,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub audio: bool,
}

/// The circuit's heaters (B6): one cathode temperature for every [`HeatedCathode`], heated
/// by `heater_ratio` (the heater winding's volts over their rating) times B5's mains wander
/// when the noise has it; `start` "warm" or "cold" (power on).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeaterSpec {
    pub t0_k: f64,
    pub t_amb_k: f64,
    pub alpha: f64,
    pub tau_s: f64,
    pub phi_ev: f64,
    pub n: f64,
    pub reserve: f64,
    pub heater_ratio: f64,
    pub start: String,
}

/// The circuit's noise: the seed every source's stream is keyed by, and the sample
/// grid its samples sit on (the project's rate). Mains wander: the [`SineSource`]s named
/// in `mains_sources` (the mains) have their amplitude times `1 + m(t)`, `m` one shared
/// stream of nominal rms `mains_rms` ([`crate::noise::MainsWander`]).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NoiseSpec {
    pub seed: u64,
    pub rate_hz: f64,
    #[serde(default, skip_serializing_if = "is_zero")]
    pub mains_rms: f64,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub mains_sources: Vec<String>,
}

fn is_zero(x: &f64) -> bool {
    *x == 0.0
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Probe {
    /// Node voltage relative to ground.
    Voltage { node: String },
}

/// A titled group of elements (a stage of the circuit). Only for readability:
/// the circuit is all sections' elements together.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Section {
    pub title: String,
    pub elements: Vec<Element>,
    /// Steps per sample, run on a thread of its own: a multi-rate part (`partition.rs`;
    /// the Ampex 351's bias oscillator above the audio rate's Nyquist frequency). Absent:
    /// the section steps with the rest.
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "opt_count"
    )]
    pub substeps: Option<usize>,
    /// A multi-rate section's decimation of what it hands on (`partition.rs`;
    /// HYBRID_PHYSICS_PLAN.md H3a, M1). Absent: the average over the sample.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub decimate: Option<Decimate>,
    /// Shared nodes a multi-rate section owns (it publishes their voltages and is fed
    /// their users' currents). Absent: it owns none.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub owns: Option<Vec<String>>,
    /// A multi-rate section that owns nothing and doesn't decimate (its part reading no
    /// other part's senses) reads the other parts' couplings this many samples late,
    /// interpolated between published samples, so its part runs up to that many samples
    /// ahead of them instead of in lockstep (`stream.rs`; TAPE_SPEED_PLAN.md P2: the Ampex
    /// 351's record side, coupled to the rest only through its supply's reservoirs). A
    /// part's lag is the largest of its sections'. Absent: lockstep.
    #[serde(
        default,
        skip_serializing_if = "Option::is_none",
        deserialize_with = "opt_count"
    )]
    pub lag_samples: Option<usize>,
    /// A multi-rate section's own integration method (a `Method` name: TAPE_SPEED_PLAN.md
    /// P4, the Ampex 351's record side on trbdf2). A part's sections agree on it. Absent:
    /// the run's.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub method: Option<String>,
    /// A multi-rate section's triodes from tables of the same model (`Options::tube_tables`
    /// for its part alone; TAPE_SPEED_PLAN.md P4). Absent: the run's setting.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tube_tables: Option<bool>,
}

/// How a multi-rate part turns its steps into the values it publishes per sample.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Decimate {
    /// A linear-phase anti-alias low-pass over its steps (`partition::Decimator`).
    Fir,
}

/// An optional count written as a number (the IR writes every number as a float).
fn opt_count<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Option<usize>, D::Error> {
    let x = f64::deserialize(d)?;
    if x >= 1.0 && x.fract() == 0.0 && x < 1e9 {
        Ok(Some(x as usize))
    } else {
        Err(serde::de::Error::custom(format!(
            "{x} isn't a count of steps (1 or more)"
        )))
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Element {
    Resistor(Resistor),
    Capacitor(Capacitor),
    Inductor(Inductor),
    Coupling(Coupling),
    VoltageSource(VoltageSource),
    SineSource(SineSource),
    Winding(Winding),
    Vccs(Vccs),
    NoiseCurrent(NoiseCurrent),
    TubeNoise(TubeNoise),
    HeatedCathode(HeatedCathode),
    Device(Device),
    Plate(Plate),
    Spring(Spring),
    Tape(Tape),
    Harp(Harp),
    ClavStrings(ClavStrings),
    NovaKeys(NovaKeys),
    NickelKeys(NickelKeys),
    ReedKeys(ReedKeys),
    ThyratronEvents(ThyratronEvents),
    ResetEvents(ResetEvents),
    EdgeEvents(EdgeEvents),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Resistor {
    pub name: String,
    pub a: String,
    pub b: String,
    pub r_ohm: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Capacitor {
    pub name: String,
    pub a: String,
    pub b: String,
    pub c_f: f64,
    /// The voltage (a - b) it holds at the start of a run: the DC operating point is
    /// solved with it held there (a start state, as SPICE's IC=), so a run can start away
    /// from a balance point the circuit would otherwise sit at (a symmetric
    /// multivibrator's: a noiseless simulation never leaves it). Absent: none. The first
    /// step takes the start's derivative as zero, as at a DC point (about half a step late).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub v0_v: Option<f64>,
}

/// Current flows from `a` to `b` through the inductor; `a` is the dotted end
/// for [`Coupling`].
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Inductor {
    pub name: String,
    pub a: String,
    pub b: String,
    pub l_h: f64,
}

/// Coupling coefficient between two inductors (SPICE `K`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Coupling {
    pub name: String,
    pub l_a: String,
    pub l_b: String,
    pub k: f64,
}

/// Ideal DC voltage source, `pos` minus `neg` = `dc_v`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VoltageSource {
    pub name: String,
    pub pos: String,
    pub neg: String,
    pub dc_v: f64,
}

/// `pos` minus `neg` = `offset_v + amplitude_v sin(2 pi freq_hz t + phase)`,
/// SPICE's `SIN(VO VA FREQ 0 0 PHASE)` (phase in degrees). The DC operating
/// point takes the value at t = 0, so phase 90 starts at the peak.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SineSource {
    pub name: String,
    pub pos: String,
    pub neg: String,
    pub offset_v: f64,
    pub amplitude_v: f64,
    pub freq_hz: f64,
    pub phase_deg: f64,
}

impl SineSource {
    /// Angular frequency (rad/s) and phase (rad) of the sine.
    pub fn omega_phase(&self) -> (f64, f64) {
        (
            2.0 * std::f64::consts::PI * self.freq_hz,
            self.phase_deg.to_radians(),
        )
    }

    /// The source voltage at time `t`.
    pub fn at(&self, t: f64) -> f64 {
        let (w, ph) = self.omega_phase();
        self.offset_v + self.amplitude_v * (w * t + ph).sin()
    }
}

/// `turns` turns on the core whose node is `core`, of cross-section
/// `area_m2`: a branch from `a` to `b` with `v_a - v_b = turns area dB/dt`
/// (B = the core node's voltage times [`TESLA_PER_V`]); its current adds
/// `turns i` to the core's magnetomotive force, so the core node's KCL is
/// `sum(turns i)` = what the core draws. `a` is the dotted end.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Winding {
    pub name: String,
    pub a: String,
    pub b: String,
    pub core: String,
    pub turns: f64,
    pub area_m2: f64,
}

/// Voltage-controlled current source (SPICE `G`): a current
/// `gm_s (v(ctrl_pos) - v(ctrl_neg))` flows from `pos` through the source to
/// `neg`. Its control draws no current.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Vccs {
    pub name: String,
    pub pos: String,
    pub neg: String,
    pub ctrl_pos: String,
    pub ctrl_neg: String,
    pub gm_s: f64,
}

/// A plate reverb's medium (docs/REVERB_PLAN.md, E2 / E6; `crate::plate`): a force
/// `force_per_v (v(sense_pos) - v(sense_neg))` (the exciter coil's current, sensed across
/// its resistance, times BL over that resistance; the sense draws no current) at
/// `drive_xy`, and the pickup's acceleration at `pickup_xy` times `out_per_m_s2` driving
/// `out` to ground, one sample after the force (one-way coupling: the plate's load on the
/// coil is the builder's, a resistor). Positions are fractions of the sides; `decay` is
/// the energy decay rate (1/s) against frequency (Hz).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Plate {
    pub name: String,
    pub sense_pos: String,
    pub sense_neg: String,
    pub force_per_v: f64,
    pub out: String,
    pub out_per_m_s2: f64,
    pub lx_m: f64,
    pub ly_m: f64,
    pub thickness_m: f64,
    pub density_kg_m3: f64,
    pub youngs_pa: f64,
    pub poisson: f64,
    pub tension_n_m: f64,
    pub drive_xy: [f64; 2],
    pub pickup_xy: [f64; 2],
    pub f_max_hz: f64,
    pub decay: Vec<[f64; 2]>,
    pub tail_db: f64,
}

/// A spring reverb tank's springs (docs/REVERB_PLAN.md, E1-E3; `crate::spring`;
/// `varimu/devices/spring.py` is the reference): a force `force_per_v (v(sense_pos) -
/// v(sense_neg))` (the input coil's current sensed across its resistance, times the
/// transducer's force per ampere over that resistance; the sense draws no current) at
/// every spring's input bead, and the sum of the output beads' tangential velocities times
/// `out_per_m_s` (the output coil's EMF) driving `out` to ground, one sample after the
/// force (one-way coupling: the springs' load on the coil is the builder's resistor).
/// `springs`: per spring (wire radius, helix radius, uncurled wire length) in metres;
/// `decay` the energy decay rate (1/s) against frequency (Hz). `saturation_v`: the input
/// transducer's pole pieces saturating, the force `force_per_v saturation_v tanh(v /
/// saturation_v)` (0: linear). SPICE has no springs: ngspice sees `out` held at 0 V.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Spring {
    pub name: String,
    pub sense_pos: String,
    pub sense_neg: String,
    pub force_per_v: f64,
    pub out: String,
    pub out_per_m_s: f64,
    pub density_kg_m3: f64,
    pub youngs_pa: f64,
    pub springs: Vec<[f64; 3]>,
    pub f_max_hz: f64,
    pub decay: Vec<[f64; 2]>,
    pub tail_db: f64,
    pub saturation_v: f64,
}

/// Magnetic tape between a record and a repro head (docs/TAPE_PLAN.md, TM4;
/// `crate::tape_stream`): the record gap's signal field `h_per_v (v(sense_pos) -
/// v(sense_neg))` (deep-gap A/m: the record coil's current, sensed across its resistance,
/// times the head's field per ampere over that resistance; the sense draws no current)
/// recorded with the medium's own AC bias, and the repro coil's EMF driving `out` to
/// ground one sample later (the tape read was recorded a head distance earlier). SPICE has
/// no tape: ngspice sees `out` held at 0 V.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Tape {
    pub name: String,
    pub sense_pos: String,
    pub sense_neg: String,
    pub h_per_v: f64,
    pub out: String,
    pub medium: Box<crate::tape_stream::TapeParams>,
    /// The capstan's supply (varispeed): the node whose voltage is its frequency (1 V =
    /// 1 Hz), sensed after each sample with the record head; the medium's `varispeed` motor
    /// reads it. None: no varispeed, and no such key in the JSON.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub supply: Option<String>,
    /// The record head's playback (Sel-Sync; the medium's `sync`): its EMF drives this node
    /// to ground one sample after the step, as the repro head's drives `out` (the record
    /// head's reading of the tape the repro head reads then). None: no such key.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sync_out: Option<String>,
}

/// A Rhodes harp (docs/RHODES_PLAN.md, RH3; `crate::harp`; `varimu.rhodes.harp` is the
/// reference): its keys struck by note events, the pickups' EMFs summed by their wiring
/// driving `out` to ground one sample after the step that rendered them (the harp senses
/// nothing: its coils' current doesn't act on the tines). The voices run at the least whole
/// multiple of the step rate at or above `rate_hz`, the hammer's contact at
/// `contact_rate_hz`. `model` is the compiled harp (a component version of kind `ep_harp`).
/// SPICE has no harp: ngspice sees `out` held at 0 V.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Harp {
    pub name: String,
    pub out: String,
    pub rate_hz: f64,
    pub contact_rate_hz: f64,
    pub model: Box<crate::harp::HarpModel>,
}

/// The Hohner Clavinet's strings (docs/CLAVINET_PLAN.md, CL3; `crate::clavinet`;
/// `varimu.clavinet.live` is the reference): its keys struck, held and released by note
/// events, the two pickups' EMFs driving `centre` and `bridge` to ground one sample after
/// the step that rendered them, and `bridge_neg` the bridge EMF negated (the A / D
/// rockers' reversed coil). The voices run at the least whole multiple of the step rate at
/// or above `rate_hz`, the contacts at `contact_rate_hz`. `data` is the compiled strings'
/// header (a component version of kind `clav_strings`: `varimu.clavinet.compile`), a path
/// relative to the repository's root ([`crate::clavinet::data_root`]) or absolute; its
/// float64 sidecar must have the sha256 `sha256`. `wear` (absent: as compiled) wears the
/// instrument ([`ClavWear`]). SPICE has no strings: ngspice sees the three nodes held at 0 V.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ClavStrings {
    pub name: String,
    pub centre: String,
    pub bridge: String,
    pub bridge_neg: String,
    pub rate_hz: f64,
    pub contact_rate_hz: f64,
    pub data: String,
    pub sha256: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wear: Option<ClavWear>,
}

/// A worn Clavinet (docs/CLAVINET_PLAN.md, "Variation and wear"; `varimu.clavinet.wear` is
/// the reference, [`crate::clavinet::ClavModel::worn`] the port): the unit `seed` (a whole
/// number, as the JSON's floats carry it), its `age` and each part's share of it (a part's
/// amount is age x share, at most [`crate::clavinet::WEAR_MAX`]), every one in [0, 2].
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ClavWear {
    pub seed: f64,
    pub age: f64,
    pub tuning: f64,
    pub strings: f64,
    pub tangents: f64,
    pub yarn: f64,
    pub pickups: f64,
}

/// The Hammond Novachord's keys (docs/NOVACHORD_PLAN.md, NV4; [`crate::novachord`]): keys
/// `keys` = [first, last] (whole plate leads of four), played by note events. It senses the
/// twelve oscillators' vibrato grids `grids` (F to E; the oscillators are compiled
/// phases), the attack switch's buses `abus` / `cbus`,
/// the keying supply's + rail `keyp`, the cut-off taps `cuts` (notes 45-72, 13-44, 5-12) and
/// its plate leads `plates` a sample late, and drives `outs` (one per plate lead) to the
/// lead's plate current times `v_per_a` at the next sample (the circuit's `G` parts draw it
/// from the lead). `mellow` (0 / 1) is the BRIGHT-MELLOW switch's CN30, `normal_vibrato`
/// and `small_vibrato` (0 / 1) the vibrato's switches (the oscillators' curves). `data` is the
/// compiled keys (a component version of kind `nova_keys`: `varimu.novachord.compile`), a
/// path relative to the repository's root or absolute, its sha256 `sha256`. SPICE has no
/// keys: ngspice sees `outs` held at 0 V.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NovaKeys {
    pub name: String,
    pub data: String,
    pub sha256: String,
    /// [first, last] (whole numbers, as the JSON's floats carry them).
    pub keys: Vec<f64>,
    pub mellow: f64,
    pub normal_vibrato: f64,
    pub small_vibrato: f64,
    pub v_per_a: f64,
    pub grids: Vec<String>,
    pub abus: String,
    pub cbus: String,
    pub keyp: String,
    pub cuts: Vec<String>,
    pub plates: Vec<String>,
    pub outs: Vec<String>,
}

impl NovaKeys {
    /// The nodes it senses, in the medium's order: the vibrato grids, A, C, the + rail, the
    /// cut-off taps, the plate leads.
    pub fn senses(&self) -> Vec<&str> {
        self.grids
            .iter()
            .map(String::as_str)
            .chain([self.abus.as_str(), &self.cbus, &self.keyp])
            .chain(self.cuts.iter().map(String::as_str))
            .chain(self.plates.iter().map(String::as_str))
            .collect()
    }

    /// Its keys' range, [first, last] (checked by validation).
    pub fn range(&self) -> (usize, usize) {
        (self.keys[0] as usize, self.keys[1] as usize)
    }

    fn check(&self, input: &str) -> Result<(), String> {
        let [lo, hi] = self.keys[..] else {
            return Err("keys is [first, last]".into());
        };
        if lo.fract() != 0.0 || hi.fract() != 0.0 || lo < 1.0 || hi > 72.0 {
            return Err(format!("keys [{lo}, {hi}]: whole numbers within 1-72"));
        }
        let (lo, hi) = (lo as usize, hi as usize);
        if !(1..=72).contains(&lo) || !(lo..=72).contains(&hi) || (lo - 1) % 4 != 0 || hi % 4 != 0 {
            return Err(format!(
                "keys [{lo}, {hi}]: whole plate leads of four within 1-72"
            ));
        }
        let leads = (hi - lo + 1) / 4;
        if self.grids.len() != 12 || self.cuts.len() != 3 {
            return Err("twelve vibrato grids and three cut-off taps".into());
        }
        if self.plates.len() != leads || self.outs.len() != leads {
            return Err(format!("{leads} plate leads and as many outputs"));
        }
        for (what, x) in [
            ("mellow", self.mellow),
            ("normal_vibrato", self.normal_vibrato),
            ("small_vibrato", self.small_vibrato),
        ] {
            if x != 0.0 && x != 1.0 {
                return Err(format!("{what} {x} (0 or 1)"));
            }
        }
        if self.v_per_a.is_nan() || self.v_per_a <= 0.0 || !self.v_per_a.is_finite() {
            return Err("v_per_a must be positive".into());
        }
        if self.data.is_empty()
            || self.sha256.len() != 64
            || !self.sha256.bytes().all(|b| b.is_ascii_hexdigit())
        {
            return Err("data names the compiled keys, sha256 its hash".into());
        }
        for (i, o) in self.outs.iter().enumerate() {
            if o == GROUND || o == input || self.outs[..i].contains(o) {
                return Err(format!("it drives {o} (ground, the input or twice)"));
            }
            if self.senses().contains(&o.as_str()) {
                return Err(format!("it drives {o}, which it senses"));
            }
        }
        Ok(())
    }
}

/// The Nickel Organ's keys (docs/NICKEL_ORGAN_DEVICE_PLAN.md; [`crate::nickel`];
/// `varimu/nickel/voice.py` is the reference): each key its brass bar with a nickel strip in
/// its coil, the bridge, its own tube loop and #327 lamp, struck, held and released by note
/// events; the keys' line outs, each through its mixing gain, summed onto `out` (to ground)
/// one sample after the step that rendered them (the keys sense nothing). The voices give
/// their line outs at the least whole multiple of the step rate at or above `rate_hz` and
/// step their physics at the least whole multiple of that at or above `step_hz`. `sustain`
/// and `polarize` (0-1) are the panel's SUSTAIN and POLARIZE (a change plays on); at most
/// `max_keys` (a whole number) keys sound at once: another struck silences one, a released
/// one first, else the one struck longest ago. `data` is the compiled organ (a component
/// version of kind `nickel_keys`: `varimu.nickel.compile`), a path relative to the
/// repository's root or absolute, its sha256 `sha256`. SPICE has no keys: ngspice sees
/// `out` held at 0 V.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NickelKeys {
    pub name: String,
    pub out: String,
    pub data: String,
    pub sha256: String,
    pub rate_hz: f64,
    pub step_hz: f64,
    pub sustain: f64,
    pub polarize: f64,
    pub max_keys: f64,
}

/// The Victorian synth's keyboard of self-interrupting reeds (docs/VICTORIAN_SYNTH_PLAN.md;
/// [`crate::reeds`]; `varimu/victorian/reed.py` is the reference): per key a steel reed kept
/// going by its electromagnet in a local circuit, its second contact chopping the line
/// through the carbon under the key, played by note events. It senses the local battery's
/// node `loc` and the line's node `line` a sample late (both circuits return to ground) and
/// drives `out_loc` and `out_line` to the keys' summed local and line currents times
/// `v_per_a` at the next sample (the circuit's `G` parts draw them from `loc` and `line`).
/// Each key steps at the least whole multiple of the step rate at or above `step_hz`. `data` is the compiled
/// keyboard (a component version of kind `reed_keys`: `varimu.victorian.compile`), a path
/// relative to the repository's root or absolute, its sha256 `sha256`. SPICE has no keys:
/// ngspice sees the outputs held at 0 V.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReedKeys {
    pub name: String,
    pub data: String,
    pub sha256: String,
    pub step_hz: f64,
    pub v_per_a: f64,
    pub loc: String,
    pub line: String,
    pub out_loc: String,
    pub out_line: String,
}

impl ReedKeys {
    /// The nodes it senses, in the medium's order.
    pub fn senses(&self) -> Vec<&str> {
        vec![&self.loc, &self.line]
    }

    fn check(&self, input: &str) -> Result<(), String> {
        if !(self.step_hz.is_finite() && self.step_hz > 0.0) {
            return Err(format!("step_hz = {} must be finite and > 0", self.step_hz));
        }
        if !(self.v_per_a.is_finite() && self.v_per_a > 0.0) {
            return Err("v_per_a must be positive".into());
        }
        if self.data.is_empty()
            || self.sha256.len() != 64
            || !self.sha256.bytes().all(|b| b.is_ascii_hexdigit())
        {
            return Err("data names the compiled keyboard, sha256 its hash".into());
        }
        for o in [&self.out_loc, &self.out_line] {
            if o == GROUND || o == input {
                return Err(format!("it drives {o} (ground or the input)"));
            }
            if self.senses().contains(&o.as_str()) {
                return Err(format!("it drives {o}, which it senses"));
            }
        }
        if self.out_loc == self.out_line {
            return Err(format!("it drives {} twice", self.out_loc));
        }
        Ok(())
    }
}

impl NickelKeys {
    fn check(&self, input: &str) -> Result<(), String> {
        for (what, x) in [("rate_hz", self.rate_hz), ("step_hz", self.step_hz)] {
            if !(x.is_finite() && x > 0.0) {
                return Err(format!("{what} = {x} must be finite and > 0"));
            }
        }
        for (what, x) in [("sustain", self.sustain), ("polarize", self.polarize)] {
            if !(0.0..=1.0).contains(&x) {
                return Err(format!("{what} {x} (0-1)"));
            }
        }
        if !(self.max_keys >= 1.0 && self.max_keys.fract() == 0.0 && self.max_keys <= 128.0) {
            return Err(format!(
                "max_keys {} (a whole number, 1-128)",
                self.max_keys
            ));
        }
        if self.data.is_empty()
            || self.sha256.len() != 64
            || !self.sha256.bytes().all(|b| b.is_ascii_hexdigit())
        {
            return Err("data names the compiled organ, sha256 its hash".into());
        }
        if self.out == GROUND || self.out == input {
            return Err(format!("its keys drive {} (ground or the input)", self.out));
        }
        Ok(())
    }
}

/// A triode gas thyratron as technique K's event kernels (HYBRID_PHYSICS_PLAN.md H3, "K's
/// design"; `varimu.devices.thyratron_events` is the reference, [`crate::events`] the port),
/// on the device's pins (a, g, w, k). Between events the tube is its capacitances and the
/// grid-to-anode leakage; w is held to k by a numerical 1 S (K has no state there). After
/// each sample it senses the unit's capacitor (v_ak plus `r_s_ohm` times its own current)
/// and the grid (v_gk less `r_g_ohm c_ga_f` times the ramp's slope), predicts a strike
/// within the next step and injects its charges a -> k, held over each step (a DK current
/// column). The tables over (`v_g_v`, `log_slope`), ascending, indexed [v_g][slope]: the
/// strike voltage, the dead time, the latched points (no pulse, dead 0), the anode
/// current's pulse from the strike at `ref_rate_hz` and the grid's over the same samples
/// (into the grid pin, injected g -> k), band-limited by the engine for its own step. SPICE
/// has only the off tube.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ThyratronEvents {
    pub name: String,
    pub a: String,
    pub g: String,
    pub w: String,
    pub k: String,
    pub c_gk_f: f64,
    pub c_ga_f: f64,
    pub c_ak_f: f64,
    pub g_leak_s: f64,
    pub c_f: f64,
    pub r_s_ohm: f64,
    pub r_g_ohm: f64,
    pub ref_rate_hz: f64,
    pub v_g_v: Vec<f64>,
    pub log_slope: Vec<f64>,
    pub v_s_v: Vec<Vec<f64>>,
    pub dead_s: Vec<Vec<f64>>,
    pub latched: Vec<Vec<bool>>,
    pub pulses_a: Vec<Vec<Vec<f64>>>,
    pub grid_pulses_a: Vec<Vec<Vec<f64>>>,
    pub source: String,
}

/// A relaxation oscillator's reset as technique K's event kernels (Python's
/// `varimu.circuit.ir.ResetEvents`; `varimu.devices.reset_events` is the reference,
/// [`crate::reset_events`] the port): it senses `sense` (to ground), and when that ramp,
/// falling, is predicted to cross its trigger level `v_t_v` within the next step, injects the
/// event's charges from `src` into `dst`, held over each step (a DK current column). Tables
/// over `log_slope` (ln V/s of the falling ramp, ascending): the trigger level, the dead time,
/// the injected current's pulse at `ref_rate_hz` from the event's start; `c_f` the
/// capacitance the charge lands on (the band-limiting's lag correction). Draws nothing between
/// events. SPICE has none of it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResetEvents {
    pub name: String,
    pub sense: String,
    pub src: String,
    pub dst: String,
    pub c_f: f64,
    pub ref_rate_hz: f64,
    pub log_slope: Vec<f64>,
    pub v_t_v: Vec<f64>,
    pub dead_s: Vec<f64>,
    pub pulses_a: Vec<Vec<f64>>,
    /// The discharging network's conductance per point (the deficit, removed from dst).
    pub g_s: Vec<f64>,
    pub source: String,
}

/// A comparator's output as technique K's event kernels (Python's
/// `varimu.circuit.ir.EdgeEvents`; [`crate::reset_events`] the port): it senses plus - minus,
/// and when that is predicted to cross zero within the next step in the direction that flips
/// its state (on: sinking, plus below minus), moves the current it holds from `src` into `dst`
/// to the new state's level through the table's band-limited step. `waves_a[direction][slope]`:
/// the output current from the input's zero crossing to settled at `ref_rate_hz` (direction 0
/// turning on, 1 off), over `log_slope` (ln V/s of |plus - minus|, ascending).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EdgeEvents {
    pub name: String,
    pub plus: String,
    pub minus: String,
    pub src: String,
    pub dst: String,
    pub ref_rate_hz: f64,
    pub log_slope: Vec<f64>,
    pub waves_a: Vec<Vec<Vec<f64>>>,
    pub source: String,
    /// A [`ResetEvents`] it follows (its input `follow_gain` of that reset's sensed ramp:
    /// `reset_events.EdgeRun`'s lead), absent from the JSON when none.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub follows: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub follow_gain: Option<f64>,
}

/// White noise current of one-sided density `psd_a2_hz` (A^2/Hz) from `a` through
/// the source to `b`: a resistor's Johnson noise as its Norton source (B5).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NoiseCurrent {
    pub name: String,
    pub a: String,
    pub b: String,
    pub psd_a2_hz: f64,
}

/// A tube instance's noise (B5) on device element `device` (a triode or pentode):
/// plate shot noise, density `shot_k gm` (with `partition` > 0, a pentode's
/// `(Ib / Ik) shot_k (gm + partition Ic2)`), the control grid's full shot noise
/// `2 q |Ig|`, and flicker as a voltage in series with the control grid of
/// one-sided density `flicker_v2 / f` (V^2), entered as the plate current `gm e_f`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TubeNoise {
    pub name: String,
    pub device: String,
    pub shot_k: f64,
    pub partition: f64,
    pub flicker_v2: f64,
}

/// Device element `device` (a triode, pentode or vacuum diode instance) has a heated
/// cathode (B6): its currents follow the circuit's cathode temperature (the space-charge
/// shift and the emission ceiling, [`crate::cathode`]); `is0_a` its emission at the rated
/// temperature.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeatedCathode {
    pub name: String,
    pub device: String,
    pub is0_a: f64,
}

/// An instance of a device model; `nodes` follow the model's pin order
/// ([`DeviceModel::pins`]).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Device {
    pub name: String,
    pub model: String,
    pub nodes: Vec<String>,
}

// --- Device models (mirrors of varimu/devices/*.py) ------------------------------

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum DeviceModel {
    Triode(Triode),
    Pentode(Pentode),
    JunctionDiode(JunctionDiode),
    VacuumDiode(VacuumDiode),
    MagneticCore(MagneticCore),
    Lamp(Lamp),
    Thyratron(Thyratron),
    Bjt(Bjt),
    Jfet(Jfet),
    Optocoupler(Optocoupler),
    Photocell(Photocell),
    Contact(Contact),
}

/// `varimu.devices.triode.Triode`: pins (plate, grid, cathode).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Triode {
    pub name: String,
    pub plate: PlateModel,
    pub grid: Option<GridCurrent>,
    pub c_gk: f64,
    pub c_gp: f64,
    pub c_pk: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum PlateModel {
    #[serde(rename = "koren")]
    Koren(KorenTriode),
    #[serde(rename = "varimu")]
    VariMu(VariMuTriode),
}

/// Koren (1996) triode plate current.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KorenTriode {
    pub mu: f64,
    pub ex: f64,
    pub kg1: f64,
    pub kp: f64,
    pub kvb: f64,
}

/// N parallel Koren sections with their own mu and cathode share (weights sum to 1).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VariMuTriode {
    pub mus: Vec<f64>,
    pub weights: Vec<f64>,
    pub ex: f64,
    pub kg1: f64,
    pub kp: f64,
    pub kvb: f64,
}

/// Grid-cathode conduction (smoothed Child law above the contact potential).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GridCurrent {
    pub perveance: f64,
    pub contact_v: f64,
    pub smooth_v: f64,
}

/// `varimu.devices.pentode.Pentode`: pins (plate, screen, grid 1, cathode).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Pentode {
    pub name: String,
    pub model: KorenPentode,
    /// Control-grid current (the triode's [`GridCurrent`] law).
    pub grid: Option<GridCurrent>,
    pub c_g1k: f64,
    pub c_g1p: f64,
    pub c_pk: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KorenPentode {
    pub mu: f64,
    pub ex: f64,
    pub kg1: f64,
    pub kg2: f64,
    pub kp: f64,
    pub kvb: f64,
    /// The screen law: absent, Koren's; `"e1"`, the plate's E1 (`varimu/devices/pentode.py`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub screen: Option<ScreenLaw>,
}

/// A pentode's screen-current law other than Koren's `(Vg1 + Vg2 / mu)^1.5 / Kg2`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ScreenLaw {
    /// `E1^Ex / Kg2`, E1 the plate law's.
    #[serde(rename = "e1")]
    E1,
}

/// Shockley diode with series resistance (SPICE `D`): pins (anode, cathode).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JunctionDiode {
    pub name: String,
    pub is_a: f64,
    pub n: f64,
    pub rs_ohm: f64,
    /// Newton's tolerance at its ports, as a factor (numerics only: [`crate::devices::
    /// Device::tol_scale`]; `None`: 1, the solver's own). A circuit's `devices` entry sets it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tol_scale: Option<f64>,
}

/// Child-law thermionic diode: pins (anode, cathode).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VacuumDiode {
    pub name: String,
    pub perveance: f64,
    pub smooth_v: f64,
}

/// `varimu.devices.core.MagneticCore`: a Jiles-Atherton core, pins (core node,
/// ground). Port current: `path_m * H(B)`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MagneticCore {
    pub name: String,
    pub ms_a_per_m: f64,
    pub a_a_per_m: f64,
    pub k_a_per_m: f64,
    pub c: f64,
    pub alpha: f64,
    pub path_m: f64,
}

/// `varimu.devices.lamp.Lamp`: an incandescent lamp, pins (a, t, b): the filament from a
/// to b, its temperature above ambient on t (1 V = 1 K; a 1 F capacitor from t to b holds
/// it). Port currents: the filament's current and dT/dt.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Lamp {
    pub name: String,
    pub wire_d_m: f64,
    pub wire_l_m: f64,
    pub rad_fraction: f64,
    /// Total emissivity c0 + c1 T + c2 T^2 + c3 T^3.
    pub emissivity: [f64; 4],
    pub t_amb_k: f64,
}

/// `varimu.devices.opto.Optocoupler`: an LED / photoresistor optocoupler, pins (la, lk, s,
/// ra, rb): the LED from la to lk, the cell's photoconductance on s (`s_unit_s` siemens per
/// volt; a 1 F capacitor from s to rb holds it), the cell from ra to rb. Port currents: the
/// LED's (into la, out of lk), -dg/dt / s_unit, the cell's.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Optocoupler {
    pub name: String,
    pub led_is_a: f64,
    pub led_n: f64,
    pub i_eta_a: f64,
    pub gen_s_per_s_a: f64,
    pub tau0_s: f64,
    pub kappa_s_s: f64,
    pub g_dark_s: f64,
    pub s_unit_s: f64,
}

/// `varimu.devices.photocell.Photocell`: a CdS cell lit by a lamp's filament, pins (t, tb, s,
/// ra, rb): t and tb sense the lamp's thermal node and reference (no current), the cell's
/// photoconductance on s (`s_unit_s` siemens per volt; a 1 F capacitor from s to rb holds it),
/// the cell from ra to rb. Port currents: 0, 0, -dg/dt / s_unit, the cell's.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Photocell {
    pub name: String,
    pub gen_s_per_s_lux: f64,
    pub tau0_s: f64,
    pub kappa_s_s: f64,
    pub g_dark_s: f64,
    pub lambda_m: f64,
    pub t_amb_k: f64,
    pub lux: f64,
    pub s_unit_s: f64,
}

/// `varimu.devices.contact.Contact`: a switch contact worked by a control voltage, pins
/// (a, b, c, ref): the contact from a to b, its conductance moving from 1 / r_off to
/// 1 / r_on as V(c, ref) goes from v_open to v_closed. Port currents: the contact's into a,
/// out of b; none into c.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Contact {
    pub name: String,
    pub r_on_ohm: f64,
    pub r_off_ohm: f64,
    pub v_open_v: f64,
    pub v_closed_v: f64,
}

/// A BJT's polarity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Polarity {
    Npn,
    Pnp,
}

/// `varimu.devices.bjt.Bjt`: SPICE's Gummel-Poon BJT, DC subset; pins (c, b, e). Port
/// currents: the collector's and the base's. `None` limits are infinite (SPICE's 0). The
/// parasitics (`rb_ohm` .. `cjc_f`) are the `bjt` part's linear elements, which the
/// builders place around the device; the device ignores them.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Bjt {
    pub name: String,
    pub polarity: Polarity,
    pub is_a: f64,
    pub bf: f64,
    pub br: f64,
    pub nf: f64,
    pub nr: f64,
    pub vaf_v: Option<f64>,
    pub var_v: Option<f64>,
    pub ikf_a: Option<f64>,
    pub ikr_a: Option<f64>,
    pub ise_a: f64,
    pub ne: f64,
    pub isc_a: f64,
    pub nc: f64,
    pub rb_ohm: f64,
    pub rc_ohm: f64,
    pub re_ohm: f64,
    pub cje_f: f64,
    pub cjc_f: f64,
    /// The junction temperature (K) and SPICE's temperature parameters EG (eV), XTI, XTB;
    /// `None`: TNOM and SPICE's defaults (`bjt.py`'s docstring, "Temperature").
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub temp_k: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub eg_ev: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub xti: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub xtb: Option<f64>,
    /// Newton's tolerance at its ports, as a factor (numerics only: [`crate::devices::
    /// Device::tol_scale`]; `None`: 1, the solver's own). A circuit's `devices` entry sets it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tol_scale: Option<f64>,
}

/// A JFET's channel type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum JfetPolarity {
    Njf,
    Pjf,
}

/// `varimu.devices.jfet.Jfet`: SPICE's level-1 JFET (DC); pins (d, g, s). Port currents: the
/// drain's and the gate's. The parasitics (`rd_ohm` .. `cgd_f`) are the `jfet` part's linear
/// elements, which the builders place around the device; the device ignores them.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Jfet {
    pub name: String,
    pub polarity: JfetPolarity,
    pub vto_v: f64,
    pub beta_a_per_v2: f64,
    pub lambda_per_v: f64,
    pub is_a: f64,
    pub n: f64,
    pub b: f64,
    pub pb_v: f64,
    pub rd_ohm: f64,
    pub rs_ohm: f64,
    pub cgs_f: f64,
    pub cgd_f: f64,
}

/// `varimu.devices.thyratron.Thyratron`: a hot-cathode gas thyratron as a lumped plasma.
/// A tetrode (`mu_g2` set) has pins (a, g2, g1, w, k): the anode, the shield and control
/// grids, the plasma's state (ln of its ion density; a 1 F capacitor from w to k holds it)
/// and the cathode; a triode (`mu_g2` None) pins (a, g, w, k). Port currents: the anode's,
/// the shield grid's (none), the control grid's and -dw/dt.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Thyratron {
    pub name: String,
    pub mu_a: f64,
    pub mu_g2: Option<f64>,
    pub v0_v: f64,
    pub e_v: f64,
    pub perveance: f64,
    pub x_n: f64,
    pub v_x_v: f64,
    pub k_ion: f64,
    pub v_ion_v: f64,
    pub w_ion_v: f64,
    pub c_meta: f64,
    pub v_meta_v: f64,
    pub w_meta_v: f64,
    pub tau_diff_s: f64,
    pub k_grid: f64,
    pub p_grid: f64,
    pub v_float_v: f64,
    pub t_e_v: f64,
    pub q_s_c: f64,
    pub g_leak_s: f64,
    pub s0_per_s: f64,
    pub c_gk: f64,
    pub c_ga: f64,
    pub c_ak: f64,
}

impl DeviceModel {
    pub fn name(&self) -> &str {
        match self {
            DeviceModel::Triode(m) => &m.name,
            DeviceModel::Pentode(m) => &m.name,
            DeviceModel::JunctionDiode(m) => &m.name,
            DeviceModel::VacuumDiode(m) => &m.name,
            DeviceModel::MagneticCore(m) => &m.name,
            DeviceModel::Lamp(m) => &m.name,
            DeviceModel::Optocoupler(m) => &m.name,
            DeviceModel::Photocell(m) => &m.name,
            DeviceModel::Contact(m) => &m.name,
            DeviceModel::Bjt(m) => &m.name,
            DeviceModel::Jfet(m) => &m.name,
            DeviceModel::Thyratron(m) => &m.name,
        }
    }

    /// Pin names, in the order of [`Device::nodes`].
    pub fn pins(&self) -> &'static [&'static str] {
        match self {
            DeviceModel::Triode(_) => &["p", "g", "k"],
            DeviceModel::Pentode(_) => &["p", "g2", "g1", "k"],
            DeviceModel::JunctionDiode(_) | DeviceModel::VacuumDiode(_) => &["a", "k"],
            DeviceModel::MagneticCore(_) => &["b", "ref"],
            DeviceModel::Lamp(_) => &["a", "t", "b"],
            DeviceModel::Optocoupler(_) => &["la", "lk", "s", "ra", "rb"],
            DeviceModel::Photocell(_) => &["t", "tb", "s", "ra", "rb"],
            DeviceModel::Contact(_) => &["a", "b", "c", "ref"],
            DeviceModel::Bjt(_) => &["c", "b", "e"],
            DeviceModel::Jfet(_) => &["d", "g", "s"],
            DeviceModel::Thyratron(t) if t.mu_g2.is_some() => &["a", "g2", "g1", "w", "k"],
            DeviceModel::Thyratron(_) => &["a", "g", "w", "k"],
        }
    }

    /// SPICE letter of an instance: `D` for the built-in diode, `Q` for the built-in BJT,
    /// `X` for subcircuits.
    pub fn instance_prefix(&self) -> char {
        match self {
            DeviceModel::JunctionDiode(_) => 'D',
            DeviceModel::Bjt(_) => 'Q',
            DeviceModel::Jfet(_) => 'J',
            _ => 'X',
        }
    }
}

impl Element {
    pub fn name(&self) -> &str {
        match self {
            Element::Resistor(e) => &e.name,
            Element::Capacitor(e) => &e.name,
            Element::Inductor(e) => &e.name,
            Element::Coupling(e) => &e.name,
            Element::VoltageSource(e) => &e.name,
            Element::SineSource(e) => &e.name,
            Element::Winding(e) => &e.name,
            Element::Vccs(e) => &e.name,
            Element::NoiseCurrent(e) => &e.name,
            Element::TubeNoise(e) => &e.name,
            Element::HeatedCathode(e) => &e.name,
            Element::Device(e) => &e.name,
            Element::Plate(e) => &e.name,
            Element::Spring(e) => &e.name,
            Element::Tape(e) => &e.name,
            Element::Harp(e) => &e.name,
            Element::ClavStrings(e) => &e.name,
            Element::NovaKeys(e) => &e.name,
            Element::NickelKeys(e) => &e.name,
            Element::ReedKeys(e) => &e.name,
            Element::ThyratronEvents(e) => &e.name,
            Element::ResetEvents(e) => &e.name,
            Element::EdgeEvents(e) => &e.name,
        }
    }

    /// Circuit nodes the element connects (none for a coupling).
    pub fn nodes(&self) -> Vec<&str> {
        match self {
            Element::Resistor(e) => vec![&e.a, &e.b],
            Element::Capacitor(e) => vec![&e.a, &e.b],
            Element::Inductor(e) => vec![&e.a, &e.b],
            Element::Coupling(_) => vec![],
            Element::VoltageSource(e) => vec![&e.pos, &e.neg],
            Element::SineSource(e) => vec![&e.pos, &e.neg],
            Element::Winding(e) => vec![&e.a, &e.b, &e.core],
            Element::Vccs(e) => vec![&e.pos, &e.neg, &e.ctrl_pos, &e.ctrl_neg],
            Element::NoiseCurrent(e) => vec![&e.a, &e.b],
            Element::TubeNoise(_) | Element::HeatedCathode(_) => vec![],
            Element::Device(e) => e.nodes.iter().map(String::as_str).collect(),
            Element::Plate(e) => vec![&e.sense_pos, &e.sense_neg, &e.out],
            Element::Spring(e) => vec![&e.sense_pos, &e.sense_neg, &e.out],
            Element::Tape(e) => {
                let mut v = vec![e.sense_pos.as_str(), &e.sense_neg, &e.out];
                v.extend(e.supply.as_deref());
                v.extend(e.sync_out.as_deref());
                v
            }
            Element::Harp(e) => vec![&e.out],
            Element::ClavStrings(e) => vec![&e.centre, &e.bridge, &e.bridge_neg],
            Element::NovaKeys(e) => {
                let mut v = e.senses();
                v.extend(e.outs.iter().map(String::as_str));
                v
            }
            Element::NickelKeys(e) => vec![&e.out],
            Element::ReedKeys(e) => vec![&e.loc, &e.line, &e.out_loc, &e.out_line],
            Element::ThyratronEvents(e) => vec![&e.a, &e.g, &e.w, &e.k],
            Element::ResetEvents(e) => vec![&e.sense, &e.src, &e.dst],
            Element::EdgeEvents(e) => vec![&e.plus, &e.minus, &e.src, &e.dst],
        }
    }
}

// --- Errors, (de)serialization, validation ----------------------------------------

#[derive(Debug, Clone, PartialEq)]
pub struct IrError(pub String);

impl fmt::Display for IrError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "circuit IR: {}", self.0)
    }
}

impl std::error::Error for IrError {}

/// An ascending axis of two or more finite values (Python's `_validate_axis`).
fn validate_axis(what: &str, ax: &[f64]) -> Result<(), IrError> {
    if ax.len() < 2 || !ax.iter().all(|x| x.is_finite()) {
        return err(format!("{what}: two or more finite values"));
    }
    if ax.windows(2).any(|w| w[1] <= w[0]) {
        return err(format!("{what}: ascending"));
    }
    Ok(())
}

/// The checks of a reset's event kernels (Python's `_validate_reset_events`).
fn validate_reset_events(e: &ResetEvents) -> Result<(), IrError> {
    let name = &e.name;
    for (k, v) in [("c_f", e.c_f), ("ref_rate_hz", e.ref_rate_hz)] {
        positive(&format!("{name}.{k}"), v)?;
    }
    validate_axis(&format!("{name}.log_slope"), &e.log_slope)?;
    let n = e.log_slope.len();
    for (k, l) in [
        ("v_t_v", e.v_t_v.len()),
        ("dead_s", e.dead_s.len()),
        ("pulses_a", e.pulses_a.len()),
        ("g_s", e.g_s.len()),
    ] {
        if l != n {
            return err(format!("{name}.{k}: one per log_slope point"));
        }
    }
    for ((v, d), p) in e.v_t_v.iter().zip(&e.dead_s).zip(&e.pulses_a) {
        if !v.is_finite() {
            return err(format!("{name}.v_t_v: finite, got {v}"));
        }
        nonneg(&format!("{name}.dead_s"), *d)?;
        if p.is_empty() || !p.iter().all(|x| x.is_finite()) {
            return err(format!("{name}: a pulse of finite samples at every point"));
        }
    }
    for g in &e.g_s {
        nonneg(&format!("{name}.g_s"), *g)?;
    }
    if e.src == e.dst {
        return err(format!("{name}: src and dst on two nodes"));
    }
    Ok(())
}

/// The checks of a comparator edge's event kernels (Python's `_validate_edge_events`).
fn validate_edge_events(e: &EdgeEvents) -> Result<(), IrError> {
    let name = &e.name;
    positive(&format!("{name}.ref_rate_hz"), e.ref_rate_hz)?;
    validate_axis(&format!("{name}.log_slope"), &e.log_slope)?;
    if e.waves_a.len() != 2 || e.waves_a.iter().any(|r| r.len() != e.log_slope.len()) {
        return err(format!(
            "{name}.waves_a: two directions of one wave per log_slope point"
        ));
    }
    for w in e.waves_a.iter().flatten() {
        if w.len() < 2 || !w.iter().all(|x| x.is_finite()) || w[0] == w[w.len() - 1] {
            return err(format!(
                "{name}: a wave of finite samples between two levels"
            ));
        }
    }
    if e.plus == e.minus || e.src == e.dst {
        return err(format!(
            "{name}: plus and minus, src and dst on two nodes each"
        ));
    }
    if e.follows.is_some() != e.follow_gain.is_some() {
        return err(format!("{name}: follows and follow_gain together"));
    }
    if let Some(g) = e.follow_gain {
        positive(&format!("{name}.follow_gain"), g)?;
    }
    Ok(())
}

/// The checks of a thyratron's event kernels (Python's `_validate_thyratron_events`).
fn validate_thyratron_events(e: &ThyratronEvents) -> Result<(), IrError> {
    let name = &e.name;
    for (k, v) in [
        ("c_f", e.c_f),
        ("r_s_ohm", e.r_s_ohm),
        ("r_g_ohm", e.r_g_ohm),
        ("ref_rate_hz", e.ref_rate_hz),
    ] {
        positive(&format!("{name}.{k}"), v)?;
    }
    for (k, v) in [
        ("c_gk_f", e.c_gk_f),
        ("c_ga_f", e.c_ga_f),
        ("c_ak_f", e.c_ak_f),
        ("g_leak_s", e.g_leak_s),
    ] {
        nonneg(&format!("{name}.{k}"), v)?;
    }
    for (k, ax) in [("v_g_v", &e.v_g_v), ("log_slope", &e.log_slope)] {
        if ax.len() < 2 || !ax.iter().all(|x| x.is_finite()) {
            return err(format!("{name}.{k}: two or more finite values"));
        }
        if ax.windows(2).any(|w| w[1] <= w[0]) {
            return err(format!("{name}.{k}: ascending"));
        }
    }
    let (nv, ns) = (e.v_g_v.len(), e.log_slope.len());
    let shaped = |lens: Vec<usize>| lens.len() == nv && lens.iter().all(|&l| l == ns);
    for (k, ok) in [
        ("v_s_v", shaped(e.v_s_v.iter().map(Vec::len).collect())),
        ("dead_s", shaped(e.dead_s.iter().map(Vec::len).collect())),
        ("latched", shaped(e.latched.iter().map(Vec::len).collect())),
        (
            "pulses_a",
            shaped(e.pulses_a.iter().map(Vec::len).collect()),
        ),
        (
            "grid_pulses_a",
            shaped(e.grid_pulses_a.iter().map(Vec::len).collect()),
        ),
    ] {
        if !ok {
            return err(format!(
                "{name}.{k}: {nv} rows of {ns} (v_g_v by log_slope)"
            ));
        }
    }
    let mut live = 0;
    for i in 0..nv {
        for j in 0..ns {
            let (v, dead, latched, p) = (
                e.v_s_v[i][j],
                e.dead_s[i][j],
                e.latched[i][j],
                &e.pulses_a[i][j],
            );
            finite(&format!("{name}.v_s_v"), v)?;
            nonneg(&format!("{name}.dead_s"), dead)?;
            if latched && (!p.is_empty() || dead != 0.0) {
                return err(format!(
                    "{name}: a latched point has no pulse and no dead time"
                ));
            }
            if !latched && (p.is_empty() || !p.iter().all(|x| x.is_finite())) {
                return err(format!(
                    "{name}: a pulse of finite samples at every point not latched"
                ));
            }
            let gp = &e.grid_pulses_a[i][j];
            if gp.len() != p.len() || !gp.iter().all(|x| x.is_finite()) {
                return err(format!(
                    "{name}: a grid pulse of finite samples as long as the anode's"
                ));
            }
            live += usize::from(!latched);
        }
    }
    if live == 0 {
        return err(format!("{name}: every point latched"));
    }
    let pins: HashSet<&str> = [&e.a, &e.g, &e.w, &e.k]
        .iter()
        .map(|s| s.as_str())
        .collect();
    if pins.len() != 4 {
        return err(format!("{name}: its pins (a, g, w, k) on four nodes"));
    }
    Ok(())
}

fn err<T>(msg: impl Into<String>) -> Result<T, IrError> {
    Err(IrError(msg.into()))
}

fn positive(what: &str, x: f64) -> Result<(), IrError> {
    if x.is_finite() && x > 0.0 {
        Ok(())
    } else {
        err(format!("{what} = {x} must be finite and > 0"))
    }
}

fn nonneg(what: &str, x: f64) -> Result<(), IrError> {
    if x.is_finite() && x >= 0.0 {
        Ok(())
    } else {
        err(format!("{what} = {x} must be finite and >= 0"))
    }
}

fn finite(what: &str, x: f64) -> Result<(), IrError> {
    if x.is_finite() {
        Ok(())
    } else {
        err(format!("{what} = {x} must be finite"))
    }
}

impl CircuitIr {
    /// Parse and validate.
    pub fn from_json(text: &str) -> Result<Self, IrError> {
        let ir: CircuitIr = serde_json::from_str(text).map_err(|e| IrError(e.to_string()))?;
        ir.validate()?;
        Ok(ir)
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).expect("IR types always serialize")
    }

    pub fn elements(&self) -> impl Iterator<Item = &Element> {
        self.sections.iter().flat_map(|s| s.elements.iter())
    }

    pub fn model(&self, name: &str) -> Option<&DeviceModel> {
        self.models.iter().find(|m| m.name() == name)
    }

    /// The same checks as `CircuitIR.validate()` in Python.
    /// Whether a section runs at substeps of its own (a multi-rate part: `partition.rs`).
    pub fn multirate(&self) -> bool {
        self.sections
            .iter()
            .any(|s| s.substeps.is_some_and(|m| m > 1))
    }

    /// The control inputs that are audio ([`Control::audio`]): their indices, IR order.
    pub fn audio_controls(&self) -> Vec<usize> {
        (0..self.controls.len())
            .filter(|&k| self.controls[k].audio)
            .collect()
    }

    pub fn validate(&self) -> Result<(), IrError> {
        if self.version != IR_VERSION {
            return err(format!(
                "version {} (this build reads {IR_VERSION})",
                self.version
            ));
        }

        let mut models: HashMap<&str, &DeviceModel> = HashMap::new();
        for m in &self.models {
            if models.insert(m.name(), m).is_some() {
                return err(format!("duplicate model {}", m.name()));
            }
            validate_model(m)?;
        }
        if let Some(s) = self.sections.iter().find(|s| s.substeps == Some(0)) {
            return err(format!(
                "section {:?}: substeps 0 (a count, 1 or more)",
                s.title
            ));
        }
        for s in &self.sections {
            let multirate = s.substeps.is_some_and(|m| m > 1);
            if s.decimate.is_some() && !multirate {
                return err(format!(
                    "section {:?}: decimate in a section without substeps",
                    s.title
                ));
            }
            if s.owns.as_ref().is_some_and(|o| o.is_empty() || !multirate) {
                return err(format!(
                    "section {:?}: owns needs nodes, in a multi-rate section",
                    s.title
                ));
            }
            if let Some(l) = s.lag_samples
                && (l == 0 || !multirate || s.decimate.is_some() || s.owns.is_some())
            {
                return err(format!(
                    "section {:?}: lag_samples {l} (1 or more, in a multi-rate section that \
                     owns nothing and doesn't decimate)",
                    s.title
                ));
            }
            if (s.method.is_some() || s.tube_tables.is_some()) && !multirate {
                return err(format!(
                    "section {:?}: method and tube_tables are for a multi-rate section",
                    s.title
                ));
            }
            if let Some(m) = &s.method
                && let Err(e) = crate::transient::Method::parse(m)
            {
                return err(format!("section {:?}: {e}", s.title));
            }
        }

        let mut names = HashSet::new();
        // reset event kernels seen so far (an edge may follow one)
        let mut resets_before: HashSet<&str> = HashSet::new();
        let mut inductors = HashSet::new();
        let mut nodes: HashSet<&str> = HashSet::new();
        for el in self.elements() {
            let name = el.name();
            if !names.insert(name.to_ascii_uppercase()) {
                return err(format!("duplicate element name {name}"));
            }
            let prefix = match el {
                Element::Resistor(e) => {
                    positive(&format!("{name}.r_ohm"), e.r_ohm)?;
                    'R'
                }
                Element::Capacitor(e) => {
                    positive(&format!("{name}.c_f"), e.c_f)?;
                    if let Some(v0) = e.v0_v {
                        finite(&format!("{name}.v0_v"), v0)?;
                    }
                    'C'
                }
                Element::Inductor(e) => {
                    positive(&format!("{name}.l_h"), e.l_h)?;
                    inductors.insert(name);
                    'L'
                }
                Element::Coupling(e) => {
                    if !(e.k.is_finite() && e.k != 0.0 && e.k.abs() <= 1.0) {
                        return err(format!("{name}.k = {} must be in [-1, 0) or (0, 1]", e.k));
                    }
                    'K'
                }
                Element::VoltageSource(e) => {
                    finite(&format!("{name}.dc_v"), e.dc_v)?;
                    'V'
                }
                Element::SineSource(e) => {
                    finite(&format!("{name}.offset_v"), e.offset_v)?;
                    finite(&format!("{name}.amplitude_v"), e.amplitude_v)?;
                    positive(&format!("{name}.freq_hz"), e.freq_hz)?;
                    finite(&format!("{name}.phase_deg"), e.phase_deg)?;
                    'V'
                }
                Element::Winding(e) => {
                    positive(&format!("{name}.turns"), e.turns)?;
                    positive(&format!("{name}.area_m2"), e.area_m2)?;
                    if e.core == GROUND || e.core == e.a || e.core == e.b {
                        return err(format!("{name}: core node {} must be its own node", e.core));
                    }
                    'L'
                }
                Element::Vccs(e) => {
                    if !(e.gm_s.is_finite() && e.gm_s != 0.0) {
                        return err(format!(
                            "{name}.gm_s = {} must be finite and nonzero",
                            e.gm_s
                        ));
                    }
                    for (a, b) in [(&e.pos, &e.neg), (&e.ctrl_pos, &e.ctrl_neg)] {
                        if a == b {
                            return err(format!("{name}: both ends on node {a}"));
                        }
                    }
                    'G'
                }
                Element::NoiseCurrent(e) => {
                    nonneg(&format!("{name}.psd_a2_hz"), e.psd_a2_hz)?;
                    'I'
                }
                Element::TubeNoise(e) => {
                    nonneg(&format!("{name}.shot_k"), e.shot_k)?;
                    nonneg(&format!("{name}.partition"), e.partition)?;
                    nonneg(&format!("{name}.flicker_v2"), e.flicker_v2)?;
                    'B'
                }
                Element::HeatedCathode(e) => {
                    positive(&format!("{name}.is0_a"), e.is0_a)?;
                    'B'
                }
                Element::Plate(e) => {
                    for (k, v) in [
                        ("lx_m", e.lx_m),
                        ("ly_m", e.ly_m),
                        ("thickness_m", e.thickness_m),
                        ("density_kg_m3", e.density_kg_m3),
                        ("youngs_pa", e.youngs_pa),
                        ("f_max_hz", e.f_max_hz),
                        ("tail_db", e.tail_db),
                    ] {
                        positive(&format!("{name}.{k}"), v)?;
                    }
                    nonneg(&format!("{name}.tension_n_m"), e.tension_n_m)?;
                    for (k, v) in [
                        ("force_per_v", e.force_per_v),
                        ("out_per_m_s2", e.out_per_m_s2),
                    ] {
                        finite(&format!("{name}.{k}"), v)?;
                    }
                    if !(0.0..0.5).contains(&e.poisson) {
                        return err(format!(
                            "{name}.poisson = {} must be in [0, 0.5)",
                            e.poisson
                        ));
                    }
                    for xy in [e.drive_xy, e.pickup_xy] {
                        if !xy.iter().all(|v| *v > 0.0 && *v < 1.0) {
                            return err(format!(
                                "{name}: position {xy:?} must be inside the plate (0..1)"
                            ));
                        }
                    }
                    if e.decay.is_empty()
                        || e.decay
                            .iter()
                            .any(|d| !(d[0] > 0.0 && d[1] >= 0.0 && d[1].is_finite()))
                        || e.decay.windows(2).any(|w| w[1][0] <= w[0][0])
                    {
                        return err(format!(
                            "{name}.decay: (Hz, 1/s) points rising in Hz, rates finite and >= 0"
                        ));
                    }
                    if e.sense_pos == e.sense_neg {
                        return err(format!(
                            "{name}: its force senses {} against itself",
                            e.sense_pos
                        ));
                    }
                    if e.out == GROUND || e.out == self.input_node {
                        return err(format!(
                            "{name}: its pickup drives {} (ground or the input)",
                            e.out
                        ));
                    }
                    'V'
                }
                Element::Spring(e) => {
                    for (k, v) in [
                        ("density_kg_m3", e.density_kg_m3),
                        ("youngs_pa", e.youngs_pa),
                        ("f_max_hz", e.f_max_hz),
                        ("tail_db", e.tail_db),
                    ] {
                        positive(&format!("{name}.{k}"), v)?;
                    }
                    for (k, v) in [
                        ("force_per_v", e.force_per_v),
                        ("out_per_m_s", e.out_per_m_s),
                    ] {
                        finite(&format!("{name}.{k}"), v)?;
                    }
                    nonneg(&format!("{name}.saturation_v"), e.saturation_v)?;
                    if e.springs.is_empty()
                        || e.springs
                            .iter()
                            .any(|s| !(s.iter().all(|v| *v > 0.0 && v.is_finite()) && s[0] < s[1]))
                    {
                        return err(format!(
                            "{name}.springs: (wire radius, helix radius, length) per spring,                              positive, the wire thinner than the helix"
                        ));
                    }
                    if e.decay.is_empty()
                        || e.decay
                            .iter()
                            .any(|d| !(d[0] > 0.0 && d[1] >= 0.0 && d[1].is_finite()))
                        || e.decay.windows(2).any(|w| w[1][0] <= w[0][0])
                    {
                        return err(format!(
                            "{name}.decay: (Hz, 1/s) points rising in Hz, rates finite and >= 0"
                        ));
                    }
                    if e.sense_pos == e.sense_neg {
                        return err(format!(
                            "{name}: its force senses {} against itself",
                            e.sense_pos
                        ));
                    }
                    if e.out == GROUND || e.out == self.input_node {
                        return err(format!(
                            "{name}: its output drives {} (ground or the input)",
                            e.out
                        ));
                    }
                    'V'
                }
                Element::Tape(e) => {
                    finite(&format!("{name}.h_per_v"), e.h_per_v)?;
                    if let Err(m) = e.medium.check(None) {
                        return err(format!("{name}: {m}"));
                    }
                    if e.supply.is_some() != e.medium.varispeed.is_some() {
                        return err(format!(
                            "{name}: a supply node and a varispeed motor go together"
                        ));
                    }
                    // A tape fed by another part senses ground in its own (partition.rs).
                    let remote = e.sense_pos == GROUND && e.sense_neg == GROUND;
                    if e.sense_pos == e.sense_neg && !remote {
                        return err(format!(
                            "{name}: its record head senses {} against itself",
                            e.sense_pos
                        ));
                    }
                    if e.out == GROUND || e.out == self.input_node {
                        return err(format!(
                            "{name}: its repro head drives {} (ground or the input)",
                            e.out
                        ));
                    }
                    if e.sync_out.is_some() != e.medium.sync.is_some() {
                        return err(format!(
                            "{name}: a sync node and the medium's sync readout go together"
                        ));
                    }
                    if let Some(y) = &e.sync_out
                        && (y == GROUND || *y == self.input_node || *y == e.out)
                    {
                        return err(format!(
                            "{name}: its record head drives {y} (ground, the input or out)"
                        ));
                    }
                    'V'
                }
                Element::Harp(e) => {
                    positive(&format!("{name}.rate_hz"), e.rate_hz)?;
                    positive(&format!("{name}.contact_rate_hz"), e.contact_rate_hz)?;
                    if let Err(m) = e.model.check() {
                        return err(format!("{name}: {m}"));
                    }
                    if e.out == GROUND || e.out == self.input_node {
                        return err(format!(
                            "{name}: its pickups drive {} (ground or the input)",
                            e.out
                        ));
                    }
                    'V'
                }
                Element::ClavStrings(e) => {
                    positive(&format!("{name}.rate_hz"), e.rate_hz)?;
                    positive(&format!("{name}.contact_rate_hz"), e.contact_rate_hz)?;
                    if e.data.is_empty()
                        || e.sha256.len() != 64
                        || !e.sha256.bytes().all(|b| b.is_ascii_hexdigit())
                    {
                        return err(format!(
                            "{name}: data names the strings' header, sha256 its sidecar's"
                        ));
                    }
                    if let Some(w) = &e.wear {
                        crate::clavinet::check_wear(w)
                            .map_err(|m| IrError(format!("{name}.wear: {m}")))?;
                    }
                    let outs = [&e.centre, &e.bridge, &e.bridge_neg];
                    for (i, o) in outs.iter().enumerate() {
                        if *o == GROUND || **o == self.input_node || outs[..i].contains(o) {
                            return err(format!(
                                "{name}: its pickups drive {o} (ground, the input or twice)"
                            ));
                        }
                    }
                    'V'
                }
                Element::NovaKeys(e) => {
                    if let Err(m) = e.check(&self.input_node) {
                        return err(format!("{name}: {m}"));
                    }
                    'V'
                }
                Element::NickelKeys(e) => {
                    if let Err(m) = e.check(&self.input_node) {
                        return err(format!("{name}: {m}"));
                    }
                    'V'
                }
                Element::ReedKeys(e) => {
                    if let Err(m) = e.check(&self.input_node) {
                        return err(format!("{name}: {m}"));
                    }
                    'V'
                }
                Element::ThyratronEvents(e) => {
                    validate_thyratron_events(e)?;
                    'X'
                }
                Element::ResetEvents(e) => {
                    validate_reset_events(e)?;
                    resets_before.insert(e.name.as_str());
                    'X'
                }
                Element::EdgeEvents(e) => {
                    validate_edge_events(e)?;
                    if let Some(f) = &e.follows
                        && !resets_before.contains(f.as_str())
                    {
                        return err(format!(
                            "{name}: follows {f}, no reset's event kernels before it"
                        ));
                    }
                    'X'
                }
                Element::Device(e) => {
                    let Some(m) = models.get(e.model.as_str()) else {
                        return err(format!("{name}: unknown model {}", e.model));
                    };
                    if e.nodes.len() != m.pins().len() {
                        return err(format!(
                            "{name}: {} nodes, model {} has pins {:?}",
                            e.nodes.len(),
                            e.model,
                            m.pins()
                        ));
                    }
                    m.instance_prefix()
                }
            };
            if !name.to_ascii_uppercase().starts_with(prefix) {
                return err(format!("element {name} must start with {prefix}"));
            }
            let el_nodes = el.nodes();
            if el_nodes.len() == 2 && el_nodes[0] == el_nodes[1] {
                return err(format!("{name}: both ends on node {}", el_nodes[0]));
            }
            for n in el_nodes {
                if n.is_empty() || n.chars().any(char::is_whitespace) {
                    return err(format!("{name}: bad node name {n:?}"));
                }
                nodes.insert(n);
            }
        }
        // Tube noise names a tube instance, once.
        let devices: HashMap<&str, &Device> = self
            .elements()
            .filter_map(|e| match e {
                Element::Device(d) => Some((d.name.as_str(), d)),
                _ => None,
            })
            .collect();
        let mut noisy = HashSet::new();
        let mut heated = HashSet::new();
        for el in self.elements() {
            if let Element::HeatedCathode(h) = el {
                let tube = matches!(
                    devices
                        .get(h.device.as_str())
                        .map(|d| models[d.model.as_str()]),
                    Some(
                        DeviceModel::Triode(_)
                            | DeviceModel::Pentode(_)
                            | DeviceModel::VacuumDiode(_)
                    )
                );
                if !tube {
                    return err(format!("{}: {} is not a tube instance", h.name, h.device));
                }
                if !heated.insert(h.device.as_str()) {
                    return err(format!("{}: {} is heated twice", h.name, h.device));
                }
                if self.heaters.is_none() {
                    return err(format!(
                        "{}: a heated cathode needs the `heaters` block",
                        h.name
                    ));
                }
            }
            if let Element::TubeNoise(t) = el {
                let m = devices
                    .get(t.device.as_str())
                    .map(|d| models[d.model.as_str()]);
                let pentode = match m {
                    Some(DeviceModel::Triode(_)) => false,
                    Some(DeviceModel::Pentode(_)) => true,
                    _ => {
                        return err(format!(
                            "{}: {} is not a triode or pentode instance",
                            t.name, t.device
                        ));
                    }
                };
                if t.partition > 0.0 && !pentode {
                    return err(format!("{}: partition noise needs a pentode", t.name));
                }
                if !noisy.insert(t.device.as_str()) {
                    return err(format!("{}: {} has noise twice", t.name, t.device));
                }
            }
        }
        // Couplings are checked once every inductor is known.
        for el in self.elements() {
            if let Element::Coupling(c) = el {
                for l in [&c.l_a, &c.l_b] {
                    if !inductors.contains(l.as_str()) {
                        return err(format!("{}: {l} is not an inductor", c.name));
                    }
                }
                if c.l_a == c.l_b {
                    return err(format!("{}: couples {} to itself", c.name, c.l_a));
                }
            }
        }

        // A source's nodes need other elements: its control draws no current and
        // its output alone would be a current into nothing.
        let others: HashSet<&str> = self
            .elements()
            .filter(|e| !matches!(e, Element::Vccs(_)))
            .flat_map(|e| e.nodes())
            .collect();
        for el in self.elements() {
            if let Element::Vccs(g) = el {
                for n in el.nodes() {
                    if n != GROUND && !others.contains(n) {
                        return err(format!("{}: node {n} has no other element", g.name));
                    }
                }
            }
        }

        if !nodes.contains(GROUND) {
            return err("no element connects to ground (node \"0\")");
        }
        if !nodes.contains(self.input_node.as_str()) {
            return err(format!("input node {} is not connected", self.input_node));
        }
        for (i, c) in self.controls.iter().enumerate() {
            if c.node == GROUND || c.node == self.input_node {
                return err(format!(
                    "control {}: node {} is ground or the input",
                    c.name, c.node
                ));
            }
            if !nodes.contains(c.node.as_str()) {
                return err(format!(
                    "control {}: node {} is not connected",
                    c.name, c.node
                ));
            }
            if self.controls[..i]
                .iter()
                .any(|d| d.name == c.name || d.node == c.node)
            {
                return err(format!("control {}: a name or node twice", c.name));
            }
        }
        for p in &self.probes {
            let Probe::Voltage { node } = p;
            if !nodes.contains(node.as_str()) {
                return err(format!("probe node {node} is not connected"));
            }
        }
        if let Some(h) = &self.heaters {
            for (what, x) in [
                ("t0_k", h.t0_k),
                ("t_amb_k", h.t_amb_k),
                ("tau_s", h.tau_s),
                ("phi_ev", h.phi_ev),
                ("n", h.n),
                ("reserve", h.reserve),
                ("heater_ratio", h.heater_ratio),
            ] {
                positive(&format!("heaters.{what}"), x)?;
            }
            nonneg("heaters.alpha", h.alpha)?;
            if h.start != "warm" && h.start != "cold" {
                return err(format!("heaters.start {:?}: warm or cold", h.start));
            }
            if h.t_amb_k >= h.t0_k {
                return err("heaters: t_amb_k must be below t0_k");
            }
        }
        if let Some(n) = &self.noise {
            positive("noise.rate_hz", n.rate_hz)?;
            nonneg("noise.mains_rms", n.mains_rms)?;
            for m in &n.mains_sources {
                if !self
                    .elements()
                    .any(|e| matches!(e, Element::SineSource(s) if &s.name == m))
                {
                    return err(format!("noise.mains_sources: {m} is not a sine source"));
                }
            }
        }
        Ok(())
    }
}

fn validate_model(m: &DeviceModel) -> Result<(), IrError> {
    let name = m.name();
    let mut values: Vec<(&str, f64)> = Vec::new();
    match m {
        DeviceModel::Triode(t) => {
            match &t.plate {
                PlateModel::Koren(k) => {
                    values.extend([("mu", k.mu), ("ex", k.ex), ("kg1", k.kg1)]);
                    values.extend([("kp", k.kp), ("kvb", k.kvb)]);
                }
                PlateModel::VariMu(v) => {
                    if v.mus.is_empty() || v.mus.len() != v.weights.len() {
                        return err(format!(
                            "{name}: mus and weights need the same, nonzero length"
                        ));
                    }
                    values.extend(v.mus.iter().map(|&x| ("mus[]", x)));
                    values.extend(v.weights.iter().map(|&x| ("weights[]", x)));
                    values.extend([("ex", v.ex), ("kg1", v.kg1), ("kp", v.kp), ("kvb", v.kvb)]);
                }
            }
            if let Some(g) = &t.grid {
                values.extend([
                    ("grid.perveance", g.perveance),
                    ("grid.smooth_v", g.smooth_v),
                ]);
                finite(&format!("{name}.grid.contact_v"), g.contact_v)?;
            }
            for (what, c) in [("c_gk", t.c_gk), ("c_gp", t.c_gp), ("c_pk", t.c_pk)] {
                if !(c.is_finite() && c >= 0.0) {
                    return err(format!("{name}.{what} = {c} must be >= 0"));
                }
            }
        }
        DeviceModel::Pentode(p) => {
            let k = &p.model;
            values.extend([("mu", k.mu), ("ex", k.ex), ("kg1", k.kg1), ("kg2", k.kg2)]);
            values.extend([("kp", k.kp), ("kvb", k.kvb)]);
            if let Some(g) = &p.grid {
                values.extend([
                    ("grid.perveance", g.perveance),
                    ("grid.smooth_v", g.smooth_v),
                ]);
                finite(&format!("{name}.grid.contact_v"), g.contact_v)?;
            }
            for (what, c) in [("c_g1k", p.c_g1k), ("c_g1p", p.c_g1p), ("c_pk", p.c_pk)] {
                if !(c.is_finite() && c >= 0.0) {
                    return err(format!("{name}.{what} = {c} must be >= 0"));
                }
            }
        }
        DeviceModel::JunctionDiode(d) => {
            values.extend([("is_a", d.is_a), ("n", d.n)]);
            if let Some(k) = d.tol_scale {
                values.push(("tol_scale", k));
            }
            if !(d.rs_ohm.is_finite() && d.rs_ohm >= 0.0) {
                return err(format!("{name}.rs_ohm = {} must be >= 0", d.rs_ohm));
            }
        }
        DeviceModel::VacuumDiode(d) => {
            values.extend([("perveance", d.perveance), ("smooth_v", d.smooth_v)]);
        }
        DeviceModel::Lamp(l) => {
            values.extend([
                ("wire_d_m", l.wire_d_m),
                ("wire_l_m", l.wire_l_m),
                ("rad_fraction", l.rad_fraction),
                ("t_amb_k", l.t_amb_k),
            ]);
            for c in l.emissivity {
                finite(&format!("{name}.emissivity[]"), c)?;
            }
        }
        DeviceModel::Contact(c) => {
            values.extend([("r_on_ohm", c.r_on_ohm), ("r_off_ohm", c.r_off_ohm)]);
            finite(&format!("{name}.v_open_v"), c.v_open_v)?;
            finite(&format!("{name}.v_closed_v"), c.v_closed_v)?;
            if c.v_closed_v == c.v_open_v {
                return err(format!("{name}: v_closed_v must differ from v_open_v"));
            }
        }
        DeviceModel::Photocell(p) => {
            values.extend([
                ("gen_s_per_s_lux", p.gen_s_per_s_lux),
                ("tau0_s", p.tau0_s),
                ("kappa_s_s", p.kappa_s_s),
                ("g_dark_s", p.g_dark_s),
                ("lambda_m", p.lambda_m),
                ("t_amb_k", p.t_amb_k),
                ("s_unit_s", p.s_unit_s),
            ]);
            if !(p.lux.is_finite() && p.lux >= 0.0) {
                return err(format!("{name}.lux = {} must be >= 0", p.lux));
            }
        }
        DeviceModel::Optocoupler(o) => {
            values.extend([
                ("led_is_a", o.led_is_a),
                ("led_n", o.led_n),
                ("i_eta_a", o.i_eta_a),
                ("gen_s_per_s_a", o.gen_s_per_s_a),
                ("tau0_s", o.tau0_s),
                ("kappa_s_s", o.kappa_s_s),
                ("g_dark_s", o.g_dark_s),
                ("s_unit_s", o.s_unit_s),
            ]);
        }
        DeviceModel::Bjt(q) => {
            values.extend([
                ("is_a", q.is_a),
                ("bf", q.bf),
                ("br", q.br),
                ("nf", q.nf),
                ("nr", q.nr),
                ("ne", q.ne),
                ("nc", q.nc),
            ]);
            for (what, x) in [
                ("vaf_v", q.vaf_v),
                ("var_v", q.var_v),
                ("ikf_a", q.ikf_a),
                ("ikr_a", q.ikr_a),
            ] {
                if let Some(x) = x {
                    values.push((what, x));
                }
            }
            for (what, x) in [
                ("ise_a", q.ise_a),
                ("isc_a", q.isc_a),
                ("rb_ohm", q.rb_ohm),
                ("rc_ohm", q.rc_ohm),
                ("re_ohm", q.re_ohm),
                ("cje_f", q.cje_f),
                ("cjc_f", q.cjc_f),
            ] {
                if !(x.is_finite() && x >= 0.0) {
                    return err(format!("{name}.{what} = {x} must be >= 0"));
                }
            }
            for (what, x) in [
                ("temp_k", q.temp_k),
                ("eg_ev", q.eg_ev),
                ("tol_scale", q.tol_scale),
            ] {
                if let Some(x) = x {
                    values.push((what, x));
                }
            }
            for (what, x) in [("xti", q.xti), ("xtb", q.xtb)] {
                if let Some(x) = x
                    && !x.is_finite()
                {
                    return err(format!("{name}.{what} = {x} must be finite"));
                }
            }
        }
        DeviceModel::Jfet(j) => {
            values.extend([
                ("beta_a_per_v2", j.beta_a_per_v2),
                ("is_a", j.is_a),
                ("n", j.n),
                ("b", j.b),
                ("pb_v", j.pb_v),
            ]);
            if !j.vto_v.is_finite() {
                return err(format!("{name}.vto_v = {} must be finite", j.vto_v));
            }
            if j.pb_v <= j.vto_v {
                return err(format!("{name}: pb_v must exceed vto_v"));
            }
            for (what, x) in [
                ("lambda_per_v", j.lambda_per_v),
                ("rd_ohm", j.rd_ohm),
                ("rs_ohm", j.rs_ohm),
                ("cgs_f", j.cgs_f),
                ("cgd_f", j.cgd_f),
            ] {
                if !(x.is_finite() && x >= 0.0) {
                    return err(format!("{name}.{what} = {x} must be >= 0"));
                }
            }
        }
        DeviceModel::Thyratron(t) => {
            values.extend([
                ("mu_a", t.mu_a),
                ("e_v", t.e_v),
                ("perveance", t.perveance),
                ("x_n", t.x_n),
                ("v_x_v", t.v_x_v),
                ("k_ion", t.k_ion),
                ("w_ion_v", t.w_ion_v),
                ("c_meta", t.c_meta),
                ("w_meta_v", t.w_meta_v),
                ("tau_diff_s", t.tau_diff_s),
                ("k_grid", t.k_grid),
                ("p_grid", t.p_grid),
                ("t_e_v", t.t_e_v),
                ("q_s_c", t.q_s_c),
                ("s0_per_s", t.s0_per_s),
            ]);
            if let Some(mu) = t.mu_g2 {
                values.push(("mu_g2", mu));
            }
            for (what, x) in [
                ("v0_v", t.v0_v),
                ("v_ion_v", t.v_ion_v),
                ("v_meta_v", t.v_meta_v),
                ("v_float_v", t.v_float_v),
            ] {
                finite(&format!("{name}.{what}"), x)?;
            }
            for (what, c) in [
                ("g_leak_s", t.g_leak_s),
                ("c_gk", t.c_gk),
                ("c_ga", t.c_ga),
                ("c_ak", t.c_ak),
            ] {
                if !(c.is_finite() && c >= 0.0) {
                    return err(format!("{name}.{what} = {c} must be >= 0"));
                }
            }
        }
        DeviceModel::MagneticCore(m) => {
            values.extend([
                ("ms_a_per_m", m.ms_a_per_m),
                ("a_a_per_m", m.a_a_per_m),
                ("k_a_per_m", m.k_a_per_m),
                ("path_m", m.path_m),
            ]);
            if !(0.0..1.0).contains(&m.c) {
                return err(format!("{name}: c = {} must be in [0, 1)", m.c));
            }
            if !(m.alpha.is_finite() && m.alpha >= 0.0) {
                return err(format!("{name}: alpha = {} must be >= 0", m.alpha));
            } else if m.alpha * m.c * m.ms_a_per_m / (3.0 * m.a_a_per_m) >= 1.0 {
                return err(format!(
                    "{name}: alpha c Ms / (3 a) must be < 1 (else dM/dH diverges at the origin)"
                ));
            }
        }
    }
    for (what, x) in values {
        positive(&format!("{name}.{what}"), x)?;
    }
    Ok(())
}
