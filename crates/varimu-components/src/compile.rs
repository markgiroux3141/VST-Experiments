//! A design compiled: the macro's values (core, turns, per winding ratio / r / c / leak,
//! interwinding), a report of what they come from, warnings, and the version file.
//!
//! - Core: area = leg x stack x stacking factor; path from the lamination table; the gap
//!   in the flux path: two joints (centre and outer leg for an EI, both legs for a UI),
//!   each the effective `joint_gap_m` plus, butt-stacked, the spacer; a spacer's gap is
//!   shortened by the fringing factor F = 1 + (l_g / sqrt(A)) ln(2 G / l_g) (McLyman,
//!   l_g one joint's gap, G the window height).
//! - DC resistance: per layer, turns x turn length x resistivity / bare area, copper at
//!   the table's temperature (20 C).
//! - Leakage: [`crate::leakage`]; capacitance: [`crate::capacitance`].
//! - The magnetizing inductance (reported, not compiled: the circuit's core model gives
//!   it): the reference winding's N^2 A / (the core's linear-limit and the gap's
//!   reluctance), as `varimu.circuit.parts.turns_for_inductance` inverts it.
//! - Warnings: a layer longer than the traverse, a build wider than the window, the flux
//!   density at the rating above `b_limit_t` or the material's saturation (mu0 Ms).

use std::f64::consts::PI;
use std::path::Path;

use circuitsim::devices::core::{MU0, MagneticCore as CoreDevice};
use circuitsim::ir::TESLA_PER_V;
use varimu_circuit::Library;
use varimu_circuit::devices::Material;
use varimu_circuit::parts::{CoreSpec, transformer_core};
use varimu_circuit::yaml::{self, Map, Value};
use varimu_circuit::yaml_out::{block_entry, flow_scalar};

use crate::capacitance::{self, Capacitances, Network, Terminal, capacitances};
use crate::design::{Design, LeakageMethod, Section, Stacking};
use crate::geometry::{Layout, layout};
use crate::tables::{Lamination, Shape, Tables};
use crate::{COMPILER, Error, err};
use crate::{fem, leakage};

#[derive(Debug, Clone)]
pub struct WindingOut {
    pub label: String,
    pub turns: f64,
    pub ratio: f64,
    pub r_ohm: f64,
    pub c_f: f64,
    /// Its series leakage in the compiled representation.
    pub leak_h: f64,
    /// The copper's length.
    pub length_m: f64,
}

/// How the compiled leakage reproduces the window's field (`crate::leakage`).
#[derive(Debug, Clone, PartialEq)]
pub enum LeakageModel {
    /// A series leakage per winding.
    Star,
    /// Series leakages with these couplings (j, k, coefficient): the star needed a
    /// negative branch, or misfit for four or more windings.
    Coupled(Vec<(usize, usize, f64)>),
}

#[derive(Debug, Clone)]
pub struct Compiled {
    pub design: Design,
    pub lamination: Lamination,
    pub material: String,
    pub area_m2: f64,
    pub path_m: f64,
    pub gap_m: f64,
    /// The spacer's fringing factor (butt stacking with a spacer).
    pub fringing: Option<f64>,
    /// The reference winding's turns.
    pub turns: f64,
    pub windings: Vec<WindingOut>,
    pub leakage_model: LeakageModel,
    /// lambda_jk (H per turn^2): winding j's leakage with k shorted is N_j^2 lambda_jk
    /// (by the design's leakage method).
    pub pairs: Vec<Vec<f64>>,
    /// The 1D formula's pairs (the same as `pairs` with the formula method).
    pub pairs_formula: Vec<Vec<f64>>,
    /// The field solution's pairs, with the field method.
    pub pairs_field: Option<Vec<Vec<f64>>>,
    /// The compiled series leakages as one matrix (H): the star's diagonal, or the coupled
    /// matrix.
    pub leak_matrix_h: Vec<Vec<f64>>,
    /// The star's branches (H, may be negative) and its worst relative misfit.
    pub star_h: Vec<f64>,
    pub star_misfit: f64,
    pub capacitance: Capacitances,
    /// The facing capacitances as capacitors between terminals (those across one winding
    /// are in its `c_f`).
    pub network: Network,
    /// The reference winding's magnetizing inductance in the core's linear limit.
    pub magnetizing_h: f64,
    pub b_peak_t: Option<f64>,
    pub b_saturation_t: f64,
    /// Copper area / window area.
    pub copper_fill: f64,
    pub layout: Layout,
    pub warnings: Vec<String>,
}

