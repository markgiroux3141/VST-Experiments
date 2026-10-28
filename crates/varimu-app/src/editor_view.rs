//! The Editor view (R3b, R3c): the schematic editor of the web page `/editor`, painted
//! with egui in the dark "studio" look (docs/editor_mockups/). The logic is the
//! library's `varimu_app::editor` (the page's, ported); this file paints it and turns
//! mouse and keys into its calls.
//!
//! Layout as the page: a bar (circuit, tools, undo / redo, Save as, the checks), the
//! left column (find, problems, the parts palette, the front panel, sections), the
//! canvas, the inspector on the right, and the listen bar: the drawing plays through
//! the Play view's file and loop region, each edit heard as it is made.

use std::collections::HashSet;

use eframe::egui::{
    self, Align2, Color32, CornerRadius, FontId, Id, Pos2, Rect, RichText, Sense, Shape, Stroke,
    StrokeKind, Vec2,
};
use varimu_app::editor::Editor;
use varimu_app::editor::camera::Camera;
use varimu_app::editor::eng::{
    js_str, number_value, parse_num, to_precision, value_text, with_unit,
};
use varimu_app::editor::geom::{Pt, Sel, tf};
use varimu_app::editor::scene::{Anchor, Hit, Shape as Sym, SymGeom, TextKind, geom};
use varimu_app::editor::session::{
    Checking, Ghost, Key, Listed, Mode, Mods, Origin, ValueForm, list_circuits,
};
use varimu_circuit::drawing::Placement;
use varimu_circuit::symbols::{self, Kind};
use varimu_circuit::yaml::Value;

use crate::play_view::{DrawingDevice, PlayView};
use crate::theme;

/// Points per mm below which part names, values and labels are hidden.
const FAR_K: f64 = 2.6;

/// The parts palette: (symbol, label).
const PALETTE: [(&str, &str); 21] = [
    ("R", "R"),
    ("C", "C"),
    ("L", "L"),
    ("Pot", "Pot"),
    ("Rheostat", "Rheostat"),
    ("Pot_Tapped", "Tapped"),
    ("T_Pad", "T-pad"),
    ("Triode", "Triode"),
    ("Triode_Dual", "Dual"),
    ("Pentode", "Pentode"),
    ("Diode", "Diode"),
    ("Diode_Dual", "Dual diode"),
    ("Bridge", "Bridge"),
    ("VR_Tube", "VR tube"),
    ("Winding", "Winding"),
    ("Core", "Core"),
    ("K", "Coupling"),
    ("V", "DC"),
    ("Sine", "Sine"),
    ("Mains", "Mains"),
    ("SW_Rotary_3", "Rotary"),
];

const SHORTCUTS: [(&str, &[(&str, &str)]); 6] = [
    (
        "Drawing",
        &[
            ("V", "select"),
            ("W", "wire"),
            ("L", "label a net"),
            ("G", "ground"),
            ("S", "section frame"),
            ("Ctrl K", "command palette: place parts, tools, find"),
            ("Esc", "back to select, clear"),
        ],
    ),
    (
        "Selection",
        &[
            ("click / Shift click", "select / add"),
            ("drag", "move (wires follow)"),
            ("drag on empty", "box select"),
            ("drag a wire", "move its segment"),
            ("drag from a pin", "draw a wire"),
            ("R / X", "rotate / mirror"),
            ("arrows", "nudge (Shift: 5 grid)"),
            ("Del", "delete"),
            ("Ctrl C / X / V / D / A", "copy, cut, paste, duplicate, all"),
        ],
    ),
    (
        "Wiring",
        &[
            ("click", "corner"),
            ("/", "flip the corner"),
            ("Enter / double click", "finish"),
            ("Esc", "finish or cancel"),
        ],
    ),
    (
        "View",
        &[
            ("wheel", "zoom"),
            ("right or middle drag, Space drag", "pan"),
            ("F", "fit"),
            ("Z", "zoom to the selection"),
            ("+ / -", "zoom"),
            ("/", "find a part or node"),
        ],
    ),
    (
        "Values",
        &[
            (
                "↑ / ↓ in a value",
                "next standard value (E12; Shift: E24), heard at once",
            ),
            ("Enter", "apply"),
            ("Esc", "revert"),
        ],
    ),
    (
        "Listening and file",
        &[
            ("Space tap", "play / stop the drawing"),
            ("Ctrl Z / Ctrl Shift Z", "undo / redo"),
            ("Ctrl S", "save as a circuit"),
        ],
    ),
];

/// What the command palette runs.
#[derive(Debug, Clone)]
enum Cmd {
    Place(String),
    Tool(Mode),
    Frame(usize),
    Part(String),
    Net(usize),
    Fit,
    Save,
    Undo,
    Redo,
    Keys,
    New,
    Play,
}

/// What opening another circuit would do (asked first when there are unsaved edits).
#[derive(Debug, Clone)]
enum Leave {
    Open(String),
    New,
    File,
}

/// The inspector's fields for the selection, as typed.
#[derive(Default)]
struct Form {
    /// What it was built for: the selected parts, the net, the drawing's revision.
    key: (Vec<String>, i64, u64),
    reference: String,
    value: String,
    source: String,
    touched: bool,
    base: Option<ValueForm>,
    label: String,
    raw: Vec<(String, String)>,
    params: Vec<(String, String)>,
    title: String,
    input: String,
    probes: String,
    error: Option<String>,
}

pub struct EditorView {
    pub ed: Editor,
    circuits: Vec<Listed>,
    find: String,
    focus_find: bool,
    form: Form,
    prompt_text: String,
    prompt_shown: bool,
    /// The prompt has taken the focus (after the click that opened it was released:
    /// its release would take the focus away again).
    prompt_armed: bool,
    prompt_rect: Rect,
    /// The Save as box: the name typed and the last error.
    save: Option<(String, String)>,
    help: bool,
    palette: Option<(String, usize)>,
    rotary: bool,
    leave: Option<Leave>,
    /// The space bar held (true once it panned).
    space: Option<bool>,
    pan: Option<(Pos2, f64, f64)>,
    /// The left button went down on the canvas (the tools' drag).
    left: bool,
    /// Frame titles on screen, for clicks.
    titles: Vec<(usize, Rect)>,
    /// The canvas on screen.
    canvas_rect: Rect,
    refit: bool,
    /// The drawing's revision last handed to the player.
    sent: u64,
    new_ctl: (String, String, String),
    new_field: (String, String),
    /// A front-panel slider being dragged: its key and value.
    ctl_drag: Option<(String, f64)>,
}

impl EditorView {
    /// The editor on `config_dir`, opening `name` (a drawn circuit) if it exists.
    pub fn new(config_dir: &std::path::Path, name: &str) -> EditorView {
        let mut ed = Editor::new(config_dir);
        let circuits = list_circuits(&ed.circuits_dir);
        if circuits.iter().any(|c| c.name == name) {
            if let Err(e) = ed.open(name) {
                ed.status = e;
            }
        } else if let Some(c) = circuits.first() {
            let _ = ed.open(&c.name.clone());
        }
        EditorView {
            ed,
            circuits,
            find: String::new(),
            focus_find: false,
            form: Form::default(),
            prompt_text: String::new(),
            prompt_shown: false,
            prompt_armed: false,
            prompt_rect: Rect::NOTHING,
            save: None,
            help: false,
            palette: None,
            rotary: false,
            leave: None,
            space: None,
            pan: None,
            left: false,
            titles: Vec::new(),
            canvas_rect: Rect::NOTHING,
            refit: true,
            sent: 0,
            new_ctl: Default::default(),
            new_field: Default::default(),
            ctl_drag: None,
        }
    }

