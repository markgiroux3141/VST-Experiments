//! The editor's state and everything that changes it (`varimu/listen/editor/main.js`,
//! `tools.js` and `inspector.js`'s behaviour, without the page): the drawing, its
//! compile and checks, the selection, the tools, undo and redo, open and save.
//!
//! Every change goes through [`Editor::apply`]: recorded for undo, recompiled, and the
//! pre-flight checks scheduled (on a thread of their own, 600 ms after the last edit).
//! `revision` counts changes, so the window knows when to hand the player a new circuit.
//!
//! The tools, as on the page:
//!
//! ```text
//!   select   click selects (shift adds), drag moves (wires follow), drag from a pin draws
//!            a wire, drag on the empty canvas selects a box; Delete, R (rotate), X
//!            (mirror), arrows (nudge), Ctrl+C / X / V / D / A
//!   wire     click to add corners (L-shaped, / flips the corner), ends on a pin or wire,
//!            Enter, a double click or Esc
//!   label    click a wire or pin to name its net
//!   ground   click a wire or pin to ground it
//!   place    a part from the palette follows the pointer: click places it (R, X turn it)
//!   frame    drag a frame, then name it (a section)
//! ```
//!
//! Pointer positions are canvas points (the camera maps them to the drawing's mm), so
//! the snapping radii are the page's: 6 px to a connection point, 7 px to hit an item.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::mpsc::{self, Receiver, Sender};
use std::time::{Duration, Instant};

use varimu_circuit::Library;
use varimu_circuit::compile::{Marker, check_drawing, compiled_spec, save_circuit};
use varimu_circuit::drawing::{Drawing, Frame, Label, Placement, load_drawing};
use varimu_circuit::spec::CircuitSpec;
use varimu_circuit::symbols::{self, Kind};
use varimu_circuit::yaml::{Map, Value};

use super::analysis::{Analysis, GenomeBounds, analyze};
use super::camera::Camera;
use super::edits::{
    History, Home, edit_source, entry_mut, param_home, set_inline, set_param, unlink, value_key,
};
use super::eng::{eng_text, number_value, parse_num, step_e, value_text};
use super::geom::{
    self, Clip, Item, Pt, Sel, add_wire, copy_items, delete_items, drag_segment, frame_contents,
    move_items, paste_items, place_symbol, rename_ref, round4, route, select_box, snap, turn_items,
};
use super::scene::{Hit, Scene, pad_box};

const DRAG_PX: f64 = 3.0;
const CHECK_DELAY: Duration = Duration::from_millis(600);

