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
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Control {
    pub name: String,
    pub node: String,
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
}

/// Shockley diode with series resistance (SPICE `D`): pins (anode, cathode).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct JunctionDiode {
    pub name: String,
    pub is_a: f64,
    pub n: f64,
    pub rs_ohm: f64,
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

impl DeviceModel {
    pub fn name(&self) -> &str {
        match self {
            DeviceModel::Triode(m) => &m.name,
            DeviceModel::Pentode(m) => &m.name,
            DeviceModel::JunctionDiode(m) => &m.name,
            DeviceModel::VacuumDiode(m) => &m.name,
            DeviceModel::MagneticCore(m) => &m.name,
        }
    }

    /// Pin names, in the order of [`Device::nodes`].
    pub fn pins(&self) -> &'static [&'static str] {
        match self {
            DeviceModel::Triode(_) => &["p", "g", "k"],
            DeviceModel::Pentode(_) => &["p", "g2", "g1", "k"],
            DeviceModel::JunctionDiode(_) | DeviceModel::VacuumDiode(_) => &["a", "k"],
            DeviceModel::MagneticCore(_) => &["b", "ref"],
        }
    }

    /// SPICE letter of an instance: `D` for the built-in diode, `X` for subcircuits.
    pub fn instance_prefix(&self) -> char {
        match self {
            DeviceModel::JunctionDiode(_) => 'D',
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

        let mut names = HashSet::new();
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
            if !(d.rs_ohm.is_finite() && d.rs_ohm >= 0.0) {
                return err(format!("{name}.rs_ohm = {} must be >= 0", d.rs_ohm));
            }
        }
        DeviceModel::VacuumDiode(d) => {
            values.extend([("perveance", d.perveance), ("smooth_v", d.smooth_v)]);
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
