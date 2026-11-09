//! The parts library: macro parts that expand into IR elements (the port of
//! `varimu/circuit/parts.py`, whose docstrings are the reference; the order of
//! floating-point operations follows Python's so the IR agrees bit for bit).

use circuitsim::devices::core::{MU0, MagneticCore as CoreDevice};
use circuitsim::devices::diode::VT_TNOM;
use circuitsim::ir::{
    Capacitor, Coupling, Device, DeviceModel, Element, GROUND, Inductor, JunctionDiode,
    MagneticCore, PlateModel, Resistor, SineSource, TESLA_PER_V, Vccs, VoltageSource, Winding,
};

use crate::Error;
use crate::devices::Material;

/// Stands in for the zero end of a pot (and a 0 dB pad's through path).
pub const MIN_R_OHM: f64 = 1e-3;

fn s(x: &str) -> String {
    x.to_string()
}

/// A resistor, never below MIN_R_OHM.
pub fn resistor(name: &str, a: &str, b: &str, ohms: f64) -> Element {
    // Python's max(ohms, MIN_R_OHM): the first unless the second is larger.
    let r = if MIN_R_OHM > ohms { MIN_R_OHM } else { ohms };
    Element::Resistor(Resistor {
        name: s(name),
        a: s(a),
        b: s(b),
        r_ohm: r,
    })
}

/// The fraction of a track at rotation `pos`: linear, or an audio taper through
/// (0.5, mid).
pub fn taper(pos: f64, mid: Option<f64>) -> Result<f64, Error> {
    let Some(mid) = mid else { return Ok(pos) };
    if !(0.0 < mid && mid < 0.5) {
        return Err(Error(format!("taper mid {mid} must be in (0, 0.5)")));
    }
    let a = ((1.0 - mid) / mid).powf(2.0);
    Ok((a.powf(pos) - 1.0) / (a - 1.0))
}

#[allow(clippy::too_many_arguments)]
pub fn pot(
    name: &str,
    end_a: &str,
    wiper: &str,
    end_b: &str,
    total: f64,
    pos: f64,
    taper_mid: Option<f64>,
    reverse: bool,
) -> Result<Vec<Element>, Error> {
    // reverse: a reverse-taper (C) pot, the taper read from end_b (parts.py's pot).
    let f = if reverse {
        1.0 - taper(1.0 - pos, taper_mid)?
    } else {
        taper(pos, taper_mid)?
    };
    Ok(vec![
        resistor(&format!("{name}a"), end_a, wiper, f * total),
        resistor(&format!("{name}b"), wiper, end_b, (1.0 - f) * total),
    ])
}

pub fn rheostat(
    name: &str,
    a: &str,
    b: &str,
    total: f64,
    pos: f64,
    taper_mid: Option<f64>,
    reverse: bool,
) -> Result<Element, Error> {
    let at = if reverse { 1.0 - pos } else { pos };
    Ok(resistor(name, a, b, taper(at, taper_mid)? * total))
}

#[allow(clippy::too_many_arguments)]
pub fn tapped_pot(
    name: &str,
    end_a: &str,
    tap: &str,
    wiper: &str,
    end_b: &str,
    total: f64,
    pos: f64,
    tap_pos: f64,
) -> Vec<Element> {
    let stops = if pos >= tap_pos {
        [(end_a, 0.0), (tap, tap_pos), (wiper, pos), (end_b, 1.0)]
    } else {
        [(end_a, 0.0), (wiper, pos), (tap, tap_pos), (end_b, 1.0)]
    };
    ["a", "b", "c"]
        .iter()
        .zip(stops.windows(2))
        .map(|(suffix, w)| {
            let ((a, xa), (b, xb)) = (w[0], w[1]);
            resistor(&format!("{name}{suffix}"), a, b, (xb - xa) * total)
        })
        .collect()
}

pub fn t_pad(name: &str, a: &str, b: &str, common: &str, z: f64, atten_db: f64) -> Vec<Element> {
    if atten_db <= 0.0 {
        return vec![resistor(&format!("R{name}s"), a, b, 0.0)];
    }
    let k = 10f64.powf(atten_db / 20.0);
    let r1 = z * (k - 1.0) / (k + 1.0);
    let r2 = 2.0 * z * k / (k * k - 1.0);
    let m = format!("{name}_m");
    vec![
        resistor(&format!("R{name}1"), a, &m, r1),
        resistor(&format!("R{name}2"), &m, b, r1),
        resistor(&format!("R{name}3"), &m, common, r2),
    ]
}

