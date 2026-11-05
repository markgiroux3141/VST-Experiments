//! The Room view (docs/ROOM_LOOP_PLAN.md): a shoebox room drawn to scale from above,
//! sources (session tracks) and mics placed in it by dragging, each mic aimed (drag with
//! the right button or Shift, or "Aim at") and drawn with its pattern, its chain and
//! settings chosen at the side; Render records every source through every mic
//! (`varimu_app::room`'s background process) and adds a session track per mic, panned.
//! The scene is kept per session in `<session>/rooms/scene.json`.

use std::collections::BTreeMap;
use std::path::PathBuf;

use eframe::egui::{self, Color32, Pos2, Rect, RichText, Sense, Stroke, Vec2};
use serde_json::{Value, json};
use varimu_app::audio;
use varimu_app::room::{
    self, CEILINGS, CHAINS, MATERIALS, PRESETS, Pattern, QUALITIES, RenderJob, RoomMic, RoomSource,
    Scene,
};

use crate::session_view::SessionView;
use crate::theme;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Sel {
    Source(usize),
    Mic(usize),
}

#[derive(Clone, Copy, Debug)]
enum Drag {
    Move(Sel),
    Aim(usize),
    Corner(usize),
}

/// A render underway: the job, where its tracks go on the timeline, at what rate.
struct Running {
    job: RenderJob,
    position: i64,
    rate: u32,
    scene: Value,
}

pub struct RoomView {
    root: PathBuf,
    scene: Scene,
    /// The session folder the scene belongs to, and what was last written there.
    dir: Option<PathBuf>,
    saved: Value,
    sel: Option<Sel>,
    drag: Option<Drag>,
    running: Option<Running>,
    status: String,
    error: Option<String>,
    rt60: Option<String>,
    add_track: usize,
    add_chain: usize,
    /// The preset's width and depth (m).
    size: [f64; 2],
}

const SOURCE_COLOR: Color32 = theme::ACCENT;
const MIC_COLOR: Color32 = theme::NET;

impl RoomView {
    pub fn new(root: &std::path::Path) -> RoomView {
        RoomView {
            root: root.to_path_buf(),
            scene: Scene::default(),
            dir: None,
            saved: Value::Null,
            sel: None,
            drag: None,
            running: None,
            status: String::new(),
            error: None,
            rt60: None,
            add_track: 0,
            add_chain: 0,
            size: [7.0, 5.5],
        }
    }

    fn scene_file(dir: &std::path::Path) -> PathBuf {
        dir.join("rooms").join("scene.json")
    }

