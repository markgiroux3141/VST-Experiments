//! The Components view's logic (docs/COMPONENT_EDITOR_PLAN.md C2 step 7): a transformer
//! component opened from a saved version, its design edited, compiled off the UI thread,
//! heard in a circuit that pins it, saved as a new version, and a circuit moved to it.
//! The window (`components_view.rs`) paints it; tests drive it directly.
//!
//! - **Editing.** The design is the version's construction as data
//!   (`varimu_components::edit`): an edit replaces a value and its source, everything else
//!   stays as read, so an unedited design compiles to the version it came from. Edits are
//!   undoable; drags of one value coalesce into one step.
//! - **Compiling.** A worker thread compiles the newest design (a design edited while it
//!   compiles is compiled next, the ones between skipped). A design whose leakage comes
//!   from the field solution (seconds per winding pair) is first compiled by the 1D
//!   formula as a preview, then by the field.
//! - **Hearing it.** A circuit file that pins the component (`uses`) plays with the
//!   design in its place: the design's compiled form as the next version number, served
//!   by the library without a file (`Library::add_unsaved`), the circuit's reference to
//!   the component retargeted in memory. A value updates the stream, a change of structure
//!   restarts it (the player's rule).
//! - **A / B.** The circuit as pinned against the design, loudness-matched: both rendered
//!   at draft-1x over the loop region with the panel as it is, integrated loudness
//!   (BS.1770) measured, the design's side trimmed by the difference.
//! - **Saving** writes the next version and its lock line (`varimu_components::store`);
//!   nothing when the design equals a saved version. **Moving a circuit** to a version is
//!   an explicit action: the circuit file's parameter naming the component is rewritten.

use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicBool;
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

use varimu_circuit::spec::{self, CircuitSpec};
use varimu_circuit::versions::{self, Ref};
use varimu_circuit::yaml::{self, Value};
use varimu_circuit::{Error, Library};
use varimu_components::compile::{Compiled, compile};
use varimu_components::design::{Design, LeakageMethod};
use varimu_components::edit::{self, Step};
use varimu_components::response::{self, Curve, Setup};
use varimu_components::store;
use varimu_components::tables::Tables;

use crate::live::{Circuit, Values};
use crate::monitor::integrated_lufs;
use crate::render::render;
use crate::settings::Settings;

/// The response plot's frequencies.
pub const F_LOW_HZ: f64 = 10.0;
pub const F_HIGH_HZ: f64 = 100e3;

/// Edits to one value within this of each other are one undo step (a drag).
const COALESCE: Duration = Duration::from_millis(800);

/// A compiled design.
#[derive(Debug)]
pub struct Outcome {
    /// The bench's revision it was compiled from.
    pub revision: u64,
    /// The 1D formula's preview of a field design (the field solution follows).
    pub preview: bool,
    pub compiled: Compiled,
    /// The version file it would be saved as, and that file parsed.
    pub text: String,
    pub data: Value,
    /// The saved version it equals, if any.
    pub saved: Option<Ref>,
}

/// A circuit file that pins the component.
#[derive(Debug, Clone, PartialEq)]
pub struct Use {
    /// The circuit's name (its file's stem) and file.
    pub circuit: String,
    pub path: PathBuf,
    /// The version it pins.
    pub version: u32,
    /// The `values` parameters that name the component, and the parts that name it inline.
    pub params: Vec<String>,
    pub parts: Vec<String>,
    /// It is compiled from a drawing (`<name>.drawing.json`): its pin moves in the drawing.
    pub drawn: bool,
}

/// The transformer components in the store, each with its versions.
pub fn transformer_components(config_dir: &Path) -> Vec<(String, Vec<u32>)> {
    let root = config_dir.join("components");
    let mut out = Vec::new();
    for folder in versions::names(&root) {
        let vs = versions::versions(&root, &folder);
        let Some(&last) = vs.last() else { continue };
        let path = root.join(&folder).join(format!("{last}.yaml"));
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        let is_transformer = text.lines().any(|l| l.trim_end() == "kind: transformer");
        let name = text
            .lines()
            .find_map(|l| l.strip_prefix("name: "))
            .map(|n| n.trim().trim_matches('\'').to_string());
        if let (true, Some(name)) = (is_transformer, name) {
            out.push((name, vs));
        }
    }
    out
}

/// A reference to `name` (any version), if `v` is one.
fn names(v: &Value, name: &str) -> Option<u32> {
    let r = versions::parse(v.as_str()?).ok()?;
    (r.name.eq_ignore_ascii_case(name))
        .then_some(r.version)
        .flatten()
}