// --- Transformers ---------------------------------------------------------------------

/// One winding: dotted end to the other, turns relative to the reference winding, DC
/// resistance, self-capacitance (0 = none), its own series leakage inductance (None: its
/// share of the transformer's total).
#[derive(Debug, Clone)]
pub struct WindingSpec {
    pub label: String,
    pub dot: String,
    pub other: String,
    pub ratio: f64,
    pub r_ohm: f64,
    pub c_f: f64,
    pub leak_h: Option<f64>,
}

#[derive(Debug, Clone)]
pub struct CoreSpec {
    pub material: String,
    pub area_m2: f64,
    pub path_m: f64,
    pub gap_m: f64,
}

/// The Jiles-Atherton core of transformer `name` (model CORE_<NAME>).
pub fn transformer_core(name: &str, core: &CoreSpec, mat: &Material) -> MagneticCore {
    MagneticCore {
        name: format!("CORE_{}", name.to_uppercase()),
        ms_a_per_m: mat.ms_a_per_m,
        a_a_per_m: mat.a_a_per_m,
        k_a_per_m: mat.k_a_per_m,
        c: mat.c,
        alpha: mat.alpha,
        path_m: core.path_m,
    }
}

/// Transformer `name`: windings on one core; the elements and its core model. A
/// winding's leakage is its own `leak_h`, else half of `leakage_h` (referred to the
/// reference winding) times its ratio squared; `couplings` (label_a, label_b, k) couple
/// two windings' leakage inductors (as Python's `parts.transformer`).
#[allow(clippy::too_many_arguments)]
pub fn transformer(
    name: &str,
    windings: &[WindingSpec],
    core: &CoreSpec,
    mat: &Material,
    turns: f64,
    leakage_h: Option<f64>,
    interwinding: Option<((String, String), String)>,
    c_interwinding_f: f64,
    couplings: &[(String, String, f64)],
    linear: bool,
) -> Result<(Vec<Element>, MagneticCore), Error> {
    let upper = name.to_uppercase();
    let u = format!("{}_core", name.to_lowercase());
    let mut els = Vec::new();
    for w in windings {
        let n = format!("{upper}_{}", w.label);
        let mut top = w.dot.clone();
        if w.r_ohm > 0.0 {
            let r_node = format!("{n}_r");
            els.push(resistor(&format!("R{n}"), &top, &r_node, w.r_ohm));
            top = r_node;
        }
        let leak = match (w.leak_h, leakage_h) {
            (Some(l), _) => l,
            (None, Some(total)) => 0.5 * total * w.ratio * w.ratio,
            (None, None) => {
                return Err(Error(format!(
                    "{name}: winding {} has no leakage (leak, or the leakage_h total)",
                    w.label
                )));
            }
        };
        if leak > 0.0 {
            let l_node = format!("{n}_l");
            els.push(Element::Inductor(Inductor {
                name: format!("L{n}_lk"),
                a: top,
                b: l_node.clone(),
                l_h: leak,
            }));
            top = l_node;
        }
        els.push(Element::Winding(Winding {
            name: format!("L{n}"),
            a: top,
            b: w.other.clone(),
            core: u.clone(),
            turns: w.ratio * turns,
            area_m2: core.area_m2,
        }));
        if w.c_f > 0.0 {
            els.push(capacitor(&format!("C{n}"), &w.dot, &w.other, w.c_f));
        }
    }
    for (a, b, k) in couplings {
        let (la, lb) = (format!("L{upper}_{a}_lk"), format!("L{upper}_{b}_lk"));
        for (lbl, ind) in [(a, &la), (b, &lb)] {
            let has = els
                .iter()
                .any(|e| matches!(e, Element::Inductor(i) if i.name == *ind));
            if !has {
                return Err(Error(format!(
                    "{name}: leak_couplings: winding {lbl} has no leakage inductor"
                )));
            }
        }
        els.push(Element::Coupling(Coupling {
            name: format!("K{upper}_{a}_{b}"),
            l_a: la,
            l_b: lb,
            k: *k,
        }));
    }
    if let Some(((end_a, end_b), other)) = interwinding
        && c_interwinding_f > 0.0
    {
        let half = 0.5 * c_interwinding_f;
        els.push(capacitor(&format!("C{upper}_iwa"), &end_a, &other, half));
        els.push(capacitor(&format!("C{upper}_iwb"), &end_b, &other, half));
    }
    let model = transformer_core(name, core, mat);
    if linear {
        let g = CoreDevice::new(&model).linear_conductance();
        els.push(Element::Resistor(Resistor {
            name: format!("R{upper}_core"),
            a: u.clone(),
            b: s(GROUND),
            r_ohm: 1.0 / g,
        }));
    } else {
        els.push(Element::Device(Device {
            name: format!("X{upper}_CORE"),
            model: model.name.clone(),
            nodes: vec![u.clone(), s(GROUND)],
        }));
    }
    if core.gap_m > 0.0 {
        els.push(Element::Resistor(Resistor {
            name: format!("R{upper}_gap"),
            a: u.clone(),
            b: s(GROUND),
            r_ohm: MU0 / (core.gap_m * TESLA_PER_V),
        }));
    }
    let (Some(lam), Some(rho)) = (mat.lamination_m, mat.resistivity_ohm_m) else {
        return Err(Error(format!(
            "{name}: core material {} needs lamination_m and resistivity_ohm_m",
            core.material
        )));
    };
    let eddy = core.path_m * lam.powf(2.0) / (12.0 * rho) * TESLA_PER_V;
    els.push(capacitor(&format!("C{upper}_eddy"), &u, GROUND, eddy));
    Ok((els, model))
}