    /// Hand the player the drawing when it changed and can be heard.
    pub fn sync_player(&mut self, play: &mut PlayView) {
        if self.ed.revision == self.sent {
            return;
        }
        self.sent = self.ed.revision;
        if let Some(spec) = self.ed.playable() {
            play.set_drawing(DrawingDevice {
                name: self.ed.name.clone(),
                title: spec.title.clone(),
                spec,
                lib: self.ed.lib.clone(),
            });
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui, play: &mut PlayView) {
        let ctx = ui.ctx().clone();
        if self.ed.poll() {
            ctx.request_repaint();
        }
        play.tick(&ctx);
        if self.ed.cam.tick() {
            ctx.request_repaint();
        }
        if self.ed.checking == Checking::Busy {
            ctx.request_repaint_after(std::time::Duration::from_millis(100));
        }
        self.keys(&ctx, play);
        // A drawing file dropped on the window opens as a new, unsaved drawing.
        let dropped = ctx.input(|i| i.raw.dropped_files.iter().find_map(|f| f.path.clone()));
        if let Some(path) = dropped {
            if let Err(e) = self.ed.open_file(&path) {
                self.ed.status = e;
            }
            self.refit = true;
        }
        egui::Panel::top("ed_bar")
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(12, 7))
                    .stroke(Stroke::new(1.0, theme::LINE)),
            )
            .show(ui, |ui| self.bar(ui));
        egui::Panel::bottom("ed_listen")
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(12, 6))
                    .stroke(Stroke::new(1.0, theme::LINE)),
            )
            .show(ui, |ui| self.listen_bar(ui, play));
        egui::Panel::left("ed_left")
            .resizable(false)
            .exact_size(236.0)
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(8, 10)),
            )
            .show(ui, |ui| {
                egui::ScrollArea::vertical()
                    .id_salt("ed_left_scroll")
                    .show(ui, |ui| self.left_column(ui));
            });
        egui::Panel::right("ed_right")
            .resizable(false)
            .exact_size(330.0)
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(16, 14)),
            )
            .show(ui, |ui| {
                egui::ScrollArea::vertical()
                    .id_salt("ed_right_scroll")
                    .show(ui, |ui| self.inspector(ui));
            });
        egui::CentralPanel::default()
            .frame(egui::Frame::NONE.fill(theme::CANVAS))
            .show(ui, |ui| self.canvas(ui));
        self.overlays(&ctx, play);
        self.sync_player(play);
    }

    // --- Keys ---------------------------------------------------------------------------

    fn keys(&mut self, ctx: &egui::Context, play: &mut PlayView) {
        if self.help {
            if ctx.input(|i| {
                i.key_pressed(egui::Key::Escape) || i.key_pressed(egui::Key::Questionmark)
            }) {
                self.help = false;
            }
            return;
        }
        if self.palette.is_some()
            || self.save.is_some()
            || self.ed.prompt.is_some()
            || self.leave.is_some()
        {
            return;
        }
        if ctx.egui_wants_keyboard_input() {
            return;
        }
        let events = ctx.input(|i| i.events.clone());
        let ctrl = Mods {
            ctrl: true,
            ..Mods::default()
        };
        for e in events {
            match e {
                egui::Event::Copy => {
                    if self.ed.key(Key::Char('c'), ctrl) {
                        // A system clipboard with text makes Ctrl+V arrive as a paste.
                        ctx.copy_text(self.ed.sel.symbols.join(" "));
                    }
                }
                egui::Event::Cut => {
                    if self.ed.key(Key::Char('x'), ctrl) {
                        ctx.copy_text("varimu parts".into());
                    }
                }
                egui::Event::Paste(_) => {
                    self.ed.key(Key::Char('v'), ctrl);
                }
                egui::Event::Key {
                    key,
                    pressed,
                    repeat,
                    modifiers,
                    ..
                } => {
                    if key == egui::Key::Space {
                        if pressed && !repeat && self.space.is_none() {
                            self.space = Some(false);
                        } else if !pressed {
                            if self.space == Some(false) {
                                play.toggle_drawing(); // a tap plays, a hold pans
                            }
                            self.space = None;
                        }
                        continue;
                    }
                    if !pressed {
                        continue;
                    }
                    let m = Mods {
                        ctrl: modifiers.command,
                        shift: modifiers.shift,
                        alt: modifiers.alt,
                    };
                    self.key(key, m, play);
                }
                _ => {}
            }
        }
    }

    fn key(&mut self, key: egui::Key, m: Mods, play: &mut PlayView) {
        use egui::Key as K;
        if m.ctrl && key == K::K {
            self.palette = Some((String::new(), 0));
            return;
        }
        if key == K::Questionmark {
            self.help = true;
            return;
        }
        if m.ctrl && key == K::Z {
            if m.shift {
                self.ed.redo();
            } else {
                self.ed.undo();
            }
            return;
        }
        if m.ctrl && key == K::Y {
            self.ed.redo();
            return;
        }
        if m.ctrl && key == K::S {
            self.open_save();
            return;
        }
        if m.ctrl && key == K::Enter {
            play.toggle_drawing();
            return;
        }
        let tool = match key {
            K::Escape => Some(Key::Escape),
            K::Enter => Some(Key::Enter),
            K::Delete | K::Backspace => Some(Key::Delete),
            K::ArrowLeft => Some(Key::Left),
            K::ArrowRight => Some(Key::Right),
            K::ArrowUp => Some(Key::Up),
            K::ArrowDown => Some(Key::Down),
            K::Slash => Some(Key::Char('/')),
            k => {
                let name = k.name();
                (name.len() == 1 && name.as_bytes()[0].is_ascii_alphabetic())
                    .then(|| Key::Char(name.chars().next().unwrap_or(' ').to_ascii_lowercase()))
            }
        };
        if let Some(t) = tool
            && self.ed.key(t, m)
        {
            return;
        }
        if m.ctrl {
            return;
        }
        let (w, h) = (self.ed.cam.w, self.ed.cam.h);
        match key {
            K::F => self.ed.fit(true),
            K::Escape => {
                self.ed.select(Sel::default(), -1);
                self.ed.focus = None;
            }
            K::Slash => self.focus_find = true,
            K::Z => {
                if let Some(r) = self.ed.sel.symbols.first().cloned() {
                    self.ed.show_part(&r);
                } else if self.ed.net >= 0 {
                    self.ed.show_net(self.ed.net as usize);
                }
            }
            K::Plus | K::Equals => self.ed.cam.zoom_at(w / 2.0, h / 2.0, self.ed.cam.k * 1.4),
            K::Minus => self.ed.cam.zoom_at(w / 2.0, h / 2.0, self.ed.cam.k / 1.4),
            _ => {}
        }
    }

    // --- The bar ------------------------------------------------------------------------

    fn bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            let title = match self.ed.origin {
                Origin::Drawn => self
                    .circuits
                    .iter()
                    .find(|c| c.name == self.ed.name)
                    .map_or(self.ed.name.clone(), |c| c.title.clone()),
                Origin::New => format!("{} (new)", self.ed.name),
            };
            let mut pick: Option<Leave> = None;
            egui::ComboBox::from_id_salt("ed_circuit")
                .width(250.0)
                .selected_text(RichText::new(title).strong())
                .show_ui(ui, |ui| {
                    for c in &self.circuits {
                        let on = self.ed.origin == Origin::Drawn && c.name == self.ed.name;
                        if ui
                            .selectable_label(on, format!("{} · drawn", c.title))
                            .clicked()
                        {
                            pick = Some(Leave::Open(c.name.clone()));
                        }
                    }
                    ui.separator();
                    if ui.selectable_label(false, "＋ New circuit…").clicked() {
                        pick = Some(Leave::New);
                    }
                    if ui.selectable_label(false, "Open a drawing file…").clicked() {
                        pick = Some(Leave::File);
                    }
                });
            if let Some(p) = pick {
                if self.ed.edited() && self.ed.hist.past.len() + self.ed.hist.future.len() > 0 {
                    self.leave = Some(p);
                } else {
                    self.do_leave(p);
                }
            }
            ui.add_space(6.0);
            for (mode, label, k) in [
                (Mode::Select, "Select", "V"),
                (Mode::Wire, "Wire", "W"),
                (Mode::Label, "Label", "L"),
                (Mode::Ground, "Ground", "G"),
                (Mode::Frame, "Section", "S"),
            ] {
                let on = self.ed.mode == mode;
                let text = RichText::new(format!("{label} {k}"));
                let text = if on {
                    text.color(theme::ACCENT_INK)
                } else {
                    text
                };
                let b =
                    egui::Button::new(text).fill(if on { theme::ACCENT } else { theme::CHROME2 });
                if ui.add(b).clicked() {
                    self.ed.set_mode(mode, None);
                }
            }
            ui.add_space(6.0);
            let kind = match self.ed.origin {
                Origin::Drawn => "drawing",
                Origin::New => "new drawing",
            };
            badge(ui, kind, theme::MUTED);
            if self.ed.edited() {
                badge(ui, "unsaved", theme::ACCENT);
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.button("Fit  F").clicked() {
                    self.ed.fit(true);
                }
                ui.label(
                    RichText::new(format!("{:.0}%", self.ed.cam.k / 4.0 * 100.0))
                        .monospace()
                        .color(theme::MUTED),
                );
                self.checks_pill(ui);
                let save =
                    egui::Button::new(RichText::new("Save as…").strong().color(theme::ACCENT_INK))
                        .fill(theme::ACCENT);
                if ui
                    .add(save)
                    .on_hover_text("Save as a circuit (Ctrl+S)")
                    .clicked()
                {
                    self.open_save();
                }
                let redo = self.ed.hist.future.last().map(|(_, l)| l.clone());
                if ui
                    .add_enabled(redo.is_some(), egui::Button::new("Redo"))
                    .on_hover_text(
                        redo.map_or("Redo (Ctrl+Shift+Z)".into(), |l| format!("Redo {l}")),
                    )
                    .clicked()
                {
                    self.ed.redo();
                }
                let undo = self.ed.hist.past.last().map(|(_, l)| l.clone());
                if ui
                    .add_enabled(undo.is_some(), egui::Button::new("Undo"))
                    .on_hover_text(undo.map_or("Undo (Ctrl+Z)".into(), |l| format!("Undo {l}")))
                    .clicked()
                {
                    self.ed.undo();
                }
                if ui.button("?").on_hover_text("Keys").clicked() {
                    self.help = true;
                }
            });
        });
    }

    fn checks_pill(&mut self, ui: &mut egui::Ui) {
        let faults = self.ed.faults();
        let (text, color) = match self.ed.checking {
            Checking::Busy => ("checking…".to_string(), theme::ACCENT),
            Checking::Done(_) if faults > 0 => (
                format!("{faults} problem{}", if faults > 1 { "s" } else { "" }),
                theme::FAULT,
            ),
            Checking::Done(_) => ("checks pass".to_string(), theme::OK),
        };
        let b = egui::Button::new(RichText::new(format!("    {text}")).strong().color(color))
            .fill(theme::alpha(color, 0.09))
            .stroke(Stroke::new(1.0, theme::alpha(color, 0.4)))
            .corner_radius(CornerRadius::same(12));
        let tip = match self.ed.checking {
            Checking::Done(s) => {
                format!("Pre-flight checks at every combination of switch positions ({s:.1} s)")
            }
            Checking::Busy => "Pre-flight checks at every combination of switch positions".into(),
        };
        let r = ui.add(b).on_hover_text(tip);
        ui.painter()
            .circle_filled(r.rect.left_center() + Vec2::new(11.0, 0.0), 3.5, color);
        if r.clicked() && !self.ed.markers.is_empty() {
            self.ed.focus_marker(0);
        }
    }

    fn open_save(&mut self) {
        let suggestion = match self.ed.origin {
            Origin::Drawn => self.ed.name.clone(),
            Origin::New => String::new(),
        };
        self.save = Some((suggestion, String::new()));
    }

    fn do_leave(&mut self, l: Leave) {
        let r = match l {
            Leave::Open(name) => self.ed.open(&name),
            Leave::New => {
                self.ed.open_blank();
                Ok(())
            }
            Leave::File => match rfd::FileDialog::new()
                .add_filter("Drawing", &["json"])
                .set_directory(&self.ed.circuits_dir)
                .pick_file()
            {
                Some(p) => self.ed.open_file(&p),
                None => Ok(()),
            },
        };
        if let Err(e) = r {
            self.ed.status = e;
        }
        self.refit = true;
    }

    // --- The listen bar -----------------------------------------------------------------

    fn listen_bar(&mut self, ui: &mut egui::Ui, play: &mut PlayView) {
        ui.horizontal(|ui| {
            ui.label(RichText::new("Listen").color(theme::MUTED));
            let playing = play.drawing_playing();
            let label = if playing { "Stop  Space" } else { "▶ Play  Space" };
            let b = egui::Button::new(RichText::new(label).strong()).fill(if playing {
                theme::alpha(theme::ACCENT, 0.2)
            } else {
                theme::CHROME2
            });
            let can = self.ed.analysis.ok() && self.ed.analysis.has_output;
            if ui
                .add_enabled(can || playing, b)
                .on_hover_text("Play the drawing through the Play view's file and loop region at draft-1x: each edit is heard as it is made")
                .clicked()
            {
                play.toggle_drawing();
            }
            ui.label(RichText::new(play.listen_line()).small().color(theme::MUTED));
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let st = &self.ed.status;
                let color = if st.starts_with("doesn't compile") {
                    theme::FAULT
                } else {
                    theme::MUTED
                };
                ui.label(RichText::new(st).small().color(color));
                ui.label(
                    RichText::new(format!(
                        "x {:.2}  y {:.2} mm   {} parts · {} nets",
                        self.ed.world.0,
                        self.ed.world.1,
                        self.ed.drawing.symbols.len(),
                        self.ed.analysis.nets.len()
                    ))
                    .small()
                    .monospace()
                    .color(theme::FAINT),
                );
            });
        });
    }

    // --- The left column ----------------------------------------------------------------

    fn left_column(&mut self, ui: &mut egui::Ui) {
        let find = ui.add(
            egui::TextEdit::singleline(&mut self.find)
                .hint_text("Find a part or node   /")
                .desired_width(f32::INFINITY),
        );
        if std::mem::take(&mut self.focus_find) {
            find.request_focus();
        }
        if find.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)) {
            let q = self.find.clone();
            if !self.ed.find(&q) {
                self.ed.status = format!("nothing called {q}");
            }
        }

        // Problems: open pins listed per part (while drawing there are many).
        let mut rows: Vec<(usize, String, String, bool)> = Vec::new(); // marker, check, text, drawing
        let mut open: Vec<(String, usize, Vec<String>)> = Vec::new();
        for (i, m) in self.ed.markers.iter().enumerate() {
            let pin = (m.check == "unconnected")
                .then(|| m.message.strip_prefix("unconnected: pin "))
                .flatten()
                .and_then(|r| r.split_once(" of "));
            if let Some((p, r)) = pin {
                match open.iter_mut().find(|(x, _, _)| x == r) {
                    Some((_, _, pins)) => pins.push(p.to_string()),
                    None => {
                        open.push((r.to_string(), i, vec![p.to_string()]));
                        rows.push((i, "open".into(), r.to_string(), false));
                    }
                }
            } else {
                let mut t = m.message.clone();
                if !m.config.is_empty() {
                    t = format!("{t}\nat {}", m.config);
                }
                rows.push((i, m.check.clone(), t, m.check == "drawing"));
            }
        }
        heading(
            ui,
            "PROBLEMS",
            &if rows.is_empty() {
                String::new()
            } else {
                rows.len().to_string()
            },
        );
        if rows.is_empty() {
            empty(ui, "none: the checks pass at every switch combination");
        }
        for (i, check, text, drawing) in rows {
            let text = if check == "open" {
                let (_, _, pins) = open.iter().find(|(r, _, _)| *r == text).expect("listed");
                format!(
                    "{text}: pin{} {} unconnected",
                    if pins.len() > 1 { "s" } else { "" },
                    pins.join(", ")
                )
            } else {
                text
            };
            let c = if drawing { theme::WARN } else { theme::FAULT };
            let on = self.ed.focus == Some(i);
            let mut job = egui::text::LayoutJob::default();
            job.append(
                &format!("{check} "),
                0.0,
                egui::TextFormat::simple(FontId::proportional(12.5), c),
            );
            job.append(
                &text,
                0.0,
                egui::TextFormat::simple(FontId::proportional(12.5), theme::INK),
            );
            if ui
                .add(egui::Button::selectable(on, job).wrap_mode(egui::TextWrapMode::Wrap))
                .clicked()
            {
                self.ed.focus_marker(i);
            }
        }

        heading(ui, "PARTS", "click, then place");
        let placing = (self.ed.mode == Mode::Place)
            .then(|| self.ed.place.as_ref().map(|p| p.name.clone()))
            .flatten();
        egui::Grid::new("ed_palette")
            .spacing(Vec2::new(4.0, 4.0))
            .show(ui, |ui| {
                for (i, (name, label)) in PALETTE.iter().enumerate() {
                    let on = placing.as_deref().is_some_and(|p| {
                        p == *name || (name.starts_with("SW_Rotary") && p.starts_with("SW_Rotary"))
                    });
                    if tile(ui, name, label, on).clicked() {
                        if name.starts_with("SW_Rotary") {
                            self.rotary = !self.rotary;
                        } else {
                            self.ed.set_mode(Mode::Place, Some(name));
                        }
                    }
                    if i % 4 == 3 {
                        ui.end_row();
                    }
                }
            });
        if self.rotary {
            ui.label(RichText::new("Positions").small().color(theme::MUTED));
            ui.horizontal_wrapped(|ui| {
                for n in 2..=12 {
                    if ui.small_button(n.to_string()).clicked() {
                        self.ed
                            .set_mode(Mode::Place, Some(&format!("SW_Rotary_{n}")));
                        self.rotary = false;
                    }
                }
            });
        }

        let controls: Vec<(String, Value)> = self
            .ed
            .drawing
            .circuit
            .get("controls")
            .and_then(Value::as_map)
            .map(|c| c.iter().map(|(k, v)| (k.to_string(), v.clone())).collect())
            .unwrap_or_default();
        heading(
            ui,
            "FRONT PANEL",
            &if controls.is_empty() {
                String::new()
            } else {
                controls.len().to_string()
            },
        );
        if controls.is_empty() {
            empty(ui, "no controls");
        }
        let base = self
            .ed
            .hist
            .base
            .as_ref()
            .and_then(|b| b.circuit.get("controls").and_then(Value::as_map).cloned());
        for (k, e) in controls {
            let Some(e) = e.as_map() else { continue };
            let v = e.get("value").cloned().unwrap_or(Value::Null);
            let changed = base
                .as_ref()
                .and_then(|b| b.get(&k))
                .and_then(Value::as_map)
                .and_then(|b| b.get("value"))
                .is_some_and(|b| !b.py_eq(&v));
            let unit = e.get("unit").map(Value::py_str).unwrap_or_default();
            ui.horizontal(|ui| {
                ui.label(RichText::new(&k).color(theme::INK))
                    .on_hover_text(e.get("source").map(Value::py_str).unwrap_or_default());
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let shown = match &self.ctl_drag {
                        Some((key, x)) if *key == k => fmt_ctl(&number_value(*x), &unit),
                        _ => fmt_ctl(&v, &unit),
                    };
                    ui.label(RichText::new(shown).small().monospace().color(if changed {
                        theme::ACCENT
                    } else {
                        theme::MUTED
                    }));
                });
            });
            if let Some(choices) = e.get("choices").and_then(Value::as_list) {
                ui.horizontal_wrapped(|ui| {
                    for c in choices {
                        if ui.selectable_label(c.py_eq(&v), value_text(c)).clicked() && !c.py_eq(&v)
                        {
                            self.ed.set_control(&k, c.clone());
                        }
                    }
                });
            } else {
                let lo = e.get("min").and_then(Value::as_f64).unwrap_or(0.0);
                let hi = e.get("max").and_then(Value::as_f64).unwrap_or(1.0);
                let mut x = match &self.ctl_drag {
                    Some((key, x)) if *key == k => *x,
                    _ => v.as_f64().unwrap_or(lo),
                };
                // Only what the user does writes: a slider shown snaps nothing.
                let mut slider = egui::Slider::new(&mut x, lo..=hi).show_value(false);
                if unit == "position" {
                    slider = slider.step_by(1.0);
                }
                let r = ui.add(slider);
                if r.dragged() {
                    self.ctl_drag = Some((k.clone(), x));
                }
                if r.drag_stopped() || r.clicked() {
                    self.ctl_drag = None;
                    // The page's range input: 100 steps, clean decimals.
                    if unit != "position" && hi > lo {
                        let st = (hi - lo) / 100.0;
                        x = to_precision(lo + ((x - lo) / st).round() * st, 10);
                    }
                    if v.as_f64()
                        .is_none_or(|old| (old - x).abs() > 1e-12 * (1.0 + old.abs()))
                    {
                        self.ed.set_control(&k, number_value(x));
                    }
                }
            }
            ui.add_space(4.0);
        }

        let count = |t: &str| self.ed.scene.section.values().filter(|s| *s == t).count();
        heading(ui, "SECTIONS", &self.ed.drawing.frames.len().to_string());
        if self.ed.drawing.frames.is_empty() {
            empty(ui, "one section: draw frames with S to make more");
        }
        let mut go = None;
        for (i, f) in self.ed.drawing.frames.iter().enumerate() {
            let on = self.ed.sel.frames.contains(&i);
            let r = ui.add(egui::Button::selectable(
                on,
                format!("{}   {}", f.title, count(&f.title)),
            ));
            if r.clicked() {
                go = Some(i);
            }
        }
        if let Some(i) = go {
            self.ed.show_frame(i);
        }
    }

    // --- The inspector ------------------------------------------------------------------

    fn rebuild_form(&mut self) {
        let key = (self.ed.sel.symbols.clone(), self.ed.net, self.ed.revision);
        if self.form.key == key {
            return;
        }
        let mut f = Form {
            key,
            ..Form::default()
        };
        let c = &self.ed.drawing.circuit;
        f.title = c.get("title").map(Value::py_str).unwrap_or_default();
        f.input = c.get("input").map_or("in".into(), Value::py_str);
        f.probes = c
            .get("probes")
            .and_then(Value::as_list)
            .map(|l| l.iter().map(Value::py_str).collect::<Vec<_>>().join(", "))
            .unwrap_or_default();
        if let [r] = self.ed.sel.symbols.as_slice()
            && self.ed.sel.size() == 1
            && let Some(s) = self.ed.drawing.symbol(r)
        {
            f.reference = r.clone();
            f.label = s.value.clone();
            f.raw = s.fields.clone();
            if let Some(vf) = self.ed.value_form(r) {
                f.value = vf.shown.clone();
                f.source = vf.source.clone();
                f.base = Some(vf);
            }
            f.params = s
                .fields
                .iter()
                .filter_map(|(_, v)| {
                    let p = self.ed.analysis.param(v)?;
                    let x = p
                        .value()
                        .filter(|x| matches!(x, Value::Int(_) | Value::Float(_)))?;
                    Some((v.clone(), value_text(x)))
                })
                .collect();
        }
        self.form = f;
    }

    fn inspector(&mut self, ui: &mut egui::Ui) {
        self.rebuild_form();
        let sel = self.ed.sel.clone();
        let n = sel.size();
        if n == 1 && sel.symbols.len() == 1 {
            self.show_symbol(ui, &sel.symbols[0]);
        } else if n > 1 {
            self.show_many(ui, &sel);
        } else if self.ed.net >= 0 && (self.ed.net as usize) < self.ed.analysis.nets.len() {
            self.show_net(ui, self.ed.net as usize);
        } else {
            self.show_circuit(ui);
        }
    }

    fn show_symbol(&mut self, ui: &mut egui::Ui, r: &str) {
        let Some(s) = self.ed.drawing.symbol(r).cloned() else {
            return;
        };
        let Some(sym) = symbols::get(&s.symbol) else {
            return;
        };
        ui.horizontal(|ui| {
            let resp = ui.add(
                egui::TextEdit::singleline(&mut self.form.reference)
                    .font(FontId::proportional(21.0))
                    .desired_width(110.0)
                    .id(Id::new("v-ref")),
            );
            if resp.lost_focus() {
                if ui.input(|i| i.key_pressed(egui::Key::Escape)) {
                    self.form.reference = r.into();
                } else if self.form.reference.trim() != r {
                    let to = self.form.reference.trim().to_string();
                    if let Err(e) = self.ed.rename(r, &to) {
                        self.form.error = Some(e);
                    }
                }
            }
            ui.label(RichText::new(s.symbol.replace('_', " ")).color(theme::MUTED));
        });
        if let Some(e) = &self.form.error {
            ui.colored_label(theme::FAULT, e);
        }
        let section = self
            .ed
            .scene
            .section
            .get(r)
            .cloned()
            .unwrap_or("main".into());
        let kind = match sym.kind {
            Kind::Macro => "part",
            Kind::Device => "tube or diode",
            Kind::Winding => "transformer winding",
            Kind::Core => "transformer core",
            Kind::Coupling => "inductor coupling",
            Kind::Switch => "rotary switch deck",
            Kind::Power => "power",
        };
        ui.label(
            RichText::new(format!("{section} · {kind}"))
                .small()
                .color(theme::MUTED),
        );
        ui.label(RichText::new(&sym.description).small().color(theme::MUTED));
        ui.add_space(6.0);

        match sym.kind {
            Kind::Device => self.device_fields(ui, r, &s.value, &s),
            Kind::Winding => {
                let cores: Vec<String> = self
                    .ed
                    .drawing
                    .symbols
                    .iter()
                    .filter(|(_, o)| o.symbol == "Core")
                    .map(|(x, _)| x.clone())
                    .collect();
                field(ui, "TRANSFORMER");
                let cur = s.field("Transformer").unwrap_or("").to_string();
                let mut pick = None;
                egui::ComboBox::from_id_salt("w_core")
                    .width(ui.available_width())
                    .selected_text(if cur.is_empty() { "–" } else { cur.as_str() })
                    .show_ui(ui, |ui| {
                        for c in std::iter::once(String::new()).chain(cores) {
                            if ui
                                .selectable_label(c == cur, if c.is_empty() { "–" } else { &c })
                                .clicked()
                            {
                                pick = Some(c);
                            }
                        }
                    });
                if let Some(c) = pick.filter(|c| *c != cur) {
                    self.ed.set_field(r, "Transformer", &c);
                }
                hint(ui, "its core: a Core symbol's name");
                field(ui, "WINDING LABEL");
                let resp = ui.add(
                    egui::TextEdit::singleline(&mut self.form.label)
                        .font(FontId::monospace(15.0))
                        .desired_width(f32::INFINITY),
                );
                if resp.lost_focus() {
                    let v = self.form.label.clone();
                    self.ed.set_label_value(r, &v);
                }
                hint(
                    ui,
                    "p, s, sa, … unique on its core; terminals are <label>.dot and .other",
                );
            }
            Kind::Switch => {
                let ctl: Vec<String> = self
                    .ed
                    .drawing
                    .circuit
                    .get("controls")
                    .and_then(Value::as_map)
                    .map(|c| {
                        c.iter()
                            .filter(|(_, e)| {
                                e.as_map().is_some_and(|e| {
                                    e.contains("choices")
                                        || e.get("unit").and_then(Value::as_str) == Some("position")
                                })
                            })
                            .map(|(k, _)| k.to_string())
                            .collect()
                    })
                    .unwrap_or_default();
                field(ui, "CONTROL");
                let cur = s.field("Control").unwrap_or("").to_string();
                let mut pick = None;
                egui::ComboBox::from_id_salt("sw_ctl")
                    .width(ui.available_width())
                    .selected_text(if cur.is_empty() { "–" } else { cur.as_str() })
                    .show_ui(ui, |ui| {
                        for c in std::iter::once(String::new()).chain(ctl) {
                            if ui
                                .selectable_label(c == cur, if c.is_empty() { "–" } else { &c })
                                .clicked()
                            {
                                pick = Some(c);
                            }
                        }
                    });
                if let Some(c) = pick.filter(|c| *c != cur) {
                    self.ed.set_field(r, "Control", &c);
                }
                let p = self.ed.analysis.param(&cur);
                let h = match p {
                    Some(p) => match p.entry.get("choices").and_then(Value::as_list) {
                        Some(c) => c.iter().map(value_text).collect::<Vec<_>>().join(" / "),
                        None => format!(
                            "{} … {}",
                            p.text("min").unwrap_or_default(),
                            p.text("max").unwrap_or_default()
                        ),
                    },
                    None => "a control with positions (the circuit panel adds one)".into(),
                };
                hint(ui, &h);
            }
            _ if sym.primary.is_some() => self.value_fields(ui, r, &s),
            _ => {}
        }

        if let Some(tol) = s.field("Tol") {
            field(ui, "TOLERANCE");
            let text = match tol {
                "none" => "none (not a physical part)".to_string(),
                "tube" => "tube (emission and µ drawn per instance)".to_string(),
                t => match self.ed.analysis.band(t) {
                    Some(b) => {
                        let pct: Vec<String> = b
                            .pct
                            .iter()
                            .map(|v| v.as_ref().map(value_text).unwrap_or_default())
                            .collect();
                        if pct.len() == 2 {
                            format!("{t}  −{} / +{} %", pct[0], pct[1])
                        } else {
                            format!("{t}  ±{} %", pct.first().cloned().unwrap_or_default())
                        }
                    }
                    None => t.to_string(),
                },
            };
            boxed(ui, &text);
        }

        // The part's other parameters.
        let meta = ["Source", "Param", "Genome", "Tol", "Unit", "Notes"];
        let rows: Vec<(String, String)> = s
            .fields
            .iter()
            .filter(|(k, _)| {
                // Fields with an editor of their own aren't listed again.
                let own = match sym.kind {
                    Kind::Winding => "Transformer",
                    Kind::Switch => "Control",
                    Kind::Device => "Model",
                    _ => "",
                };
                !meta.contains(&k.as_str()) && k != own
            })
            .cloned()
            .collect();
        if !rows.is_empty() {
            field(ui, "PARAMETERS");
            egui::Grid::new("ed_params")
                .num_columns(2)
                .striped(false)
                .show(ui, |ui| {
                    for (k, v) in rows {
                        ui.label(RichText::new(&k).monospace().small().color(theme::MUTED));
                        self.param_cell(ui, &v);
                        ui.end_row();
                    }
                });
        }

        // Pins and their nets.
        let pins: Vec<_> = self
            .ed
            .scene
            .pins
            .iter()
            .filter(|p| p.r == r)
            .cloned()
            .collect();
        if !pins.is_empty() {
            field(ui, "PINS");
            let choices = (sym.kind == Kind::Switch)
                .then(|| self.ed.analysis.param(s.field("Control").unwrap_or("")))
                .flatten()
                .and_then(|p| {
                    p.entry
                        .get("choices")
                        .and_then(Value::as_list)
                        .map(<[Value]>::to_vec)
                });
            let mut go = None;
            egui::Grid::new("ed_pins").num_columns(2).show(ui, |ui| {
                for p in &pins {
                    let unit = if sym.units.len() > 1 {
                        format!("{}.", char::from(b'@' + p.unit as u8))
                    } else {
                        String::new()
                    };
                    let name = if p.name == p.number {
                        p.number.clone()
                    } else {
                        format!("{} ({})", p.name, p.number)
                    };
                    let pos = choices
                        .as_ref()
                        .and_then(|c| {
                            p.number
                                .parse::<usize>()
                                .ok()
                                .map(|i| c.get(i - 1).map_or("–".into(), value_text))
                        })
                        .map(|t| format!("  {t}"))
                        .unwrap_or_default();
                    ui.label(
                        RichText::new(format!("{unit}{name}{pos}"))
                            .monospace()
                            .small()
                            .color(theme::MUTED),
                    );
                    match self
                        .ed
                        .analysis
                        .nets
                        .get(p.net.max(0) as usize)
                        .filter(|_| p.net >= 0)
                    {
                        Some(net) => {
                            if tag(ui, &net.node, theme::NET).clicked() {
                                go = Some(p.net as usize);
                            }
                        }
                        None => {
                            ui.label(RichText::new("–").color(theme::FAINT));
                        }
                    }
                    ui.end_row();
                }
            });
            if let Some(i) = go {
                self.ed.select(Sel::default(), i as i64);
                self.ed.show_net(i);
            }
        }
        if sym.kind == Kind::Core {
            field(ui, "WINDINGS");
            let ws: Vec<(String, String)> = self
                .ed
                .drawing
                .symbols
                .iter()
                .filter(|(_, w)| w.symbol == "Winding" && w.field("Transformer") == Some(r))
                .map(|(x, w)| (x.clone(), w.value.clone()))
                .collect();
            let mut go = None;
            ui.horizontal_wrapped(|ui| {
                for (x, v) in &ws {
                    if tag(ui, v, theme::MUTED).clicked() {
                        go = Some(x.clone());
                    }
                }
                if ws.is_empty() {
                    ui.label("–");
                }
            });
            if let Some(x) = go {
                self.ed.select(Sel::symbol(&x), -1);
                self.ed.show_part(&x);
            }
        }

        // Every field, as the circuit file reads it.
        ui.add_space(8.0);
        egui::CollapsingHeader::new(RichText::new("ALL FIELDS").small().color(theme::MUTED))
            .id_salt(("all_fields", r))
            .show(ui, |ui| {
                let mut names: Vec<String> = sym.fields.iter().map(|f| f.to_string()).collect();
                for (k, _) in &s.fields {
                    if !names.contains(k) {
                        names.push(k.clone());
                    }
                }
                egui::Grid::new("ed_raw").num_columns(2).show(ui, |ui| {
                    for name in names {
                        ui.label(RichText::new(&name).monospace().small().color(theme::MUTED));
                        let i = match self.form.raw.iter().position(|(k, _)| *k == name) {
                            Some(i) => i,
                            None => {
                                self.form.raw.push((name.clone(), String::new()));
                                self.form.raw.len() - 1
                            }
                        };
                        let old = s.field(&name).unwrap_or("").to_string();
                        let resp = ui.add(
                            egui::TextEdit::singleline(&mut self.form.raw[i].1)
                                .font(FontId::monospace(12.0))
                                .desired_width(170.0),
                        );
                        if resp.lost_focus() {
                            if ui.input(|i| i.key_pressed(egui::Key::Escape)) {
                                self.form.raw[i].1 = old;
                            } else if self.form.raw[i].1.trim() != old {
                                let v = self.form.raw[i].1.clone();
                                self.ed.set_field(r, &name, &v);
                            }
                        }
                        ui.end_row();
                    }
                    ui.add(
                        egui::TextEdit::singleline(&mut self.new_field.0)
                            .hint_text("name")
                            .font(FontId::monospace(12.0))
                            .desired_width(80.0),
                    );
                    let resp = ui.add(
                        egui::TextEdit::singleline(&mut self.new_field.1)
                            .hint_text("value (YAML)")
                            .font(FontId::monospace(12.0))
                            .desired_width(170.0),
                    );
                    if resp.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)) {
                        let (k, v) = (
                            self.new_field.0.trim().to_string(),
                            self.new_field.1.trim().to_string(),
                        );
                        let ok = k.starts_with(|c: char| c.is_ascii_alphabetic() || c == '_')
                            && k.chars().all(|c| c.is_ascii_alphanumeric() || c == '_');
                        if ok && !v.is_empty() {
                            self.ed.set_field(r, &k, &v);
                            self.new_field = Default::default();
                        }
                    }
                    ui.end_row();
                });
                hint(
                    ui,
                    "Capitalized fields are metadata (kicad/README.md); an empty field is removed.",
                );
            });
    }

    fn value_fields(&mut self, ui: &mut egui::Ui, r: &str, s: &varimu_circuit::drawing::Symbol) {
        let Some(base) = self.form.base.clone() else {
            return;
        };
        let p = base
            .key
            .as_deref()
            .and_then(|k| self.ed.analysis.param(k))
            .cloned();
        field(ui, "VALUE");
        let id = Id::new("v-in");
        let focused = ui.memory(|m| m.has_focus(id));
        if focused && !base.derived {
            // ↑ / ↓ step through standard values (E12; E24 with Shift), heard at once.
            let step = ui.input_mut(|i| {
                for (m, e24) in [
                    (egui::Modifiers::NONE, false),
                    (egui::Modifiers::SHIFT, true),
                ] {
                    if i.consume_key(m, egui::Key::ArrowUp) {
                        return Some((1, e24));
                    }
                    if i.consume_key(m, egui::Key::ArrowDown) {
                        return Some((-1, e24));
                    }
                }
                None
            });
            if let Some((dir, e24)) = step
                && let Some(t) = self.ed.step_value(r, &self.form.value.clone(), dir, e24)
            {
                self.form.value = t;
                self.rebuild_form();
            }
        }
        let bad = parse_num(&self.form.value).is_none()
            && self.ed.analysis.param(self.form.value.trim()).is_none();
        let resp = ui.add_enabled(
            !base.derived,
            egui::TextEdit::singleline(&mut self.form.value)
                .id(id)
                .font(FontId::monospace(19.0))
                .text_color(if bad { theme::FAULT } else { theme::INK })
                .desired_width(f32::INFINITY),
        );
        if resp.changed() && !self.form.touched {
            self.form.source = base.default_source(&self.form.value);
        }
        if resp.lost_focus() {
            if ui.input(|i| i.key_pressed(egui::Key::Escape)) {
                self.form.value = base.shown.clone();
                self.form.source = base.source.clone();
            } else if self.form.value.trim() != base.shown {
                let (v, src) = (self.form.value.clone(), self.form.source.clone());
                if let Err(e) = self.ed.commit_value(r, &v, &src) {
                    self.form.error = Some(e);
                }
            }
        }
        let x = parse_num(&self.form.value);
        let h = match x.or_else(|| p.as_ref().and_then(|p| p.value()).and_then(Value::as_f64)) {
            Some(x) => {
                let mut h = format!("= {}", with_unit(x, base.unit));
                if let Some(b) = p.as_ref().and_then(|p| p.bounds.as_ref())
                    && let (Some(lo), Some(hi)) = (b.min, b.max)
                    && (x < lo || x > hi)
                {
                    h.push_str(&format!(
                        " · outside the genome's {} … {}",
                        with_unit(lo, base.unit),
                        with_unit(hi, base.unit)
                    ));
                }
                h
            }
            None if base.derived => "derived from other values (read-only)".into(),
            None if self.ed.analysis.param(self.form.value.trim()).is_some() => {
                format!("the parameter {}", self.form.value.trim())
            }
            None => "not a number (40u, 4k7, 2.2e-9) or a parameter key".into(),
        };
        ui.label(RichText::new(h).small().color(theme::MUTED))
            .on_hover_text("↑ / ↓ step through standard values (E12; E24 with Shift)");

        if let Some(key) = &base.key {
            field(ui, "PARAMETER");
            if s.field("Param").is_some() {
                let sharers: Vec<String> = self
                    .ed
                    .drawing
                    .symbols
                    .iter()
                    .filter(|(x, o)| x != r && o.field("Param") == Some(key.as_str()))
                    .map(|(x, _)| x.clone())
                    .collect();
                let mut go = None;
                ui.horizontal_wrapped(|ui| {
                    tag(ui, key, theme::ACCENT);
                    if !sharers.is_empty() {
                        ui.label(RichText::new("· shared with").small().color(theme::MUTED));
                        for x in sharers.iter().take(6) {
                            if tag(ui, x, theme::MUTED).clicked() {
                                go = Some(x.clone());
                            }
                        }
                    }
                });
                if !sharers.is_empty() {
                    ui.horizontal(|ui| {
                        ui.label(
                            RichText::new("An edit changes every part on it.")
                                .small()
                                .color(theme::MUTED),
                        );
                        if ui.link(RichText::new("Only this part").small()).clicked() {
                            self.ed.unlink(r);
                        }
                    });
                }
                if let Some(x) = go {
                    self.ed.select(Sel::symbol(&x), -1);
                    self.ed.show_part(&x);
                }
            } else {
                ui.horizontal(|ui| {
                    tag(ui, key, theme::ACCENT);
                    let kind = p
                        .as_ref()
                        .map_or("unknown key".into(), |p| p.kind.replace('_', " "));
                    ui.label(RichText::new(kind).small().color(theme::MUTED));
                });
            }
        }
        field(ui, "SOURCE");
        let missing = self.form.source.trim().is_empty();
        let resp = egui::Frame::NONE
            .stroke(Stroke::new(
                1.0,
                if missing { theme::FAULT } else { theme::LINE },
            ))
            .corner_radius(CornerRadius::same(6))
            .show(ui, |ui| {
                ui.add_enabled(
                    !base.derived,
                    egui::TextEdit::multiline(&mut self.form.source)
                        .desired_rows(2)
                        .frame(egui::Frame::NONE)
                        .desired_width(f32::INFINITY),
                )
            })
            .inner;
        if resp.changed() {
            self.form.touched = true;
        }
        if resp.lost_focus()
            && self.form.value.trim() == base.shown
            && self.form.source != base.source
        {
            let t = self.form.source.clone();
            self.ed.commit_source(r, &t);
        }
        if missing {
            ui.label(
                RichText::new("a number needs a source: it won't compile without one")
                    .small()
                    .color(theme::FAULT),
            );
        }
        let genome = s
            .field("Genome")
            .map(str::to_string)
            .or_else(|| p.as_ref().and_then(|p| p.text("genome")));
        if let Some(g) = genome {
            field(ui, "GENOME");
            let range = match p.as_ref().and_then(|p| p.bounds.as_ref()) {
                Some(b) => match &b.choices {
                    Some(c) => c.iter().map(value_text).collect::<Vec<_>>().join(" / "),
                    None => format!(
                        "{} … {}",
                        b.min.map_or("?".into(), |x| with_unit(x, base.unit)),
                        b.max.map_or("?".into(), |x| with_unit(x, base.unit))
                    ),
                },
                None => "bounds not found".into(),
            };
            boxed(ui, &format!("{g}\n{range}"));
        }
        if let Some(notes) = s
            .field("Notes")
            .map(str::to_string)
            .or_else(|| p.as_ref().and_then(|p| p.text("notes")))
        {
            field(ui, "NOTES");
            boxed(ui, &notes);
        }
    }

    fn device_fields(
        &mut self,
        ui: &mut egui::Ui,
        r: &str,
        value: &str,
        s: &varimu_circuit::drawing::Symbol,
    ) {
        let key = self.ed.analysis.param(value).map(|_| value.to_string());
        let file = key
            .as_deref()
            .and_then(|k| self.ed.analysis.param(k))
            .and_then(|p| p.value())
            .map_or(value.to_string(), Value::py_str);
        let kinds: &[&str] = match s.symbol.as_str() {
            "Triode" | "Triode_Dual" => &["triode"],
            "Pentode" => &["pentode"],
            "Diode" | "Diode_Dual" => &["vacuum_diode", "junction_diode"],
            _ => &[],
        };
        field(ui, "DEVICE");
        let options: Vec<(String, String)> = self
            .ed
            .parts
            .devices
            .iter()
            .filter(|(_, k)| kinds.contains(&k.as_str()))
            .cloned()
            .collect();
        let mut pick = None;
        egui::ComboBox::from_id_salt("v-device")
            .width(ui.available_width())
            .selected_text(&file)
            .show_ui(ui, |ui| {
                for (name, kind) in &options {
                    let on = name.eq_ignore_ascii_case(&file);
                    if ui
                        .selectable_label(on, format!("{name} · {}", kind.replace('_', " ")))
                        .clicked()
                        && !on
                    {
                        pick = Some(name.clone());
                    }
                }
            });
        if let Some(name) = pick {
            self.ed.set_device(r, &name);
        }
        let mut h = String::new();
        if let Some(k) = &key {
            h.push_str(&format!("parameter {k} · "));
        }
        h.push_str(&format!("config/devices/{}.yaml", file.to_lowercase()));
        hint(ui, &h);
        if let Some(m) = s.field("Model") {
            field(ui, "MODEL");
            boxed(ui, &format!("{m}  (one instance shared by both units)"));
        }
        if let Some(src) = s.field("Source") {
            field(ui, "SOURCE");
            boxed(ui, src);
        }
    }

    fn param_cell(&mut self, ui: &mut egui::Ui, v: &str) {
        let Some(p) = self
            .ed
            .analysis
            .param(v)
            .cloned()
            .filter(|p| p.kind != "derived")
        else {
            ui.label(RichText::new(v).monospace().small());
            return;
        };
        match p.value() {
            Some(Value::Str(m)) if self.ed.parts.materials.contains(m) => {
                let mut pick = None;
                egui::ComboBox::from_id_salt(("mat", v))
                    .selected_text(m)
                    .show_ui(ui, |ui| {
                        for x in &self.ed.parts.materials {
                            if ui.selectable_label(x == m, x).clicked() && x != m {
                                pick = Some(x.clone());
                            }
                        }
                    });
                if let Some(x) = pick {
                    self.ed.set_param_value(v, Value::Str(x));
                }
            }
            Some(x @ (Value::Int(_) | Value::Float(_))) => {
                let i = match self.form.params.iter().position(|(k, _)| k == v) {
                    Some(i) => i,
                    None => {
                        self.form.params.push((v.to_string(), value_text(x)));
                        self.form.params.len() - 1
                    }
                };
                ui.vertical(|ui| {
                    let resp = ui.add(
                        egui::TextEdit::singleline(&mut self.form.params[i].1)
                            .font(FontId::monospace(12.0))
                            .desired_width(150.0),
                    );
                    if resp.lost_focus()
                        && ui.input(|i| i.key_pressed(egui::Key::Enter))
                        && let Some(n) = parse_num(&self.form.params[i].1)
                    {
                        self.ed.set_param_value(v, number_value(n));
                    }
                    let unit = varimu_app::editor::eng::unit_of(Some(v), None);
                    ui.label(
                        RichText::new(format!(
                            "{v} · {}",
                            with_unit(x.as_f64().unwrap_or(0.0), unit)
                        ))
                        .small()
                        .color(theme::MUTED),
                    );
                });
            }
            other => {
                ui.label(
                    RichText::new(format!(
                        "{v}\n= {}",
                        other.map(Value::py_str).unwrap_or_default()
                    ))
                    .monospace()
                    .small(),
                );
            }
        }
    }

    fn show_many(&mut self, ui: &mut egui::Ui, sel: &Sel) {
        ui.label(
            RichText::new(format!("{} items", sel.size()))
                .size(21.0)
                .strong(),
        );
        let counts: Vec<String> = [
            (sel.symbols.len(), "part"),
            (sel.wires.len(), "wire"),
            (sel.labels.len(), "label"),
            (sel.grounds.len(), "ground"),
            (sel.frames.len(), "section"),
        ]
        .iter()
        .filter(|(k, _)| *k > 0)
        .map(|(k, w)| format!("{k} {w}{}", if *k > 1 { "s" } else { "" }))
        .collect();
        ui.label(
            RichText::new(counts.join(" · "))
                .small()
                .color(theme::MUTED),
        );
        if !sel.symbols.is_empty() {
            field(ui, "PARTS");
            let mut go = None;
            ui.horizontal_wrapped(|ui| {
                for r in sel.symbols.iter().take(40) {
                    if tag(ui, r, theme::MUTED).clicked() {
                        go = Some(r.clone());
                    }
                }
            });
            if let Some(r) = go {
                self.ed.select(Sel::symbol(&r), -1);
                self.ed.show_part(&r);
            }
        }
        ui.add_space(12.0);
        hint(ui, "Drag to move them · R rotate · X mirror · arrows nudge");
        hint(ui, "Ctrl C copy · Ctrl D duplicate · Del delete");
    }

    fn show_net(&mut self, ui: &mut egui::Ui, i: usize) {
        let n = self.ed.analysis.nets[i].clone();
        let name = if n.node == "0" {
            "ground".to_string()
        } else {
            n.node.clone()
        };
        ui.horizontal(|ui| {
            ui.label(RichText::new(&name).size(21.0).strong());
            ui.label(RichText::new("net").color(theme::MUTED));
        });
        let pins: Vec<_> = self
            .ed
            .scene
            .pins
            .iter()
            .filter(|p| p.net == i as i64)
            .cloned()
            .collect();
        let mut crumb = format!("{} pins", pins.len());
        if !n.labels.is_empty() {
            crumb.push_str(&format!(" · {} labels", n.labels.len()));
        }
        if !n.grounds.is_empty() {
            crumb.push_str(&format!(" · {} grounds", n.grounds.len()));
        }
        ui.label(RichText::new(crumb).small().color(theme::MUTED));
        field(ui, "NODE");
        let mut node = n.node.clone();
        if n.node.starts_with("n_") {
            node.push_str("\nunlabelled: named after its first pin");
        }
        boxed(ui, &node);
        field(ui, "PINS");
        let mut go = None;
        egui::Grid::new("ed_net_pins")
            .num_columns(2)
            .show(ui, |ui| {
                for p in &pins {
                    let multi = self
                        .ed
                        .drawing
                        .symbol(&p.r)
                        .and_then(|s| symbols::get(&s.symbol))
                        .is_some_and(|s| s.units.len() > 1);
                    let unit = if multi {
                        char::from(b'@' + p.unit as u8).to_string()
                    } else {
                        String::new()
                    };
                    if tag(ui, &format!("{}{unit}", p.r), theme::ACCENT).clicked() {
                        go = Some(p.r.clone());
                    }
                    let pin = if p.name == p.number {
                        format!("pin {}", p.number)
                    } else {
                        format!("{} ({})", p.name, p.number)
                    };
                    ui.label(RichText::new(pin).monospace().small());
                    ui.end_row();
                }
            });
        if let Some(r) = go {
            self.ed.select(Sel::symbol(&r), -1);
            self.ed.show_part(&r);
        }
    }

    fn show_circuit(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(RichText::new("Circuit").size(21.0).strong());
            ui.label(RichText::new(&self.ed.name).color(theme::MUTED));
        });
        ui.label(
            RichText::new(format!(
                "{} parts · {} nets · {} sections",
                self.ed.drawing.symbols.len(),
                self.ed.analysis.nets.len(),
                self.ed.drawing.frames.len()
            ))
            .small()
            .color(theme::MUTED),
        );
        field(ui, "TITLE");
        let r =
            ui.add(egui::TextEdit::singleline(&mut self.form.title).desired_width(f32::INFINITY));
        if r.lost_focus() {
            let t = self.form.title.trim().to_string();
            self.ed.set_circuit("title", Value::Str(t));
        }
        ui.columns(2, |cols| {
            field(&mut cols[0], "INPUT NODE");
            let r = cols[0].add(
                egui::TextEdit::singleline(&mut self.form.input)
                    .font(FontId::monospace(14.0))
                    .desired_width(f32::INFINITY),
            );
            if r.lost_focus() {
                let t = self.form.input.trim().to_string();
                self.ed.set_circuit("input", Value::Str(t));
            }
            field(&mut cols[1], "OUTPUT NODE");
            let has = self.ed.analysis.has_output;
            boxed(
                &mut cols[1],
                if has {
                    "out · drawn"
                } else {
                    "out · not drawn"
                },
            );
        });
        field(ui, "PROBES");
        let r = ui.add(
            egui::TextEdit::singleline(&mut self.form.probes)
                .font(FontId::monospace(13.0))
                .desired_width(f32::INFINITY),
        );
        if r.lost_focus() {
            let v: Vec<Value> = self
                .form
                .probes
                .split(',')
                .map(str::trim)
                .filter(|x| !x.is_empty())
                .map(|x| Value::Str(x.into()))
                .collect();
            self.ed.set_circuit("probes", Value::List(v));
        }
        hint(ui, "node voltages every render saves, besides out");
        field(ui, "CONTROLS");
        let ctl: Vec<(String, String)> = self
            .ed
            .drawing
            .circuit
            .get("controls")
            .and_then(Value::as_map)
            .map(|c| {
                c.iter()
                    .map(|(k, e)| {
                        let e = e.as_map().cloned().unwrap_or_default();
                        let d = match e.get("choices").and_then(Value::as_list) {
                            Some(c) => c.iter().map(value_text).collect::<Vec<_>>().join(" / "),
                            None => format!(
                                "{} … {}{}",
                                e.get("min").map(value_text).unwrap_or_default(),
                                e.get("max").map(value_text).unwrap_or_default(),
                                e.get("unit")
                                    .map(|u| format!(" {}", u.py_str()))
                                    .unwrap_or_default()
                            ),
                        };
                        (k.to_string(), d)
                    })
                    .collect()
            })
            .unwrap_or_default();
        if ctl.is_empty() {
            empty(ui, "none");
        }
        for (k, d) in ctl {
            ui.horizontal(|ui| {
                ui.label(RichText::new(&k).strong());
                ui.label(RichText::new(d).small().color(theme::MUTED));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if ui.link(RichText::new("remove").small()).clicked() {
                        self.ed.remove_control(&k);
                    }
                });
            });
        }
        egui::CollapsingHeader::new(RichText::new("Add a control").small().color(theme::MUTED))
            .id_salt("add_ctl")
            .show(ui, |ui| {
                ui.columns(2, |c| {
                    c[0].add(
                        egui::TextEdit::singleline(&mut self.new_ctl.0).hint_text("key, e.g. tc"),
                    );
                    c[1].add(
                        egui::TextEdit::singleline(&mut self.new_ctl.1).hint_text("0..1 or 1,2,3"),
                    );
                });
                ui.add(
                    egui::TextEdit::singleline(&mut self.new_ctl.2)
                        .hint_text("source (e.g. man: TIME CONSTANT, 6 positions)")
                        .desired_width(f32::INFINITY),
                );
                ui.horizontal(|ui| {
                    hint(ui, "A range is a knob; a list is a switch's positions.");
                    if ui.button("Add").clicked() {
                        let (k, r, s) = self.new_ctl.clone();
                        match self.ed.add_control(&k, &r, &s) {
                            Ok(()) => self.new_ctl = Default::default(),
                            Err(e) => self.ed.status = e,
                        }
                    }
                });
            });
        ui.add_space(12.0);
        hint(
            ui,
            "Values without a part, device parameters, mains and tolerance bands come with the circuit (its sidecar) and are edited in the file for now.",
        );
    }

    // --- The canvas ---------------------------------------------------------------------

    fn canvas(&mut self, ui: &mut egui::Ui) {
        let (rect, resp) = ui.allocate_exact_size(ui.available_size(), Sense::click_and_drag());
        self.canvas_rect = rect;
        self.ed.cam.w = f64::from(rect.width());
        self.ed.cam.h = f64::from(rect.height());
        if std::mem::take(&mut self.refit) {
            self.ed.fit(false);
        }
        let o = rect.min;
        let local = |p: Pos2| (f64::from(p.x - o.x), f64::from(p.y - o.y));
        let ctx = ui.ctx().clone();
        let (pos, pressed, released, shift, other_pressed, any_released, wheel) = ctx.input(|i| {
            let mut wheel = Vec::new();
            for e in &i.events {
                if let egui::Event::MouseWheel {
                    unit,
                    delta,
                    modifiers,
                    ..
                } = e
                {
                    wheel.push((*unit, *delta, modifiers.command));
                }
            }
            (
                i.pointer.latest_pos(),
                i.pointer.primary_pressed(),
                i.pointer.primary_released(),
                i.modifiers.shift,
                i.pointer.button_pressed(egui::PointerButton::Secondary)
                    || i.pointer.button_pressed(egui::PointerButton::Middle),
                i.pointer.any_released(),
                wheel,
            )
        });
        let over = resp.hovered() && self.ed.prompt.is_none();
        if let Some(pos) = pos {
            let (sx, sy) = local(pos);
            if over {
                for (unit, d, ctrl) in wheel {
                    let px = match unit {
                        egui::MouseWheelUnit::Point => d,
                        egui::MouseWheelUnit::Line => d * 100.0,
                        egui::MouseWheelUnit::Page => d * 800.0,
                    };
                    let trackpad = unit == egui::MouseWheelUnit::Point && px.y.abs() < 50.0;
                    if !ctrl && trackpad && px.x.abs() > px.y.abs() * 0.5 {
                        self.ed.cam.pan(f64::from(px.x), f64::from(px.y));
                    } else {
                        let f = (f64::from(px.y) * if ctrl { 0.01 } else { 0.0018 }).exp();
                        self.ed.cam.zoom_at(sx, sy, self.ed.cam.k * f);
                    }
                }
            }
            // Panning: the right or middle button, or the left with the space bar held.
            if over && (other_pressed || (pressed && self.space.is_some())) {
                if self.space.is_some() {
                    self.space = Some(true);
                }
                self.ed.cam.stop();
                self.pan = Some((pos, self.ed.cam.x, self.ed.cam.y));
            } else if over && pressed && !self.left {
                let title = self
                    .titles
                    .iter()
                    .find(|(_, r)| r.contains(pos))
                    .map(|(i, _)| *i);
                match title {
                    Some(i) if resp.double_clicked() => {
                        self.ed.rename_frame(i, (sx, sy - 30.0));
                    }
                    Some(i) => {
                        self.left = self.ed.frame_down(i, sx, sy, shift);
                    }
                    None => {
                        self.ed.cam.stop();
                        self.left = true;
                        self.ed.down(sx, sy, shift);
                    }
                }
            }
            if let Some((p0, x0, y0)) = self.pan {
                let d = pos - p0;
                self.ed
                    .cam
                    .set(x0 + f64::from(d.x), y0 + f64::from(d.y), self.ed.cam.k);
            } else if self.left {
                self.ed.moved(sx, sy);
            } else if over {
                self.ed.hover_at(sx, sy);
            } else if self.ed.hover.is_some() {
                self.ed.leave();
            }
            if released && self.left {
                self.left = false;
                self.ed.up(sx, sy);
            }
            if any_released && self.pan.is_some() && !ctx.input(|i| i.pointer.any_down()) {
                self.pan = None;
            }
            if resp.double_clicked() && !self.titles.iter().any(|(_, r)| r.contains(pos)) {
                self.ed.double_click(sx, sy);
            }
        }
        if self.pan.is_some() || self.space.is_some() {
            ctx.set_cursor_icon(if self.pan.is_some() {
                egui::CursorIcon::Grabbing
            } else {
                egui::CursorIcon::Grab
            });
        }
        let painter = ui.painter_at(rect);
        self.titles = paint(&painter, rect, &self.ed);
        if over
            && !self.left
            && let Some(pos) = pos
        {
            chip(&painter, rect, pos, &self.ed);
        }
    }

    // --- Overlays -----------------------------------------------------------------------

    fn overlays(&mut self, ctx: &egui::Context, play: &mut PlayView) {
        self.prompt_box(ctx);
        if let Some((mut name, err)) = self.save.take() {
            let mut keep = true;
            egui::Area::new(Id::new("ed_save"))
                .anchor(Align2::RIGHT_TOP, Vec2::new(-12.0, 92.0))
                .order(egui::Order::Foreground)
                .show(ctx, |ui| {
                    popup_frame().show(ui, |ui| {
                        ui.set_width(320.0);
                        ui.label(RichText::new("Save as a circuit").strong());
                        ui.label(
                            RichText::new(
                                "config/circuits/<name>.drawing.json and the compiled <name>.yaml",
                            )
                            .small()
                            .color(theme::MUTED),
                        );
                        let r = ui.add(
                            egui::TextEdit::singleline(&mut name)
                                .hint_text("name: lowercase, digits, _")
                                .font(FontId::monospace(14.0))
                                .desired_width(f32::INFINITY),
                        );
                        if !r.has_focus() && !r.lost_focus() {
                            r.request_focus();
                        }
                        let enter = r.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
                        let esc = ui.input(|i| i.key_pressed(egui::Key::Escape));
                        if !err.is_empty() {
                            ui.colored_label(theme::FAULT, &err);
                        }
                        ui.horizontal(|ui| {
                            let go = ui
                                .add(
                                    egui::Button::new(
                                        RichText::new("Save").color(theme::ACCENT_INK),
                                    )
                                    .fill(theme::ACCENT),
                                )
                                .clicked();
                            if ui.button("Cancel").clicked() || esc {
                                keep = false;
                            }
                            if go || enter {
                                match self.ed.save_as(name.trim()) {
                                    Ok(()) => {
                                        keep = false;
                                        self.circuits = list_circuits(&self.ed.circuits_dir);
                                    }
                                    Err(e) => self.save = Some((name.clone(), e)),
                                }
                            }
                        });
                    });
                });
            if keep && self.save.is_none() {
                self.save = Some((name, err));
            }
        }
        if let Some(l) = self.leave.clone() {
            let m = egui::Modal::new(Id::new("ed_leave")).show(ctx, |ui| {
                ui.label("Leave the unsaved edits?");
                ui.horizontal(|ui| {
                    if ui.button("Leave them").clicked() {
                        self.leave = None;
                        self.do_leave(l.clone());
                    }
                    if ui.button("Stay").clicked() {
                        self.leave = None;
                    }
                });
            });
            if m.should_close() {
                self.leave = None;
            }
        }
        if self.help {
            let m = egui::Modal::new(Id::new("ed_help")).show(ctx, |ui| {
                ui.set_width(640.0);
                ui.label(RichText::new("Keys").size(18.0).strong());
                ui.columns(2, |cols| {
                    for (i, (group, keys)) in SHORTCUTS.iter().enumerate() {
                        let ui = &mut cols[i % 2];
                        ui.add_space(6.0);
                        ui.label(
                            RichText::new(group.to_uppercase())
                                .small()
                                .color(theme::MUTED),
                        );
                        for (k, what) in keys.iter() {
                            ui.horizontal(|ui| {
                                ui.label(
                                    RichText::new(*k).monospace().small().color(theme::ACCENT),
                                );
                                ui.label(RichText::new(*what).small());
                            });
                        }
                    }
                });
            });
            if m.should_close() {
                self.help = false;
            }
        }
        self.command_palette(ctx, play);
    }

    fn prompt_box(&mut self, ctx: &egui::Context) {
        let Some(p) = self.ed.prompt.clone() else {
            self.prompt_shown = false;
            return;
        };
        if !self.prompt_shown {
            self.prompt_text = p.initial.clone();
            self.prompt_shown = true;
            self.prompt_armed = false;
        }
        let button_down = ctx.input(|i| i.pointer.any_down());
        let inside = ctx
            .pointer_latest_pos()
            .is_some_and(|q| self.prompt_rect.contains(q));
        let at = self.canvas_rect.min + Vec2::new(p.at.0 as f32, p.at.1 as f32);
        let mut answer: Option<Option<String>> = None;
        let shown = egui::Area::new(Id::new("ed_prompt"))
            .fixed_pos(at)
            .order(egui::Order::Foreground)
            .show(ctx, |ui| {
                popup_frame().show(ui, |ui| {
                    ui.set_width(220.0);
                    ui.label(RichText::new(&p.title).small().color(theme::MUTED));
                    let r = ui.add(
                        egui::TextEdit::singleline(&mut self.prompt_text)
                            .font(FontId::monospace(14.0))
                            .desired_width(f32::INFINITY),
                    );
                    if !self.prompt_armed && !button_down {
                        r.request_focus();
                        self.prompt_armed = true;
                    } else if self.prompt_armed && r.lost_focus() {
                        let esc = ui.input(|i| i.key_pressed(egui::Key::Escape));
                        let enter = ui.input(|i| i.key_pressed(egui::Key::Enter));
                        if !enter && !esc && inside {
                            self.prompt_armed = false; // a click on its own chips: focus again
                        } else {
                            answer = Some((enter && !esc).then(|| self.prompt_text.clone()));
                        }
                    }
                    let q = self.prompt_text.to_lowercase();
                    let opts: Vec<&String> = p
                        .options
                        .iter()
                        .filter(|o| q.is_empty() || o.to_lowercase().starts_with(&q))
                        .take(12)
                        .collect();
                    if !opts.is_empty() {
                        ui.horizontal_wrapped(|ui| {
                            for o in opts {
                                if ui.small_button(o.as_str()).clicked() {
                                    answer = Some(Some(o.clone()));
                                }
                            }
                        });
                    }
                });
            });
        self.prompt_rect = shown.response.rect;
        if let Some(a) = answer {
            self.ed.answer(a.as_deref());
            self.prompt_shown = false;
        }
    }

    fn commands(&self) -> Vec<(String, String, Cmd)> {
        let mut out = Vec::new();
        for (name, label) in PALETTE {
            if let Some(s) = symbols::get(name) {
                out.push((
                    format!("Place {label}"),
                    s.description.clone(),
                    Cmd::Place(name.into()),
                ));
            }
        }
        for n in 2..=12 {
            out.push((
                format!("Place rotary switch, {n} positions"),
                format!("SW_Rotary_{n}"),
                Cmd::Place(format!("SW_Rotary_{n}")),
            ));
        }
        for (mode, label, k) in [
            (Mode::Select, "Select", "V"),
            (Mode::Wire, "Wire", "W"),
            (Mode::Label, "Label a net", "L"),
            (Mode::Ground, "Ground", "G"),
            (Mode::Frame, "Section frame", "S"),
        ] {
            out.push((format!("Tool: {label}"), k.into(), Cmd::Tool(mode)));
        }
        for (i, f) in self.ed.drawing.frames.iter().enumerate() {
            out.push((
                format!("Go to section: {}", f.title),
                "section".into(),
                Cmd::Frame(i),
            ));
        }
        for (r, s) in &self.ed.drawing.symbols {
            out.push((
                format!("Find {r}"),
                format!("{} · {}", s.symbol, s.value),
                Cmd::Part(r.clone()),
            ));
        }
        for (i, n) in self.ed.analysis.nets.iter().enumerate() {
            if !n.node.starts_with("n_") {
                let name = if n.node == "0" { "ground" } else { &n.node };
                out.push((
                    format!("Find node {name}"),
                    format!("{} pins", n.pins.len()),
                    Cmd::Net(i),
                ));
            }
        }
        out.extend([
            ("Fit the drawing".to_string(), "F".to_string(), Cmd::Fit),
            ("Play / stop the drawing".into(), "Space".into(), Cmd::Play),
            ("Save as a circuit".into(), "Ctrl S".into(), Cmd::Save),
            ("Undo".into(), "Ctrl Z".into(), Cmd::Undo),
            ("Redo".into(), "Ctrl Shift Z".into(), Cmd::Redo),
            ("Keys".into(), "?".into(), Cmd::Keys),
            ("New circuit".into(), "a blank drawing".into(), Cmd::New),
        ]);
        out
    }

    fn command_palette(&mut self, ctx: &egui::Context, play: &mut PlayView) {
        let Some((mut q, mut at)) = self.palette.take() else {
            return;
        };
        let all = self.commands();
        let terms: Vec<String> = q
            .to_lowercase()
            .split_whitespace()
            .map(str::to_string)
            .collect();
        let mut shown: Vec<(i32, &(String, String, Cmd))> = all
            .iter()
            .filter_map(|c| {
                let l = c.0.to_lowercase();
                if terms.is_empty() {
                    return Some((0, c));
                }
                let h = c.1.to_lowercase();
                if !terms
                    .iter()
                    .all(|t| l.contains(t.as_str()) || h.contains(t.as_str()))
                {
                    return None;
                }
                let first = &terms[0];
                let s = i32::from(l.starts_with(first.as_str())) * 2
                    + i32::from(l.split([' ', ':']).any(|w| w.starts_with(first.as_str())));
                Some((s, c))
            })
            .collect();
        shown.sort_by(|a, b| b.0.cmp(&a.0));
        shown.truncate(14);
        at = at.min(shown.len().saturating_sub(1));
        let mut run: Option<Cmd> = None;
        let mut close = false;
        let m = egui::Modal::new(Id::new("ed_cmdk")).show(ctx, |ui| {
            ui.set_width(520.0);
            let (down, up, enter, esc) = ui.input_mut(|i| {
                (
                    i.consume_key(egui::Modifiers::NONE, egui::Key::ArrowDown),
                    i.consume_key(egui::Modifiers::NONE, egui::Key::ArrowUp),
                    i.key_pressed(egui::Key::Enter),
                    i.key_pressed(egui::Key::Escape),
                )
            });
            if down {
                at = (at + 1).min(shown.len().saturating_sub(1));
            }
            if up {
                at = at.saturating_sub(1);
            }
            let r = ui.add(
                egui::TextEdit::singleline(&mut q)
                    .hint_text("Place a part, a tool, find a part or node…")
                    .font(FontId::proportional(15.0))
                    .desired_width(f32::INFINITY),
            );
            r.request_focus();
            if r.changed() {
                at = 0;
            }
            if esc {
                close = true;
            }
            if enter && let Some((_, c)) = shown.get(at) {
                run = Some(c.2.clone());
            }
            ui.add_space(4.0);
            if shown.is_empty() {
                ui.label(RichText::new("nothing matches").small().color(theme::MUTED));
            }
            for (i, (_, c)) in shown.iter().enumerate() {
                let mut job = egui::text::LayoutJob::default();
                job.append(
                    &c.0,
                    0.0,
                    egui::TextFormat::simple(FontId::proportional(13.0), theme::INK),
                );
                job.append(
                    &format!("   {}", c.1),
                    0.0,
                    egui::TextFormat::simple(FontId::proportional(11.0), theme::MUTED),
                );
                if ui
                    .add(egui::Button::selectable(i == at, job).truncate())
                    .clicked()
                {
                    run = Some(c.2.clone());
                }
            }
        });
        if m.should_close() {
            close = true;
        }
        if let Some(c) = run {
            self.run(c, play);
            return;
        }
        if !close {
            self.palette = Some((q, at));
        }
    }

    fn run(&mut self, c: Cmd, play: &mut PlayView) {
        match c {
            Cmd::Place(name) => self.ed.set_mode(Mode::Place, Some(&name)),
            Cmd::Tool(m) => self.ed.set_mode(m, None),
            Cmd::Frame(i) => self.ed.show_frame(i),
            Cmd::Part(r) => {
                self.ed.select(Sel::symbol(&r), -1);
                self.ed.show_part(&r);
            }
            Cmd::Net(i) => {
                self.ed.select(Sel::default(), i as i64);
                self.ed.show_net(i);
            }
            Cmd::Fit => self.ed.fit(true),
            Cmd::Save => self.open_save(),
            Cmd::Undo => self.ed.undo(),
            Cmd::Redo => self.ed.redo(),
            Cmd::Keys => self.help = true,
            Cmd::New => {
                if self.ed.edited() && !self.ed.hist.past.is_empty() {
                    self.leave = Some(Leave::New);
                } else {
                    self.do_leave(Leave::New);
                }
            }
            Cmd::Play => play.toggle_drawing(),
        }
    }
}

