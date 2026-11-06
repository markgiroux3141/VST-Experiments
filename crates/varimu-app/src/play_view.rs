//! The Play view: a device, a file and its loop region, the front panel and meters
//! (R2; the web `/play` page's counterpart). Plays at draft-1x through
//! `varimu_app::player`; knobs reach the player as they turn.
//!
//! R3b: the editor's drawing is a device too (`set_drawing`): each edit that compiles
//! reaches the player as a new circuit (a value updates the stream in place, a change
//! of topology restarts it).
//!
//! The sampler (`crate::sampler_view`) is an instrument here too: chosen as the device, the
//! left column holds its kit and the main area a browser of `samples/`.
//!
//! A device can go at the chain's end (`panel::CHAIN_ENDS`, the plate reverb): after the
//! device, on threads of its own (`player::EndDevice`), its knobs under CHAIN END.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::time::{Duration, Instant};

use eframe::egui::{self, Color32, RichText, Stroke};
use varimu_app::audio;
use varimu_app::live::Circuit;
use varimu_app::midi::{self, Keyboard, MOD_WHEEL, Touch, Wave};
use varimu_app::panel::{self, DEVICES, Device, Kind, Knob};
use varimu_app::player::{
    AHEAD_S, END_MIX, EndDevice, INPUT_BUFFER_S, InputDevice, Playback, Player, ProxyStart, Source,
    State, input_devices,
};
use varimu_app::prefs::{ALIGNMENT_DBFS, KeyTouch, Prefs};
use varimu_app::render::{Rendered, render};
use varimu_app::settings::{Quality, Settings};
use varimu_circuit::Library;
use varimu_circuit::spec::CircuitSpec;
use varimu_circuit::yaml::Value;

use crate::sampler_view::{SamplerPanel, Wants};
use crate::theme;

/// Waveform overview columns.
const OVERVIEW: usize = 1200;
/// A new file's loop region (s): its loudest stretch this long.
const DEFAULT_REGION_S: f64 = 8.0;
/// The shortest loop region (s).
const MIN_REGION_S: f64 = 0.25;

/// A loaded file.
struct Clip {
    path: PathBuf,
    /// Mono at the project's rate.
    samples: Vec<f64>,
    rate: u32,
    /// Min and max per overview column.
    overview: Vec<(f32, f32)>,
    /// Its loudest stretch (the default loop region) and that stretch's level (dBFS,
    /// sine-equivalent rms: rms * sqrt 2, as the output meter reads).
    loudest: (f64, f64),
    level_dbfs: f64,
}

impl Clip {
    fn seconds(&self) -> f64 {
        self.samples.len() as f64 / self.rate as f64
    }
}

fn overview(x: &[f64]) -> Vec<(f32, f32)> {
    let per = x.len().div_ceil(OVERVIEW).max(1);
    x.chunks(per)
        .map(|c| {
            c.iter().fold((f32::MAX, f32::MIN), |(lo, hi), &v| {
                (lo.min(v as f32), hi.max(v as f32))
            })
        })
        .collect()
}

/// A production render running on a thread of its own.
struct RenderTask {
    /// Fraction done (f64 bits).
    progress: Arc<AtomicU64>,
    cancel: Arc<AtomicBool>,
    /// The render and where it was saved (None: saving failed).
    result: Receiver<Result<(Rendered, Option<PathBuf>), String>>,
    started: Instant,
    label: String,
}

/// The editor's drawing as a device: its compiled circuit.
#[derive(Clone)]
pub struct DrawingDevice {
    /// The drawing's name (its circuit's, once saved).
    pub name: String,
    pub title: String,
    /// The view it comes from, for the menu ("Editor", "Components").
    pub origin: &'static str,
    pub spec: CircuitSpec,
    pub lib: Arc<Library>,
    /// Audio kept ahead of playback (s): `AHEAD_S`, or a Play device's for its circuit
    /// (the Components view: the 5E3's heavy blocks).
    pub ahead_s: f64,
}

/// The drawing's panel: every control but the mains settings.
const DRAWING: Device = Device {
    id: "drawing",
    label: "The editor's drawing",
    short: "Drawing",
    about: "The editor's drawing, as it is now: edits are heard as they are made",
    group: panel::Group::Retired,
    circuit: "",
    panel: None,
    ahead_s: AHEAD_S,
    quality: Quality::Draft1x,
    cores: None,
    mod_wheel: None,
    gate: None,
    velocity: None,
    pitch: None,
    own_oscillator: false,
    key: None,
    partition: None,
    coupling: None,
    pitch2: None,
    live_speaker_v: None,
    newton: None,
};

/// A finished render: where it was saved and what it was.
struct Done {
    rendered: Rendered,
    path: Option<PathBuf>,
    label: String,
}

pub struct PlayView {
    config_dir: PathBuf,
    clips_dir: PathBuf,
    /// The user's settings (source folders), and the sources found: per group (a
    /// folder of files), its label and files.
    prefs: Prefs,
    sources: Vec<(String, Vec<PathBuf>)>,
    settings: Result<Settings, String>,
    /// The settings at each device's quality (its `quality`: draft-1x, draft-2x).
    by_quality: Vec<(Quality, Result<Settings, String>)>,
    /// An index into DEVICES, or DEVICES.len(): the editor's drawing.
    device: usize,
    drawing: Option<DrawingDevice>,
    knobs: Vec<Knob>,
    clip: Option<Clip>,
    loading: Option<(PathBuf, Receiver<Result<Clip, String>>)>,
    /// The loop region (s).
    region: (f64, f64),
    /// Where a drag on the overview started (s).
    drag_from: Option<f64>,
    player: Option<Player>,
    /// The player is the Session view's (an insert auditioned), not this view's device.
    adopted: bool,
    /// The region and device the player plays (a change restarts it).
    playing: Option<((f64, f64), usize, PathBuf)>,
    /// Start playing once the file being loaded is in.
    autoplay: bool,
    task: Option<RenderTask>,
    done: Option<Done>,
    playback: Option<Playback>,
    /// Live input instead of the file: the device, channel and starting queue.
    live_input: bool,
    inputs: Vec<InputDevice>,
    input: usize,
    channel: usize,
    input_buffer_ms: f64,
    /// The keys' velocity range (dB; a device with a velocity table), and whether
    /// velocity plays at all (off: every key at full level, the range kept).
    velocity_db: f64,
    velocity_on: bool,
    /// Multi-trigger: a new key while another is held restarts the envelope.
    retrigger: bool,
    /// The device's keys strike a medium with a velocity law of its own (the Rhodes harp),
    /// and that law's span (dB from velocity 127 to 1), read when it starts (None: not yet).
    has_harp: bool,
    key_span_db: Option<f64>,
    /// The keyboard's touch changed and isn't saved yet (saved once the slider is let go).
    touch_dirty: bool,
    /// A MIDI keyboard instead (live, `live_input` set too): its ports, the one chosen,
    /// the test oscillator's waveform, the keyboard while playing, and how many mod
    /// wheel messages have been applied.
    midi: bool,
    midi_ports: Vec<String>,
    midi_port: usize,
    wave: Wave,
    keyboard: Option<Keyboard>,
    wheel_seen: u64,
    /// The last take, saved (it is then the file).
    take_saved: Option<PathBuf>,
    /// Input trim (dB) on top of the normalization.
    trim_db: f64,
    /// The device bypassed (its input played), and gain compensation on (monitoring).
    bypass: bool,
    /// The device's noise sources on (device builder B5; only devices whose file has
    /// them): off by default (the user's call), which saves their CPU. Renders follow it.
    noise: bool,
    /// The next start is a power-on (heated cathodes cold), then back to warm (B6).
    power_on: bool,
    /// Whether the chosen device's file has noise sources / heated cathodes (read with its
    /// knobs: the switches show only then).
    has_noise: bool,
    has_heaters: bool,
    compensate: bool,
    /// A manual gain on the device's output (dB, monitoring only).
    output_db: f64,
    /// The device at the chain's end (an index into DEVICES, one of `panel::CHAIN_ENDS`),
    /// its knobs and its share of the output.
    end: Option<usize>,
    end_knobs: Vec<Knob>,
    end_mix: f64,
    /// The sampler is the instrument (the device chosen stays as it was underneath), and
    /// its kit and browser.
    sampler_on: bool,
    kit: SamplerPanel,
    /// The Components view's A / B: a fixed trim (dB) on the device's output, measured
    /// offline, with the running compensation off while it is set (it would undo the
    /// difference the trim matches).
    ab_trim_db: Option<f64>,
    /// The keys play the device's proxy (docs/MIDI_TAKES_PLAN.md N2) in its place: the
    /// choice, the device's tables (None: it has no proxy), and whether the player playing
    /// is the proxy.
    proxy_on: bool,
    proxy_tables: Option<Arc<varimu_app::proxy::Tables>>,
    playing_proxy: bool,
    error: Option<String>,
}

/// What the command line asks for:
/// `varimu-app [FILE] [--play] [--device ID] [--input NAME [--channel N]] [--midi NAME]
/// [--edit NAME]` (`--midi`: a MIDI keyboard, the first port named like NAME).
#[derive(Debug, Default)]
pub struct Args {
    pub file: Option<PathBuf>,
    pub play: bool,
    pub device: Option<String>,
    /// Live input from this device (and channel, from 1).
    pub input: Option<String>,
    pub channel: usize,
    /// A MIDI keyboard (the first port whose name contains this).
    pub midi: Option<String>,
    /// Open the editor on this drawn circuit.
    pub edit: Option<String>,
    /// Open the Components view on this component (`NAME` or `NAME@N`).
    pub component: Option<String>,
    /// Open the Room view.
    pub room: bool,
}

impl Args {
    pub fn parse(args: impl Iterator<Item = String>) -> Result<Args, String> {
        let mut a = Args::default();
        let mut it = args.skip(1);
        while let Some(x) = it.next() {
            match x.as_str() {
                "--play" => a.play = true,
                "--room" => a.room = true,
                "--device" => a.device = Some(it.next().ok_or("--device needs an id")?),
                "--edit" => a.edit = Some(it.next().ok_or("--edit needs a circuit name")?),
                "--component" => {
                    a.component = Some(it.next().ok_or("--component needs a component name")?);
                }
                "--input" => a.input = Some(it.next().ok_or("--input needs a device name")?),
                "--midi" => a.midi = Some(it.next().ok_or("--midi needs a port name")?),
                "--channel" => {
                    let c = it.next().ok_or("--channel needs a number")?;
                    a.channel = c.parse().map_err(|_| format!("--channel {c}"))?;
                }
                s if s.starts_with("--") => return Err(format!("unknown option {s}")),
                _ => a.file = Some(PathBuf::from(x)),
            }
        }
        Ok(a)
    }
}

