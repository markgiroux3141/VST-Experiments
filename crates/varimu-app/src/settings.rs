//! The engine's settings per quality, read from `config/sim_settings.yaml` as
//! `varimu.sim.io.TransientSettings.from_sim_settings(engine="circuitsim", quality=...)`
//! reads them: the `circuitsim` block, then `circuitsim_draft` for draft, then
//! `circuitsim_draft_1x` for draft-1x (only the circuitsim fields; ngspice's don't apply).
//! Production is what a render uses, draft-1x what the player uses (the user's choice,
//! 2026-10-27), draft-2x what it uses for devices that clip hard (the 5E3, 2026-10-29:
//! `circuitsim_draft_2x`, the app's own quality; Python has none such).

use std::path::Path;

use circuitsim::ir::CircuitIr;
use circuitsim::partition::{self, Coupling, GROUP_BREAK};
use circuitsim::transient::ErrorNorm;
use circuitsim::{Method, Options, Solver};
use varimu_circuit::Cores;
use varimu_circuit::yaml::{self, Map, Value};

/// A quality: which blocks go on top of `circuitsim`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Quality {
    Production,
    Draft,
    Draft1x,
    /// The draft's 96 kHz internal rate behind a 48 kHz host (2x oversampling in a stream).
    Draft2x,
}

impl Quality {
    pub fn name(self) -> &'static str {
        match self {
            Quality::Production => "production",
            Quality::Draft => "draft",
            Quality::Draft1x => "draft-1x",
            Quality::Draft2x => "draft-2x",
        }
    }

    /// The quality of a [`Quality::name`].
    pub fn from_name(name: &str) -> Option<Quality> {
        [
            Quality::Production,
            Quality::Draft,
            Quality::Draft1x,
            Quality::Draft2x,
        ]
        .into_iter()
        .find(|q| q.name() == name)
    }

    fn blocks(self) -> &'static [&'static str] {
        match self {
            Quality::Production => &[],
            Quality::Draft => &["circuitsim_draft"],
            Quality::Draft1x => &["circuitsim_draft", "circuitsim_draft_1x"],
            Quality::Draft2x => &["circuitsim_draft", "circuitsim_draft_2x"],
        }
    }
}

/// circuitsim's settings at one quality (the fields of `TransientSettings` it uses).
#[derive(Debug, Clone, PartialEq)]
pub struct Settings {
    pub quality: Quality,
    /// The project's rate: files, renders and their outputs (Hz).
    pub sample_rate: u32,
    /// Circuit volts (peak) at 0 dBFS.
    pub full_scale_volts_peak: f64,
    /// Seconds run with the input held at its first sample before it starts.
    pub settle_s: f64,
    pub oversample: u32,
    pub method: String,
    pub input_order: usize,
    pub error_abstol: f64,
    pub error_reltol: f64,
    pub solver: String,
    pub newton_reltol: f64,
    pub newton_vntol: f64,
    pub newton_reuse: bool,
    pub step_selection: bool,
    pub error_norm: String,
    pub cores: String,
    pub tube_tables: bool,
    pub partition: Vec<String>,
    pub partition_coupling: String,
    /// The simulation host's rate (0: `sample_rate`).
    pub host_rate: u32,
    /// Gas thyratrons as their event kernels where a circuit has tables (technique K: the
    /// live qualities'; production renders the tube itself, M1).
    pub events: bool,
    /// A literal tape's recording kernel on the GPU in f32 (circuitsim's `gpu` feature,
    /// docs/TAPE_SPEED_PLAN.md P5: a print within ~-117 dB of the f64 CPU kernel's, ~3x
    /// faster on the 351). [`Settings::load`] turns it on at production when the app was
    /// built with the GPU kernel and a GPU is there (`VARIMU_GPU=off` keeps the CPU's, the
    /// reference); the live qualities play a reduced tape, which has no kernel. In the
    /// print cache's key with the rest of the settings.
    pub tape_gpu: bool,
}