/// Where `spec` names component `name`: its `values` parameters and its parts' inline
/// `component:` (with the version they pin).
/// (where, the version pinned) pairs.
type Pins = Vec<(String, u32)>;

fn references(spec: &CircuitSpec, name: &str) -> (Pins, Pins) {
    let mut params = Vec::new();
    for (k, e) in spec.values.iter() {
        if let Some(v) = e
            .as_map()
            .and_then(|m| m.get("value"))
            .and_then(|v| names(v, name))
        {
            params.push((k.to_string(), v));
        }
    }
    let mut parts = Vec::new();
    for s in &spec.sections {
        for (k, p) in s.parts.iter() {
            if let Some(v) = p
                .as_map()
                .and_then(|m| m.get("component"))
                .and_then(|v| names(v, name))
            {
                parts.push((k.to_string(), v));
            }
        }
    }
    (params, parts)
}

/// Every circuit file in config/circuits that pins component `name`, by name.
pub fn uses(config_dir: &Path, name: &str) -> Vec<Use> {
    let dir = config_dir.join("circuits");
    let needle = format!("{}@", name.to_lowercase());
    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|e| e == "yaml"))
        .collect();
    files.sort();
    let mut out = Vec::new();
    for path in files {
        let Ok(text) = std::fs::read_to_string(&path) else {
            continue;
        };
        if !text.to_lowercase().contains(&needle) {
            continue;
        }
        let Ok(spec) = spec::load_circuit(&path) else {
            continue;
        };
        let (params, parts) = references(&spec, name);
        let Some(version) = params.iter().chain(&parts).map(|(_, v)| *v).max() else {
            continue;
        };
        let circuit = path.file_stem().unwrap().to_string_lossy().into_owned();
        out.push(Use {
            drawn: dir.join(format!("{circuit}.drawing.json")).is_file(),
            circuit,
            path,
            version,
            params: params.into_iter().map(|(k, _)| k).collect(),
            parts: parts.into_iter().map(|(k, _)| k).collect(),
        });
    }
    // Hand-written circuits first.
    out.sort_by_key(|u| u.drawn);
    out
}

/// `spec` with every reference to component `name` replaced by `reference`; how many.
pub fn retarget(spec: &mut CircuitSpec, name: &str, reference: &str) -> usize {
    let mut n = 0;
    for (_, e) in spec.values.0.iter_mut() {
        if let Value::Map(m) = e
            && m.get("value").is_some_and(|v| names(v, name).is_some())
        {
            m.insert("value", Value::Str(reference.into()));
            n += 1;
        }
    }
    for s in &mut spec.sections {
        for (_, p) in s.parts.0.iter_mut() {
            if let Value::Map(m) = p
                && m.get("component").is_some_and(|v| names(v, name).is_some())
            {
                m.insert("component", Value::Str(reference.into()));
                n += 1;
            }
        }
    }
    n
}

/// Rewrites circuit file `u.path`'s pin to `to`: each parameter naming the component gets
/// the new version and `source` (its line rewritten, nothing else in the file touched).
/// Inline parts and drawn circuits are refused (a drawing's pin moves in the Editor).
pub fn move_pin(u: &Use, to: &Ref, source: &str) -> Result<(), String> {
    if u.drawn {
        return Err(format!(
            "{} is compiled from its drawing: move its pin there (the Editor's Core symbol)",
            u.circuit
        ));
    }
    if !u.parts.is_empty() {
        return Err(format!(
            "{} names the component inline ({}): give it a parameter first",
            u.circuit,
            u.parts.join(", ")
        ));
    }
    let text = std::fs::read_to_string(&u.path).map_err(|e| e.to_string())?;
    let crlf = text.contains("\r\n");
    let mut lines: Vec<String> = text.lines().map(str::to_string).collect();
    let entry = Value::Map(yaml::Map(vec![
        ("value".into(), Value::Str(to.to_string())),
        ("source".into(), Value::Str(source.into())),
    ]));
    // The `values` block's entries, one line each (`  key: {value: ..., source: ...}`).
    let start = lines
        .iter()
        .position(|l| l.trim_end() == "values:")
        .ok_or("the circuit has no values block")?;
    for key in &u.params {
        let prefix = format!("  {key}:");
        let i = lines
            .iter()
            .enumerate()
            .skip(start + 1)
            .take_while(|(_, l)| l.is_empty() || l.starts_with(' ') || l.starts_with('#'))
            .find(|(_, l)| l.starts_with(&prefix))
            .map(|(i, _)| i)
            .ok_or_else(|| format!("{}: no one-line values entry {key}", u.circuit))?;
        lines[i] = format!("{prefix} {}", varimu_circuit::yaml_out::flow(&entry));
    }
    let nl = if crlf { "\r\n" } else { "\n" };
    let mut out = lines.join(nl);
    out.push_str(nl);
    std::fs::write(&u.path, out).map_err(|e| e.to_string())?;
    // Read back: the parameters name the new version.
    let spec = spec::load_circuit(&u.path).map_err(|e| e.to_string())?;
    let (params, _) = references(&spec, &to.name);
    if params.iter().any(|(_, v)| Some(*v) != to.version) || params.len() != u.params.len() {
        return Err(format!("{}: the pin didn't move", u.circuit));
    }
    Ok(())
}