impl PlayView {
    pub fn new(config_dir: PathBuf, args: Args) -> PlayView {
        let clips_dir = config_dir.parent().map_or_else(
            || PathBuf::from("data/clips"),
            |r| r.join("data").join("clips"),
        );
        let settings = Settings::load(&config_dir, Quality::Draft1x);
        let repo = config_dir
            .parent()
            .map_or_else(|| PathBuf::from("."), Path::to_path_buf);
        let mut by_quality: Vec<(Quality, Result<Settings, String>)> = Vec::new();
        for q in DEVICES.iter().chain([&DRAWING]).map(|d| d.quality) {
            if !by_quality.iter().any(|(x, _)| *x == q) {
                by_quality.push((q, Settings::load(&config_dir, q)));
            }
        }
        let mut v = PlayView {
            config_dir,
            clips_dir,
            prefs: Prefs::load(),
            sources: Vec::new(),
            settings,
            by_quality,
            device: 0,
            drawing: None,
            knobs: Vec::new(),
            clip: None,
            loading: None,
            region: (0.0, 0.0),
            drag_from: None,
            player: None,
            adopted: false,
            playing: None,
            autoplay: args.play,
            task: None,
            done: None,
            playback: None,
            live_input: false,
            inputs: Vec::new(),
            input: 0,
            channel: 0,
            input_buffer_ms: INPUT_BUFFER_S * 1000.0,
            velocity_db: panel::VELOCITY_RANGE_DB,
            velocity_on: true,
            retrigger: true,
            has_harp: false,
            key_span_db: None,
            touch_dirty: false,
            midi: false,
            midi_ports: Vec::new(),
            midi_port: 0,
            wave: Wave::Saw,
            keyboard: None,
            wheel_seen: 0,
            take_saved: None,
            trim_db: 0.0,
            bypass: false,
            noise: false,
            power_on: false,
            has_noise: false,
            has_heaters: false,
            compensate: true,
            output_db: 0.0,
            end: None,
            end_knobs: Vec::new(),
            end_mix: END_MIX,
            sampler_on: false,
            kit: SamplerPanel::new(&repo),
            ab_trim_db: None,
            proxy_on: false,
            proxy_tables: None,
            playing_proxy: false,
            error: None,
        };
        if let Some(id) = &args.device {
            match DEVICES.iter().position(|d| d.id == id.as_str()) {
                Some(i) => v.device = i,
                None if id == "sampler" => v.sampler_on = true,
                None => v.error = Some(format!("unknown device {id}")),
            }
        }
        v.load_knobs();
        v.scan_sources();
        if let Some(name) = &args.input {
            v.live_input = true;
            v.inputs = input_devices();
            match v.inputs.iter().position(|d| &d.name == name) {
                Some(i) => v.input = i,
                None => v.error = Some(format!("no input device {name}")),
            }
            v.channel = args.channel.saturating_sub(1);
            if args.play && v.error.is_none() {
                v.start();
            }
        }
        if let Some(name) = &args.midi {
            v.live_input = true;
            v.midi = true;
            v.midi_ports = midi::ports().unwrap_or_default();
            let want = name.to_lowercase();
            match v
                .midi_ports
                .iter()
                .position(|p| p.to_lowercase().contains(&want))
            {
                Some(i) => v.midi_port = i,
                None => v.error = Some(format!("no MIDI input named like {name}")),
            }
            if args.play && v.error.is_none() {
                v.start();
            }
        }
        if let Some(f) = args.file {
            v.open(f);
        }
        v
    }

    /// The normalization's gain (dB) for the file: its loudest stretch to the target
    /// (live input: none), within +-40 dB (a silent file stays silent).
    fn normalize_db(&self) -> f64 {
        match (self.prefs.normalize_dbfs, &self.clip) {
            (Some(target), Some(c)) if !self.live_input => {
                (target - c.level_dbfs).clamp(-40.0, 40.0)
            }
            _ => 0.0,
        }
    }

    /// The input gain (linear): normalization and trim.
    fn gain(&self) -> f64 {
        10f64.powf((self.normalize_db() + self.trim_db) / 20.0)
    }

    /// Normalization and trim: the source's level into the unit.
    fn level_ui(&mut self, ui: &mut egui::Ui) {
        Self::heading(ui, "INPUT LEVEL");
        let before = self.prefs.normalize_dbfs;
        if !self.live_input {
            ui.horizontal(|ui| {
                let mut on = self.prefs.normalize_dbfs.is_some();
                ui.checkbox(&mut on, "Normalize to")
                    .on_hover_text(
                        "Bring the file's loudest 8 s to this level (sine-equivalent rms). \
                         -18 dBFS = +4 dBu, the studio alignment the 670's factory adjustment assumes.",
                    );
                let mut t = self.prefs.normalize_dbfs.unwrap_or(ALIGNMENT_DBFS);
                ui.add_enabled(
                    on,
                    egui::DragValue::new(&mut t).range(-40.0..=0.0).speed(0.2).suffix(" dBFS"),
                );
                self.prefs.normalize_dbfs = on.then_some(t);
            });
            if let Some(c) = &self.clip {
                ui.label(
                    RichText::new(format!(
                        "file at {:.1} dBFS (its loudest 8 s) · normalize {:+.1} dB",
                        c.level_dbfs,
                        self.normalize_db()
                    ))
                    .small()
                    .color(theme::MUTED),
                );
            }
        }
        ui.horizontal(|ui| {
            ui.label(RichText::new("Trim").color(theme::MUTED));
            ui.add(
                egui::Slider::new(&mut self.trim_db, -24.0..=24.0)
                    .step_by(0.5)
                    .suffix(" dB"),
            );
        });
        ui.label(
            RichText::new(format!("input gain {:+.1} dB", 20.0 * self.gain().log10()))
                .small()
                .color(theme::INK),
        );
        if self.prefs.normalize_dbfs != before {
            self.save_prefs();
        }
    }

    /// data/clips, then each source folder (a group per folder holding files).
    fn scan_sources(&mut self) {
        let mut groups = Vec::new();
        let clips = list_audio(&self.clips_dir);
        if !clips.is_empty() {
            groups.push(("data/clips".to_string(), clips));
        }
        for root in &self.prefs.source_folders {
            scan_folder(root, root, &mut groups);
        }
        self.sources = groups;
    }

    fn save_prefs(&mut self) {
        if let Err(e) = self.prefs.save() {
            self.error = Some(format!("can't save the settings: {e}"));
        }
    }

    fn load_knobs(&mut self) {
        self.proxy_tables = DEVICES
            .get(self.device)
            .filter(|_| self.drawing_device().is_none())
            .and_then(|d| {
                varimu_app::proxy::Tables::load(&self.config_dir, d.id)
                    .ok()
                    .flatten()
            })
            .map(Arc::new);
        if let Some(d) = self.drawing_device() {
            let k = panel::knobs(&DRAWING, &d.spec);
            let flags = (d.spec.noise.is_some(), d.spec.heaters.is_some());
            (self.has_harp, self.key_span_db) = (has_harp_part(&d.spec), None);
            self.knobs = k;
            (self.has_noise, self.has_heaters) = flags;
            return;
        }
        let dev = &DEVICES[self.device];
        match varimu_circuit::spec::circuit_path(&self.config_dir, dev.circuit)
            .and_then(|p| varimu_circuit::spec::load_circuit(&p))
        {
            Ok(spec) => {
                self.knobs = panel::knobs(dev, &spec);
                (self.has_noise, self.has_heaters) = (spec.noise.is_some(), spec.heaters.is_some());
                (self.has_harp, self.key_span_db) = (has_harp_part(&spec), None);
            }
            Err(e) => self.error = Some(e.to_string()),
        }
    }

    /// The drawing, when it is the device.
    fn drawing_device(&self) -> Option<&DrawingDevice> {
        self.drawing
            .as_ref()
            .filter(|_| self.device == DEVICES.len())
    }

    /// The device's circuit, built with `cores`, its noise as the switch says, its gas
    /// thyratrons' event kernels as its quality's settings say.
    fn circuit(&self, cores: varimu_circuit::Cores) -> Result<Circuit, String> {
        let c = match self.drawing_device() {
            Some(d) => Circuit::from_spec(d.lib.clone(), d.spec.clone(), cores),
            None => Circuit::load(&self.config_dir, DEVICES[self.device].circuit, cores)?,
        };
        let heaters = if self.power_on {
            varimu_circuit::Heaters::Cold
        } else {
            varimu_circuit::Heaters::File
        };
        // Its event kernels as its quality says (technique K: the live qualities').
        let dev = DEVICES.get(self.device).unwrap_or(&DRAWING);
        let events = self.settings_for(dev).is_ok_and(|s| s.events);
        Ok(dev
            .live(c)
            .with_noise(self.noise)
            .with_heaters(heaters)
            .with_events(events))
    }

    /// The device's name and id (for files).
    fn device_names(&self) -> (String, String) {
        if self.sampler_on {
            return ("Sampler".into(), "sampler".into());
        }
        match self.drawing_device() {
            Some(d) => (format!("{}: {}", d.origin, d.title), d.name.clone()),
            None => {
                let dev = &DEVICES[self.device];
                (dev.label.to_string(), dev.id.to_string())
            }
        }
    }

    /// The editor's drawing, compiled. When it is the device, the playing circuit
    /// follows it; knobs keep their values unless the drawing changed their default.
    /// (A drawing that can't be heard isn't passed: the last one plays on.)
    pub fn set_drawing(&mut self, d: DrawingDevice) {
        let was = self.drawing.replace(d.clone());
        if self.device != DEVICES.len() {
            return;
        }
        let old = std::mem::take(&mut self.knobs);
        let old_defaults = was
            .map(|w| panel::knobs(&DRAWING, &w.spec))
            .unwrap_or_default();
        self.knobs = panel::knobs(&DRAWING, &d.spec);
        for k in &mut self.knobs {
            let kept = old.iter().find(|o| o.key == k.key);
            let same_default = old_defaults
                .iter()
                .any(|o| o.key == k.key && o.default.py_eq(&k.default) && o.kind == k.kind);
            if let Some(o) = kept
                && same_default
            {
                k.value = o.value.clone();
            }
        }
        if let (Some(p), Ok(s)) = (&self.player, &self.settings)
            && let Ok(cores) = s.cores()
        {
            p.set_circuit(
                Circuit::from_spec(d.lib.clone(), d.spec.clone(), cores).with_noise(self.noise),
                panel::values(&self.knobs),
            );
        }
    }

    /// Play the drawing through the file's loop region (the first clip when none is
    /// open), or stop it.
    pub fn toggle_drawing(&mut self) {
        if self.drawing_playing() {
            self.stop();
            return;
        }
        if self.drawing.is_none() {
            self.error =
                Some("the drawing can't be heard: it needs to compile and have an out node".into());
            return;
        }
        if self.device != DEVICES.len() {
            self.device = DEVICES.len();
            self.load_knobs();
        }
        self.live_input = false;
        if self.clip.is_some() {
            self.start();
        } else if self.loading.is_none() {
            match self.sources.first().and_then(|(_, f)| f.first()).cloned() {
                Some(p) => {
                    self.autoplay = true;
                    self.open(p);
                }
                None => self.error = Some("no audio file to play: open one in Play".into()),
            }
        } else {
            self.autoplay = true;
        }
    }

    /// Whether the drawing is what plays.
    pub fn drawing_playing(&self) -> bool {
        self.player.is_some() && self.device == DEVICES.len()
    }

    /// A line on what plays, for the editor's listen bar.
    pub fn listen_line(&self) -> String {
        let file = self
            .clip
            .as_ref()
            .and_then(|c| c.path.file_name())
            .map_or("no file".into(), |n| n.to_string_lossy().into_owned());
        let (a, b) = self.region;
        let mut line = format!("{file} · {a:.1}-{b:.1} s");
        if let Some(p) = self
            .player
            .as_ref()
            .filter(|_| self.device == DEVICES.len())
        {
            let st = p.status();
            match &st.state {
                State::Starting => line.push_str(" · settling…"),
                State::Failed(e) => line = format!("{line} · stopped: {e}"),
                State::Playing => {
                    line.push_str(&format!(" · load {:.0}%", st.load * 100.0));
                    if st.restarts > 0 {
                        line.push_str(&format!(" · {} restarts", st.restarts));
                    }
                    if let Some(e) = &st.build_error {
                        line = format!("{line} · build: {e}");
                    }
                }
            }
        } else if self.loading.is_some() {
            line.push_str(" · loading…");
        }
        if let Some(e) = &self.error {
            line = format!("{line} · {e}");
        }
        line
    }

