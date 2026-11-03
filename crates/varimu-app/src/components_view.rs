//! The Components view (docs/COMPONENT_EDITOR_PLAN.md C2 step 7): a transformer component's
//! design edited by its construction, its compiled values, its winding window and its
//! response shown, heard in a circuit that pins it, saved as a version. The logic is
//! `varimu_app::components`; this paints it in the studio look.
//!
//! Left, the construction (core, bobbin, the winding plan's sections); middle, the window
//! drawn to scale, the compiled figures beside the opened version's, the response between
//! a stated source and load (the opened version's curve under it); bottom, listening: the
//! circuit it plays in, ▶ (Space), A / B against the circuit as pinned (loudness-matched),
//! Save as the next version, and moving the circuit to it.

use std::path::{Path, PathBuf};

use eframe::egui::{self, Color32, CornerRadius, FontId, RichText, Stroke, StrokeKind};
use varimu_app::components::{Bench, F_HIGH_HZ, F_LOW_HZ, Side, materials, transformer_components};
use varimu_circuit::yaml::Value;
use varimu_components::design::Arrangement;
use varimu_components::edit::{self, SectionKind, Step};
use varimu_components::geometry::Placed;
use varimu_components::path;
use varimu_components::response::{Curve, Ground};

use varimu_app::panel::DEVICES;
use varimu_app::player::AHEAD_S;

use crate::play_view::{DrawingDevice, PlayView};
use crate::theme;

/// One colour per winding (in the design's order).
const WINDING_COLOURS: [Color32; 6] = [
    theme::ACCENT,
    theme::NET,
    Color32::from_rgb(0x7a, 0xa2, 0xf0),
    Color32::from_rgb(0xe0, 0x7a, 0xa8),
    theme::OK,
    Color32::from_rgb(0xb8, 0x8c, 0xf0),
];

/// Seconds of the loop region a loudness match renders.
const MATCH_S: f64 = 8.0;

pub struct ComponentsView {
    config_dir: PathBuf,
    bench: Option<Bench>,
    error: Option<String>,
    components: Vec<(String, Vec<u32>)>,
    materials: Vec<String>,
    wires: Vec<String>,
    dielectrics: Vec<String>,
    laminations: Vec<String>,
    /// What was last sent to the player: (revision, saved, side, use), and whether this
    /// view drives the player's drawing at all (after its ▶).
    sent: Option<(u64, bool, Side, usize)>,
    driving: bool,
    side: Side,
    confirm_move: bool,
}

impl ComponentsView {
    pub fn new(config_dir: &Path, open: Option<&str>) -> ComponentsView {
        let components = transformer_components(config_dir);
        let mut v = ComponentsView {
            config_dir: config_dir.to_path_buf(),
            bench: None,
            error: None,
            materials: materials(config_dir),
            wires: Vec::new(),
            dielectrics: Vec::new(),
            laminations: Vec::new(),
            components,
            sent: None,
            driving: false,
            side: Side::Design,
            confirm_move: false,
        };
        // The 5E3's output transformer first: C2's component.
        let first = open.map(str::to_string).or_else(|| {
            v.components
                .iter()
                .find(|(n, _)| n == "OT_5E3")
                .or(v.components.first())
                .map(|(n, _)| n.clone())
        });
        if let Some(r) = first {
            v.open(&r);
        }
        v
    }

