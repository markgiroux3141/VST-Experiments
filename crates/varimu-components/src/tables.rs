//! The sourced tables a design draws from (`config/transformer/`):
//!
//! - `laminations.yaml`: lamination sizes in groups, one group per source table, the
//!   dimensions as the table prints them (`unit: inch | mm`): the wound leg's width
//!   (`leg`), the window (`window_width`, from the wound leg to the outer leg or the other
//!   leg; `window_height`, between the yokes), and the magnetic path length (`path`) when
//!   the table gives one; else it is derived from the overall `width` and `height` (the
//!   mean path through the legs' and yokes' middles, [`Lamination::derived_path_m`]);
//! - `wire.yaml`: copper's resistivity, the AWG bare diameter formula and overall
//!   (insulated) diameters by build, metric wire's overall diameters by grade;
//! - `dielectrics.yaml`: relative permittivities.
//!
//! A table row keeps its group's source, so a compiled version can name it.

use std::collections::BTreeMap;
use std::path::Path;

use varimu_circuit::yaml::{self, Map, Value};

use crate::sourced::{get, map, number, only, text};
use crate::{Error, err};

pub const INCH_M: f64 = 0.0254;

/// Lamination shape: EI (the wound centre leg between two windows; the outer legs carry
/// half the flux each) or UI (two legs, one window).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Shape {
    Ei,
    Ui,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Lamination {
    pub name: String,
    pub shape: Shape,
    /// The wound leg's width (the centre tongue of an EI).
    pub leg_m: f64,
    /// From the wound leg to the next leg.
    pub window_width_m: f64,
    /// Between the yokes.
    pub window_height_m: f64,
    /// The magnetic path length.
    pub path_m: f64,
    /// True when `path_m` was derived from the overall dimensions (the table gives none).
    pub path_derived: bool,
    pub source: String,
}

impl Lamination {
    /// The mean magnetic path through the middles of the legs and yokes: for an EI one
    /// window's loop (the centre leg's half, the outer leg, the yokes), for a UI the loop
    /// through both legs. A scrapless EI (leg a: window a/2 x 3a/2, 3a x 5a/2 overall)
    /// gives 6a.
    pub fn derived_path_m(
        shape: Shape,
        leg: f64,
        window_width: f64,
        window_height: f64,
        width: f64,
        height: f64,
    ) -> f64 {
        let yoke = 0.5 * (height - window_height);
        match shape {
            Shape::Ei => {
                let outer = 0.5 * (width - leg - 2.0 * window_width);
                2.0 * (window_width + 0.25 * leg + 0.5 * outer) + 2.0 * (window_height + yoke)
            }
            Shape::Ui => {
                let other = width - leg - window_width;
                2.0 * (window_width + 0.5 * leg + 0.5 * other) + 2.0 * (window_height + yoke)
            }
        }
    }
}