    /// The player, while a device plays (the Session view runs its transport).
    pub fn player(&self) -> Option<&Player> {
        self.player.as_ref()
    }

    /// Start the chosen device from the chosen source, as Play's ▶ does.
    pub fn start_device(&mut self) {
        self.adopted = false;
        self.start();
    }

    /// Play `p` (the Session view's audition of an insert) in place of this view's device,
    /// which stops: one output, one live device.
    pub fn adopt(&mut self, p: Player) {
        self.stop();
        self.player = Some(p);
        self.adopted = true;
    }

    /// Stop an adopted player (this view's own device stays as it is).
    pub fn release(&mut self) {
        if self.adopted {
            self.player = None;
            self.adopted = false;
        }
    }

    /// Whether the player playing is the Session view's.
    pub fn adopted(&self) -> bool {
        self.adopted
    }

    /// The chosen device: its label and id (a take records the id).
    pub fn device_label_id(&self) -> (String, String) {
        self.device_names()
    }

    /// Whether this view's player plays a device from the MIDI keyboard (a take recorded
    /// from it is an event take: docs/MIDI_TAKES_PLAN.md N1).
    pub fn plays_keys(&self) -> bool {
        self.player.is_some()
            && !self.adopted
            && self.live_input
            && self.midi
            && !self.sampler_on
            && self.keyboard.is_some()
            && self.device < DEVICES.len()
    }

    /// Whether the chosen device has a proxy (its measured tables).
    pub fn has_proxy(&self) -> bool {
        self.proxy_tables.is_some()
    }

    /// Whether the player playing is the device's proxy.
    pub fn monitor_proxy(&self) -> bool {
        self.player.is_some() && !self.adopted && self.playing_proxy
    }

    /// Monitor through the proxy (on) or the device; a keyboard playing restarts on the
    /// other.
    pub fn set_monitor_proxy(&mut self, on: bool) {
        if on == self.proxy_on {
            return;
        }
        self.proxy_on = on;
        if self.plays_keys() {
            self.start();
        }
    }

    /// A key pressed (`on`) or let go on the keyboard playing, as if played (a piano roll's
    /// preview of a note). Nothing while no keyboard plays.
    pub fn preview_key(&self, note: u8, velocity: u8, on: bool) {
        if let Some(kb) = &self.keyboard {
            let m = if on {
                [0x90, note & 127, velocity.clamp(1, 127)]
            } else {
                [0x80, note & 127, 0]
            };
            kb.keys.message(&m);
        }
    }

    /// What Play does every frame for a device played live, while another view is shown:
    /// the mod wheel turns its knob.
    pub fn live_controls(&mut self) {
        self.follow_mod_wheel();
    }

    /// The input gain and the monitor (bypass, compensation, output gain) to the player:
    /// every frame Play is shown, and after the Session view's calibration muted it.
    pub fn apply_monitor(&self) {
        if let Some(p) = &self.player {
            p.set_gain(self.gain());
            p.set_bypass(self.bypass);
            p.set_compensation(self.compensate && self.ab_trim_db.is_none());
            p.set_output_db(self.output_db + self.ab_trim_db.unwrap_or(0.0));
            if !self.adopted {
                p.set_end_mix(self.end_mix);
            }
        }
    }

    /// The Components view's A / B trim (dB; None: off, the compensation as chosen).
    pub fn set_ab_trim(&mut self, db: Option<f64>) {
        self.ab_trim_db = db;
        self.apply_monitor();
    }

    /// The loop region's input as the device gets it (the input gain applied), at most
    /// `max_s` of it: what a loudness match renders.
    pub fn match_input(&self, max_s: f64) -> Option<Vec<f64>> {
        let mut x = self.region_samples()?;
        let rate = self.clip.as_ref()?.rate as f64;
        x.truncate((max_s * rate) as usize);
        let g = self.gain();
        x.iter_mut().for_each(|v| *v *= g);
        (!x.is_empty()).then_some(x)
    }

    /// The drawing's knobs as overrides (its panel as set in Play).
    pub fn drawing_values(&self) -> varimu_app::live::Values {
        if self.drawing_device().is_some() {
            panel::values(&self.knobs)
        } else {
            Vec::new()
        }
    }

    /// The settings the drawing plays at (draft-1x).
    pub fn drawing_settings(&self) -> Result<Settings, String> {
        self.settings_for(&DRAWING)
    }

    /// Keep the view's background work going (the editor view calls this when Play
    /// isn't shown).
    pub fn tick(&mut self, ctx: &egui::Context) {
        self.poll_loading();
        if self.player.is_some() || self.loading.is_some() {
            ctx.request_repaint_after(Duration::from_millis(100));
        }
    }

    fn open(&mut self, path: PathBuf) {
        let Ok(s) = &self.settings else { return };
        let rate = s.sample_rate;
        let (tx, rx) = mpsc::channel();
        let p = path.clone();
        std::thread::spawn(move || {
            let r = audio::load(&p, rate).map(|samples| {
                let loud = audio::loudest(&samples, rate, DEFAULT_REGION_S);
                let (i, j) = (
                    (loud.0 * rate as f64) as usize,
                    (loud.1 * rate as f64) as usize,
                );
                let w = &samples[i.min(samples.len())..j.min(samples.len())];
                let rms = (w.iter().map(|v| v * v).sum::<f64>() / w.len().max(1) as f64).sqrt();
                Clip {
                    overview: overview(&samples),
                    path: p.clone(),
                    loudest: loud,
                    level_dbfs: 20.0 * (rms * 2f64.sqrt()).max(1e-12).log10(),
                    samples,
                    rate,
                }
            });
            let _ = tx.send(r);
        });
        self.loading = Some((path, rx));
    }

    fn poll_loading(&mut self) {
        let Some((_, rx)) = &self.loading else { return };
        match rx.try_recv() {
            Ok(Ok(clip)) => {
                // A default region: the loudest 8 s (stems often start silent), as
                // the listening pool's excerpts.
                self.region = clip.loudest;
                self.clip = Some(clip);
                self.loading = None;
                self.error = None;
                if (self.player.is_some() && !self.live_input && !self.adopted)
                    || std::mem::take(&mut self.autoplay)
                {
                    self.start();
                }
            }
            Ok(Err(e)) => {
                self.error = Some(e);
                self.loading = None;
            }
            Err(mpsc::TryRecvError::Empty) => {}
            Err(mpsc::TryRecvError::Disconnected) => self.loading = None,
        }
    }

    /// The loop region's samples (at the project's rate).
    fn region_samples(&self) -> Option<Vec<f64>> {
        let clip = self.clip.as_ref()?;
        let (a, b) = self.region;
        let n = clip.samples.len();
        let (i, j) = (
            (a * clip.rate as f64) as usize,
            (b * clip.rate as f64) as usize,
        );
        Some(clip.samples[i.min(n)..j.min(n)].to_vec())
    }