    fn open(&mut self, reference: &str) {
        match Bench::open(&self.config_dir, reference) {
            Ok(b) => {
                self.wires = b.tables.wire_codes();
                self.dielectrics = b.tables.dielectrics.keys().cloned().collect();
                self.laminations = b.tables.laminations.keys().cloned().collect();
                self.bench = Some(b);
                self.error = None;
                self.sent = None;
                self.side = Side::Design;
            }
            Err(e) => self.error = Some(e),
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui, play: &mut PlayView) {
        let ctx = ui.ctx().clone();
        play.tick(&ctx);
        if let Some(b) = &mut self.bench {
            if b.poll() {
                ctx.request_repaint();
            }
            if !b.settled() || b.matching() {
                ctx.request_repaint_after(std::time::Duration::from_millis(100));
            }
        }
        self.keys(&ctx, play);
        egui::Panel::top("cv_bar")
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(12, 7))
                    .stroke(Stroke::new(1.0, theme::LINE)),
            )
            .show(ui, |ui| self.bar(ui));
        egui::Panel::bottom("cv_listen")
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(12, 6))
                    .stroke(Stroke::new(1.0, theme::LINE)),
            )
            .show(ui, |ui| self.listen_bar(ui, play));
        egui::Panel::left("cv_left")
            .resizable(false)
            .exact_size(330.0)
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(10, 10)),
            )
            .show(ui, |ui| {
                egui::ScrollArea::vertical()
                    .id_salt("cv_left_scroll")
                    .show(ui, |ui| self.form(ui));
            });
        egui::CentralPanel::default()
            .frame(
                egui::Frame::NONE
                    .fill(theme::CANVAS)
                    .inner_margin(egui::Margin::symmetric(16, 12)),
            )
            .show(ui, |ui| {
                egui::ScrollArea::vertical()
                    .id_salt("cv_main_scroll")
                    .show(ui, |ui| self.main(ui));
            });
        self.sync_player(play);
    }

    // --- The player ---------------------------------------------------------------------

    /// Sends the circuit to the player when what it should play changed (the design's
    /// compile, its save, the A / B side, the circuit), once this view's ▶ was pressed.
    fn sync_player(&mut self, play: &mut PlayView) {
        let Some(b) = &self.bench else { return };
        if !self.driving {
            return;
        }
        let Some(o) = &b.outcome else { return };
        let key = (o.revision, o.saved.is_some(), self.side, b.play_in);
        if self.sent == Some(key) {
            return;
        }
        match b.playable(self.side) {
            Ok(p) => {
                // The look-ahead Play's device for this circuit keeps, if there is one.
                let ahead_s = DEVICES
                    .iter()
                    .find(|d| d.circuit == p.name)
                    .map_or(AHEAD_S, |d| d.ahead_s);
                play.set_drawing(DrawingDevice {
                    name: p.name,
                    title: p.title,
                    spec: p.spec,
                    lib: p.lib,
                    ahead_s,
                });
                self.sent = Some(key);
                self.apply_trim(play);
            }
            Err(e) => {
                if let Some(b) = &mut self.bench {
                    b.status = e;
                }
            }
        }
    }

    /// The A / B's trim: the design's side by the measured loudness difference while a
    /// match for this design exists (the running compensation off), else none.
    fn apply_trim(&self, play: &mut PlayView) {
        let trim = self.bench.as_ref().and_then(Bench::match_db);
        play.set_ab_trim(trim.map(|db| if self.side == Side::Design { db } else { 0.0 }));
    }

    fn toggle_play(&mut self, play: &mut PlayView) {
        if play.drawing_playing() && self.driving {
            play.toggle_drawing();
            return;
        }
        self.driving = true;
        self.sent = None;
        self.sync_player(play);
        if !play.drawing_playing() {
            play.toggle_drawing();
        }
    }

    fn set_side(&mut self, side: Side, play: &mut PlayView) {
        self.side = side;
        self.sync_player(play);
    }

    fn keys(&mut self, ctx: &egui::Context, play: &mut PlayView) {
        if ctx.egui_wants_keyboard_input() {
            return;
        }
        let (space, a, b, undo, redo) = ctx.input(|i| {
            (
                i.key_pressed(egui::Key::Space),
                i.key_pressed(egui::Key::A) && i.modifiers.is_none(),
                i.key_pressed(egui::Key::B) && i.modifiers.is_none(),
                i.key_pressed(egui::Key::Z) && i.modifiers.command && !i.modifiers.shift,
                (i.key_pressed(egui::Key::Z) && i.modifiers.command && i.modifiers.shift)
                    || (i.key_pressed(egui::Key::Y) && i.modifiers.command),
            )
        });
        if space {
            self.toggle_play(play);
        }
        if a {
            self.set_side(Side::Pinned, play);
        }
        if b {
            self.set_side(Side::Design, play);
        }
        if let Some(bench) = &mut self.bench {
            if undo {
                bench.undo();
            }
            if redo {
                bench.redo();
            }
        }
    }

    // --- The top bar --------------------------------------------------------------------

    fn bar(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            ui.label(RichText::new("Component").color(theme::MUTED));
            let current = self
                .bench
                .as_ref()
                .map_or(String::new(), |b| b.name.clone());
            let mut pick = None;
            egui::ComboBox::from_id_salt("cv_component")
                .width(150.0)
                .selected_text(if current.is_empty() { "–" } else { &current })
                .show_ui(ui, |ui| {
                    for (n, vs) in &self.components {
                        for v in vs.iter().rev() {
                            let label = format!("{n}@{v}");
                            if ui.selectable_label(false, &label).clicked() {
                                pick = Some(label);
                            }
                        }
                    }
                });
            if let Some(r) = pick {
                self.open(&r);
            }
            let Some(b) = &mut self.bench else {
                if let Some(e) = &self.error {
                    ui.colored_label(theme::FAULT, e);
                }
                return;
            };
            if let Some(r) = &b.opened {
                ui.label(
                    RichText::new(format!("opened {r}"))
                        .small()
                        .monospace()
                        .color(theme::FAINT),
                );
            }
            let edited = b.edited();
            chip(
                ui,
                if edited { "edited" } else { "as saved" },
                if edited { theme::WARN } else { theme::OK },
            );
            ui.add_space(8.0);
            if ui
                .add_enabled(b.can_undo(), egui::Button::new("↶ Undo"))
                .on_hover_text("Ctrl+Z")
                .clicked()
            {
                b.undo();
            }
            if ui
                .add_enabled(b.can_redo(), egui::Button::new("↷ Redo"))
                .on_hover_text("Ctrl+Shift+Z")
                .clicked()
            {
                b.redo();
            }
            ui.add_space(8.0);
            let next = format!("{}@{}", b.name, b.next_version());
            let ready = b.settled() && b.error.is_none();
            let saved = b.outcome.as_ref().and_then(|o| o.saved.clone());
            let label = match &saved {
                Some(r) if ready => format!("Saved as {r}"),
                _ => format!("Save as {next}"),
            };
            if ui
                .add_enabled(
                    ready && saved.is_none(),
                    egui::Button::new(RichText::new(label).strong())
                        .fill(theme::alpha(theme::ACCENT, 0.18)),
                )
                .on_hover_text(
                    "Save the design as the component's next version (immutable, with its line in \
                     versions.lock). Circuits keep the version they pin until moved.",
                )
                .clicked()
            {
                match b.save() {
                    Ok(_) => self.components = transformer_components(&self.config_dir),
                    Err(e) => b.status = e,
                }
            }
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                let (text, colour) = if let Some(e) = &b.error {
                    (format!("doesn't compile: {e}"), theme::FAULT)
                } else if !b.settled() {
                    let what = match &b.outcome {
                        Some(o) if o.preview && o.revision == b.revision => {
                            "the field solution computing (the formula's preview shown)…"
                        }
                        _ => "compiling…",
                    };
                    (what.to_string(), theme::MUTED)
                } else {
                    (b.status.clone(), theme::MUTED)
                };
                ui.label(RichText::new(text).small().color(colour));
            });
        });
    }

    // --- The construction ---------------------------------------------------------------

    fn form(&mut self, ui: &mut egui::Ui) {
        let Some(b) = &mut self.bench else {
            empty(ui, "No transformer component in config/components.");
            return;
        };
        if let Some(s) = edit::get(&b.design, &path!["source"]).and_then(Value::as_str) {
            ui.label(RichText::new(s).small().color(theme::MUTED))
                .on_hover_text(s);
        }
        heading(ui, "CORE", "");
        choice(
            ui,
            b,
            "Lamination",
            path!["core", "lamination"],
            &self.laminations,
        );
        choice(
            ui,
            b,
            "Material",
            path!["core", "material"],
            &self.materials,
        );
        number(
            ui,
            b,
            "Stack",
            path!["core", "stack_m"],
            1e3,
            " mm",
            0.1,
            (1.0, 200.0),
            false,
        );
        number(
            ui,
            b,
            "Stacking factor",
            path!["core", "stacking_factor"],
            1.0,
            "",
            0.005,
            (0.5, 1.0),
            false,
        );
        let stacks = ["interleaved".to_string(), "butt".to_string()];
        choice(ui, b, "Stacking", path!["core", "stacking"], &stacks);
        number(
            ui,
            b,
            "Joint gap",
            path!["core", "joint_gap_m"],
            1e6,
            " µm",
            0.5,
            (0.0, 2000.0),
            false,
        );
        let butt = edit::text(&b.design, &path!["core", "stacking"]).as_deref() == Some("butt");
        if butt {
            optional_number(
                ui,
                b,
                "Spacer",
                path!["core", "spacer_m"],
                1e6,
                " µm",
                1.0,
                (0.0, 5000.0),
                100e-6,
            );
        }

        heading(ui, "BOBBIN", "");
        number(
            ui,
            b,
            "Wall",
            path!["bobbin", "wall_m"],
            1e3,
            " mm",
            0.02,
            (0.0, 10.0),
            false,
        );
        number(
            ui,
            b,
            "Cheeks",
            path!["bobbin", "cheek_m"],
            1e3,
            " mm",
            0.02,
            (0.0, 10.0),
            false,
        );
        number(
            ui,
            b,
            "Margins",
            path!["bobbin", "margin_m"],
            1e3,
            " mm",
            0.05,
            (0.0, 20.0),
            false,
        );
        number(
            ui,
            b,
            "Pitch factor",
            path!["bobbin", "pitch_factor"],
            1.0,
            "",
            0.005,
            (1.0, 3.0),
            false,
        );

        heading(ui, "WINDING PLAN", "");
        let arr = ["layer".to_string(), "disc".to_string()];
        choice(ui, b, "Arrangement", path!["arrangement"], &arr);
        row(ui, "Leakage by", |ui| {
            let cur = edit::get(&b.design, &path!["leakage_method"])
                .and_then(Value::as_str)
                .unwrap_or("formula")
                .to_string();
            for (m, hint) in [
                ("formula", "the 1D energy method: instant"),
                (
                    "field",
                    "the 2D field solution of the window: a few seconds per winding pair (disc and sectioned windings)",
                ),
            ] {
                if ui
                    .selectable_label(cur == m, m)
                    .on_hover_text(hint)
                    .clicked()
                    && cur != m
                {
                    let _ = b.edit(path!["leakage_method"], |d| {
                        edit::set_plain(d, "leakage_method", Value::Str(m.into()))
                    });
                }
            }
        });
        let labels = b.winding_labels();
        ui.label(
            RichText::new(format!(
                "windings {} (the circuit names these; the first is the reference)",
                labels.join(", ")
            ))
            .small()
            .color(theme::FAINT),
        );
        ui.add_space(4.0);
        let n = edit::sections(&b.design).len();
        let mut action: Option<(usize, &str)> = None;
        for i in 0..n {
            let s = edit::sections(&b.design)[i].clone();
            let kind = edit::section_kind(&s);
            egui::Frame::NONE
                .fill(theme::CHROME2)
                .stroke(Stroke::new(1.0, theme::LINE))
                .corner_radius(CornerRadius::same(6))
                .inner_margin(egui::Margin::symmetric(8, 6))
                .show(ui, |ui| {
                    ui.set_width(ui.available_width());
                    ui.horizontal(|ui| {
                        let (title, colour) = match kind {
                            Some(SectionKind::Winding) => {
                                let w = edit::section_winding(&s).unwrap_or("?");
                                let k = labels.iter().position(|x| x == w).unwrap_or(0);
                                (format!("{} · winding {w}", i + 1), WINDING_COLOURS[k % 6])
                            }
                            Some(SectionKind::Insulation) => {
                                (format!("{} · insulation", i + 1), theme::MUTED)
                            }
                            Some(SectionKind::Shield) => {
                                (format!("{} · shield", i + 1), theme::WIRE)
                            }
                            None => (format!("{}", i + 1), theme::FAULT),
                        };
                        ui.label(RichText::new(title).small().strong().color(colour));
                        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                            if small_button(ui, "✕", "Remove").clicked() {
                                action = Some((i, "remove"));
                            }
                            if small_button(ui, "⧉", "Duplicate").clicked() {
                                action = Some((i, "dup"));
                            }
                            if kind == Some(SectionKind::Winding)
                                && small_button(
                                    ui,
                                    "✂",
                                    "Split in two along its turns and layers (to interleave)",
                                )
                                .clicked()
                            {
                                action = Some((i, "split"));
                            }
                            if i + 1 < n && small_button(ui, "↓", "Move outward / along").clicked()
                            {
                                action = Some((i, "down"));
                            }
                            if i > 0 && small_button(ui, "↑", "Move inward / back").clicked() {
                                action = Some((i, "up"));
                            }
                        });
                    });
                    match kind {
                        Some(SectionKind::Winding) => {
                            self_winding(ui, b, i, &labels, &self.wires, &self.dielectrics)
                        }
                        Some(SectionKind::Insulation) => {
                            number(
                                ui,
                                b,
                                "Thickness",
                                path!["sections", i, "insulation", "thickness_m"],
                                1e3,
                                " mm",
                                0.01,
                                (0.001, 20.0),
                                false,
                            );
                            choice(
                                ui,
                                b,
                                "Dielectric",
                                path!["sections", i, "insulation", "dielectric"],
                                &self.dielectrics,
                            );
                        }
                        Some(SectionKind::Shield) => {
                            number(
                                ui,
                                b,
                                "Thickness",
                                path!["sections", i, "shield", "thickness_m"],
                                1e3,
                                " mm",
                                0.005,
                                (0.001, 5.0),
                                false,
                            );
                        }
                        None => {}
                    }
                });
            ui.add_space(4.0);
        }
        if let Some((i, what)) = action {
            let src = edit::chosen(&varimu_components::store::today());
            let r = match what {
                "remove" => b.edit(vec![], |d| edit::remove_section(d, i).map(|_| ())),
                "dup" => b.edit(vec![], |d| edit::duplicate_section(d, i)),
                "up" => b.edit(vec![], |d| edit::move_section(d, i, i - 1)),
                "down" => b.edit(vec![], |d| edit::move_section(d, i, i + 1)),
                "split" => {
                    let s = &edit::sections(&b.design)[i];
                    let t = edit::number(s, &path!["turns"]).unwrap_or(0.0) as u32;
                    let l = edit::number(s, &path!["layers"]).unwrap_or(0.0) as u32;
                    b.edit(vec![], |d| edit::split_section(d, i, t / 2, l / 2, &src))
                }
                _ => Ok(()),
            };
            if let Err(e) = r {
                b.status = e;
            }
        }
        ui.horizontal(|ui| {
            if ui.button("+ insulation").clicked() {
                let src = edit::chosen(&varimu_components::store::today());
                let _ = b.edit(vec![], |d| {
                    edit::insert_section(d, usize::MAX, edit::insulation_section(0.13e-3, "kraft_dry", &src))
                });
            }
            if ui.button("+ shield").on_hover_text("A foil between sections: a terminal of its own the circuit names (shields: {S: node})").clicked() {
                let _ = b.edit(vec![], |d| {
                    let src = edit::chosen(&varimu_components::store::today());
                    let shield = Value::Map(varimu_circuit::yaml::Map(vec![(
                        "shield".into(),
                        Value::Map(varimu_circuit::yaml::Map(vec![
                            ("name".into(), Value::Str("S".into())),
                            ("thickness_m".into(), edit::sourced(Value::Float(0.05e-3), &src)),
                        ])),
                    )]));
                    edit::insert_section(d, usize::MAX, shield)
                });
            }
        });

        heading(ui, "RATING (FLUX CHECK)", "");
        number(
            ui,
            b,
            "Voltage",
            path!["rating", "v_rms"],
            1.0,
            " V rms",
            1.0,
            (0.001, 10000.0),
            false,
        );
        number(
            ui,
            b,
            "Lowest frequency",
            path!["rating", "f_hz"],
            1.0,
            " Hz",
            1.0,
            (1.0, 1000.0),
            false,
        );
        optional_number(
            ui,
            b,
            "Limit",
            path!["rating", "b_limit_t"],
            1.0,
            " T",
            0.01,
            (0.01, 3.0),
            1.2,
        );
        ui.add_space(12.0);
    }

    // --- The figures, the window, the response ------------------------------------------

    fn main(&mut self, ui: &mut egui::Ui) {
        let Some(b) = &mut self.bench else { return };
        if b.outcome.is_none() {
            empty(ui, "compiling…");
            return;
        }
        let o = b.outcome.as_ref().unwrap();
        let c = &o.compiled;
        let r = b.reference.as_ref();
        ui.horizontal_top(|ui| {
            let side = (ui.available_width() * 0.36).clamp(220.0, 420.0);
            ui.vertical(|ui| {
                ui.set_width(side);
                heading(
                    ui,
                    "WINDOW",
                    &format!("{} · {}", c.lamination.name, c.material.replace('_', " ")),
                );
                window(ui, c, side);
                ui.label(
                    RichText::new(format!(
                        "copper fill {:.1}% · area {:.2} cm² · path {:.1} cm · gap {:.0} µm",
                        100.0 * c.copper_fill,
                        c.area_m2 * 1e4,
                        c.path_m * 1e2,
                        c.gap_m * 1e6
                    ))
                    .small()
                    .color(theme::MUTED),
                );
            });
            ui.add_space(16.0);
            ui.vertical(|ui| {
                let was = r.and(b.opened.as_ref()).map(|o| format!("(was: {o})"));
                heading(ui, "COMPILED", was.as_deref().unwrap_or(""));
                figures(ui, c, r);
            });
        });
        let warnings = c.warnings.clone();
        heading(ui, "RESPONSE", "small signal, the core's linear limit");
        setup_controls(ui, b);
        let (now, before) = b.curves();
        plot(
            ui,
            now.as_ref(),
            before.as_ref(),
            b.opened.as_ref().map(ToString::to_string),
        );
        if !warnings.is_empty() {
            heading(ui, "WARNINGS", "");
            for w in &warnings {
                ui.label(RichText::new(format!("• {w}")).small().color(theme::WARN));
            }
        }
    }

    // --- Listening ------------------------------------------------------------------------

    fn listen_bar(&mut self, ui: &mut egui::Ui, play: &mut PlayView) {
        ui.horizontal(|ui| {
            ui.label(RichText::new("Listen in").color(theme::MUTED));
            let Some(b) = &mut self.bench else { return };
            if b.uses.is_empty() {
                ui.label(RichText::new("no circuit pins this component").small().color(theme::FAINT));
                return;
            }
            let cur = b.play_use().map_or(String::new(), |u| format!("{} (@{})", u.circuit, u.version));
            let mut pick = None;
            egui::ComboBox::from_id_salt("cv_use")
                .width(190.0)
                .selected_text(cur)
                .show_ui(ui, |ui| {
                    for (i, u) in b.uses.iter().enumerate() {
                        let drawn = if u.drawn { " · drawn" } else { "" };
                        if ui
                            .selectable_label(i == b.play_in, format!("{} (@{}){drawn}", u.circuit, u.version))
                            .clicked()
                        {
                            pick = Some(i);
                        }
                    }
                });
            if let Some(i) = pick {
                b.play_in = i;
            }
            let playing = play.drawing_playing() && self.driving;
            let label = if playing { "Stop  Space" } else { "▶ Play  Space" };
            let btn = egui::Button::new(RichText::new(label).strong()).fill(if playing {
                theme::alpha(theme::ACCENT, 0.2)
            } else {
                theme::CHROME2
            });
            let toggle = ui
                .add_enabled(b.outcome.is_some(), btn)
                .on_hover_text("Play the circuit through the Play view's file and loop region at draft-1x, with the design in the component's place: each edit is heard as it compiles")
                .clicked();
            ui.add_space(6.0);
            let pinned = b.play_use().map_or(String::new(), |u| format!("A  {}@{}", b.name, u.version));
            let design = match b.design_ref() {
                Some(r) if b.outcome.as_ref().is_some_and(|o| o.saved.is_some()) => format!("B  {r}"),
                Some(r) => format!("B  {r} (unsaved)"),
                None => "B  design".into(),
            };
            let mut side = None;
            if ui
                .selectable_label(self.side == Side::Pinned, RichText::new(pinned).monospace())
                .on_hover_text("The circuit as it pins the component (key A)")
                .clicked()
            {
                side = Some(Side::Pinned);
            }
            if ui
                .selectable_label(self.side == Side::Design, RichText::new(design).monospace())
                .on_hover_text("The design in its place (key B)")
                .clicked()
            {
                side = Some(Side::Design);
            }
            let m = match (b.matching(), b.match_db()) {
                (true, _) => "matching…".to_string(),
                (false, Some(db)) => format!("matched: B {db:+.2} dB"),
                _ => "Match loudness".to_string(),
            };
            let can_match = !b.matching() && b.outcome.is_some();
            let mut start_match = false;
            if ui
                .add_enabled(can_match, egui::Button::new(m))
                .on_hover_text(
                    "Render A and B through the loop region (up to 8 s) at draft-1x with the panel as set, \
                     measure their integrated loudness (BS.1770) and trim B by the difference; while a match \
                     holds, Play's running compensation is off. A new edit needs a new match.",
                )
                .clicked()
            {
                start_match = true;
            }
            // Moving the circuit to the saved design.
            let saved = b.outcome.as_ref().and_then(|o| o.saved.clone());
            if let (Some(to), Some(u)) = (saved, b.play_use())
                && to.version != Some(u.version)
            {
                let text = format!("Move {} to {to}…", u.circuit);
                if ui.button(text).clicked() {
                    self.confirm_move = true;
                }
            }
            ui.label(RichText::new(play.listen_line()).small().color(theme::MUTED));
            if start_match {
                match (play.match_input(MATCH_S), play.drawing_settings()) {
                    (Some(x), Ok(s)) => b.start_match(x, play.drawing_values(), s),
                    (None, _) => b.status = "no file to match on: open one in Play".into(),
                    (_, Err(e)) => b.status = e,
                }
            }
            if toggle {
                self.toggle_play(play);
            }
            if let Some(s) = side {
                self.set_side(s, play);
            }
        });
        // A match landing (or going stale) changes the trim.
        self.apply_trim(play);
        if self.confirm_move {
            self.move_dialog(ui.ctx());
        }
    }

    fn move_dialog(&mut self, ctx: &egui::Context) {
        let Some(b) = &mut self.bench else { return };
        let (Some(u), Some(to)) = (
            b.play_use().cloned(),
            b.outcome.as_ref().and_then(|o| o.saved.clone()),
        ) else {
            self.confirm_move = false;
            return;
        };
        let mut open = true;
        let mut done = false;
        egui::Window::new("Move the circuit to the new version")
            .collapsible(false)
            .resizable(false)
            .open(&mut open)
            .anchor(egui::Align2::CENTER_CENTER, egui::Vec2::ZERO)
            .show(ctx, |ui| {
                ui.label(format!(
                    "{} pins {}@{}. Moving it to {to} rewrites its parameter ({}) in {}.",
                    u.circuit,
                    b.name,
                    u.version,
                    u.params.join(", "),
                    u.path.display()
                ));
                ui.label(
                    RichText::new(
                        "Its IR changes as meant: rerun scripts/export_app_fixtures.py (and the goldens if the \
                         circuit has them) afterwards.",
                    )
                    .small()
                    .color(theme::MUTED),
                );
                ui.horizontal(|ui| {
                    if ui.button(RichText::new("Move").strong()).clicked() {
                        if let Err(e) = b.move_pin() {
                            b.status = e;
                        }
                        done = true;
                    }
                    if ui.button("Cancel").clicked() {
                        done = true;
                    }
                });
            });
        if done || !open {
            self.confirm_move = false;
            self.sent = None;
        }
    }
}

