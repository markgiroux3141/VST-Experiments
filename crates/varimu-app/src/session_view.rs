//! The Session view (docs/RECORDING_PLAN.md): an arrangement of tracks, as a DAW's, much
//! simpler. The transport bar (record, play, stop, the position as heard, tempo, meter,
//! click, count-in, pre-roll), a bar ruler (click it to move the start bar), and the
//! tracks stacked vertically: each a channel strip (arm, mute, solo, fader, balance, its
//! takes) and a lane with its active take's waveform. The take being recorded draws as it
//! grows. Below, the latency and the loopback calibration (T1).
//!
//! The device playing live is the Play view's choice (device and source): the armed track
//! records it and plays it through its strip. A session is a folder (`crate::session` on
//! disk), new ones in the repo's `sessions/` (git-ignored: performances are never
//! committed); Save as… copies the whole folder to a new one. The last session, the default
//! transport and the calibrations are the user's prefs (`%APPDATA%\varimu\recording.json`,
//! apart from `app.json`).
//!
//! **Undo.** Every change to the session is a step: takes recorded (a loop's passes
//! together), moved, deleted, switched; tracks added or deleted; names, faders, balance,
//! mute, solo; tempo, meter, click, locators. A step is kept when a gesture ends (the mouse
//! released, a text field left, a recording stopped). Ctrl+Z undoes, Ctrl+Y or
//! Ctrl+Shift+Z redoes; the history is saved with the session (`history.json`), so it
//! survives a restart. Selecting a track and showing its takes aren't steps.
//!
//! Mouse: a click on a track (its strip or lane) selects it: the selected track is the armed
//! one, which records. A click on a take selects it, a drag moves it (by whole beats; Alt:
//! freely), right-click deletes a take or a track. Deleted takes leave the session but
//! their files stay in its folder. Ctrl+Z undoes moves and deletions.
//!
//! The ruler: a click moves the start bar, Ctrl+click puts the left locator there,
//! Alt+click the right one; a drag draws the loop between them (and turns it on), a drag on
//! a locator's handle moves it. With the loop on, play (and recording) repeats from the
//! left locator to the right one, each recorded pass a new take in the lane. Below the
//! lanes a scrollbar scrolls in time; −, + and Fit zoom.
//!
//! Keys: Space plays / stops, R records, / turns the loop on or off, G and H zoom out and
//! in, Delete deletes the selected take, Ctrl+Z / Ctrl+Y undo and redo, Ctrl+S saves
//! (while no text field has focus).
//! Over the lanes, Shift+wheel scrolls in time, Ctrl+wheel zooms.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::mpsc::{self, Receiver};
use std::time::Duration;

use eframe::egui::{self, Color32, Pos2, Rect, RichText, Sense, Stroke, StrokeKind};
use serde_json::{Value, json};
use varimu_app::loopback::{self, Analysis, Calibration, Run};
use varimu_app::player::{BLOCK, InputDevice, State, input_devices};
use varimu_app::session::{
    OVERVIEW_BIN, Overview, Session, Take, Track, transport_from, transport_json,
};
use varimu_app::transport::{ClickMode, Grid, Phase, TransportSettings};

use crate::play_view::PlayView;
use crate::theme;

/// How long a calibration plays the click (s).
const CALIBRATE_S: f64 = 8.0;
/// The channel strips' width and a track's height (px).
const STRIP_W: f32 = 250.0;
const TRACK_H: f32 = 78.0;
const RULER_H: f32 = 26.0;
/// A take's row when a track shows every take (px).
const TAKE_H: f32 = 34.0;
/// The rate a session starts at before a device has played (the app's devices' host rate).
const DEFAULT_RATE: u32 = 48_000;
const REC: Color32 = Color32::from_rgb(0xe0, 0x4a, 0x4a);
/// Track colours, in turn.
const COLOURS: [Color32; 6] = [
    Color32::from_rgb(0x4f, 0x9d, 0xd8),
    Color32::from_rgb(0xd8, 0x9a, 0x3f),
    Color32::from_rgb(0x5f, 0xc0, 0x86),
    Color32::from_rgb(0xb0, 0x7c, 0xd8),
    Color32::from_rgb(0xd8, 0x6a, 0x8a),
    Color32::from_rgb(0x4f, 0xc4, 0xc4),
];

enum Calibrate {
    Idle,
    /// Capturing: the run, the input's label and where position 0 left the app.
    Running {
        run: Box<Run>,
        input: String,
        output: String,
        origin: Option<i64>,
    },
    Analysing {
        rx: Receiver<Result<Analysis, String>>,
        input: String,
        output: String,
    },
}

/// The take being recorded, as the view draws it.
struct Recording {
    start: i64,
    latency: i64,
    len: usize,
    overview: Overview,
}

/// A take being dragged: its track and index, where it was, where the drag started (px).
struct Drag {
    track: usize,
    take: usize,
    from: i64,
    press_x: f32,
}

/// A drag on the ruler: a locator's handle, or a new loop from a beat.
#[derive(Clone, Copy)]
enum RulerDrag {
    Left,
    Right,
    New(i64),
}

pub struct SessionView {
    session: Session,
    ruler_drag: Option<RulerDrag>,
    /// The lanes' width as last drawn (px): G and H zoom about its middle.
    lanes_w: f64,
    /// A drag on the scrollbar's thumb: where it started (px) and the view then (s).
    scroll_drag: Option<(f32, f64)>,
    /// The selected take (track, index), a drag in progress, the right-clicked take.
    selected: Option<(usize, usize)>,
    drag: Option<Drag>,
    /// The session's states before each step (oldest first) and the ones undone; the
    /// state the last step left (what the next change is compared with).
    undo: Vec<Value>,
    redo: Vec<Value>,
    committed: Value,
    /// The repo: sessions go in its `sessions/`.
    root: PathBuf,
    /// Save as…: the new session's name, while it is being typed.
    save_as: Option<String>,
    /// Whether the session's folder has been written (a new one isn't, until a take).
    saved: bool,
    calibrations: Vec<Calibration>,
    recording: Option<Recording>,
    /// The timeline's left edge (s from bar 1) and zoom (px per s).
    view_s: f64,
    px_per_s: f64,
    show_latency: bool,
    inputs: Vec<InputDevice>,
    /// 0: the output's own mix (WASAPI loopback); i + 1: `inputs[i]`.
    cal_source: usize,
    cal_channel: usize,
    calibrate: Calibrate,
    last: Option<(String, Analysis)>,
    error: Option<String>,
}

fn prefs_path() -> Option<PathBuf> {
    varimu_app::prefs::path().map(|p| p.with_file_name("recording.json"))
}

/// Where sessions go: the repo's `sessions/` (git-ignored).
fn sessions_root(repo: &Path) -> PathBuf {
    repo.join("sessions")
}

/// The first "Session N" folder that doesn't exist yet.
fn new_session_dir(repo: &Path) -> PathBuf {
    let root = sessions_root(repo);
    (1..)
        .map(|n| root.join(format!("Session {n}")))
        .find(|d| !d.exists())
        .expect("a free name")
}

/// A folder name from what the user typed: no path separators or characters Windows
/// refuses.
fn folder_name(s: &str) -> String {
    let t: String = s
        .chars()
        .map(|c| {
            if "<>:\"/\\|?*".contains(c) || c.is_control() {
                '_'
            } else {
                c
            }
        })
        .collect();
    t.trim().trim_end_matches('.').to_string()
}

/// A state as undo compares it: without what isn't a step (the armed track, takes shown).
fn step_key(v: &Value) -> Value {
    let mut v = v.clone();
    v["armed"] = Value::Null;
    if let Some(tracks) = v["tracks"].as_array_mut() {
        for t in tracks {
            t["show_takes"] = Value::Null;
        }
    }
    v
}

impl SessionView {
    pub fn new(repo: &Path) -> SessionView {
        let (last, transport, calibrations) = load_prefs();
        let (session, saved, error) = match last.as_deref().map(Session::load) {
            Some(Ok(s)) => (s, true, None),
            r => {
                let e = match r {
                    Some(Err(e)) => Some(format!("couldn't open the last session: {e}")),
                    _ => None,
                };
                (
                    Session::new(new_session_dir(repo), DEFAULT_RATE, transport),
                    false,
                    e,
                )
            }
        };
        let undo = if saved {
            session.load_history()
        } else {
            Vec::new()
        };
        let committed = session.state();
        SessionView {
            session,
            undo,
            redo: Vec::new(),
            committed,
            root: repo.to_path_buf(),
            save_as: None,
            ruler_drag: None,
            lanes_w: 800.0,
            scroll_drag: None,
            selected: None,
            drag: None,
            saved,
            calibrations,
            recording: None,
            view_s: -0.5,
            px_per_s: 40.0,
            show_latency: false,
            inputs: Vec::new(),
            cal_source: 0,
            cal_channel: 0,
            calibrate: Calibrate::Idle,
            last: None,
            error,
        }
    }

