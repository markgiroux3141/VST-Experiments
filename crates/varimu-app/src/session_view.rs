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
//!
//! **Inserts** (docs/SESSION_FX_PLAN.md, F2): under each track's strip its chain of devices
//! (+ adds one; a click selects one, its panel opens at the bottom; right-click bypasses,
//! moves or removes it). The chain is rendered on the active take in the background
//! (`varimu_app::print`, at most [`MAX_PRINT_JOBS`] at a time, none while recording or
//! while a knob is held), and the track plays that render (a preview: the inserts stay
//! editable): ✓ ready, ◔ rendering, … waiting
//! (the older print plays meanwhile), ! failed. The first insert's trim is set once from
//! the take's loudest stretch to the alignment level (-18 dBFS); later ones start at 0 dB.
//!
//! **Audition** (F3): while an insert's panel is open, that device plays live in the
//! session's player (the Play view's device stops: one live device), fed by the track's
//! audio where the transport is (the prints of the inserts before it, else the take), so
//! Space plays the session with it and its knobs, trim, make-up and bypass are heard as
//! they turn (an instrument playing from the Play view gives way only to a panel just
//! opened, and plays again when it closes; one started while a panel is open closes the
//! panel). The other tracks play their prints; the inserts after it aren't heard. The
//! track isn't rendered while it is auditioned: closing the panel renders it. No recording
//! while auditioning.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::mpsc::{self, Receiver};
use std::time::Duration;

use eframe::egui::{self, Color32, Pos2, Rect, RichText, Sense, Stroke, StrokeKind};
use serde_json::{Value, json};
use varimu_app::audio;
use varimu_app::live::{Circuit, Values};
use varimu_app::loopback::{self, Analysis, Calibration, Run};
use varimu_app::panel::{self as vpanel, DEVICES, Kind, Knob};
use varimu_app::player::{BLOCK, InputDevice, Player, Source, State, input_devices};
use varimu_app::prefs::ALIGNMENT_DBFS;
use varimu_app::print::{Job, Slot, find_device};
use varimu_app::session::{
    OVERVIEW_BIN, Overview, Printed, Session, Take, Track, transport_from, transport_json,
};
use varimu_app::settings::{Quality, Settings};
use varimu_app::transport::{ClickMode, Grid, Phase, TransportSettings};
use varimu_circuit::spec;
use varimu_circuit::yaml::Value as YValue;

use crate::play_view::PlayView;

// **Render** (⤓, the user's ask 2026-10-31): a track's chain rendered at production into a
// new take on the track, its inserts then removed (the effect baked in). The source take
// stays in the lane and Undo brings the inserts back; the new take's `take.json` says what
// it was rendered from. One at a time, in the background.
//
// **No live device needed to play.** While neither the Play view's device nor an
// audition plays, the session runs the tracks-only player (`Player::start_mix`), so the
// transport always has ▶; ● (record) starts the Play view's device and records once it
// plays.
use crate::theme;

/// How long a calibration plays the click (s).
const CALIBRATE_S: f64 = 8.0;
/// The channel strips' width and a track's height (px).
const STRIP_W: f32 = 250.0;
const TRACK_H: f32 = 102.0;
const RULER_H: f32 = 26.0;
/// A take's row when a track shows every take (px).
const TAKE_H: f32 = 34.0;
/// Prints running at once (each a chain on its own thread; a draft 670 uses two cores).
const MAX_PRINT_JOBS: usize = 2;
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

/// A track's chain printing: what it is made from, the take, the job.
struct PrintJob {
    signature: String,
    take: String,
    job: Job,
    cancelled: bool,
}

/// An insert playing live (F3): which, what its input is (to see it change), and what
/// was last sent to the player.
struct Audition {
    track: usize,
    slot: usize,
    device: String,
    input: String,
    values: Values,
    gains: (f64, f64, bool, f64),
}