/// The op-amp macro model's input stage transconductance (sets only its impedances).
pub const OPAMP_GM_S: f64 = 1e-3;

/// Op-amp `name` as a single-pole macro model (Python's `parts.opamp`, whose docstring
/// is the reference): `clamp` is the clamp diodes' model name with its `swing_v`.
#[allow(clippy::too_many_arguments)]
pub fn opamp(
    name: &str,
    plus: &str,
    minus: &str,
    out: &str,
    a0: f64,
    gbw_hz: f64,
    r_out_ohm: f64,
    r_in_ohm: f64,
    clamp: Option<(&str, f64)>,
) -> Vec<Element> {
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let n1 = format!("{n}_1");
    let vccs = |nm: String, pos: &str, neg: &str, cp: &str, cn: &str, gm_s: f64| {
        Element::Vccs(Vccs {
            name: nm,
            pos: s(pos),
            neg: s(neg),
            ctrl_pos: s(cp),
            ctrl_neg: s(cn),
            gm_s,
        })
    };
    let mut els = vec![
        resistor(&format!("R{upper}_i"), plus, minus, r_in_ohm),
        vccs(format!("G{upper}_1"), GROUND, &n1, plus, minus, OPAMP_GM_S),
        resistor(&format!("R{upper}_1"), &n1, GROUND, a0 / OPAMP_GM_S),
        capacitor(
            &format!("C{upper}_1"),
            &n1,
            GROUND,
            OPAMP_GM_S / (2.0 * std::f64::consts::PI * gbw_hz),
        ),
    ];
    if let Some((model, swing_v)) = clamp {
        let (rp, rn) = (format!("{n}_p"), format!("{n}_n"));
        els.push(Element::VoltageSource(VoltageSource {
            name: format!("V{upper}_p"),
            pos: rp.clone(),
            neg: s(GROUND),
            dc_v: swing_v,
        }));
        els.push(Element::Device(Device {
            name: format!("D{upper}_p"),
            model: s(model),
            nodes: vec![n1.clone(), rp],
        }));
        els.push(Element::VoltageSource(VoltageSource {
            name: format!("V{upper}_n"),
            pos: rn.clone(),
            neg: s(GROUND),
            dc_v: -swing_v,
        }));
        els.push(Element::Device(Device {
            name: format!("D{upper}_n"),
            model: s(model),
            nodes: vec![rn, n1.clone()],
        }));
    }
    els.push(vccs(
        format!("G{upper}_o"),
        GROUND,
        out,
        &n1,
        GROUND,
        1.0 / r_out_ohm,
    ));
    els.push(resistor(&format!("R{upper}_o"), out, GROUND, r_out_ohm));
    els
}

pub fn capacitor(name: &str, a: &str, b: &str, c_f: f64) -> Element {
    Element::Capacitor(Capacitor {
        name: s(name),
        a: s(a),
        b: s(b),
        c_f,
        v0_v: None,
    })
}