// --- Painting ---------------------------------------------------------------------------

/// World (mm) to screen.
fn sp(o: Pos2, cam: &Camera, p: Pt) -> Pos2 {
    Pos2::new(
        o.x + (p.0 * cam.k + cam.x) as f32,
        o.y + (p.1 * cam.k + cam.y) as f32,
    )
}

/// One placed unit's body and pins (also a part being placed).
fn paint_unit(
    p: &egui::Painter,
    o: Pos2,
    cam: &Camera,
    g: &SymGeom,
    unit: i64,
    pl: &Placement,
    color: Color32,
) {
    let k = cam.k as f32;
    let stroke = Stroke::new(1.6, color);
    let at = |x: f64, y: f64| sp(o, cam, tf(x, y, pl));
    for s in &g.shapes {
        match s {
            Sym::Line { pts, filled } => {
                let pts: Vec<Pos2> = pts.iter().map(|&(x, y)| at(x, y)).collect();
                if *filled {
                    p.add(Shape::convex_polygon(pts, color, stroke));
                } else {
                    p.add(Shape::line(pts, stroke));
                }
            }
            Sym::Closed { pts } => {
                let pts: Vec<Pos2> = pts.iter().map(|&(x, y)| at(x, y)).collect();
                p.add(Shape::closed_line(pts, stroke));
            }
            Sym::Circle { c, r, filled } => {
                let c = at(c.0, c.1);
                if *filled {
                    p.circle(c, *r as f32 * k, color, stroke);
                } else {
                    p.circle_stroke(c, *r as f32 * k, stroke);
                }
            }
            Sym::Text {
                text,
                at: (x, y),
                size,
            } => {
                let fs = *size as f32 * k;
                if fs > 4.0 {
                    p.text(
                        at(*x, *y),
                        Align2::CENTER_CENTER,
                        *text,
                        FontId::proportional(fs),
                        color,
                    );
                }
            }
        }
    }
    for pin in g.unit_pins(unit) {
        let a = at(pin.x, pin.y);
        let b = at(
            pin.x + pin.into.0 * pin.length,
            pin.y + pin.into.1 * pin.length,
        );
        p.line_segment([a, b], stroke);
    }
}

