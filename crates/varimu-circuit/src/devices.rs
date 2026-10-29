//! Device files (component versions, config/components/<name>/<N>.yaml: `versions`) as
//! IR device models, and core materials
//! (config/magnetics.yaml): the load path of `varimu/devices/library.py` and
//! `varimu/devices/core.py` (fitting stays Python).
//!
//! The 6386's plate model is its pitch distribution discretized into sections
//! (`PitchDistribution.sections` in `varimu/devices/fit.py`), computed here in
//! numpy's order of operations, its pairwise sum included.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use circuitsim::ir::{
    DeviceModel, GridCurrent, JunctionDiode, KorenPentode, KorenTriode, Pentode, PlateModel,
    Triode, VacuumDiode, VariMuTriode,
};

use crate::speaker::{self, Speaker};
use crate::yaml::{self, Map, Value};
use crate::{Error, versions};

/// A core material's Jiles-Atherton fields and lamination (config/magnetics.yaml).
#[derive(Debug, Clone, PartialEq)]
pub struct Material {
    pub ms_a_per_m: f64,
    pub a_a_per_m: f64,
    pub k_a_per_m: f64,
    pub c: f64,
    pub alpha: f64,
    pub lamination_m: Option<f64>,
    pub resistivity_ohm_m: Option<f64>,
}

/// The config directory's device files and materials, each file read once.
pub struct Library {
    config_dir: PathBuf,
    devices: Mutex<HashMap<String, DeviceModel>>,
    speakers: Mutex<HashMap<String, Speaker>>,
    materials: Mutex<Option<HashMap<String, Material>>>,
}

impl Library {
    pub fn new(config_dir: impl Into<PathBuf>) -> Library {
        Library {
            config_dir: config_dir.into(),
            devices: Mutex::new(HashMap::new()),
            speakers: Mutex::new(HashMap::new()),
            materials: Mutex::new(None),
        }
    }

    pub fn config_dir(&self) -> &Path {
        &self.config_dir
    }

    /// Where the component versions are (config/components).
    pub fn components_dir(&self) -> PathBuf {
        self.config_dir.join("components")
    }

