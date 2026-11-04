//! Magnetic tape: the port of `varimu/devices/tape.py`'s component (`tape_from_data`) and of
//! the tape part in `varimu/circuit/parts.py` (`tape`), so the IR agrees bit for bit
//! (docs/TAPE_PLAN.md, TM4).

use circuitsim::ir::{Element, Inductor, Resistor, Tape};
use circuitsim::tape_stream::{TapeParams, Varispeed};

use crate::Error;
use crate::yaml::{Map, Value};

/// A tape component version (kind tape): its coating and particles.
#[derive(Debug, Clone, PartialEq)]
pub struct TapeComponent {
    pub name: String,
    pub coating_m: f64,
    pub ms_a_m: f64,
    pub hc_median_a_m: f64,
    pub sigma_ln_hc: f64,
    pub sigma_hi_a_m: f64,
    pub h_max_a_m: f64,
    pub n_table: usize,
    pub kappa: f64,
    pub orientations: usize,
    /// The noise block's (particle_volume_m3, packing, packing_sigma, packing_corr_m),
    /// zeros without one.
    pub grain: [f64; 4],
}

/// The tape part's numerics (`parts.TAPE_*`).
pub const LAYERS: usize = 6;
/// Cells per bias wavelength (`parts.TAPE_CELLS_PER_BIAS_WAVELENGTH`).
pub const CELLS_PER_BIAS_WAVELENGTH: f64 = 7.62;
pub const TABLE_STEP: f64 = 1.0 / 40.0;
pub const DEMAG_ITERATIONS: usize = 8;
pub const DEMAG_TOL: f64 = 2e-3;
pub const BLOCK_M: f64 = 16e-3;
pub const MARGIN_M: f64 = 0.5e-3;

/// 120 Oe, as `parts.TAPE_ZONE_FLOOR_A_M`.
pub fn zone_floor_a_m() -> f64 {
    120.0 * (1000.0 / (4.0 * std::f64::consts::PI))
}

/// The part's physical values, in the macro's order (`parts.TAPE_VALUES`).
pub const VALUES: [&str; 16] = [
    "speed_m_s",
    "f_bias_hz",
    "bias_a_m",
    "rec_gap_m",
    "rep_gap_m",
    "pole_m",
    "relax_m",
    "spacing_m",
    "track_m",
    "head_distance_m",
    "rec_l_h",
    "rec_r_ohm",
    "rec_h_per_a",
    "rep_l_h",
    "rep_r_ohm",
    "rep_h_per_a",
];

fn num(m: &Map, key: &str, what: &str) -> Result<f64, Error> {
    m.get(key)
        .and_then(Value::as_f64)
        .ok_or_else(|| Error(format!("{what}: `{key}` must be a number")))
}

fn count(m: &Map, key: &str, what: &str) -> Result<usize, Error> {
    let x = num(m, key, what)?;
    if x >= 0.0 && x.fract() == 0.0 {
        Ok(x as usize)
    } else {
        Err(Error(format!("{what}: `{key}` must be a count")))
    }
}

fn sub<'a>(m: &'a Map, key: &str, what: &str) -> Result<&'a Map, Error> {
    m.get(key)
        .and_then(Value::as_map)
        .ok_or_else(|| Error(format!("{what}: needs `{key}`")))
}

/// The values only the medium's own bias reads (`parts.TAPE_OWN_BIAS`: the literal bias
/// leaves them out).
pub const OWN_BIAS: [&str; 2] = ["bias_a_m", "rec_l_h"];

/// The transport's values (`parts.TAPE_TRANSPORT`): optional, all or none.
pub const TRANSPORT: [&str; 13] = [
    "capstan_d_m",
    "capstan_rms",
    "roller_d_m",
    "roller_rms",
    "reel_r_m",
    "reel_rms",
    "hunting_hz",
    "hunting_q",
    "hunting_rms",
    "scrape_span_m",
    "scrape_c_m_s",
    "scrape_q",
    "scrape_rms",
];

/// The speed's components from [`TRANSPORT`]'s values, as `parts.tape_transport`:
/// periodic (relative peak, Hz, phase) and random resonances (relative rms, Hz, Q).
pub fn transport(speed_m_s: f64, tr: &[f64; 13]) -> (Vec<[f64; 3]>, Vec<[f64; 3]>) {
    let [
        capstan_d,
        capstan_rms,
        roller_d,
        roller_rms,
        reel_r,
        reel_rms,
        hunting_hz,
        hunting_q,
        hunting_rms,
        scrape_span,
        scrape_c,
        scrape_q,
        scrape_rms,
    ] = *tr;
    let pi = std::f64::consts::PI;
    let v = speed_m_s;
    let periodic = vec![
        [capstan_rms * 2f64.sqrt(), v / (pi * capstan_d), 0.0],
        [roller_rms * 2f64.sqrt(), v / (pi * roller_d), 1.0],
        [reel_rms * 2f64.sqrt(), v / (2.0 * pi * reel_r), 2.0],
    ];
    let random = vec![
        [hunting_rms, hunting_hz, hunting_q],
        [scrape_rms, scrape_c / (2.0 * scrape_span), scrape_q],
    ];
    (periodic, random)
}