/// JFET `name` (parts.py's `jfet`): the device on its internal nodes, the model's series
/// resistances from the terminals to them (where nonzero) and its gate capacitances.
pub fn jfet(name: &str, d: &str, g: &str, src: &str, model: &circuitsim::ir::Jfet) -> Vec<Element> {
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let inner = |r: f64, tag: &str, outer: &str| {
        if r > 0.0 {
            format!("{n}_{tag}")
        } else {
            s(outer)
        }
    };
    let di = inner(model.rd_ohm, "d", d);
    let si = inner(model.rs_ohm, "s", src);
    let mut els = vec![Element::Device(Device {
        name: s(name),
        model: model.name.clone(),
        nodes: vec![di.clone(), s(g), si.clone()],
    })];
    for (tag, outer, inner, r) in [("d", d, &di, model.rd_ohm), ("s", src, &si, model.rs_ohm)] {
        if r > 0.0 {
            els.push(Element::Resistor(Resistor {
                name: format!("R{upper}_{tag}"),
                a: s(outer),
                b: inner.clone(),
                r_ohm: r,
            }));
        }
    }
    if model.cgs_f > 0.0 {
        els.push(capacitor(&format!("C{upper}_gs"), g, &si, model.cgs_f));
    }
    if model.cgd_f > 0.0 {
        els.push(capacitor(&format!("C{upper}_gd"), g, &di, model.cgd_f));
    }
    els
}

/// Transistor `name` (parts.py's `bjt`): the device on its internal nodes, the model's
/// series resistances from the terminals to them (where nonzero) and its junction
/// capacitances between them.
pub fn bjt(name: &str, c: &str, b: &str, e: &str, model: &circuitsim::ir::Bjt) -> Vec<Element> {
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let inner = |r: f64, tag: &str, outer: &str| {
        if r > 0.0 {
            format!("{n}_{tag}")
        } else {
            s(outer)
        }
    };
    let ci = inner(model.rc_ohm, "c", c);
    let bi = inner(model.rb_ohm, "b", b);
    let ei = inner(model.re_ohm, "e", e);
    let mut els = vec![Element::Device(Device {
        name: s(name),
        model: model.name.clone(),
        nodes: vec![ci.clone(), bi.clone(), ei.clone()],
    })];
    for (tag, outer, inner, r) in [
        ("b", b, &bi, model.rb_ohm),
        ("c", c, &ci, model.rc_ohm),
        ("e", e, &ei, model.re_ohm),
    ] {
        if r > 0.0 {
            els.push(Element::Resistor(Resistor {
                name: format!("R{upper}_{tag}"),
                a: s(outer),
                b: inner.clone(),
                r_ohm: r,
            }));
        }
    }
    if model.cje_f > 0.0 {
        els.push(capacitor(&format!("C{upper}_je"), &bi, &ei, model.cje_f));
    }
    if model.cjc_f > 0.0 {
        els.push(capacitor(&format!("C{upper}_jc"), &bi, &ci, model.cjc_f));
    }
    els
}

// --- Rectifiers, references, sources ------------------------------------------------

pub fn bridge(
    name: &str,
    [ac_a, ac_b, plus, minus]: [&str; 4],
    model: &DeviceModel,
    arm_c_f: f64,
) -> Vec<Element> {
    let arms = [
        ("A", ac_a, plus),
        ("B", ac_b, plus),
        ("C", minus, ac_a),
        ("D", minus, ac_b),
    ];
    let prefix = if matches!(model, DeviceModel::JunctionDiode(_)) {
        "D"
    } else {
        "X"
    };
    let mut els: Vec<Element> = arms
        .iter()
        .map(|(sfx, a, k)| {
            Element::Device(Device {
                name: format!("{prefix}{name}{sfx}"),
                model: model.name().to_string(),
                nodes: vec![s(a), s(k)],
            })
        })
        .collect();
    if arm_c_f > 0.0 {
        els.extend(
            arms.iter()
                .map(|(sfx, a, k)| capacitor(&format!("C{name}{sfx}"), a, k, arm_c_f)),
        );
    }
    els
}

/// The fixed voltage in series with a glow tube's diode model: `operating_v` at
/// `ref_current_a`.
pub fn burning_voltage(model: &JunctionDiode, operating_v: f64, ref_current_a: f64) -> f64 {
    let drop =
        model.n * VT_TNOM * (ref_current_a / model.is_a).ln_1p() + ref_current_a * model.rs_ohm;
    operating_v - drop
}