/// Whether a literal tape's recording kernel can run on the GPU here (`tape_gpu`): the app
/// built with circuitsim's `gpu` feature, a GPU found, `VARIMU_GPU` not off. Asked once.
pub fn tape_gpu_available() -> bool {
    static AVAILABLE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *AVAILABLE.get_or_init(|| circuitsim::tape_stream::gpu_available().is_ok())
}

fn get<'a>(m: &'a Map, key: &str, block: &str) -> Result<&'a Value, String> {
    m.get(key)
        .ok_or_else(|| format!("sim_settings {block}: no `{key}`"))
}

fn num(v: &Value, key: &str) -> Result<f64, String> {
    v.as_f64()
        .ok_or_else(|| format!("sim_settings: `{key}` is not a number"))
}

fn int(v: &Value, key: &str) -> Result<i64, String> {
    match v {
        Value::Int(i) => Ok(*i),
        Value::Float(x) if x.fract() == 0.0 => Ok(*x as i64),
        _ => Err(format!("sim_settings: `{key}` is not an integer")),
    }
}

fn boolean(v: &Value, key: &str) -> Result<bool, String> {
    match v {
        Value::Bool(b) => Ok(*b),
        Value::Int(i) => Ok(*i != 0),
        _ => Err(format!("sim_settings: `{key}` is not a boolean")),
    }
}

fn string(v: &Value, key: &str) -> Result<String, String> {
    match v {
        Value::Str(s) => Ok(s.clone()),
        Value::Null => Err(format!("sim_settings: `{key}` is empty")),
        other => Ok(other.py_str()),
    }
}

impl Settings {
    /// The settings at `quality` from `<config_dir>/sim_settings.yaml`.
    pub fn load(config_dir: &Path, quality: Quality) -> Result<Settings, String> {
        let path = config_dir.join("sim_settings.yaml");
        let doc = yaml::load(&path).map_err(|e| e.to_string())?;
        let top = doc
            .as_map()
            .ok_or_else(|| format!("{}: not a mapping", path.display()))?;
        let mut s = Settings::from_map(top, quality)?;
        s.tape_gpu = quality == Quality::Production && tape_gpu_available();
        Ok(s)
    }