/// A wire: its bare copper diameter and its overall diameter over the enamel.
#[derive(Debug, Clone, PartialEq)]
pub struct Wire {
    pub name: String,
    pub bare_m: f64,
    pub overall_m: f64,
    pub source: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Copper {
    /// At `temperature_c`.
    pub resistivity_ohm_m: f64,
    pub temperature_c: f64,
    pub source: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Dielectric {
    pub name: String,
    pub eps_r: f64,
    pub source: String,
}

/// Overall diameters of one wire size by insulation build (or grade): (min, nominal,
/// max) in metres, the nominal the middle of the range when the table prints none.
type Builds = BTreeMap<String, (f64, f64, f64)>;

#[derive(Debug, Clone, Default)]
pub struct Tables {
    pub laminations: BTreeMap<String, Lamination>,
    pub copper: Option<Copper>,
    awg_bare_source: String,
    awg: BTreeMap<u32, Builds>,
    awg_source: String,
    metric: BTreeMap<String, Builds>,
    metric_source: String,
    pub dielectrics: BTreeMap<String, Dielectric>,
}

fn unit_m(unit: &str, what: &str) -> Result<f64, Error> {
    match unit {
        "inch" => Ok(INCH_M),
        "mm" => Ok(1e-3),
        "m" => Ok(1.0),
        _ => err(format!("{what}: unit is inch, mm or m (got {unit})")),
    }
}

fn builds(v: &Value, scale: f64, what: &str) -> Result<Builds, Error> {
    let mut out = Builds::new();
    for (k, r) in map(v, what)?.iter() {
        let w = format!("{what}.{k}");
        let xs: Vec<f64> = r
            .as_list()
            .ok_or_else(|| Error(format!("{w}: [min, max] or [min, nominal, max]")))?
            .iter()
            .map(|x| number(x, &w).map(|x| x * scale))
            .collect::<Result<_, _>>()?;
        let t = match xs[..] {
            [lo, hi] => (lo, 0.5 * (lo + hi), hi),
            [lo, nom, hi] => (lo, nom, hi),
            _ => return err(format!("{w}: [min, max] or [min, nominal, max]")),
        };
        if !(t.0 > 0.0 && t.0 <= t.1 && t.1 <= t.2) {
            return err(format!("{w}: needs 0 < min <= nominal <= max"));
        }
        out.insert(k.to_string(), t);
    }
    Ok(out)
}

impl Tables {
    /// Reads `<config>/transformer/{laminations,wire,dielectrics}.yaml`.
    pub fn load(config_dir: &Path) -> Result<Tables, Error> {
        let dir = config_dir.join("transformer");
        let mut t = Tables::default();
        t.read_laminations(
            &yaml::load(&dir.join("laminations.yaml"))?,
            "laminations.yaml",
        )?;
        t.read_wire(&yaml::load(&dir.join("wire.yaml"))?, "wire.yaml")?;
        t.read_dielectrics(
            &yaml::load(&dir.join("dielectrics.yaml"))?,
            "dielectrics.yaml",
        )?;
        Ok(t)
    }

    fn read_laminations(&mut self, data: &Value, what: &str) -> Result<(), Error> {
        let groups = get(map(data, what)?, "groups", what)?
            .as_list()
            .ok_or_else(|| Error(format!("{what}: groups is a list")))?;
        for (i, g) in groups.iter().enumerate() {
            let gw = format!("{what}: groups[{i}]");
            let g = map(g, &gw)?;
            only(g, &["source", "unit", "shape", "sizes", "notes"], &gw)?;
            let source = text(get(g, "source", &gw)?, &gw)?;
            let scale = unit_m(&text(get(g, "unit", &gw)?, &gw)?, &gw)?;
            let shape = match text(get(g, "shape", &gw)?, &gw)?.as_str() {
                "EI" => Shape::Ei,
                "UI" => Shape::Ui,
                s => return err(format!("{gw}: shape is EI or UI (got {s})")),
            };
            for (name, row) in map(get(g, "sizes", &gw)?, &gw)?.iter() {
                let rw = format!("{gw}.{name}");
                let r = map(row, &rw)?;
                only(
                    r,
                    &[
                        "leg",
                        "window_width",
                        "window_height",
                        "path",
                        "width",
                        "height",
                    ],
                    &rw,
                )?;
                let n = |k: &str| -> Result<Option<f64>, Error> {
                    r.get(k)
                        .map(|v| number(v, &format!("{rw}.{k}")).map(|x| x * scale))
                        .transpose()
                };
                let need = |k: &str| -> Result<f64, Error> {
                    n(k)?.ok_or_else(|| Error(format!("{rw}: needs `{k}`")))
                };
                let (leg, ww, wh) = (need("leg")?, need("window_width")?, need("window_height")?);
                let (path, derived) = match n("path")? {
                    Some(p) => (p, false),
                    None => match (n("width")?, n("height")?) {
                        (Some(w), Some(h)) => {
                            (Lamination::derived_path_m(shape, leg, ww, wh, w, h), true)
                        }
                        _ => {
                            return err(format!(
                                "{rw}: needs `path`, or the overall `width` and `height` to derive it"
                            ));
                        }
                    },
                };
                if self.laminations.contains_key(name) {
                    return err(format!("{rw}: {name} is in two groups"));
                }
                self.laminations.insert(
                    name.to_string(),
                    Lamination {
                        name: name.to_string(),
                        shape,
                        leg_m: leg,
                        window_width_m: ww,
                        window_height_m: wh,
                        path_m: path,
                        path_derived: derived,
                        source: source.clone(),
                    },
                );
            }
        }
        Ok(())
    }

    fn read_wire(&mut self, data: &Value, what: &str) -> Result<(), Error> {
        let m = map(data, what)?;
        only(m, &["copper", "awg", "metric"], what)?;
        let c = map(get(m, "copper", what)?, &format!("{what}: copper"))?;
        let cw = format!("{what}: copper");
        self.copper = Some(Copper {
            resistivity_ohm_m: number(get(c, "resistivity_ohm_m", &cw)?, &cw)?,
            temperature_c: number(get(c, "temperature_c", &cw)?, &cw)?,
            source: text(get(c, "source", &cw)?, &cw)?,
        });
        let aw = format!("{what}: awg");
        let a = map(get(m, "awg", what)?, &aw)?;
        only(a, &["bare_source", "source", "unit", "overall"], &aw)?;
        self.awg_bare_source = text(get(a, "bare_source", &aw)?, &aw)?;
        self.awg_source = text(get(a, "source", &aw)?, &aw)?;
        let scale = unit_m(&text(get(a, "unit", &aw)?, &aw)?, &aw)?;
        for (k, v) in map(get(a, "overall", &aw)?, &aw)?.iter() {
            let n: u32 = k
                .parse()
                .map_err(|_| Error(format!("{aw}: {k} is not a gauge number")))?;
            self.awg.insert(n, builds(v, scale, &format!("{aw}.{k}"))?);
        }
        let mw = format!("{what}: metric");
        let mt = map(get(m, "metric", what)?, &mw)?;
        only(mt, &["source", "unit", "overall"], &mw)?;
        self.metric_source = text(get(mt, "source", &mw)?, &mw)?;
        let scale = unit_m(&text(get(mt, "unit", &mw)?, &mw)?, &mw)?;
        for (k, v) in map(get(mt, "overall", &mw)?, &mw)?.iter() {
            k.parse::<f64>()
                .map_err(|_| Error(format!("{mw}: {k} is not a diameter")))?;
            self.metric
                .insert(k.to_string(), builds(v, scale, &format!("{mw}.{k}"))?);
        }
        Ok(())
    }

    fn read_dielectrics(&mut self, data: &Value, what: &str) -> Result<(), Error> {
        let d = get(map(data, what)?, "dielectrics", what)?;
        for (name, row) in map(d, what)?.iter() {
            let rw = format!("{what}: {name}");
            let r: &Map = map(row, &rw)?;
            only(r, &["eps_r", "source", "notes"], &rw)?;
            let eps_r = number(get(r, "eps_r", &rw)?, &rw)?;
            if eps_r < 1.0 {
                return err(format!("{rw}: eps_r must be >= 1"));
            }
            self.dielectrics.insert(
                name.to_string(),
                Dielectric {
                    name: name.to_string(),
                    eps_r,
                    source: text(get(r, "source", &rw)?, &rw)?,
                },
            );
        }
        Ok(())
    }

    pub fn lamination(&self, name: &str) -> Result<&Lamination, Error> {
        self.laminations.get(name).ok_or_else(|| {
            Error(format!(
                "no lamination '{name}' in config/transformer/laminations.yaml (have: {})",
                self.laminations
                    .keys()
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(", ")
            ))
        })
    }

    pub fn dielectric(&self, name: &str) -> Result<&Dielectric, Error> {
        self.dielectrics.get(name).ok_or_else(|| {
            Error(format!(
                "no dielectric '{name}' in config/transformer/dielectrics.yaml (have: {})",
                self.dielectrics
                    .keys()
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(", ")
            ))
        })
    }

    pub fn copper(&self) -> Result<&Copper, Error> {
        self.copper
            .as_ref()
            .ok_or_else(|| Error("wire.yaml: no copper block".into()))
    }

    /// AWG n's bare diameter (ASTM B258's definition: 0.005 in x 92^((36 - n) / 39)).
    pub fn awg_bare_m(n: u32) -> f64 {
        0.005 * INCH_M * 92f64.powf((36.0 - f64::from(n)) / 39.0)
    }

    /// Every wire code the tables hold, AWG from thick to thin, then metric from thick to
    /// thin (what the Components view offers).
    pub fn wire_codes(&self) -> Vec<String> {
        let mut out = Vec::new();
        for (n, row) in &self.awg {
            for b in row.keys() {
                out.push(format!("AWG {n} {b}"));
            }
        }
        let mut metric: Vec<(&String, &Builds)> = self.metric.iter().collect();
        metric.sort_by(|a, b| {
            let d = |k: &str| k.parse::<f64>().unwrap_or(0.0);
            d(b.0).total_cmp(&d(a.0))
        });
        for (d, row) in metric {
            for g in row.keys() {
                if let Some(g) = g.strip_prefix("grade") {
                    out.push(format!("{d} mm grade {g}"));
                }
            }
        }
        out.retain(|c| self.wire(c).is_ok());
        out
    }

    /// A wire by its code: `AWG <n> <build>` (`AWG 32 heavy`) or `<d> mm grade <g>`
    /// (`0.13 mm grade 1`), its overall diameter the table's nominal.
    pub fn wire(&self, code: &str) -> Result<Wire, Error> {
        let words: Vec<&str> = code.split_whitespace().collect();
        let bad = || {
            Error(format!(
                "wire '{code}': `AWG <n> <build>` (e.g. AWG 32 heavy) or `<d> mm grade <g>` (e.g. 0.13 mm grade 1)"
            ))
        };
        match words[..] {
            ["AWG", n, build] => {
                let n: u32 = n.parse().map_err(|_| bad())?;
                let row = self.awg.get(&n).ok_or_else(|| {
                    Error(format!("wire '{code}': AWG {n} isn't in wire.yaml's table"))
                })?;
                let &(_, nom, _) = row.get(build).ok_or_else(|| {
                    Error(format!(
                        "wire '{code}': AWG {n} has builds {}",
                        row.keys().cloned().collect::<Vec<_>>().join(", ")
                    ))
                })?;
                Ok(Wire {
                    name: code.to_string(),
                    bare_m: Self::awg_bare_m(n),
                    overall_m: nom,
                    source: format!(
                        "bare: {}; overall ({build}, nominal): {}",
                        self.awg_bare_source, self.awg_source
                    ),
                })
            }
            [d, "mm", "grade", g] => {
                let bare = d.parse::<f64>().map_err(|_| bad())? * 1e-3;
                let row = self
                    .metric
                    .iter()
                    .find(|(k, _)| (k.parse::<f64>().unwrap() * 1e-3 - bare).abs() < 1e-9)
                    .map(|(_, r)| r)
                    .ok_or_else(|| {
                        Error(format!(
                            "wire '{code}': {d} mm isn't in wire.yaml's metric table"
                        ))
                    })?;
                let key = format!("grade{g}");
                let &(_, nom, _) = row.get(&key).ok_or_else(|| {
                    Error(format!(
                        "wire '{code}': {d} mm has {}",
                        row.keys().cloned().collect::<Vec<_>>().join(", ")
                    ))
                })?;
                Ok(Wire {
                    name: code.to_string(),
                    bare_m: bare,
                    overall_m: nom,
                    source: format!(
                        "bare: nominal {d} mm; overall (grade {g}, nominal): {}",
                        self.metric_source
                    ),
                })
            }
            _ => Err(bad()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn awg_follows_its_definition() {
        // ASTM B258: AWG 36 is 0.005 in, AWG 0000 (n = -3) 0.46 in; every 6 gauges ~halve.
        assert!((Tables::awg_bare_m(36) - 0.127e-3).abs() < 1e-12);
        let r = Tables::awg_bare_m(30) / Tables::awg_bare_m(36);
        assert!((r - 92f64.powf(6.0 / 39.0)).abs() < 1e-12);
    }

    #[test]
    fn a_scrapless_ei_path_is_six_tongues() {
        let a = 0.02;
        let p = Lamination::derived_path_m(Shape::Ei, a, a / 2.0, 1.5 * a, 3.0 * a, 2.5 * a);
        assert!((p - 6.0 * a).abs() < 1e-15);
    }
}