const GROUND_LINES: [[Pt; 2]; 4] = [
    [(0.0, 0.0), (0.0, 1.27)],
    [(-1.52, 1.27), (1.52, 1.27)],
    [(-0.95, 1.9), (0.95, 1.9)],
    [(-0.38, 2.5), (0.38, 2.5)],
];

fn paint_ground(p: &egui::Painter, o: Pos2, cam: &Camera, g: &Placement, stroke: Stroke) {
    for [a, b] in GROUND_LINES {
        p.line_segment(
            [sp(o, cam, tf(a.0, a.1, g)), sp(o, cam, tf(b.0, b.1, g))],
            stroke,
        );
    }
}

fn wr(o: Pos2, cam: &Camera, b: [f64; 4]) -> Rect {
    Rect::from_two_pos(sp(o, cam, (b[0], b[1])), sp(o, cam, (b[2], b[3])))
}

/// The drawing, its states and the tools' ghost; returns the frame titles' rects.
fn paint(p: &egui::Painter, rect: Rect, ed: &Editor) -> Vec<(usize, Rect)> {
    let (d, sc) = ed.shown();
    let cam = &ed.cam;
    let o = rect.min;
    let k = cam.k;
    let kf = k as f32;

    // The dot grid.
    let mut step = 2.54;
    while step * k < 9.0 {
        step *= 5.0;
    }
    let (wx0, wy0) = cam.to_world(0.0, 0.0);
    let (wx1, wy1) = cam.to_world(cam.w, cam.h);
    let mut gx = (wx0 / step).floor() * step;
    while gx <= wx1 {
        let mut gy = (wy0 / step).floor() * step;
        while gy <= wy1 {
            let c = sp(o, cam, (gx, gy));
            p.rect_filled(Rect::from_center_size(c, Vec2::splat(2.0)), 0.0, theme::DOT);
            gy += step;
        }
        gx += step;
    }

    // Frames.
    for f in &d.frames {
        let r = wr(o, cam, [f.x, f.y, f.x + f.w, f.y + f.h]);
        p.rect_filled(
            r,
            CornerRadius::same((1.5 * kf).min(40.0) as u8),
            Color32::from_white_alpha(3),
        );
        let pts = vec![
            r.left_top(),
            r.right_top(),
            r.right_bottom(),
            r.left_bottom(),
            r.left_top(),
        ];
        p.extend(Shape::dashed_line(
            &pts,
            Stroke::new(1.2, theme::FRAME),
            6.0,
            5.0,
        ));
    }

    // Highlighted nets (hover, the inspector's) and nets with problems.
    let mut hl: HashSet<i64> = HashSet::new();
    if let Some(h) = &ed.hover {
        hl.insert(h.net());
    }
    hl.insert(ed.net);
    hl.remove(&-1);
    let mut bad: HashSet<i64> = HashSet::new();
    if !sc.preview {
        for m in &ed.markers {
            bad.extend(m.nets.iter().map(|&n| n as i64));
        }
    }
    let net_color = |n: i64, base: Color32, w: f32| -> Stroke {
        if bad.contains(&n) {
            Stroke::new(2.6, theme::FAULT)
        } else if hl.contains(&n) {
            Stroke::new(3.0, theme::NET)
        } else {
            Stroke::new(w, base)
        }
    };

    for (i, w) in d.wires.iter().enumerate() {
        let n = sc.wire_net.get(i).copied().unwrap_or(-1);
        let pts: Vec<Pos2> = w.iter().map(|&q| sp(o, cam, q)).collect();
        p.add(Shape::line(pts, net_color(n, theme::WIRE, 1.6)));
    }

    // Symbols.
    for u in &sc.units {
        let Some(s) = d.symbol(&u.r) else { continue };
        let (Some(g), Some(pl)) = (geom(&s.symbol), s.unit(u.unit)) else {
            continue;
        };
        if !rect.intersects(wr(o, cam, u.bbox).expand(4.0)) {
            continue;
        }
        match u.core_span {
            Some((y0, y1)) => {
                let st = Stroke::new(1.6, theme::PART);
                for dx in [-0.508, 0.508] {
                    p.line_segment(
                        [sp(o, cam, (pl.x + dx, y0)), sp(o, cam, (pl.x + dx, y1))],
                        st,
                    );
                }
            }
            None => paint_unit(p, o, cam, g, u.unit, pl, theme::PART),
        }
    }

    // Labels and grounds.
    for (i, l) in d.labels.iter().enumerate() {
        let n = sc.label_net.get(i).copied().unwrap_or(-1);
        let c = if bad.contains(&n) {
            theme::FAULT
        } else if hl.contains(&n) {
            theme::NET
        } else {
            theme::WIRE
        };
        p.circle_filled(sp(o, cam, (l.x, l.y)), 0.32 * kf, c);
        if k >= FAR_K {
            let (ax, ay, anchor) = match l.rot.rem_euclid(360) {
                180 => (-0.3, -0.85, Align2::RIGHT_CENTER),
                90 => (0.0, -1.0, Align2::CENTER_CENTER),
                270 => (0.0, 1.05, Align2::CENTER_CENTER),
                _ => (0.3, -0.85, Align2::LEFT_CENTER),
            };
            p.text(
                sp(o, cam, (l.x + ax, l.y + ay)),
                anchor,
                &l.name,
                FontId::monospace(1.35 * kf),
                c,
            );
        }
    }
    for (i, g) in d.grounds.iter().enumerate() {
        let n = sc.ground_net.get(i).copied().unwrap_or(-1);
        paint_ground(p, o, cam, g, net_color(n, theme::WIRE, 1.6));
    }

    // Names and values.
    if k >= FAR_K {
        for t in &sc.texts {
            let at = sp(o, cam, t.at);
            if !rect.expand(60.0).contains(at) {
                continue;
            }
            let anchor = match t.anchor {
                Anchor::Start => Align2::LEFT_CENTER,
                Anchor::Middle => Align2::CENTER_CENTER,
                Anchor::End => Align2::RIGHT_CENTER,
            };
            let (font, color) = match t.kind {
                TextKind::Ref => (FontId::proportional(1.55 * kf), theme::TEXT_PART),
                TextKind::Value => (FontId::monospace(1.35 * kf), theme::MUTED),
            };
            p.text(at, anchor, &t.text, font, color);
        }
    }
    for &j in &sc.junctions {
        p.circle_filled(sp(o, cam, j), 0.42 * kf, theme::WIRE);
    }
    for &q in &sc.open_pins {
        p.circle_stroke(
            sp(o, cam, q),
            0.55 * kf,
            Stroke::new(1.0, theme::alpha(theme::WARN, 0.75)),
        );
    }

    // Problems: rings around their parts, or around open pins.
    if !sc.preview {
        for (mi, m) in ed.markers.iter().enumerate() {
            let w = if ed.focus == Some(mi) { 2.6 } else { 1.6 };
            let st = Stroke::new(w, theme::FAULT);
            if m.check == "unconnected" {
                for &n in &m.nets {
                    for q in sc.pins.iter().filter(|q| q.net == n as i64) {
                        p.circle(
                            sp(o, cam, (q.x, q.y)),
                            1.1 * kf,
                            theme::alpha(theme::FAULT, 0.08),
                            st,
                        );
                    }
                }
            } else {
                for r in &m.symbols {
                    for b in sc.unit_boxes(r) {
                        let rr = wr(o, cam, [b[0] - 0.8, b[1] - 0.8, b[2] + 0.8, b[3] + 0.8]);
                        p.rect(
                            rr,
                            CornerRadius::same((1.4 * kf).min(40.0) as u8),
                            theme::alpha(theme::FAULT, 0.08),
                            st,
                            StrokeKind::Middle,
                        );
                    }
                }
            }
        }
    }

    // The selection.
    let s = &ed.sel;
    let radius = CornerRadius::same((0.8 * kf).min(30.0) as u8);
    for r in &s.symbols {
        for b in sc.unit_boxes(r) {
            p.rect(
                wr(o, cam, b),
                radius,
                theme::alpha(theme::ACCENT, 0.09),
                Stroke::new(1.5, theme::ACCENT),
                StrokeKind::Middle,
            );
        }
    }
    for &i in &s.wires {
        if let Some(w) = d.wires.get(i) {
            let pts: Vec<Pos2> = w.iter().map(|&q| sp(o, cam, q)).collect();
            p.add(Shape::line(
                pts,
                Stroke::new(3.0, theme::alpha(theme::ACCENT, 0.9)),
            ));
        }
    }
    for &i in &s.labels {
        if let Some(l) = d.labels.get(i) {
            p.circle_filled(sp(o, cam, (l.x, l.y)), 0.7 * kf, theme::ACCENT);
        }
    }
    for &i in &s.grounds {
        if let Some(g) = d.grounds.get(i) {
            p.circle_filled(sp(o, cam, (g.x, g.y)), 0.7 * kf, theme::ACCENT);
        }
    }
    for &i in &s.frames {
        if let Some(f) = d.frames.get(i) {
            let r = wr(o, cam, [f.x, f.y, f.x + f.w, f.y + f.h]);
            p.rect_stroke(
                r,
                CornerRadius::same((1.5 * kf).min(40.0) as u8),
                Stroke::new(1.5, theme::ACCENT),
                StrokeKind::Middle,
            );
            let h = Rect::from_center_size(
                r.right_bottom(),
                Vec2::splat(2.4 * kf).max(Vec2::splat(8.0)),
            );
            p.rect(
                h,
                2.0,
                theme::ACCENT,
                Stroke::new(1.0, theme::BG),
                StrokeKind::Middle,
            );
        }
    }

    // Hover: a net's pins, the pin under the pointer, the part under it.
    for &n in &hl {
        for q in sc.pins.iter().filter(|q| q.net == n) {
            p.circle_filled(sp(o, cam, (q.x, q.y)), 0.5 * kf, theme::NET);
        }
    }
    match &ed.hover {
        Some(Hit::Pin { i, .. }) => {
            if let Some(q) = sc.pins.get(*i) {
                p.circle_stroke(
                    sp(o, cam, (q.x, q.y)),
                    0.95 * kf,
                    Stroke::new(1.4, theme::ACCENT),
                );
            }
        }
        Some(Hit::Symbol { r, .. }) if !s.symbols.contains(r) => {
            for b in sc.unit_boxes(r) {
                p.rect(
                    wr(o, cam, b),
                    radius,
                    Color32::from_white_alpha(9),
                    Stroke::new(1.0, Color32::from_white_alpha(46)),
                    StrokeKind::Middle,
                );
            }
        }
        _ => {}
    }

    // The tools' ghost.
    if let Some(gh) = ed.ghost() {
        let dashed =
            |pts: &[Pos2]| Shape::dashed_line(pts, Stroke::new(1.6, theme::ACCENT), 5.0, 3.0);
        match gh {
            Ghost::Part { name, pl } => {
                if let Some(g) = geom(&name) {
                    paint_unit(p, o, cam, g, 1, &pl, theme::alpha(theme::ACCENT, 0.6));
                }
            }
            Ghost::Wire { pts, cursor } => {
                let pts: Vec<Pos2> = pts.iter().map(|&q| sp(o, cam, q)).collect();
                if pts.len() >= 2 {
                    p.extend(dashed(&pts));
                }
                p.circle_filled(sp(o, cam, cursor), (0.45 * kf).max(2.0), theme::ACCENT);
            }
            Ghost::Cursor(c) => {
                p.circle_filled(sp(o, cam, c), (0.45 * kf).max(2.0), theme::ACCENT);
            }
            Ghost::Ground(g) => paint_ground(
                p,
                o,
                cam,
                &g,
                Stroke::new(1.6, theme::alpha(theme::ACCENT, 0.7)),
            ),
            Ghost::Box(b) => {
                let r = wr(o, cam, b);
                p.rect_filled(r, 0.0, theme::alpha(theme::ACCENT, 0.07));
                let pts = vec![
                    r.left_top(),
                    r.right_top(),
                    r.right_bottom(),
                    r.left_bottom(),
                    r.left_top(),
                ];
                p.extend(Shape::dashed_line(
                    &pts,
                    Stroke::new(1.0, theme::ACCENT),
                    4.0,
                    3.0,
                ));
            }
            Ghost::FrameBox(b) => {
                let r = wr(o, cam, b);
                p.rect_filled(r, 0.0, Color32::from_white_alpha(5));
                let pts = vec![
                    r.left_top(),
                    r.right_top(),
                    r.right_bottom(),
                    r.left_bottom(),
                    r.left_top(),
                ];
                p.extend(Shape::dashed_line(
                    &pts,
                    Stroke::new(1.2, theme::FRAME),
                    4.0,
                    3.0,
                ));
            }
        }
    }

    // Frame titles, above each frame's top-left corner (screen size).
    let mut titles = Vec::new();
    for (i, f) in d.frames.iter().enumerate() {
        let at = sp(o, cam, (f.x, f.y)) + Vec2::new(2.0, -5.0);
        let n = sc.section.values().filter(|t| **t == f.title).count();
        let on = ed.sel.frames.contains(&i);
        let r = p.text(
            at,
            Align2::LEFT_BOTTOM,
            f.title.to_uppercase(),
            FontId::proportional(11.0),
            if on { theme::ACCENT } else { theme::MUTED },
        );
        p.text(
            r.right_bottom() + Vec2::new(6.0, 0.0),
            Align2::LEFT_BOTTOM,
            n.to_string(),
            FontId::monospace(11.0),
            theme::FAINT,
        );
        titles.push((i, r.expand(2.0)));
    }
    titles
}

