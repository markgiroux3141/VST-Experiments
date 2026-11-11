//! Loudspeakers: the port of `varimu/devices/speaker.py` (the model and its docstring)
//! and of the speaker part in `varimu/circuit/parts.py` (`speaker_driver`,
//! `speaker_readout`), in Python's order of floating-point operations so the IR agrees
//! bit for bit (component editor C3).

use std::f64::consts::PI;

use circuitsim::ir::{
    Capacitor, Device, DeviceModel, Element, GROUND, Gyrator, Inductor, Resistor, Vccs,
};

use crate::Error;
use crate::yaml::{Map, Value};

/// Air at 20 C and 101.325 kPa (speaker.py's sources).
pub const RHO_AIR_KG_M3: f64 = 1.204;
pub const C_AIR_M_S: f64 = 343.2;
/// A baffled piston's directivity 2 J1(x) / x is 1/sqrt(2) at x = 1.616.
pub const PISTON_KA_3DB: f64 = 1.616;
/// The readout's numerical choices (not physics): one section of the delay line, and
/// the readout's impedance level.
pub const LADDER_SECTION_S: f64 = 62.5e-6;
pub const READOUT_OHM: f64 = 1000.0;
/// The fixed gyrator of a field coil's transformer (numerics).
pub const GYRATOR_S: f64 = 1.0;

#[derive(Debug, Clone, PartialEq)]
pub struct Mode {
    pub mass_kg: f64,
    pub f_hz: f64,
    pub q: f64,
    pub area_m2: f64,
}

/// An electromagnet's field winding (speaker.py's `Field`).
#[derive(Debug, Clone, PartialEq)]
pub struct Field {
    pub re_ohm: f64,
    pub l_h: f64,
    pub i_nominal_a: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Speaker {
    pub name: String,
    pub re_ohm: f64,
    pub le_h: f64,
    pub l2_h: f64,
    pub r2_ohm: f64,
    pub mms_kg: f64,
    pub cms_m_per_n: f64,
    pub rms_ns_per_m: f64,
    pub bl_tm: f64,
    pub sd_m2: f64,
    pub modes: Vec<Mode>,
    pub field: Option<Field>,
}

/// The baffle around the driver (speaker.py's `Cabinet`).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Cabinet {
    pub width_m: f64,
    pub height_m: f64,
    pub depth_m: f64,
    pub offset_x_m: f64,
    pub offset_y_m: f64,
}

fn num(m: &Map, key: &str, what: &str) -> Result<f64, Error> {
    m.get(key)
        .and_then(Value::as_f64)
        .ok_or_else(|| Error(format!("{what}: `{key}` must be a number")))
}

fn sub<'a>(m: &'a Map, key: &str, what: &str) -> Result<&'a Map, Error> {
    m.get(key)
        .and_then(Value::as_map)
        .ok_or_else(|| Error(format!("{what}: needs `{key}`")))
}

/// A speaker version's data (kind speaker), as `speaker_from_data`.
pub fn from_data(data: &Value, what: &str) -> Result<Speaker, Error> {
    let d = data
        .as_map()
        .ok_or_else(|| Error(format!("{what}: not a mapping")))?;
    if d.get("kind").and_then(Value::as_str) != Some("speaker") {
        return Err(Error(format!("{what}: not a speaker")));
    }
    let vc = sub(d, "voice_coil", what)?;
    let m = sub(d, "moving_system", what)?;
    let list = sub(d, "modes", what)?
        .get("list")
        .and_then(Value::as_list)
        .ok_or_else(|| Error(format!("{what}: modes needs `list`")))?;
    let modes = list
        .iter()
        .map(|x| {
            let x = x
                .as_map()
                .ok_or_else(|| Error(format!("{what}: a mode is a mapping")))?;
            Ok(Mode {
                mass_kg: num(x, "mass_kg", what)?,
                f_hz: num(x, "f_hz", what)?,
                q: num(x, "q", what)?,
                area_m2: num(x, "area_m2", what)?,
            })
        })
        .collect::<Result<Vec<_>, Error>>()?;
    let field = match d.get("field") {
        None => None,
        Some(v) => {
            let f = v
                .as_map()
                .ok_or_else(|| Error(format!("{what}: field is a mapping")))?;
            Some(Field {
                re_ohm: num(f, "re_ohm", what)?,
                l_h: num(f, "l_h", what)?,
                i_nominal_a: num(f, "i_nominal_a", what)?,
            })
        }
    };
    Ok(Speaker {
        name: d.get("name").map(Value::py_str).unwrap_or_default(),
        re_ohm: num(vc, "re_ohm", what)?,
        le_h: num(vc, "le_h", what)?,
        l2_h: num(vc, "l2_h", what)?,
        r2_ohm: num(vc, "r2_ohm", what)?,
        mms_kg: num(m, "mms_kg", what)?,
        cms_m_per_n: num(m, "cms_m_per_n", what)?,
        rms_ns_per_m: num(m, "rms_ns_per_m", what)?,
        bl_tm: num(m, "bl_tm", what)?,
        sd_m2: num(m, "sd_m2", what)?,
        modes,
        field,
    })
}