/// Where the drawing came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Origin {
    /// A `<name>.drawing.json` in config/circuits.
    Drawn,
    /// A blank drawing or a file opened from elsewhere, not saved yet.
    New,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Select,
    Wire,
    Label,
    Ground,
    Frame,
    Place,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Placing {
    pub name: String,
    pub rot: i64,
    pub mirror: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Wiring {
    pub pts: Vec<Pt>,
    pub hfirst: bool,
}

#[derive(Debug, Clone)]
enum OpKind {
    Move {
        w0: Pt,
        sel: Sel,
        snapshot: Box<Drawing>,
        last: Pt,
    },
    Segment {
        wi: usize,
        j: usize,
        w0: Pt,
        snapshot: Box<Drawing>,
        last: Pt,
    },
    Resize {
        i: usize,
        snapshot: Box<Drawing>,
        frame: Option<(f64, f64)>,
    },
    Box {
        a: Pt,
        add: bool,
    },
    Frame {
        a: Pt,
    },
    PinWire {
        from: Pt,
        pin: usize,
    },
}

#[derive(Debug, Clone)]
struct Op {
    kind: OpKind,
    sx: f64,
    sy: f64,
    moved: bool,
}

/// A question the window asks in a small box by the pointer.
#[derive(Debug, Clone, PartialEq)]
pub enum Ask {
    /// A net's name for a new label at a point.
    Label(Pt),
    RenameLabel(usize),
    /// A section's name for a new frame (x, y, w, h).
    Frame([f64; 4]),
    RenameFrame(usize),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Prompt {
    pub ask: Ask,
    pub title: String,
    pub initial: String,
    /// Names to offer.
    pub options: Vec<String>,
    /// Where (canvas points).
    pub at: Pt,
}

/// What the tools draw over the drawing.
#[derive(Debug, Clone, PartialEq)]
pub enum Ghost {
    Part { name: String, pl: Placement },
    Wire { pts: Vec<Pt>, cursor: Pt },
    Cursor(Pt),
    Ground(Placement),
    Box([f64; 4]),
    FrameBox([f64; 4]),
}

/// A key the tools know.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Key {
    Escape,
    Enter,
    Delete,
    Left,
    Right,
    Up,
    Down,
    Char(char),
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct Mods {
    pub ctrl: bool,
    pub shift: bool,
    pub alt: bool,
}

/// The checks' state, for the pill.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Checking {
    Busy,
    /// Done in this long (s).
    Done(f64),
}

/// Device files and core materials: what a part's type can be swapped for.
#[derive(Debug, Clone, Default)]
pub struct PartLib {
    /// (name, kind) of each device file.
    pub devices: Vec<(String, String)>,
    pub materials: Vec<String>,
}

impl PartLib {
    pub fn load(config_dir: &Path) -> PartLib {
        let mut devices = Vec::new();
        if let Ok(rd) = std::fs::read_dir(config_dir.join("devices")) {
            let mut paths: Vec<PathBuf> = rd
                .flatten()
                .map(|e| e.path())
                .filter(|p| p.extension().is_some_and(|x| x == "yaml"))
                .collect();
            paths.sort();
            for p in paths {
                if let Ok(Value::Map(m)) = varimu_circuit::yaml::load(&p) {
                    let stem = p
                        .file_stem()
                        .unwrap_or_default()
                        .to_string_lossy()
                        .into_owned();
                    devices.push((
                        m.get("name").map_or(stem, Value::py_str),
                        m.get("kind").map(Value::py_str).unwrap_or_default(),
                    ));
                }
            }
        }
        let materials = match varimu_circuit::yaml::load(&config_dir.join("magnetics.yaml")) {
            Ok(Value::Map(m)) => m
                .get("materials")
                .and_then(Value::as_map)
                .map(|x| x.keys().map(str::to_string).collect())
                .unwrap_or_default(),
            _ => Vec::new(),
        };
        PartLib { devices, materials }
    }
}

/// A circuit that can be opened in the editor.
#[derive(Debug, Clone, PartialEq)]
pub struct Listed {
    pub name: String,
    pub title: String,
}

/// The drawn circuits in `dir` (each `<name>.drawing.json`), by name.
pub fn list_circuits(dir: &Path) -> Vec<Listed> {
    let mut out = Vec::new();
    if let Ok(rd) = std::fs::read_dir(dir) {
        for e in rd.flatten() {
            let p = e.path();
            let fname = p
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .into_owned();
            let Some(name) = fname.strip_suffix(".drawing.json") else {
                continue;
            };
            let title = load_drawing(&p)
                .ok()
                .and_then(|d| d.circuit.get("title").map(Value::py_str))
                .unwrap_or_else(|| name.to_string());
            out.push(Listed {
                name: name.to_string(),
                title,
            });
        }
    }
    out.sort_by(|a, b| a.name.cmp(&b.name));
    out
}

/// A new circuit's drawing.
pub fn blank() -> Drawing {
    Drawing {
        circuit: Map(vec![
            ("title".into(), Value::Str("Untitled circuit".into())),
            ("input".into(), Value::Str("in".into())),
            ("probes".into(), Value::List(Vec::new())),
        ]),
        ..Drawing::default()
    }
}

struct CheckWorker {
    tx: Sender<(u64, Drawing)>,
    rx: Receiver<(u64, Vec<Marker>, f64)>,
}

impl CheckWorker {
    fn new(lib: Arc<Library>) -> CheckWorker {
        let (tx, jobs) = mpsc::channel::<(u64, Drawing)>();
        let (done, rx) = mpsc::channel();
        std::thread::Builder::new()
            .name("editor checks".into())
            .spawn(move || {
                while let Ok(mut job) = jobs.recv() {
                    while let Ok(newer) = jobs.try_recv() {
                        job = newer;
                    }
                    let t0 = Instant::now();
                    let (_, m) = check_drawing(&job.1, &lib);
                    if done.send((job.0, m, t0.elapsed().as_secs_f64())).is_err() {
                        return;
                    }
                }
            })
            .expect("a thread for the checks");
        CheckWorker { tx, rx }
    }
}

/// The schematic editor's state.
pub struct Editor {
    pub lib: Arc<Library>,
    pub bounds: GenomeBounds,
    pub parts: PartLib,
    /// config/circuits: where drawings open from and save to.
    pub circuits_dir: PathBuf,
    pub name: String,
    pub origin: Origin,
    pub drawing: Drawing,
    pub analysis: Analysis,
    pub scene: Scene,
    /// A drag's preview: the drawing as it would be, laid out.
    pub preview: Option<(Drawing, Scene)>,
    pub sel: Sel,
    /// The net shown in the inspector (-1: none).
    pub net: i64,
    pub hover: Option<Hit>,
    pub markers: Vec<Marker>,
    /// The marker clicked in the problems list.
    pub focus: Option<usize>,
    pub checking: Checking,
    pub hist: History,
    pub cam: Camera,
    pub mode: Mode,
    pub place: Option<Placing>,
    pub wire: Option<Wiring>,
    op: Option<Op>,
    pub clip: Option<Clip>,
    /// The pointer (world) and where it was last (canvas).
    pub world: Pt,
    last_screen: Option<Pt>,
    pub prompt: Option<Prompt>,
    pub status: String,
    /// Changes so far (edits, undo, opening): a new one means a new circuit to hear.
    pub revision: u64,
    checks: CheckWorker,
    checks_due: Option<Instant>,
    checks_started: Option<(u64, Instant)>,
}

impl Editor {
    /// An editor on config dir `config_dir`, with a blank drawing.
    pub fn new(config_dir: &Path) -> Editor {
        let lib = Arc::new(Library::new(config_dir));
        let bounds = GenomeBounds::load(config_dir);
        let drawing = blank();
        let analysis = analyze(&drawing, &lib, &bounds);
        let scene = Scene::build(&drawing, &analysis, false);
        Editor {
            checks: CheckWorker::new(lib.clone()),
            lib,
            bounds,
            parts: PartLib::load(config_dir),
            circuits_dir: config_dir.join("circuits"),
            name: "untitled".into(),
            origin: Origin::New,
            drawing,
            analysis,
            scene,
            preview: None,
            sel: Sel::default(),
            net: -1,
            hover: None,
            markers: Vec::new(),
            focus: None,
            checking: Checking::Done(0.0),
            hist: History::default(),
            cam: Camera::default(),
            mode: Mode::Select,
            place: None,
            wire: None,
            op: None,
            clip: None,
            world: (0.0, 0.0),
            last_screen: None,
            prompt: None,
            status: String::new(),
            revision: 0,
            checks_due: None,
            checks_started: None,
        }
    }

    // --- Opening and saving -------------------------------------------------------------

    /// Open the drawn circuit `name` (config/circuits/<name>.drawing.json).
    pub fn open(&mut self, name: &str) -> Result<(), String> {
        let p = self.circuits_dir.join(format!("{name}.drawing.json"));
        let d = load_drawing(&p).map_err(|e| e.to_string())?;
        self.load(name, Origin::Drawn, d);
        Ok(())
    }

    /// A blank drawing.
    pub fn open_blank(&mut self) {
        self.load("untitled", Origin::New, blank());
    }

    /// A drawing file from anywhere: a new, unsaved drawing.
    pub fn open_file(&mut self, path: &Path) -> Result<(), String> {
        let d = load_drawing(path).map_err(|e| e.to_string())?;
        let fname = path
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned();
        let name = fname
            .strip_suffix(".drawing.json")
            .unwrap_or(&fname)
            .to_string();
        self.load(&name, Origin::New, d);
        Ok(())
    }

    fn load(&mut self, name: &str, origin: Origin, d: Drawing) {
        self.name = name.into();
        self.origin = origin;
        self.hist.reset(Some(&d));
        self.drawing = d;
        self.set_mode(Mode::Select, None);
        self.markers.clear();
        self.focus = None;
        self.sel = Sel::default();
        self.net = -1;
        self.hover = None;
        self.recompile();
        self.revision += 1;
        self.fit(false);
        self.run_checks();
    }

    /// Whether the drawing differs from what was opened (or a new one).
    pub fn edited(&self) -> bool {
        self.origin == Origin::New || self.hist.is_edited(&self.drawing)
    }

    /// Save as circuit `name`: `<name>.drawing.json` and the compiled `<name>.yaml`, then
    /// go on editing it.
    pub fn save_as(&mut self, name: &str) -> Result<(), String> {
        let ok = name.len() >= 2
            && name.len() <= 48
            && name.starts_with(|c: char| c.is_ascii_lowercase())
            && name
                .chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_');
        if !ok {
            return Err("a name is 2-48 characters: lowercase letters, digits, _".into());
        }
        let origin = self.name.clone();
        save_circuit(&self.drawing, name, &origin, &self.circuits_dir, &self.lib)
            .map_err(|e| e.to_string())?;
        self.name = name.into();
        self.origin = Origin::Drawn;
        self.hist.base = Some(self.drawing.clone());
        self.status = format!("saved as {name}");
        Ok(())
    }

    // --- Editing ------------------------------------------------------------------------

    /// Apply an edit: record the drawing before it, change it, recompile, schedule the
    /// checks. False when nothing changed.
    pub fn apply(&mut self, label: &str, mutate: impl FnOnce(&mut Drawing)) -> bool {
        let before = self.drawing.clone();
        mutate(&mut self.drawing);
        if before == self.drawing {
            return false;
        }
        self.hist.push(before, label);
        self.refresh(label);
        true
    }

    fn refresh(&mut self, label: &str) {
        self.recompile();
        self.revision += 1;
        self.sel = self.sel.existing(&self.drawing);
        if self.net >= self.analysis.nets.len() as i64 {
            self.net = -1;
        }
        // Until the checks run again, what they found about the last drawing may be gone.
        self.markers
            .retain(|m| m.check != "import" && m.check != "unconnected");
        self.focus = None;
        self.checks_due = Some(Instant::now() + CHECK_DELAY);
        self.checking = Checking::Busy;
        self.status = if !self.analysis.ok() {
            format!(
                "doesn't compile: {}",
                self.analysis.errors().first().cloned().unwrap_or_default()
            )
        } else if !self.analysis.has_output {
            "label the output node out to hear the circuit".into()
        } else {
            label.to_string()
        };
    }

    fn recompile(&mut self) {
        self.analysis = analyze(&self.drawing, &self.lib, &self.bounds);
        self.scene = Scene::build(&self.drawing, &self.analysis, false);
        self.preview = None;
    }

    pub fn undo(&mut self) {
        if let Some((d, label)) = self.hist.undo(&self.drawing) {
            self.drawing = d;
            self.refresh(&format!("undo {label}"));
        }
    }

    pub fn redo(&mut self) {
        if let Some((d, label)) = self.hist.redo(&self.drawing) {
            self.drawing = d;
            self.refresh(&format!("redo {label}"));
        }
    }

    /// The compiled circuit, when it can be heard (it compiles and has an `out` node).
    pub fn playable(&self) -> Option<CircuitSpec> {
        if !self.analysis.ok() || !self.analysis.has_output {
            return None;
        }
        compiled_spec(&self.analysis.compiled).ok()
    }

    // --- Checks -------------------------------------------------------------------------

    /// Start the checks now (they run on their own thread).
    pub fn run_checks(&mut self) {
        self.checks_due = None;
        self.checking = Checking::Busy;
        self.checks_started = Some((self.revision, Instant::now()));
        let _ = self.checks.tx.send((self.revision, self.drawing.clone()));
    }

    /// Start checks that are due, take finished ones; true when something changed.
    pub fn poll(&mut self) -> bool {
        if self.checks_due.is_some_and(|t| Instant::now() >= t) {
            self.run_checks();
        }
        let mut changed = false;
        while let Ok((rev, markers, secs)) = self.checks.rx.try_recv() {
            if rev == self.revision {
                self.markers = markers;
                self.focus = None;
                if self.checks_due.is_none() {
                    self.checking = Checking::Done(secs);
                }
                changed = true;
            }
        }
        changed
    }

    /// Run the checks here and wait (scripts and tests).
    pub fn check_now(&mut self) -> &[Marker] {
        let (_, m) = check_drawing(&self.drawing, &self.lib);
        self.markers = m;
        self.checks_due = None;
        self.checking = Checking::Done(0.0);
        &self.markers
    }

    /// Faults (drawing remarks aside), counting a part's open pins once.
    pub fn faults(&self) -> usize {
        let mut seen: Vec<String> = Vec::new();
        for m in self.markers.iter().filter(|m| m.check != "drawing") {
            let k = if m.check == "unconnected" {
                format!("open {}", m.symbols.first().cloned().unwrap_or_default())
            } else {
                m.message.clone()
            };
            if !seen.contains(&k) {
                seen.push(k);
            }
        }
        seen.len()
    }

    // --- Selection and view -------------------------------------------------------------

    pub fn select(&mut self, sel: Sel, net: i64) {
        self.sel = sel;
        self.net = net;
    }

    /// The scene being shown (a drag's preview, else the drawing's).
    pub fn shown(&self) -> (&Drawing, &Scene) {
        match &self.preview {
            Some((d, s)) => (d, s),
            None => (&self.drawing, &self.scene),
        }
    }

    pub fn fit(&mut self, animate: bool) {
        let b = self.scene.bounds(&self.drawing);
        self.cam.show(b, 48.0, 8.0, animate);
    }

    /// Show a part, a net or a marker's items.
    pub fn show_part(&mut self, r: &str) {
        if let Some(b) = self.scene.boxes.get(r).copied() {
            self.cam.show(pad_box(b, 14.0), 48.0, 10.0, true);
        }
    }

    pub fn show_net(&mut self, i: usize) {
        if let Some(b) = self.scene.net_box(&self.drawing, &self.analysis, i) {
            self.cam.show(pad_box(b, 8.0), 48.0, 10.0, true);
        }
    }

    pub fn show_frame(&mut self, i: usize) {
        if let Some(f) = self.drawing.frames.get(i) {
            let b = [f.x, f.y - 6.0, f.x + f.w, f.y + f.h];
            self.cam.show(b, 48.0, 14.0, true);
        }
    }

    /// Click on a problem: show it, select what it is about.
    pub fn focus_marker(&mut self, i: usize) {
        let Some(m) = self.markers.get(i).cloned() else {
            return;
        };
        self.focus = Some(i);
        let mut b: Option<[f64; 4]> = None;
        for &n in &m.nets {
            if let Some(x) = self.scene.net_box(&self.drawing, &self.analysis, n) {
                b = Some(b.map_or(x, |a| super::scene::union_box(a, x)));
            }
        }
        for r in &m.symbols {
            if let Some(x) = self.scene.boxes.get(r) {
                b = Some(b.map_or(*x, |a| super::scene::union_box(a, *x)));
            }
        }
        if let Some(b) = b {
            self.cam.show(pad_box(b, 10.0), 48.0, 10.0, true);
        }
        if m.symbols.len() == 1 {
            self.select(Sel::symbol(&m.symbols[0]), -1);
        } else if m.nets.len() == 1 {
            self.select(Sel::default(), m.nets[0] as i64);
        }
    }

    /// Find a part or a node by name (exact, else a prefix); true when found.
    pub fn find(&mut self, q: &str) -> bool {
        let q = q.trim().to_lowercase();
        if q.is_empty() {
            return false;
        }
        let refs: Vec<String> = self
            .drawing
            .symbols
            .iter()
            .map(|(r, _)| r.clone())
            .collect();
        let r = refs
            .iter()
            .find(|r| r.to_lowercase() == q)
            .or_else(|| refs.iter().find(|r| r.to_lowercase().starts_with(&q)));
        if let Some(r) = r.cloned() {
            self.select(Sel::symbol(&r), -1);
            self.show_part(&r);
            return true;
        }
        let nets = &self.analysis.nets;
        let j = nets
            .iter()
            .position(|n| n.node.to_lowercase() == q)
            .or_else(|| {
                nets.iter()
                    .position(|n| n.node.to_lowercase().starts_with(&q))
            });
        if let Some(j) = j {
            self.select(Sel::default(), j as i64);
            self.show_net(j);
            return true;
        }
        false
    }

    // --- Tools --------------------------------------------------------------------------

    pub fn set_mode(&mut self, mode: Mode, place: Option<&str>) {
        self.cancel_op();
        self.mode = mode;
        if mode == Mode::Place {
            self.place = place.map(|n| Placing {
                name: n.into(),
                rot: 0,
                mirror: false,
            });
            if self.place.is_none() {
                self.mode = Mode::Select;
            }
        }
    }

    fn cancel_op(&mut self) {
        self.op = None;
        self.wire = None;
        self.place = None;
        self.preview = None;
    }

    /// The grid point at a canvas point, or a connection point within 6 points.
    pub fn point_at(&self, sx: f64, sy: f64, connect: bool) -> Pt {
        let (x, y) = self.cam.to_world(sx, sy);
        let near = if connect {
            self.scene.snap_point(&self.drawing, x, y, 6.0 / self.cam.k)
        } else {
            None
        };
        match near {
            Some(p) => (round4(p.0), round4(p.1)),
            None => (snap(x), snap(y)),
        }
    }

    /// Whether a drag (move, segment, box, ...) is under way.
    pub fn dragging(&self) -> bool {
        self.op.is_some()
    }

    /// The left button went down at a canvas point.
    pub fn down(&mut self, sx: f64, sy: f64, shift: bool) {
        self.last_screen = Some((sx, sy));
        let (wx, wy) = self.cam.to_world(sx, sy);
        let r = 7.0 / self.cam.k;
        let op = |kind| Op {
            kind,
            sx,
            sy,
            moved: false,
        };
        match self.mode {
            Mode::Place => {
                let p = self.point_at(sx, sy, false);
                self.place_at(p);
                return;
            }
            Mode::Wire => {
                let p = self.point_at(sx, sy, true);
                self.wire_click(p, false);
                return;
            }
            Mode::Label => {
                let p = self.point_at(sx, sy, true);
                self.label_at(p, (sx, sy));
                return;
            }
            Mode::Ground => {
                let p = self.point_at(sx, sy, true);
                self.ground_at(p);
                return;
            }
            Mode::Frame => {
                self.op = Some(op(OpKind::Frame {
                    a: (snap(wx), snap(wy)),
                }));
                return;
            }
            Mode::Select => {}
        }
        // A selected frame's resize handle (its bottom-right corner).
        for &i in &self.sel.frames {
            let Some(f) = self.drawing.frames.get(i) else {
                continue;
            };
            let (hx, hy) = (f.x + f.w, f.y + f.h);
            if (wx - hx).abs() <= 1.2 + r * 0.3 && (wy - hy).abs() <= 1.2 + r * 0.3 {
                self.op = Some(op(OpKind::Resize {
                    i,
                    snapshot: Box::new(self.drawing.clone()),
                    frame: None,
                }));
                return;
            }
        }
        let t = self.scene.hit(&self.drawing, wx, wy, r, None);
        let Some(t) = t else {
            self.op = Some(op(OpKind::Box {
                a: (wx, wy),
                add: shift,
            }));
            return;
        };
        if let Hit::Pin { i, .. } = t {
            let p = &self.scene.pins[i];
            self.op = Some(op(OpKind::PinWire {
                from: (p.x, p.y),
                pin: i,
            }));
            return;
        }
        if let Hit::Wire { i, j, net, .. } = t
            && !shift
            && !(self.sel.wires.contains(&i) && self.sel.size() > 1)
        {
            // A wire on its own: dragging moves the segment under the pointer sideways.
            self.select(Sel::only(Item::Wire(i)), net);
            self.op = Some(op(OpKind::Segment {
                wi: i,
                j,
                w0: (wx, wy),
                snapshot: Box::new(self.drawing.clone()),
                last: (0.0, 0.0),
            }));
            return;
        }
        let item = item_of(&t);
        let mut sel = self.sel.clone();
        if shift {
            sel.toggle(&item);
        } else if !sel.has(&item) {
            sel = Sel::only(item);
        }
        self.select(sel.clone(), t.net());
        self.op = Some(op(OpKind::Move {
            w0: (wx, wy),
            sel,
            snapshot: Box::new(self.drawing.clone()),
            last: (0.0, 0.0),
        }));
    }

    /// The left button went down on frame `i`'s title.
    pub fn frame_down(&mut self, i: usize, sx: f64, sy: f64, shift: bool) -> bool {
        if self.mode != Mode::Select || i >= self.drawing.frames.len() {
            return false;
        }
        let sel = if shift {
            let mut s = self.sel.clone();
            s.toggle(&Item::Frame(i));
            s
        } else {
            frame_contents(&self.drawing, i)
        };
        self.select(sel.clone(), -1);
        let w0 = self.cam.to_world(sx, sy);
        self.op = Some(Op {
            kind: OpKind::Move {
                w0,
                sel,
                snapshot: Box::new(self.drawing.clone()),
                last: (0.0, 0.0),
            },
            sx,
            sy,
            moved: false,
        });
        true
    }

    /// The pointer moved (a button held or not).
    pub fn moved(&mut self, sx: f64, sy: f64) {
        self.world = self.cam.to_world(sx, sy);
        self.last_screen = Some((sx, sy));
        let world = self.world;
        let Some(op) = self.op.as_mut() else { return };
        if !op.moved && (sx - op.sx).hypot(sy - op.sy) > DRAG_PX {
            op.moved = true;
        }
        if !op.moved {
            return;
        }
        let preview = match &mut op.kind {
            OpKind::Move {
                w0,
                sel,
                snapshot,
                last,
            } => {
                let (dx, dy) = (snap(world.0 - w0.0), snap(world.1 - w0.1));
                if (dx, dy) == *last {
                    return;
                }
                *last = (dx, dy);
                let mut tmp = (**snapshot).clone();
                move_items(&mut tmp, sel, dx, dy);
                tmp
            }
            OpKind::Segment {
                wi,
                j,
                w0,
                snapshot,
                last,
            } => {
                let (dx, dy) = (snap(world.0 - w0.0), snap(world.1 - w0.1));
                if (dx, dy) == *last {
                    return;
                }
                *last = (dx, dy);
                let mut tmp = (**snapshot).clone();
                drag_segment(&mut tmp, *wi, *j, dx, dy);
                tmp
            }
            OpKind::Resize { i, snapshot, frame } => {
                let mut tmp = (**snapshot).clone();
                let f = &snapshot.frames[*i];
                let w = snap(world.0 - f.x).max(20.0);
                let h = snap(world.1 - f.y).max(15.0);
                tmp.frames[*i].w = w;
                tmp.frames[*i].h = h;
                *frame = Some((w, h));
                tmp
            }
            _ => return,
        };
        let sc = Scene::build(&preview, &self.analysis, true);
        self.preview = Some((preview, sc));
    }

    /// The left button came up.
    pub fn up(&mut self, sx: f64, sy: f64) {
        let Some(op) = self.op.take() else { return };
        self.preview = None;
        match op.kind {
            OpKind::Move {
                sel,
                snapshot,
                last,
                ..
            } => {
                if op.moved && last != (0.0, 0.0) {
                    let n = sel.size();
                    self.drawing = *snapshot; // the drag previewed a copy
                    let what = if n == 1 {
                        sel.describe()
                    } else {
                        format!("{n} items")
                    };
                    self.apply(&format!("move {what}"), |d| {
                        move_items(d, &sel, last.0, last.1)
                    });
                }
            }
            OpKind::Segment {
                wi,
                j,
                snapshot,
                last,
                ..
            } => {
                if op.moved && last != (0.0, 0.0) {
                    self.drawing = *snapshot;
                    self.apply("drag a wire", |d| drag_segment(d, wi, j, last.0, last.1));
                }
            }
            OpKind::Resize { i, snapshot, frame } => {
                if let Some((w, h)) = frame {
                    let title = snapshot.frames[i].title.clone();
                    self.drawing = *snapshot;
                    self.apply(&format!("resize {title}"), |d| {
                        d.frames[i].w = w;
                        d.frames[i].h = h;
                    });
                }
            }
            OpKind::Box { a, add } => {
                if !op.moved {
                    self.select(Sel::default(), -1);
                    return;
                }
                let (x1, y1) = self.world;
                let got = select_box(
                    &self.drawing,
                    [a.0.min(x1), a.1.min(y1), a.0.max(x1), a.1.max(y1)],
                );
                let sel = if add { self.sel.union(&got) } else { got };
                self.select(sel, -1);
            }
            OpKind::Frame { a } => {
                if !op.moved {
                    return;
                }
                let (x1, y1) = (snap(self.world.0), snap(self.world.1));
                let b = [a.0.min(x1), a.1.min(y1), (x1 - a.0).abs(), (y1 - a.1).abs()];
                if b[2] < 10.0 || b[3] < 10.0 {
                    return;
                }
                let (tx, ty) = self.cam.to_screen(b[0], b[1]);
                self.prompt = Some(Prompt {
                    ask: Ask::Frame(b),
                    title: "Section name".into(),
                    initial: format!("section {}", self.drawing.frames.len() + 1),
                    options: Vec::new(),
                    at: (tx, ty - 26.0),
                });
            }
            OpKind::PinWire { from, pin } => {
                let p = &self.scene.pins[pin];
                let (r, name, net) = (p.r.clone(), p.name.clone(), p.net);
                if !op.moved {
                    self.select(Sel::symbol(&r), net);
                    return;
                }
                let to = self.point_at(sx, sy, true);
                let pts = route(from, to, (to.0 - from.0).abs() >= (to.1 - from.1).abs());
                self.apply(&format!("wire from {r}.{name}"), |d| {
                    add_wire(d, &pts);
                });
            }
        }
    }

    /// A double click (after its two clicks went down and up).
    pub fn double_click(&mut self, sx: f64, sy: f64) {
        if self.mode == Mode::Wire {
            self.finish_wire();
            return;
        }
        if self.mode != Mode::Select {
            return;
        }
        let (wx, wy) = self.cam.to_world(sx, sy);
        if let Some(Hit::Label { i, .. }) =
            self.scene
                .hit(&self.drawing, wx, wy, 7.0 / self.cam.k, None)
        {
            self.prompt = Some(Prompt {
                ask: Ask::RenameLabel(i),
                title: "Net name".into(),
                initial: self.drawing.labels[i].name.clone(),
                options: Vec::new(),
                at: (sx + 8.0, sy - 14.0),
            });
        }
    }

    /// Hover at a canvas point (no button held): what is under it.
    pub fn hover_at(&mut self, sx: f64, sy: f64) {
        self.world = self.cam.to_world(sx, sy);
        self.last_screen = Some((sx, sy));
        self.hover = if self.mode == Mode::Select && self.op.is_none() {
            let (wx, wy) = self.world;
            self.scene
                .hit(&self.drawing, wx, wy, 7.0 / self.cam.k, None)
        } else {
            None
        };
    }

    pub fn leave(&mut self) {
        self.hover = None;
        self.last_screen = None;
    }

    /// What the tools draw over the drawing now.
    pub fn ghost(&self) -> Option<Ghost> {
        if let Some(op) = &self.op {
            if !op.moved {
                return None;
            }
            let (x1, y1) = self.world;
            return match &op.kind {
                OpKind::Box { a, .. } => Some(Ghost::Box([
                    a.0.min(x1),
                    a.1.min(y1),
                    a.0.max(x1),
                    a.1.max(y1),
                ])),
                OpKind::Frame { a } => {
                    let (x1, y1) = (snap(x1), snap(y1));
                    Some(Ghost::FrameBox([
                        a.0.min(x1),
                        a.1.min(y1),
                        a.0.max(x1),
                        a.1.max(y1),
                    ]))
                }
                OpKind::PinWire { from, .. } => {
                    let (sx, sy) = self.last_screen?;
                    let p = self.point_at(sx, sy, true);
                    let pts = route(*from, p, (p.0 - from.0).abs() >= (p.1 - from.1).abs());
                    Some(Ghost::Wire { pts, cursor: p })
                }
                _ => None,
            };
        }
        let (sx, sy) = self.last_screen?;
        match self.mode {
            Mode::Place => {
                let pl = self.place.as_ref()?;
                let (x, y) = self.point_at(sx, sy, false);
                Some(Ghost::Part {
                    name: pl.name.clone(),
                    pl: Placement {
                        x,
                        y,
                        rot: pl.rot,
                        mirror: pl.mirror,
                    },
                })
            }
            Mode::Wire => {
                let p = self.point_at(sx, sy, true);
                let pts = match &self.wire {
                    Some(w) => {
                        let mut pts = w.pts.clone();
                        pts.extend(route(*w.pts.last()?, p, w.hfirst).into_iter().skip(1));
                        pts
                    }
                    None => Vec::new(),
                };
                Some(Ghost::Wire { pts, cursor: p })
            }
            Mode::Label => Some(Ghost::Cursor(self.point_at(sx, sy, true))),
            Mode::Ground => {
                let p = self.point_at(sx, sy, true);
                Some(Ghost::Ground(Placement {
                    x: p.0,
                    y: p.1,
                    rot: self.auto_rot(p, &GROUND_ROT),
                    mirror: false,
                }))
            }
            Mode::Frame => Some(Ghost::Cursor(self.point_at(sx, sy, false))),
            Mode::Select => None,
        }
    }

    fn place_at(&mut self, p: Pt) {
        let Some(pl) = self.place.clone() else { return };
        let mut got = None;
        self.apply(&format!("place {}", pl.name), |d| {
            got = place_symbol(d, &pl.name, p.0, p.1, pl.rot, pl.mirror);
        });
        if let Some(r) = got {
            self.select(Sel::symbol(&r), -1);
        }
    }

    fn wire_click(&mut self, p: Pt, double: bool) {
        let Some(w) = self.wire.as_mut() else {
            self.wire = Some(Wiring {
                pts: vec![p],
                hfirst: true,
            });
            return;
        };
        let last = *w.pts.last().expect("a wire has a start");
        if p != last {
            w.pts.extend(route(last, p, w.hfirst).into_iter().skip(1));
            // Ending on something that connects (a pin, another wire, a label) finishes it.
            let t = self.scene.hit(
                &self.drawing,
                p.0,
                p.1,
                0.05,
                Some(&["pin", "wire", "label", "ground"]),
            );
            if t.is_some() || double {
                self.finish_wire();
            }
        } else if double {
            self.finish_wire();
        }
    }

    fn finish_wire(&mut self) {
        let Some(w) = self.wire.take() else { return };
        if w.pts.len() >= 2 {
            self.apply("wire", |d| {
                add_wire(d, &w.pts);
            });
        }
    }

    /// The rotation that points away from the wire a point ends, or from the body of the
    /// pin it is on; else 0.
    fn auto_rot(&self, p: Pt, table: &[((i32, i32), i64); 4]) -> i64 {
        let sign = |v: f64| {
            let v = round4(v);
            if v > 0.0 {
                1
            } else if v < 0.0 {
                -1
            } else {
                0
            }
        };
        let look = |dir: (i32, i32)| table.iter().find(|(d, _)| *d == dir).map(|(_, r)| *r);
        let close = |a: Pt| (a.0 - p.0).abs() < 1e-3 && (a.1 - p.1).abs() < 1e-3;
        for w in &self.drawing.wires {
            let n = w.len();
            for (e, q) in [(w[0], w[1]), (w[n - 1], w[n - 2])] {
                if close(e)
                    && let Some(r) = look((sign(e.0 - q.0), sign(e.1 - q.1)))
                {
                    return r;
                }
            }
        }
        if let Some(pin) = self.scene.pins.iter().find(|q| close((q.x, q.y))) {
            // Away from the body: the pin's line points into it.
            let s = self.drawing.symbol(&pin.r);
            let g = s.and_then(|s| super::scene::geom(&s.symbol));
            let pl = s.and_then(|s| s.unit(pin.unit));
            if let (Some(g), Some(pl)) = (g, pl)
                && let Some(pd) = g
                    .unit_pins(pin.unit)
                    .iter()
                    .find(|q| q.number == pin.number)
            {
                let a = geom::tf(pd.x, pd.y, pl);
                let b = geom::tf(pd.x + pd.into.0, pd.y + pd.into.1, pl);
                if let Some(r) = look((sign(a.0 - b.0), sign(a.1 - b.1))) {
                    return r;
                }
            }
        }
        0
    }

    fn label_at(&mut self, p: Pt, screen: Pt) {
        let mut names: Vec<String> = Vec::new();
        for n in &self.analysis.nets {
            if !n.node.starts_with("n_") && n.node != "0" && !names.contains(&n.node) {
                names.push(n.node.clone());
            }
        }
        self.prompt = Some(Prompt {
            ask: Ask::Label(p),
            title: "Net name".into(),
            initial: String::new(),
            options: names,
            at: (screen.0 + 8.0, screen.1 - 14.0),
        });
    }

    fn ground_at(&mut self, p: Pt) {
        let rot = self.auto_rot(p, &GROUND_ROT);
        self.apply("ground", |d| {
            d.grounds.push(Placement {
                x: p.0,
                y: p.1,
                rot,
                mirror: false,
            })
        });
    }

    /// The answer to the open prompt (None: cancelled).
    pub fn answer(&mut self, text: Option<&str>) {
        let Some(prompt) = self.prompt.take() else {
            return;
        };
        let Some(text) = text.map(str::trim).filter(|t| !t.is_empty()) else {
            return;
        };
        match prompt.ask {
            Ask::Label(p) => {
                if !node_name(text) {
                    self.status = format!("{text}: a node name is letters, digits and _");
                    return;
                }
                let rot = self.auto_rot(p, &LABEL_ROT);
                self.apply(&format!("label {text}"), |d| {
                    d.labels.push(Label {
                        name: text.into(),
                        x: p.0,
                        y: p.1,
                        rot,
                    })
                });
            }
            Ask::RenameLabel(i) => {
                let old = self.drawing.labels[i].name.clone();
                if text != old {
                    self.apply(&format!("rename {old} → {text}"), |d| {
                        d.labels[i].name = text.into()
                    });
                }
            }
            Ask::Frame(b) => {
                if self.drawing.frames.iter().any(|f| f.title == text) {
                    self.status = format!("a section is already called {text}");
                    return;
                }
                self.apply(&format!("section {text}"), |d| {
                    d.frames.push(Frame {
                        title: text.into(),
                        x: b[0],
                        y: b[1],
                        w: b[2],
                        h: b[3],
                    })
                });
                self.set_mode(Mode::Select, None);
            }
            Ask::RenameFrame(i) => {
                let old = self.drawing.frames[i].title.clone();
                if text != old && !self.drawing.frames.iter().any(|f| f.title == text) {
                    self.apply(&format!("rename section {old} → {text}"), |d| {
                        d.frames[i].title = text.into()
                    });
                }
            }
        }
    }

    /// Ask for a frame's new title.
    pub fn rename_frame(&mut self, i: usize, at: Pt) {
        if let Some(f) = self.drawing.frames.get(i) {
            self.prompt = Some(Prompt {
                ask: Ask::RenameFrame(i),
                title: "Section name".into(),
                initial: f.title.clone(),
                options: Vec::new(),
                at,
            });
        }
    }

    /// Handle a key; true when it was the tools'.
    pub fn key(&mut self, k: Key, m: Mods) -> bool {
        let ch = match k {
            Key::Char(c) => Some(c.to_ascii_lowercase()),
            _ => None,
        };
        if k == Key::Escape {
            if self.mode == Mode::Wire && self.wire.is_some() {
                if self.wire.as_ref().is_some_and(|w| w.pts.len() >= 2) {
                    self.finish_wire();
                } else {
                    self.wire = None;
                }
                return true;
            }
            if self.mode != Mode::Select {
                self.set_mode(Mode::Select, None);
                return true;
            }
            return false;
        }
        if self.mode == Mode::Wire && k == Key::Enter {
            self.finish_wire();
            return true;
        }
        if self.mode == Mode::Wire && ch == Some('/') {
            if let Some(w) = &mut self.wire {
                w.hfirst = !w.hfirst;
            }
            return true;
        }
        if self.mode == Mode::Place
            && let Some(p) = &mut self.place
        {
            if ch == Some('r') {
                p.rot = (p.rot + 90) % 360;
                return true;
            }
            if ch == Some('x') {
                p.mirror = !p.mirror;
                return true;
            }
        }
        if !m.ctrl && !m.alt {
            let mode = match ch {
                Some('v') => Some(Mode::Select),
                Some('w') => Some(Mode::Wire),
                Some('l') => Some(Mode::Label),
                Some('g') => Some(Mode::Ground),
                Some('s') => Some(Mode::Frame),
                _ => None,
            };
            if let Some(mode) = mode {
                self.set_mode(mode, None);
                return true;
            }
        }
        if self.mode != Mode::Select {
            return false;
        }
        let sel = self.sel.clone();
        let n = sel.size();
        let what = if n == 1 {
            sel.describe()
        } else {
            format!("{n} items")
        };
        if k == Key::Delete && n > 0 {
            self.apply(&format!("delete {what}"), |d| delete_items(d, &sel));
            self.select(Sel::default(), -1);
            return true;
        }
        if !m.ctrl && n > 0 && (ch == Some('r') || ch == Some('x')) {
            let mirror = ch == Some('x');
            let verb = if mirror { "mirror" } else { "rotate" };
            self.apply(&format!("{verb} {}", sel.describe()), |d| {
                turn_items(d, &sel, mirror)
            });
            return true;
        }
        let nudge = match k {
            Key::Left => Some((-1.0, 0.0)),
            Key::Right => Some((1.0, 0.0)),
            Key::Up => Some((0.0, -1.0)),
            Key::Down => Some((0.0, 1.0)),
            _ => None,
        };
        if let Some((nx, ny)) = nudge
            && n > 0
        {
            let step = if m.shift { 5.0 } else { 1.0 } * 1.27;
            self.apply(&format!("nudge {}", sel.describe()), |d| {
                move_items(d, &sel, nx * step, ny * step)
            });
            return true;
        }
        if m.ctrl && (ch == Some('c') || ch == Some('x')) && n > 0 {
            self.clip = copy_items(&self.drawing, &sel);
            if ch == Some('x') {
                self.apply(&format!("cut {n} items"), |d| delete_items(d, &sel));
                self.select(Sel::default(), -1);
            } else {
                self.status = format!("copied {n} item{}", if n > 1 { "s" } else { "" });
            }
            return true;
        }
        if m.ctrl && ch == Some('v') {
            if let Some(clip) = self.clip.clone() {
                let at = self.world;
                self.paste(&clip, at);
            }
            return true;
        }
        if m.ctrl && ch == Some('d') && n > 0 {
            if let (Some(clip), Some(b)) = (
                copy_items(&self.drawing, &sel),
                geom::sel_bounds(&self.drawing, &sel),
            ) {
                self.paste(&clip, (b.0 + 5.08, b.1 + 5.08));
            }
            return true;
        }
        if m.ctrl && ch == Some('a') {
            self.select(Sel::all(&self.drawing), -1);
            return true;
        }
        false
    }

    pub fn paste(&mut self, clip: &Clip, at: Pt) {
        let mut got = None;
        self.apply(&format!("paste {} parts", clip.symbols.len()), |d| {
            got = Some(paste_items(d, clip, at.0, at.1));
        });
        if let Some(sel) = got {
            self.select(sel, -1);
        }
    }

    // --- The inspector's edits ----------------------------------------------------------

    /// The value field of part `r` as the inspector shows it.
    pub fn value_form(&self, r: &str) -> Option<ValueForm> {
        let s = self.drawing.symbol(r)?;
        let sym = symbols::get(&s.symbol)?;
        let key = value_key(s);
        let p = key.as_deref().and_then(|k| self.analysis.param(k));
        let num = parse_num(&s.value);
        let shown = match (num, p.and_then(|p| p.value())) {
            (Some(_), _) => s.value.clone(),
            (None, Some(v @ (Value::Int(_) | Value::Float(_)))) => value_text(v),
            _ => s.value.clone(),
        };
        let source = match s.field("Source") {
            Some(x) => x.to_string(),
            None if s.field("Param").is_some() => {
                let k = key.clone().unwrap_or_default();
                self.drawing
                    .symbols
                    .iter()
                    .find_map(|(_, o)| {
                        (o.field("Param") == Some(k.as_str()))
                            .then(|| o.field("Source").filter(|x| !x.is_empty()))
                            .flatten()
                    })
                    .unwrap_or("")
                    .to_string()
            }
            None => p.and_then(|p| p.text("source")).unwrap_or_default(),
        };
        Some(ValueForm {
            derived: p.is_some_and(|p| p.kind == "derived"),
            unit: super::eng::unit_of(key.as_deref(), sym.primary),
            key,
            shown,
            source,
        })
    }

    /// Commit part `r`'s value field: a number (with `source`) or another parameter's
    /// key. Err: neither (nothing applied).
    pub fn commit_value(&mut self, r: &str, text: &str, source: &str) -> Result<(), String> {
        let form = self.value_form(r).ok_or("no such part")?;
        let text = text.trim().to_string();
        let src = source.trim().to_string();
        let x = parse_num(&text);
        if x.is_none() && self.analysis.param(&text).is_none() {
            return Err("not a number (40u, 4k7, 2.2e-9) or a parameter key".into());
        }
        let key = form.key.clone();
        let r2 = r.to_string();
        self.apply(&format!("{r} {} → {text}", form.shown), |d| {
            let has_param = d
                .symbol(&r2)
                .and_then(|s| s.field("Param"))
                .map(str::to_string);
            match x {
                None => {
                    let s = d.symbol_mut(&r2).expect("the part");
                    for k in ["Param", "Source", "Genome"] {
                        s.remove_field(k);
                    }
                    s.value = text.clone();
                }
                Some(x) => {
                    if let Some(p) = has_param {
                        set_param(d, &p, &number_value(x), Some(&src));
                    } else if let Some(k) = key.as_deref().filter(|k| param_home(d, k).is_some()) {
                        set_param(d, k, &number_value(x), Some(&src));
                    } else {
                        set_inline(d, &r2, &text, &src);
                    }
                }
            }
        });
        Ok(())
    }

    /// Step part `r`'s value to the next standard value up (`dir` 1) or down (-1) in the
    /// E12 (or E24) series, its source saying it was by ear; the new text, if any.
    pub fn step_value(&mut self, r: &str, text: &str, dir: i32, e24: bool) -> Option<String> {
        let form = self.value_form(r)?;
        if form.derived {
            return None;
        }
        let x = parse_num(text).or_else(|| {
            form.key
                .as_deref()
                .and_then(|k| self.analysis.param(k))
                .and_then(|p| p.value())
                .and_then(Value::as_f64)
        })?;
        if x <= 0.0 {
            return None;
        }
        let t = eng_text(step_e(x, dir, if e24 { 24 } else { 12 }));
        let src = edit_source(&form.shown, &form.source);
        self.commit_value(r, &t, &src).ok()?;
        Some(t)
    }

    /// The source field changed alone (the value as it was).
    pub fn commit_source(&mut self, r: &str, text: &str) {
        let t = text.trim().to_string();
        let key = self.drawing.symbol(r).and_then(value_key);
        let r2 = r.to_string();
        self.apply(&format!("source of {r}"), |d| {
            let param = d
                .symbol(&r2)
                .and_then(|s| s.field("Param"))
                .map(str::to_string);
            if let Some(p) = param {
                for (_, o) in d.symbols.iter_mut() {
                    if o.field("Param") == Some(p.as_str()) {
                        o.set_field("Source", &t);
                    }
                }
            } else if let Some(k) = key.as_deref()
                && let Some(Home::Entry(kind)) = param_home(d, k)
            {
                entry_mut(d, kind, k)
                    .expect("entry")
                    .insert("source", Value::Str(t.clone()));
            } else if let Some(s) = d.symbol_mut(&r2) {
                s.set_field("Source", &t);
            }
        });
    }

    /// Rename part `r` (windings follow a renamed core).
    pub fn rename(&mut self, r: &str, to: &str) -> Result<(), String> {
        let to = to.trim();
        if to == r {
            return Ok(());
        }
        if self.drawing.symbol(to).is_some() {
            return Err(format!("{to} is taken"));
        }
        if !geom::valid_ref(to) {
            return Err("letters, digits and _".into());
        }
        self.apply(&format!("rename {r} → {to}"), |d| {
            rename_ref(d, r, to);
        });
        let net = self.net;
        self.select(Sel::symbol(to), net.min(-1));
        Ok(())
    }

    /// Set (or, empty, remove) a field of part `r`.
    pub fn set_field(&mut self, r: &str, name: &str, value: &str) {
        let v = value.trim();
        let label = if name == "Transformer" || name == "Control" {
            format!("{r} {name} → {}", if v.is_empty() { "–" } else { v })
        } else {
            format!("{r} {name}")
        };
        self.apply(&label, |d| {
            if let Some(s) = d.symbol_mut(r) {
                if v.is_empty() {
                    s.remove_field(name);
                } else {
                    s.set_field(name, v);
                }
            }
        });
    }

    /// A winding's label (its Value).
    pub fn set_label_value(&mut self, r: &str, v: &str) {
        let v = v.trim();
        if v.is_empty() || self.drawing.symbol(r).is_some_and(|s| s.value == v) {
            return;
        }
        self.apply(&format!("{r} label → {v}"), |d| {
            if let Some(s) = d.symbol_mut(r) {
                s.value = v.into();
            }
        });
    }

    /// Take part `r` off its shared parameter.
    pub fn unlink(&mut self, r: &str) {
        let p = self
            .drawing
            .symbol(r)
            .and_then(|s| s.field("Param"))
            .unwrap_or("")
            .to_string();
        self.apply(&format!("{r} off {p}"), |d| unlink(d, r));
    }

    /// Swap a tube's or diode's device file.
    pub fn set_device(&mut self, r: &str, name: &str) {
        let Some(s) = self.drawing.symbol(r) else {
            return;
        };
        let p = self.analysis.param(&s.value).cloned();
        let old = p
            .as_ref()
            .and_then(|p| p.value())
            .map_or(s.value.clone(), Value::py_str);
        let value = s.value.clone();
        self.apply(&format!("{r} {old} → {name}"), |d| {
            if let Some(p) = p.as_ref().filter(|_| param_home(d, &value).is_some()) {
                let src = edit_source(&old, &p.text("source").unwrap_or_default());
                set_param(d, &value, &Value::Str(name.into()), Some(&src));
            } else if let Some(s) = d.symbol_mut(r) {
                let src = edit_source(&old, s.field("Source").unwrap_or(""));
                s.value = name.into();
                s.set_field("Source", &src);
            }
        });
    }

    /// Set parameter `k` (a part's other parameter, by key) to `value`, its source an
    /// edit's.
    pub fn set_param_value(&mut self, k: &str, value: Value) {
        let Some(p) = self.analysis.param(k).cloned() else {
            return;
        };
        let old = p.value().map(value_text).unwrap_or_default();
        if p.value().is_some_and(|v| v.py_eq(&value)) {
            return;
        }
        let src = edit_source(&old, &p.text("source").unwrap_or_default());
        let new = value_text(&value);
        self.apply(&format!("{k} {old} → {new}"), |d| {
            set_param(d, k, &value, Some(&src));
        });
    }

    /// A front-panel control's value (its source stays the panel's).
    pub fn set_control(&mut self, k: &str, value: Value) {
        let old = self
            .drawing
            .circuit
            .get("controls")
            .and_then(Value::as_map)
            .and_then(|c| c.get(k))
            .and_then(Value::as_map)
            .and_then(|e| e.get("value"))
            .cloned()
            .unwrap_or(Value::Null);
        if old.py_eq(&value) {
            return;
        }
        let fmt = |v: &Value| match v.as_f64() {
            Some(x) if !matches!(v, Value::Int(_)) => {
                super::eng::js_str(super::eng::to_precision(x, 3))
            }
            _ => value_text(v),
        };
        self.apply(&format!("{k} {} → {}", fmt(&old), fmt(&value)), |d| {
            set_param(d, k, &value, None);
        });
    }

    /// The circuit's title or input node (strings), or its probes (a list).
    pub fn set_circuit(&mut self, k: &str, v: Value) {
        let current = self.drawing.circuit.get(k).cloned().unwrap_or(match k {
            "probes" => Value::List(Vec::new()),
            _ => Value::Str(String::new()),
        });
        if current == v {
            return;
        }
        self.apply(&format!("circuit {k}"), |d| d.circuit.insert(k, v));
    }

    /// Add a control: `range` "0..1" (a knob) or "1,2,3" (a switch's positions).
    pub fn add_control(&mut self, key: &str, range: &str, source: &str) -> Result<(), String> {
        let (key, range, source) = (key.trim(), range.trim(), source.trim());
        let key_ok = key.starts_with(|c: char| c.is_ascii_lowercase() || c == '_')
            && key
                .chars()
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_');
        if !key_ok || range.is_empty() || source.is_empty() {
            return Err("a key (lowercase), a range and a source".into());
        }
        let num = |t: &str| t.trim().parse::<f64>().ok().filter(|x| x.is_finite());
        let entry = match range
            .split_once("..")
            .and_then(|(a, b)| Some((num(a)?, num(b)?)))
        {
            Some((a, b)) => Map(vec![
                ("value".into(), number_value(a)),
                ("min".into(), number_value(a)),
                ("max".into(), number_value(b)),
                ("source".into(), Value::Str(source.into())),
            ]),
            None => {
                let choices: Vec<Value> = range
                    .split(',')
                    .map(str::trim)
                    .filter(|x| !x.is_empty())
                    .map(|x| num(x).map_or(Value::Str(x.into()), number_value))
                    .collect();
                if choices.is_empty() {
                    return Err("no positions".into());
                }
                Map(vec![
                    ("value".into(), choices[0].clone()),
                    ("choices".into(), Value::List(choices)),
                    ("unit".into(), Value::Str("position".into())),
                    ("source".into(), Value::Str(source.into())),
                ])
            }
        };
        self.apply(&format!("add control {key}"), |d| {
            let mut c = d
                .circuit
                .get("controls")
                .and_then(Value::as_map)
                .cloned()
                .unwrap_or_default();
            c.insert(key, Value::Map(entry));
            d.circuit.insert("controls", Value::Map(c));
        });
        Ok(())
    }

    pub fn remove_control(&mut self, key: &str) {
        self.apply(&format!("remove control {key}"), |d| {
            if let Some(Value::Map(c)) = d.circuit.get_mut("controls") {
                c.remove(key);
            }
        });
    }
}

/// A part's value field: the text shown, its source, the parameter it is.
#[derive(Debug, Clone, PartialEq)]
pub struct ValueForm {
    pub shown: String,
    pub source: String,
    pub key: Option<String>,
    pub unit: &'static str,
    /// A derived value: read-only.
    pub derived: bool,
}

impl ValueForm {
    /// The source to offer for value `text` when the source wasn't touched: an edit's
    /// for a new value, the old one for the old value.
    pub fn default_source(&self, text: &str) -> String {
        if text.trim() == self.shown {
            self.source.clone()
        } else {
            edit_source(&self.shown, &self.source)
        }
    }
}

const LABEL_ROT: [((i32, i32), i64); 4] =
    [((1, 0), 0), ((0, -1), 90), ((-1, 0), 180), ((0, 1), 270)];
const GROUND_ROT: [((i32, i32), i64); 4] =
    [((0, 1), 0), ((1, 0), 90), ((0, -1), 180), ((-1, 0), 270)];

fn node_name(t: &str) -> bool {
    let mut c = t.chars();
    c.next()
        .is_some_and(|f| f.is_ascii_alphabetic() || f == '_')
        && c.all(|x| x.is_ascii_alphanumeric() || x == '_')
}

fn item_of(t: &Hit) -> Item {
    match t {
        Hit::Symbol { r, .. } => Item::Symbol(r.clone()),
        Hit::Wire { i, .. } => Item::Wire(*i),
        Hit::Label { i, .. } => Item::Label(*i),
        Hit::Ground { i, .. } => Item::Ground(*i),
        Hit::Pin { .. } => unreachable!("a pin starts a wire"),
    }
}

/// Whether a symbol is a switch deck (its spare contacts need no wire).
pub fn is_switch(name: &str) -> bool {
    symbols::get(name).is_some_and(|s| s.kind == Kind::Switch)
}