/// A tape version's data (kind tape), as `tape_from_data`; it must have an orientation
/// block (the vector model the stream runs).
pub fn from_data(data: &Value, what: &str) -> Result<TapeComponent, Error> {
    let d = data
        .as_map()
        .ok_or_else(|| Error(format!("{what}: not a mapping")))?;
    if d.get("kind").and_then(Value::as_str) != Some("tape") {
        return Err(Error(format!("{what}: not a tape")));
    }
    let c = sub(d, "coating", what)?;
    let m = sub(d, "particles", what)?;
    let o = sub(d, "orientation", what)?;
    Ok(TapeComponent {
        name: what.to_string(),
        coating_m: num(c, "thickness_m", what)?,
        ms_a_m: num(m, "ms_a_m", what)?,
        hc_median_a_m: num(m, "hc_median_a_m", what)?,
        sigma_ln_hc: num(m, "sigma_ln_hc", what)?,
        sigma_hi_a_m: num(m, "sigma_hi_a_m", what)?,
        h_max_a_m: num(m, "h_max_a_m", what)?,
        n_table: count(m, "n_table", what)?,
        kappa: num(o, "kappa", what)?,
        orientations: count(o, "n", what)?,
        grain: match d.get("noise").and_then(Value::as_map) {
            Some(nz) => [
                num(nz, "particle_volume_m3", what)?,
                num(nz, "packing", what)?,
                num(nz, "packing_sigma", what)?,
                num(nz, "packing_corr_m", what)?,
            ],
            None => [0.0; 4],
        },
    })
}

/// The tape part (`parts.tape`): the record coil, the tape and the repro coil. `v`: the
/// values of [`VALUES`], in order. `bias_substeps`: the literal bias (rec_plus and
/// rec_minus the record coil's resistance's ends in a multi-rate section; no record coil
/// of its own; bias_a_m and rec_l_h not read). `transport`: [`TRANSPORT`]'s values, or
/// None (a constant speed). `supply`: varispeed's (node, nominal Hz): the capstan's motor
/// on a supply whose frequency is the node's voltage, hunting at the transport's
/// hunting_hz and hunting_q (a transport is required).
#[allow(clippy::too_many_arguments)]
pub fn tape(
    name: &str,
    rec_plus: &str,
    rec_minus: &str,
    out: &str,
    t: &TapeComponent,
    v: &[f64; 16],
    bias_substeps: Option<usize>,
    transport: Option<&[f64; 13]>,
    supply: Option<(&str, f64)>,
) -> Vec<Element> {
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let [
        speed,
        f_bias,
        bias,
        rec_gap,
        rep_gap,
        pole,
        relax,
        spacing,
        track,
        distance,
        rec_l,
        rec_r,
        rec_h,
        rep_l,
        rep_r,
        rep_h,
    ] = *v;
    let (flutter, flutter_noise) = match transport {
        Some(tr) => self::transport(speed, tr),
        None => (Vec::new(), Vec::new()),
    };
    let medium = TapeParams {
        hc_median_a_m: t.hc_median_a_m,
        sigma_ln_hc: t.sigma_ln_hc,
        sigma_hi_a_m: t.sigma_hi_a_m,
        h_max_a_m: t.h_max_a_m,
        n_table: t.n_table,
        ms_a_m: t.ms_a_m,
        coating_m: t.coating_m,
        kappa: t.kappa,
        orientations: t.orientations,
        speed_m_s: speed,
        f_bias_hz: f_bias,
        hg_bias_a_m: if bias_substeps.is_some() { 0.0 } else { bias },
        bias_phase_rad: 0.0,
        rec_gap_m: rec_gap,
        rep_gap_m: rep_gap,
        pole_m: pole,
        relax_m: relax,
        spacing_m: spacing,
        track_m: track,
        head_distance_m: distance,
        rep_h_per_a: rep_h,
        layers: LAYERS,
        ds_m: speed / (f_bias * CELLS_PER_BIAS_WAVELENGTH),
        table_step: TABLE_STEP,
        zone_floor_a_m: zone_floor_a_m(),
        local_zones: true,
        demag_iterations: DEMAG_ITERATIONS,
        demag_tol: DEMAG_TOL,
        head_image: true,
        lam_min_m: 3.0 * speed / f_bias,
        block_m: BLOCK_M,
        margin_m: MARGIN_M,
        flutter,
        flutter_noise,
        particle_volume_m3: t.grain[0],
        packing: t.grain[1],
        packing_sigma: t.grain[2],
        packing_corr_m: t.grain[3],
        bias_substeps,
        reduced: None,
        varispeed: match (supply, transport) {
            (Some((_, nominal_hz)), Some(tr)) => Some(Varispeed {
                nominal_hz,
                hunting_hz: tr[6],
                hunting_q: tr[7],
            }),
            _ => None,
        },
    };
    let literal = bias_substeps.is_some();
    let mut els = Vec::new();
    if !literal {
        els.push(Element::Inductor(Inductor {
            name: format!("L{upper}_rec"),
            a: rec_plus.to_string(),
            b: format!("{n}_a"),
            l_h: rec_l,
        }));
        els.push(Element::Resistor(Resistor {
            name: format!("R{upper}_rec"),
            a: format!("{n}_a"),
            b: rec_minus.to_string(),
            r_ohm: rec_r,
        }));
    }
    els.push(Element::Tape(Tape {
        name: format!("V{upper}"),
        sense_pos: if literal {
            rec_plus.to_string()
        } else {
            format!("{n}_a")
        },
        sense_neg: rec_minus.to_string(),
        h_per_v: rec_h / rec_r,
        out: format!("{n}_e"),
        medium: Box::new(medium),
        supply: supply.map(|(node, _)| node.to_string()),
    }));
    els.extend([
        Element::Inductor(Inductor {
            name: format!("L{upper}_rep"),
            a: format!("{n}_e"),
            b: format!("{n}_b"),
            l_h: rep_l,
        }),
        Element::Resistor(Resistor {
            name: format!("R{upper}_rep"),
            a: format!("{n}_b"),
            b: out.to_string(),
            r_ohm: rep_r,
        }),
    ]);
    els
}