// --- The form's fields ------------------------------------------------------------------

fn self_winding(
    ui: &mut egui::Ui,
    b: &mut Bench,
    i: usize,
    labels: &[String],
    wires: &[String],
    dielectrics: &[String],
) {
    let s = edit::sections(&b.design)[i].clone();
    row(ui, "Winding", |ui| {
        let cur = edit::section_winding(&s).unwrap_or("").to_string();
        for w in labels {
            if ui.selectable_label(*w == cur, w).clicked() && *w != cur {
                let w = w.clone();
                if let Err(e) = b.edit(vec![], |d| edit::set_section_winding(d, i, &w)) {
                    b.status = e;
                }
            }
        }
    });
    number(
        ui,
        b,
        "Turns",
        path!["sections", i, "turns"],
        1.0,
        "",
        1.0,
        (1.0, 100_000.0),
        true,
    );
    number(
        ui,
        b,
        "Layers",
        path!["sections", i, "layers"],
        1.0,
        "",
        0.1,
        (1.0, 1000.0),
        true,
    );
    choice(ui, b, "Wire", path!["sections", i, "wire"], wires);
    choice(ui, b, "Enamel", path!["sections", i, "enamel"], dielectrics);
    let has = edit::get(&s, &path!["interlayer"]).is_some();
    if has {
        number(
            ui,
            b,
            "Between layers",
            path!["sections", i, "interlayer", "thickness_m"],
            1e3,
            " mm",
            0.005,
            (0.001, 5.0),
            false,
        );
        choice(
            ui,
            b,
            "  of",
            path!["sections", i, "interlayer", "dielectric"],
            dielectrics,
        );
    }
    ui.horizontal(|ui| {
        let built = edit::get(&s, &path!["build_m"]).is_some();
        if !built {
            let text = if has {
                "– interlayer paper"
            } else {
                "+ interlayer paper"
            };
            if ui.small_button(text).clicked() {
                let src = edit::chosen(&varimu_components::store::today());
                let r = if has {
                    b.edit(vec![], |d| {
                        edit::remove(d, &path!["sections", i, "interlayer"]).map(|_| ())
                    })
                } else {
                    b.edit(vec![], |d| {
                        edit::set(
                            d,
                            &path!["sections", i, "interlayer", "thickness_m"],
                            Value::Float(0.05e-3),
                            &src,
                        )?;
                        edit::set(
                            d,
                            &path!["sections", i, "interlayer", "dielectric"],
                            Value::Str("kraft_dry".into()),
                            &src,
                        )
                    })
                };
                if let Err(e) = r {
                    b.status = e;
                }
            }
        }
    });
    for (k, label) in [("width_m", "Drawn width"), ("build_m", "Drawn build")] {
        if edit::get(&s, &path![k]).is_some() {
            number(
                ui,
                b,
                label,
                path!["sections", i, k],
                1e3,
                " mm",
                0.05,
                (0.01, 200.0),
                false,
            );
        }
    }
}