/// A material's `source` from config/magnetics.yaml.
fn material_source(config_dir: &Path, name: &str) -> Result<String, Error> {
    let data = yaml::load(&config_dir.join("magnetics.yaml"))?;
    Ok(data
        .as_map()
        .and_then(|m| m.get("materials"))
        .and_then(Value::as_map)
        .and_then(|m| m.get(name))
        .and_then(Value::as_map)
        .and_then(|m| m.get("source"))
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string())
}

pub fn compile(d: &Design, tables: &Tables, lib: &Library) -> Result<Compiled, Error> {
    let lam = tables.lamination(&d.core.lamination.value)?.clone();
    let mat: Material = lib.material(&d.core.material.value)?;
    let mut lay = layout(d, tables, &lam)?;
    let mut warnings = std::mem::take(&mut lay.warnings);
    let n = d.windings.len();

    // Core.
    let area = lam.leg_m * d.core.stack_m.value * d.core.stacking_factor.value;
    let path = lam.path_m;
    let joint = d.core.joint_gap_m.value;
    let (gap, fringing) = match d.core.stacking.value {
        Stacking::Interleaved => (2.0 * joint, None),
        Stacking::Butt => {
            let spacer = d.core.spacer_m.as_ref().map_or(0.0, |s| s.value);
            if spacer > 0.0 {
                let f = 1.0 + spacer / area.sqrt() * (2.0 * lam.window_height_m / spacer).ln();
                (2.0 * (joint + spacer / f), Some(f))
            } else {
                (2.0 * joint, None)
            }
        }
    };
    if lam.shape == Shape::Ui {
        warnings.push(
            "a UI core: the windings are taken to sit on one leg (the formulas are the EI's)"
                .into(),
        );
    }

    // Turns, DC resistance, copper length.
    // Each winding's turns: its sections' whole turns (the layers' shares sum to them only
    // to rounding).
    let mut turns = vec![0.0; n];
    for sec in &d.sections {
        if let Section::Winding(w) = sec {
            turns[d.winding_index(&w.winding)] += f64::from(w.turns.value);
        }
    }
    let copper = tables.copper()?;
    let mut r_ohm = vec![0.0; n];
    let mut length = vec![0.0; n];
    let mut copper_area = 0.0;
    for l in &lay.layers {
        let sec = match &d.sections[l.section] {
            Section::Winding(w) => w,
            _ => unreachable!(),
        };
        let wire = tables.wire(&sec.wire.value)?;
        let a_cu = PI * wire.bare_m * wire.bare_m / 4.0;
        let len = l.turns * l.mlt_m;
        length[l.winding] += len;
        r_ohm[l.winding] += copper.resistivity_ohm_m * len / a_cu;
        copper_area += l.turns * a_cu;
    }
    let copper_fill = copper_area / (lam.window_width_m * lam.window_height_m);

    // Leakage.
    let pairs_formula = leakage::pairs(&lay, n);
    let (pairs, field_pairs) = match d.leakage_method {
        LeakageMethod::Formula => (pairs_formula.clone(), None),
        LeakageMethod::Field => {
            let z0 = d.bobbin.cheek_m.value + d.bobbin.margin_m.value;
            let mut p = vec![vec![0.0; n]; n];
            let pairs_jk = (0..n).flat_map(|j| ((j + 1)..n).map(move |k| (j, k)));
            for (j, k) in pairs_jk {
                let l = fem::series_short_circuit(&lay, z0, n, &[j], &[k], fem::Mesh::default());
                p[j][k] = l / (turns[j] * turns[j]);
                p[k][j] = p[j][k];
            }
            (p.clone(), Some(p))
        }
    };
    let (star_lam, star_misfit) = match d.leakage_method {
        LeakageMethod::Formula => leakage::star(&lay, n),
        LeakageMethod::Field => {
            let split = (n == 2).then(|| {
                let (s, _) = leakage::star(&lay, 2);
                [s[0], s[1]]
            });
            leakage::star_from_pairs(&pairs, split)
        }
    };
    let star_h: Vec<f64> = (0..n).map(|k| star_lam[k] * turns[k] * turns[k]).collect();
    let (leak, leakage_model, leak_matrix) =
        if star_h.iter().all(|&l| l > 0.0) && star_misfit < 1e-3 || n < 2 {
            let diag = (0..n)
                .map(|j| {
                    (0..n)
                        .map(|k| if j == k { star_h[j] } else { 0.0 })
                        .collect()
                })
                .collect();
            (star_h.clone(), LeakageModel::Star, diag)
        } else {
            let m = match d.leakage_method {
                LeakageMethod::Formula => leakage::coupled(&lay, n),
                LeakageMethod::Field => {
                    let g = leakage::coupled(&lay, n);
                    let gauge: Vec<f64> = (0..n)
                        .map(|j| 0.5 * g[j][j] / (turns[j] * turns[j]))
                        .collect();
                    leakage::coupled_from_pairs(&pairs, &turns, &gauge)
                }
            };
            let mut ks = Vec::new();
            for j in 0..n {
                for k in (j + 1)..n {
                    if m[j][j] > 0.0 && m[k][k] > 0.0 {
                        ks.push((j, k, m[j][k] / (m[j][j] * m[k][k]).sqrt()));
                    }
                }
            }
            warnings.push(format!(
                "leakage: the star needs {} (branches {}): compiled as coupled series leakages",
                if star_misfit >= 1e-3 {
                    format!("a {:.1}% misfit", 100.0 * star_misfit)
                } else {
                    "a negative branch".to_string()
                },
                d.windings
                    .iter()
                    .zip(&star_h)
                    .map(|(w, l)| format!("{w} {:.4} mH", l * 1e3))
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
            (
                (0..n).map(|k| m[k][k]).collect(),
                LeakageModel::Coupled(ks),
                m,
            )
        };

    // Capacitance.
    let caps = capacitances(&lay, n, &turns);
    let net = capacitance::network(&lay, n, &turns, &caps);
    let mut c_winding = vec![0.0; n];
    for (k, cw) in c_winding.iter_mut().enumerate() {
        let c = caps.self_f[k] + net.across_f[k];
        if c < 0.0 {
            warnings.push(format!(
                "capacitance: {}'s own capacitance plus its facing layers' share is {:.2} pF: compiled as 0",
                d.windings[k],
                c * 1e12
            ));
        }
        *cw = c.max(0.0);
    }

    // Magnetizing inductance in the linear limit.
    let core_spec = CoreSpec {
        material: d.core.material.value.clone(),
        area_m2: area,
        path_m: path,
        gap_m: gap,
    };
    let model = transformer_core(&d.name, &core_spec, &mat);
    let mut g = CoreDevice::new(&model).linear_conductance();
    if gap > 0.0 {
        g += gap * TESLA_PER_V / MU0;
    }
    let n_ref = turns[0];
    let magnetizing = n_ref * n_ref * area * TESLA_PER_V / g;

    // Flux density at the rating.
    let b_sat = MU0 * mat.ms_a_per_m;
    let b_peak = d.rating.as_ref().map(|r| {
        let n_r: f64 = r.windings.iter().map(|w| turns[d.winding_index(w)]).sum();
        let b = 2f64.sqrt() * r.v_rms.value / (2.0 * PI * r.f_hz.value * n_r * area);
        if let Some(lim) = &r.b_limit_t
            && b > lim.value
        {
            warnings.push(format!(
                "flux: {b:.3} T peak at {} V rms, {} Hz exceeds the limit {} T",
                r.v_rms.value, r.f_hz.value, lim.value
            ));
        }
        if b > b_sat {
            warnings.push(format!(
                "flux: {b:.3} T peak at {} V rms, {} Hz is past the material's saturation {b_sat:.3} T",
                r.v_rms.value, r.f_hz.value
            ));
        }
        b
    });

    let windings = (0..n)
        .map(|k| WindingOut {
            label: d.windings[k].clone(),
            turns: turns[k],
            ratio: turns[k] / n_ref,
            r_ohm: r_ohm[k],
            c_f: c_winding[k],
            leak_h: leak[k],
            length_m: length[k],
        })
        .collect();
    if lay.slabs.is_empty() && n > 1 {
        return err(format!("{}: no windings laid out", d.name));
    }
    Ok(Compiled {
        design: d.clone(),
        lamination: lam,
        material: d.core.material.value.clone(),
        area_m2: area,
        path_m: path,
        gap_m: gap,
        fringing,
        turns: n_ref,
        windings,
        leakage_model,
        pairs,
        pairs_formula,
        pairs_field: field_pairs,
        leak_matrix_h: leak_matrix,
        star_h,
        star_misfit,
        capacitance: caps,
        network: net,
        magnetizing_h: magnetizing,
        b_peak_t: b_peak,
        b_saturation_t: b_sat,
        copper_fill,
        layout: lay,
        warnings,
    })
}

// --- The version file ------------------------------------------------------------------

fn map(entries: Vec<(&str, Value)>) -> Value {
    Value::Map(Map(entries
        .into_iter()
        .map(|(k, v)| (k.to_string(), v))
        .collect()))
}

fn f(x: f64) -> Value {
    Value::Float(x)
}

fn s(x: &str) -> Value {
    Value::Str(x.to_string())
}

impl Compiled {
    /// Winding j's leakage with winding k shorted (H).
    pub fn short_circuit_h(&self, j: usize, k: usize) -> f64 {
        let n = self.windings[j].turns;
        n * n * self.pairs[j][k]
    }

    /// The leakage (H) of the windings `drive` in series with `shorted` in series and
    /// shorted, from the compiled leakages (what a circuit built from this version sees,
    /// the magnetizing current neglected).
    pub fn group_short_circuit_h(&self, drive: &[usize], shorted: &[usize]) -> f64 {
        let n = self.windings.len();
        let nd: f64 = drive.iter().map(|&k| self.windings[k].turns).sum();
        let ns: f64 = shorted.iter().map(|&k| self.windings[k].turns).sum();
        let mut i = vec![0.0; n];
        for &k in drive {
            i[k] += 1.0;
        }
        for &k in shorted {
            i[k] -= nd / ns;
        }
        let m = &self.leak_matrix_h;
        (0..n)
            .flat_map(|j| (0..n).map(move |k| (j, k)))
            .map(|(j, k)| m[j][k] * i[j] * i[k])
            .sum()
    }

    /// What the macro takes (the `compiled` block).
    pub fn compiled_value(&self) -> Value {
        let w = |k: usize| self.windings[k].label.as_str();
        let mut entries = vec![
            (
                "source",
                s(&format!(
                    "derived: {COMPILER} from this version's construction (the formulas: crates/varimu-components)"
                )),
            ),
            (
                "core",
                map(vec![
                    ("material", s(&self.material)),
                    ("area_m2", f(self.area_m2)),
                    ("path_m", f(self.path_m)),
                    ("gap_m", f(self.gap_m)),
                ]),
            ),
            ("turns", f(self.turns)),
            (
                "windings",
                Value::Map(Map(self
                    .windings
                    .iter()
                    .map(|x| {
                        (
                            x.label.clone(),
                            map(vec![
                                ("ratio", f(x.ratio)),
                                ("r", f(x.r_ohm)),
                                ("c", f(x.c_f)),
                                ("leak", f(x.leak_h)),
                            ]),
                        )
                    })
                    .collect())),
            ),
        ];
        if let LeakageModel::Coupled(ks) = &self.leakage_model {
            entries.push((
                "leak_couplings",
                Value::List(
                    ks.iter()
                        .map(|&(j, k, c)| {
                            map(vec![
                                ("between", Value::List(vec![s(w(j)), s(w(k))])),
                                ("k", f(c)),
                            ])
                        })
                        .collect(),
                ),
            ));
        }
        let term = |x: &Terminal| match x {
            Terminal::Dot(k) => format!("{}.dot", w(*k)),
            Terminal::Other(k) => format!("{}.other", w(*k)),
            Terminal::Shield(name) => format!("shield.{name}"),
        };
        if !self.network.caps.is_empty() {
            entries.push((
                "capacitors",
                Value::List(
                    self.network
                        .caps
                        .iter()
                        .map(|(a, b, c)| {
                            map(vec![
                                ("between", Value::List(vec![s(&term(a)), s(&term(b))])),
                                ("c", f(*c)),
                            ])
                        })
                        .collect(),
                ),
            ));
        }
        map(entries)
    }

    /// Derived figures for reading and checking (the `report` block).
    pub fn report_value(&self) -> Value {
        let n = self.windings.len();
        let w = |k: usize| self.windings[k].label.clone();
        let mut sc = Vec::new();
        for j in 0..n {
            for k in 0..n {
                if j != k {
                    sc.push((
                        format!("{} ({} shorted)", w(j), w(k)),
                        f(self.short_circuit_h(j, k)),
                    ));
                }
            }
        }
        let per_winding = Value::Map(Map((0..n)
            .map(|k| {
                let x = &self.windings[k];
                (
                    x.label.clone(),
                    map(vec![
                        ("turns", f(x.turns)),
                        ("copper_m", f(x.length_m)),
                        ("dcr_ohm", f(x.r_ohm)),
                        ("magnetizing_h", f(self.magnetizing_h * x.ratio * x.ratio)),
                        ("star_leak_h", f(self.star_h[k])),
                        ("self_c_f", f(x.c_f)),
                    ]),
                )
            })
            .collect()));
        let lay = &self.layout;
        let method = match self.design.leakage_method {
            LeakageMethod::Formula => "formula",
            LeakageMethod::Field => "field",
        };
        let mut entries = vec![
            ("windings", per_winding),
            ("leakage_method", s(method)),
            ("short_circuit_h", Value::Map(Map(sc))),
            (
                "core",
                map({
                    let mut e = vec![
                        ("area_m2", f(self.area_m2)),
                        ("path_m", f(self.path_m)),
                        ("gap_m", f(self.gap_m)),
                        ("saturation_t", f(self.b_saturation_t)),
                    ];
                    if let Some(fr) = self.fringing {
                        e.push(("fringing", f(fr)));
                    }
                    e
                }),
            ),
            (
                "window",
                map(vec![
                    ("traverse_m", f(lay.traverse_m)),
                    ("extent_m", f(lay.extent_m())),
                    ("window_width_m", f(lay.window_width_m)),
                    ("field_length_m", f(lay.field_length_m)),
                    ("copper_fill", f(self.copper_fill)),
                ]),
            ),
        ];
        if self.pairs_field.is_some() {
            let mut f1 = Vec::new();
            for j in 0..n {
                for k in 0..n {
                    if j != k {
                        let nj = self.windings[j].turns;
                        f1.push((
                            format!("{} ({} shorted)", w(j), w(k)),
                            f(nj * nj * self.pairs_formula[j][k]),
                        ));
                    }
                }
            }
            entries.push(("short_circuit_formula_h", Value::Map(Map(f1))));
        }
        if let (Some(b), Some(r)) = (self.b_peak_t, &self.design.rating) {
            entries.push((
                "flux",
                map(vec![
                    (
                        "windings",
                        Value::List(r.windings.iter().map(|x| s(x)).collect()),
                    ),
                    ("v_rms", f(r.v_rms.value)),
                    ("f_hz", f(r.f_hz.value)),
                    ("b_peak_t", f(b)),
                ]),
            ));
        }
        let facing: Vec<Value> = self
            .capacitance
            .between
            .iter()
            .map(|b| {
                map(vec![
                    ("between", Value::List(vec![s(&w(b.a)), s(&w(b.b))])),
                    (
                        "sections",
                        Value::List(vec![
                            Value::Int(b.sections.0 as i64),
                            Value::Int(b.sections.1 as i64),
                        ]),
                    ),
                    ("c_f", f(b.c_f)),
                ])
            })
            .chain(self.capacitance.to_shields.iter().map(|x| {
                map(vec![
                    (
                        "between",
                        Value::List(vec![s(&w(x.winding)), s(&format!("shield.{}", x.shield))]),
                    ),
                    (
                        "sections",
                        Value::List(vec![
                            Value::Int(x.sections.0 as i64),
                            Value::Int(x.sections.1 as i64),
                        ]),
                    ),
                    ("c_f", f(x.c_f)),
                ])
            }))
            .collect();
        entries.push(("facing_capacitance", Value::List(facing)));
        entries.push((
            "warnings",
            Value::List(self.warnings.iter().map(|x| s(x)).collect()),
        ));
        map(entries)
    }

    /// The table rows and material the design used (the `resolved` block).
    pub fn resolved_value(&self, tables: &Tables, config_dir: &Path) -> Result<Value, Error> {
        let l = &self.lamination;
        let mut wires = Vec::new();
        let mut diel = Vec::new();
        let mut add_diel = |name: &str| -> Result<(), Error> {
            if !diel.iter().any(|(k, _)| k == name) {
                let x = tables.dielectric(name)?;
                diel.push((
                    name.to_string(),
                    map(vec![("eps_r", f(x.eps_r)), ("source", s(&x.source))]),
                ));
            }
            Ok(())
        };
        for sec in &self.design.sections {
            match sec {
                Section::Winding(ws) => {
                    if !wires
                        .iter()
                        .any(|(k, _): &(String, Value)| *k == ws.wire.value)
                    {
                        let x = tables.wire(&ws.wire.value)?;
                        wires.push((
                            ws.wire.value.clone(),
                            map(vec![
                                ("bare_m", f(x.bare_m)),
                                ("overall_m", f(x.overall_m)),
                                ("source", s(&x.source)),
                            ]),
                        ));
                    }
                    add_diel(&ws.enamel.value)?;
                    if let Some(i) = &ws.interlayer {
                        add_diel(&i.dielectric.value)?;
                    }
                }
                Section::Insulation(i) => add_diel(&i.dielectric.value)?,
                Section::Shield(_) => {}
            }
        }
        let c = tables.copper()?;
        Ok(map(vec![
            (
                "lamination",
                map(vec![
                    ("name", s(&l.name)),
                    ("shape", s(if l.shape == Shape::Ei { "EI" } else { "UI" })),
                    ("leg_m", f(l.leg_m)),
                    ("window_width_m", f(l.window_width_m)),
                    ("window_height_m", f(l.window_height_m)),
                    ("path_m", f(l.path_m)),
                    ("path_derived", Value::Bool(l.path_derived)),
                    ("source", s(&l.source)),
                ]),
            ),
            (
                "material",
                map(vec![
                    ("name", s(&self.material)),
                    ("source", s(&material_source(config_dir, &self.material)?)),
                ]),
            ),
            (
                "copper",
                map(vec![
                    ("resistivity_ohm_m", f(c.resistivity_ohm_m)),
                    ("temperature_c", f(c.temperature_c)),
                    ("source", s(&c.source)),
                ]),
            ),
            ("wires", Value::Map(Map(wires))),
            ("dielectrics", Value::Map(Map(diel))),
        ]))
    }

    /// The version file: the construction as written, the table rows it resolved to,
    /// the compiled values and the report.
    pub fn version_text(
        &self,
        design_data: &Value,
        tables: &Tables,
        config_dir: &Path,
        date: &str,
    ) -> Result<String, Error> {
        let src = design_data.as_map().unwrap();
        let construction = Value::Map(Map(src
            .iter()
            .filter(|(k, _)| !matches!(*k, "name" | "kind" | "source"))
            .map(|(k, v)| (k.to_string(), v.clone()))
            .collect()));
        let mut out = format!(
            "# Compiled by {COMPILER} on {date}.\n# Don't edit by hand: edit the design and save it as a new version.\n"
        );
        for (k, v) in [
            ("name", s(&self.design.name)),
            ("kind", s("transformer")),
            ("source", s(&self.design.source)),
            ("compiler", s(COMPILER)),
            ("construction", construction),
            ("resolved", self.resolved_value(tables, config_dir)?),
            ("compiled", self.compiled_value()),
            ("report", self.report_value()),
        ] {
            match v {
                Value::Map(_) | Value::List(_) => out.push_str(&block_entry(k, &v)),
                _ => out.push_str(&format!("{k}: {}", flow_scalar(&v))),
            }
            out.push('\n');
        }
        Ok(out)
    }
}

/// Reads and compiles a design file.
pub fn compile_file(path: &Path, config_dir: &Path) -> Result<(Value, Tables, Compiled), Error> {
    let data = yaml::load(path)?;
    let design = Design::parse(&data)?;
    let tables = Tables::load(config_dir)?;
    let lib = Library::new(config_dir);
    let c = compile(&design, &tables, &lib)?;
    Ok((data, tables, c))
}