/// The chip by the pointer: what is under it.
fn chip(p: &egui::Painter, rect: Rect, pos: Pos2, ed: &Editor) {
    let Some(h) = &ed.hover else { return };
    let (head, head_color, body) = match h {
        Hit::Symbol { r, .. } => {
            let Some(s) = ed.drawing.symbol(r) else {
                return;
            };
            let sec = ed.scene.section.get(r).cloned().unwrap_or_default();
            (format!("{r} · {}", s.value), theme::ACCENT, sec)
        }
        Hit::Pin { i, net } if *net < 0 => {
            let Some(q) = ed.scene.pins.get(*i) else {
                return;
            };
            let v = ed
                .drawing
                .symbol(&q.r)
                .map(|s| s.value.clone())
                .unwrap_or_default();
            (
                format!("{} · {v}", q.r),
                theme::ACCENT,
                format!("pin {} · drag to wire", q.name),
            )
        }
        h => {
            let net = h.net();
            let Some(n) = ed
                .analysis
                .nets
                .get(net.max(0) as usize)
                .filter(|_| net >= 0)
            else {
                return;
            };
            let pins: Vec<String> = ed
                .scene
                .pins
                .iter()
                .filter(|q| q.net == net)
                .map(|q| {
                    let multi = ed
                        .drawing
                        .symbol(&q.r)
                        .and_then(|s| symbols::get(&s.symbol))
                        .is_some_and(|s| s.units.len() > 1);
                    let u = if multi {
                        char::from(b'@' + q.unit as u8).to_string()
                    } else {
                        String::new()
                    };
                    format!("{}{u}.{}", q.r, q.name)
                })
                .collect();
            let name = if n.node == "0" { "ground" } else { &n.node };
            let mut head = format!(
                "{name} · {} pin{}",
                pins.len(),
                if pins.len() == 1 { "" } else { "s" }
            );
            if matches!(h, Hit::Pin { .. }) {
                head.push_str(" · drag to wire");
            }
            let mut body = pins.iter().take(8).cloned().collect::<Vec<_>>().join("  ");
            if pins.len() > 8 {
                body.push_str(" …");
            }
            (head, theme::NET, body)
        }
    };
    let g1 = p.layout_no_wrap(head, FontId::monospace(12.0), head_color);
    let g2 = p.layout(body, FontId::monospace(11.0), theme::MUTED, 340.0);
    let size = Vec2::new(
        g1.size().x.max(g2.size().x) + 18.0,
        g1.size().y + g2.size().y + 14.0,
    );
    let mut at = pos + Vec2::new(16.0, 18.0);
    if at.x + size.x > rect.right() - 8.0 {
        at.x = rect.right() - 8.0 - size.x;
    }
    if at.y + size.y > rect.bottom() {
        at.y = pos.y - size.y - 12.0;
    }
    let r = Rect::from_min_size(at, size);
    p.rect(
        r,
        7.0,
        theme::alpha(theme::CHROME2, 0.96),
        Stroke::new(1.0, theme::LINE),
        StrokeKind::Inside,
    );
    let y2 = at.y + 7.0 + g1.size().y;
    p.galley(at + Vec2::new(9.0, 7.0), g1, theme::INK);
    p.galley(Pos2::new(at.x + 9.0, y2), g2, theme::MUTED);
}