fn row(ui: &mut egui::Ui, label: &str, add: impl FnOnce(&mut egui::Ui)) {
    ui.horizontal(|ui| {
        ui.add_sized(
            [118.0, 18.0],
            egui::Label::new(RichText::new(label).small().color(theme::MUTED)),
        );
        add(ui);
    });
}

/// The source of the value at `path`, for its hover.
fn source_of(b: &Bench, path: &[Step]) -> String {
    edit::source(&b.design, path).unwrap_or_else(|| "(no source)".into())
}

#[allow(clippy::too_many_arguments)]
fn number(
    ui: &mut egui::Ui,
    b: &mut Bench,
    label: &str,
    path: impl Into<Vec<Step>>,
    scale: f64,
    unit: &str,
    speed: f64,
    range: (f64, f64),
    int: bool,
) {
    let path: Vec<Step> = path.into();
    let Some(x) = edit::number(&b.design, &path) else {
        return;
    };
    let src = source_of(b, &path);
    row(ui, label, |ui| {
        let mut v = x * scale;
        let mut d = egui::DragValue::new(&mut v)
            .speed(speed)
            .range(range.0..=range.1)
            .suffix(unit);
        d = if int {
            d.fixed_decimals(0)
        } else {
            d.max_decimals(4)
        };
        let r = ui.add(d).on_hover_text(&src);
        if r.changed() {
            let new = if int {
                Value::Int(v.round() as i64)
            } else {
                Value::Float(v / scale)
            };
            if let Err(e) = b.set(path.clone(), new) {
                b.status = e;
            }
        }
        if src.starts_with("design choice") {
            ui.label(RichText::new("•").color(theme::ACCENT))
                .on_hover_text("set here: a design choice, not data");
        }
    });
}