    /// The model of device file `name` (`NAME@N`, or `NAME` for its latest version),
    /// checked against versions.lock.
    pub fn device(&self, name: &str) -> Result<DeviceModel, Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(m) = self.devices.lock().unwrap().get(&key) {
            return Ok(m.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let model = load_device(&yaml::parse(&text, name)?, name)?;
        self.devices.lock().unwrap().insert(key, model.clone());
        Ok(model)
    }

    /// Speaker component `name` (`NAME@N`, or `NAME` for its latest version), checked
    /// against versions.lock (`load_speaker` in library.py).
    pub fn speaker(&self, name: &str) -> Result<Speaker, Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(s) = self.speakers.lock().unwrap().get(&key) {
            return Ok(s.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let s = speaker::from_data(&yaml::parse(&text, name)?, name)?;
        self.speakers.lock().unwrap().insert(key, s.clone());
        Ok(s)
    }

    pub fn material(&self, name: &str) -> Result<Material, Error> {
        let mut cache = self.materials.lock().unwrap();
        if cache.is_none() {
            *cache = Some(load_materials(&self.config_dir.join("magnetics.yaml"))?);
        }
        cache
            .as_ref()
            .unwrap()
            .get(name)
            .cloned()
            .ok_or_else(|| Error(format!("unknown core material '{name}'")))
    }
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

fn grid(d: &Map, what: &str) -> Result<Option<GridCurrent>, Error> {
    match d.get("grid_current") {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Map(g)) => Ok(Some(GridCurrent {
            perveance: num(g, "perveance", what)?,
            contact_v: num(g, "contact_v", what)?,
            smooth_v: num(g, "smooth_v", what)?,
        })),
        Some(_) => Err(Error(format!("{what}: grid_current must be a mapping"))),
    }
}

fn load_device(data: &Value, what: &str) -> Result<DeviceModel, Error> {
    let d = data
        .as_map()
        .ok_or_else(|| Error(format!("{what}: not a mapping")))?;
    let name = d
        .get("name")
        .map(Value::py_str)
        .ok_or_else(|| Error(format!("{what}: needs `name`")))?;
    let kind = d.get("kind").and_then(Value::as_str).unwrap_or("");
    Ok(match kind {
        "triode" => {
            let p = sub(d, "plate", what)?;
            let plate = match p.get("model").and_then(Value::as_str) {
                Some("koren") => PlateModel::Koren(KorenTriode {
                    mu: num(p, "mu", what)?,
                    ex: num(p, "ex", what)?,
                    kg1: num(p, "kg1", what)?,
                    kp: num(p, "kp", what)?,
                    kvb: num(p, "kvb", what)?,
                }),
                Some("varimu") => {
                    let pd = sub(p, "pitch_distribution", what)?;
                    let coeffs = pd
                        .get("coeffs")
                        .and_then(Value::as_list)
                        .ok_or_else(|| Error(format!("{what}: needs coeffs")))?
                        .iter()
                        .map(|c| {
                            c.as_f64()
                                .ok_or_else(|| Error(format!("{what}: coeffs must be numbers")))
                        })
                        .collect::<Result<Vec<_>, _>>()?;
                    let n = num(pd, "n_sections", what)?;
                    let (mus, weights) = pitch_sections(
                        num(pd, "u_min", what)?,
                        num(pd, "u_span", what)?,
                        &coeffs,
                        n as usize,
                    );
                    PlateModel::VariMu(VariMuTriode {
                        mus,
                        weights,
                        ex: num(p, "ex", what)?,
                        kg1: num(p, "kg1", what)?,
                        kp: num(p, "kp", what)?,
                        kvb: num(p, "kvb", what)?,
                    })
                }
                other => {
                    return Err(Error(format!("{what}: unknown plate model {other:?}")));
                }
            };
            let c = sub(d, "capacitances_f", what)?;
            DeviceModel::Triode(Triode {
                name,
                plate,
                grid: grid(d, what)?,
                c_gk: num(c, "gk", what)?,
                c_gp: num(c, "gp", what)?,
                c_pk: num(c, "pk", what)?,
            })
        }
        "pentode" => {
            let p = sub(d, "model", what)?;
            let c = sub(d, "capacitances_f", what)?;
            DeviceModel::Pentode(Pentode {
                name,
                model: KorenPentode {
                    mu: num(p, "mu", what)?,
                    ex: num(p, "ex", what)?,
                    kg1: num(p, "kg1", what)?,
                    kg2: num(p, "kg2", what)?,
                    kp: num(p, "kp", what)?,
                    kvb: num(p, "kvb", what)?,
                },
                grid: grid(d, what)?,
                c_g1k: num(c, "g1k", what)?,
                c_g1p: num(c, "g1p", what)?,
                c_pk: num(c, "pk", what)?,
            })
        }
        "junction_diode" => DeviceModel::JunctionDiode(JunctionDiode {
            name,
            is_a: num(d, "is_a", what)?,
            n: num(d, "n", what)?,
            rs_ohm: num(d, "rs_ohm", what)?,
        }),
        "vacuum_diode" => DeviceModel::VacuumDiode(VacuumDiode {
            name,
            perveance: num(d, "perveance", what)?,
            smooth_v: if d.contains("smooth_v") {
                num(d, "smooth_v", what)?
            } else {
                0.1
            },
        }),
        other => return Err(Error(format!("{what}: unknown device kind '{other}'"))),
    })
}

/// `PitchDistribution(u_min, u_span, coeffs, n).sections()`: the sections' mu and
/// cathode share, in numpy's order of operations.
pub fn pitch_sections(u_min: f64, u_span: f64, coeffs: &[f64], n: usize) -> (Vec<f64>, Vec<f64>) {
    let nf = n as f64;
    let t: Vec<f64> = (0..n).map(|i| (i as f64 + 0.5) / nf).collect();
    // lw = sum(c * t ** (k + 1)): Python's sum from 0; numpy squares by multiplying and
    // passes t ** 1 through.
    let mut lw = vec![0.0; n];
    for (k, &c) in coeffs.iter().enumerate() {
        for (l, &ti) in lw.iter_mut().zip(&t) {
            let p = match k + 1 {
                1 => ti,
                2 => ti * ti,
                e => ti.powf(e as f64),
            };
            *l += c * p;
        }
    }
    let max = lw.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let w: Vec<f64> = lw.iter().map(|l| (l - max).exp()).collect();
    let total = pairwise_sum(&w);
    let weights = w.iter().map(|x| x / total).collect();
    let mus = t.iter().map(|ti| 1.0 / (u_min + ti * u_span)).collect();
    (mus, weights)
}

/// numpy's pairwise summation of a contiguous float64 array (`np.add.reduce`).
pub fn pairwise_sum(a: &[f64]) -> f64 {
    const BLOCK: usize = 128;
    let n = a.len();
    if n < 8 {
        let mut res = 0.0;
        for &x in a {
            res += x;
        }
        res
    } else if n <= BLOCK {
        let mut r = [0.0; 8];
        r.copy_from_slice(&a[..8]);
        let mut i = 8;
        while i < n - (n % 8) {
            for (j, rj) in r.iter_mut().enumerate() {
                *rj += a[i + j];
            }
            i += 8;
        }
        let mut res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for &x in &a[i..] {
            res += x;
        }
        res
    } else {
        let mut n2 = n / 2;
        n2 -= n2 % 8;
        pairwise_sum(&a[..n2]) + pairwise_sum(&a[n2..])
    }
}

fn load_materials(path: &Path) -> Result<HashMap<String, Material>, Error> {
    let data = yaml::load(path)?;
    let what = path.display().to_string();
    let mats = data
        .as_map()
        .and_then(|m| m.get("materials"))
        .and_then(Value::as_map)
        .ok_or_else(|| Error(format!("{what}: needs `materials`")))?;
    let mut out = HashMap::new();
    for (name, m) in mats.iter() {
        let m = m
            .as_map()
            .ok_or_else(|| Error(format!("{what}: material {name} is not a mapping")))?;
        let w = format!("{what}: material {name}");
        if !m.contains("source") {
            return Err(Error(format!("{w} lacks ['source']")));
        }
        let opt = |k: &str| m.get(k).and_then(Value::as_f64);
        out.insert(
            name.to_string(),
            Material {
                ms_a_per_m: num(m, "ms_a_per_m", &w)?,
                a_a_per_m: num(m, "a_a_per_m", &w)?,
                k_a_per_m: num(m, "k_a_per_m", &w)?,
                c: num(m, "c", &w)?,
                alpha: num(m, "alpha", &w)?,
                lamination_m: opt("lamination_m"),
                resistivity_ohm_m: opt("resistivity_ohm_m"),
            },
        );
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::pairwise_sum;

    #[test]
    fn pairwise_matches_the_blocked_order() {
        let a: Vec<f64> = (0..32).map(|i| 1.0 / (i as f64 + 1.0)).collect();
        let r: Vec<f64> = (0..8)
            .map(|j| a[j] + a[j + 8] + a[j + 16] + a[j + 24])
            .collect();
        let want = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        assert_eq!(pairwise_sum(&a).to_bits(), want.to_bits());
        assert_eq!(pairwise_sum(&[1.0, 2.0, 3.0]), 6.0);
    }
}