/// The newest design waiting to be compiled, and the worker's wake-up.
type Slot = Arc<(Mutex<Option<(u64, Value)>>, Condvar)>;

fn worker(
    config_dir: PathBuf,
    tables: Arc<Tables>,
    slot: Slot,
    tx: Sender<Result<Outcome, (u64, String)>>,
) {
    let lib = Library::new(&config_dir);
    let root = config_dir.join("components");
    loop {
        let (rev, data) = {
            let (m, cv) = &*slot;
            let mut g = m.lock().unwrap();
            loop {
                if let Some(x) = g.take() {
                    break x;
                }
                g = cv.wait(g).unwrap();
            }
        };
        let newer = || slot.0.lock().unwrap().is_some();
        let design = match Design::parse(&data) {
            Ok(d) => d,
            Err(e) => {
                if tx.send(Err((rev, e.0))).is_err() {
                    return;
                }
                continue;
            }
        };
        let mut passes = vec![(design.clone(), false)];
        if design.leakage_method == LeakageMethod::Field {
            let mut d = design.clone();
            d.leakage_method = LeakageMethod::Formula;
            passes.insert(0, (d, true));
        }
        for (d, preview) in passes {
            if !preview && newer() && design.leakage_method == LeakageMethod::Field {
                break; // a newer design waits: its preview first
            }
            let r = compile(&d, &tables, &lib).and_then(|c| {
                let text = c.version_text(&data, &tables, &config_dir, &store::today())?;
                let parsed = yaml::parse(&text, &design.name)?;
                let saved = if preview {
                    None
                } else {
                    saved_as(&root, &design.name, &text)
                };
                Ok(Outcome {
                    revision: rev,
                    preview,
                    compiled: c,
                    text,
                    data: parsed,
                    saved,
                })
            });
            if tx.send(r.map_err(|e| (rev, e.0))).is_err() {
                return;
            }
        }
    }
}

/// The saved version of `name` whose body equals `text`'s, if any.
pub fn saved_as(root: &Path, name: &str, text: &str) -> Option<Ref> {
    let body = |t: &str| store::body(t).replace("\r\n", "\n");
    let want = body(text);
    versions::versions(root, name)
        .into_iter()
        .rev()
        .find_map(|v| {
            let r = Ref {
                name: name.to_string(),
                version: Some(v),
            };
            let (r, t) = versions::read_text(root, &r).ok()?;
            (body(&t) == want).then_some(r)
        })
}

/// Which side of the A / B.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side {
    /// The circuit as it pins the component.
    Pinned,
    /// The design (saved or not).
    Design,
}

/// A circuit to play: its title, spec and library.
pub struct Playable {
    pub name: String,
    pub title: String,
    pub spec: CircuitSpec,
    pub lib: Arc<Library>,
}

/// A loudness match running, or its result: each side's integrated loudness (LUFS).
pub struct Matching {
    pub revision: u64,
    rx: Receiver<Result<(f64, f64), String>>,
}