#[allow(clippy::too_many_arguments)]
fn optional_number(
    ui: &mut egui::Ui,
    b: &mut Bench,
    label: &str,
    path: impl Into<Vec<Step>>,
    scale: f64,
    unit: &str,
    speed: f64,
    range: (f64, f64),
    default: f64,
) {
    let path: Vec<Step> = path.into();
    if edit::get(&b.design, &path).is_some() {
        number(ui, b, label, path.clone(), scale, unit, speed, range, false);
        ui.horizontal(|ui| {
            ui.add_space(122.0);
            if ui
                .small_button(format!("– {}", label.to_lowercase()))
                .clicked()
            {
                let p = path.clone();
                let _ = b.edit(vec![], move |d| edit::remove(d, &p).map(|_| ()));
            }
        });
    } else {
        row(ui, label, |ui| {
            if ui.small_button("+ add").clicked() {
                let _ = b.set(path, Value::Float(default));
            }
        });
    }
}

fn choice(
    ui: &mut egui::Ui,
    b: &mut Bench,
    label: &str,
    path: impl Into<Vec<Step>>,
    options: &[String],
) {
    let path: Vec<Step> = path.into();
    let Some(cur) = edit::text(&b.design, &path) else {
        return;
    };
    let src = source_of(b, &path);
    let id = format!("cv_choice_{path:?}");
    row(ui, label, |ui| {
        let mut pick = None;
        egui::ComboBox::from_id_salt(id)
            .width(170.0)
            .selected_text(cur.replace('_', " "))
            .show_ui(ui, |ui| {
                for o in options {
                    if ui
                        .selectable_label(*o == cur, o.replace('_', " "))
                        .clicked()
                    {
                        pick = Some(o.clone());
                    }
                }
            })
            .response
            .on_hover_text(&src);
        if let Some(p) = pick
            && p != cur
            && let Err(e) = b.set(path.clone(), Value::Str(p))
        {
            b.status = e;
        }
    });
}