/// (delay-line tap, weight) of the back wave around each edge: top, left, bottom, right
/// (speaker.py's `edge_taps`).
pub fn edge_taps(cab: &Cabinet, distance_m: f64) -> Vec<(usize, f64)> {
    let (x0, x1) = (
        -cab.width_m / 2.0 - cab.offset_x_m,
        cab.width_m / 2.0 - cab.offset_x_m,
    );
    let (y0, y1) = (
        -cab.height_m / 2.0 - cab.offset_y_m,
        cab.height_m / 2.0 - cab.offset_y_m,
    );
    let corners = [(x1, y1), (x0, y1), (x0, y0), (x1, y0)];
    let angles: Vec<f64> = corners.iter().map(|&(x, y)| y.atan2(x)).collect();
    let dists = [y1, -x0, -y0, x1];
    let (r, depth) = (distance_m, cab.depth_m);
    (0..4)
        .map(|e| {
            let mut span = angles[(e + 1) % 4] - angles[e];
            if span < 0.0 {
                span += 2.0 * PI;
            }
            let d = dists[e];
            let path = (depth * depth + d * d).sqrt() + depth + (r * r + d * d).sqrt() - r;
            let tap = (path / (C_AIR_M_S * LADDER_SECTION_S) + 0.5).floor() as usize;
            (tap, span / (2.0 * PI) * r / (r + path))
        })
        .collect()
}

/// A closed box's air as a spring on the cone: V / (rho c^2 Sd^2).
pub fn box_compliance_m_per_n(volume_m3: f64, sd_m2: f64) -> f64 {
    volume_m3 / (RHO_AIR_KG_M3 * C_AIR_M_S * C_AIR_M_S * sd_m2 * sd_m2)
}

/// The closed box's baffle step: c / (pi W), W the front's mean side.
pub fn baffle_step_hz(cab: &Cabinet) -> f64 {
    C_AIR_M_S / (PI * (cab.width_m + cab.height_m) / 2.0)
}

/// The gyrator of speaker `name`'s field winding (`parts.speaker_field_model`).
pub fn field_model(name: &str, s: &Speaker) -> Option<DeviceModel> {
    let f = s.field.as_ref()?;
    Some(DeviceModel::Gyrator(Gyrator {
        name: format!("{}_FIELD", name.to_uppercase()),
        g_per_v: GYRATOR_S / (f.re_ohm * f.i_nominal_a),
    }))
}