    fn start(&mut self) {
        self.player = None; // the old one stops first (its output and threads)
        self.adopted = false;
        self.playing = None;
        self.playback = None;
        if self.sampler_on {
            return self.start_sampler();
        }
        if self.live_input {
            return self.start_input();
        }
        let (Some(x), Ok(s)) = (self.region_samples(), self.play_settings()) else {
            return;
        };
        let clip_path = self
            .clip
            .as_ref()
            .expect("a region needs a clip")
            .path
            .clone();
        let result = s.cores().and_then(|c| self.circuit(c)).and_then(|c| {
            let v = panel::values(&self.knobs);
            let ahead_s = match self.drawing_device() {
                Some(d) => d.ahead_s,
                None => DEVICES[self.device].ahead_s,
            };
            Player::start(Source::Loop(x), v, c, s.clone(), self.gain(), ahead_s)
        });
        match result {
            Ok(p) => {
                self.attach_end(&p);
                self.player = Some(p);
                self.playing = Some((self.region, self.device, clip_path));
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }

    /// The settings the chosen device plays at (its quality, its cores).
    fn play_settings(&self) -> Result<Settings, String> {
        self.settings_for(DEVICES.get(self.device).unwrap_or(&DRAWING))
    }

    /// The settings `dev` plays at.
    fn settings_for(&self, dev: &Device) -> Result<Settings, String> {
        self.by_quality
            .iter()
            .find(|(x, _)| *x == dev.quality)
            .map_or(&self.settings, |(_, s)| s)
            .as_ref()
            .map(|s| dev.play_settings(s))
            .map_err(Clone::clone)
    }

    /// Monitor the chosen input through the device.
    fn start_input(&mut self) {
        let Ok(s) = self.play_settings() else { return };
        if self.midi {
            return self.start_keys(s);
        }
        let Some(dev_in) = self.inputs.get(self.input) else {
            self.error = Some("no input device".into());
            return;
        };
        let source = Source::Input {
            device: Some(dev_in.name.clone()),
            channel: self.channel,
        };
        let buffer = self.input_buffer_ms / 1000.0;
        let result = s.cores().and_then(|c| self.circuit(c)).and_then(|c| {
            let v = panel::values(&self.knobs);
            Player::start(source, v, c, s.clone(), self.gain(), buffer)
        });
        match result {
            Ok(p) => {
                self.attach_end(&p);
                self.player = Some(p);
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }

    /// Play the device from the chosen MIDI keyboard (the test oscillator into it).
    fn start_keys(&mut self, s: Settings) {
        self.keyboard = None;
        let Some(port) = self.midi_ports.get(self.midi_port).cloned() else {
            self.error = Some("no MIDI input".into());
            return;
        };
        let buffer = self.input_buffer_ms / 1000.0;
        let touch = self.touch();
        self.playing_proxy = false;
        // The proxy in the device's place (its own small buffer: it costs nothing).
        if self.proxy_on
            && let (Some(t), Some(d)) = (self.proxy_tables.clone(), DEVICES.get(self.device))
        {
            let result = Keyboard::open(Some(&port)).and_then(|kb| {
                kb.keys.set_touch(touch);
                let start = ProxyStart {
                    tables: t,
                    device: d.id.to_string(),
                    quality: d.quality,
                    voices: 1,
                    noise: self.noise,
                };
                let v = panel::values(&self.knobs);
                let p = Player::start_proxy(kb.keys.clone(), start, v, s.clone(), buffer)?;
                p.set_velocity_range(self.velocity_range_db());
                p.set_retrigger(self.retrigger);
                self.wheel_seen = kb.keys.cc(MOD_WHEEL).1;
                Ok((kb, p))
            });
            match result {
                Ok((kb, p)) => {
                    self.keyboard = Some(kb);
                    self.player = Some(p);
                    self.playing_proxy = true;
                    self.error = None;
                }
                Err(e) => self.error = Some(e),
            }
            return;
        }
        let result = Keyboard::open(Some(&port)).and_then(|kb| {
            let c = s.cores().and_then(|c| self.circuit(c))?;
            let v = panel::values(&self.knobs);
            // The harp's own velocity law (its build is cached for the player's).
            let span = match self.has_harp {
                true => c.key_velocity_span_db(&v)?,
                false => None,
            };
            kb.keys.set_touch(Touch {
                native_db: span,
                ..touch
            });
            let feeds = match DEVICES.get(self.device) {
                Some(d) => panel::key_feeds(d, c.spec())?,
                None => Vec::new(),
            };
            let own = DEVICES
                .get(self.device)
                .is_some_and(|d| d.plays_own_oscillator());
            let wave = if own { Wave::Off } else { self.wave };
            let source = Source::Keys(kb.keys.clone(), wave, feeds);
            let p = Player::start(source, v, c, s.clone(), self.gain(), buffer)?;
            if let Some(m) = panel::range_mode(&self.knobs) {
                p.set_range_mode(m);
            }
            p.set_velocity_range(self.velocity_range_db());
            p.set_retrigger(self.retrigger);
            self.wheel_seen = kb.keys.cc(MOD_WHEEL).1;
            Ok((kb, p, span))
        });
        match result {
            Ok((kb, p, span)) => {
                self.key_span_db = span;
                self.attach_end(&p);
                self.keyboard = Some(kb);
                self.player = Some(p);
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }

    /// Play the sampler's kit from the chosen MIDI keyboard (none: from the pads only).
    fn start_sampler(&mut self) {
        self.keyboard = None;
        let s = match &self.settings {
            Ok(s) => s.clone(),
            Err(e) => {
                self.error = Some(e.clone());
                return;
            }
        };
        if self.midi_ports.is_empty() {
            self.midi_ports = midi::ports().unwrap_or_default();
        }
        let mut error = None;
        let kb =
            self.midi_ports
                .get(self.midi_port)
                .and_then(|port| match Keyboard::open(Some(port)) {
                    Ok(kb) => Some(kb),
                    Err(e) => {
                        error = Some(format!("{e}: the pads still play the kit"));
                        None
                    }
                });
        if let Some(kb) = &kb {
            kb.keys.set_touch(self.touch());
        }
        let keys = kb.as_ref().map(|k| k.keys.clone());
        let buffer = self.input_buffer_ms / 1000.0;
        match Player::start_sampler(self.kit.sampler.clone(), keys, s, buffer) {
            Ok(p) => {
                self.player = Some(p);
                self.keyboard = kb;
                self.error = error;
            }
            Err(e) => self.error = Some(e),
        }
    }

    /// The sampler's player running (a preview or a pad asked for a sound).
    fn ensure_sampler(&mut self) {
        if self.sampler_on && (self.player.is_none() || self.adopted) {
            self.start();
        }
    }

    /// The left column with the sampler chosen: its keyboard and its kit.
    fn sampler_side(&mut self, ui: &mut egui::Ui) {
        Self::heading(ui, "MIDI KEYBOARD");
        let (port, buffer) = (self.midi_port, self.input_buffer_ms);
        ui.horizontal(|ui| {
            let name = self
                .midi_ports
                .get(self.midi_port)
                .map_or("(no MIDI inputs: the pads play)", String::as_str);
            egui::ComboBox::from_id_salt("sampler_midi_port")
                .width(ui.available_width() - 34.0)
                .selected_text(name)
                .show_ui(ui, |ui| {
                    for (i, p) in self.midi_ports.iter().enumerate() {
                        ui.selectable_value(&mut self.midi_port, i, p);
                    }
                });
            if ui
                .button("↻")
                .on_hover_text("List the MIDI inputs again")
                .clicked()
            {
                self.midi_ports = midi::ports().unwrap_or_default();
                self.midi_port = self.midi_port.min(self.midi_ports.len().saturating_sub(1));
            }
        });
        ui.horizontal(|ui| {
            ui.label(RichText::new("Buffer").color(theme::MUTED));
            egui::ComboBox::from_id_salt("sampler_buffer")
                .width(70.0)
                .selected_text(format!("{:.0} ms", self.input_buffer_ms))
                .show_ui(ui, |ui| {
                    for ms in [5.0, 10.0, 20.0, 30.0, 50.0] {
                        ui.selectable_value(&mut self.input_buffer_ms, ms, format!("{ms:.0} ms"));
                    }
                })
                .response
                .on_hover_text("Audio computed ahead: most of a key's delay (less can drop out)");
        });
        self.touch_ui(ui);
        if (port, buffer) != (self.midi_port, self.input_buffer_ms)
            && self.player.is_some()
            && !self.adopted
        {
            self.start();
        }
        Self::heading(ui, "KIT");
        let mut wants = Wants::default();
        self.kit.slots_ui(ui, &mut wants);
        if wants.player {
            self.ensure_sampler();
        }
    }

    /// The main area with the sampler chosen: start / stop, its levels, the browser.
    fn sampler_main(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            if self.player.is_none() || self.adopted {
                let go =
                    egui::Button::new(RichText::new("▶  Play").strong().color(theme::ACCENT_INK))
                        .fill(theme::ACCENT)
                        .min_size(egui::vec2(96.0, 30.0));
                if ui
                    .add(go)
                    .on_hover_text("Play the kit from the keys (a preview starts it too)")
                    .clicked()
                {
                    self.start();
                }
            } else if ui
                .add(egui::Button::new("■  Stop").min_size(egui::vec2(96.0, 30.0)))
                .clicked()
            {
                self.stop();
            }
            ui.add_space(12.0);
            let line = match self.player.as_ref().filter(|_| !self.adopted) {
                Some(p) => {
                    let st = p.status();
                    let kb = self
                        .keyboard
                        .as_ref()
                        .map_or("no keyboard".to_string(), |k| k.name.clone());
                    format!(
                        "{kb} · out {:.0} dBFS peak · key to ear {:.0} ms · dropouts {}",
                        st.meter.out_dbfs,
                        st.latency_s.unwrap_or(0.0) * 1000.0,
                        p.dropouts()
                    )
                }
                None => "stopped".into(),
            };
            ui.label(RichText::new(line).color(theme::MUTED));
        });
        ui.label(
            RichText::new(
                "Pick sounds here, then record in the Session view: select a track, press R \
                 (the preview is never recorded)",
            )
            .small()
            .color(theme::FAINT),
        );
        if let Some(e) = &self.error {
            ui.colored_label(theme::FAULT, e);
        }
        ui.add_space(8.0);
        let mut wants = Wants::default();
        self.kit.browser_ui(ui, &mut wants);
        if wants.player {
            self.ensure_sampler();
        }
    }

    /// The chain's end as chosen, built (None: none chosen).
    fn end_device(&self) -> Option<Result<EndDevice, String>> {
        let dev = &DEVICES[self.end?];
        Some(self.settings_for(dev).and_then(|s| {
            let c = Circuit::load(&self.config_dir, dev.circuit, s.cores()?)?
                .with_events(s.events)
                .with_noise(false);
            Ok(EndDevice {
                label: dev.label.to_string(),
                circuit: c,
                values: panel::values(&self.end_knobs),
                settings: s,
            })
        }))
    }

    /// Put the chosen end on `p` (or take it off).
    fn attach_end(&mut self, p: &Player) {
        match self.end_device() {
            Some(Ok(d)) => p.set_end(Some(d)),
            Some(Err(e)) => {
                self.error = Some(format!("chain end: {e}"));
                p.set_end(None);
            }
            None => p.set_end(None),
        }
        p.set_end_mix(self.end_mix);
    }

    /// The chain's end: which device, its share of the output, its knobs.
    fn end_ui(&mut self, ui: &mut egui::Ui) {
        Self::heading(ui, "CHAIN END");
        let before = self.end;
        let shown = self.end.map_or("(none)", |i| DEVICES[i].label);
        egui::ComboBox::from_id_salt("chain_end")
            .width(ui.available_width())
            .selected_text(shown)
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut self.end, None, "(none)");
                for (group, ids) in panel::play_menu() {
                    let ends: Vec<usize> = ids
                        .into_iter()
                        .filter(|&i| panel::CHAIN_ENDS.contains(&DEVICES[i].id))
                        .collect();
                    if ends.is_empty() {
                        continue;
                    }
                    theme::menu_heading(ui, group.title());
                    for i in ends {
                        ui.selectable_value(&mut self.end, Some(i), DEVICES[i].label)
                            .on_hover_text(DEVICES[i].about);
                    }
                }
            })
            .response
            .on_hover_text(
                "A device after this one, on threads of its own (a block, 10 ms, later): \
                 the synth's output through a reverb",
            );
        if self.end != before {
            self.end_knobs = match self.end {
                Some(i) => {
                    let dev = &DEVICES[i];
                    match varimu_circuit::spec::circuit_path(&self.config_dir, dev.circuit)
                        .and_then(|p| varimu_circuit::spec::load_circuit(&p))
                    {
                        Ok(spec) => panel::knobs(dev, &spec),
                        Err(e) => {
                            self.error = Some(e.to_string());
                            Vec::new()
                        }
                    }
                }
                None => Vec::new(),
            };
            if let Some(p) = self.player.take() {
                if !self.adopted {
                    self.attach_end(&p);
                }
                self.player = Some(p);
            }
        }
        if self.end.is_none() {
            return;
        }
        ui.label(RichText::new("Mix (its share of the output)").color(theme::INK));
        let w = ui.available_width();
        ui.add_sized(
            [w, 18.0],
            egui::Slider::new(&mut self.end_mix, 0.0..=1.0).max_decimals(2),
        );
        ui.add_space(4.0);
        let mut changed = false;
        for k in &mut self.end_knobs {
            changed |= knob_ui(ui, k);
        }
        if changed
            && !self.adopted
            && let Some(p) = &self.player
        {
            p.set_end_values(panel::values(&self.end_knobs));
        }
    }

    /// The velocity range the keys play with (0 with velocity off).
    fn velocity_range_db(&self) -> f64 {
        if self.velocity_on {
            self.velocity_db
        } else {
            0.0
        }
    }

    /// The mod wheel turns the device's `mod_wheel` knob over its range.
    fn follow_mod_wheel(&mut self) {
        let (Some(kb), Some(p)) = (&self.keyboard, &self.player) else {
            return;
        };
        let Some(key) = DEVICES
            .get(self.device)
            .and_then(|d| d.mod_wheel)
            .filter(|_| !self.sampler_on)
        else {
            return;
        };
        let (cc, n) = kb.keys.cc(MOD_WHEEL);
        if n == self.wheel_seen {
            return;
        }
        self.wheel_seen = n;
        if let Some(k) = self.knobs.iter_mut().find(|k| k.key == key)
            && let Kind::Range { min, max } = k.kind
        {
            k.value = Value::Float(min + (max - min) * cc as f64 / 127.0);
            p.set(panel::values(&self.knobs));
        }
    }

    fn stop(&mut self) {
        let recording = self.player.as_ref().is_some_and(Player::recording);
        if let Some(p) = &self.player {
            p.record(false);
        }
        // The sampler records only in the Session view: no take to wait for.
        if recording || !self.sampler_on {
            self.collect_take();
        }
        self.player = None;
        self.playing = None;
        self.keyboard = None;
        self.adopted = false;
    }

    /// A take the worker has handed over, without waiting.
    fn collect_take_now(&mut self) {
        if let Some(t) = self.player.as_ref().and_then(Player::take) {
            self.save_take(t);
        }
    }

    /// A finished take: saved as a WAV at the input's rate (float32, as it came in),
    /// then opened as the file (loop it, render it).
    fn collect_take(&mut self) {
        let Some(take) = self.player.as_ref().and_then(|p| {
            // The worker hands the take over at its next input chunk.
            for _ in 0..50 {
                if let Some(t) = p.take() {
                    return Some(t);
                }
                std::thread::sleep(Duration::from_millis(5));
            }
            None
        }) else {
            return;
        };
        self.save_take(take);
    }

    fn save_take(&mut self, take: varimu_app::player::Take) {
        let when = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs());
        let dir = self
            .config_dir
            .parent()
            .map_or_else(|| PathBuf::from("cache"), |r| r.join("cache"))
            .join("app_takes");
        let path = dir.join(format!("take_{when}.wav"));
        match audio::write_wav(&path, &take.samples, take.rate) {
            Ok(()) => {
                self.take_saved = Some(path.clone());
                self.open(path);
            }
            Err(e) => self.error = Some(e),
        }
    }

