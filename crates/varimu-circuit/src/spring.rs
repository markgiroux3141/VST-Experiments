//! Spring reverb tanks: the port of `varimu/devices/spring.py`'s component and decay table,
//! and of the spring tank part in `varimu/circuit/parts.py` (`spring_tank`), in Python's
//! order of floating-point operations so the IR agrees bit for bit (docs/REVERB_PLAN.md,
//! E3).

use std::f64::consts::PI;

use circuitsim::ir::{Element, Inductor, Resistor, Spring};

use crate::Error;
use crate::plate::SIX_LN10;
use crate::yaml::{Map, Value};

/// Third octaves from 20 Hz to 20 kHz (`spring.DECAY_GRID_HZ`).
pub const DECAY_GRID_HZ: [f64; 31] = [
    20.0, 25.0, 31.5, 40.0, 50.0, 63.0, 80.0, 100.0, 125.0, 160.0, 200.0, 250.0, 315.0, 400.0,
    500.0, 630.0, 800.0, 1000.0, 1250.0, 1600.0, 2000.0, 2500.0, 3150.0, 4000.0, 5000.0, 6300.0,
    8000.0, 10000.0, 12500.0, 16000.0, 20000.0,
];

/// One spring as measured.
#[derive(Debug, Clone, PartialEq)]
pub struct SpringGeometry {
    pub wire_diameter_m: f64,
    pub helix_diameter_m: f64,
    pub turns: f64,
    pub helix_length_m: f64,
}