pub struct Bench {
    pub config_dir: PathBuf,
    pub tables: Arc<Tables>,
    pub name: String,
    /// The version it was opened from (or last saved as).
    pub opened: Option<Ref>,
    pub design: Value,
    pub revision: u64,
    history: Vec<Value>,
    future: Vec<Value>,
    /// The last edit's path and time (drags coalesce).
    last_edit: Option<(Vec<Step>, Instant)>,
    /// The newest compile of the design (maybe a preview, maybe older than `revision`).
    pub outcome: Option<Outcome>,
    /// The newest design doesn't compile: why.
    pub error: Option<String>,
    /// The opened version compiled (the response's reference curve).
    pub reference: Option<Compiled>,
    pub setup: Option<Setup>,
    pub uses: Vec<Use>,
    /// Which use plays.
    pub play_in: usize,
    /// The last loudness match (revision, pinned LUFS, design LUFS), and one running.
    pub matched: Option<(u64, f64, f64)>,
    matching: Option<Matching>,
    pub status: String,
    slot: Slot,
    rx: Receiver<Result<Outcome, (u64, String)>>,
}

impl Bench {
    /// Opens component `reference` (`NAME@N`, or `NAME` for its latest version).
    pub fn open(config_dir: &Path, reference: &str) -> Result<Bench, String> {
        let root = config_dir.join("components");
        let r = versions::resolve(&root, &versions::parse(reference).map_err(|e| e.0)?)
            .map_err(|e| e.0)?;
        let (r, text) = versions::read_text(&root, &r).map_err(|e| e.0)?;
        let data = yaml::parse(&text, reference).map_err(|e| e.0)?;
        let design = edit::design_of_version(&data).map_err(|e| e.0)?;
        let tables = Arc::new(Tables::load(config_dir).map_err(|e| e.0)?);
        let lib = Library::new(config_dir);
        let reference = Design::parse(&design)
            .and_then(|d| compile(&d, &tables, &lib))
            .ok();
        let slot: Slot = Arc::new((Mutex::new(None), Condvar::new()));
        let (tx, rx) = mpsc::channel();
        {
            let (cfg, t, s) = (config_dir.to_path_buf(), tables.clone(), slot.clone());
            std::thread::Builder::new()
                .name("components-compile".into())
                .spawn(move || worker(cfg, t, s, tx))
                .map_err(|e| e.to_string())?;
        }
        let uses = uses(config_dir, &r.name);
        let setup = reference.as_ref().and_then(Setup::default_for);
        let mut b = Bench {
            config_dir: config_dir.to_path_buf(),
            tables,
            name: r.name.clone(),
            opened: Some(r),
            design,
            revision: 0,
            history: Vec::new(),
            future: Vec::new(),
            last_edit: None,
            outcome: None,
            error: None,
            reference,
            setup,
            uses,
            play_in: 0,
            matched: None,
            matching: None,
            status: String::new(),
            slot,
            rx,
        };
        b.submit();
        Ok(b)
    }

    fn submit(&mut self) {
        let (m, cv) = &*self.slot;
        *m.lock().unwrap() = Some((self.revision, self.design.clone()));
        cv.notify_one();
    }

    /// Takes the worker's results; true when something changed.
    pub fn poll(&mut self) -> bool {
        let mut changed = false;
        while let Ok(r) = self.rx.try_recv() {
            changed = true;
            match r {
                Ok(o) => {
                    if o.revision == self.revision {
                        self.error = None;
                    }
                    // An older revision's result still replaces an older one.
                    let newer = self
                        .outcome
                        .as_ref()
                        .is_none_or(|x| (o.revision, !o.preview) >= (x.revision, !x.preview));
                    if newer {
                        self.outcome = Some(o);
                    }
                }
                Err((rev, e)) => {
                    if rev == self.revision {
                        self.error = Some(e);
                    }
                }
            }
        }
        if let Some(m) = &self.matching
            && let Ok(r) = m.rx.try_recv()
        {
            let rev = m.revision;
            self.matching = None;
            changed = true;
            match r {
                Ok((a, b)) => self.matched = Some((rev, a, b)),
                Err(e) => self.status = format!("loudness match: {e}"),
            }
        }
        changed
    }

    /// Whether the newest design is compiled (by its own method).
    pub fn settled(&self) -> bool {
        self.error.is_some()
            || self
                .outcome
                .as_ref()
                .is_some_and(|o| o.revision == self.revision && !o.preview)
    }

    /// Waits for the newest design's compile (tests, scripts).
    pub fn wait(&mut self, timeout: Duration) -> Result<&Outcome, String> {
        let t0 = Instant::now();
        while !self.settled() {
            if t0.elapsed() > timeout {
                return Err("compiling took too long".into());
            }
            std::thread::sleep(Duration::from_millis(5));
            self.poll();
        }
        match &self.error {
            Some(e) => Err(e.clone()),
            None => Ok(self.outcome.as_ref().unwrap()),
        }
    }