    /// Render the loop region at production on a thread of its own.
    fn start_render(&mut self) {
        let Some(mut x) = self.region_samples() else {
            return;
        };
        let g = self.gain();
        if g != 1.0 {
            for v in &mut x {
                *v *= g;
            }
        }
        let clip = self.clip.as_ref().expect("a region needs a clip");
        let (label, id) = self.device_names();
        let drawing = self.drawing_device().cloned();
        let dev = DEVICES[self.device.min(DEVICES.len() - 1)];
        let noise = self.noise;
        let (a, b) = self.region;
        let stem = clip
            .path
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned();
        let label = format!("{label} · {stem} {a:.2}-{b:.2} s");
        let file_stem = format!("{stem}_{id}_{a:.2}-{b:.2}");
        let values = panel::values(&self.knobs);
        let config = self.config_dir.clone();
        let out_dir = config
            .parent()
            .map_or_else(|| PathBuf::from("cache"), |r| r.join("cache"))
            .join("app_renders");
        let progress = Arc::new(AtomicU64::new(0f64.to_bits()));
        let cancel = Arc::new(AtomicBool::new(false));
        let (tx, rx) = mpsc::channel();
        let (p, c) = (progress.clone(), cancel.clone());
        std::thread::spawn(move || {
            let r = (|| {
                let s = Settings::load(&config, Quality::Production)?;
                let circuit = match drawing {
                    Some(d) => Circuit::from_spec(d.lib, d.spec, s.cores()?).with_events(s.events),
                    None => Circuit::load(&config, dev.circuit, s.cores()?)?.with_events(s.events),
                }
                .with_noise(noise);
                render(
                    &circuit,
                    &values,
                    &x,
                    &s,
                    |f| p.store(f.to_bits(), Ordering::Relaxed),
                    &c,
                )
            })();
            let _ = tx.send(r.map(|r| {
                let when = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .map_or(0, |d| d.as_secs());
                let path = out_dir.join(format!("{file_stem}_{when}.wav"));
                let saved = audio::write_wav(&path, &r.out, r.sample_rate)
                    .ok()
                    .map(|()| path);
                (r, saved)
            }));
        });
        self.task = Some(RenderTask {
            progress,
            cancel,
            result: rx,
            started: Instant::now(),
            label,
        });
    }

    fn poll_render(&mut self) {
        let Some(t) = &self.task else { return };
        match t.result.try_recv() {
            Ok(Ok((rendered, path))) => {
                self.done = Some(Done {
                    path,
                    label: t.label.clone(),
                    rendered,
                });
                self.task = None;
            }
            Ok(Err(e)) => {
                if !t.cancel.load(Ordering::Relaxed) {
                    self.error = Some(format!("render: {e}"));
                }
                self.task = None;
            }
            Err(mpsc::TryRecvError::Empty) => {}
            Err(mpsc::TryRecvError::Disconnected) => self.task = None,
        }
    }

    /// The noise switch, for a device whose file has noise sources: a change restarts
    /// the stream (other elements) with a crossfade.
    fn noise_ui(&mut self, ui: &mut egui::Ui) {
        // The device's own settings (its quality, and its cores: the tube synth plays on
        // Jiles-Atherton cores whatever its quality's are; with the app's default settings
        // the replacement circuit had linear cores, and its reactor stopped tuning).
        let Some(cores) = self.play_settings().ok().and_then(|s| s.cores().ok()) else {
            return;
        };
        if self.has_heaters
            && self.player.is_some()
            && ui
                .button("Power on (cold)")
                .on_hover_text(
                    "Restart with the tubes' cathodes cold (device builder B6): they warm \
                     over ~10 s, the sound comes as they emit and the pitch settles over \
                     tens of seconds. Restarts after it start warm.",
                )
                .clicked()
        {
            self.power_on = true;
            self.start();
            self.power_on = false;
            // Later rebuilds are warm: an in-place update, the temperature carried over.
            if let (Some(p), Ok(c)) = (&self.player, self.circuit(cores)) {
                p.set_circuit(c, panel::values(&self.knobs));
            }
        }
        if !self.has_noise {
            return;
        }
        let r = ui.checkbox(&mut self.noise, "Noise").on_hover_text(
            "The circuit's noise sources (device builder B5): Johnson noise of its \
             resistors, its tubes' shot and flicker noise, the mains wander. Off saves their \
             CPU (tube synth: ~0.3x real time); renders follow this switch.",
        );
        if r.changed()
            && let Some(p) = &self.player
            && let Ok(c) = self.circuit(cores)
        {
            p.set_circuit(c, panel::values(&self.knobs));
        }
    }

    /// The device in or bypassed (B), and gain compensation.
    fn monitor_ui(&mut self, ui: &mut egui::Ui) {
        let typing = ui.ctx().egui_wants_keyboard_input();
        if !typing && ui.input(|i| i.key_pressed(egui::Key::B)) {
            self.bypass = !self.bypass;
        }
        ui.horizontal(|ui| {
            let (text, fill, ink) = if self.bypass {
                ("BYPASSED", theme::CHROME3, theme::MUTED)
            } else {
                ("DEVICE IN", theme::ACCENT, theme::ACCENT_INK)
            };
            let b = egui::Button::new(RichText::new(text).strong().color(ink))
                .fill(fill)
                .min_size(egui::vec2(110.0, 26.0));
            if ui
                .add(b)
                .on_hover_text("Hear the device or its input (B); the circuit keeps running")
                .clicked()
            {
                self.bypass = !self.bypass;
            }
            self.noise_ui(ui);
            ui.checkbox(&mut self.compensate, "Gain compensation")
                .on_hover_text(
                    "Match the device's output to its input's loudness (K-weighted, ~3 s), so \
                 bypass compares character, not level. Monitoring only: renders are the \
                 device as it is.",
                );
            if let Some(p) = &self.player
                && self.compensate
            {
                ui.label(
                    RichText::new(format!("{:+.1} dB", p.status().compensation_db))
                        .monospace()
                        .color(theme::INK),
                );
            }
            ui.add_space(12.0);
            ui.add_enabled_ui(!self.bypass, |ui| {
                ui.label(RichText::new("Output").color(theme::MUTED));
                let r = ui
                    .add(
                        egui::Slider::new(&mut self.output_db, -24.0..=24.0)
                            .step_by(0.5)
                            .suffix(" dB"),
                    )
                    .on_hover_text(
                        "A manual gain on the device's output, on top of the compensation \
                         (double-click: 0 dB). Monitoring only: renders are the device as it is.",
                    );
                if r.double_clicked() {
                    self.output_db = 0.0;
                }
            });
        });
    }