    pub fn from_map(top: &Map, quality: Quality) -> Result<Settings, String> {
        let block = |name: &str| -> Result<&Map, String> {
            get(top, name, "file")?
                .as_map()
                .ok_or_else(|| format!("sim_settings: `{name}` is not a mapping"))
        };
        let audio = block("audio")?;
        let cs = block("circuitsim")?;
        let devices = block("devices")?;
        let opt = |m: &Map, k: &str| m.get(k).cloned();
        let sample_rate = int(get(top, "sample_rate", "file")?, "sample_rate")?;
        let settle_s = match top.get("start").and_then(Value::as_map) {
            Some(s) => s.get("settle_s").map_or(Ok(0.0), |v| num(v, "settle_s"))?,
            None => 0.0,
        };
        let or = |v: Option<Value>, d: Value| v.unwrap_or(d);
        let mut s = Settings {
            quality,
            sample_rate: sample_rate as u32,
            full_scale_volts_peak: num(
                get(audio, "full_scale_volts_peak", "audio")?,
                "full_scale_volts_peak",
            )?,
            settle_s,
            oversample: int(get(cs, "oversample", "circuitsim")?, "oversample")? as u32,
            method: string(get(cs, "method", "circuitsim")?, "method")?,
            input_order: int(&or(opt(cs, "input_order"), Value::Int(1)), "input_order")? as usize,
            error_abstol: num(
                &or(opt(cs, "error_abstol"), Value::Float(0.0)),
                "error_abstol",
            )?,
            error_reltol: num(
                &or(opt(cs, "error_reltol"), Value::Float(0.0)),
                "error_reltol",
            )?,
            solver: string(&or(opt(cs, "solver"), Value::Str("dk".into())), "solver")?,
            newton_reltol: num(
                &or(opt(cs, "newton_reltol"), Value::Float(1e-6)),
                "newton_reltol",
            )?,
            newton_vntol: num(
                &or(opt(cs, "newton_vntol"), Value::Float(1e-6)),
                "newton_vntol",
            )?,
            newton_reuse: boolean(
                &or(opt(cs, "newton_reuse"), Value::Bool(true)),
                "newton_reuse",
            )?,
            step_selection: boolean(
                &or(opt(cs, "step_selection"), Value::Bool(true)),
                "step_selection",
            )?,
            error_norm: string(
                &or(opt(cs, "error_norm"), Value::Str("nodes".into())),
                "error_norm",
            )?,
            cores: string(&or(opt(devices, "cores"), Value::Str("ja".into())), "cores")?,
            tube_tables: false,
            partition: Vec::new(),
            partition_coupling: "extrapolate".into(),
            host_rate: 0,
            events: false,
            tape_gpu: false,
        };
        for name in quality.blocks() {
            let d = block(name)?;
            for (k, v) in d.iter() {
                match k {
                    "oversample" => s.oversample = int(v, k)? as u32,
                    "method" => s.method = string(v, k)?,
                    "input_order" => s.input_order = int(v, k)? as usize,
                    "solver" => s.solver = string(v, k)?,
                    "error_abstol" => s.error_abstol = num(v, k)?,
                    "error_reltol" => s.error_reltol = num(v, k)?,
                    "newton_reltol" => s.newton_reltol = num(v, k)?,
                    "newton_vntol" => s.newton_vntol = num(v, k)?,
                    "newton_reuse" => s.newton_reuse = boolean(v, k)?,
                    "cores" => s.cores = string(v, k)?,
                    "tube_tables" => s.tube_tables = boolean(v, k)?,
                    "partition_coupling" => s.partition_coupling = string(v, k)?,
                    "host_rate" => s.host_rate = int(v, k)? as u32,
                    "events" => s.events = boolean(v, k)?,
                    "partition" => {
                        // A title, or a list of titles: a group on a thread of its own
                        // (flattened with the group break between groups).
                        let mut flat = Vec::new();
                        for t in v
                            .as_list()
                            .ok_or("sim_settings: `partition` is not a list")?
                        {
                            match t.as_list() {
                                Some(g) => {
                                    if !flat.is_empty() {
                                        flat.push(GROUP_BREAK.to_string());
                                    }
                                    for t in g {
                                        flat.push(string(t, k)?);
                                    }
                                }
                                None => flat.push(string(t, k)?),
                            }
                        }
                        s.partition = flat;
                    }
                    _ => return Err(format!("sim_settings {name}: unknown key `{k}`")),
                }
            }
        }
        if s.oversample == 0 || s.sample_rate == 0 {
            return Err("sim_settings: sample_rate and oversample must be positive".into());
        }
        Ok(s)
    }

    /// The rate the simulation's host runs at.
    pub fn host(&self) -> u32 {
        if self.host_rate != 0 {
            self.host_rate
        } else {
            self.sample_rate
        }
    }

    /// The engine's rate: the host's times the oversampling.
    pub fn sim_rate(&self) -> u32 {
        self.host() * self.oversample
    }

    pub fn cores(&self) -> Result<Cores, String> {
        Cores::parse(&self.cores).map_err(|e| e.to_string())
    }

    pub fn coupling(&self) -> Result<Coupling, String> {
        Coupling::parse(&self.partition_coupling).map_err(|e| e.to_string())
    }

    /// The solver options `circuitsim.simulate` gets from `varimu.sim.fast.run_transient`
    /// (probes only: `all_unknowns` off).
    pub fn run_options(&self) -> Result<Options, String> {
        let d = Options::default();
        Ok(Options {
            method: Method::parse(&self.method).map_err(|e| e.to_string())?,
            solver: Solver::parse(&self.solver).map_err(|e| e.to_string())?,
            reltol: self.newton_reltol,
            vntol: self.newton_vntol,
            newton_reuse: self.newton_reuse,
            input_order: self.input_order,
            error_abstol: self.error_abstol,
            error_reltol: self.error_reltol,
            step_selection: self.step_selection,
            error_norm: ErrorNorm::parse(&self.error_norm).map_err(|e| e.to_string())?,
            tube_tables: self.tube_tables,
            all_unknowns: false,
            tape_gpu: self.tape_gpu,
            ..d
        })
    }

