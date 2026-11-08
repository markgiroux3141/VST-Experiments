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
    Bjt, Contact, DeviceModel, GridCurrent, Jfet, JfetPolarity, JunctionDiode, KorenPentode,
    KorenTriode, Lamp, Optocoupler, Pentode, PlateModel, Polarity, ScreenLaw, Thyratron, Triode,
    VacuumDiode, VariMuTriode,
};

use crate::capsule::{self, Capsule, DualCapsule};
use crate::moving_coil::{self, MovingCoil};
use crate::plate::{self, PlateComponent};
use crate::speaker::{self, Speaker};
use crate::spring::{self, SpringTankComponent};
use crate::tape::{self, TapeComponent};
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
    capsules: Mutex<HashMap<String, Capsule>>,
    dual_capsules: Mutex<HashMap<String, DualCapsule>>,
    moving_coils: Mutex<HashMap<String, MovingCoil>>,
    plates: Mutex<HashMap<String, PlateComponent>>,
    springs: Mutex<HashMap<String, SpringTankComponent>>,
    tapes: Mutex<HashMap<String, TapeComponent>>,
    harps: Mutex<HashMap<String, std::sync::Arc<circuitsim::harp::HarpModel>>>,
    clav_strings: Mutex<HashMap<String, (String, String)>>,
    materials: Mutex<Option<HashMap<String, Material>>>,
    /// Versions not saved yet ({folder@N: data}): the Components view's design while it is
    /// edited, heard in a circuit before it is a version (docs/COMPONENT_EDITOR_PLAN.md C2).
    unsaved: Mutex<HashMap<String, Value>>,
}

impl Library {
    pub fn new(config_dir: impl Into<PathBuf>) -> Library {
        Library {
            config_dir: config_dir.into(),
            devices: Mutex::new(HashMap::new()),
            speakers: Mutex::new(HashMap::new()),
            capsules: Mutex::new(HashMap::new()),
            dual_capsules: Mutex::new(HashMap::new()),
            moving_coils: Mutex::new(HashMap::new()),
            plates: Mutex::new(HashMap::new()),
            springs: Mutex::new(HashMap::new()),
            tapes: Mutex::new(HashMap::new()),
            harps: Mutex::new(HashMap::new()),
            clav_strings: Mutex::new(HashMap::new()),
            materials: Mutex::new(None),
            unsaved: Mutex::new(HashMap::new()),
        }
    }