// --- Small widgets ----------------------------------------------------------------------

fn heading(ui: &mut egui::Ui, text: &str, right: &str) {
    ui.add_space(12.0);
    ui.horizontal(|ui| {
        ui.label(RichText::new(text).small().strong().color(theme::MUTED));
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            ui.label(RichText::new(right).small().monospace().color(theme::FAINT));
        });
    });
    ui.add_space(2.0);
}

fn empty(ui: &mut egui::Ui, text: &str) {
    ui.label(RichText::new(text).small().color(theme::FAINT));
}

fn field(ui: &mut egui::Ui, text: &str) {
    ui.add_space(8.0);
    ui.label(RichText::new(text).small().strong().color(theme::MUTED));
}

fn hint(ui: &mut egui::Ui, text: &str) {
    ui.label(RichText::new(text).small().color(theme::MUTED));
}

fn boxed(ui: &mut egui::Ui, text: &str) {
    egui::Frame::NONE
        .fill(theme::CHROME2)
        .stroke(Stroke::new(1.0, theme::LINE))
        .corner_radius(CornerRadius::same(7))
        .inner_margin(egui::Margin::symmetric(10, 7))
        .show(ui, |ui| {
            ui.set_width(ui.available_width());
            ui.label(RichText::new(text).monospace().size(12.5));
        });
}

