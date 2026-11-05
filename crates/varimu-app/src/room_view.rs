//! The Room view (docs/ROOM_LOOP_PLAN.md): a shoebox room drawn to scale from above,
//! sources (session tracks) and mics placed in it by dragging, each mic aimed (drag with
//! the right button or Shift, or "Aim at") and drawn with its pattern, its chain and
//! settings chosen at the side; Render records every source through every mic
//! (`varimu_app::room`'s background process) and adds a session track per mic, panned.
//! The scene is kept per session in `<session>/rooms/scene.json`.

use std::collections::BTreeMap;
use std::path::PathBuf;

use eframe::egui::{self, Color32, Pos2, Rect, RichText, Sense, Stroke, StrokeKind, Vec2};
use serde_json::{Value, json};
use varimu_app::audio;
use varimu_app::room::{
    self, CHAINS, MATERIALS, Pattern, QUALITIES, RenderJob, RoomMic, RoomSource, Scene,
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
            for (i, l) in ["W", "D", "H"].iter().enumerate() {
                ui.label(*l);
                ui.add(
                    egui::DragValue::new(&mut self.scene.dims[i])
                        .range(1.0..=60.0)
                        .speed(0.05)
                        .suffix(" m")
                        .max_decimals(2),
                );
            }
        });
        for (label, which) in [("Walls", 0), ("Floor", 1), ("Ceiling", 2)] {
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
                let d = self.scene.dims;
                self.scene.sources.push(RoomSource {
                    name: unique(&self.scene, &name),
                    track: id,
                    spl_db: 90.0,
                    pos: [
                        (d[0] * (0.3 + 0.2 * n)).min(d[0] - 0.5),
                        d[1] * 0.45,
                        1.3f64.min(d[2] - 0.2),
                    ],
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
                let d = self.scene.dims;
                let name = self.scene.free_name("Mic");
                let mut m = RoomMic::new(
                    &name,
                    CHAINS[self.add_chain].id,
                    [d[0] * 0.5, d[1] * 0.8, 1.5f64.min(d[2] - 0.2)],
                    -90.0,
                );
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
        let dims = self.scene.dims;
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
        let dims = self.scene.dims;
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
        let d = self.scene.dims;
        let pad = 40.0;
        let k = ((rect.width() - 2.0 * pad) / d[0] as f32)
            .min((rect.height() - 2.0 * pad) / d[1] as f32)
            .max(1.0);
        let size = Vec2::new(d[0] as f32 * k, d[1] as f32 * k);
        let o = rect.center() - size / 2.0; // the room's top-left on screen (y = D there)
        let to_s = |x: f64, y: f64| Pos2::new(o.x + x as f32 * k, o.y + (d[1] - y) as f32 * k);
        let to_w = |p: Pos2| (((p.x - o.x) / k) as f64, d[1] - ((p.y - o.y) / k) as f64);
        let painter = ui.painter_at(rect);

        // the room, a 1 m grid
        let room_rect = Rect::from_min_size(o, size);
        painter.rect_filled(room_rect, 2.0, theme::CHROME2);
        for i in 1..(d[0].ceil() as i32) {
            let x = o.x + i as f32 * k;
            painter.line_segment(
                [Pos2::new(x, o.y), Pos2::new(x, o.y + size.y)],
                Stroke::new(1.0, theme::DOT),
            );
        }
        for j in 1..(d[1].ceil() as i32) {
            let y = o.y + size.y - j as f32 * k;
            painter.line_segment(
                [Pos2::new(o.x, y), Pos2::new(o.x + size.x, y)],
                Stroke::new(1.0, theme::DOT),
            );
        }
        painter.rect_stroke(
            room_rect,
            2.0,
            Stroke::new(2.0, theme::FRAME),
            StrokeKind::Inside,
        );
        let small = egui::FontId::proportional(11.0);
        painter.text(
            Pos2::new(o.x + size.x / 2.0, o.y + size.y + 14.0),
            egui::Align2::CENTER_CENTER,
            format!("{:.2} m", d[0]),
            small.clone(),
            theme::MUTED,
        );
        painter.text(
            Pos2::new(o.x - 22.0, o.y + size.y / 2.0),
            egui::Align2::CENTER_CENTER,
            format!("{:.2} m", d[1]),
            small.clone(),
            theme::MUTED,
        );
        painter.text(
            Pos2::new(o.x + size.x, o.y - 12.0),
            egui::Align2::RIGHT_CENTER,
            format!(
                "{} · height {:.2} m · seen from above",
                self.scene.name, d[2]
            ),
            small.clone(),
            theme::FAINT,
        );

        // input: pick, move, aim
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
        let shift = ui.input(|i| i.modifiers.shift);
        if resp.drag_started()
            && let Some(p) = pointer
        {
            let h = hit(p);
            let secondary = ui.input(|i| i.pointer.secondary_down());
            self.drag = match h {
                Some(Sel::Mic(i)) if secondary || shift => Some(Drag::Aim(i)),
                Some(s) => Some(Drag::Move(s)),
                None => match self.sel {
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
            let cx = x.clamp(0.05, d[0] - 0.05);
            let cy = y.clamp(0.05, d[1] - 0.05);
            match dr {
                Drag::Move(Sel::Source(i)) => {
                    if let Some(s) = self.scene.sources.get_mut(i) {
                        s.pos[0] = round_cm(cx);
                        s.pos[1] = round_cm(cy);
                    }
                }
                Drag::Move(Sel::Mic(i)) => {
                    if let Some(m) = self.scene.mics.get_mut(i) {
                        m.pos[0] = round_cm(cx);
                        m.pos[1] = round_cm(cy);
                    }
                }
                Drag::Aim(i) => {
                    if let Some(m) = self.scene.mics.get_mut(i) {
                        m.aim_at(x, y);
                        m.azimuth_deg = m.azimuth_deg.round();
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
        if let Some(p) = resp.hover_pos()
            && room_rect.contains(p)
        {
            let (x, y) = to_w(p);
            painter.text(
                Pos2::new(o.x, o.y - 12.0),
                egui::Align2::LEFT_CENTER,
                format!("x {x:.2}  y {y:.2} m"),
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
            let chain = room::chain(&m.chain).map_or("", |ch| ch.label);
            painter.text(
                c + Vec2::new(10.0, 12.0),
                egui::Align2::LEFT_CENTER,
                format!("{} · {}", m.name, chain),
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

fn position_fields(ui: &mut egui::Ui, pos: &mut [f64; 3], dims: [f64; 3]) {
    ui.horizontal(|ui| {
        for (j, l) in ["x", "y", "z"].iter().enumerate() {
            ui.label(*l);
            ui.add(
                egui::DragValue::new(&mut pos[j])
                    .range(0.05..=(dims[j] - 0.05).max(0.06))
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