pub fn directivity_pole_hz(sd_m2: f64) -> f64 {
    let a = (sd_m2 / PI).sqrt();
    PISTON_KA_3DB * C_AIR_M_S / (2.0 * PI * a)
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

fn g(name: String, pos: &str, neg: &str, cp: &str, cn: &str, gm_s: f64) -> Element {
    Element::Vccs(Vccs {
        name,
        pos: pos.into(),
        neg: neg.into(),
        ctrl_pos: cp.into(),
        ctrl_neg: cn.into(),
        gm_s,
    })
}

/// The driver's electrical equivalent, and each radiating node with its area. `series` n:
/// n identical drivers in series, exactly (`parts.speaker_driver`): resistances and
/// inductances times n, capacitances over n (n = 1: bit for bit one driver's). A closed
/// box (`box_m3` > 0) and a field winding (`field`, the caller has checked the
/// component has one and `series` is 1) as `parts.speaker_driver`.
pub fn driver(
    name: &str,
    plus: &str,
    minus: &str,
    s: &Speaker,
    series: f64,
    field: Option<&str>,
    box_m3: f64,
) -> (Vec<Element>, Vec<(String, f64)>) {
    let (n, up) = (name.to_lowercase(), name.to_uppercase());
    let bl2 = s.bl_tm * s.bl_tm;
    let m0 = s.mms_kg - s.modes.iter().fold(0.0, |acc, m| acc + m.mass_kg);
    let s0 = s.sd_m2 - s.modes.iter().fold(0.0, |acc, m| acc + m.area_m2);
    let coil = format!("{n}_m");
    let (nl, ne) = (format!("{n}_l"), format!("{n}_e"));
    let mut cms = s.cms_m_per_n;
    if box_m3 > 0.0 {
        let cab = box_compliance_m_per_n(box_m3, s.sd_m2);
        cms = cms * cab / (cms + cab);
    }
    let ve = if field.is_some() {
        format!("{n}_v")
    } else {
        coil.clone()
    };
    let mut els = vec![
        r(format!("R{up}_re"), plus, &nl, s.re_ohm * series),
        l(format!("L{up}_le"), &nl, &ne, s.le_h * series),
        l(format!("L{up}_l2"), &ne, &ve, s.l2_h * series),
        r(format!("R{up}_r2"), &ne, &ve, s.r2_ohm * series),
        c(format!("C{up}_m"), &coil, minus, m0 / bl2 / series),
        l(format!("L{up}_cms"), &coil, minus, cms * bl2 * series),
        r(
            format!("R{up}_rms"),
            &coil,
            minus,
            bl2 / s.rms_ns_per_m * series,
        ),
    ];
    if let (Some(fnode), Some(f), Some(model)) = (field, s.field.as_ref(), field_model(name, s)) {
        let (x, fs) = (format!("{n}_x"), format!("{n}_fs"));
        els.push(g(format!("G{up}_g1"), &ve, minus, &x, minus, GYRATOR_S));
        els.push(g(format!("G{up}_g2"), &x, minus, &ve, minus, -GYRATOR_S));
        els.push(Element::Device(Device {
            name: format!("X{up}_g"),
            model: model.name().to_string(),
            nodes: vec![x.clone(), coil.clone(), fs.clone(), minus.to_string()],
        }));
        els.push(l(format!("L{up}_f"), fnode, &fs, f.l_h));
        els.push(r(format!("R{up}_f"), &fs, minus, f.re_ohm));
    }
    let mut radiating = vec![(coil.clone(), s0)];
    for (i, m) in s.modes.iter().enumerate() {
        let k = i + 1;
        let w = 2.0 * PI * m.f_hz;
        let stiffness = m.mass_kg * (w * w);
        let damping = w * m.mass_kg / m.q;
        let node = format!("{n}_k{k}");
        els.push(r(
            format!("R{up}_k{k}"),
            &coil,
            &node,
            bl2 / damping * series,
        ));
        els.push(l(
            format!("L{up}_k{k}"),
            &coil,
            &node,
            bl2 / stiffness * series,
        ));
        els.push(c(
            format!("C{up}_k{k}"),
            &node,
            minus,
            m.mass_kg / bl2 / series,
        ));
        radiating.push((node, m.area_m2));
    }
    (els, radiating)
}

/// The sound pressure on `out` (pascals as volts), drawing nothing from the driver: one
/// driver's of `series` (the nodes carry all of theirs).
#[allow(clippy::too_many_arguments)]
pub fn readout(
    name: &str,
    minus: &str,
    out: &str,
    s: &Speaker,
    radiating: &[(String, f64)],
    cab: &Cabinet,
    distance_m: f64,
    series: f64,
    closed: bool,
) -> Vec<Element> {
    let (n, up) = (name.to_lowercase(), name.to_uppercase());
    let r0 = READOUT_OHM;
    let (pf, lp) = (format!("{n}_pf"), format!("{n}_b"));
    let mut els = Vec::new();
    for (i, (node, area)) in radiating.iter().enumerate() {
        let gm = RHO_AIR_KG_M3 * area / (2.0 * PI * distance_m * s.bl_tm) / series;
        if gm != 0.0 {
            els.push(g(format!("G{up}_a{i}"), GROUND, &pf, node, minus, gm));
        }
    }
    els.push(l(format!("L{up}_pf"), &pf, GROUND, 1.0));
    if closed {
        let fb = baffle_step_hz(cab);
        els.push(g(format!("G{up}_b"), GROUND, &lp, &pf, GROUND, 1.0 / r0));
        els.push(r(format!("R{up}_b"), &lp, GROUND, r0));
        els.push(c(
            format!("C{up}_b"),
            &lp,
            GROUND,
            1.0 / (2.0 * PI * fb * r0),
        ));
        els.push(g(format!("G{up}_o"), GROUND, out, &pf, GROUND, 1.0 / r0));
        els.push(g(format!("G{up}_o0"), GROUND, out, &lp, GROUND, -0.5 / r0));
        els.push(r(format!("R{up}_o"), out, GROUND, r0));
        return els;
    }
    let fb = directivity_pole_hz(s.sd_m2);
    els.push(g(format!("G{up}_b"), GROUND, &lp, &pf, GROUND, 1.0 / r0));
    els.push(r(format!("R{up}_b"), &lp, GROUND, r0));
    els.push(c(
        format!("C{up}_b"),
        &lp,
        GROUND,
        1.0 / (2.0 * PI * fb * r0),
    ));
    let taps = edge_taps(cab, distance_m);
    let last = taps.iter().map(|t| t.0).max().unwrap_or(0);
    let tau = LADDER_SECTION_S;
    let d = |i: usize| format!("{n}_d{i}");
    els.push(g(format!("G{up}_d"), GROUND, &d(0), &lp, GROUND, 2.0 / r0));
    els.push(r(format!("R{up}_d0"), &d(0), GROUND, r0));
    els.push(c(format!("C{up}_d0"), &d(0), GROUND, tau / r0 / 2.0));
    for i in 1..=last {
        els.push(l(format!("L{up}_d{i}"), &d(i - 1), &d(i), tau * r0));
        let cf = if i < last { tau / r0 } else { tau / r0 / 2.0 };
        els.push(c(format!("C{up}_d{i}"), &d(i), GROUND, cf));
    }
    els.push(r(format!("R{up}_dt"), &d(last), GROUND, r0));
    els.push(g(format!("G{up}_o"), GROUND, out, &pf, GROUND, 1.0 / r0));
    for (e, &(tap, weight)) in taps.iter().enumerate() {
        if weight != 0.0 {
            els.push(g(
                format!("G{up}_o{e}"),
                GROUND,
                out,
                &d(tap),
                GROUND,
                -weight / r0,
            ));
        }
    }
    els.push(r(format!("R{up}_o"), out, GROUND, r0));
    els
}

/// Speaker `name` between plus and minus (`series` identical drivers), one driver's sound
/// pressure on `out`.
#[allow(clippy::too_many_arguments)]
pub fn speaker(
    name: &str,
    plus: &str,
    minus: &str,
    out: &str,
    s: &Speaker,
    cab: &Cabinet,
    distance_m: f64,
    series: f64,
    field: Option<&str>,
    box_m3: f64,
) -> Vec<Element> {
    let (mut els, radiating) = driver(name, plus, minus, s, series, field, box_m3);
    els.extend(readout(
        name,
        minus,
        out,
        s,
        &radiating,
        cab,
        distance_m,
        series,
        box_m3 > 0.0,
    ));
    els
}

/// Speaker `name` without its readout (a live build's; `parts.speaker_terminal`): the driver
/// between plus and minus, its terminal voltage on `out` (G<NAME>_t into R<NAME>_t, 1 ohm
/// to ground); with `series` drivers, one driver's (the pair's voltage over n).
#[allow(clippy::too_many_arguments)]
pub fn terminal(
    name: &str,
    plus: &str,
    minus: &str,
    out: &str,
    s: &Speaker,
    series: f64,
    field: Option<&str>,
    box_m3: f64,
) -> Vec<Element> {
    let (mut els, _) = driver(name, plus, minus, s, series, field, box_m3);
    let upper = name.to_uppercase();
    els.push(Element::Vccs(circuitsim::ir::Vccs {
        name: format!("G{upper}_t"),
        pos: GROUND.into(),
        neg: out.into(),
        ctrl_pos: plus.into(),
        ctrl_neg: minus.into(),
        gm_s: 1.0 / series,
    }));
    els.push(Element::Resistor(circuitsim::ir::Resistor {
        name: format!("R{upper}_t"),
        a: out.into(),
        b: GROUND.into(),
        r_ohm: 1.0,
    }));
    els
}