    /// The render row: start / progress / cancel, then play back and save.
    fn render_ui(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            if let Some(t) = &self.task {
                let f = f64::from_bits(t.progress.load(Ordering::Relaxed));
                let el = t.started.elapsed().as_secs_f64();
                let eta = if f > 0.02 {
                    format!(", ~{:.0} s left", el / f - el)
                } else {
                    String::new()
                };
                ui.add(
                    egui::ProgressBar::new(f as f32)
                        .desired_width(260.0)
                        .text(format!("rendering at production {:.0} %{eta}", f * 100.0)),
                );
                if ui.button("Cancel").clicked() {
                    t.cancel.store(true, Ordering::Relaxed);
                }
            } else if ui
                .add_enabled(
                    self.clip.is_some(),
                    egui::Button::new("Render (production)"),
                )
                .on_hover_text("The loop region and panel at production settings, saved as a WAV")
                .clicked()
            {
                self.start_render();
            }
            let Some(d) = &self.done else { return };
            ui.add_space(12.0);
            if self.playback.is_none() {
                if ui.button("▶ Play render").clicked() {
                    self.player = None;
                    self.playing = None;
                    match Playback::start(&d.rendered.out, d.rendered.sample_rate) {
                        Ok(p) => self.playback = Some(p),
                        Err(e) => self.error = Some(e),
                    }
                }
            } else if ui.button("■ Stop render").clicked() {
                self.playback = None;
            }
            if ui.button("Save as…").clicked()
                && let Some(p) = rfd::FileDialog::new()
                    .add_filter("WAV", &["wav"])
                    .save_file()
            {
                match audio::write_wav(&p, &d.rendered.out, d.rendered.sample_rate) {
                    Ok(()) => {
                        if let Some(d) = &mut self.done {
                            d.path = Some(p);
                        }
                    }
                    Err(e) => self.error = Some(e),
                }
            }
        });
        if let Some(d) = &self.done {
            let saved = d
                .path
                .as_ref()
                .map_or("(not saved)".to_string(), |p| p.display().to_string());
            ui.label(
                RichText::new(format!(
                    "{} · {:.1} s in {:.0} s ({:.1}x real time) · saved to {saved}",
                    d.label,
                    d.rendered.out.len() as f64 / d.rendered.sample_rate as f64,
                    d.rendered.wall_s,
                    d.rendered.realtime_factor(),
                ))
                .small()
                .color(theme::MUTED),
            );
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui) {
        self.poll_loading();
        self.poll_render();
        self.apply_monitor();
        if self.player.as_ref().is_some_and(|p| !p.recording()) {
            self.collect_take_now();
        }
        self.follow_mod_wheel();
        if let Err(e) = &self.settings {
            ui.colored_label(theme::FAULT, format!("can't read the settings: {e}"));
            return;
        }
        egui::Panel::left("play_panel")
            .resizable(false)
            .exact_size(320.0)
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::same(14)),
            )
            .show(ui, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| self.side(ui));
            });
        egui::CentralPanel::default()
            .frame(
                egui::Frame::NONE
                    .fill(theme::CANVAS)
                    .inner_margin(egui::Margin::same(18)),
            )
            .show(ui, |ui| self.main(ui));
        if self.player.is_some()
            || self.loading.is_some()
            || self.task.is_some()
            || self.playback.is_some()
        {
            ui.ctx().request_repaint_after(Duration::from_millis(33));
        }
    }

    fn heading(ui: &mut egui::Ui, text: &str) {
        ui.add_space(6.0);
        ui.label(RichText::new(text).small().color(theme::FAINT));
        ui.add_space(2.0);
    }

    /// The left column: device, file, front panel.
    fn side(&mut self, ui: &mut egui::Ui) {
        Self::heading(ui, "DEVICE");
        let before = (self.device, self.sampler_on);
        let (shown, _) = self.device_names();
        let drawing_title = self
            .drawing
            .as_ref()
            .map(|d| format!("{}: {}", d.origin, d.title));
        egui::ComboBox::from_id_salt("device")
            .width(ui.available_width())
            .selected_text(shown)
            .height(640.0)
            .show_ui(ui, |ui| {
                for (group, ids) in panel::play_menu() {
                    theme::menu_heading(ui, group.title());
                    for i in ids {
                        let d = &DEVICES[i];
                        if ui
                            .selectable_label(!self.sampler_on && self.device == i, d.label)
                            .on_hover_text(d.about)
                            .clicked()
                        {
                            (self.device, self.sampler_on) = (i, false);
                        }
                    }
                    // The sampler is an instrument with no circuit.
                    if group == panel::Group::Instruments
                        && ui
                            .selectable_label(self.sampler_on, "Sampler")
                            .on_hover_text(
                                "A kit of sounds, one per key of an octave, and a browser of \
                                 samples/",
                            )
                            .clicked()
                    {
                        self.sampler_on = true;
                    }
                }
                if let Some(t) = drawing_title {
                    theme::menu_heading(ui, "FROM THE EDITOR");
                    if ui
                        .selectable_label(!self.sampler_on && self.device == DEVICES.len(), t)
                        .on_hover_text("As it is now: edits are heard as they are made")
                        .clicked()
                    {
                        (self.device, self.sampler_on) = (DEVICES.len(), false);
                    }
                }
            });
        if (self.device, self.sampler_on) != before {
            if self.sampler_on {
                self.start();
            } else {
                self.load_knobs();
                if before.1 {
                    self.stop();
                } else if self.player.is_some() {
                    self.start();
                }
            }
        }
        if self.sampler_on {
            return self.sampler_side(ui);
        }

        Self::heading(ui, "SOURCE");
        // 0: the file, 1: live input, 2: a MIDI keyboard (live too).
        let mode = |v: &Self| match (v.live_input, v.midi) {
            (false, _) => 0,
            (true, false) => 1,
            (true, true) => 2,
        };
        let before = mode(self);
        let mut now = before;
        ui.horizontal(|ui| {
            ui.selectable_value(&mut now, 0, "File");
            ui.selectable_value(&mut now, 1, "Live input");
            ui.selectable_value(&mut now, 2, "MIDI keyboard")
                .on_hover_text("Play the device from a keyboard: its keys play a test oscillator into the device's input");
        });
        if now != before {
            self.stop();
            self.live_input = now != 0;
            self.midi = now == 2;
            if now == 1 && self.inputs.is_empty() {
                self.inputs = input_devices();
            }
            if now == 2 && self.midi_ports.is_empty() {
                self.midi_ports = midi::ports().unwrap_or_default();
            }
        }
        if self.midi {
            self.midi_ui(ui);
            ui.add_space(6.0);
            ui.label(RichText::new("File").small().color(theme::FAINT));
        } else if self.live_input {
            self.input_ui(ui);
            ui.add_space(6.0);
            ui.label(
                RichText::new("Recorded take / file")
                    .small()
                    .color(theme::FAINT),
            );
        }
        let current = self
            .clip
            .as_ref()
            .and_then(|c| c.path.file_name())
            .map_or("(none)".to_string(), |n| n.to_string_lossy().into_owned());
        let mut pick: Option<PathBuf> = None;
        let playing_path = self.clip.as_ref().map(|c| c.path.clone());
        egui::ComboBox::from_id_salt("clip")
            .width(ui.available_width())
            .height(520.0)
            .selected_text(current)
            .show_ui(ui, |ui| {
                for (group, files) in &self.sources {
                    theme::menu_heading(ui, group);
                    for p in files {
                        let name = p.file_name().unwrap_or_default().to_string_lossy();
                        let on = playing_path.as_ref() == Some(p);
                        if ui.selectable_label(on, name).clicked() {
                            pick = Some(p.clone());
                        }
                    }
                    ui.add_space(4.0);
                }
            });
        ui.horizontal(|ui| {
            if ui.button("Open file…").clicked()
                && let Some(p) = rfd::FileDialog::new()
                    .add_filter("Audio", &AUDIO_EXT)
                    .pick_file()
            {
                pick = Some(p);
            }
            if ui
                .button("Add folder…")
                .on_hover_text("List a folder's audio files (and its subfolders') as sources")
                .clicked()
                && let Some(dir) = rfd::FileDialog::new().pick_folder()
                && !self.prefs.source_folders.contains(&dir)
            {
                self.prefs.source_folders.push(dir);
                self.save_prefs();
                self.scan_sources();
            }
        });
        let mut remove = None;
        for (i, f) in self.prefs.source_folders.iter().enumerate() {
            ui.horizontal(|ui| {
                if ui
                    .small_button("×")
                    .on_hover_text("Stop listing this folder")
                    .clicked()
                {
                    remove = Some(i);
                }
                ui.label(
                    RichText::new(f.display().to_string())
                        .small()
                        .color(theme::MUTED),
                );
            });
        }
        if let Some(i) = remove {
            self.prefs.source_folders.remove(i);
            self.save_prefs();
            self.scan_sources();
        }
        if let Some(p) = pick {
            self.open(p);
        }
        if let Some((p, _)) = &self.loading {
            ui.label(
                RichText::new(format!(
                    "loading {}…",
                    p.file_name().unwrap_or_default().display()
                ))
                .color(theme::MUTED),
            );
        }

        self.level_ui(ui);

        Self::heading(ui, "FRONT PANEL");
        let mut changed = false;
        for k in &mut self.knobs {
            changed |= knob_ui(ui, k);
        }
        if ui.small_button("Defaults").clicked() {
            for k in &mut self.knobs {
                k.value = k.default.clone();
            }
            changed = true;
        }
        if changed && let Some(p) = &self.player {
            if let Some(m) = panel::range_mode(&self.knobs) {
                p.set_range_mode(m);
            }
            p.set(panel::values(&self.knobs));
        }
        self.end_ui(ui);
    }

    /// The MIDI keyboard's port, the test oscillator's waveform, the buffer, and what is
    /// held.
    fn midi_ui(&mut self, ui: &mut egui::Ui) {
        let (port, wave, buffer) = (self.midi_port, self.wave, self.input_buffer_ms);
        ui.horizontal(|ui| {
            let name = self
                .midi_ports
                .get(self.midi_port)
                .map_or("(no MIDI inputs)", String::as_str);
            egui::ComboBox::from_id_salt("midi_port")
                .width(ui.available_width() - 34.0)
                .selected_text(name)
                .show_ui(ui, |ui| {
                    for (i, p) in self.midi_ports.iter().enumerate() {
                        ui.selectable_value(&mut self.midi_port, i, p);
                    }
                });
            if ui
                .button("↻")
                .on_hover_text("List the MIDI inputs again")
                .clicked()
            {
                self.midi_ports = midi::ports().unwrap_or_default();
                self.midi_port = self.midi_port.min(self.midi_ports.len().saturating_sub(1));
            }
        });
        if let Some(t) = self.proxy_tables.clone() {
            let mut on = self.proxy_on;
            let stale = t.stale(&self.config_dir);
            ui.horizontal(|ui| {
                ui.checkbox(&mut on, "Monitor through the proxy")
                    .on_hover_text(format!(
                        "A cheap digital stand-in that follows the panel through tables measured on \
                         the device (config/proxy/{}.json). Takes recorded through it render on \
                         the device behind the recording. The heaters, the reservoir and the mains \
                         are heard in the render only.",
                        t.device
                    ));
                if stale {
                    ui.label(RichText::new("tables stale").small().color(theme::WARN))
                        .on_hover_text("The circuit file changed since the proxy's tables were measured: rerun scripts/proxy_tables.py");
                }
            });
            if on != self.proxy_on {
                self.set_monitor_proxy(on);
            }
        }
        // A device with an oscillator of its own (a pitch control input) plays it from the
        // keys; the test oscillator stays silent, so its waveform does nothing there.
        let own_oscillator = DEVICES
            .get(self.device)
            .is_some_and(|d| d.plays_own_oscillator());
        ui.horizontal(|ui| {
            ui.add_enabled_ui(!own_oscillator, |ui| {
                ui.label(RichText::new("Wave").color(theme::MUTED));
                ui.selectable_value(&mut self.wave, Wave::Saw, "Saw");
                ui.selectable_value(&mut self.wave, Wave::Square, "Square");
            })
            .response
            .on_disabled_hover_text(
                "The test oscillator's waveform: this device plays its own oscillator \
                 (its WAVE knob on the front panel)",
            );
            ui.label(RichText::new("Buffer").color(theme::MUTED));
            egui::ComboBox::from_id_salt("midi_buffer")
                .width(70.0)
                .selected_text(format!("{:.0} ms", self.input_buffer_ms))
                .show_ui(ui, |ui| {
                    for ms in [10.0, 20.0, 30.0, 50.0] {
                        ui.selectable_value(&mut self.input_buffer_ms, ms, format!("{ms:.0} ms"));
                    }
                });
        });
        self.touch_ui(ui);
        if DEVICES.get(self.device).is_some_and(|d| d.gate.is_some())
            && ui
                .checkbox(&mut self.retrigger, "Retrigger")
                .on_hover_text(
                    "On: a new key while another is held restarts the envelope (the keyboard \
                     lifts its bus for 1 ms). Off: legato, the envelope carries on",
                )
                .changed()
            && let Some(p) = &self.player
        {
            p.set_retrigger(self.retrigger);
        }
        let held = self.keyboard.as_ref().map(|kb| match kb.keys.sounding() {
            Some((n, v)) => format!(
                "key {} ({:.0} Hz), velocity {v}, pressure {}",
                note_name(n),
                midi::TestOsc::note_hz(n),
                kb.keys.pressure()
            ),
            None => "no key held".into(),
        });
        ui.label(
            RichText::new(held.unwrap_or_else(|| {
                if own_oscillator {
                    "the keys play the device's own oscillator (the test oscillator is off)".into()
                } else {
                    "a test oscillator (band-limited, one voice) plays into the device: not part of it"
                        .into()
                }
            }))
            .small()
            .color(theme::MUTED),
        );
        let changed = (port, wave, buffer) != (self.midi_port, self.wave, self.input_buffer_ms);
        if changed && self.player.is_some() {
            self.start();
        }
    }

    /// The chosen keyboard's saved touch (`app.json`, by its port's name).
    fn key_touch(&self) -> KeyTouch {
        self.midi_ports
            .get(self.midi_port)
            .and_then(|port| self.prefs.touch.get(port))
            .copied()
            .unwrap_or_default()
    }

    /// The keys strike the harp (not the sampler in its place).
    fn harp_keys(&self) -> bool {
        self.has_harp && !self.sampler_on
    }

    /// The touch the keys play with: the keyboard's, on the harp's own law when they strike
    /// one (other devices' ranges are their own: tube_synth's Range is the Play view's).
    fn touch(&self) -> Touch {
        let t = self.key_touch();
        Touch {
            curve: t.curve,
            range_db: t.range_db,
            native_db: self.key_span_db.filter(|_| self.harp_keys()),
        }
    }

    /// The keyboard's touch (`midi::Touch`): Sensitivity (how far the line bends toward
    /// full) and Range (the harp's; tube_synth's velocity range), the curve with the last key on it.
    fn touch_ui(&mut self, ui: &mut egui::Ui) {
        let Some(port) = self.midi_ports.get(self.midi_port).cloned() else {
            return;
        };
        let mut t = self.key_touch();
        let before = t;
        let harp = self.harp_keys();
        let table = !self.sampler_on
            && DEVICES
                .get(self.device)
                .is_some_and(|d| d.velocity.is_some());
        let span = self.key_span_db.unwrap_or(panel::VELOCITY_RANGE_MAX_DB);
        ui.horizontal(|ui| {
            ui.label(RichText::new("Sensitivity").color(theme::MUTED));
            let slider = egui::Slider::new(&mut t.curve, 0.0..=1.0)
                .custom_formatter(|v, _| format!("{:.0}%", v * 100.0));
            ui.add(slider).on_hover_text(
                "How far a lighter touch plays toward the full sound: the line bends into a \
                 smooth curve (0%: as the keyboard sends; 100%: velocity 64 plays within ~1 dB \
                 of full on the harp). The softest and hardest keys stay where they were. The \
                 keyboard's, saved by its name; a take keeps the velocities it played",
            );
        });
        if harp {
            ui.horizontal(|ui| {
                ui.label(RichText::new("Range").color(theme::MUTED));
                let mut r = t.range_db.unwrap_or(span).min(span);
                let hover = format!(
                    "How much softer the softest key plays than full: the hammer's speed \
                     (the harp's own law spans {span:.0} dB)"
                );
                let slider = egui::Slider::new(&mut r, 0.0..=span)
                    .step_by(1.0)
                    .suffix(" dB");
                if ui.add(slider).on_hover_text(hover).changed() {
                    t.range_db = Some(r);
                }
                if t.range_db.is_some()
                    && ui
                        .small_button("own")
                        .on_hover_text("The harp's own range")
                        .clicked()
                {
                    t.range_db = None;
                }
            });
        } else if table {
            ui.horizontal(|ui| {
                let mut changed = ui
                    .checkbox(&mut self.velocity_on, "Range")
                    .on_hover_text("Off: every key plays at full level however hard it's pressed")
                    .changed();
                changed |= ui
                    .add_enabled(
                        self.velocity_on,
                        egui::Slider::new(
                            &mut self.velocity_db,
                            0.0..=panel::VELOCITY_RANGE_MAX_DB,
                        )
                        .step_by(1.0)
                        .suffix(" dB"),
                    )
                    .on_hover_text(
                        "How much softer the softest key plays than the hardest: the \
                         keyboard bus's key-down volts by velocity",
                    )
                    .changed();
                if changed && let Some(p) = &self.player {
                    p.set_velocity_range(self.velocity_range_db());
                }
            });
        }
        // The level each velocity plays at below full, on the device's law.
        let law: Box<dyn Fn(u8) -> f64> = if harp {
            Box::new(move |v| -span * (127 - v) as f64 / 126.0)
        } else if table {
            let db = self.velocity_range_db();
            Box::new(move |v| -db * (127 - v) as f64 / 126.0)
        } else {
            // The sampler and the test oscillator: a level linear in velocity.
            Box::new(|v| 20.0 * (v as f64 / 127.0).log10())
        };
        let shown = Touch {
            curve: t.curve,
            range_db: t.range_db,
            native_db: harp.then_some(span),
        };
        let sent = self.keyboard.as_ref().and_then(|kb| kb.keys.last_sent());
        touch_curve(ui, &shown, &*law, sent);
        if t != before {
            self.prefs.touch.insert(port, t);
            self.touch_dirty = true;
            if let Some(kb) = &self.keyboard {
                kb.keys.set_touch(self.touch());
            }
        }
        if self.touch_dirty && !ui.ctx().input(|i| i.pointer.any_down()) {
            self.touch_dirty = false;
            self.save_prefs();
        }
    }

    /// Live input's device, channel and buffer.
    fn input_ui(&mut self, ui: &mut egui::Ui) {
        let (input, channel, buffer) = (self.input, self.channel, self.input_buffer_ms);
        ui.horizontal(|ui| {
            let name = self
                .inputs
                .get(self.input)
                .map_or("(no inputs)", |d| d.name.as_str());
            egui::ComboBox::from_id_salt("input")
                .width(ui.available_width() - 34.0)
                .selected_text(name)
                .show_ui(ui, |ui| {
                    for (i, d) in self.inputs.iter().enumerate() {
                        let label =
                            format!("{} ({} ch, {} kHz)", d.name, d.channels, d.rate / 1000);
                        ui.selectable_value(&mut self.input, i, label);
                    }
                });
            if ui
                .button("↻")
                .on_hover_text("List the input devices again")
                .clicked()
            {
                self.inputs = input_devices();
                self.input = self.input.min(self.inputs.len().saturating_sub(1));
            }
        });
        let channels = self
            .inputs
            .get(self.input)
            .map_or(1, |d| d.channels as usize);
        self.channel = self.channel.min(channels - 1);
        ui.horizontal(|ui| {
            ui.label(RichText::new("Channel").color(theme::MUTED));
            egui::ComboBox::from_id_salt("channel")
                .width(60.0)
                .selected_text(format!("{}", self.channel + 1))
                .show_ui(ui, |ui| {
                    for c in 0..channels {
                        ui.selectable_value(&mut self.channel, c, format!("{}", c + 1));
                    }
                });
            ui.label(RichText::new("Buffer").color(theme::MUTED));
            egui::ComboBox::from_id_salt("buffer")
                .width(70.0)
                .selected_text(format!("{:.0} ms", self.input_buffer_ms))
                .show_ui(ui, |ui| {
                    for ms in [10.0, 20.0, 30.0, 50.0, 80.0, 150.0] {
                        ui.selectable_value(&mut self.input_buffer_ms, ms, format!("{ms:.0} ms"));
                    }
                });
        });
        let changed = (input, channel, buffer) != (self.input, self.channel, self.input_buffer_ms);
        if changed && self.player.is_some() {
            self.start();
        }
    }

    /// Transport, the waveform with its loop region, meters.
    fn main(&mut self, ui: &mut egui::Ui) {
        if self.sampler_on {
            return self.sampler_main(ui);
        }
        if self.live_input {
            self.input_transport(ui);
        } else {
            self.file_transport(ui);
        }
        ui.add_space(8.0);
        self.monitor_ui(ui);
        ui.add_space(8.0);
        self.render_ui(ui);
        ui.add_space(8.0);
        self.waveform(ui);
        // A region changed while playing: restart on release.
        if self.drag_from.is_none()
            && let Some((region, dev, path)) = &self.playing
            && (*region != self.region || *dev != self.device)
            && self.clip.as_ref().is_some_and(|c| &c.path == path)
        {
            self.start();
        }
        ui.add_space(16.0);
        self.meters(ui);
        if let Some(e) = &self.error {
            ui.add_space(8.0);
            ui.colored_label(theme::FAULT, e);
        }
    }

    fn input_transport(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            if self.player.is_none() {
                let go = egui::Button::new(
                    RichText::new("▶  Monitor")
                        .strong()
                        .color(theme::ACCENT_INK),
                )
                .fill(theme::ACCENT)
                .min_size(egui::vec2(110.0, 30.0));
                let can = if self.midi {
                    !self.midi_ports.is_empty()
                } else {
                    !self.inputs.is_empty()
                };
                if ui.add_enabled(can, go).clicked() {
                    self.start();
                }
            } else if ui
                .add(egui::Button::new("■  Stop").min_size(egui::vec2(110.0, 30.0)))
                .clicked()
            {
                self.stop();
            }
            let recording = self.player.as_ref().is_some_and(Player::recording);
            let rec = if recording {
                egui::Button::new(RichText::new("■  Stop recording").color(Color32::WHITE))
                    .fill(theme::FAULT)
            } else {
                egui::Button::new("●  Record")
            };
            if ui
                .add_enabled(
                    self.player.is_some() && !self.midi,
                    rec.min_size(egui::vec2(130.0, 30.0)),
                )
                .on_hover_text("Keep the input as a take: it becomes the file (loop it, render it)")
                .clicked()
                && let Some(p) = &self.player
            {
                p.record(!recording);
                if recording {
                    self.collect_take();
                }
            }
            if let Some(t) = &self.take_saved {
                ui.label(
                    RichText::new(format!("take saved: {}", t.display()))
                        .small()
                        .color(theme::MUTED),
                );
            }
        });
    }

    fn file_transport(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            let can_play = self.clip.is_some();
            if self.player.is_none() {
                let play =
                    egui::Button::new(RichText::new("▶  Play").strong().color(theme::ACCENT_INK))
                        .fill(theme::ACCENT)
                        .min_size(egui::vec2(96.0, 30.0));
                if ui.add_enabled(can_play, play).clicked() {
                    self.start();
                }
            } else if ui
                .add(egui::Button::new("■  Stop").min_size(egui::vec2(96.0, 30.0)))
                .clicked()
            {
                self.stop();
            }
            ui.add_space(12.0);
            if let Some(c) = &self.clip {
                let (a, b) = self.region;
                ui.label(
                    RichText::new(format!(
                        "loop {:.2} – {:.2} s ({:.2} s of {:.1} s)",
                        a,
                        b,
                        b - a,
                        c.seconds()
                    ))
                    .color(theme::MUTED),
                );
            } else {
                ui.label(RichText::new("Open a file to play it").color(theme::MUTED));
            }
            if let Ok(s) = self.play_settings() {
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    ui.label(
                        RichText::new(format!("{} · {} kHz", s.quality.name(), s.host() / 1000))
                            .small()
                            .color(theme::FAINT),
                    );
                });
            }
        });
    }

    fn waveform(&mut self, ui: &mut egui::Ui) {
        let h = 140.0;
        let (rect, resp) =
            ui.allocate_exact_size(egui::vec2(ui.available_width(), h), egui::Sense::drag());
        let painter = ui.painter_at(rect);
        painter.rect_filled(rect, 4.0, theme::BG);
        let Some(clip) = &self.clip else {
            return;
        };
        let secs = clip.seconds();
        let x_of = |t: f64| rect.left() + (t / secs) as f32 * rect.width();
        let t_of = |x: f32| (((x - rect.left()) / rect.width()) as f64 * secs).clamp(0.0, secs);
        // The region.
        let (a, b) = self.region;
        let sel = egui::Rect::from_x_y_ranges(x_of(a)..=x_of(b), rect.y_range());
        painter.rect_filled(sel, 0.0, theme::ACCENT.gamma_multiply(0.12));
        // The overview.
        let mid = rect.center().y;
        let n = clip.overview.len().max(1) as f32;
        for (i, &(lo, hi)) in clip.overview.iter().enumerate() {
            let x = rect.left() + (i as f32 + 0.5) / n * rect.width();
            let t = (i as f64 + 0.5) / n as f64 * secs;
            let c = if t >= a && t <= b {
                theme::INK
            } else {
                theme::FAINT
            };
            let (y0, y1) = (mid - hi.max(0.0) * h * 0.48, mid - lo.min(0.0) * h * 0.48);
            painter.line_segment(
                [egui::pos2(x, y0), egui::pos2(x, y1.max(y0 + 1.0))],
                Stroke::new(1.0, c),
            );
        }
        for x in [sel.left(), sel.right()] {
            painter.line_segment(
                [egui::pos2(x, rect.top()), egui::pos2(x, rect.bottom())],
                Stroke::new(1.5, theme::ACCENT),
            );
        }
        // The playhead.
        if let Some(p) = &self.player {
            let st = p.status();
            if st.state == State::Playing && st.loop_s > 0.0 {
                let x = x_of(a + st.position_s);
                painter.line_segment(
                    [egui::pos2(x, rect.top()), egui::pos2(x, rect.bottom())],
                    Stroke::new(1.0, Color32::WHITE),
                );
            }
        }
        if let Some(pb) = &self.playback {
            let x = x_of(a + pb.position_s());
            painter.line_segment(
                [egui::pos2(x, rect.top()), egui::pos2(x, rect.bottom())],
                Stroke::new(1.0, theme::ACCENT),
            );
        }
        // Drag selects a new region.
        if resp.drag_started()
            && let Some(pos) = resp.interact_pointer_pos()
        {
            self.drag_from = Some(t_of(pos.x));
        }
        if let (Some(t0), Some(pos)) = (self.drag_from, resp.interact_pointer_pos())
            && resp.dragged()
        {
            let t1 = t_of(pos.x);
            self.region = (t0.min(t1), t0.max(t1));
        }
        if resp.drag_stopped() {
            self.drag_from = None;
            let (a, b) = self.region;
            if b - a < MIN_REGION_S {
                let b = (a + MIN_REGION_S).min(secs);
                self.region = ((b - MIN_REGION_S).max(0.0), b);
            }
        }
        resp.on_hover_text("Drag to choose the loop");
    }

    fn meters(&mut self, ui: &mut egui::Ui) {
        let Some(p) = &self.player else {
            return;
        };
        let st = p.status();
        match &st.state {
            State::Starting => {
                ui.horizontal(|ui| {
                    ui.spinner();
                    ui.label(
                        RichText::new("building and settling the circuit…").color(theme::MUTED),
                    );
                });
                return;
            }
            State::Failed(e) => {
                ui.colored_label(theme::FAULT, e);
                return;
            }
            State::Playing => {}
        }
        let m = st.meter;
        let gain_label = if DEVICES
            .get(self.device)
            .is_some_and(|d| d.id == "fairchild_670")
        {
            "Gain (GR)"
        } else if m.spl_db.is_some() {
            "Gain (Pa/V)"
        } else {
            "Gain"
        };
        bar(
            ui,
            gain_label,
            m.gain_db,
            -30.0,
            10.0,
            format!("{:+.1} dB", m.gain_db),
        );
        bar(
            ui,
            "Output",
            m.out_dbfs,
            -60.0,
            0.0,
            format!("{:.1} dBFS", m.out_dbfs),
        );
        if let Some(spl) = m.spl_db {
            bar(
                ui,
                "Sound pressure",
                spl,
                60.0,
                130.0,
                format!("{spl:.1} dB SPL"),
            );
        }
        if let Some(cv) = m.cv_v {
            bar(ui, "Control voltage", -cv, 0.0, 60.0, format!("{cv:.2} V"));
        }
        bar(
            ui,
            "Load",
            st.load * 100.0,
            0.0,
            100.0,
            format!("{:.0} %", st.load * 100.0),
        );
        ui.add_space(8.0);
        let knob = st.knob_to_ear_s.map_or(String::new(), |k| {
            format!(" · last knob heard after {:.0} ms", k * 1000.0)
        });
        let line = format!(
            "{} · {} Hz · queued {:.0} ms · dropouts {} · restarts {}{knob}",
            st.device,
            st.rate,
            p.queued_s() * 1000.0,
            p.dropouts(),
            st.restarts,
        );
        ui.label(RichText::new(line).small().color(theme::MUTED));
        if let (Some(input), Some(lat)) = (&st.input, st.latency_s) {
            let (lost, skipped) = p.input_losses();
            let line = format!(
                "input {input} · input to output {:.1} ms (output device {:.1} ms) · lost {lost} samples, skipped {skipped} blocks",
                lat * 1000.0,
                p.output_latency_s() * 1000.0,
            );
            ui.label(RichText::new(line).small().color(theme::MUTED));
        }
        if let Some(e) = &st.build_error {
            ui.colored_label(theme::WARN, format!("knob change not applied: {e}"));
        }
        if let Some(end) = &st.end {
            ui.add_space(6.0);
            match &end.state {
                State::Starting => {
                    ui.horizontal(|ui| {
                        ui.spinner();
                        ui.label(
                            RichText::new(format!("{}: settling (dry meanwhile)…", end.label))
                                .color(theme::MUTED),
                        );
                    });
                }
                State::Failed(e) => {
                    ui.colored_label(theme::FAULT, format!("{}: {e}", end.label));
                }
                State::Playing => {
                    bar(
                        ui,
                        "End load",
                        end.load * 100.0,
                        0.0,
                        100.0,
                        format!("{:.0} %", end.load * 100.0),
                    );
                    let line = format!(
                        "{} · worst block {:.0} % · out {:.1} dBFS · restarts {}",
                        end.label,
                        end.load_max * 100.0,
                        end.out_dbfs,
                        end.restarts
                    );
                    ui.label(RichText::new(line).small().color(theme::MUTED));
                }
            }
            if let Some(e) = &end.build_error {
                ui.colored_label(theme::WARN, format!("end knob not applied: {e}"));
            }
        }
    }
}

