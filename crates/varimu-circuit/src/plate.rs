//! Plate reverbs' plates: the port of `varimu/devices/plate.py`'s component and decay
//! table, and of the plate part in `varimu/circuit/parts.py` (`plate`), in Python's order
//! of floating-point operations so the IR agrees bit for bit (docs/REVERB_PLAN.md, E6).

use circuitsim::ir::{Capacitor, Element, Inductor, Plate, Resistor};

use crate::Error;
use crate::yaml::{Map, Value};

/// 6 ln 10 (T60 = 6 ln 10 / the energy decay rate): `math.log(10.0)` is this constant.
pub const SIX_LN10: f64 = 6.0 * std::f64::consts::LN_10;

#[derive(Debug, Clone, PartialEq)]
pub struct PlateComponent {
    pub name: String,
    pub lx_m: f64,
    pub ly_m: f64,
    pub thickness_m: f64,
    pub density_kg_m3: f64,
    pub youngs_pa: f64,
    pub poisson: f64,
    pub tension_n_m: f64,
    pub drive_xy: [f64; 2],
    pub pickup_xy: [f64; 2],
    pub exciter_re_ohm: f64,
    pub exciter_le_h: f64,
    pub exciter_bl_tm: f64,
    pub pickup_v_per_m_s2: f64,
    pub pickup_c_f: f64,
    pub f_max_hz: f64,
    pub tail_db: f64,
    pub decay_f_hz: Vec<f64>,
    pub decay_curves_s: Vec<Vec<f64>>,
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

fn nums(v: Option<&Value>, what: &str) -> Result<Vec<f64>, Error> {
    v.and_then(Value::as_list)
        .ok_or_else(|| Error(format!("{what}: needs a list")))?
        .iter()
        .map(|x| {
            x.as_f64()
                .ok_or_else(|| Error(format!("{what}: not a number")))
        })
        .collect()
}

fn pair(m: &Map, key: &str, what: &str) -> Result<[f64; 2], Error> {
    let v = nums(m.get(key), &format!("{what}.{key}"))?;
    match v.as_slice() {
        [a, b] => Ok([*a, *b]),
        _ => Err(Error(format!("{what}.{key}: two numbers"))),
    }
}

/// A plate version's data (kind plate), as `plate_from_data`.
pub fn from_data(data: &Value, what: &str) -> Result<PlateComponent, Error> {
    let d = data
        .as_map()
        .ok_or_else(|| Error(format!("{what}: not a mapping")))?;
    if d.get("kind").and_then(Value::as_str) != Some("plate") {
        return Err(Error(format!("{what}: not a plate")));
    }
    let p = sub(d, "plate", what)?;
    let pos = sub(d, "positions", what)?;
    let ex = sub(d, "exciter", what)?;
    let pu = sub(d, "pickup", what)?;
    let m = sub(d, "model", what)?;
    let dec = sub(d, "decay", what)?;
    let curves = dec
        .get("curves")
        .and_then(Value::as_list)
        .ok_or_else(|| Error(format!("{what}: decay needs `curves`")))?
        .iter()
        .map(|c| {
            c.as_map()
                .ok_or_else(|| Error(format!("{what}: a decay curve isn't a mapping")))
                .and_then(|c| nums(c.get("t60_s"), &format!("{what}.decay.curves")))
        })
        .collect::<Result<Vec<_>, _>>()?;
    let f_hz = nums(dec.get("f_hz"), &format!("{what}.decay.f_hz"))?;
    if curves.iter().any(|c| c.len() != f_hz.len()) || !f_hz.contains(&500.0) {
        return Err(Error(format!(
            "{what}: each decay curve needs a T60 per frequency, and 500 Hz among them"
        )));
    }
    Ok(PlateComponent {
        name: what.to_string(),
        lx_m: num(p, "lx_m", what)?,
        ly_m: num(p, "ly_m", what)?,
        thickness_m: num(p, "thickness_m", what)?,
        density_kg_m3: num(p, "density_kg_m3", what)?,
        youngs_pa: num(p, "youngs_pa", what)?,
        poisson: num(p, "poisson", what)?,
        tension_n_m: num(p, "tension_n_m", what)?,
        drive_xy: pair(pos, "drive_xy", what)?,
        pickup_xy: pair(pos, "pickup_xy", what)?,
        exciter_re_ohm: num(ex, "re_ohm", what)?,
        exciter_le_h: num(ex, "le_h", what)?,
        exciter_bl_tm: num(ex, "bl_tm", what)?,
        pickup_v_per_m_s2: num(pu, "v_per_m_s2", what)?,
        pickup_c_f: num(pu, "c_f", what)?,
        f_max_hz: num(m, "f_max_hz", what)?,
        tail_db: num(m, "tail_db", what)?,
        decay_f_hz: f_hz,
        decay_curves_s: curves,
    })
}

impl PlateComponent {
    fn i500(&self) -> usize {
        self.decay_f_hz
            .iter()
            .position(|&f| f == 500.0)
            .expect("checked on load")
    }

