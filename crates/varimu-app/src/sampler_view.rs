//! The sampler in the Play view (`varimu_app::sampler`): its kit's twelve slots (the left
//! column) and a browser of the repo's `samples/` (the main area), whose files play as
//! they are chosen.
//!
//! Browsing: a click on a file plays it (the preview: heard, never recorded), ↑ / ↓ step
//! through the list playing each, Enter or a double-click loads the file into the slot
//! marked ▸ (then the mark moves to the next slot). A click on a slot marks it; its pad
//! plays it; × empties it. The filter searches every folder's file names.
//!
//! The kit is kept between runs (`sampler.json` beside the app's settings).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use eframe::egui::{self, RichText, Stroke};
use varimu_app::sampler::{SLOTS, Sample, Sampler};

use crate::theme;

/// The keys of an octave, slot by slot.
const KEYS: [&str; SLOTS] = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
];
/// How long a slot lights after a hit.
const LIT: Duration = Duration::from_millis(140);
/// A file row's height in the browser (px).
const ROW_H: f32 = 20.0;
/// Decoded files kept for previews (the oldest dropped past this).
const CACHE: usize = 400;

/// What the panel needs from the Play view this frame.
#[derive(Debug, Default, PartialEq)]
pub struct Wants {
    /// A sound to be heard: the sampler's player must be running.
    pub player: bool,
}

pub struct SamplerPanel {
    pub sampler: Arc<Sampler>,
    /// The browser: `samples/`, its folders holding audio (label, files), the folder shown,
    /// the filter, the file chosen.
    root: PathBuf,
    groups: Vec<(String, Vec<PathBuf>)>,
    folder: usize,
    filter: String,
    selected: Option<PathBuf>,
    /// The slot a file loads into.
    target: usize,
    cache: HashMap<PathBuf, Arc<Sample>>,
    /// Each slot's hits seen, and when it last lit.
    seen: [u64; SLOTS],
    lit: [Option<Instant>; SLOTS],
    /// Scroll the file list to the chosen file (it moved by the keys).
    scroll_to: bool,
    pub error: Option<String>,
}

impl SamplerPanel {
    /// The panel on `repo`'s `samples/`, the saved kit loaded.
    pub fn new(repo: &Path) -> SamplerPanel {
        let sampler = Arc::new(Sampler::default());
        let errors = sampler.load_saved();
        let mut p = SamplerPanel {
            sampler,
            root: repo.join("samples"),
            groups: Vec::new(),
            folder: 0,
            filter: String::new(),
            selected: None,
            target: 0,
            cache: HashMap::new(),
            seen: [0; SLOTS],
            lit: [None; SLOTS],
            scroll_to: false,
            error: (!errors.is_empty()).then(|| {
                format!(
                    "the saved kit: {} files didn't load ({})",
                    errors.len(),
                    errors[0]
                )
            }),
        };
        p.rescan();
        p
    }

    fn rescan(&mut self) {
        let mut groups = Vec::new();
        crate::play_view::scan_folder(&self.root, &self.root, &mut groups);
        // "samples / drums / kick" -> "drums / kick"
        for (label, _) in &mut groups {
            if let Some(rest) = label.strip_prefix("samples / ") {
                *label = rest.to_string();
            }
        }
        self.groups = groups;
        self.folder = self.folder.min(self.groups.len().saturating_sub(1));
    }

    /// A file decoded (cached).
    fn sample(&mut self, path: &Path) -> Result<Arc<Sample>, String> {
        if let Some(s) = self.cache.get(path) {
            return Ok(s.clone());
        }
        let s = Arc::new(Sample::load(path)?);
        if self.cache.len() >= CACHE {
            self.cache.clear();
        }
        self.cache.insert(path.to_path_buf(), s.clone());
        Ok(s)
    }