fn tag(ui: &mut egui::Ui, text: &str, color: Color32) -> egui::Response {
    ui.add(
        egui::Button::new(
            RichText::new(text)
                .monospace()
                .small()
                .strong()
                .color(color),
        )
        .fill(theme::alpha(color, 0.15))
        .stroke(Stroke::NONE)
        .corner_radius(CornerRadius::same(4))
        .small(),
    )
}

fn badge(ui: &mut egui::Ui, text: &str, color: Color32) {
    egui::Frame::NONE
        .stroke(Stroke::new(1.0, theme::alpha(color, 0.45)))
        .corner_radius(CornerRadius::same(10))
        .inner_margin(egui::Margin::symmetric(8, 2))
        .show(ui, |ui| {
            ui.label(RichText::new(text).small().color(color));
        });
}

fn popup_frame() -> egui::Frame {
    egui::Frame::NONE
        .fill(theme::CHROME2)
        .stroke(Stroke::new(1.0, theme::LINE))
        .corner_radius(CornerRadius::same(10))
        .inner_margin(egui::Margin::same(12))
        .shadow(egui::epaint::Shadow {
            offset: [0, 8],
            blur: 24,
            spread: 0,
            color: Color32::from_black_alpha(120),
        })
}

/// A control's value as the front panel shows it.
fn fmt_ctl(v: &Value, unit: &str) -> String {
    match v {
        Value::Int(_) | Value::Float(_) => {
            let x = v.as_f64().unwrap_or(0.0);
            let u = if unit.is_empty() || unit == "rotation" || unit == "position" {
                String::new()
            } else {
                format!(" {unit}")
            };
            format!("{}{u}", js_str(to_precision(x, 4)))
        }
        other => value_text(other),
    }
}