    /// Serve `data` as version `reference` (`NAME@N`) of a component, in this library only
    /// and without a file: a version that isn't saved yet (N past the saved ones; a saved
    /// version can't be shadowed). [`Library::component_data`] reads it, so a transformer
    /// part's `component:` builds from it. Nothing is written.
    pub fn add_unsaved(&self, reference: &str, data: Value) -> Result<(), Error> {
        let r = versions::parse(reference)?;
        let Some(v) = r.version else {
            return Err(Error(format!(
                "an unsaved version names its number ({reference})"
            )));
        };
        if versions::versions(&self.components_dir(), &r.name).contains(&v) {
            return Err(Error(format!(
                "{r} is saved: an unsaved version can't replace it"
            )));
        }
        let key = format!("{}@{v}", r.folder());
        self.unsaved.lock().unwrap().insert(key, data);
        Ok(())
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

    /// Capsule component `name` (`NAME@N`, or `NAME` for its latest version), checked
    /// against versions.lock (`load_capsule` in library.py).
    pub fn capsule(&self, name: &str) -> Result<Capsule, Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(c) = self.capsules.lock().unwrap().get(&key) {
            return Ok(c.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let c = capsule::from_data(&yaml::parse(&text, name)?, name)?;
        self.capsules.lock().unwrap().insert(key, c.clone());
        Ok(c)
    }

    /// Dual-diaphragm capsule component `name` (`load_dual_capsule` in library.py).
    pub fn dual_capsule(&self, name: &str) -> Result<DualCapsule, Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(c) = self.dual_capsules.lock().unwrap().get(&key) {
            return Ok(c.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let c = capsule::dual_from_data(&yaml::parse(&text, name)?, name)?;
        self.dual_capsules.lock().unwrap().insert(key, c.clone());
        Ok(c)
    }

    /// Moving-coil cartridge component `name` (`load_moving_coil` in library.py).
    pub fn moving_coil(&self, name: &str) -> Result<MovingCoil, Error> {
        self.transducer(name, "moving_coil")
    }

    /// Ribbon motor component `name`, its network in the moving-coil format
    /// (`load_ribbon_motor` in library.py).
    pub fn ribbon_motor(&self, name: &str) -> Result<MovingCoil, Error> {
        self.transducer(name, "ribbon_motor")
    }

    fn transducer(&self, name: &str, kind: &str) -> Result<MovingCoil, Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(c) = self.moving_coils.lock().unwrap().get(&key) {
            return Ok(c.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let c = moving_coil::from_data_of(&yaml::parse(&text, name)?, name, kind)?;
        self.moving_coils.lock().unwrap().insert(key, c.clone());
        Ok(c)
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

    /// Component `name`'s file as data (`NAME@N`, or `NAME` for its latest version),
    /// checked against versions.lock (`component_data` in library.py).
    /// An unsaved version ([`Library::add_unsaved`]) when `name` pins one.
    pub fn component_data(&self, name: &str) -> Result<Value, Error> {
        let root = self.components_dir();
        let p = versions::parse(name)?;
        if let Some(v) = p.version {
            let key = format!("{}@{v}", p.folder());
            if let Some(d) = self.unsaved.lock().unwrap().get(&key) {
                return Ok(d.clone());
            }
        }
        let r = versions::resolve(&root, &p)?;
        let (_, text) = versions::read_text(&root, &r)?;
        yaml::parse(&text, name)
    }

    /// Plate component `name` (`NAME@N`, or `NAME` for its latest version), checked
    /// against versions.lock (`load_plate` in library.py).
    /// Harp component `name`'s compiled data (kind `ep_harp`; `varimu.rhodes.compile`): the
    /// file its version names, checked against the sha256 the version gives.
    pub fn harp(&self, name: &str) -> Result<std::sync::Arc<circuitsim::harp::HarpModel>, Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(h) = self.harps.lock().unwrap().get(&key) {
            return Ok(h.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let d = yaml::parse(&text, name)?;
        let d = d
            .as_map()
            .ok_or_else(|| Error(format!("{r}: not a mapping")))?;
        let kind = d.get("kind").and_then(Value::as_str);
        if kind != Some("ep_harp") {
            return Err(Error(format!("{r} is not a harp (kind {kind:?})")));
        }
        let data = d.get("data").and_then(Value::as_map);
        let field = |k: &str| {
            data.and_then(|m| m.get(k))
                .and_then(Value::as_str)
                .ok_or_else(|| Error(format!("{r}: data.{k} is missing")))
        };
        let path = root.join(r.folder()).join(field("file")?);
        let raw = std::fs::read_to_string(&path)
            .map_err(|e| Error(format!("{r}: {}: {e}", path.display())))?;
        if versions::text_hash(&raw) != field("sha256")? {
            return Err(Error(format!(
                "{r}'s data {} doesn't match the sha256 its version names",
                path.display()
            )));
        }
        let model: circuitsim::harp::HarpModel = serde_json::from_str(&raw)
            .map_err(|e| Error(format!("{r}: {}: {e}", path.display())))?;
        model.check().map_err(|e| Error(format!("{r}: {e}")))?;
        let model = std::sync::Arc::new(model);
        self.harps.lock().unwrap().insert(key, model.clone());
        Ok(model)
    }

    /// A Clavinet strings component `name` (kind `clav_strings`; `varimu.clavinet.compile`)
    /// as the IR names it: (its header's path, relative to the repository's root with
    /// forward slashes when it is inside it, else absolute; its sidecar's sha256), both
    /// files checked against the sha256s the version gives (`compile.ir_data`).
    pub fn clav_strings(&self, name: &str) -> Result<(String, String), Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(c) = self.clav_strings.lock().unwrap().get(&key) {
            return Ok(c.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let d = yaml::parse(&text, name)?;
        let d = d
            .as_map()
            .ok_or_else(|| Error(format!("{r}: not a mapping")))?;
        let kind = d.get("kind").and_then(Value::as_str);
        if kind != Some("clav_strings") {
            return Err(Error(format!(
                "{r} is not a Clavinet's strings (kind {kind:?})"
            )));
        }
        let field = |block: &str, k: &str| {
            d.get(block)
                .and_then(Value::as_map)
                .and_then(|m| m.get(k))
                .and_then(Value::as_str)
                .ok_or_else(|| Error(format!("{r}: {block}.{k} is missing")))
        };
        let folder = root.join(r.folder());
        let header = folder.join(field("data", "file")?);
        let raw = std::fs::read_to_string(&header)
            .map_err(|e| Error(format!("{r}: {}: {e}", header.display())))?;
        if versions::text_hash(&raw) != field("data", "sha256")? {
            return Err(Error(format!(
                "{r}'s data {} doesn't match the sha256 its version names",
                header.display()
            )));
        }
        let bin = folder.join(field("binary", "file")?);
        let bytes =
            std::fs::read(&bin).map_err(|e| Error(format!("{r}: {}: {e}", bin.display())))?;
        let sha = field("binary", "sha256")?.to_string();
        use sha2::Digest;
        let digest = sha2::Sha256::digest(&bytes);
        let hex: String = digest.iter().map(|b| format!("{b:02x}")).collect();
        if hex != sha {
            return Err(Error(format!(
                "{r}'s sidecar {} doesn't match the sha256 its version names",
                bin.display()
            )));
        }
        let repo = self.config_dir.join("..");
        let rel = match (header.canonicalize(), repo.canonicalize()) {
            (Ok(h), Ok(top)) => match h.strip_prefix(&top) {
                Ok(p) => p
                    .components()
                    .map(|c| c.as_os_str().to_string_lossy().into_owned())
                    .collect::<Vec<_>>()
                    .join("/"),
                Err(_) => h.to_string_lossy().into_owned(),
            },
            _ => header.to_string_lossy().into_owned(),
        };
        let out = (rel, sha);
        self.clav_strings.lock().unwrap().insert(key, out.clone());
        Ok(out)
    }

    pub fn plate(&self, name: &str) -> Result<PlateComponent, Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(p) = self.plates.lock().unwrap().get(&key) {
            return Ok(p.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let p = plate::from_data(&yaml::parse(&text, name)?, name)?;
        self.plates.lock().unwrap().insert(key, p.clone());
        Ok(p)
    }

    /// Spring tank component `name` (`NAME@N`, or `NAME` for its latest version), checked
    /// against versions.lock (`load_spring_tank` in library.py).
    pub fn spring_tank(&self, name: &str) -> Result<SpringTankComponent, Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(p) = self.springs.lock().unwrap().get(&key) {
            return Ok(p.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let p = spring::from_data(&yaml::parse(&text, name)?, name)?;
        self.springs.lock().unwrap().insert(key, p.clone());
        Ok(p)
    }

    /// Tape component `name` (`NAME@N`, or `NAME` for its latest version), checked against
    /// versions.lock (`load_tape` in library.py).
    pub fn tape(&self, name: &str) -> Result<TapeComponent, Error> {
        let root = self.components_dir();
        let r = versions::resolve(&root, &versions::parse(name)?)?;
        let key = format!("{}@{}", r.folder(), r.version.unwrap());
        if let Some(t) = self.tapes.lock().unwrap().get(&key) {
            return Ok(t.clone());
        }
        let (_, text) = versions::read_text(&root, &r)?;
        let t = tape::from_data(&yaml::parse(&text, name)?, name)?;
        self.tapes.lock().unwrap().insert(key, t.clone());
        Ok(t)
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

/// A pentode model's screen law (`varimu/devices/pentode.py`'s `screen`): absent or null,
/// Koren's.
fn screen_law(m: &Map, what: &str) -> Result<Option<ScreenLaw>, Error> {
    match m.get("screen") {
        None | Some(Value::Null) => Ok(None),
        Some(v) if v.as_str() == Some("e1") => Ok(Some(ScreenLaw::E1)),
        Some(v) => Err(Error(format!("{what}: unknown screen law {v}"))),
    }
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
                    screen: screen_law(p, what)?,
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
            tol_scale: None,
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
        "lamp" => {
            let w = sub(d, "filament", what)?;
            let e = sub(d, "emissivity", what)?;
            let c: Vec<f64> = e
                .get("coeffs")
                .and_then(Value::as_list)
                .ok_or_else(|| Error(format!("{what}: needs emissivity coeffs")))?
                .iter()
                .map(|c| {
                    c.as_f64()
                        .ok_or_else(|| Error(format!("{what}: coeffs must be numbers")))
                })
                .collect::<Result<_, _>>()?;
            let emissivity: [f64; 4] = c
                .try_into()
                .map_err(|_| Error(format!("{what}: 4 emissivity coeffs (c0..c3)")))?;
            DeviceModel::Lamp(Lamp {
                name,
                wire_d_m: num(w, "wire_d_m", what)?,
                wire_l_m: num(w, "wire_l_m", what)?,
                rad_fraction: num(w, "rad_fraction", what)?,
                emissivity,
                t_amb_k: num(d, "t_amb_k", what)?,
            })
        }
        "contact" => {
            // contact.py's contact_from_data
            let c = sub(d, "contact", what)?;
            DeviceModel::Contact(Contact {
                name,
                r_on_ohm: num(c, "r_on_ohm", what)?,
                r_off_ohm: num(c, "r_off_ohm", what)?,
                v_open_v: num(c, "v_open_v", what)?,
                v_closed_v: num(c, "v_closed_v", what)?,
            })
        }
        "optocoupler" => {
            // opto.py's opto_from_data
            let led = sub(d, "led", what)?;
            let cell = sub(d, "cell", what)?;
            DeviceModel::Optocoupler(Optocoupler {
                name,
                led_is_a: num(led, "is_a", what)?,
                led_n: num(led, "n", what)?,
                i_eta_a: num(led, "i_eta_a", what)?,
                gen_s_per_s_a: num(cell, "gen_s_per_s_a", what)?,
                tau0_s: num(cell, "tau0_s", what)?,
                kappa_s_s: num(cell, "kappa_s_s", what)?,
                g_dark_s: num(cell, "g_dark_s", what)?,
                // The state node's unit (numerics): a version's `state` block, else 1 mS / V.
                s_unit_s: match d.get("state") {
                    Some(Value::Map(st)) => match st.get("s_unit_s") {
                        Some(_) => num(st, "s_unit_s", what)?,
                        None => 1e-3,
                    },
                    _ => 1e-3,
                },
            })
        }
        "bjt" => {
            let dc = sub(d, "dc", what)?;
            let empty = Map(Vec::new());
            let par = match d.get("parasitics") {
                Some(Value::Map(m)) => m,
                _ => &empty,
            };
            // bjt.py's bjt_from_data: absent or null optional limits are infinite (None),
            // other absent values SPICE's defaults.
            let opt = |k: &str| -> Result<Option<f64>, Error> {
                match dc.get(k) {
                    None | Some(Value::Null) => Ok(None),
                    Some(_) => Ok(Some(num(dc, k, what)?)),
                }
            };
            let or = |m: &Map, k: &str, default: f64| -> Result<f64, Error> {
                if m.contains(k) {
                    num(m, k, what)
                } else {
                    Ok(default)
                }
            };
            let polarity = match d.get("polarity").and_then(Value::as_str) {
                Some("npn") => Polarity::Npn,
                Some("pnp") => Polarity::Pnp,
                _ => return Err(Error(format!("{what}: polarity must be npn or pnp"))),
            };
            DeviceModel::Bjt(Bjt {
                name,
                polarity,
                is_a: num(dc, "is_a", what)?,
                bf: num(dc, "bf", what)?,
                br: or(dc, "br", 1.0)?,
                nf: or(dc, "nf", 1.0)?,
                nr: or(dc, "nr", 1.0)?,
                vaf_v: opt("vaf_v")?,
                var_v: opt("var_v")?,
                ikf_a: opt("ikf_a")?,
                ikr_a: opt("ikr_a")?,
                ise_a: or(dc, "ise_a", 0.0)?,
                ne: or(dc, "ne", 1.5)?,
                isc_a: or(dc, "isc_a", 0.0)?,
                nc: or(dc, "nc", 2.0)?,
                rb_ohm: or(par, "rb_ohm", 0.0)?,
                rc_ohm: or(par, "rc_ohm", 0.0)?,
                re_ohm: or(par, "re_ohm", 0.0)?,
                cje_f: or(par, "cje_f", 0.0)?,
                cjc_f: or(par, "cjc_f", 0.0)?,
                temp_k: None,
                eg_ev: opt("eg_ev")?,
                xti: opt("xti")?,
                xtb: opt("xtb")?,
                tol_scale: None,
            })
        }
        "jfet" => {
            // jfet.py's jfet_from_data: absent values SPICE's defaults.
            let dc = sub(d, "dc", what)?;
            let empty = Map(Vec::new());
            let par = match d.get("parasitics") {
                Some(Value::Map(m)) => m,
                _ => &empty,
            };
            let or = |m: &Map, k: &str, default: f64| -> Result<f64, Error> {
                if m.contains(k) {
                    num(m, k, what)
                } else {
                    Ok(default)
                }
            };
            let polarity = match d.get("polarity").and_then(Value::as_str) {
                Some("njf") => JfetPolarity::Njf,
                Some("pjf") => JfetPolarity::Pjf,
                _ => return Err(Error(format!("{what}: polarity must be njf or pjf"))),
            };
            DeviceModel::Jfet(Jfet {
                name,
                polarity,
                vto_v: num(dc, "vto_v", what)?,
                beta_a_per_v2: num(dc, "beta_a_per_v2", what)?,
                lambda_per_v: or(dc, "lambda_per_v", 0.0)?,
                is_a: or(dc, "is_a", 1e-14)?,
                n: or(dc, "n", 1.0)?,
                b: or(dc, "b", 1.0)?,
                pb_v: or(dc, "pb_v", 1.0)?,
                rd_ohm: or(par, "rd_ohm", 0.0)?,
                rs_ohm: or(par, "rs_ohm", 0.0)?,
                cgs_f: or(par, "cgs_f", 0.0)?,
                cgd_f: or(par, "cgd_f", 0.0)?,
            })
        }
        "thyratron" => {
            let m = sub(d, "model", what)?;
            let c = sub(d, "capacitances_f", what)?;
            let mu_g2 = match m.get("mu_g2") {
                None | Some(Value::Null) => None,
                Some(_) => Some(num(m, "mu_g2", what)?),
            };
            DeviceModel::Thyratron(Thyratron {
                name,
                mu_a: num(m, "mu_a", what)?,
                mu_g2,
                v0_v: num(m, "v0_v", what)?,
                e_v: num(m, "e_v", what)?,
                perveance: num(m, "perveance", what)?,
                x_n: num(m, "x_n", what)?,
                v_x_v: num(m, "v_x_v", what)?,
                k_ion: num(m, "k_ion", what)?,
                v_ion_v: num(m, "v_ion_v", what)?,
                w_ion_v: num(m, "w_ion_v", what)?,
                c_meta: num(m, "c_meta", what)?,
                v_meta_v: num(m, "v_meta_v", what)?,
                w_meta_v: num(m, "w_meta_v", what)?,
                tau_diff_s: num(m, "tau_diff_s", what)?,
                k_grid: num(m, "k_grid", what)?,
                p_grid: num(m, "p_grid", what)?,
                v_float_v: num(m, "v_float_v", what)?,
                t_e_v: num(m, "t_e_v", what)?,
                q_s_c: num(m, "q_s_c", what)?,
                g_leak_s: num(m, "g_leak_s", what)?,
                s0_per_s: num(m, "s0_per_s", what)?,
                c_gk: num(c, "gk", what)?,
                c_ga: num(c, "ga", what)?,
                c_ak: num(c, "ak", what)?,
            })
        }
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