    fn preview(&mut self, path: &Path, wants: &mut Wants) {
        match self.sample(path) {
            Ok(s) => {
                self.sampler.preview(s);
                wants.player = true;
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }

    /// `path` into the marked slot; the mark moves on.
    fn load_into_target(&mut self, path: &Path) {
        match self.sample(path) {
            Ok(s) => {
                self.sampler.set_slot(self.target, Some(s));
                self.target = (self.target + 1) % SLOTS;
                self.save();
            }
            Err(e) => self.error = Some(e),
        }
    }

    fn save(&mut self) {
        if let Err(e) = self.sampler.save() {
            self.error = Some(format!("can't save the kit: {e}"));
        }
    }

    /// The files listed now: the folder's, or every folder's matching the filter.
    fn listed(&self) -> Vec<(&PathBuf, &str)> {
        let f = self.filter.trim().to_lowercase();
        if f.is_empty() {
            return self
                .groups
                .get(self.folder)
                .map_or_else(Vec::new, |(g, files)| {
                    files.iter().map(|p| (p, g.as_str())).collect()
                });
        }
        let words: Vec<&str> = f.split_whitespace().collect();
        self.groups
            .iter()
            .flat_map(|(g, files)| files.iter().map(move |p| (p, g.as_str())))
            .filter(|(p, g)| {
                let name = format!(
                    "{g} {}",
                    p.file_name().unwrap_or_default().to_string_lossy()
                )
                .to_lowercase();
                words.iter().all(|w| name.contains(w))
            })
            .collect()
    }

    /// The kit's column: level, velocity, the twelve slots.
    pub fn slots_ui(&mut self, ui: &mut egui::Ui, wants: &mut Wants) {
        let mut gain = self.sampler.gain_db();
        let mut vel = self.sampler.velocity();
        ui.horizontal(|ui| {
            ui.label(RichText::new("Level").color(theme::MUTED));
            let r = ui.add(
                egui::Slider::new(&mut gain, -24.0..=12.0)
                    .step_by(0.5)
                    .suffix(" dB"),
            );
            if r.changed() {
                self.sampler.set_gain_db(gain);
            }
            if r.drag_stopped() || (r.changed() && !r.dragged()) {
                self.save();
            }
        });
        if ui
            .checkbox(&mut vel, "Velocity")
            .on_hover_text(
                "On: a key's velocity sets its hit's level. Off: every hit at full level",
            )
            .changed()
        {
            self.sampler.set_velocity(vel);
            self.save();
        }
        ui.add_space(4.0);
        ui.label(
            RichText::new("Every octave of the keyboard plays these: C is slot 1, C# slot 2, …")
                .small()
                .color(theme::FAINT),
        );
        ui.add_space(4.0);
        let now = Instant::now();
        let mut clear = None;
        for (i, key) in KEYS.iter().enumerate() {
            let hits = self.sampler.hits(i);
            if hits != self.seen[i] {
                self.seen[i] = hits;
                self.lit[i] = Some(now);
            }
            let lit = self.lit[i].is_some_and(|t| now - t < LIT);
            let slot = self.sampler.slot(i);
            let marked = i == self.target;
            let frame = egui::Frame::NONE
                .fill(if marked {
                    theme::CHROME3
                } else {
                    theme::CHROME2
                })
                .stroke(Stroke::new(
                    1.0,
                    if marked { theme::ACCENT } else { theme::LINE },
                ))
                .corner_radius(4.0)
                .inner_margin(egui::Margin::symmetric(6, 3));
            let r = frame
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        let pad = egui::Button::new(
                            RichText::new(*key).monospace().strong().color(if lit {
                                theme::ACCENT_INK
                            } else {
                                theme::INK
                            }),
                        )
                        .fill(if lit { theme::ACCENT } else { theme::CHROME })
                        .min_size(egui::vec2(34.0, 22.0));
                        if ui
                            .add_enabled(slot.is_some(), pad)
                            .on_hover_text("Play it")
                            .clicked()
                        {
                            self.sampler.hit(i, 110);
                            wants.player = true;
                        }
                        let (name, pack) =
                            slot.as_ref().map_or(("—".to_string(), String::new()), |s| {
                                split_name(&s.name())
                            });
                        let w = ui.available_width() - 24.0;
                        ui.add_sized(
                            [w.max(40.0), 18.0],
                            egui::Label::new(RichText::new(name).color(if slot.is_some() {
                                theme::INK
                            } else {
                                theme::FAINT
                            }))
                            .truncate(),
                        )
                        .on_hover_text(pack);
                        if slot.is_some()
                            && ui
                                .small_button("×")
                                .on_hover_text("Empty the slot")
                                .clicked()
                        {
                            clear = Some(i);
                        }
                    });
                })
                .response
                .interact(egui::Sense::click());
            if r.clicked() {
                self.target = i;
            }
            ui.add_space(2.0);
        }
        if let Some(i) = clear {
            self.sampler.set_slot(i, None);
            self.save();
        }
        if ui.small_button("Empty every slot").clicked() {
            for i in 0..SLOTS {
                self.sampler.set_slot(i, None);
            }
            self.target = 0;
            self.save();
        }
        if self.lit.iter().any(Option::is_some) {
            ui.ctx().request_repaint_after(Duration::from_millis(30));
        }
    }

    /// The browser: folders, the filter, the files (a click plays one).
    pub fn browser_ui(&mut self, ui: &mut egui::Ui, wants: &mut Wants) {
        if self.groups.is_empty() {
            ui.label(
                RichText::new(format!(
                    "No sounds in {}: run scripts/import_samples.py to fill it",
                    self.root.display()
                ))
                .color(theme::MUTED),
            );
            if ui.button("Look again").clicked() {
                self.rescan();
            }
            return;
        }
        // The keys: ↑ / ↓ step and play, Enter loads (not while typing in another field).
        let typing_elsewhere = ui.ctx().egui_wants_keyboard_input()
            && !ui.memory(|m| m.has_focus(egui::Id::new("sampler_filter")));
        let (up, down, enter) = if typing_elsewhere {
            (false, false, false)
        } else {
            ui.input(|i| {
                (
                    i.key_pressed(egui::Key::ArrowUp),
                    i.key_pressed(egui::Key::ArrowDown),
                    i.key_pressed(egui::Key::Enter),
                )
            })
        };
        let listed: Vec<(PathBuf, String)> = self
            .listed()
            .into_iter()
            .map(|(p, g)| (p.clone(), g.to_string()))
            .collect();
        let at = self
            .selected
            .as_ref()
            .and_then(|s| listed.iter().position(|(p, _)| p == s));
        if (up || down) && !listed.is_empty() {
            let n = listed.len();
            let i = match (at, down) {
                (None, _) => 0,
                (Some(i), true) => (i + 1).min(n - 1),
                (Some(i), false) => i.saturating_sub(1),
            };
            let p = listed[i].0.clone();
            self.preview(&p, wants);
            self.selected = Some(p);
            self.scroll_to = true;
        }
        if enter && let Some(p) = self.selected.clone() {
            self.load_into_target(&p);
        }

        let h = ui.available_height().max(200.0);
        ui.horizontal_top(|ui| {
            // Folders.
            ui.vertical(|ui| {
                ui.set_width(210.0);
                egui::ScrollArea::vertical()
                    .id_salt("sampler_folders")
                    .max_height(h)
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        let mut pick = None;
                        let mut last_top = "";
                        for (i, (label, files)) in self.groups.iter().enumerate() {
                            // "drums / unlabeled / kick": the top folder once, as a heading.
                            let (top, rest) = label.split_once(" / ").unwrap_or(("", label));
                            if top != last_top {
                                ui.label(RichText::new(top).small().strong().color(theme::ACCENT));
                                last_top = top;
                            }
                            let on = i == self.folder && self.filter.trim().is_empty();
                            let text = format!("{rest}  ({})", files.len());
                            if ui.selectable_label(on, text).clicked() {
                                pick = Some(i);
                            }
                        }
                        if let Some(i) = pick {
                            self.folder = i;
                            self.filter.clear();
                        }
                    });
            });
            ui.separator();
            // Files.
            ui.vertical(|ui| {
                ui.horizontal(|ui| {
                    ui.add(
                        egui::TextEdit::singleline(&mut self.filter)
                            .id(egui::Id::new("sampler_filter"))
                            .hint_text("search every folder (e.g. 808 kick)")
                            .desired_width(260.0),
                    );
                    let target = format!("Load into {} ▸", KEYS[self.target]);
                    if ui
                        .add_enabled(self.selected.is_some(), egui::Button::new(target))
                        .on_hover_text("The chosen file into the marked slot (Enter, or double-click the file)")
                        .clicked()
                        && let Some(p) = self.selected.clone()
                    {
                        self.load_into_target(&p);
                    }
                    if ui.button("■").on_hover_text("Stop the preview").clicked() {
                        self.sampler.stop_preview();
                    }
                    ui.label(
                        RichText::new(format!("{} files · ↑↓ play · Enter loads", listed.len()))
                            .small()
                            .color(theme::FAINT),
                    );
                });
                ui.add_space(4.0);
                let searching = !self.filter.trim().is_empty();
                let mut area = egui::ScrollArea::vertical()
                    .id_salt("sampler_files")
                    .max_height(h - 34.0)
                    .auto_shrink([false, false]);
                let spacing = ui.spacing().item_spacing.y;
                if std::mem::take(&mut self.scroll_to)
                    && let Some(i) = self
                        .selected
                        .as_ref()
                        .and_then(|s| listed.iter().position(|(p, _)| p == s))
                {
                    let row = ROW_H + spacing;
                    let y = (i as f32 * row - (h - 34.0) * 0.4).max(0.0);
                    area = area.vertical_scroll_offset(y);
                }
                let mut clicked: Option<(PathBuf, bool)> = None;
                area.show_rows(ui, ROW_H, listed.len(), |ui, range| {
                    for (p, group) in &listed[range] {
                        let (name, pack) = split_name(
                            &p.file_stem().unwrap_or_default().to_string_lossy(),
                        );
                        let on = self.selected.as_ref() == Some(p);
                        let mut text = egui::text::LayoutJob::default();
                        let font = egui::TextStyle::Body.resolve(ui.style());
                        text.append(
                            &name,
                            0.0,
                            egui::TextFormat::simple(font.clone(), theme::INK),
                        );
                        let small = egui::TextStyle::Small.resolve(ui.style());
                        let where_ = if searching {
                            format!("{group} · {pack}")
                        } else {
                            pack
                        };
                        text.append(
                            &where_,
                            12.0,
                            egui::TextFormat::simple(small, theme::FAINT),
                        );
                        let r = ui.add_sized(
                            [ui.available_width(), ROW_H],
                            egui::Button::selectable(on, text).frame_when_inactive(false),
                        );
                        if r.double_clicked() {
                            clicked = Some((p.clone(), true));
                        } else if r.clicked() {
                            clicked = Some((p.clone(), false));
                        }
                    }
                });
                if let Some((p, load)) = clicked {
                    if load {
                        self.load_into_target(&p);
                    } else {
                        self.preview(&p, wants);
                    }
                    self.selected = Some(p);
                }
            });
        });
        if let Some(e) = &self.error {
            ui.colored_label(theme::FAULT, e);
        }
    }
}

/// A sorted file's name and its pack (`pack_name` from scripts/import_samples.py).
fn split_name(stem: &str) -> (String, String) {
    match stem.split_once('_') {
        Some((pack, name)) if !name.is_empty() => (name.to_string(), pack.to_string()),
        _ => (stem.to_string(), String::new()),
    }
}