    /// Applies `f` to the design: an undo step (unless it continues a drag of the same
    /// value), a new revision, compiled next.
    pub fn edit(
        &mut self,
        path: impl Into<Vec<Step>>,
        f: impl FnOnce(&mut Value) -> Result<(), Error>,
    ) -> Result<(), String> {
        let path = path.into();
        let mut d = self.design.clone();
        f(&mut d).map_err(|e| e.0)?;
        if d == self.design {
            return Ok(());
        }
        let coalesce = !path.is_empty()
            && self
                .last_edit
                .as_ref()
                .is_some_and(|(p, t)| *p == path && t.elapsed() < COALESCE);
        if !coalesce {
            self.history.push(std::mem::replace(&mut self.design, d));
        } else {
            self.design = d;
        }
        self.last_edit = Some((path, Instant::now()));
        self.future.clear();
        self.changed();
        Ok(())
    }

    /// Sets the physical value at `path`, its source a design choice of today.
    pub fn set(&mut self, path: impl Into<Vec<Step>>, x: Value) -> Result<(), String> {
        let path: Vec<Step> = path.into();
        let src = edit::chosen(&store::today());
        let p = path.clone();
        self.edit(path, move |d| edit::set(d, &p, x, &src))
    }

    fn changed(&mut self) {
        self.revision += 1;
        self.submit();
    }

    pub fn can_undo(&self) -> bool {
        !self.history.is_empty()
    }

    pub fn can_redo(&self) -> bool {
        !self.future.is_empty()
    }

    pub fn undo(&mut self) {
        if let Some(d) = self.history.pop() {
            self.future.push(std::mem::replace(&mut self.design, d));
            self.last_edit = None;
            self.changed();
        }
    }

    pub fn redo(&mut self) {
        if let Some(d) = self.future.pop() {
            self.history.push(std::mem::replace(&mut self.design, d));
            self.last_edit = None;
            self.changed();
        }
    }

    /// The design differs from the version it was opened from.
    pub fn edited(&self) -> bool {
        match (&self.outcome, &self.opened) {
            (Some(o), Some(r)) if o.revision == self.revision && !o.preview => {
                o.saved.as_ref() != Some(r)
            }
            _ => !self.history.is_empty(),
        }
    }

    /// The number the design would be saved as.
    pub fn next_version(&self) -> u32 {
        versions::versions(&self.config_dir.join("components"), &self.name)
            .last()
            .copied()
            .unwrap_or(0)
            + 1
    }

    /// The reference the design plays as: the saved version it equals, else the next
    /// number (unsaved).
    pub fn design_ref(&self) -> Option<Ref> {
        let o = self.outcome.as_ref()?;
        Some(o.saved.clone().unwrap_or(Ref {
            name: self.name.clone(),
            version: Some(self.next_version()),
        }))
    }

    /// The use that plays.
    pub fn play_use(&self) -> Option<&Use> {
        self.uses.get(self.play_in)
    }

    /// The circuit to play: as pinned, or with the design in the component's place.
    pub fn playable(&self, side: Side) -> Result<Playable, String> {
        let u = self.play_use().ok_or("no circuit pins this component")?;
        let mut spec = spec::load_circuit(&u.path).map_err(|e| e.to_string())?;
        let lib = Library::new(&self.config_dir);
        let title = match side {
            Side::Pinned => format!("{} ({}@{})", spec.title, self.name, u.version),
            Side::Design => {
                let o = self
                    .outcome
                    .as_ref()
                    .ok_or("the design isn't compiled yet")?;
                let r = self.design_ref().unwrap();
                if o.saved.is_none() {
                    lib.add_unsaved(&r.to_string(), o.data.clone())
                        .map_err(|e| e.0)?;
                }
                retarget(&mut spec, &self.name, &r.to_string());
                let what = if o.saved.is_some() { "" } else { ", unsaved" };
                format!("{} ({r}{what})", spec.title)
            }
        };
        Ok(Playable {
            name: u.circuit.clone(),
            title,
            spec,
            lib: Arc::new(lib),
        })
    }

    /// The response of the design (and of the opened version, for comparison).
    pub fn curves(&self) -> (Option<Curve>, Option<Curve>) {
        let Some(s) = &self.setup else {
            return (None, None);
        };
        let f = response::frequencies(F_LOW_HZ, F_HIGH_HZ, 12);
        let of = |c: &Compiled| {
            let ok = s
                .drive
                .iter()
                .chain([&s.load])
                .all(|&k| k < c.windings.len());
            ok.then(|| response::curve(&response::Network::of(c), s, &f))
                .flatten()
        };
        (
            self.outcome.as_ref().and_then(|o| of(&o.compiled)),
            self.reference.as_ref().and_then(of),
        )
    }