/// A track's chain rendering into a new take (⤓ Render): the track, its source take, the
/// job.
struct Bake {
    track: usize,
    take: String,
    slots: Vec<Slot>,
    job: Job,
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
    /// Prints running, the chains whose print failed (by signature), the insert whose
    /// panel is open (track, slot), each device's knobs (by id).
    jobs: Vec<PrintJob>,
    print_errors: HashMap<String, String>,
    insert_sel: Option<(usize, usize)>,
    knobs: HashMap<String, Result<Vec<Knob>, String>>,
    audition: Option<Audition>,
    /// The audition's state as the panel shows it (set each frame).
    audition_status: Option<String>,
    bake: Option<Bake>,
    /// The tracks-only player couldn't start (don't retry every frame).
    mix_failed: bool,
    /// Record was pressed while no instrument played: record once it plays.
    record_pending: bool,
    /// The user opened an insert's panel this frame (an audition may take an instrument's
    /// place only then), and the instrument to start again when the audition ends.
    audition_request: bool,
    resume_instrument: bool,
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
            jobs: Vec::new(),
            print_errors: HashMap::new(),
            insert_sel: None,
            knobs: HashMap::new(),
            audition: None,
            audition_status: None,
            bake: None,
            mix_failed: false,
            record_pending: false,
            audition_request: false,
            resume_instrument: false,
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
        self.sync_audition(play, idle);
        // Nothing playing: the tracks-only player, so ▶ is always there.
        if idle && self.audition.is_none() && play.player().is_none() && !self.mix_failed {
            self.mix_failed = !self.start_mix(play);
        }
        // Record asked for while the instrument started: record once it plays.
        if self.record_pending
            && let Some(p) = play.player()
            && !play.adopted()
        {
            match p.status().state {
                State::Playing => {
                    self.record_pending = false;
                    self.play(play, true);
                }
                State::Failed(_) => self.record_pending = false,
                State::Starting => {}
            }
        }
        self.poll_bake();
        if idle {
            if self.audition.is_none() {
                play.apply_monitor();
            }
            if let Some(p) = play.player() {
                p.set_transport(&self.session.transport);
                let mix = match &self.audition {
                    Some(a) => self.session.mix_audition(a.track),
                    None => self.session.mix(),
                };
                p.set_mix(Arc::new(mix));
            }
        }
        self.poll_recording(play);
        let armed = play.player().is_some_and(|p| p.take_armed());
        self.poll_prints(ui.ctx(), armed);
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
        if self.insert_selected().is_some() {
            egui::Panel::bottom("session_insert")
                .frame(
                    egui::Frame::NONE
                        .fill(theme::CHROME2)
                        .inner_margin(egui::Margin::symmetric(14, 10)),
                )
                .show(ui, |ui| self.insert_panel(ui));
        }
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
        if record && self.audition.is_some() {
            self.error = Some("close the insert's panel to record (it plays live)".into());
            return;
        }
        // Recording needs the live device (the Play view's choice); playing doesn't: with
        // nothing playing, the session's tracks play on their own.
        if record && play.adopted() {
            let (label, _) = play.device_label_id();
            play.start_device();
            self.mix_failed = false;
            self.record_pending = play.player().is_some();
            self.error = None;
            if self.record_pending {
                self.error = Some(format!("starting {label}: recording begins once it plays"));
            }
            return;
        }
        let Some(p) = play.player() else {
            if record {
                play.start_device();
            } else if self.start_mix(play)
                && let Some(p) = play.player()
            {
                p.transport_run(true);
            }
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

    /// The selected insert's input for an audition: the print of the inserts before it
    /// (if the track's print holds it), else the active take; where it starts, and a key
    /// that changes when it does.
    fn audition_input(&self, t: usize, k: usize) -> Option<(Arc<Vec<f32>>, i64, String)> {
        let track = self.session.tracks.get(t)?;
        let take = track.active_take()?;
        let stage = track.inserts[..k].iter().filter(|s| !s.bypass).count();
        let printed = track
            .printed
            .as_ref()
            .filter(|p| p.take == take.id && stage > 0 && p.stages.len() >= stage);
        let audio = match printed {
            Some(p) => p.stages[stage - 1].clone(),
            None => take.audio.clone(),
        };
        let key = format!(
            "{}|{}|{}|{}|{:p}",
            take.id,
            stage,
            take.position,
            audio.len(),
            Arc::as_ptr(&audio)
        );
        Some((audio, take.position, key))
    }

    /// The audition follows the open panel: started (the Play view's device stops) when an
    /// insert is selected or its input changes, its knobs and gains sent as they change,
    /// stopped when the panel closes.
    fn sync_audition(&mut self, play: &mut PlayView, idle: bool) {
        let requested = std::mem::take(&mut self.audition_request);
        // The instrument started from the Play view while an insert played: it wins, and
        // the insert's panel closes (a panel left open never stops an instrument).
        let instrument = play.player().is_some() && !play.adopted();
        if self.audition.is_some() && instrument {
            self.audition = None;
            self.audition_status = None;
            self.insert_sel = None;
            self.resume_instrument = false;
            return;
        }
        let want = self
            .insert_selected()
            .filter(|_| idle && self.recording.is_none());
        let Some((t, k)) = want else {
            if self.audition.take().is_some() {
                self.end_audition(play);
            }
            return;
        };
        let Some((audio, start, input)) = self.audition_input(t, k) else {
            // Nothing to play into it yet (no take).
            if self.audition.take().is_some() {
                self.end_audition(play);
            }
            return;
        };
        let slot = self.session.tracks[t].inserts[k].clone();
        let same = self.audition.as_ref().is_some_and(|a| {
            a.track == t && a.slot == k && a.device == slot.device && a.input == input
        }) && play.adopted();
        if !same {
            // An instrument plays: only a panel the user just opened takes its place (it
            // comes back when the panel closes); a panel left open closes instead.
            if self.audition.is_none() && instrument {
                if !requested {
                    self.insert_sel = None;
                    return;
                }
                self.resume_instrument = true;
            }
            let running = play.player().is_some_and(|p| p.status().transport.running);
            match self.start_audition(&slot, audio, start) {
                Ok(p) => {
                    if p.rate != self.session.rate && self.session.end() > 0 {
                        self.error = Some(format!(
                            "{} plays at {} Hz, the session is at {} Hz",
                            slot.device, p.rate, self.session.rate
                        ));
                        self.insert_sel = None;
                        return;
                    }
                    p.set_transport(&self.session.transport);
                    if running {
                        p.transport_run(true);
                    }
                    play.adopt(p);
                    self.audition = Some(Audition {
                        track: t,
                        slot: k,
                        device: slot.device.clone(),
                        input,
                        values: slot.values.clone(),
                        gains: (f64::NAN, f64::NAN, false, f64::NAN),
                    });
                    self.error = None;
                }
                Err(e) => {
                    self.error = Some(format!("can't play {} live: {e}", slot.device));
                    self.insert_sel = None;
                    return;
                }
            }
        }
        let (Some(a), Some(p)) = (self.audition.as_mut(), play.player()) else {
            return;
        };
        let st = p.status();
        self.audition_status = Some(match &st.state {
            State::Starting => "● live: starting…".to_string(),
            State::Failed(e) => format!("live: stopped ({e})"),
            State::Playing => format!(
                "● live{} · load {:.0}%",
                if st.transport.running {
                    ", playing"
                } else {
                    " (Space plays)"
                },
                st.load * 100.0
            ),
        });
        if a.values != slot.values {
            p.set(slot.values.clone());
            a.values = slot.values.clone();
        }
        let gains = (slot.trim_db, slot.makeup_db, slot.bypass, slot.wet);
        if a.gains != gains {
            p.set_gain(10f64.powf(slot.trim_db / 20.0));
            p.set_output_db(slot.makeup_db);
            p.set_bypass(slot.bypass);
            p.set_wet(slot.wet);
            p.set_compensation(false);
            a.gains = gains;
        }
    }

    /// The audition's player stopped; if the session was playing, it plays on without a
    /// device.
    fn end_audition(&mut self, play: &mut PlayView) {
        let running = play.player().is_some_and(|p| p.status().transport.running);
        play.release();
        self.audition_status = None;
        // The instrument the audition took the place of plays again.
        if std::mem::take(&mut self.resume_instrument) {
            play.start_device();
            return;
        }
        if running
            && self.start_mix(play)
            && let Some(p) = play.player()
        {
            p.transport_run(true);
        }
    }

    /// The session's tracks playing with no device (`Player::start_mix`), in the Play
    /// view's place.
    fn start_mix(&mut self, play: &mut PlayView) -> bool {
        let config = self.root.join("config");
        match Settings::load(&config, Quality::Draft1x)
            .and_then(|s| Player::start_mix(None, s, 0.05))
        {
            Ok(p) => {
                p.set_transport(&self.session.transport);
                p.set_mix(Arc::new(self.session.mix()));
                play.adopt(p);
                true
            }
            Err(e) => {
                self.error = Some(e);
                false
            }
        }
    }

    /// A player for `slot`'s device at its play quality, fed by `audio` from timeline
    /// position `start`.
    fn start_audition(
        &self,
        slot: &Slot,
        audio: Arc<Vec<f32>>,
        start: i64,
    ) -> Result<Player, String> {
        let config = self.root.join("config");
        let d = find_device(&slot.device).ok_or(format!("no device {}", slot.device))?;
        let s = d.play_settings(&Settings::load(&config, d.quality)?);
        let circuit = Circuit::load(&config, d.circuit, s.cores()?)?.with_noise(slot.noise);
        let p = Player::start(
            Source::Timeline { audio, start },
            slot.values.clone(),
            circuit,
            s,
            10f64.powf(slot.trim_db / 20.0),
            d.ahead_s,
        )?;
        p.set_compensation(false);
        p.set_output_db(slot.makeup_db);
        p.set_bypass(slot.bypass);
        p.set_wet(slot.wet);
        Ok(p)
    }

    /// Prints: finished ones to their tracks, ones no track wants any more cancelled, and
    /// new ones started for chains whose print isn't current (not while recording or while
    /// a gesture is in progress: a knob held prints once, when it's let go).
    fn poll_prints(&mut self, ctx: &egui::Context, recording: bool) {
        let rate = self.session.rate;
        let mut i = 0;
        while i < self.jobs.len() {
            if !self.jobs[i].job.is_finished() {
                i += 1;
                continue;
            }
            let j = self.jobs.remove(i);
            match j.job.join() {
                Some(Ok(prints)) => {
                    let Some(audio) = prints.last().map(|p| p.audio.clone()) else {
                        continue;
                    };
                    let printed = Printed {
                        signature: j.signature.clone(),
                        take: j.take.clone(),
                        overview: Arc::new(Overview::of(&audio, OVERVIEW_BIN)),
                        audio,
                        stages: prints.iter().map(|p| p.audio.clone()).collect(),
                    };
                    for t in &mut self.session.tracks {
                        if t.chain_signature(rate).as_deref() == Some(j.signature.as_str()) {
                            t.printed = Some(printed.clone());
                        }
                    }
                }
                Some(Err(e)) if !j.cancelled => {
                    self.print_errors.insert(j.signature, e);
                }
                _ => {}
            }
        }
        let wanted: HashSet<String> = self
            .session
            .tracks
            .iter()
            .filter_map(|t| t.chain_signature(rate))
            .collect();
        for j in &mut self.jobs {
            if !j.cancelled && !wanted.contains(&j.signature) {
                j.job.cancel();
                j.cancelled = true;
            }
        }
        let busy = recording
            || self.recording.is_some()
            || ctx.input(|i| i.pointer.any_down())
            || ctx.egui_wants_keyboard_input();
        if !busy {
            let config = self.root.join("config");
            let cache = self.session.dir.join("prints");
            let auditioned = self.audition.as_ref().map(|a| a.track);
            for (ti, t) in self.session.tracks.iter().enumerate() {
                if Some(ti) == auditioned {
                    continue;
                }
                let running = self.jobs.iter().filter(|j| !j.cancelled).count();
                if running >= MAX_PRINT_JOBS {
                    break;
                }
                let (Some(sig), Some(k)) = (t.chain_signature(rate), t.active_take()) else {
                    continue;
                };
                if t.print_current(rate)
                    || self.print_errors.contains_key(&sig)
                    || self.jobs.iter().any(|j| !j.cancelled && j.signature == sig)
                {
                    continue;
                }
                let slots: Vec<Slot> = t.inserts.iter().filter(|s| !s.bypass).cloned().collect();
                self.jobs.push(PrintJob {
                    job: Job::spawn(
                        config.clone(),
                        slots,
                        k.audio.clone(),
                        rate,
                        Some(cache.clone()),
                    ),
                    signature: sig,
                    take: k.id.clone(),
                    cancelled: false,
                });
            }
        }
        if !self.jobs.is_empty() {
            ctx.request_repaint_after(Duration::from_millis(100));
        }
    }

    /// Insert `k` of track `t`'s state: its glyph, colour and what it says on hover.
    fn insert_state(&self, t: usize, k: usize) -> (String, Color32, String) {
        let track = &self.session.tracks[t];
        let rate = self.session.rate;
        let slot = &track.inserts[k];
        if slot.bypass {
            return ("⏻".into(), theme::FAINT, "bypassed".into());
        }
        let Some(sig) = track.chain_signature(rate) else {
            return ("".into(), theme::MUTED, "no take to print".into());
        };
        if let Some(e) = self.print_errors.get(&sig) {
            return ("!".into(), theme::FAULT, format!("the render failed: {e}"));
        }
        if let Some(j) = self
            .jobs
            .iter()
            .find(|j| !j.cancelled && j.signature == sig)
        {
            let stage = track.inserts[..k].iter().filter(|s| !s.bypass).count();
            let (at, f) = j.job.progress();
            return match stage.cmp(&at) {
                std::cmp::Ordering::Less => (
                    "✓".into(),
                    theme::OK,
                    "rendered for playback (still editable)".into(),
                ),
                std::cmp::Ordering::Equal => (
                    format!("◔ {:.0}%", f * 100.0),
                    theme::ACCENT,
                    "rendering for playback".into(),
                ),
                std::cmp::Ordering::Greater => (
                    "…".into(),
                    theme::MUTED,
                    "waiting for the inserts before it".into(),
                ),
            };
        }
        if track.print_current(rate) {
            (
                "✓".into(),
                theme::OK,
                "rendered for playback (still editable; ⤓ Render bakes it into a new take)".into(),
            )
        } else {
            (
                "…".into(),
                theme::WARN,
                "waiting to render (the older render plays meanwhile)".into(),
            )
        }
    }

    /// The selected insert, if it still exists.
    fn insert_selected(&self) -> Option<(usize, usize)> {
        self.insert_sel.filter(|&(t, k)| {
            self.session
                .tracks
                .get(t)
                .is_some_and(|x| k < x.inserts.len())
        })
    }

    /// A device's knobs (its circuit's controls), loaded once.
    fn knobs_for(&mut self, device: &str) -> Result<Vec<Knob>, String> {
        let config = self.root.join("config");
        self.knobs
            .entry(device.to_string())
            .or_insert_with(|| {
                let d = find_device(device).ok_or(format!("no device {device}"))?;
                let path = spec::circuit_path(&config, d.circuit).map_err(|e| e.to_string())?;
                let s = spec::load_circuit(&path).map_err(|e| e.to_string())?;
                Ok(vpanel::knobs(d, &s))
            })
            .clone()
    }

    /// `device` added at the end of track `t`'s chain, its panel opened. The first insert
    /// that isn't bypassed gets its trim from the take (the take's loudest stretch to the
    /// alignment level), set once.
    fn add_insert(&mut self, t: usize, device: &str) {
        let rate = self.session.rate;
        let Some(track) = self.session.tracks.get_mut(t) else {
            return;
        };
        let mut slot = Slot::new(device);
        if track.inserts.iter().all(|s| s.bypass)
            && let Some(k) = track.active_take()
        {
            let x: Vec<f64> = k.audio.iter().map(|&v| v as f64).collect();
            let level = audio::level_dbfs(&x, rate, 8.0);
            slot.trim_db = ((ALIGNMENT_DBFS - level).clamp(-40.0, 40.0) * 10.0).round() / 10.0;
        }
        track.inserts.push(slot);
        self.insert_sel = Some((t, track.inserts.len() - 1));
        self.audition_request = true;
        self.save();
    }

    /// The selected insert's panel: its gains, bypass, quality, place in the chain, knobs.
    fn insert_panel(&mut self, ui: &mut egui::Ui) {
        let Some((t, k)) = self.insert_selected() else {
            self.insert_sel = None;
            return;
        };
        let device = self.session.tracks[t].inserts[k].device.clone();
        let label = find_device(&device).map_or(device.clone(), |d| d.label.to_string());
        let (glyph, colour, state) = self.insert_state(t, k);
        let knobs = self.knobs_for(&device);
        let rate = self.session.rate;
        let mut changed = false;
        let mut remove = false;
        let mut render = false;
        let mut moved: Option<usize> = None;
        let n = self.session.tracks[t].inserts.len();
        let last_on = self.session.tracks[t]
            .inserts
            .iter()
            .rposition(|s| !s.bypass)
            == Some(k);
        // The take's and the print's levels, for Match.
        let levels = {
            let tr = &self.session.tracks[t];
            match (tr.active_take(), &tr.printed) {
                (Some(take), Some(p)) if tr.print_current(rate) => {
                    let a: Vec<f64> = take.audio.iter().map(|&v| v as f64).collect();
                    let b: Vec<f64> = p.audio.iter().map(|&v| v as f64).collect();
                    Some((
                        audio::level_dbfs(&a, rate, 8.0),
                        audio::level_dbfs(&b, rate, 8.0),
                    ))
                }
                _ => None,
            }
        };
        let track_name = self.session.tracks[t].name.clone();
        let live_line = match (&self.audition, self.audition_status.as_ref()) {
            (Some(_), Some(s)) => s.clone(),
            _ => "not playing live".to_string(),
        };
        ui.horizontal(|ui| {
            ui.label(
                RichText::new(format!("{track_name} · {label}"))
                    .strong()
                    .color(theme::INK),
            );
            ui.label(RichText::new(glyph).color(colour))
                .on_hover_text(&state);
            ui.label(RichText::new(&state).small().color(theme::MUTED));
            ui.add_space(12.0);
            ui.label(RichText::new(&live_line).small().color(theme::ACCENT))
                .on_hover_text(
                    "While this panel is open the device plays live on the track (Space plays \
                     the session); closing it renders the chain again for playback. The \
                     inserts after it \
                     aren't heard meanwhile.",
                );
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.button("✕").on_hover_text("Close the panel").clicked() {
                    self.insert_sel = None;
                }
                if ui.button("Remove").clicked() {
                    remove = true;
                }
                if ui
                    .add_enabled(
                        self.bake.is_none(),
                        egui::Button::new(RichText::new("⤓ Render track").color(theme::ACCENT)),
                    )
                    .on_hover_text(
                        "Render the track through its inserts at production quality into a new \
                         take, and remove the inserts (Undo brings them back)",
                    )
                    .clicked()
                {
                    render = true;
                }
                if ui
                    .add_enabled(k + 1 < n, egui::Button::new("▶"))
                    .on_hover_text("Later in the chain")
                    .clicked()
                {
                    moved = Some(k + 1);
                }
                if ui
                    .add_enabled(k > 0, egui::Button::new("◀"))
                    .on_hover_text("Earlier in the chain")
                    .clicked()
                {
                    moved = Some(k - 1);
                }
            });
        });
        ui.add_space(4.0);
        let slot = &mut self.session.tracks[t].inserts[k];
        let play_quality = find_device(&slot.device).map_or(Quality::Draft1x, |d| d.quality);
        ui.horizontal(|ui| {
            ui.label("Trim");
            changed |= ui
                .add(
                    egui::DragValue::new(&mut slot.trim_db)
                        .range(-40.0..=40.0)
                        .speed(0.1)
                        .max_decimals(1)
                        .suffix(" dB"),
                )
                .on_hover_text("The fader in front of the device: how hard the take drives it")
                .changed();
            ui.add_space(8.0);
            ui.label("Make-up");
            changed |= ui
                .add(
                    egui::DragValue::new(&mut slot.makeup_db)
                        .range(-40.0..=40.0)
                        .speed(0.1)
                        .max_decimals(1)
                        .suffix(" dB"),
                )
                .on_hover_text("The gain after the device")
                .changed();
            if last_on
                && let Some((a, b)) = levels
                && ui
                    .small_button("Match")
                    .on_hover_text(format!(
                        "Make-up so the chain's print is as loud as the take (take \
                         {a:.1} dBFS, print {b:.1} dBFS)"
                    ))
                    .clicked()
            {
                slot.makeup_db = ((slot.makeup_db + a - b) * 10.0).round() / 10.0;
                changed = true;
            }
            ui.add_space(8.0);
            ui.label("Wet");
            changed |= ui
                .add(
                    egui::DragValue::new(&mut slot.wet)
                        .range(0.0..=1.0)
                        .speed(0.01)
                        .custom_formatter(|v, _| format!("{:.0}%", v * 100.0)),
                )
                .on_hover_text(
                    "The device's share of the track (a console's wet / dry): 100% is the \
                     device only, less mixes in the track as it came",
                )
                .changed();
            ui.add_space(8.0);
            changed |= ui.checkbox(&mut slot.bypass, "Bypass").changed();
            ui.add_space(8.0);
            egui::ComboBox::from_id_salt(("insert_quality", t, k))
                .selected_text(slot.quality.name())
                .show_ui(ui, |ui| {
                    for q in [play_quality, Quality::Production] {
                        changed |= ui
                            .selectable_value(&mut slot.quality, q, q.name())
                            .changed();
                    }
                })
                .response
                .on_hover_text(
                    "The quality it prints at: its play quality while iterating, production \
                     for the final mix (several times slower)",
                );
        });
        ui.add_space(6.0);
        match knobs {
            Err(e) => {
                ui.colored_label(theme::FAULT, e);
            }
            Ok(knobs) => {
                ui.horizontal_wrapped(|ui| {
                    for knob in &knobs {
                        changed |= knob_ui(ui, knob, &mut slot.values, (t, k));
                    }
                });
            }
        }
        if let Some(to) = moved {
            let ins = &mut self.session.tracks[t].inserts;
            let s = ins.remove(k);
            ins.insert(to, s);
            self.insert_sel = Some((t, to));
            changed = true;
        }
        if remove {
            self.session.tracks[t].inserts.remove(k);
            self.insert_sel = None;
            changed = true;
        }
        if render {
            self.insert_sel = None;
            self.start_bake(t);
        }
        if changed {
            self.save();
        }
    }

    /// The row of insert chips under a track's strip (+ adds one).
    fn inserts_row(&mut self, ui: &mut egui::Ui, i: usize) -> bool {
        let mut changed = false;
        let mut bake = false;
        let mut add: Option<&'static str> = None;
        let mut action: Option<(usize, &'static str)> = None;
        ui.horizontal(|ui| {
            ui.spacing_mut().item_spacing.x = 4.0;
            for k in 0..self.session.tracks[i].inserts.len() {
                let slot = &self.session.tracks[i].inserts[k];
                let name = find_device(&slot.device).map_or(slot.device.clone(), |d| {
                    d.label.split(" (").next().unwrap_or(d.label).to_string()
                });
                let short = name.split_whitespace().last().unwrap_or(&name).to_string();
                let (glyph, colour, state) = self.insert_state(i, k);
                let selected = self.insert_selected() == Some((i, k));
                let bypass = self.session.tracks[i].inserts[k].bypass;
                let text = RichText::new(format!("{short} {glyph}"))
                    .small()
                    .color(if bypass { theme::FAINT } else { colour });
                let b = egui::Button::new(text)
                    .fill(if selected { theme::CHROME3 } else { theme::BG })
                    .stroke(Stroke::new(
                        1.0,
                        if selected { theme::ACCENT } else { theme::LINE },
                    ))
                    .min_size(egui::vec2(0.0, 18.0));
                let r = ui.add(b).on_hover_text(format!("{name}: {state}"));
                if r.clicked() {
                    self.insert_sel = if selected { None } else { Some((i, k)) };
                    self.audition_request = !selected;
                }
                r.context_menu(|ui| {
                    if ui
                        .button(if bypass { "Bypass off" } else { "Bypass" })
                        .clicked()
                    {
                        action = Some((k, "bypass"));
                        ui.close();
                    }
                    if ui.button("Remove").clicked() {
                        action = Some((k, "remove"));
                        ui.close();
                    }
                });
            }
            ui.menu_button(RichText::new("+").small(), |ui| {
                for d in DEVICES.iter().filter(|d| !d.plays_own_oscillator()) {
                    if ui.button(d.label).clicked() {
                        add = Some(d.id);
                        ui.close();
                    }
                }
            })
            .response
            .on_hover_text(
                "Add a device to this track's chain (rendered in the background for \
                 playback; open it to hear it live while you turn it)",
            );
            if self.session.tracks[i].inserts.iter().any(|s| !s.bypass) {
                match &self.bake {
                    Some(b) if b.track == i => {
                        let (at, f) = b.job.progress();
                        let pct = (at as f64 + f) / b.slots.len().max(1) as f64 * 100.0;
                        ui.label(
                            RichText::new(format!("⤓ {pct:.0}%"))
                                .small()
                                .color(theme::ACCENT),
                        )
                        .on_hover_text("Rendering into a new take at production quality");
                        if ui
                            .small_button("✕")
                            .on_hover_text("Cancel the render")
                            .clicked()
                        {
                            b.job.cancel();
                        }
                    }
                    _ => {
                        if ui
                            .add_enabled(
                                self.bake.is_none() && self.recording.is_none(),
                                egui::Button::new(RichText::new("⤓ Render").small()),
                            )
                            .on_hover_text(
                                "Render this track through its inserts at production quality \
                                 into a new take, and remove the inserts (the effect is baked \
                                 in; the old take stays in the lane, Undo brings the inserts \
                                 back)",
                            )
                            .clicked()
                        {
                            bake = true;
                        }
                    }
                }
            }
        });
        if bake {
            self.start_bake(i);
        }
        if let Some((k, what)) = action {
            let ins = &mut self.session.tracks[i].inserts;
            if what == "bypass" {
                ins[k].bypass = !ins[k].bypass;
            } else {
                ins.remove(k);
                if self.insert_sel.is_some_and(|(t, _)| t == i) {
                    self.insert_sel = None;
                }
            }
            changed = true;
        }
        if let Some(d) = add {
            self.add_insert(i, d);
            changed = true;
        }
        changed
    }

    /// Render track `t`'s chain (its inserts not bypassed, at production) into a new take.
    fn start_bake(&mut self, t: usize) {
        if self.bake.is_some() {
            self.error = Some("one render at a time".into());
            return;
        }
        let Some(track) = self.session.tracks.get(t) else {
            return;
        };
        let Some(take) = track.active_take() else {
            self.error = Some("the track has no take to render".into());
            return;
        };
        let slots: Vec<Slot> = track
            .inserts
            .iter()
            .filter(|s| !s.bypass)
            .map(|s| Slot {
                quality: Quality::Production,
                ..s.clone()
            })
            .collect();
        if slots.is_empty() {
            return;
        }
        let job = Job::spawn(
            self.root.join("config"),
            slots.clone(),
            take.audio.clone(),
            self.session.rate,
            Some(self.session.dir.join("prints")),
        );
        self.bake = Some(Bake {
            track: t,
            take: take.id.clone(),
            slots,
            job,
        });
        self.error = None;
    }

    /// A finished render: a new take on its track (where its source sits), the inserts it
    /// went through removed.
    fn poll_bake(&mut self) {
        if !self.bake.as_ref().is_some_and(|b| b.job.is_finished()) {
            return;
        }
        let b = self.bake.take().expect("a render");
        let audio = match b.job.join() {
            Some(Ok(prints)) => match prints.last() {
                Some(p) => (*p.audio).clone(),
                None => return,
            },
            Some(Err(e)) => {
                if e != "cancelled" && !e.contains("cancelled") {
                    self.error = Some(format!("the render failed: {e}"));
                }
                return;
            }
            None => return,
        };
        let Some(pos) = self
            .session
            .tracks
            .get(b.track)
            .and_then(|t| t.takes.iter().find(|k| k.id == b.take))
            .map(|k| k.position)
        else {
            self.error = Some("the rendered take's track or source take is gone".into());
            return;
        };
        let from = json!({
            "take": b.take,
            "inserts": b.slots.iter().map(Slot::to_json).collect::<Vec<_>>(),
            "quality": Quality::Production.name(),
            "code": circuitsim::SOURCE_HASH,
        });
        self.saved = true;
        match self.session.add_rendered_take(b.track, audio, pos, from) {
            Ok(_) => {
                self.session.tracks[b.track].inserts.retain(|s| s.bypass);
                if self.insert_sel.is_some_and(|(t, _)| t == b.track) {
                    self.insert_sel = None;
                }
                self.save();
            }
            Err(e) => self.error = Some(e),
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
            let printed = track
                .playing(self.session.rate)
                .is_some_and(|p| p.2)
                .then_some(track.printed.as_ref())
                .flatten();
            let (len, overview) = match printed {
                Some(p) => (p.audio.len(), &p.overview),
                None => (k.audio.len(), &k.overview),
            };
            draw_clip(
                &lp,
                lane,
                view,
                k.position,
                len,
                overview,
                colour,
                &if printed.is_some() {
                    format!("{} · with inserts", k.id)
                } else {
                    k.id.clone()
                },
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
        changed |= self.inserts_row(&mut child, i);
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
/// A knob of an insert's panel as an egui widget, its value in `values` (the circuit's
/// default while it isn't there). Returns whether it changed.
fn knob_ui(
    ui: &mut egui::Ui,
    knob: &Knob,
    values: &mut Vec<(String, YValue)>,
    id: (usize, usize),
) -> bool {
    let cur = values
        .iter()
        .find(|(k, _)| *k == knob.key)
        .map_or(knob.default.clone(), |(_, v)| v.clone());
    let mut set: Option<YValue> = None;
    ui.vertical(|ui| {
        ui.label(RichText::new(&knob.label).small().color(theme::MUTED));
        match &knob.kind {
            Kind::Range { min, max } => {
                let mut x = cur.as_f64().unwrap_or(*min);
                if ui
                    .add(egui::Slider::new(&mut x, *min..=*max).max_decimals(3))
                    .changed()
                {
                    set = Some(YValue::Float(x));
                }
            }
            Kind::Steps { min, max, int } => {
                let mut x = cur.as_f64().unwrap_or(*min);
                if ui
                    .add(egui::Slider::new(&mut x, *min..=*max).step_by(1.0))
                    .changed()
                {
                    set = Some(if *int {
                        YValue::Int(x.round() as i64)
                    } else {
                        YValue::Float(x)
                    });
                }
            }
            Kind::Choices(choices) => {
                egui::ComboBox::from_id_salt(("knob", id.0, id.1, knob.key.as_str()))
                    .selected_text(cur.py_str())
                    .show_ui(ui, |ui| {
                        for c in choices {
                            if ui.selectable_label(cur.py_eq(c), c.py_str()).clicked() {
                                set = Some(c.clone());
                            }
                        }
                    });
            }
        }
    });
    match set {
        Some(v) => {
            match values.iter_mut().find(|(k, _)| *k == knob.key) {
                Some(e) => e.1 = v,
                None => values.push((knob.key.clone(), v)),
            }
            true
        }
        None => false,
    }
}

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
