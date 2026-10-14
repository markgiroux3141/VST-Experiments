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

use std::collections::{HashMap, HashSet};
use std::fmt;

use serde::{Deserialize, Serialize};

/// JSON schema version. Bump it (in Python too) on any incompatible change.
pub const IR_VERSION: u32 = 1;

/// The ground node.
pub const GROUND: &str = "0";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitIr {
    pub version: u32,
    pub title: String,
    /// Driven by the audio input, relative to ground.
    pub input_node: String,
    pub probes: Vec<Probe>,
    pub models: Vec<DeviceModel>,
    pub sections: Vec<Section>,
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
    Device(Device),
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

impl DeviceModel {
    pub fn name(&self) -> &str {
        match self {
            DeviceModel::Triode(m) => &m.name,
            DeviceModel::Pentode(m) => &m.name,
            DeviceModel::JunctionDiode(m) => &m.name,
            DeviceModel::VacuumDiode(m) => &m.name,
        }
    }

    /// Pin names, in the order of [`Device::nodes`].
    pub fn pins(&self) -> &'static [&'static str] {
        match self {
            DeviceModel::Triode(_) => &["p", "g", "k"],
            DeviceModel::Pentode(_) => &["p", "g2", "g1", "k"],
            DeviceModel::JunctionDiode(_) | DeviceModel::VacuumDiode(_) => &["a", "k"],
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
            Element::Device(e) => &e.name,
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
            Element::Device(e) => e.nodes.iter().map(String::as_str).collect(),
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

        if !nodes.contains(GROUND) {
            return err("no element connects to ground (node \"0\")");
        }
        if !nodes.contains(self.input_node.as_str()) {
            return err(format!("input node {} is not connected", self.input_node));
        }
        for p in &self.probes {
            let Probe::Voltage { node } = p;
            if !nodes.contains(node.as_str()) {
                return err(format!("probe node {node} is not connected"));
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
    }
    for (what, x) in values {
        positive(&format!("{name}.{what}"), x)?;
    }
    Ok(())
}