// --- The window ---------------------------------------------------------------------------

/// The winding window to scale: the leg on the left, r across, z along the leg (down).
fn window(ui: &mut egui::Ui, c: &varimu_components::compile::Compiled, width: f32) {
    let lay = &c.layout;
    let (ww, wh) = (lay.window_width_m, lay.window_height_m);
    let leg = (lay.leg_m * 0.5).min(ww * 0.4);
    let total_w = leg + ww + 0.12 * ww;
    let scale = (width as f64 / total_w).min(260.0 / (wh * 1.12));
    let h = (wh * 1.12 * scale) as f32;
    let (rect, resp) = ui.allocate_exact_size(egui::vec2(width, h), egui::Sense::hover());
    let p = ui.painter_at(rect);
    p.rect_filled(rect, 4.0, theme::BG);
    let x0 = rect.left() + (leg * scale) as f32;
    let y0 = rect.top() + (0.06 * wh * scale) as f32;
    let to = |r: f64, z: f64| egui::pos2(x0 + (r * scale) as f32, y0 + (z * scale) as f32);
    // Iron around the window.
    let iron = theme::CHROME3;
    let win = egui::Rect::from_min_max(to(0.0, 0.0), to(ww, wh));
    p.rect_filled(
        egui::Rect::from_min_max(rect.min, egui::pos2(win.left(), rect.bottom())),
        0.0,
        iron,
    );
    p.rect_filled(
        egui::Rect::from_min_max(
            egui::pos2(win.left(), rect.top()),
            egui::pos2(rect.right(), win.top()),
        ),
        0.0,
        iron,
    );
    p.rect_filled(
        egui::Rect::from_min_max(egui::pos2(win.left(), win.bottom()), rect.max),
        0.0,
        iron,
    );
    p.rect_filled(
        egui::Rect::from_min_max(
            egui::pos2(win.right(), win.top()),
            egui::pos2(rect.right(), win.bottom()),
        ),
        0.0,
        iron,
    );
    p.rect_stroke(win, 0.0, Stroke::new(1.0, theme::LINE), StrokeKind::Middle);
    // The bobbin: its tube and cheeks.
    let d = &c.design;
    let z_off = d.bobbin.cheek_m.value + d.bobbin.margin_m.value;
    let cheek = d.bobbin.cheek_m.value;
    let bob = theme::alpha(theme::FAINT, 0.35);
    p.rect_filled(
        egui::Rect::from_min_max(to(0.0, 0.0), to(lay.wall_m, wh)),
        0.0,
        bob,
    );
    p.rect_filled(
        egui::Rect::from_min_max(to(0.0, 0.0), to(ww * 0.98, cheek)),
        0.0,
        bob,
    );
    p.rect_filled(
        egui::Rect::from_min_max(to(0.0, wh - cheek), to(ww * 0.98, wh)),
        0.0,
        bob,
    );
    // Insulation and shields.
    for pl in &lay.placed {
        match pl {
            Placed::Insulation {
                thickness_m,
                x0_m: a,
                ..
            } => {
                let r = match lay.arrangement {
                    Arrangement::Layer => egui::Rect::from_min_max(
                        to(*a, z_off),
                        to(a + thickness_m, z_off + lay.traverse_m),
                    ),
                    Arrangement::Disc => egui::Rect::from_min_max(
                        to(lay.wall_m, z_off + a),
                        to(ww * 0.95, z_off + a + thickness_m),
                    ),
                };
                p.rect_filled(r, 0.0, theme::alpha(theme::MUTED, 0.18));
            }
            Placed::Shield {
                thickness_m,
                x0_m: a,
                ..
            } => {
                let r = match lay.arrangement {
                    Arrangement::Layer => egui::Rect::from_min_max(
                        to(*a, z_off),
                        to(a + thickness_m.max(ww * 0.004), z_off + lay.traverse_m),
                    ),
                    Arrangement::Disc => egui::Rect::from_min_max(
                        to(lay.wall_m, z_off + a),
                        to(ww * 0.95, z_off + a + thickness_m.max(wh * 0.004)),
                    ),
                };
                p.rect_filled(r, 0.0, theme::WIRE);
            }
            Placed::Winding { .. } => {}
        }
    }
    // The layers.
    let mut hovered = None;
    for (i, l) in lay.layers.iter().enumerate() {
        let r = egui::Rect::from_min_max(to(l.r0_m, z_off + l.z0_m), to(l.r1_m, z_off + l.z1_m));
        let col = WINDING_COLOURS[l.winding % 6];
        p.rect_filled(r.shrink(0.25), 0.0, theme::alpha(col, 0.75));
        if resp.hover_pos().is_some_and(|q| r.contains(q)) {
            hovered = Some(i);
            p.rect_stroke(r, 0.0, Stroke::new(1.0, theme::INK), StrokeKind::Middle);
        }
    }
    if let Some(i) = hovered {
        let l = &lay.layers[i];
        resp.on_hover_text(format!(
            "{} · section {} · {:.1} turns · turn {:.1} mm long",
            c.windings[l.winding].label,
            l.section + 1,
            l.turns,
            l.mlt_m * 1e3
        ));
    }
    p.text(
        egui::pos2(rect.left() + 4.0, rect.bottom() - 4.0),
        egui::Align2::LEFT_BOTTOM,
        format!("{:.1} × {:.1} mm", ww * 1e3, wh * 1e3),
        FontId::monospace(10.0),
        theme::FAINT,
    );
}