    /// The damper's range: the curves' decay at 500 Hz, shortest and longest.
    pub fn t500_range(&self) -> (f64, f64) {
        let i = self.i500();
        let t: Vec<f64> = self.decay_curves_s.iter().map(|c| c[i]).collect();
        (
            t.iter().copied().fold(f64::INFINITY, f64::min),
            t.iter().copied().fold(f64::NEG_INFINITY, f64::max),
        )
    }
}

/// `decay_table` in plate.py: the energy decay rate (Hz, 1/s) for the damper at `t500_s`.
pub fn decay_table(c: &PlateComponent, t500_s: f64) -> Vec<[f64; 2]> {
    let i500 = c.i500();
    let rates: Vec<Vec<f64>> = c
        .decay_curves_s
        .iter()
        .map(|curve| curve.iter().map(|t| SIX_LN10 / t).collect())
        .collect();
    let mut order: Vec<usize> = (0..rates.len()).collect();
    order.sort_by(|&a, &b| rates[a][i500].total_cmp(&rates[b][i500]));
    let (lo, hi) = c.t500_range();
    let t = t500_s.max(lo).min(hi);
    let target = SIX_LN10 / t;
    let (mut a, mut b) = (order[0], order[order.len() - 1]);
    for j in 0..order.len() - 1 {
        if rates[order[j]][i500] <= target && target <= rates[order[j + 1]][i500] {
            (a, b) = (order[j], order[j + 1]);
            break;
        }
    }
    let (ra, rb) = (rates[a][i500], rates[b][i500]);
    let w = if rb == ra {
        0.0
    } else {
        (target - ra) / (rb - ra)
    };
    c.decay_f_hz
        .iter()
        .zip(rates[a].iter().zip(&rates[b]))
        .map(|(&f, (&sa, &sb))| [f, (1.0 - w) * sa + w * sb])
        .collect()
}

/// The plate's driving-point impedance, an infinite plate's 8 sqrt(D rho H) (N s/m).
pub fn plate_impedance_ns_per_m(c: &PlateComponent) -> f64 {
    let h = c.thickness_m;
    let d = c.youngs_pa * (h * h * h) / (12.0 * (1.0 - c.poisson * c.poisson));
    8.0 * (d * c.density_kg_m3 * h).sqrt()
}

/// The plate part (`parts.plate`): the exciter coil, the plate and the pickup's capacitance.
pub fn plate(
    name: &str,
    plus: &str,
    minus: &str,
    out: &str,
    c: &PlateComponent,
    decay_500hz_s: f64,
) -> Vec<Element> {
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let bl = c.exciter_bl_tm;
    vec![
        Element::Inductor(Inductor {
            name: format!("L{upper}_le"),
            a: plus.to_string(),
            b: format!("{n}_a"),
            l_h: c.exciter_le_h,
        }),
        Element::Resistor(Resistor {
            name: format!("R{upper}_mot"),
            a: format!("{n}_a"),
            b: format!("{n}_c"),
            r_ohm: bl * bl / plate_impedance_ns_per_m(c),
        }),
        Element::Resistor(Resistor {
            name: format!("R{upper}_re"),
            a: format!("{n}_c"),
            b: minus.to_string(),
            r_ohm: c.exciter_re_ohm,
        }),
        Element::Plate(Plate {
            name: format!("V{upper}"),
            sense_pos: format!("{n}_c"),
            sense_neg: minus.to_string(),
            force_per_v: bl / c.exciter_re_ohm,
            out: format!("{n}_p"),
            out_per_m_s2: c.pickup_v_per_m_s2,
            lx_m: c.lx_m,
            ly_m: c.ly_m,
            thickness_m: c.thickness_m,
            density_kg_m3: c.density_kg_m3,
            youngs_pa: c.youngs_pa,
            poisson: c.poisson,
            tension_n_m: c.tension_n_m,
            drive_xy: c.drive_xy,
            pickup_xy: c.pickup_xy,
            f_max_hz: c.f_max_hz,
            decay: decay_table(c, decay_500hz_s),
            tail_db: c.tail_db,
        }),
        Element::Capacitor(Capacitor {
            name: format!("C{upper}_pu"),
            a: format!("{n}_p"),
            b: out.to_string(),
            c_f: c.pickup_c_f,
            v0_v: None,
        }),
    ]
}