/// One knob; true if it moved.
fn knob_ui(ui: &mut egui::Ui, k: &mut Knob) -> bool {
    ui.label(RichText::new(&k.label).color(theme::INK));
    let w = ui.available_width();
    let changed = match &k.kind {
        Kind::Range { min, max } => {
            let (f, suffix) = k.display_scale();
            let mut v = k.number() * f;
            let r = ui.add_sized(
                [w, 18.0],
                egui::Slider::new(&mut v, *min * f..=*max * f)
                    .max_decimals(3)
                    .suffix(suffix),
            );
            if r.changed() {
                k.value = Value::Float(v / f);
            }
            r.changed()
        }
        Kind::Steps { min, max, int } => {
            let mut v = k.number().round();
            let r = ui.add_sized(
                [w, 18.0],
                egui::Slider::new(&mut v, *min..=*max)
                    .step_by(1.0)
                    .max_decimals(0),
            );
            if r.changed() {
                k.value = if *int {
                    Value::Int(v as i64)
                } else {
                    Value::Float(v)
                };
            }
            r.changed()
        }
        Kind::Choices(choices) => {
            let mut i = k.number() as usize;
            let before = i;
            egui::ComboBox::from_id_salt(&k.key)
                .width(w)
                .selected_text(k.choice_text(&choices[i]))
                .show_ui(ui, |ui| {
                    for (j, c) in choices.iter().enumerate() {
                        ui.selectable_value(&mut i, j, k.choice_text(c));
                    }
                });
            if i != before {
                k.value = choices[i].clone();
            }
            i != before
        }
        Kind::Toggle => {
            let mut on = k.number() != 0.0;
            let r = ui.checkbox(&mut on, "");
            if r.changed() {
                k.value = Value::Int(i64::from(on));
            }
            r.changed()
        }
    };
    ui.add_space(4.0);
    changed
}