// --- The figures ----------------------------------------------------------------------------

fn figures(
    ui: &mut egui::Ui,
    c: &varimu_components::compile::Compiled,
    r: Option<&varimu_components::compile::Compiled>,
) {
    let same = r.is_some_and(|r| r.windings.len() == c.windings.len());
    let was = |now: f64, old: Option<f64>, fmt: &dyn Fn(f64) -> String| -> RichText {
        let base = fmt(now);
        match old {
            Some(o) if same && (now - o).abs() > 0.005 * o.abs().max(1e-30) => {
                RichText::new(format!("{base}  ({})", fmt(o)))
                    .monospace()
                    .size(12.0)
                    .color(theme::ACCENT)
            }
            _ => RichText::new(base).monospace().size(12.0).color(theme::INK),
        }
    };
    egui::Grid::new("cv_figures")
        .num_columns(7)
        .spacing([14.0, 3.0])
        .show(ui, |ui| {
            for h in ["", "turns", "ratio", "DCR Ω", "Lm H", "leak mH", "C pF"] {
                ui.label(RichText::new(h).small().color(theme::MUTED));
            }
            ui.end_row();
            for (k, w) in c.windings.iter().enumerate() {
                let o = r.and_then(|r| r.windings.get(k));
                ui.label(
                    RichText::new(&w.label)
                        .strong()
                        .color(WINDING_COLOURS[k % 6]),
                );
                ui.label(was(w.turns, o.map(|x| x.turns), &|v| format!("{v:.0}")));
                ui.label(was(w.ratio, o.map(|x| x.ratio), &|v| format!("{v:.4}")));
                ui.label(was(w.r_ohm, o.map(|x| x.r_ohm), &|v| format!("{v:.3}")));
                let lm =
                    |cc: &varimu_components::compile::Compiled, x: f64| cc.magnetizing_h * x * x;
                ui.label(was(
                    lm(c, w.ratio),
                    o.zip(r).map(|(x, rr)| lm(rr, x.ratio)),
                    &|v| format!("{v:.3}"),
                ));
                ui.label(was(w.leak_h * 1e3, o.map(|x| x.leak_h * 1e3), &|v| {
                    format!("{v:.3}")
                }));
                ui.label(was(w.c_f * 1e12, o.map(|x| x.c_f * 1e12), &|v| {
                    format!("{v:.1}")
                }));
                ui.end_row();
            }
        });
    ui.add_space(6.0);
    ui.label(
        RichText::new("leakage, each winding with another shorted")
            .small()
            .color(theme::MUTED),
    );
    let n = c.windings.len();
    for j in 0..n {
        for k in 0..n {
            if j == k {
                continue;
            }
            let now = c.short_circuit_h(j, k) * 1e3;
            let old = r.filter(|_| same).map(|r| r.short_circuit_h(j, k) * 1e3);
            ui.label(was(now, old, &|v| {
                format!(
                    "{}:{} shorted  {v:.3} mH",
                    c.windings[j].label, c.windings[k].label
                )
            }));
        }
    }
    let caps = &c.network.caps;
    if !caps.is_empty() {
        let total: f64 = caps.iter().map(|x| x.2).sum();
        ui.label(
            RichText::new(format!(
                "{} capacitors between terminals, {:.1} pF in all",
                caps.len(),
                total * 1e12
            ))
            .small()
            .color(theme::MUTED),
        );
    }
    if let Some(bp) = c.b_peak_t {
        let rt = c.design.rating.as_ref().unwrap();
        let col = if bp > c.b_saturation_t {
            theme::FAULT
        } else {
            theme::MUTED
        };
        ui.label(
            RichText::new(format!(
                "flux {:.3} T peak at {} V rms, {} Hz (saturation {:.2} T)",
                bp, rt.v_rms.value, rt.f_hz.value, c.b_saturation_t
            ))
            .small()
            .color(col),
        );
    }
    let how = match c.design.leakage_method {
        varimu_components::design::LeakageMethod::Field => "leakage by the 2D field solution",
        varimu_components::design::LeakageMethod::Formula => "leakage by the 1D formula",
    };
    ui.label(RichText::new(how).small().color(theme::FAINT));
}

// --- The response ---------------------------------------------------------------------------