    /// Follow the session: its scene loaded when it changes, ours saved when edited.
    fn sync_session(&mut self, sv: &SessionView) {
        let dir = sv.session().dir.clone();
        if self.dir.as_ref() != Some(&dir) {
            self.scene = std::fs::read_to_string(Self::scene_file(&dir))
                .ok()
                .and_then(|t| serde_json::from_str::<Value>(&t).ok())
                .map(|v| Scene::from_state(&v))
                .unwrap_or_default();
            self.saved = self.scene.state();
            self.sel = None;
            self.dir = Some(dir);
            return;
        }
        let state = self.scene.state();
        if state != self.saved {
            let path = Self::scene_file(&dir);
            let _ = std::fs::create_dir_all(path.parent().unwrap());
            if let Err(e) = std::fs::write(&path, serde_json::to_string_pretty(&state).unwrap()) {
                self.error = Some(format!("{}: {e}", path.display()));
            }
            self.saved = state;
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui, sv: &mut SessionView) {
        self.sync_session(sv);
        self.poll(sv);
        if self.running.is_some() {
            ui.ctx()
                .request_repaint_after(std::time::Duration::from_millis(200));
        }
        egui::Panel::left("room_left")
            .resizable(false)
            .exact_size(340.0)
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(10, 10)),
            )
            .show(ui, |ui| {
                egui::ScrollArea::vertical()
                    .id_salt("room_left_scroll")
                    .show(ui, |ui| self.form(ui, sv));
            });
        egui::CentralPanel::default()
            .frame(
                egui::Frame::NONE
                    .fill(theme::CANVAS)
                    .inner_margin(egui::Margin::symmetric(16, 12)),
            )
            .show(ui, |ui| self.canvas(ui));
    }

    // --- The side panel ----------------------------------------------------------------

    fn form(&mut self, ui: &mut egui::Ui, sv: &mut SessionView) {
        ui.label(RichText::new("ROOM").strong().color(theme::MUTED));
        ui.horizontal(|ui| {
            ui.label("Name");
            ui.text_edit_singleline(&mut self.scene.name);
        });
        ui.horizontal(|ui| {
            ui.label("Shape");
            let mut pick = None;
            egui::ComboBox::from_id_salt("room_shape")
                .selected_text(&self.scene.shape)
                .show_ui(ui, |ui| {
                    for pr in PRESETS {
                        if ui.selectable_label(self.scene.shape == *pr, *pr).clicked() {
                            pick = Some(*pr);
                        }
                    }
                });
            let mut resized = false;
            for i in 0..2 {
                ui.label(["W", "D"][i]);
                resized |= ui
                    .add(
                        egui::DragValue::new(&mut self.size[i])
                            .range(2.0..=40.0)
                            .speed(0.05)
                            .suffix(" m")
                            .max_decimals(2),
                    )
                    .changed();
            }
            let shape = self.scene.shape.clone();
            if let Some(pr) = pick {
                self.scene.set_preset(pr, self.size[0], self.size[1]);
            } else if resized && shape != "custom" {
                self.scene.set_preset(&shape, self.size[0], self.size[1]);
            }
        });
        if self.scene.shape == "custom" {
            ui.label(
                RichText::new("custom plan: drag corners, double-click a wall for a corner, right-click a corner to remove it")
                    .small()
                    .color(theme::FAINT),
            );
        }
        ui.horizontal(|ui| {
            ui.label("Ceiling");
            let r = &mut self.scene.roof;
            egui::ComboBox::from_id_salt("room_ceiling")
                .selected_text(&r.kind)
                .show_ui(ui, |ui| {
                    for c in CEILINGS {
                        ui.selectable_value(&mut r.kind, c.to_string(), *c);
                    }
                });
            ui.add(
                egui::DragValue::new(&mut r.height)
                    .range(1.5..=30.0)
                    .speed(0.02)
                    .suffix(" m")
                    .max_decimals(2),
            )
            .on_hover_text("height (at the eaves / the low side)");
            if r.kind != "flat" {
                ui.label("to");
                ui.add(
                    egui::DragValue::new(&mut r.peak)
                        .range(1.5..=40.0)
                        .speed(0.02)
                        .suffix(" m")
                        .max_decimals(2),
                )
                .on_hover_text("the peak (the ridge, the high side, the vault's crown)");
            }
        });
        if self.scene.roof.kind != "flat" {
            ui.horizontal(|ui| {
                let r = &mut self.scene.roof;
                ui.label("Slope across");
                ui.add(
                    egui::DragValue::new(&mut r.axis_deg)
                        .range(-180.0..=180.0)
                        .speed(1.0)
                        .suffix("°"),
                )
                .on_hover_text(
                    "the direction the ceiling rises along (0° = across the plan, left to right)",
                );
                if r.kind == "vault" {
                    ui.label("facets");
                    ui.add(egui::DragValue::new(&mut r.facets).range(2..=24));
                }
            });
        }
        for (label, which) in [
            ("Wall surface", 0),
            ("Floor surface", 1),
            ("Ceiling surface", 2),
        ] {
            let v = match which {
                0 => &mut self.scene.walls,
                1 => &mut self.scene.floor,
                _ => &mut self.scene.ceiling,
            };
            ui.horizontal(|ui| {
                ui.label(label);
                egui::ComboBox::from_id_salt(("room_mat", which))
                    .selected_text(v.replace('_', " "))
                    .show_ui(ui, |ui| {
                        for m in MATERIALS {
                            ui.selectable_value(v, m.to_string(), m.replace('_', " "));
                        }
                    });
            });
        }
        if let Some(rt) = &self.rt60 {
            ui.label(RichText::new(rt).small().color(theme::MUTED));
        }
        ui.separator();

        // Sources
        ui.label(RichText::new("SOURCES").strong().color(theme::MUTED));
        let tracks: Vec<(String, String)> = sv
            .session()
            .tracks
            .iter()
            .filter(|t| t.active_take().is_some())
            .map(|t| (t.id.clone(), t.name.clone()))
            .collect();
        let track_name = |id: &str| {
            tracks
                .iter()
                .find(|(i, _)| i == id)
                .map_or("(no track)".to_string(), |(_, n)| n.clone())
        };
        for (i, s) in self.scene.sources.iter().enumerate() {
            let on = self.sel == Some(Sel::Source(i));
            let text = format!(
                "● {}  ·  {}  ·  {:.0} dB",
                s.name,
                track_name(&s.track),
                s.spl_db
            );
            if ui
                .selectable_label(on, RichText::new(text).color(SOURCE_COLOR))
                .clicked()
            {
                self.sel = Some(Sel::Source(i));
            }
        }
        ui.horizontal(|ui| {
            if tracks.is_empty() {
                ui.label(
                    RichText::new("record or load a take in the Session view first")
                        .small()
                        .color(theme::FAINT),
                );
                return;
            }
            self.add_track = self.add_track.min(tracks.len() - 1);
            egui::ComboBox::from_id_salt("room_add_track")
                .selected_text(&tracks[self.add_track].1)
                .show_ui(ui, |ui| {
                    for (k, (_, n)) in tracks.iter().enumerate() {
                        ui.selectable_value(&mut self.add_track, k, n);
                    }
                });
            if ui.button("+ Source").clicked() {
                let (id, name) = tracks[self.add_track].clone();
                let n = self.scene.sources.len() as f64;
                let (lo, hi) = self.scene.bbox();
                let mut pos = [
                    lo[0] + (hi[0] - lo[0]) * (0.3 + 0.2 * n).min(0.8),
                    lo[1] + (hi[1] - lo[1]) * 0.45,
                    1.3,
                ];
                if !self.scene.inside(&pos) {
                    pos = centroid(&self.scene);
                }
                self.scene.sources.push(RoomSource {
                    name: unique(&self.scene, &name),
                    track: id,
                    spl_db: 90.0,
                    pos,
                });
                self.sel = Some(Sel::Source(self.scene.sources.len() - 1));
            }
        });
        ui.separator();

        // Mics
        ui.label(RichText::new("MICS").strong().color(theme::MUTED));
        for (i, m) in self.scene.mics.iter().enumerate() {
            let on = self.sel == Some(Sel::Mic(i));
            let chain = room::chain(&m.chain).map_or(m.chain.as_str(), |c| c.label);
            let text = format!("◉ {}  ·  {}  ·  pan {:+.2}", m.name, chain, m.pan);
            if ui
                .selectable_label(on, RichText::new(text).color(MIC_COLOR))
                .clicked()
            {
                self.sel = Some(Sel::Mic(i));
            }
        }
        ui.horizontal(|ui| {
            egui::ComboBox::from_id_salt("room_add_chain")
                .selected_text(CHAINS[self.add_chain].label)
                .show_ui(ui, |ui| {
                    for (k, c) in CHAINS.iter().enumerate() {
                        ui.selectable_value(&mut self.add_chain, k, c.label);
                    }
                });
            if ui.button("+ Mic").clicked() {
                let (lo, hi) = self.scene.bbox();
                let name = self.scene.free_name("Mic");
                let mut pos = [0.5 * (lo[0] + hi[0]), lo[1] + 0.8 * (hi[1] - lo[1]), 1.5];
                if !self.scene.inside(&pos) {
                    pos = centroid(&self.scene);
                }
                let mut m = RoomMic::new(&name, CHAINS[self.add_chain].id, pos, -90.0);
                if let Some(s) = self.scene.sources.first() {
                    m.aim_at(s.pos[0], s.pos[1]);
                }
                self.scene.mics.push(m);
                self.sel = Some(Sel::Mic(self.scene.mics.len() - 1));
            }
        });
        ui.separator();

        // The selected item
        match self.sel {
            Some(Sel::Source(i)) if i < self.scene.sources.len() => {
                self.source_form(ui, i, &tracks)
            }
            Some(Sel::Mic(i)) if i < self.scene.mics.len() => self.mic_form(ui, i),
            _ => {
                ui.label(
                    RichText::new(
                        "Drag sources and mics on the plan. Right-drag (or Shift-drag) a mic to aim it. Delete removes the selected one.",
                    )
                    .small()
                    .color(theme::FAINT),
                );
            }
        }
        ui.separator();
        self.render_form(ui, sv);
    }

    fn source_form(&mut self, ui: &mut egui::Ui, i: usize, tracks: &[(String, String)]) {
        let dims = bounds(&self.scene);
        let mut delete = false;
        {
            let s = &mut self.scene.sources[i];
            ui.label(
                RichText::new(format!("SOURCE {}", s.name))
                    .strong()
                    .color(SOURCE_COLOR),
            );
            ui.horizontal(|ui| {
                ui.label("Name");
                ui.text_edit_singleline(&mut s.name);
            });
            ui.horizontal(|ui| {
                ui.label("Track");
                let cur = tracks
                    .iter()
                    .find(|(id, _)| *id == s.track)
                    .map_or("(none)".to_string(), |(_, n)| n.clone());
                egui::ComboBox::from_id_salt("room_src_track")
                    .selected_text(cur)
                    .show_ui(ui, |ui| {
                        for (id, n) in tracks {
                            ui.selectable_value(&mut s.track, id.clone(), n);
                        }
                    });
            });
            ui.horizontal(|ui| {
                ui.label("Level at 1 m");
                ui.add(
                    egui::DragValue::new(&mut s.spl_db)
                        .range(40.0..=130.0)
                        .speed(0.5)
                        .suffix(" dB SPL"),
                );
            });
            position_fields(ui, &mut s.pos, dims);
            if ui.button("Delete source").clicked() {
                delete = true;
            }
        }
        let s = self.scene.sources[i].clone();
        for m in &self.scene.mics {
            ui.label(
                RichText::new(format!(
                    "{} → {}: {:.2} m",
                    s.name,
                    m.name,
                    dist(&s.pos, &m.pos)
                ))
                .small()
                .color(theme::MUTED),
            );
        }
        if delete {
            self.scene.sources.remove(i);
            self.sel = None;
        }
    }

    fn mic_form(&mut self, ui: &mut egui::Ui, i: usize) {
        let dims = bounds(&self.scene);
        let sources = self.scene.sources.clone();
        let mut delete = false;
        let m = &mut self.scene.mics[i];
        ui.label(
            RichText::new(format!("MIC {}", m.name))
                .strong()
                .color(MIC_COLOR),
        );
        ui.horizontal(|ui| {
            ui.label("Name");
            ui.text_edit_singleline(&mut m.name);
        });
        ui.horizontal(|ui| {
            ui.label("Chain");
            let cur = room::chain(&m.chain).map_or(m.chain.clone(), |c| c.label.to_string());
            let mut picked = None;
            egui::ComboBox::from_id_salt("room_mic_chain")
                .selected_text(cur)
                .show_ui(ui, |ui| {
                    for c in CHAINS {
                        if ui.selectable_label(m.chain == c.id, c.label).clicked() {
                            picked = Some(c.id);
                        }
                    }
                });
            if let Some(id) = picked
                && id != m.chain
            {
                let fresh = RoomMic::new(&m.name, id, m.pos, m.azimuth_deg);
                m.chain = fresh.chain;
                m.set = fresh.set;
            }
        });
        if let Some(c) = room::chain(&m.chain) {
            for st in c.settings {
                let v = m.set.entry(st.key.to_string()).or_insert(st.default);
                ui.horizontal(|ui| {
                    ui.label(st.label);
                    let cur = st
                        .choices
                        .iter()
                        .find(|(x, _)| x == v)
                        .map_or(format!("{v}"), |(_, l)| l.to_string());
                    egui::ComboBox::from_id_salt(("room_set", st.key))
                        .selected_text(cur)
                        .show_ui(ui, |ui| {
                            for (x, l) in st.choices {
                                ui.selectable_value(v, *x, *l);
                            }
                        });
                });
            }
        }
        position_fields(ui, &mut m.pos, dims);
        ui.horizontal(|ui| {
            ui.label("Aim");
            ui.add(
                egui::DragValue::new(&mut m.azimuth_deg)
                    .range(-180.0..=180.0)
                    .speed(1.0)
                    .suffix("°"),
            );
            ui.label("tilt");
            ui.add(
                egui::DragValue::new(&mut m.elevation_deg)
                    .range(-90.0..=90.0)
                    .speed(1.0)
                    .suffix("°"),
            );
        });
        ui.horizontal_wrapped(|ui| {
            for s in &sources {
                if ui.small_button(format!("Aim at {}", s.name)).clicked() {
                    m.aim_at(s.pos[0], s.pos[1]);
                    let d = ((s.pos[0] - m.pos[0]).powi(2) + (s.pos[1] - m.pos[1]).powi(2)).sqrt();
                    m.elevation_deg = (s.pos[2] - m.pos[2]).atan2(d).to_degrees();
                }
            }
        });
        ui.horizontal(|ui| {
            ui.label("Pan");
            ui.add(egui::Slider::new(&mut m.pan, -1.0..=1.0).step_by(0.05));
        });
        for s in &sources {
            let off = off_axis_deg(m, &s.pos);
            ui.label(
                RichText::new(format!(
                    "{}: {:.2} m, {:.0}° off axis",
                    s.name,
                    dist(&s.pos, &m.pos),
                    off
                ))
                .small()
                .color(theme::MUTED),
            );
        }
        if ui.button("Delete mic").clicked() {
            delete = true;
        }
        if delete {
            self.scene.mics.remove(i);
            self.sel = None;
        }
    }

    fn render_form(&mut self, ui: &mut egui::Ui, sv: &mut SessionView) {
        ui.label(RichText::new("RENDER").strong().color(theme::MUTED));
        ui.horizontal(|ui| {
            ui.label("Quality");
            egui::ComboBox::from_id_salt("room_quality")
                .selected_text(&self.scene.quality)
                .show_ui(ui, |ui| {
                    for q in QUALITIES {
                        ui.selectable_value(&mut self.scene.quality, q.to_string(), *q);
                    }
                });
        });
        let problems = self.scene.problems();
        for p in &problems {
            ui.label(RichText::new(format!("• {p}")).small().color(theme::WARN));
        }
        if let Some(r) = &self.running {
            let p = r.job.progress();
            ui.add(egui::ProgressBar::new(p as f32).show_percentage());
            for line in r.job.tail(3) {
                ui.label(RichText::new(line).small().color(theme::FAINT));
            }
            if ui.button("✕ Cancel").clicked() {
                r.job.cancel();
            }
        } else if ui
            .add_enabled(
                problems.is_empty(),
                egui::Button::new(RichText::new("⤓ Render to tracks").strong()),
            )
            .on_hover_text("Records every source in the room through every mic (offline) and adds a track per mic, panned")
            .clicked()
            && let Err(e) = self.start(sv)
        {
            self.error = Some(e);
        }
        if !self.status.is_empty() {
            ui.label(RichText::new(&self.status).small().color(theme::OK));
        }
        if let Some(e) = &self.error {
            ui.label(RichText::new(e).small().color(theme::FAULT));
        }
    }

    // --- Rendering ---------------------------------------------------------------------

    fn start(&mut self, sv: &mut SessionView) -> Result<(), String> {
        self.error = None;
        self.status.clear();
        let session = sv.session();
        let rate = session.rate;
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs());
        let dir = session.dir.join("rooms").join(format!("render_{stamp}"));
        std::fs::create_dir_all(dir.join("sources")).map_err(|e| e.to_string())?;
        // Each source's take, all on one clock: the earliest take's start.
        let mut takes = Vec::new();
        for s in &self.scene.sources {
            let t = session
                .tracks
                .iter()
                .find(|t| t.id == s.track)
                .and_then(|t| t.active_take())
                .ok_or(format!("{}: its track has no take", s.name))?;
            takes.push((s.name.clone(), t.position, t.audio.clone()));
        }
        let start = takes.iter().map(|t| t.1).min().unwrap_or(0);
        let mut clips = BTreeMap::new();
        for (name, pos, audio) in &takes {
            let lead = (pos - start).max(0) as usize;
            let mut x = vec![0.0f64; lead];
            x.extend(audio.iter().map(|&v| v as f64));
            let path = dir.join("sources").join(format!("{}.wav", safe(name)));
            audio::write_wav(&path, &x, rate)?;
            clips.insert(name.clone(), path);
        }
        let scene_json = self.scene.render_json(&clips);
        let scene_path = dir.join("scene.json");
        std::fs::write(
            &scene_path,
            serde_json::to_string_pretty(&scene_json).unwrap(),
        )
        .map_err(|e| e.to_string())?;
        let job = RenderJob::spawn(&self.root, &scene_path, &dir.join("render"))?;
        self.running = Some(Running {
            job,
            position: start,
            rate,
            scene: scene_json,
        });
        self.status = "rendering…".to_string();
        Ok(())
    }

    fn poll(&mut self, sv: &mut SessionView) {
        let Some(r) = &mut self.running else { return };
        let Some(result) = r.job.poll() else { return };
        let r = self.running.take().unwrap();
        match result.and_then(|rendered| {
            let mut tracks = Vec::new();
            for m in &rendered.mics {
                let x = audio::load(&m.file, r.rate)?;
                let from = json!({
                    "take": format!("room {}", self.scene.name),
                    "room": {"scene": r.scene, "mic": m.name, "render": rendered.json},
                });
                tracks.push((
                    format!("{} · {}", self.scene.name, m.name),
                    m.pan,
                    x.iter().map(|&v| v as f32).collect::<Vec<f32>>(),
                    r.position,
                    from,
                ));
            }
            if let Some(rt) = rendered.json["rt60_s"].as_object() {
                let s: Vec<String> = rt
                    .iter()
                    .map(|(k, v)| format!("{k}: {:.2}", v.as_f64().unwrap_or(0.0)))
                    .collect();
                self.rt60 = Some(format!("RT60 (s) {}", s.join("  ")));
            }
            let n = tracks.len();
            sv.add_room_tracks(tracks)?;
            Ok(n)
        }) {
            Ok(n) => self.status = format!("added {n} tracks to the session"),
            Err(e) => {
                self.error = Some(e);
                self.status.clear();
            }
        }
    }

    // --- The plan ----------------------------------------------------------------------

    fn canvas(&mut self, ui: &mut egui::Ui) {
        let (rect, resp) = ui.allocate_exact_size(ui.available_size(), Sense::click_and_drag());
        let (lo, hi) = self.scene.bbox();
        let (w, h) = ((hi[0] - lo[0]).max(1.0), (hi[1] - lo[1]).max(1.0));
        let pad = 48.0;
        let k = ((rect.width() - 2.0 * pad) / w as f32)
            .min((rect.height() - 2.0 * pad) / h as f32)
            .max(1.0);
        let size = Vec2::new(w as f32 * k, h as f32 * k);
        let o = rect.center() - size / 2.0; // the plan's top-left on screen (y = max there)
        let to_s =
            |x: f64, y: f64| Pos2::new(o.x + (x - lo[0]) as f32 * k, o.y + (hi[1] - y) as f32 * k);
        let to_w = |p: Pos2| {
            (
                lo[0] + ((p.x - o.x) / k) as f64,
                hi[1] - ((p.y - o.y) / k) as f64,
            )
        };
        let painter = ui.painter_at(rect);
        let small = egui::FontId::proportional(11.0);

        // the floor: a 1 m grid inside the bounding box, the polygon over it
        let plan: Vec<Pos2> = self.scene.plan.iter().map(|p| to_s(p[0], p[1])).collect();
        for i in (lo[0].ceil() as i32)..=(hi[0].floor() as i32) {
            let x = to_s(i as f64, 0.0).x;
            painter.line_segment(
                [Pos2::new(x, o.y), Pos2::new(x, o.y + size.y)],
                Stroke::new(1.0, theme::DOT),
            );
        }
        for j in (lo[1].ceil() as i32)..=(hi[1].floor() as i32) {
            let y = to_s(0.0, j as f64).y;
            painter.line_segment(
                [Pos2::new(o.x, y), Pos2::new(o.x + size.x, y)],
                Stroke::new(1.0, theme::DOT),
            );
        }
        if plan.len() >= 3 {
            // a fill by triangles from each edge to the centroid works for star-shaped
            // plans; the outline is what reads, so keep the fill faint
            let c = plan.iter().fold(Vec2::ZERO, |a, p| a + p.to_vec2()) / plan.len() as f32;
            let c = c.to_pos2();
            for i in 0..plan.len() {
                let (a, b) = (plan[i], plan[(i + 1) % plan.len()]);
                painter.add(egui::Shape::convex_polygon(
                    vec![c, a, b],
                    theme::CHROME2.gamma_multiply(0.6),
                    Stroke::NONE,
                ));
            }
            let mut closed = plan.clone();
            closed.push(plan[0]);
            painter.add(egui::Shape::line(closed, Stroke::new(2.5, theme::FRAME)));
        }
        // the ceiling: where its facets meet (dashed), heights at the knots
        if self.scene.roof.kind != "flat" {
            let a = self.scene.roof.axis_deg.to_radians();
            let (ux, uy) = (a.cos(), a.sin());
            let (vx, vy) = (-uy, ux);
            let span = (w * w + h * h).sqrt();
            let mid = [0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1])];
            let mid_u = mid[0] * ux + mid[1] * uy;
            for (u, z) in self.scene.profile() {
                let base = [mid[0] + (u - mid_u) * ux, mid[1] + (u - mid_u) * uy];
                let p0 = to_s(base[0] - span * vx, base[1] - span * vy);
                let p1 = to_s(base[0] + span * vx, base[1] + span * vy);
                let peak = (z - self.scene.top()).abs() < 1e-6;
                let col = if peak { theme::WARN } else { theme::WIRE };
                painter.add(egui::Shape::dashed_line(
                    &[p0, p1],
                    Stroke::new(1.0, col.gamma_multiply(0.7)),
                    6.0,
                    5.0,
                ));
                let lab = to_s(base[0], base[1]);
                if rect.contains(lab) {
                    painter.text(
                        lab + Vec2::new(4.0, -8.0),
                        egui::Align2::LEFT_CENTER,
                        format!("{z:.1} m"),
                        small.clone(),
                        col,
                    );
                }
            }
        }
        painter.text(
            Pos2::new(o.x + size.x / 2.0, o.y + size.y + 16.0),
            egui::Align2::CENTER_CENTER,
            format!("{w:.2} m"),
            small.clone(),
            theme::MUTED,
        );
        painter.text(
            Pos2::new(o.x - 24.0, o.y + size.y / 2.0),
            egui::Align2::CENTER_CENTER,
            format!("{h:.2} m"),
            small.clone(),
            theme::MUTED,
        );
        let ceiling = match self.scene.roof.kind.as_str() {
            "flat" => format!("flat ceiling {:.2} m", self.scene.roof.height),
            k => format!(
                "{k} ceiling {:.2} → {:.2} m",
                self.scene.roof.height, self.scene.roof.peak
            ),
        };
        painter.text(
            Pos2::new(o.x + size.x, o.y - 14.0),
            egui::Align2::RIGHT_CENTER,
            format!("{} · {} · seen from above", self.scene.name, ceiling),
            small.clone(),
            theme::FAINT,
        );

        // input: pick, move, aim, corners
        let pointer = resp.interact_pointer_pos().or(resp.hover_pos());
        let marks: Vec<(Sel, Pos2)> = self
            .scene
            .mics
            .iter()
            .enumerate()
            .map(|(i, m)| (Sel::Mic(i), to_s(m.pos[0], m.pos[1])))
            .chain(
                self.scene
                    .sources
                    .iter()
                    .enumerate()
                    .map(|(i, s)| (Sel::Source(i), to_s(s.pos[0], s.pos[1]))),
            )
            .collect();
        let hit = |p: Pos2| -> Option<Sel> {
            marks
                .iter()
                .map(|(s, q)| (*s, q.distance(p)))
                .filter(|(_, dd)| *dd < 14.0)
                .min_by(|a, b| a.1.total_cmp(&b.1))
                .map(|(s, _)| s)
        };
        let corner = |p: Pos2| -> Option<usize> {
            plan.iter()
                .enumerate()
                .map(|(i, q)| (i, q.distance(p)))
                .filter(|(_, dd)| *dd < 9.0)
                .min_by(|a, b| a.1.total_cmp(&b.1))
                .map(|(i, _)| i)
        };
        let shift = ui.input(|i| i.modifiers.shift);
        if resp.drag_started()
            && let Some(p) = pointer
        {
            let h = hit(p);
            let secondary = ui.input(|i| i.pointer.secondary_down());
            self.drag = match (h, corner(p)) {
                (Some(Sel::Mic(i)), _) if secondary || shift => Some(Drag::Aim(i)),
                (Some(s), _) => Some(Drag::Move(s)),
                (None, Some(c)) if !secondary => Some(Drag::Corner(c)),
                (None, _) => match self.sel {
                    Some(Sel::Mic(i)) if secondary || shift => Some(Drag::Aim(i)),
                    _ => None,
                },
            };
            if let Some(s) = h {
                self.sel = Some(s);
            }
        }
        if resp.dragged()
            && let (Some(dr), Some(p)) = (self.drag, pointer)
        {
            let (x, y) = to_w(p);
            let (x, y) = (round_cm(x), round_cm(y));
            let scene = &mut self.scene;
            let ok = |sc: &Scene, z: f64| sc.inside(&[x, y, z]);
            match dr {
                Drag::Move(Sel::Source(i)) => {
                    let z = scene.sources.get(i).map_or(1.0, |s| s.pos[2]);
                    if ok(scene, z)
                        && let Some(s) = scene.sources.get_mut(i)
                    {
                        s.pos[0] = x;
                        s.pos[1] = y;
                    }
                }
                Drag::Move(Sel::Mic(i)) => {
                    let z = scene.mics.get(i).map_or(1.0, |m| m.pos[2]);
                    if ok(scene, z)
                        && let Some(m) = scene.mics.get_mut(i)
                    {
                        m.pos[0] = x;
                        m.pos[1] = y;
                    }
                }
                Drag::Aim(i) => {
                    if let Some(m) = scene.mics.get_mut(i) {
                        m.aim_at(x, y);
                        m.azimuth_deg = m.azimuth_deg.round();
                    }
                }
                Drag::Corner(c) => {
                    if c < scene.plan.len() {
                        // snap to 5 cm
                        scene.plan[c] = [(x * 20.0).round() / 20.0, (y * 20.0).round() / 20.0];
                        scene.shape = "custom".to_string();
                    }
                }
            }
        }
        if resp.drag_stopped() {
            self.drag = None;
        }
        if resp.clicked()
            && let Some(p) = pointer
        {
            self.sel = hit(p);
        }
        // a double-click on a wall adds a corner there; a right-click removes one
        if resp.double_clicked()
            && let Some(p) = pointer
            && hit(p).is_none()
        {
            let n = plan.len();
            let best = (0..n)
                .map(|i| {
                    let (a, b) = (plan[i], plan[(i + 1) % n]);
                    let ab = b - a;
                    let t = ((p - a).dot(ab) / ab.length_sq().max(1e-6)).clamp(0.0, 1.0);
                    (i, (a + ab * t).distance(p))
                })
                .min_by(|a, b| a.1.total_cmp(&b.1));
            if let Some((i, dd)) = best
                && dd < 10.0
            {
                let (x, y) = to_w(p);
                self.scene.plan.insert(i + 1, [round_cm(x), round_cm(y)]);
                self.scene.shape = "custom".to_string();
            }
        }
        if resp.secondary_clicked()
            && let Some(p) = pointer
            && let Some(c) = corner(p)
            && self.scene.plan.len() > 3
            && hit(p).is_none()
        {
            self.scene.plan.remove(c);
            self.scene.shape = "custom".to_string();
        }
        if resp.hovered()
            && ui.input(|i| i.key_pressed(egui::Key::Delete))
            && !ui.ctx().egui_wants_keyboard_input()
        {
            match self.sel.take() {
                Some(Sel::Source(i)) if i < self.scene.sources.len() => {
                    self.scene.sources.remove(i);
                }
                Some(Sel::Mic(i)) if i < self.scene.mics.len() => {
                    self.scene.mics.remove(i);
                }
                _ => {}
            }
        }
        // corner handles
        let near = pointer.and_then(corner);
        for (i, q) in plan.iter().enumerate() {
            let on = near == Some(i) || matches!(self.drag, Some(Drag::Corner(c)) if c == i);
            let r = if on { 5.0 } else { 3.5 };
            painter.rect_filled(
                Rect::from_center_size(*q, Vec2::splat(2.0 * r)),
                1.0,
                if on {
                    theme::INK
                } else {
                    theme::FRAME.gamma_multiply(1.6)
                },
            );
        }
        if let Some(p) = resp.hover_pos()
            && in_room_plan(&self.scene, to_w(p))
        {
            let (x, y) = to_w(p);
            painter.text(
                Pos2::new(o.x, o.y - 14.0),
                egui::Align2::LEFT_CENTER,
                format!(
                    "x {x:.2}  y {y:.2} m · ceiling {:.2} m",
                    self.scene.height_at(x, y)
                ),
                small.clone(),
                theme::FAINT,
            );
        }

        // sources, then mics with their patterns
        let font = egui::FontId::proportional(12.0);
        for (i, s) in self.scene.sources.iter().enumerate() {
            let c = to_s(s.pos[0], s.pos[1]);
            let on = self.sel == Some(Sel::Source(i));
            painter.circle_filled(c, 9.0, SOURCE_COLOR);
            if on {
                painter.circle_stroke(c, 13.0, Stroke::new(2.0, theme::INK));
            }
            painter.text(
                c + Vec2::new(14.0, -10.0),
                egui::Align2::LEFT_CENTER,
                format!("{}  {:.0} dB", s.name, s.spl_db),
                font.clone(),
                SOURCE_COLOR,
            );
        }
        for (i, m) in self.scene.mics.iter().enumerate() {
            let c = to_s(m.pos[0], m.pos[1]);
            let on = self.sel == Some(Sel::Mic(i));
            let az = (m.azimuth_deg as f32).to_radians();
            let r0 = 0.6 * k.clamp(40.0, 90.0);
            let pts: Vec<Pos2> = (0..=72)
                .map(|j| {
                    let th = j as f32 / 72.0 * std::f32::consts::TAU;
                    let g = match m.pattern() {
                        Pattern::Cardioid => 0.5 * (1.0 + th.cos()),
                        Pattern::Omni => 0.55,
                    };
                    let a = az + th;
                    c + Vec2::new(a.cos(), -a.sin()) * (g * r0)
                })
                .collect();
            let col = if on {
                MIC_COLOR
            } else {
                MIC_COLOR.gamma_multiply(0.55)
            };
            painter.add(egui::Shape::convex_polygon(
                pts.clone(),
                MIC_COLOR.gamma_multiply(0.08),
                Stroke::NONE,
            ));
            painter.add(egui::Shape::line(pts, Stroke::new(1.5, col)));
            let tip = c + Vec2::new(az.cos(), -az.sin()) * 16.0;
            painter.line_segment([c, tip], Stroke::new(2.5, col));
            painter.circle_filled(c, 6.0, col);
            if on {
                painter.circle_stroke(c, 10.0, Stroke::new(2.0, theme::INK));
            }
            painter.text(
                c + Vec2::new(10.0, 12.0),
                egui::Align2::LEFT_CENTER,
                &m.name,
                font.clone(),
                col,
            );
        }
        if self.scene.sources.is_empty() && self.scene.mics.is_empty() {
            painter.text(
                rect.center(),
                egui::Align2::CENTER_CENTER,
                "Add sources (session tracks) and mics at the left",
                egui::FontId::proportional(15.0),
                theme::FAINT,
            );
        }
    }
}