/// A palette tile: the symbol drawn small, its label under it.
fn tile(ui: &mut egui::Ui, name: &str, label: &str, on: bool) -> egui::Response {
    let (rect, resp) = ui.allocate_exact_size(Vec2::new(48.0, 50.0), Sense::click());
    let p = ui.painter_at(rect);
    let bg = if on {
        theme::alpha(theme::ACCENT, 0.18)
    } else if resp.hovered() {
        theme::CHROME2
    } else {
        Color32::TRANSPARENT
    };
    p.rect_filled(rect, 6.0, bg);
    if let Some(g) = geom(name) {
        let b = g.bbox;
        let (cx, cy) = ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0);
        let w = (b[2] - b[0]).max(5.08);
        let h = (b[3] - b[1]).max(5.08);
        let k = (36.0 / w).min(28.0 / h);
        let mut cam = Camera::default();
        cam.set(f64::from(rect.width() / 2.0) - cx * k, 18.0 - cy * k, k);
        let color = if on { theme::ACCENT } else { theme::PART };
        paint_unit(
            &p,
            rect.min,
            &cam,
            g,
            1,
            &Placement {
                x: 0.0,
                y: 0.0,
                rot: 0,
                mirror: false,
            },
            color,
        );
    }
    p.text(
        Pos2::new(rect.center().x, rect.bottom() - 6.0),
        Align2::CENTER_CENTER,
        label,
        FontId::proportional(10.5),
        if on { theme::ACCENT } else { theme::MUTED },
    );
    let desc = symbols::get(name)
        .map(|s| s.description.clone())
        .unwrap_or_default();
    resp.on_hover_text(desc)
}