    /// The options `circuitsim.Stream` gets from `varimu.sim.live` (no error control).
    pub fn stream_options(&self) -> Result<Options, String> {
        let d = Options::default();
        Ok(Options {
            method: Method::parse(&self.method).map_err(|e| e.to_string())?,
            solver: Solver::parse(&self.solver).map_err(|e| e.to_string())?,
            reltol: self.newton_reltol,
            vntol: self.newton_vntol,
            input_order: self.input_order,
            newton_reuse: self.newton_reuse,
            tube_tables: self.tube_tables,
            all_unknowns: false,
            tape_gpu: self.tape_gpu,
            ..d
        })
    }

    /// The options a [`crate::live::Live`] stream runs with: the stream's at the live
    /// qualities, a render's (its local error control) at production (an event take
    /// rendered offline at production, docs/MIDI_TAKES_PLAN.md).
    pub fn live_options(&self) -> Result<Options, String> {
        match self.quality {
            Quality::Production => self.run_options(),
            _ => self.stream_options(),
        }
    }

    /// The sections of `ir` that `partition` puts on other threads: the titles the
    /// circuit has with elements in them, groups separated by the group break
    /// (`partition::GROUP_BREAK`; empty groups dropped), none if that would leave
    /// nothing else (`fast.partition_sections`). A section a switch has emptied (the
    /// tube synth's LFO turned off) gets no thread.
    pub fn partition_sections(&self, ir: &CircuitIr) -> Vec<String> {
        let titles: Vec<&str> = ir
            .sections
            .iter()
            .filter(|s| !s.elements.is_empty())
            .map(|s| s.title.as_str())
            .collect();
        let groups: Vec<Vec<String>> = partition::groups(&self.partition)
            .into_iter()
            .map(|g| {
                g.into_iter()
                    .filter(|t| titles.contains(&t.as_str()))
                    .collect::<Vec<_>>()
            })
            .filter(|g| !g.is_empty())
            .collect();
        if groups.iter().map(Vec::len).sum::<usize>() >= titles.len() {
            return Vec::new();
        }
        groups.join(&GROUP_BREAK.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config() -> std::path::PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
    }

    #[test]
    fn only_production_records_tape_on_the_gpu() {
        for q in [Quality::Draft, Quality::Draft1x, Quality::Draft2x] {
            let s = Settings::load(&config(), q).unwrap();
            assert!(!s.tape_gpu && !s.run_options().unwrap().tape_gpu);
        }
        let p = Settings::load(&config(), Quality::Production).unwrap();
        assert_eq!(p.tape_gpu, tape_gpu_available());
        assert_eq!(p.run_options().unwrap().tape_gpu, p.tape_gpu);
        // from_map alone (the settings as Python reads them) keeps the CPU's kernel.
        let doc = yaml::load(&config().join("sim_settings.yaml")).unwrap();
        let m = Settings::from_map(doc.as_map().unwrap(), Quality::Production).unwrap();
        assert!(!m.tape_gpu);
    }

    #[test]
    fn qualities_stack_like_python() {
        let p = Settings::load(&config(), Quality::Production).unwrap();
        assert_eq!((p.sample_rate, p.oversample, p.host()), (96_000, 2, 96_000));
        assert_eq!(p.method, "esdirk4");
        assert!(p.partition.is_empty() && !p.tube_tables);
        assert_eq!(p.cores, "ja");
        let d = Settings::load(&config(), Quality::Draft1x).unwrap();
        assert_eq!((d.host(), d.oversample, d.sim_rate()), (48_000, 1, 48_000));
        assert_eq!(d.method, "trbdf2");
        assert_eq!(d.error_abstol, 0.0);
        assert_eq!(d.cores, "linear");
        assert!(d.tube_tables);
        assert_eq!(d.partition.len(), 3);
        // Draft-1x keeps what it doesn't set from production.
        assert_eq!(d.input_order, p.input_order);
        assert_eq!(d.settle_s, 1.0);
    }
}