/// The room's bounds for the position fields: (low, high) per axis.
fn bounds(scene: &Scene) -> [(f64, f64); 3] {
    let (lo, hi) = scene.bbox();
    [(lo[0], hi[0]), (lo[1], hi[1]), (0.0, scene.top())]
}

fn centroid(scene: &Scene) -> [f64; 3] {
    let n = scene.plan.len().max(1) as f64;
    let x = scene.plan.iter().map(|p| p[0]).sum::<f64>() / n;
    let y = scene.plan.iter().map(|p| p[1]).sum::<f64>() / n;
    [x, y, 1.3f64.min(0.5 * scene.roof.height)]
}

fn position_fields(ui: &mut egui::Ui, pos: &mut [f64; 3], dims: [(f64, f64); 3]) {
    ui.horizontal(|ui| {
        for (j, l) in ["x", "y", "z"].iter().enumerate() {
            ui.label(*l);
            ui.add(
                egui::DragValue::new(&mut pos[j])
                    .range((dims[j].0 + 0.05)..=(dims[j].1 - 0.05).max(dims[j].0 + 0.06))
                    .speed(0.01)
                    .suffix(" m")
                    .max_decimals(2),
            );
        }
    });
}

fn dist(a: &[f64; 3], b: &[f64; 3]) -> f64 {
    (0..3).map(|i| (a[i] - b[i]).powi(2)).sum::<f64>().sqrt()
}