/// A horizontal meter bar from `lo` to `hi`.
fn bar(ui: &mut egui::Ui, label: &str, v: f64, lo: f64, hi: f64, text: String) {
    ui.horizontal(|ui| {
        ui.add_sized(
            [120.0, 18.0],
            egui::Label::new(RichText::new(label).color(theme::MUTED)),
        );
        let (rect, _) = ui.allocate_exact_size(egui::vec2(260.0, 12.0), egui::Sense::hover());
        let p = ui.painter_at(rect);
        p.rect_filled(rect, 2.0, theme::BG);
        let f = (((v - lo) / (hi - lo)).clamp(0.0, 1.0)) as f32;
        let mut fill = rect;
        fill.set_width(rect.width() * f);
        p.rect_filled(fill, 2.0, theme::ACCENT);
        ui.label(RichText::new(text).monospace().color(theme::INK));
    });
}

/// The audio files the app reads (symphonia's formats).
pub(crate) const AUDIO_EXT: [&str; 6] = ["wav", "aif", "aiff", "flac", "ogg", "mp3"];

/// `dir` and its subfolders: a group per folder holding audio files, labelled by its
/// path under `root` (a folder nested in one of the same name, as multitrack
/// downloads unpack, shows once).
pub(crate) fn scan_folder(root: &Path, dir: &Path, groups: &mut Vec<(String, Vec<PathBuf>)>) {
    let files = list_audio(dir);
    if !files.is_empty() {
        let mut parts: Vec<String> = Vec::new();
        let base = root.file_name().map(|n| n.to_string_lossy().into_owned());
        let rel = dir.strip_prefix(root).unwrap_or(dir);
        for c in base
            .into_iter()
            .chain(rel.iter().map(|c| c.to_string_lossy().into_owned()))
        {
            if parts.last() != Some(&c) {
                parts.push(c);
            }
        }
        groups.push((parts.join(" / "), files));
    }
    let mut dirs: Vec<PathBuf> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.is_dir())
        .collect();
    dirs.sort();
    for d in dirs {
        scan_folder(root, &d, groups);
    }
}

/// The audio files in `dir` (not its subfolders), by name.
fn list_audio(dir: &Path) -> Vec<PathBuf> {
    let ext = AUDIO_EXT;
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir)
        .into_iter()
        .flatten()
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| ext.contains(&e.to_ascii_lowercase().as_str()))
        })
        .collect();
    v.sort();
    v
}

/// Whether a circuit's keys strike a medium (a `harp` part: the Rhodes).
fn has_harp_part(spec: &CircuitSpec) -> bool {
    spec.sections.iter().any(|s| {
        s.parts
            .iter()
            .any(|(_, e)| e.as_map().is_some_and(|m| m.get("harp").is_some()))
    })
}

/// The touch's curve: the level each velocity sent plays at (`law`, dB below full) as the
/// keyboard sends it (faint) and through the touch, the last key sent on it.
fn touch_curve(ui: &mut egui::Ui, t: &Touch, law: &dyn Fn(u8) -> f64, sent: Option<u8>) {
    let w = ui.available_width().min(260.0);
    let (rect, _) = ui.allocate_exact_size(egui::vec2(w, 54.0), egui::Sense::hover());
    let painter = ui.painter_at(rect);
    painter.rect_filled(rect, 2.0, theme::CANVAS);
    let floor = law(1).min(-1.0);
    let at = |v: u8, db: f64| {
        egui::pos2(
            rect.left() + rect.width() * (v - 1) as f32 / 126.0,
            rect.top() + 3.0 + (rect.height() - 6.0) * (db / floor).clamp(0.0, 1.0) as f32,
        )
    };
    let own: Vec<egui::Pos2> = (1..=127).map(|v| at(v, law(v))).collect();
    let touched: Vec<egui::Pos2> = (1..=127).map(|v| at(v, law(t.map(v)))).collect();
    painter.add(egui::Shape::line(own, Stroke::new(1.0, theme::FAINT)));
    painter.add(egui::Shape::line(touched, Stroke::new(1.5, theme::ACCENT)));
    let text = match sent {
        Some(v) => {
            painter.circle_filled(at(v, law(t.map(v))), 3.5, theme::INK);
            format!(
                "last key sent {v}, plays {} ({:+.1} dB)",
                t.map(v),
                law(t.map(v))
            )
        }
        None => format!("velocity 1 plays {:.1} dB below full", -law(t.map(1))),
    };
    ui.label(RichText::new(text).small().color(theme::MUTED));
}

/// A MIDI note's name (C4 = 60).
fn note_name(n: u8) -> String {
    const NAMES: [&str; 12] = [
        "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
    ];
    format!("{}{}", NAMES[n as usize % 12], n as i32 / 12 - 1)
}