    fn save_prefs(&mut self) {
        let Some(p) = prefs_path() else { return };
        let cals: Vec<Value> = self
            .calibrations
            .iter()
            .map(|c| {
                json!({
                    "output": c.output,
                    "input": c.input,
                    "round_trip_s": c.round_trip_s,
                    "cpal_round_trip_s": c.cpal_round_trip_s,
                })
            })
            .collect();
        let v = json!({
            "last_session": self.saved.then(|| self.session.dir.display().to_string()),
            "transport": transport_json(&self.session.transport),
            "calibrations": cals,
        });
        let r = p
            .parent()
            .map_or(Ok(()), std::fs::create_dir_all)
            .and_then(|_| {
                std::fs::write(
                    &p,
                    serde_json::to_string_pretty(&v).unwrap_or_default() + "\n",
                )
            });
        if let Err(e) = r {
            self.error = Some(format!("{}: {e}", p.display()));
        }
    }

    /// Save the session (once it has a folder) and the prefs.
    fn save(&mut self) {
        if self.saved
            && let Err(e) = self.session.save()
        {
            self.error = Some(e);
        }
        self.save_prefs();
    }

    pub fn ui(&mut self, ui: &mut egui::Ui, play: &mut PlayView) {
        play.tick(ui.ctx());
        play.live_controls();
        self.poll_calibration(play);
        let idle = matches!(self.calibrate, Calibrate::Idle);
        if idle {
            play.apply_monitor();
            if let Some(p) = play.player() {
                p.set_transport(&self.session.transport);
                p.set_mix(Arc::new(self.session.mix()));
            }
        }
        self.poll_recording(play);
        self.keys(ui, play);
        egui::Panel::top("session_transport")
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(14, 10)),
            )
            .show(ui, |ui| {
                self.transport_ui(ui, play);
                ui.add_space(6.0);
                self.settings_ui(ui);
            });
        egui::Panel::bottom("session_latency")
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(14, 8)),
            )
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    let arrow = if self.show_latency { "▾" } else { "▸" };
                    if ui
                        .add(
                            egui::Button::new(format!("{arrow} Latency & calibration"))
                                .frame(false),
                        )
                        .clicked()
                    {
                        self.show_latency = !self.show_latency;
                    }
                    self.session_line(ui);
                });
                if self.show_latency {
                    ui.add_space(6.0);
                    self.latency_ui(ui, play);
                    ui.add_space(10.0);
                    self.calibrate_ui(ui, play);
                }
                if let Some(e) = &self.error {
                    ui.colored_label(theme::FAULT, e);
                }
            });
        egui::CentralPanel::default()
            .frame(egui::Frame::NONE.fill(theme::CANVAS))
            .show(ui, |ui| self.arrangement(ui, play));
        let armed = play.player().is_some_and(|p| p.take_armed());
        self.commit(ui.ctx(), armed);
        if play.player().is_some() || !idle {
            ui.ctx().request_repaint_after(Duration::from_millis(33));
        }
    }

    /// Space plays / stops, R records.
    fn keys(&mut self, ui: &egui::Ui, play: &mut PlayView) {
        if ui.ctx().egui_wants_keyboard_input() {
            return;
        }
        let (space, r, delete, undo) = ui.input(|i| {
            (
                i.key_pressed(egui::Key::Space),
                i.key_pressed(egui::Key::R) && !i.modifiers.command,
                i.key_pressed(egui::Key::Delete) || i.key_pressed(egui::Key::Backspace),
                i.key_pressed(egui::Key::Z) && i.modifiers.command && !i.modifiers.shift,
            )
        });
        let (redo, save) = ui.input(|i| {
            (
                i.modifiers.command
                    && (i.key_pressed(egui::Key::Y)
                        || (i.key_pressed(egui::Key::Z) && i.modifiers.shift)),
                i.modifiers.command && i.key_pressed(egui::Key::S),
            )
        });
        if redo {
            self.redo();
        }
        if save {
            self.save_now();
        }
        let (slash, zoom_out, zoom_in) = ui.input(|i| {
            (
                i.key_pressed(egui::Key::Slash),
                i.key_pressed(egui::Key::G),
                i.key_pressed(egui::Key::H),
            )
        });
        if slash {
            self.session.transport.loop_on = !self.session.transport.loop_on;
            self.save();
        }
        if zoom_out {
            self.zoom(0.5, Some(self.lanes_w * 0.5));
        }
        if zoom_in {
            self.zoom(2.0, Some(self.lanes_w * 0.5));
        }
        if delete && let Some((t, k)) = self.selected {
            self.delete_take(t, k);
        }
        if undo {
            self.undo();
        }
        let running = play.player().is_some_and(|p| p.status().transport.running);
        if space {
            if running {
                self.stop(play);
            } else {
                self.play(play, false);
            }
        }
        if r && !running {
            self.play(play, true);
        }
    }

    fn play(&mut self, play: &mut PlayView, record: bool) {
        let Some(p) = play.player() else {
            play.start_device();
            return;
        };
        if p.status().state != State::Playing || !matches!(self.calibrate, Calibrate::Idle) {
            return;
        }
        if record {
            let has_takes = self.session.tracks.iter().any(|t| !t.takes.is_empty());
            if has_takes && p.rate != self.session.rate {
                self.error = Some(format!(
                    "this device plays at {} Hz, the session is at {} Hz",
                    p.rate, self.session.rate
                ));
                return;
            }
            self.session.rate = p.rate;
            if self.session.tracks.is_empty() {
                self.add_track();
            }
            if self.session.armed.is_none() {
                self.session.armed = Some(0);
            }
        }
        p.arm_take(record);
        p.transport_run(true);
        self.error = None;
    }

    fn stop(&mut self, play: &PlayView) {
        if let Some(p) = play.player() {
            p.arm_take(false);
            p.transport_run(false);
        }
    }

    /// A new track, selected (armed) for the next take.
    fn add_track(&mut self) {
        let n = self.session.tracks.len() + 1;
        self.session.tracks.push(Track::new(&format!("Track {n}")));
        self.session.armed = Some(n - 1);
        self.save();
    }

    /// A step for undo, if the session changed since the last one and no gesture is in
    /// progress (a mouse button down, a text field being typed in, a recording).
    fn commit(&mut self, ctx: &egui::Context, recording: bool) {
        let busy = recording
            || self.recording.is_some()
            || self.drag.is_some()
            || self.ruler_drag.is_some()
            || ctx.input(|i| i.pointer.any_down())
            || ctx.egui_wants_keyboard_input();
        if busy {
            return;
        }
        let now = self.session.state();
        if now == self.committed {
            return;
        }
        if step_key(&now) != step_key(&self.committed) {
            let before = std::mem::replace(&mut self.committed, now);
            self.undo.push(before);
            if self.undo.len() > 200 {
                self.undo.remove(0);
            }
            self.redo.clear();
            self.save_history();
        } else {
            self.committed = now;
        }
    }

    fn save_history(&mut self) {
        if self.saved
            && let Err(e) = self.session.save_history(&self.undo)
        {
            self.error = Some(e);
        }
    }

    /// Back one step (Ctrl+Z).
    fn undo(&mut self) {
        if self.recording.is_some() {
            return;
        }
        if let Some(prev) = self.undo.pop() {
            self.redo.push(self.session.state());
            self.go_to(prev);
        }
    }

    /// Forward one step undone (Ctrl+Y).
    fn redo(&mut self) {
        if self.recording.is_some() {
            return;
        }
        if let Some(next) = self.redo.pop() {
            self.undo.push(self.session.state());
            self.go_to(next);
        }
    }

    fn go_to(&mut self, state: Value) {
        match self.session.restore(&state) {
            Ok(()) => {
                self.committed = state;
                self.selected = None;
                self.drag = None;
                self.save();
                self.save_history();
            }
            Err(e) => self.error = Some(e),
        }
    }

    /// Write the session now (Ctrl+S), a new one's folder too.
    fn save_now(&mut self) {
        self.saved = true;
        self.save();
        self.save_history();
    }

    /// The session copied to `sessions/<name>` and carried on there; the old folder stays
    /// as it was.
    fn save_as(&mut self, name: &str) {
        let name = folder_name(name);
        if name.is_empty() {
            self.error = Some("a session needs a name".into());
            return;
        }
        let dir = sessions_root(&self.root).join(&name);
        match self.session.copy_to(&dir) {
            Ok(copy) => {
                self.session = copy;
                self.saved = true;
                self.save_history();
                self.save_prefs();
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }

    /// Another session in place of this one (its history with it).
    fn switch_to(&mut self, session: Session, saved: bool) {
        self.session = session;
        self.saved = saved;
        self.undo = if saved {
            self.session.load_history()
        } else {
            Vec::new()
        };
        self.redo.clear();
        self.committed = self.session.state();
        self.selected = None;
        self.drag = None;
        self.recording = None;
        self.save_prefs();
    }

    /// Take `k` out of track `t` (its files stay in the session's folder).
    fn delete_take(&mut self, t: usize, k: usize) {
        if self.recording.is_some()
            || self
                .session
                .tracks
                .get(t)
                .is_none_or(|x| k >= x.takes.len())
        {
            return;
        }
        let track = &mut self.session.tracks[t];
        track.takes.remove(k);
        track.active = match track.active {
            _ if track.takes.is_empty() => None,
            Some(a) if a == k => Some(track.takes.len() - 1),
            Some(a) if a > k => Some(a - 1),
            a => a,
        };
        self.selected = None;
        self.save();
    }

    /// Track `t` out of the session (its takes' files stay in the folder).
    fn delete_track(&mut self, t: usize) {
        if self.recording.is_some() || t >= self.session.tracks.len() {
            return;
        }
        self.session.tracks.remove(t);
        let n = self.session.tracks.len();
        self.session.armed = match self.session.armed {
            _ if n == 0 => None,
            Some(a) if a == t => Some(t.min(n - 1)),
            Some(a) if a > t => Some(a - 1),
            a => a,
        };
        self.selected = None;
        self.save();
    }

    /// The take being recorded: its waveform as it grows; a finished one into the armed
    /// track.
    fn poll_recording(&mut self, play: &PlayView) {
        let Some(p) = play.player() else {
            self.recording = None;
            return;
        };
        let from = self.recording.as_ref().map_or(0, |r| r.len);
        match p.take_tail(from) {
            Some((start, latency, len, tail)) => {
                let r = self.recording.get_or_insert_with(|| Recording {
                    start,
                    latency,
                    len: 0,
                    overview: Overview::new(OVERVIEW_BIN),
                });
                r.overview.extend(&tail);
                r.len = len;
            }
            None => self.recording = None,
        }
        // A new pass of a loop started: its waveform from the beginning.
        if let Some(r) = &self.recording
            && let Some((start, _, len, _)) = p.take_tail(usize::MAX)
            && (start != r.start || len < r.len)
        {
            self.recording = None;
        }
        // Every finished take (a loop's passes: one each) into the armed track.
        while let Some(rec) = p.finished_take() {
            if rec.samples.is_empty() {
                continue;
            }
            let track = self.session.armed.unwrap_or(0);
            let (_, device) = play.device_label_id();
            self.saved = true;
            match self.session.add_take(track, rec, &device) {
                Ok(()) => self.save_prefs(),
                Err(e) => self.error = Some(e),
            }
        }
    }

    fn transport_ui(&mut self, ui: &mut egui::Ui, play: &mut PlayView) {
        let Some(p) = play.player() else {
            ui.horizontal(|ui| {
                let go = egui::Button::new(
                    RichText::new("▶  Start the device")
                        .strong()
                        .color(theme::ACCENT_INK),
                )
                .fill(theme::ACCENT)
                .min_size(egui::vec2(160.0, 30.0));
                if ui
                    .add(go)
                    .on_hover_text("Start what Play has chosen (device and source): the armed track records it")
                    .clicked()
                {
                    play.start_device();
                }
                ui.label(RichText::new(play.listen_line()).color(theme::MUTED));
            });
            return;
        };
        let st = p.status();
        let t = &st.transport;
        let recording = p.take_armed();
        let busy = !matches!(self.calibrate, Calibrate::Idle);
        let ready = st.state == State::Playing && !busy;
        let mut action: Option<Option<bool>> = None; // Some(None): stop; Some(Some(rec)): play
        ui.horizontal(|ui| {
            let rec_button = egui::Button::new(RichText::new("●").size(18.0).color(if recording {
                Color32::WHITE
            } else {
                REC
            }))
            .fill(if recording { REC } else { theme::CHROME3 })
            .min_size(egui::vec2(40.0, 30.0));
            if ui
                .add_enabled(ready, rec_button)
                .on_hover_text(
                    "Record into the armed track (R): the count-in, then from the start bar",
                )
                .clicked()
            {
                action = Some(if recording && t.running {
                    None
                } else {
                    Some(true)
                });
            }
            if t.running {
                if ui
                    .add_enabled(
                        !busy,
                        egui::Button::new("■").min_size(egui::vec2(40.0, 30.0)),
                    )
                    .on_hover_text("Stop (Space)")
                    .clicked()
                {
                    action = Some(None);
                }
            } else {
                let go = egui::Button::new(RichText::new("▶").color(theme::ACCENT_INK))
                    .fill(theme::ACCENT)
                    .min_size(egui::vec2(40.0, 30.0));
                if ui
                    .add_enabled(ready, go)
                    .on_hover_text("Play from the start bar (Space)")
                    .clicked()
                {
                    action = Some(Some(false));
                }
            }
            ui.add_space(12.0);
            let label = t.grid.map_or("---.-.-".into(), |g| g.label(t.heard));
            ui.label(
                RichText::new(label)
                    .monospace()
                    .size(24.0)
                    .color(theme::INK),
            );
            ui.add_space(8.0);
            let (badge, colour) = match (t.phase, recording) {
                (Some(Phase::CountIn), _) => ("COUNT-IN", theme::WARN),
                (Some(Phase::PreRoll), _) => ("PRE-ROLL", theme::WARN),
                (Some(Phase::Rolling), true) => ("RECORDING", REC),
                (Some(Phase::Rolling), false) => ("PLAYING", theme::OK),
                (None, _) => ("STOPPED", theme::FAINT),
            };
            ui.label(RichText::new(badge).strong().color(colour));
            ui.add_space(12.0);
            ui.label(
                RichText::new(format!(
                    "{} · load {:.0}% · {} dropouts",
                    play.device_label_id().0,
                    st.load * 100.0,
                    p.dropouts()
                ))
                .small()
                .color(theme::MUTED),
            );
        });
        match action {
            Some(None) => self.stop(play),
            Some(Some(rec)) => self.play(play, rec),
            None => {}
        }
    }

    fn settings_ui(&mut self, ui: &mut egui::Ui) {
        let before = self.session.transport.clone();
        let s = &mut self.session.transport;
        ui.horizontal_wrapped(|ui| {
            ui.add(
                egui::DragValue::new(&mut s.bpm)
                    .range(20.0..=400.0)
                    .speed(0.25)
                    .max_decimals(2)
                    .suffix(" bpm"),
            );
            ui.add_space(8.0);
            ui.add(egui::DragValue::new(&mut s.beats_per_bar).range(1..=16));
            ui.label("/");
            egui::ComboBox::from_id_salt("beat_unit")
                .width(44.0)
                .selected_text(s.beat_unit.to_string())
                .show_ui(ui, |ui| {
                    for u in [2, 4, 8, 16] {
                        ui.selectable_value(&mut s.beat_unit, u, u.to_string());
                    }
                });
            ui.add_space(14.0);
            ui.label("click");
            egui::ComboBox::from_id_salt("click_mode")
                .width(110.0)
                .selected_text(s.click.label())
                .show_ui(ui, |ui| {
                    for m in ClickMode::ALL {
                        ui.selectable_value(&mut s.click, m, m.label());
                    }
                });
            ui.add(
                egui::DragValue::new(&mut s.click_db)
                    .range(-60.0..=0.0)
                    .speed(0.25)
                    .suffix(" dBFS"),
            )
            .on_hover_text("The click's peak level (it is mixed after everything, never recorded)");
            ui.add_space(14.0);
            ui.label("count-in");
            ui.add(
                egui::DragValue::new(&mut s.count_in_bars)
                    .range(0..=4)
                    .suffix(" bars"),
            );
            ui.add_space(8.0);
            ui.label("pre-roll");
            ui.add(
                egui::DragValue::new(&mut s.pre_roll_bars)
                    .range(0..=16)
                    .suffix(" bars"),
            )
            .on_hover_text("The tracks play before the start bar; a take starts at it");
            ui.add_space(8.0);
            ui.label("start bar");
            ui.add(egui::DragValue::new(&mut s.start_bar).range(1..=9999));
            ui.add_space(14.0);
            let per = s.beats_per_bar as i64;
            let looping = s.loop_on;
            let b = egui::Button::new(RichText::new("⟲ Loop").color(if looping {
                theme::ACCENT_INK
            } else {
                theme::MUTED
            }))
            .fill(if looping {
                theme::ACCENT
            } else {
                theme::CHROME2
            });
            if ui
                .add(b)
                .on_hover_text("Loop between the locators (/); recording makes a take per pass")
                .clicked()
            {
                s.loop_on = !s.loop_on;
            }
            let beat_field = |ui: &mut egui::Ui, k: &mut i64, tip: &str| {
                ui.add(
                    egui::DragValue::new(k)
                        .range(0..=99_999)
                        .speed(0.1)
                        .custom_formatter(move |v, _| {
                            let v = v as i64;
                            format!("{}.{}", v.div_euclid(per) + 1, v.rem_euclid(per) + 1)
                        })
                        .custom_parser(move |t| {
                            let mut it = t.split('.');
                            let bar: i64 = it.next()?.trim().parse().ok()?;
                            let beat: i64 = it.next().map_or(Some(1), |b| b.trim().parse().ok())?;
                            Some(((bar - 1) * per + beat - 1) as f64)
                        }),
                )
                .on_hover_text(tip);
            };
            ui.label("L");
            beat_field(
                ui,
                &mut s.left_beat,
                "The left locator (bar.beat): Ctrl+click the ruler",
            );
            ui.label("R");
            beat_field(
                ui,
                &mut s.right_beat,
                "The right locator (bar.beat): Alt+click the ruler",
            );
        });
        if self.session.transport != before {
            self.session.transport = self.session.transport.clone().clamped();
            self.save();
        }
    }

    /// The session's folder, New and Open.
    /// Undo, redo, and the session's folder: Save, Save as…, New, Open….
    fn session_line(&mut self, ui: &mut egui::Ui) {
        ui.add_space(16.0);
        if ui
            .add_enabled(!self.undo.is_empty(), egui::Button::new("↶ Undo").small())
            .on_hover_text(format!("Ctrl+Z ({} steps)", self.undo.len()))
            .clicked()
        {
            self.undo();
        }
        if ui
            .add_enabled(!self.redo.is_empty(), egui::Button::new("↷ Redo").small())
            .on_hover_text(format!("Ctrl+Y ({} steps)", self.redo.len()))
            .clicked()
        {
            self.redo();
        }
        ui.add_space(12.0);
        let name = self
            .session
            .dir
            .file_name()
            .map_or("?".into(), |n| n.to_string_lossy().to_string());
        ui.label(RichText::new(format!("session: {name}")).color(theme::MUTED))
            .on_hover_text(format!(
                "{}{}",
                self.session.dir.display(),
                if self.saved {
                    " (saved as you go)"
                } else {
                    " (written with the first take, or Save)"
                }
            ));
        if ui
            .small_button("Save")
            .on_hover_text("Ctrl+S: the session is also saved after every change")
            .clicked()
        {
            self.save_now();
        }
        match &mut self.save_as {
            None => {
                if ui
                    .small_button("Save as…")
                    .on_hover_text("Copy the session, every take's audio with it, to a new folder in sessions/ and carry on there (this one stays as it is)")
                    .clicked()
                {
                    self.save_as = Some(format!("{name} copy"));
                }
            }
            Some(text) => {
                let edit = ui.add(egui::TextEdit::singleline(text).desired_width(160.0));
                let enter = edit.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
                if ui.small_button("Save").clicked() || enter {
                    let n = text.clone();
                    self.save_as = None;
                    self.save_as(&n);
                } else if ui.small_button("Cancel").clicked() {
                    self.save_as = None;
                }
            }
        }
        if ui.small_button("New").clicked() {
            let s = Session::new(
                new_session_dir(&self.root),
                self.session.rate,
                self.session.transport.clone(),
            );
            self.switch_to(s, false);
        }
        if ui.small_button("Open…").clicked()
            && let Some(dir) = rfd::FileDialog::new()
                .set_directory(sessions_root(&self.root))
                .pick_folder()
        {
            match Session::load(&dir) {
                Ok(s) => {
                    self.switch_to(s, true);
                    self.error = None;
                }
                Err(e) => self.error = Some(e),
            }
        }
        if self.saved && ui.small_button("Show folder").clicked() {
            show_folder(&self.session.dir);
        }
    }

    /// Zoom by `factor` about `x` (px from the lanes' left).
    fn zoom(&mut self, factor: f64, x: Option<f64>) {
        let x = x.unwrap_or(0.0);
        let at_s = self.view_s + x / self.px_per_s;
        self.px_per_s = (self.px_per_s * factor).clamp(2.0, 2000.0);
        self.view_s = at_s - x / self.px_per_s;
    }

    /// The span the scrollbar covers (s): the session and a margin around what's in view.
    fn scroll_span(&self, lanes_w: f64) -> (f64, f64) {
        let rate = self.session.rate as f64;
        let grid = Grid::new(self.session.rate, &self.session.transport);
        let end_s = (self.session.end() as f64 / rate)
            .max(grid.beat(self.session.transport.right_beat) as f64 / rate)
            + 30.0;
        let visible = lanes_w / self.px_per_s;
        (self.view_s.min(-1.0), end_s.max(self.view_s + visible))
    }

    /// The ruler, the tracks, the scrollbar.
    fn arrangement(&mut self, ui: &mut egui::Ui, play: &PlayView) {
        let rate = self.session.rate as f64;
        let grid = Grid::new(self.session.rate, &self.session.transport);
        let st = play.player().map(|p| p.status());
        let running = st.as_ref().is_some_and(|s| s.transport.running);
        let heard = st.as_ref().map(|s| s.transport.heard);
        let full = ui.available_rect_before_wrap();
        let lanes_w = (full.width() - STRIP_W).max(50.0) as f64;
        self.lanes_w = lanes_w;
        // Wheel over the arrangement: Shift scrolls in time, Ctrl zooms about the pointer.
        if ui.rect_contains_pointer(full) {
            let (zoom, scroll, pointer) = ui.input(|i| {
                (
                    i.zoom_delta(),
                    i.smooth_scroll_delta.x,
                    i.pointer.hover_pos(),
                )
            });
            if zoom != 1.0 {
                let x = pointer.map_or(lanes_w * 0.5, |p| {
                    ((p.x - full.left() - STRIP_W) as f64).max(0.0)
                });
                self.zoom(zoom as f64, Some(x));
            }
            if scroll != 0.0 {
                self.view_s -= scroll as f64 / self.px_per_s;
            }
        }
        // Follow the playhead.
        if running
            && self.scroll_drag.is_none()
            && let Some(h) = heard
        {
            let x = (h as f64 / rate - self.view_s) * self.px_per_s;
            if x > lanes_w * 0.92 || x < 0.0 {
                self.view_s = h as f64 / rate - lanes_w * 0.1 / self.px_per_s;
            }
        }
        let view = View {
            left: full.left() + STRIP_W,
            view_s: self.view_s,
            px_per_s: self.px_per_s,
            rate,
        };
        // The ruler: the header with the zoom, the bars, the loop, the start bar.
        let (ruler, resp) =
            ui.allocate_exact_size(egui::vec2(full.width(), RULER_H), Sense::click_and_drag());
        let painter = ui.painter_at(ruler);
        painter.rect_filled(ruler, 0.0, theme::CHROME2);
        let lanes_rect = Rect::from_min_max(Pos2::new(view.left, ruler.top()), ruler.max);
        draw_ruler(&painter, lanes_rect, &view, &grid, &self.session.transport);
        let header = Rect::from_min_max(ruler.min, Pos2::new(view.left, ruler.bottom()));
        let mut hui = ui.new_child(
            egui::UiBuilder::new()
                .id_salt("ruler_header")
                .max_rect(header.shrink2(egui::vec2(10.0, 2.0)))
                .layout(egui::Layout::left_to_right(egui::Align::Center)),
        );
        hui.label(RichText::new("TRACKS").small().color(theme::FAINT));
        hui.add_space(hui.available_width() - 104.0);
        if hui
            .small_button("−")
            .on_hover_text("Zoom out (G)")
            .clicked()
        {
            self.zoom(0.5, Some(lanes_w * 0.5));
        }
        if hui.small_button("+").on_hover_text("Zoom in (H)").clicked() {
            self.zoom(2.0, Some(lanes_w * 0.5));
        }
        if hui
            .small_button("Fit")
            .on_hover_text("The whole session in view")
            .clicked()
        {
            let end_s = (self.session.end() as f64 / rate).max(8.0);
            self.px_per_s = (lanes_w / (end_s + 1.0)).clamp(2.0, 2000.0);
            self.view_s = -0.5;
        }
        // Clicks and drags on the bars.
        let snap = |x: f32| {
            let p = view.position(x);
            grid.beat_at(p + (grid.samples_per_beat() * 0.5) as i64)
        };
        let t = &mut self.session.transport;
        let mut moved = false;
        if resp.drag_started()
            && let Some(p) = resp.interact_pointer_pos()
            && p.x >= view.left
        {
            let (xl, xr) = (
                view.x(grid.beat(t.left_beat)),
                view.x(grid.beat(t.right_beat)),
            );
            self.ruler_drag = Some(if (p.x - xl).abs() < 7.0 {
                RulerDrag::Left
            } else if (p.x - xr).abs() < 7.0 {
                RulerDrag::Right
            } else {
                RulerDrag::New(snap(p.x))
            });
        }
        if resp.dragged()
            && let (Some(d), Some(p)) = (self.ruler_drag, ui.ctx().pointer_interact_pos())
        {
            let k = snap(p.x).max(0);
            match d {
                RulerDrag::Left => t.left_beat = k.min(t.right_beat - 1),
                RulerDrag::Right => t.right_beat = k.max(t.left_beat + 1),
                RulerDrag::New(a) => {
                    let a = a.max(0);
                    if k != a {
                        t.left_beat = a.min(k);
                        t.right_beat = a.max(k);
                        t.loop_on = true;
                    }
                }
            }
            moved = true;
        }
        if resp.drag_stopped() {
            self.ruler_drag = None;
            moved = true;
        }
        if resp.clicked()
            && let Some(p) = resp.interact_pointer_pos()
            && p.x >= view.left
        {
            let (ctrl, alt) = ui.input(|i| (i.modifiers.command, i.modifiers.alt));
            let k = snap(p.x).max(0);
            if ctrl {
                t.left_beat = k.min(t.right_beat - 1);
            } else if alt {
                t.right_beat = k.max(t.left_beat + 1);
            } else if !running {
                let bar = grid
                    .beat_at(view.position(p.x))
                    .div_euclid(grid.beats_per_bar as i64)
                    + 1;
                t.start_bar = bar.max(1);
            }
            moved = true;
        }
        if moved {
            self.session.transport = self.session.transport.clone().clamped();
            self.save();
        }
        if resp.hovered()
            && let Some(p) = ui.ctx().pointer_hover_pos()
        {
            let t = &self.session.transport;
            let (xl, xr) = (
                view.x(grid.beat(t.left_beat)),
                view.x(grid.beat(t.right_beat)),
            );
            if (p.x - xl).abs() < 7.0 || (p.x - xr).abs() < 7.0 {
                ui.ctx().set_cursor_icon(egui::CursorIcon::ResizeHorizontal);
            }
        }
        if let Some(h) = heard.filter(|_| running) {
            let x = view.x(h);
            if x >= view.left {
                painter.line_segment(
                    [Pos2::new(x, ruler.top()), Pos2::new(x, ruler.bottom())],
                    Stroke::new(1.5, theme::INK),
                );
            }
        }
        // The tracks, above the scrollbar.
        const BAR_H: f32 = 16.0;
        let mut changed = false;
        let tracks_h = (ui.available_height() - BAR_H - 4.0).max(40.0);
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .max_height(tracks_h)
            .show(ui, |ui| {
                let mut i = 0;
                while i < self.session.tracks.len() {
                    changed |= self.track_row(ui, i, &view, &grid, heard.filter(|_| running));
                    i += 1;
                }
                ui.add_space(6.0);
                ui.horizontal(|ui| {
                    ui.add_space(10.0);
                    if ui.button("+ Track").clicked() {
                        self.add_track();
                    }
                });
            });
        if changed {
            self.save();
        }
        // The scrollbar: the thumb is what's in view, of the session and a margin.
        ui.add_space(2.0);
        let (bar, bresp) =
            ui.allocate_exact_size(egui::vec2(full.width(), BAR_H), Sense::click_and_drag());
        let track = Rect::from_min_max(Pos2::new(view.left, bar.top()), bar.max);
        let (lo, hi) = self.scroll_span(lanes_w);
        let visible = lanes_w / self.px_per_s;
        let w = track.width() as f64;
        let to_x = |t: f64| track.left() + ((t - lo) / (hi - lo) * w) as f32;
        let thumb = Rect::from_min_max(
            Pos2::new(to_x(self.view_s), track.top() + 3.0),
            Pos2::new(
                to_x(self.view_s + visible).max(to_x(self.view_s) + 12.0),
                track.bottom() - 3.0,
            ),
        );
        let bp = ui.painter_at(bar);
        bp.rect_filled(track, 4.0, theme::CHROME);
        let hot = bresp.hovered() || self.scroll_drag.is_some();
        bp.rect_filled(thumb, 4.0, if hot { theme::MUTED } else { theme::FAINT });
        if bresp.drag_started()
            && let Some(p) = bresp.interact_pointer_pos()
        {
            if !thumb.contains(p) {
                // Jump: the thumb centred under the pointer, then drag from there.
                self.view_s = lo + ((p.x - track.left()) as f64 / w) * (hi - lo) - visible * 0.5;
            }
            self.scroll_drag = Some((p.x, self.view_s));
        }
        if bresp.dragged()
            && let (Some((x0, v0)), Some(p)) = (self.scroll_drag, ui.ctx().pointer_interact_pos())
        {
            self.view_s = v0 + ((p.x - x0) as f64 / w) * (hi - lo);
        }
        if bresp.drag_stopped() {
            self.scroll_drag = None;
        }
        if bresp.clicked()
            && let Some(p) = bresp.interact_pointer_pos()
            && !thumb.contains(p)
        {
            self.view_s = lo + ((p.x - track.left()) as f64 / w) * (hi - lo) - visible * 0.5;
        }
    }

    /// One track: its strip and its lane, and what a click or drag on them does. Returns
    /// whether the strip changed.
    fn track_row(
        &mut self,
        ui: &mut egui::Ui,
        i: usize,
        view: &View,
        grid: &Grid,
        playhead: Option<i64>,
    ) -> bool {
        let colour = COLOURS[i % COLOURS.len()];
        let width = ui.available_width();
        let t = &self.session.tracks[i];
        let shown = if t.show_takes { t.takes.len() } else { 0 };
        let (whole, _) = ui.allocate_exact_size(
            egui::vec2(width, TRACK_H + shown as f32 * TAKE_H),
            Sense::hover(),
        );
        let row = Rect::from_min_size(whole.min, egui::vec2(width, TRACK_H));
        let strip = Rect::from_min_size(row.min, egui::vec2(STRIP_W, TRACK_H));
        let lane = Rect::from_min_max(Pos2::new(row.left() + STRIP_W, row.top()), row.max);
        // The strip and lane take clicks and drags; the strip's controls, added after, sit
        // on top of them.
        let strip_resp = ui.interact(strip, ui.id().with(("strip", i)), Sense::click());
        let lane_resp = ui.interact(lane, ui.id().with(("lane", i)), Sense::click_and_drag());
        let mut changed = false;
        let clip_rect = |k: &Take| {
            Rect::from_min_max(
                Pos2::new(view.x(k.position), lane.top() + 4.0),
                Pos2::new(
                    view.x(k.end()).max(view.x(k.position) + 1.0),
                    lane.bottom() - 4.0,
                ),
            )
        };
        let on_clip = |p: Option<Pos2>, t: &Track| {
            p.zip(t.active_take())
                .is_some_and(|(p, k)| clip_rect(k).contains(p))
        };
        // Select (and arm) the track; select a take, drag it, delete it.
        if strip_resp.clicked() || lane_resp.clicked() || lane_resp.drag_started() {
            if self.session.armed != Some(i) && self.recording.is_none() {
                self.session.armed = Some(i);
                changed = true;
            }
            let t = &self.session.tracks[i];
            let hit = on_clip(lane_resp.interact_pointer_pos(), t)
                && lane_resp
                    .interact_pointer_pos()
                    .is_some_and(|p| lane.contains(p));
            self.selected = if hit { t.active.map(|k| (i, k)) } else { None };
            if lane_resp.drag_started()
                && hit
                && let (Some(k), Some(p)) = (t.active, lane_resp.interact_pointer_pos())
            {
                self.drag = Some(Drag {
                    track: i,
                    take: k,
                    from: t.takes[k].position,
                    press_x: p.x,
                });
            }
        }
        if lane_resp.dragged()
            && let Some(d) = &self.drag
            && d.track == i
            && let Some(p) = ui.ctx().pointer_interact_pos()
        {
            let free = ui.input(|x| x.modifiers.alt);
            let delta = ((p.x - d.press_x) as f64 / view.px_per_s * view.rate).round() as i64;
            let delta = if free {
                delta
            } else {
                let spb = grid.samples_per_beat();
                ((delta as f64 / spb).round() * spb).round() as i64
            };
            let (k, from) = (d.take, d.from);
            if let Some(take) = self.session.tracks[i].takes.get_mut(k) {
                take.position = from + delta;
            }
        }
        if lane_resp.drag_stopped()
            && let Some(d) = self.drag.take()
        {
            changed |= self.session.tracks[d.track]
                .takes
                .get(d.take)
                .is_some_and(|k| k.position != d.from);
        }
        let mut delete_take = None;
        lane_resp.context_menu(|ui| {
            let t = &self.session.tracks[i];
            match t.active {
                Some(k) => {
                    if ui
                        .button(format!("Delete take {}", t.takes[k].id))
                        .clicked()
                    {
                        delete_take = Some(k);
                        ui.close();
                    }
                }
                None => {
                    ui.label(RichText::new("no take").color(theme::MUTED));
                }
            }
        });
        let mut delete_track = false;
        strip_resp.context_menu(|ui| {
            if ui
                .button(format!("Delete track {}", self.session.tracks[i].name))
                .clicked()
            {
                delete_track = true;
                ui.close();
            }
        });
        // Paint.
        let armed = self.session.armed == Some(i);
        let painter = ui.painter_at(row);
        painter.rect_filled(
            strip,
            0.0,
            if armed { theme::CHROME3 } else { theme::CHROME },
        );
        painter.rect_filled(
            Rect::from_min_size(strip.min, egui::vec2(4.0, TRACK_H)),
            0.0,
            colour,
        );
        let lane_fill = if armed {
            theme::CHROME2
        } else if i.is_multiple_of(2) {
            theme::CANVAS
        } else {
            theme::BG
        };
        painter.rect_filled(lane, 0.0, lane_fill);
        painter.line_segment(
            [
                Pos2::new(row.left(), row.bottom()),
                Pos2::new(row.right(), row.bottom()),
            ],
            Stroke::new(1.0, theme::LINE),
        );
        if armed {
            painter.rect_stroke(
                strip.shrink(0.5),
                0.0,
                Stroke::new(1.0, REC.gamma_multiply(0.7)),
                StrokeKind::Inside,
            );
        }
        let lp = ui.painter_at(lane);
        draw_grid(&lp, lane, view, grid);
        let t = &self.session.transport;
        if t.loop_on {
            let (xl, xr) = (
                view.x(grid.beat(t.left_beat)),
                view.x(grid.beat(t.right_beat)),
            );
            lp.rect_filled(
                Rect::from_min_max(Pos2::new(xl, lane.top()), Pos2::new(xr, lane.bottom())),
                0.0,
                theme::ACCENT.gamma_multiply(0.05),
            );
            for x in [xl, xr] {
                lp.line_segment(
                    [Pos2::new(x, lane.top()), Pos2::new(x, lane.bottom())],
                    Stroke::new(1.0, theme::ACCENT.gamma_multiply(0.45)),
                );
            }
        }
        let track = &self.session.tracks[i];
        if let Some(k) = track.active_take() {
            draw_clip(
                &lp,
                lane,
                view,
                k.position,
                k.audio.len(),
                &k.overview,
                colour,
                &k.id,
            );
            if self.selected == track.active.map(|a| (i, a)) {
                lp.rect_stroke(
                    clip_rect(k),
                    3.0,
                    Stroke::new(2.0, theme::INK),
                    StrokeKind::Inside,
                );
            }
        }
        if armed && let Some(r) = &self.recording {
            draw_clip(
                &lp,
                lane,
                view,
                r.start - r.latency,
                r.len,
                &r.overview,
                REC,
                "recording",
            );
        }
        if let Some(h) = playhead {
            let x = view.x(h);
            if x >= lane.left() {
                lp.line_segment(
                    [Pos2::new(x, lane.top()), Pos2::new(x, lane.bottom())],
                    Stroke::new(1.5, theme::INK),
                );
            }
        }
        if lane_resp.hovered() && on_clip(ui.ctx().pointer_hover_pos(), track) {
            ui.ctx().set_cursor_icon(egui::CursorIcon::Grab);
        }
        // The strip's controls.
        let inner = strip.shrink2(egui::vec2(12.0, 8.0));
        let mut child = ui.new_child(
            egui::UiBuilder::new()
                .id_salt(("strip_controls", i))
                .max_rect(inner),
        );
        let mut arm_clicked = false;
        let t = &mut self.session.tracks[i];
        child.horizontal(|ui| {
            changed |= ui
                .add(
                    egui::TextEdit::singleline(&mut t.name)
                        .id_salt(("track_name", i))
                        .desired_width(118.0),
                )
                .lost_focus();
            let arm = egui::Button::new(RichText::new("●").color(if armed {
                Color32::WHITE
            } else {
                REC
            }))
            .fill(if armed { REC } else { theme::CHROME2 })
            .min_size(egui::vec2(24.0, 20.0));
            if ui
                .add(arm)
                .on_hover_text(
                    "Arm: this track records and plays the live device (or click the track)",
                )
                .clicked()
            {
                arm_clicked = true;
            }
            let toggle = |ui: &mut egui::Ui, on: &mut bool, text: &str, col: Color32, tip: &str| {
                let b = egui::Button::new(RichText::new(text).color(if *on {
                    theme::ACCENT_INK
                } else {
                    theme::MUTED
                }))
                .fill(if *on { col } else { theme::CHROME2 })
                .min_size(egui::vec2(22.0, 20.0));
                let c = ui.add(b).on_hover_text(tip).clicked();
                if c {
                    *on = !*on;
                }
                c
            };
            changed |= toggle(ui, &mut t.mute, "M", theme::WARN, "Mute");
            changed |= toggle(ui, &mut t.solo, "S", theme::OK, "Solo");
        });
        if arm_clicked && self.recording.is_none() {
            self.session.armed = Some(i);
            changed = true;
        }
        let t = &mut self.session.tracks[i];
        child.horizontal(|ui| {
            changed |= ui
                .add(
                    egui::DragValue::new(&mut t.volume_db)
                        .range(-60.0..=12.0)
                        .speed(0.2)
                        .max_decimals(1)
                        .suffix(" dB"),
                )
                .on_hover_text("Fader")
                .changed();
            changed |= ui
                .add(
                    egui::DragValue::new(&mut t.pan)
                        .range(-1.0..=1.0)
                        .speed(0.01)
                        .custom_formatter(|v, _| match v {
                            v if v.abs() < 0.005 => "C".into(),
                            v if v < 0.0 => format!("L{:.0}", -v * 100.0),
                            v => format!("R{:.0}", v * 100.0),
                        }),
                )
                .on_hover_text("Balance")
                .changed();
            let n = t.takes.len();
            if n > 0 {
                let a = t.active.unwrap_or(0);
                if ui
                    .add_enabled(a > 0, egui::Button::new("‹").small())
                    .on_hover_text("The earlier take")
                    .clicked()
                {
                    t.active = Some(a - 1);
                    changed = true;
                }
                ui.label(
                    RichText::new(format!("{}/{n}", a + 1))
                        .small()
                        .color(theme::MUTED),
                );
                if ui
                    .add_enabled(a + 1 < n, egui::Button::new("›").small())
                    .on_hover_text("The later take")
                    .clicked()
                {
                    t.active = Some(a + 1);
                    changed = true;
                }
                if ui
                    .add(egui::Button::new(if t.show_takes { "▾" } else { "▸" }).small())
                    .on_hover_text("Show every take of this track (click one to play it)")
                    .clicked()
                {
                    t.show_takes = !t.show_takes;
                    changed = true;
                }
            }
        });
        if let Some(k) = self.session.tracks[i].active_take() {
            child.label(
                RichText::new(take_line(k, self.session.rate))
                    .small()
                    .color(theme::FAINT),
            );
        }
        // Every take, stacked under the track: the one playing marked, a click plays another.
        if shown > 0 {
            for j in 0..self.session.tracks[i].takes.len() {
                let y = row.bottom() + j as f32 * TAKE_H;
                let srow = Rect::from_min_size(Pos2::new(row.left(), y), egui::vec2(width, TAKE_H));
                let sstrip = Rect::from_min_size(srow.min, egui::vec2(STRIP_W, TAKE_H));
                let slane = Rect::from_min_max(Pos2::new(srow.left() + STRIP_W, y), srow.max);
                let resp = ui
                    .interact(srow, ui.id().with(("take_lane", i, j)), Sense::click())
                    .on_hover_text("Click: play this take on the track");
                let t = &self.session.tracks[i];
                let k = &t.takes[j];
                let active = t.active == Some(j);
                let p = ui.painter_at(srow);
                p.rect_filled(sstrip, 0.0, theme::CHROME);
                p.rect_filled(slane, 0.0, theme::BG);
                p.line_segment(
                    [
                        Pos2::new(srow.left(), srow.bottom()),
                        Pos2::new(srow.right(), srow.bottom()),
                    ],
                    Stroke::new(1.0, theme::DOT),
                );
                p.text(
                    Pos2::new(sstrip.left() + 22.0, sstrip.center().y),
                    egui::Align2::LEFT_CENTER,
                    format!(
                        "{}take {} · {} · {:.1} s",
                        if active { "▶ " } else { "" },
                        j + 1,
                        k.id,
                        k.audio.len() as f64 / self.session.rate as f64
                    ),
                    egui::FontId::proportional(11.0),
                    if active { theme::ACCENT } else { theme::MUTED },
                );
                let lp = ui.painter_at(slane);
                draw_grid(&lp, slane, view, grid);
                draw_clip(
                    &lp,
                    slane,
                    view,
                    k.position,
                    k.audio.len(),
                    &k.overview,
                    if active { colour } else { theme::FAINT },
                    "",
                );
                if resp.clicked() && !active {
                    self.session.tracks[i].active = Some(j);
                    changed = true;
                }
                resp.context_menu(|ui| {
                    if ui.button(format!("Delete take {}", j + 1)).clicked() {
                        delete_take = Some(j);
                        ui.close();
                    }
                });
            }
        }
        if let Some(k) = delete_take {
            self.delete_take(i, k);
        }
        if delete_track {
            self.delete_track(i);
        }
        changed
    }

    fn latency_ui(&mut self, ui: &mut egui::Ui, play: &PlayView) {
        let Some(p) = play.player() else {
            ui.label(
                RichText::new("latency: (while a device plays)")
                    .small()
                    .color(theme::MUTED),
            );
            return;
        };
        let st = p.status();
        let out = p.output_latency_s();
        let queue = p.queued_s();
        let block = BLOCK as f64 / p.rate as f64;
        let heard = out + queue;
        ui.label(format!(
            "output device {:.1} ms (cpal) · queue {:.1} ms · block {:.1} ms: the tracks and the click are heard {:.0} ms after they are computed, a key about {:.0} ms after it is played (takes are placed by it)",
            out * 1e3,
            queue * 1e3,
            block * 1e3,
            heard * 1e3,
            (heard + block * (1.0 + st.load)) * 1e3
        ));
        for c in self.calibrations.iter().filter(|c| c.output == st.device) {
            ui.label(format!(
                "round trip via {}: {:.2} ms measured, {:.2} ms by cpal ({:+.2} ms)",
                c.input,
                c.round_trip_s * 1e3,
                c.cpal_round_trip_s * 1e3,
                (c.round_trip_s - c.cpal_round_trip_s) * 1e3
            ));
        }
    }

    fn calibrate_ui(&mut self, ui: &mut egui::Ui, play: &PlayView) {
        ui.label(
            RichText::new(
                "Loopback calibration: an output cabled to an input of the interface (or a channel that \
                 returns its output, or the output's own mix). The click plays 8 s with the device muted \
                 and is found in the capture.",
            )
            .small()
            .color(theme::MUTED),
        );
        let idle = matches!(self.calibrate, Calibrate::Idle);
        ui.horizontal(|ui| {
            if self.inputs.is_empty() && ui.small_button("list inputs").clicked() {
                self.inputs = input_devices();
            }
            let label = |i: usize, inputs: &[InputDevice]| match i {
                0 => "the output's own mix (no cable)".to_string(),
                i => inputs
                    .get(i - 1)
                    .map_or("?".into(), |d| format!("{} ({} ch)", d.name, d.channels)),
            };
            ui.add_enabled_ui(idle, |ui| {
                egui::ComboBox::from_id_salt("cal_source")
                    .width(300.0)
                    .selected_text(label(self.cal_source, &self.inputs))
                    .show_ui(ui, |ui| {
                        for i in 0..=self.inputs.len() {
                            ui.selectable_value(&mut self.cal_source, i, label(i, &self.inputs));
                        }
                    });
                if let Some(d) = self
                    .cal_source
                    .checked_sub(1)
                    .and_then(|i| self.inputs.get(i))
                {
                    ui.label("ch");
                    let mut ch = self.cal_channel + 1;
                    ui.add(egui::DragValue::new(&mut ch).range(1..=d.channels as usize));
                    self.cal_channel = ch - 1;
                }
            });
            let can = idle
                && play.player().is_some_and(|p| {
                    p.status().state == State::Playing && !p.status().transport.running
                });
            if ui
                .add_enabled(can, egui::Button::new("Calibrate"))
                .on_hover_text("Needs a device playing and the transport stopped")
                .clicked()
            {
                self.start_calibration(play);
            }
            if let Calibrate::Running { run, .. } = &self.calibrate {
                let f = (run.started.elapsed().as_secs_f64() / CALIBRATE_S).min(1.0) as f32;
                ui.add(egui::ProgressBar::new(f).desired_width(160.0));
            } else if matches!(self.calibrate, Calibrate::Analysing { .. }) {
                ui.spinner();
            }
        });
        if let Some((input, a)) = &self.last {
            let ok = a.found == a.scheduled && a.max_residual <= 1.0;
            ui.colored_label(
                if ok { theme::OK } else { theme::WARN },
                format!(
                    "{input}: {} of {} clicks found · each within {:.3} samples of its line · drift {:+.1} ppm",
                    a.found, a.scheduled, a.max_residual, a.drift_ppm
                ),
            );
            if let (Some(rt), Some(c)) = (a.round_trip_s, a.cpal_round_trip_s) {
                ui.label(format!(
                    "round trip {:.2} ms measured, {:.2} ms by cpal ({:+.2} ms)",
                    rt * 1e3,
                    c * 1e3,
                    (rt - c) * 1e3
                ));
            }
        }
    }

    fn start_calibration(&mut self, play: &PlayView) {
        let Some(p) = play.player() else { return };
        let source = match self
            .cal_source
            .checked_sub(1)
            .and_then(|i| self.inputs.get(i))
        {
            None => loopback::Source::Output { device: None },
            Some(d) => loopback::Source::Input {
                device: Some(d.name.clone()),
                channel: self.cal_channel,
            },
        };
        match Run::start(&source) {
            Ok(run) => {
                p.set_compensation(false);
                p.set_output_db(-300.0);
                p.arm_take(false);
                // Only the click: no tracks.
                p.set_mix(Arc::new(varimu_app::session::Mix::default()));
                p.set_transport(&TransportSettings {
                    click: ClickMode::On,
                    click_db: -20.0,
                    count_in_bars: 0,
                    pre_roll_bars: 0,
                    ..self.session.transport.clone()
                });
                p.transport_run(true);
                self.calibrate = Calibrate::Running {
                    input: run.name().to_string(),
                    output: p.status().device,
                    run: Box::new(run),
                    origin: None,
                };
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }

    fn poll_calibration(&mut self, play: &PlayView) {
        match std::mem::replace(&mut self.calibrate, Calibrate::Idle) {
            Calibrate::Idle => {}
            Calibrate::Running {
                run,
                input,
                output,
                mut origin,
            } => {
                let Some(p) = play.player() else {
                    self.error = Some("the device stopped during the calibration".into());
                    return;
                };
                run.note_output(p.output_clock());
                let st = p.status();
                origin = origin.or(st.transport.origin);
                if run.started.elapsed().as_secs_f64() < CALIBRATE_S {
                    self.calibrate = Calibrate::Running {
                        run,
                        input,
                        output,
                        origin,
                    };
                    return;
                }
                p.transport_run(false);
                play.apply_monitor();
                let (Some(grid), Some(origin)) = (st.transport.grid, origin) else {
                    self.error = Some("the transport didn't run".into());
                    return;
                };
                let captured = (*run).stop();
                let (rate, out_s) = (p.rate, p.output_latency_s());
                let (tx, rx) = mpsc::channel();
                std::thread::spawn(move || {
                    let r = captured.analyse(&grid, origin, rate, out_s).map(|(a, _)| a);
                    let _ = tx.send(r);
                });
                self.calibrate = Calibrate::Analysing { rx, input, output };
            }
            Calibrate::Analysing { rx, input, output } => match rx.try_recv() {
                Ok(Ok(a)) => {
                    if let (Some(rt), Some(c)) = (a.round_trip_s, a.cpal_round_trip_s)
                        && a.found > 0
                    {
                        self.calibrations
                            .retain(|x| !(x.output == output && x.input == input));
                        self.calibrations.push(Calibration {
                            output,
                            input: input.clone(),
                            round_trip_s: rt,
                            cpal_round_trip_s: c,
                        });
                        self.save_prefs();
                    }
                    self.last = Some((input, a));
                }
                Ok(Err(e)) => self.error = Some(e),
                Err(mpsc::TryRecvError::Empty) => {
                    self.calibrate = Calibrate::Analysing { rx, input, output };
                }
                Err(mpsc::TryRecvError::Disconnected) => {
                    self.error = Some("the analysis stopped".into());
                }
            },
        }
    }
}

/// The last session, the default transport and the calibrations (`recording.json`).
fn load_prefs() -> (Option<PathBuf>, TransportSettings, Vec<Calibration>) {
    let Some(text) = prefs_path().and_then(|p| std::fs::read_to_string(p).ok()) else {
        return (None, TransportSettings::default(), Vec::new());
    };
    let v: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
    let last = v["last_session"].as_str().map(PathBuf::from);
    let cals = v["calibrations"]
        .as_array()
        .map(|a| {
            a.iter()
                .filter_map(|c| {
                    Some(Calibration {
                        output: c["output"].as_str()?.to_string(),
                        input: c["input"].as_str()?.to_string(),
                        round_trip_s: c["round_trip_s"].as_f64()?,
                        cpal_round_trip_s: c["cpal_round_trip_s"].as_f64()?,
                    })
                })
                .collect()
        })
        .unwrap_or_default();
    (last, transport_from(&v["transport"]), cals)
}

fn show_folder(dir: &Path) {
    #[cfg(windows)]
    let _ = std::process::Command::new("explorer").arg(dir).spawn();
    #[cfg(not(windows))]
    let _ = std::process::Command::new("xdg-open").arg(dir).spawn();
}

/// A take's line under its strip: its id, device, length and latency.
fn take_line(k: &Take, rate: u32) -> String {
    format!(
        "{} · {} · {:.1} s · placed {:.0} ms early",
        k.id,
        if k.device.is_empty() { "?" } else { &k.device },
        k.audio.len() as f64 / rate as f64,
        k.latency as f64 / rate as f64 * 1e3
    )
}

/// The timeline's mapping between positions (samples) and x (px).
struct View {
    left: f32,
    view_s: f64,
    px_per_s: f64,
    rate: f64,
}

impl View {
    fn x(&self, pos: i64) -> f32 {
        self.left + ((pos as f64 / self.rate - self.view_s) * self.px_per_s) as f32
    }

    fn position(&self, x: f32) -> i64 {
        ((self.view_s + (x - self.left) as f64 / self.px_per_s) * self.rate).round() as i64
    }
}

/// Bars wide enough apart to label: every 1, 2, 4, ... bars.
fn bar_step(view: &View, grid: &Grid) -> i64 {
    let bar_px = grid.samples_per_beat() * grid.beats_per_bar as f64 / view.rate * view.px_per_s;
    let mut step = 1;
    while (bar_px * step as f64) < 48.0 && step < 4096 {
        step *= 2;
    }
    step
}

fn draw_ruler(
    painter: &egui::Painter,
    rect: Rect,
    view: &View,
    grid: &Grid,
    s: &TransportSettings,
) {
    let step = bar_step(view, grid);
    let first = grid
        .beat_at(view.position(rect.left()))
        .div_euclid(grid.beats_per_bar as i64)
        + 1;
    let mut bar = first - first.rem_euclid(step);
    loop {
        let x = view.x(grid.bar(bar));
        if x > rect.right() {
            break;
        }
        if x >= rect.left() && bar >= 1 {
            painter.line_segment(
                [
                    Pos2::new(x, rect.bottom() - 8.0),
                    Pos2::new(x, rect.bottom()),
                ],
                Stroke::new(1.0, theme::MUTED),
            );
            painter.text(
                Pos2::new(x + 3.0, rect.top() + 10.0),
                egui::Align2::LEFT_TOP,
                bar.to_string(),
                egui::FontId::monospace(11.0),
                theme::MUTED,
            );
        }
        bar += step;
    }
    // The locators: a band between them (bright while looping), a handle at each.
    let (xl, xr) = (
        view.x(grid.beat(s.left_beat)),
        view.x(grid.beat(s.right_beat)),
    );
    let band = Rect::from_min_max(
        Pos2::new(xl.max(rect.left()), rect.top() + 2.0),
        Pos2::new(xr.min(rect.right()), rect.top() + 9.0),
    );
    if band.width() > 0.0 {
        let c = if s.loop_on {
            theme::ACCENT.gamma_multiply(0.8)
        } else {
            theme::FAINT.gamma_multiply(0.7)
        };
        painter.rect_filled(band, 2.0, c);
    }
    for (x, name) in [(xl, "L"), (xr, "R")] {
        if x >= rect.left() && x <= rect.right() {
            let c = if s.loop_on {
                theme::ACCENT
            } else {
                theme::MUTED
            };
            painter.line_segment(
                [Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())],
                Stroke::new(1.5, c),
            );
            painter.text(
                Pos2::new(x + 3.0, rect.bottom() - 2.0),
                egui::Align2::LEFT_BOTTOM,
                name,
                egui::FontId::proportional(9.0),
                c,
            );
        }
    }
    // The start bar.
    let x = view.x(grid.bar(s.start_bar));
    if x >= rect.left() && x <= rect.right() {
        let y = rect.bottom();
        painter.add(egui::Shape::convex_polygon(
            vec![
                Pos2::new(x, y),
                Pos2::new(x - 6.0, y - 9.0),
                Pos2::new(x + 6.0, y - 9.0),
            ],
            theme::ACCENT,
            Stroke::NONE,
        ));
    }
}

fn draw_grid(painter: &egui::Painter, rect: Rect, view: &View, grid: &Grid) {
    let step = bar_step(view, grid);
    let beat_px = grid.samples_per_beat() / view.rate * view.px_per_s;
    let first = grid.beat_at(view.position(rect.left()));
    let mut k = first;
    loop {
        let x = view.x(grid.beat(k));
        if x > rect.right() {
            break;
        }
        let bar = k.div_euclid(grid.beats_per_bar as i64) + 1;
        let downbeat = grid.is_downbeat(k);
        let show = if downbeat {
            (bar - 1).rem_euclid(step) == 0
        } else {
            beat_px >= 14.0
        };
        if x >= rect.left() && show {
            let c = if downbeat { theme::LINE } else { theme::DOT };
            painter.line_segment(
                [Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())],
                Stroke::new(1.0, c),
            );
        }
        k += 1;
    }
}

/// A clip: a rounded box from `start` for `len` samples, its waveform from `ov`.
#[allow(clippy::too_many_arguments)]
fn draw_clip(
    painter: &egui::Painter,
    lane: Rect,
    view: &View,
    start: i64,
    len: usize,
    ov: &Overview,
    colour: Color32,
    label: &str,
) {
    let (x0, x1) = (view.x(start), view.x(start + len as i64));
    if x1 < lane.left() || x0 > lane.right() {
        return;
    }
    let r = Rect::from_min_max(
        Pos2::new(x0, lane.top() + 4.0),
        Pos2::new(x1.max(x0 + 1.0), lane.bottom() - 4.0),
    );
    painter.rect_filled(r, 3.0, colour.gamma_multiply(0.22));
    painter.rect_stroke(
        r,
        3.0,
        Stroke::new(1.0, colour.gamma_multiply(0.8)),
        StrokeKind::Inside,
    );
    painter.text(
        Pos2::new(r.left().max(lane.left()) + 5.0, r.top() + 2.0),
        egui::Align2::LEFT_TOP,
        label,
        egui::FontId::proportional(10.0),
        colour,
    );
    // The waveform: one line per pixel column, the lowest to the highest sample in it
    // (under the label, if there is one).
    let (mid, half) = if label.is_empty() {
        (r.center().y, r.height() * 0.42)
    } else {
        (r.center().y + 5.0, (r.height() - 16.0) * 0.5)
    };
    let spp = view.rate / view.px_per_s; // samples per pixel
    let (a, b) = (
        x0.max(lane.left()).floor() as i32,
        x1.min(lane.right()).ceil() as i32,
    );
    let wave = colour.gamma_multiply(0.95);
    for px in a..b {
        let s0 = (px as f32 - x0) as f64 * spp;
        if let Some((lo, hi)) = ov.range(s0, s0 + spp) {
            let (lo, hi) = (lo.clamp(-1.0, 1.0), hi.clamp(-1.0, 1.0));
            painter.line_segment(
                [
                    Pos2::new(px as f32 + 0.5, mid - hi * half),
                    Pos2::new(px as f32 + 0.5, mid - lo * half + 0.5),
                ],
                Stroke::new(1.0, wave),
            );
        }
    }
}