/// The angle between a mic's axis and the direction to `p`.
fn off_axis_deg(m: &RoomMic, p: &[f64; 3]) -> f64 {
    let (az, el) = (m.azimuth_deg.to_radians(), m.elevation_deg.to_radians());
    let aim = [el.cos() * az.cos(), el.cos() * az.sin(), el.sin()];
    let v = [p[0] - m.pos[0], p[1] - m.pos[1], p[2] - m.pos[2]];
    let n = dist(p, &m.pos).max(1e-9);
    let c = (aim[0] * v[0] + aim[1] * v[1] + aim[2] * v[2]) / n;
    c.clamp(-1.0, 1.0).acos().to_degrees()
}

fn in_room_plan(scene: &Scene, (x, y): (f64, f64)) -> bool {
    room::in_polygon(&scene.plan, x, y)
}

fn round_cm(x: f64) -> f64 {
    (x * 100.0).round() / 100.0
}

fn safe(name: &str) -> String {
    let s: String = name
        .chars()
        .map(|c| {
            if c.is_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect();
    if s.is_empty() { "source".into() } else { s }
}

fn unique(scene: &Scene, base: &str) -> String {
    let taken = |n: &str| {
        scene.sources.iter().any(|s| s.name == n) || scene.mics.iter().any(|m| m.name == n)
    };
    if !taken(base) {
        return base.to_string();
    }
    (2..)
        .map(|i| format!("{base} {i}"))
        .find(|n| !taken(n))
        .unwrap()
}