    /// Saves the design as the next version (nothing when it equals a saved one).
    pub fn save(&mut self) -> Result<Ref, String> {
        let o = self.outcome.as_ref().ok_or("nothing compiled")?;
        if o.revision != self.revision || o.preview {
            return Err("the design is still compiling".into());
        }
        if let Some(r) = &o.saved {
            self.opened = Some(r.clone());
            return Ok(r.clone());
        }
        let root = self.config_dir.join("components");
        let r = store::save(&root, &self.name, &o.text).map_err(|e| e.0)?;
        // What's saved is what was read back.
        versions::read_text(&root, &r).map_err(|e| e.0)?;
        if let Some(o) = &mut self.outcome {
            o.saved = Some(r.clone());
        }
        self.reference = self.outcome.as_ref().map(|o| o.compiled.clone());
        self.opened = Some(r.clone());
        self.status = format!("saved {r}");
        Ok(r)
    }

    /// Moves the playing circuit to the design's saved version.
    pub fn move_pin(&mut self) -> Result<String, String> {
        let o = self.outcome.as_ref().ok_or("nothing compiled")?;
        let to = o.saved.clone().ok_or("save the design first")?;
        let u = self.play_use().ok_or("no circuit")?.clone();
        if Some(u.version) == to.version {
            return Err(format!("{} pins {to} already", u.circuit));
        }
        let src = format!(
            "config/components/{}/{}.yaml (moved from {}@{} in the Components view, {})",
            to.folder(),
            to.version.unwrap(),
            self.name,
            u.version,
            store::today()
        );
        move_pin(&u, &to, &src)?;
        self.uses = uses(&self.config_dir, &self.name);
        self.play_in = self
            .uses
            .iter()
            .position(|x| x.circuit == u.circuit)
            .unwrap_or(0);
        let msg = format!(
            "{} now pins {to}: rerun scripts/export_app_fixtures.py (its IR changes, as meant)",
            u.circuit
        );
        self.status = msg.clone();
        Ok(msg)
    }

    /// Starts a loudness match of the two sides on `input` (full scale 1.0, the project's
    /// rate, the input gain applied) with the panel's `values`, at `settings` (draft-1x).
    pub fn start_match(&mut self, input: Vec<f64>, values: Values, settings: Settings) {
        let sides = (self.playable(Side::Pinned), self.playable(Side::Design));
        let (tx, rx) = mpsc::channel();
        self.matching = Some(Matching {
            revision: self.revision,
            rx,
        });
        let cores = settings.cores();
        std::thread::spawn(move || {
            let run = || -> Result<(f64, f64), String> {
                let (a, b) = (sides.0?, sides.1?);
                let cores = cores?;
                let cancel = AtomicBool::new(false);
                let loud = |p: Playable| -> Result<f64, String> {
                    let c = Circuit::from_spec(p.lib, p.spec, cores);
                    let r = render(&c, &values, &input, &settings, |_| {}, &cancel)?;
                    Ok(integrated_lufs(&r.out, r.sample_rate))
                };
                std::thread::scope(|s| {
                    let h = s.spawn(|| loud(a));
                    let lb = loud(b)?;
                    let la = h.join().map_err(|_| "a render panicked")??;
                    Ok((la, lb))
                })
            };
            let _ = tx.send(run());
        });
    }

    pub fn matching(&self) -> bool {
        self.matching.is_some()
    }

    /// The design side's trim (dB) to match the pinned side, if measured for this design.
    pub fn match_db(&self) -> Option<f64> {
        let (rev, a, b) = self.matched?;
        (rev == self.revision && a.is_finite() && b.is_finite()).then_some(a - b)
    }

    /// A transformer by its index in the design's windings.
    pub fn winding_labels(&self) -> Vec<String> {
        edit::windings(&self.design)
    }
}

/// The materials config/magnetics.yaml offers.
pub fn materials(config_dir: &Path) -> Vec<String> {
    yaml::load(&config_dir.join("magnetics.yaml"))
        .ok()
        .and_then(|d| {
            d.as_map()?
                .get("materials")?
                .as_map()
                .map(|m| m.keys().map(str::to_string).collect())
        })
        .unwrap_or_default()
}
