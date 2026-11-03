//! Condenser microphone capsules: the port of `varimu/devices/capsule.py` (`Capsule`,
//! `capsule_from_data`) and of the capsule part in `varimu/circuit/parts.py`, in
//! Python's order of floating-point operations so the IR agrees bit for bit
//! (MIC_ROOM_PLAN.md, A2). The component file carries the lumped elements (derived from
//! the geometry at fit time), so nothing here needs more than arithmetic.

use circuitsim::ir::{Capacitor, Element, GROUND, Inductor, Resistor, Vccs};

use crate::Error;
use crate::yaml::{Map, Value};

/// The Thevenin source's resistance (numerical; no noise).
pub const READOUT_OHM: f64 = 1.0;

#[derive(Debug, Clone, PartialEq)]
pub struct Capsule {
    pub name: String,
    pub m_front: f64,
    pub c_diaphragm: f64,
    pub c_gap: f64,
    pub r_holes: f64,
    pub m_holes: f64,
    pub c_cavity: f64,
    pub r_vent: f64,
    pub c0_f: f64,
    pub c_stray_f: f64,
    pub gap_m: f64,
    pub displacement_per_volume: f64,
    pub neg_stiffness_per_v2: f64,
}

impl Capsule {
    /// The diaphragm's compliance at a polarization (`Capsule.c_diaphragm_at`).
    pub fn c_diaphragm_at(&self, e0_v: f64) -> f64 {
        1.0 / (1.0 / self.c_diaphragm - self.neg_stiffness_per_v2 * e0_v * e0_v)
    }

    /// Open-circuit volts per m^3 of volume displacement (`Capsule.volts_per_volume`).
    pub fn volts_per_volume(&self, e0_v: f64) -> f64 {
        e0_v * self.displacement_per_volume / self.gap_m
    }
}

fn num(m: &Map, key: &str, what: &str) -> Result<f64, Error> {
    m.get(key)
        .and_then(Value::as_f64)
        .ok_or_else(|| Error(format!("{what}: lumped needs `{key}`")))
}

/// A capsule version's data (kind capsule), as `capsule_from_data`.
pub fn from_data(data: &Value, what: &str) -> Result<Capsule, Error> {
    let d = data
        .as_map()
        .ok_or_else(|| Error(format!("{what}: not a mapping")))?;
    let kind = d.get("kind").and_then(Value::as_str).unwrap_or("");
    if kind != "capsule" {
        return Err(Error(format!("{what} is not a capsule (kind '{kind}')")));
    }
    let name = d
        .get("name")
        .map(Value::py_str)
        .ok_or_else(|| Error(format!("{what}: needs `name`")))?;
    let lp = d
        .get("lumped")
        .and_then(Value::as_map)
        .ok_or_else(|| Error(format!("{what}: needs `lumped`")))?;
    Ok(Capsule {
        name,
        m_front: num(lp, "m_front", what)?,
        c_diaphragm: num(lp, "c_diaphragm", what)?,
        c_gap: num(lp, "c_gap", what)?,
        r_holes: num(lp, "r_holes", what)?,
        m_holes: num(lp, "m_holes", what)?,
        c_cavity: num(lp, "c_cavity", what)?,
        r_vent: num(lp, "r_vent", what)?,
        c0_f: num(lp, "c0_f", what)?,
        c_stray_f: num(lp, "c_stray_f", what)?,
        gap_m: num(lp, "gap_m", what)?,
        displacement_per_volume: num(lp, "displacement_per_volume", what)?,
        neg_stiffness_per_v2: num(lp, "neg_stiffness_per_v2", what)?,
    })
}

fn r(name: String, a: &str, b: &str, r_ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name,
        a: a.into(),
        b: b.into(),
        r_ohm,
    })
}

fn c(name: String, a: &str, b: &str, c_f: f64) -> Element {
    Element::Capacitor(Capacitor {
        name,
        a: a.into(),
        b: b.into(),
        c_f,
        v0_v: None,
    })
}

fn l(name: String, a: &str, b: &str, l_h: f64) -> Element {
    Element::Inductor(Inductor {
        name,
        a: a.into(),
        b: b.into(),
        l_h,
    })
}

/// The capsule part (`parts.capsule`).
pub fn capsule(
    name: &str,
    front: &str,
    backplate: &str,
    out: &str,
    cap: &Capsule,
    polarization_v: f64,
) -> Vec<Element> {
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let cd = cap.c_diaphragm_at(polarization_v);
    let k = cap.volts_per_volume(polarization_v) * cd;
    let one = format!("{n}_1");
    let gap = format!("{n}_g");
    let holes = format!("{n}_h");
    let cav = format!("{n}_c");
    let e = format!("{n}_e");
    let mut els = vec![
        l(format!("L{upper}_m"), front, &one, cap.m_front),
        c(format!("C{upper}_d"), &one, &gap, cd),
        c(format!("C{upper}_g"), &gap, GROUND, cap.c_gap),
        r(format!("R{upper}_h"), &gap, &holes, cap.r_holes),
        l(format!("L{upper}_h"), &holes, &cav, cap.m_holes),
        c(format!("C{upper}_c"), &cav, GROUND, cap.c_cavity),
        r(format!("R{upper}_v"), &cav, front, cap.r_vent),
        Element::Vccs(Vccs {
            name: format!("G{upper}_x"),
            pos: backplate.into(),
            neg: e.clone(),
            ctrl_pos: one.clone(),
            ctrl_neg: gap.clone(),
            gm_s: k / READOUT_OHM,
        }),
        r(format!("R{upper}_x"), &e, backplate, READOUT_OHM),
        c(format!("C{upper}_0"), &e, out, cap.c0_f),
    ];
    if cap.c_stray_f > 0.0 {
        els.push(c(format!("C{upper}_s"), out, backplate, cap.c_stray_f));
    }
    els
}