impl SpringGeometry {
    /// The uncurled wire's length (`Spring.wire_length_m`).
    pub fn wire_length_m(&self) -> f64 {
        let a = 2.0 * PI * (0.5 * self.helix_diameter_m) * self.turns;
        let h = self.helix_length_m;
        (a * a + h * h).sqrt()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct SpringTankComponent {
    pub name: String,
    pub springs: Vec<SpringGeometry>,
    pub density_kg_m3: f64,
    pub youngs_pa: f64,
    pub input_re_ohm: f64,
    pub input_le_h: f64,
    pub input_force_per_a: f64,
    pub input_saturation_a: f64,
    pub output_re_ohm: f64,
    pub output_le_h: f64,
    pub output_v_per_m_s: f64,
    pub t60_500hz_s: f64,
    pub loss_factor: f64,
    pub f_max_hz: f64,
    pub tail_db: f64,
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

/// A spring tank version's data (kind spring_tank), as `spring_tank_from_data`.
pub fn from_data(data: &Value, what: &str) -> Result<SpringTankComponent, Error> {
    let d = data
        .as_map()
        .ok_or_else(|| Error(format!("{what}: not a mapping")))?;
    if d.get("kind").and_then(Value::as_str) != Some("spring_tank") {
        return Err(Error(format!("{what}: not a spring tank")));
    }
    let list = sub(d, "springs", what)?
        .get("list")
        .and_then(Value::as_list)
        .ok_or_else(|| Error(format!("{what}: springs.list must be a list")))?;
    let mut springs = Vec::new();
    for (i, s) in list.iter().enumerate() {
        let w = format!("{what}.springs.list[{i}]");
        let m = s
            .as_map()
            .ok_or_else(|| Error(format!("{w}: not a mapping")))?;
        springs.push(SpringGeometry {
            wire_diameter_m: num(m, "wire_diameter_m", &w)?,
            helix_diameter_m: num(m, "helix_diameter_m", &w)?,
            turns: num(m, "turns", &w)?,
            helix_length_m: num(m, "helix_length_m", &w)?,
        });
    }
    let mat = sub(d, "material", what)?;
    let i = sub(d, "input", what)?;
    let o = sub(d, "output", what)?;
    let loss = sub(d, "losses", what)?;
    let m = sub(d, "model", what)?;
    Ok(SpringTankComponent {
        name: what.to_string(),
        springs,
        density_kg_m3: num(mat, "density_kg_m3", what)?,
        youngs_pa: num(mat, "youngs_pa", what)?,
        input_re_ohm: num(i, "re_ohm", what)?,
        input_le_h: num(i, "le_h", what)?,
        input_force_per_a: num(i, "force_per_a", what)?,
        input_saturation_a: num(i, "saturation_a", what)?,
        output_re_ohm: num(o, "re_ohm", what)?,
        output_le_h: num(o, "le_h", what)?,
        output_v_per_m_s: num(o, "v_per_m_s", what)?,
        t60_500hz_s: num(loss, "t60_500hz_s", what)?,
        loss_factor: num(loss, "loss_factor", what)?,
        f_max_hz: num(m, "f_max_hz", what)?,
        tail_db: num(m, "tail_db", what)?,
    })
}

/// The energy decay rate (Hz, 1/s) on [`DECAY_GRID_HZ`] (`spring.decay_table`).
pub fn decay_table(t60_500hz_s: f64, loss_factor: f64) -> Vec<[f64; 2]> {
    let ends = SIX_LN10 / t60_500hz_s - 2.0 * PI * 500.0 * loss_factor;
    let ends = ends.max(0.0);
    DECAY_GRID_HZ
        .iter()
        .map(|&f| [f, ends + 2.0 * PI * f * loss_factor])
        .collect()
}

/// The springs' tangential impedance at their ends (`characteristic_impedance_ns_per_m`).
pub fn characteristic_impedance_ns_per_m(c: &SpringTankComponent) -> f64 {
    let c_m_s = (c.youngs_pa / c.density_kg_m3).sqrt();
    let mut z = 0.0;
    for s in &c.springs {
        let r = 0.5 * s.wire_diameter_m;
        let area = PI * r * r;
        let v0 = r * c_m_s / s.helix_diameter_m;
        z += c.density_kg_m3 * area * v0;
    }
    z
}

/// The spring tank part (`parts.spring_tank`): the input coil, the springs and the output
/// coil; `out_r`, a split tank (every second spring on an output coil of its own).
pub fn spring_tank(
    name: &str,
    plus: &str,
    minus: &str,
    out: &str,
    c: &SpringTankComponent,
    out_r: Option<&str>,
) -> Result<Vec<Element>, Error> {
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let k = c.input_force_per_a;
    let all: Vec<[f64; 3]> = c
        .springs
        .iter()
        .map(|s| {
            [
                0.5 * s.wire_diameter_m,
                0.5 * s.helix_diameter_m,
                s.wire_length_m(),
            ]
        })
        .collect();
    if let Some(o) = out_r
        && all.len() < 2
    {
        return Err(Error(format!(
            "{} has one spring: it can't be split onto {o}",
            c.name
        )));
    }
    let medium = |el: String, springs: Vec<[f64; 3]>, node: String| {
        Element::Spring(Spring {
            name: el,
            sense_pos: format!("{n}_c"),
            sense_neg: minus.to_string(),
            force_per_v: k / c.input_re_ohm,
            out: node,
            out_per_m_s: c.output_v_per_m_s,
            density_kg_m3: c.density_kg_m3,
            youngs_pa: c.youngs_pa,
            springs,
            f_max_hz: c.f_max_hz,
            decay: decay_table(c.t60_500hz_s, c.loss_factor),
            tail_db: c.tail_db,
            saturation_v: c.input_saturation_a * c.input_re_ohm,
        })
    };
    // Split: the first, third, ... spring on out, the second, fourth, ... on out_r.
    let every = |from: usize| {
        all.iter()
            .skip(from)
            .step_by(2)
            .copied()
            .collect::<Vec<_>>()
    };
    let left = match out_r {
        Some(_) => every(0),
        None => all.clone(),
    };
    let mut els = vec![
        Element::Inductor(Inductor {
            name: format!("L{upper}_in"),
            a: plus.to_string(),
            b: format!("{n}_a"),
            l_h: c.input_le_h,
        }),
        Element::Resistor(Resistor {
            name: format!("R{upper}_mot"),
            a: format!("{n}_a"),
            b: format!("{n}_c"),
            r_ohm: k * k / characteristic_impedance_ns_per_m(c),
        }),
        Element::Resistor(Resistor {
            name: format!("R{upper}_in"),
            a: format!("{n}_c"),
            b: minus.to_string(),
            r_ohm: c.input_re_ohm,
        }),
        medium(format!("V{upper}"), left, format!("{n}_e")),
        Element::Inductor(Inductor {
            name: format!("L{upper}_out"),
            a: format!("{n}_e"),
            b: format!("{n}_b"),
            l_h: c.output_le_h,
        }),
        Element::Resistor(Resistor {
            name: format!("R{upper}_out"),
            a: format!("{n}_b"),
            b: out.to_string(),
            r_ohm: c.output_re_ohm,
        }),
    ];
    if let Some(o) = out_r {
        els.push(medium(format!("V{upper}_R"), every(1), format!("{n}_e2")));
        els.push(Element::Inductor(Inductor {
            name: format!("L{upper}_out2"),
            a: format!("{n}_e2"),
            b: format!("{n}_b2"),
            l_h: c.output_le_h,
        }));
        els.push(Element::Resistor(Resistor {
            name: format!("R{upper}_out2"),
            a: format!("{n}_b2"),
            b: o.to_string(),
            r_ohm: c.output_re_ohm,
        }));
    }
    Ok(els)
}