pub fn vr_tube(
    name: &str,
    [anode, mid, cathode]: [&str; 3],
    model: &JunctionDiode,
    operating_v: f64,
    ref_current_a: f64,
) -> Vec<Element> {
    vec![
        Element::Device(Device {
            name: format!("D{name}"),
            model: model.name.clone(),
            nodes: vec![s(anode), s(mid)],
        }),
        Element::VoltageSource(VoltageSource {
            name: s(name),
            pos: s(mid),
            neg: s(cathode),
            dc_v: burning_voltage(model, operating_v, ref_current_a),
        }),
    ]
}

/// A winding fed from the mains: `v_rms` at the rated mains, scaled with the actual.
#[allow(clippy::too_many_arguments)]
pub fn mains_sine(
    name: &str,
    pos: &str,
    neg: &str,
    v_rms: f64,
    mains_v_rms: f64,
    rated_mains_v_rms: f64,
    mains_hz: f64,
    phase_deg: f64,
) -> Element {
    let scale = mains_v_rms / rated_mains_v_rms;
    Element::SineSource(SineSource {
        name: s(name),
        pos: s(pos),
        neg: s(neg),
        offset_v: 0.0,
        amplitude_v: 2f64.sqrt() * v_rms * scale,
        freq_hz: mains_hz,
        phase_deg,
    })
}

// --- Device instances ----------------------------------------------------------------

/// The spreads and counts of one device instance (`device_instance` in Python).
#[derive(Debug, Clone, Copy)]
pub struct Instance {
    pub n_parallel: i64,
    pub emission_scale: f64,
    pub mu_spread: f64,
    pub grid_contact_v: Option<f64>,
    pub area: f64,
    /// A BJT's junction temperature (parts.py's `temp_c`; None: TNOM).
    pub temp_c: Option<f64>,
}