/// A dual-diaphragm capsule (`DualCapsule`): per side, the halves equal.
#[derive(Debug, Clone, PartialEq)]
pub struct DualCapsule {
    pub name: String,
    pub m_diaphragm: f64,
    pub c_diaphragm: f64,
    pub c_gap: f64,
    pub r_film: f64,
    pub r_blind: f64,
    pub c_blind: f64,
    pub r_through: f64,
    pub m_through: f64,
    pub r_leak: f64,
    pub c0_f: f64,
    pub c_stray_f: f64,
    pub gap_m: f64,
    pub displacement_per_volume: f64,
    pub neg_stiffness_per_v2: f64,
}

impl DualCapsule {
    pub fn c_diaphragm_at(&self, e0_v: f64) -> f64 {
        1.0 / (1.0 / self.c_diaphragm - self.neg_stiffness_per_v2 * e0_v * e0_v)
    }

    pub fn volts_per_volume(&self, e0_v: f64) -> f64 {
        e0_v * self.displacement_per_volume / self.gap_m
    }
}

/// A dual-diaphragm capsule version's data (kind capsule, form dual).
pub fn dual_from_data(data: &Value, what: &str) -> Result<DualCapsule, Error> {
    let d = data
        .as_map()
        .ok_or_else(|| Error(format!("{what}: not a mapping")))?;
    let kind = d.get("kind").and_then(Value::as_str).unwrap_or("");
    let form = d.get("form").and_then(Value::as_str).unwrap_or("");
    if kind != "capsule" || form != "dual" {
        return Err(Error(format!("{what} is not a dual-diaphragm capsule")));
    }
    let name = d
        .get("name")
        .map(Value::py_str)
        .ok_or_else(|| Error(format!("{what}: needs `name`")))?;
    let lp = d
        .get("lumped")
        .and_then(Value::as_map)
        .ok_or_else(|| Error(format!("{what}: needs `lumped`")))?;
    Ok(DualCapsule {
        name,
        m_diaphragm: num(lp, "m_diaphragm", what)?,
        c_diaphragm: num(lp, "c_diaphragm", what)?,
        c_gap: num(lp, "c_gap", what)?,
        r_film: num(lp, "r_film", what)?,
        r_blind: num(lp, "r_blind", what)?,
        c_blind: num(lp, "c_blind", what)?,
        r_through: num(lp, "r_through", what)?,
        m_through: num(lp, "m_through", what)?,
        r_leak: num(lp, "r_leak", what)?,
        c0_f: num(lp, "c0_f", what)?,
        c_stray_f: num(lp, "c_stray_f", what)?,
        gap_m: num(lp, "gap_m", what)?,
        displacement_per_volume: num(lp, "displacement_per_volume", what)?,
        neg_stiffness_per_v2: num(lp, "neg_stiffness_per_v2", what)?,
    })
}

/// The dual-diaphragm capsule part (`parts.capsule_dual`).
#[allow(clippy::too_many_arguments)]
pub fn capsule_dual(
    name: &str,
    front: &str,
    rear: &str,
    backplate: &str,
    out_front: &str,
    out_rear: &str,
    cap: &DualCapsule,
    polarization_front_v: f64,
    polarization_rear_v: f64,
) -> Vec<Element> {
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let mut els = Vec::new();
    for (s, outside, out, e0) in [
        ("f", front, out_front, polarization_front_v),
        ("r", rear, out_rear, polarization_rear_v),
    ] {
        let cd = cap.c_diaphragm_at(e0);
        let k = cap.volts_per_volume(e0) * cd;
        let one = format!("{n}_{s}1");
        let gap = format!("{n}_{s}g");
        let holes = format!("{n}_{s}h");
        let blind = format!("{n}_{s}b");
        let e = format!("{n}_{s}e");
        els.extend([
            l(format!("L{upper}_m{s}"), outside, &one, cap.m_diaphragm),
            c(format!("C{upper}_d{s}"), &one, &gap, cd),
            c(format!("C{upper}_g{s}"), &gap, GROUND, cap.c_gap),
            r(format!("R{upper}_f{s}"), &gap, &holes, cap.r_film),
            r(format!("R{upper}_b{s}"), &holes, &blind, cap.r_blind),
            c(format!("C{upper}_b{s}"), &blind, GROUND, cap.c_blind),
        ]);
        if e0 == 0.0 {
            // Unpolarized: no source, C0 straight from the backplate.
            els.push(c(format!("C{upper}_0{s}"), backplate, out, cap.c0_f));
        } else {
            els.extend([
                Element::Vccs(Vccs {
                    name: format!("G{upper}_x{s}"),
                    pos: backplate.into(),
                    neg: e.clone(),
                    ctrl_pos: one.clone(),
                    ctrl_neg: gap.clone(),
                    gm_s: k / READOUT_OHM,
                }),
                r(format!("R{upper}_x{s}"), &e, backplate, READOUT_OHM),
                c(format!("C{upper}_0{s}"), &e, out, cap.c0_f),
            ]);
        }
        if cap.c_stray_f > 0.0 {
            els.push(c(format!("C{upper}_s{s}"), out, backplate, cap.c_stray_f));
        }
    }
    let through = format!("{n}_t");
    els.extend([
        r(
            format!("R{upper}_t"),
            &format!("{n}_fh"),
            &through,
            cap.r_through,
        ),
        l(
            format!("L{upper}_t"),
            &through,
            &format!("{n}_rh"),
            cap.m_through,
        ),
        r(format!("R{upper}_l"), &through, GROUND, cap.r_leak),
    ]);
    els
}