fn setup_controls(ui: &mut egui::Ui, b: &mut Bench) {
    let labels: Vec<String> = b
        .outcome
        .as_ref()
        .map(|o| {
            o.compiled
                .windings
                .iter()
                .map(|w| w.label.clone())
                .collect()
        })
        .unwrap_or_default();
    let Some(s) = &mut b.setup else {
        empty(ui, "one winding: no response to show");
        return;
    };
    ui.horizontal_wrapped(|ui| {
        ui.label(RichText::new("source").small().color(theme::MUTED));
        for (k, l) in labels.iter().enumerate() {
            let mut on = s.drive.contains(&k);
            if ui.checkbox(&mut on, l).changed() {
                if on && k != s.load {
                    s.drive.push(k);
                    s.drive.sort_unstable();
                } else if !on && s.drive.len() > 1 {
                    s.drive.retain(|&x| x != k);
                }
            }
        }
        let mut bal = s.ground == Ground::Middle;
        if ui
            .add_enabled(s.drive.len() % 2 == 0, egui::Checkbox::new(&mut bal, "balanced"))
            .on_hover_text("Two half sources at the ends, the middle junction grounded: a push-pull pair's plates")
            .changed()
        {
            s.ground = if bal { Ground::Middle } else { Ground::End };
        }
        if s.drive.len() % 2 != 0 {
            s.ground = Ground::End;
        }
        let sp = s.source_ohm * 0.01;
        ui.add(egui::DragValue::new(&mut s.source_ohm).speed(sp).range(0.01..=1e7).suffix(" Ω"));
        ui.add_space(12.0);
        ui.label(RichText::new("into").small().color(theme::MUTED));
        egui::ComboBox::from_id_salt("cv_load")
            .width(60.0)
            .selected_text(labels.get(s.load).cloned().unwrap_or_default())
            .show_ui(ui, |ui| {
                for (k, l) in labels.iter().enumerate() {
                    if !s.drive.contains(&k) {
                        ui.selectable_value(&mut s.load, k, l);
                    }
                }
            });
        let sp = s.load_ohm * 0.01;
        ui.add(egui::DragValue::new(&mut s.load_ohm).speed(sp).range(0.01..=1e8).suffix(" Ω"));
    });
}

fn plot(
    ui: &mut egui::Ui,
    now: Option<&Curve>,
    before: Option<&Curve>,
    before_label: Option<String>,
) {
    let w = ui.available_width();
    let h = 230.0;
    let (rect, _) = ui.allocate_exact_size(egui::vec2(w, h), egui::Sense::hover());
    let p = ui.painter_at(rect);
    p.rect_filled(rect, 4.0, theme::BG);
    let plot = rect
        .shrink2(egui::vec2(34.0, 16.0))
        .translate(egui::vec2(12.0, -4.0));
    let (db_lo, db_hi) = (-24.0, 6.0);
    let x_of = |f: f64| {
        plot.left()
            + ((f / F_LOW_HZ).log10() / (F_HIGH_HZ / F_LOW_HZ).log10()) as f32 * plot.width()
    };
    let y_of = |db: f64| {
        plot.top() + ((db_hi - db.clamp(db_lo, db_hi)) / (db_hi - db_lo)) as f32 * plot.height()
    };
    for f in [
        10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1e3, 2e3, 5e3, 1e4, 2e4, 5e4, 1e5,
    ] {
        let x = x_of(f);
        let major = [10.0, 100.0, 1e3, 1e4, 1e5].contains(&f);
        p.line_segment(
            [egui::pos2(x, plot.top()), egui::pos2(x, plot.bottom())],
            Stroke::new(1.0, if major { theme::LINE } else { theme::DOT }),
        );
        let label = if f >= 1e3 {
            format!("{}k", f / 1e3)
        } else {
            format!("{f}")
        };
        p.text(
            egui::pos2(x, plot.bottom() + 2.0),
            egui::Align2::CENTER_TOP,
            label,
            FontId::monospace(9.5),
            theme::FAINT,
        );
    }
    for db in [-24.0, -18.0, -12.0, -6.0, -3.0, 0.0, 6.0] {
        let y = y_of(db);
        p.line_segment(
            [egui::pos2(plot.left(), y), egui::pos2(plot.right(), y)],
            Stroke::new(1.0, if db == 0.0 { theme::FAINT } else { theme::DOT }),
        );
        p.text(
            egui::pos2(plot.left() - 4.0, y),
            egui::Align2::RIGHT_CENTER,
            format!("{db:+}"),
            FontId::monospace(9.5),
            theme::FAINT,
        );
    }
    let line = |c: &Curve, colour: Color32, width: f32| {
        let pts: Vec<egui::Pos2> = c
            .f_hz
            .iter()
            .zip(&c.db)
            .map(|(&f, &d)| egui::pos2(x_of(f), y_of(d)))
            .collect();
        p.add(egui::Shape::line(pts, Stroke::new(width, colour)));
    };
    if let Some(c) = before {
        line(c, theme::MUTED, 1.2);
    }
    if let Some(c) = now {
        line(c, theme::ACCENT, 2.0);
    }
    let fmt = |c: &Curve| {
        let hz = |f: Option<f64>| {
            f.map_or("–".into(), |f| {
                if f >= 1e3 {
                    format!("{:.1} kHz", f / 1e3)
                } else {
                    format!("{f:.1} Hz")
                }
            })
        };
        let z1k = c
            .f_hz
            .iter()
            .position(|&f| f >= 1e3)
            .map_or(0.0, |i| c.z_in_ohm[i]);
        format!(
            "-3 dB {} – {} · insertion loss {:.2} dB at 1 kHz · |Zin| {:.0} Ω",
            hz(c.low_3db_hz),
            hz(c.high_3db_hz),
            -c.loss_1khz_db,
            z1k
        )
    };
    let mut y = rect.top() + 6.0;
    if let Some(c) = now {
        p.text(
            egui::pos2(plot.left() + 6.0, y),
            egui::Align2::LEFT_TOP,
            format!("design   {}", fmt(c)),
            FontId::monospace(10.5),
            theme::ACCENT,
        );
        y += 14.0;
    }
    if let (Some(c), Some(l)) = (before, before_label) {
        p.text(
            egui::pos2(plot.left() + 6.0, y),
            egui::Align2::LEFT_TOP,
            format!("{l:<8} {}", fmt(c)),
            FontId::monospace(10.5),
            theme::MUTED,
        );
    }
}

// --- Small widgets ----------------------------------------------------------------------------

fn heading(ui: &mut egui::Ui, text: &str, right: &str) {
    ui.add_space(10.0);
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

fn chip(ui: &mut egui::Ui, text: &str, colour: Color32) {
    egui::Frame::NONE
        .fill(theme::alpha(colour, 0.14))
        .corner_radius(CornerRadius::same(4))
        .inner_margin(egui::Margin::symmetric(6, 1))
        .show(ui, |ui| {
            ui.label(RichText::new(text).small().color(colour));
        });
}

fn small_button(ui: &mut egui::Ui, text: &str, hint: &str) -> egui::Response {
    ui.add(egui::Button::new(RichText::new(text).small()).frame(false))
        .on_hover_text(hint)
}