pub fn device_instance(
    base: &DeviceModel,
    name: &str,
    inst: Instance,
) -> Result<DeviceModel, Error> {
    let n = inst.n_parallel as f64;
    if inst.temp_c.is_some() && !matches!(base, DeviceModel::Bjt(_)) {
        return Err(Error(format!("{name}: temp_c is for BJTs")));
    }
    match base {
        DeviceModel::Triode(t) => {
            let k = n * inst.emission_scale;
            let plate = match &t.plate {
                PlateModel::VariMu(p) => {
                    let mut p = p.clone();
                    p.mus = p.mus.iter().map(|m| m * inst.mu_spread).collect();
                    p.kg1 /= k;
                    PlateModel::VariMu(p)
                }
                PlateModel::Koren(p) => {
                    let mut p = p.clone();
                    p.mu *= inst.mu_spread;
                    p.kg1 /= k;
                    PlateModel::Koren(p)
                }
            };
            let grid = t.grid.as_ref().map(|g| circuitsim::ir::GridCurrent {
                perveance: g.perveance * n,
                contact_v: inst.grid_contact_v.unwrap_or(g.contact_v),
                smooth_v: g.smooth_v,
            });
            Ok(DeviceModel::Triode(circuitsim::ir::Triode {
                name: s(name),
                plate,
                grid,
                c_gk: t.c_gk * n,
                c_gp: t.c_gp * n,
                c_pk: t.c_pk * n,
            }))
        }
        _ if inst.grid_contact_v.is_some() => {
            Err(Error(format!("{name}: grid_contact_v is for triodes")))
        }
        DeviceModel::Pentode(p) => {
            let k = n * inst.emission_scale;
            let mut model = p.model.clone();
            model.mu *= inst.mu_spread;
            model.kg1 /= k;
            model.kg2 /= k;
            let grid = p.grid.as_ref().map(|g| {
                let mut g = g.clone();
                g.perveance *= n;
                g
            });
            Ok(DeviceModel::Pentode(circuitsim::ir::Pentode {
                name: s(name),
                model,
                grid,
                c_g1k: p.c_g1k * n,
                c_g1p: p.c_g1p * n,
                c_pk: p.c_pk * n,
            }))
        }
        _ if inst.mu_spread != 1.0 => Err(Error(format!(
            "{name}: mu_spread is for triodes and pentodes"
        ))),
        DeviceModel::VacuumDiode(d) => {
            let mut d = d.clone();
            d.name = s(name);
            d.perveance = d.perveance * n * inst.emission_scale;
            Ok(DeviceModel::VacuumDiode(d))
        }
        DeviceModel::JunctionDiode(d) => {
            if inst.emission_scale != 1.0 {
                return Err(Error(format!(
                    "{name}: a junction diode has no emission spread"
                )));
            }
            let k = n * inst.area;
            let mut d = d.clone();
            d.name = s(name);
            d.is_a *= k;
            d.rs_ohm /= k;
            Ok(DeviceModel::JunctionDiode(d))
        }
        DeviceModel::Bjt(q) => {
            if inst.emission_scale != 1.0 {
                return Err(Error(format!("{name}: a BJT has no emission spread")));
            }
            let k = n * inst.area;
            let mut q = q.clone();
            q.name = s(name);
            q.is_a *= k;
            q.ikf_a = q.ikf_a.map(|x| x * k);
            q.ikr_a = q.ikr_a.map(|x| x * k);
            q.ise_a *= k;
            q.isc_a *= k;
            q.rb_ohm /= k;
            q.rc_ohm /= k;
            q.re_ohm /= k;
            q.cje_f *= k;
            q.cjc_f *= k;
            q.temp_k = inst.temp_c.map(|t| t + 273.15);
            Ok(DeviceModel::Bjt(q))
        }
        DeviceModel::Jfet(j) => {
            if inst.emission_scale != 1.0 {
                return Err(Error(format!("{name}: a JFET has no emission spread")));
            }
            let k = n * inst.area;
            let mut j = j.clone();
            j.name = s(name);
            j.beta_a_per_v2 *= k;
            j.is_a *= k;
            j.rd_ohm /= k;
            j.rs_ohm /= k;
            j.cgs_f *= k;
            j.cgd_f *= k;
            Ok(DeviceModel::Jfet(j))
        }
        DeviceModel::Lamp(l) => {
            if n != 1.0 || inst.emission_scale != 1.0 || inst.area != 1.0 {
                return Err(Error(format!(
                    "{name}: a lamp takes no parallel, emission or area"
                )));
            }
            let mut l = l.clone();
            l.name = s(name);
            Ok(DeviceModel::Lamp(l))
        }
        DeviceModel::Contact(c) => {
            if n != 1.0 || inst.emission_scale != 1.0 || inst.area != 1.0 {
                return Err(Error(format!(
                    "{name}: a contact takes no parallel, emission or area"
                )));
            }
            let mut c = c.clone();
            c.name = s(name);
            Ok(DeviceModel::Contact(c))
        }
        DeviceModel::Photocell(p) => {
            if n != 1.0 || inst.emission_scale != 1.0 || inst.area != 1.0 {
                return Err(Error(format!(
                    "{name}: a photocell takes no parallel, emission or area"
                )));
            }
            let mut p = p.clone();
            p.name = s(name);
            Ok(DeviceModel::Photocell(p))
        }
        DeviceModel::Optocoupler(o) => {
            if n != 1.0 || inst.emission_scale != 1.0 || inst.area != 1.0 {
                return Err(Error(format!(
                    "{name}: an optocoupler takes no parallel, emission or area"
                )));
            }
            let mut o = o.clone();
            o.name = s(name);
            Ok(DeviceModel::Optocoupler(o))
        }
        DeviceModel::Thyratron(t) => {
            if n != 1.0 || inst.emission_scale != 1.0 || inst.area != 1.0 {
                return Err(Error(format!(
                    "{name}: a thyratron takes no parallel, emission or area"
                )));
            }
            let mut t = t.clone();
            t.name = s(name);
            Ok(DeviceModel::Thyratron(t))
        }
        DeviceModel::MagneticCore(_) => Err(Error(format!("{name}: no instances of MagneticCore"))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tapped_pot_orders_its_stops() {
        let els = tapped_pot("R1", "0", "t", "w", "top", 100.0, 0.25, 0.5);
        let names: Vec<_> = els.iter().map(|e| e.name().to_string()).collect();
        assert_eq!(names, ["R1a", "R1b", "R1c"]);
        assert_eq!(els[0].nodes(), ["0", "w"]);
        assert_eq!(els[1].nodes(), ["w", "t"]);
    }

    #[test]
    fn zero_db_pad_is_one_minimal_resistor() {
        let els = t_pad("AT1", "a", "b", "0", 600.0, 0.0);
        let Element::Resistor(r) = &els[0] else {
            panic!()
        };
        assert_eq!((r.name.as_str(), r.r_ohm), ("RAT1s", MIN_R_OHM));
    }
}
