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
//! one, which records.
//!
//! **Clips** (docs/SESSION_EDITING_PLAN.md SE5): a lane is clips, stretches of the track's
//! takes. A click selects one, a drag moves it (by the snap; Alt inverts it), onto another
//! track too; a drag on its left or right edge trims it (the audio under it stays: a trim is
//! undone by trimming back), on a top corner's handle sets its fade, on the gain handle (top
//! middle) its gain. S splits the selected clip (or the armed track's under the cursor) at
//! the cursor, Delete deletes it (its take stays in the track's pool), right-click offers
//! split, mute, reset, delete and its take's actions. A later clip lies on top of an earlier
//! one; the earlier crossfades under its fades. Cut edges get a 2 ms fade, a take's own ends
//! none, an untouched split none (it plays seamlessly). With every take shown (▸), a click
//! on a take's row puts it in the lane whole, a drag across it promotes that stretch into
//! the lane on top (comping); ‹ › put the earlier / later take in the lane whole. A track's
//! inserts print its lane as arranged. Deleted takes leave the session but their files stay
//! in its folder. Ctrl+Z undoes every gesture.
//!
//! **Editing** (docs/SESSION_EDITING_PLAN.md SE8): a toolbar over the arrangement has the
//! tools (1-5: Pointer; Blade, a click splits; Erase, a click deletes; Slip, a drag slides the
//! audio inside a clip, as Ctrl+drag does with the pointer; Envelope, points on a clip's gain
//! envelope), Cut / Copy / Paste / Duplicate / Delete / Split, two switches (Zero crossings:
//! splits move to the nearest one within 5 ms; Ripple: deletes close their gap on the track),
//! the Clip menu (also in a clip's context menu: polarity, fade shape, crossfade into the next
//! clip with a tape splice's length, Reverse and Varispeed into a new take, Split at transients,
//! Quantize, Strip silence, Consolidate, Clear envelope) and Bounce (what plays: the soloed
//! tracks, else the mix, over the selected range or the loop, to a new stereo track; and
//! Consolidate the selection). Shift+drag copies a clip, ← / → nudge.
//!
//! **The cursor** (docs/SESSION_EDITING_PLAN.md SE2) is where play starts and a take
//! records: a click on the ruler or on empty lane space puts it there (snapped; Alt: the
//! snap inverted), a click on a marker's flag jumps to it. Moving it while playing plays on
//! from it. Stop puts the playhead back at the cursor, or with "return" off leaves the
//! cursor where play stopped. Moving the cursor isn't an undo step.
//!
//! **Snap** (the transport's second row): Bar, Beat, 1/8, 1/8T, 1/16, 1/32 or Off, for
//! every gesture on the timeline (moving takes, the cursor, the locators on beats or bars);
//! Alt inverts it. A snapped move keeps a take's offset from the grid. The piano roll opens
//! with the snap as its grid.
//!
//! The ruler: Ctrl+click puts the left locator there, Shift+click the right one; a drag
//! draws the loop between them (and turns it on), a drag on a locator's handle moves it;
//! right-click adds a marker, or renames or deletes the one under it. With the loop on, play
//! (and recording) repeats from the left locator to the right one, each recorded pass a new
//! take in the lane. Below the lanes a scrollbar scrolls in time; −, + and Fit zoom.
//!
//! Keys: Space plays / stops (Shift+Space: from where it stopped), R records, Home / End
//! put the cursor at bar 1 / the session's end, Ctrl+← / → move it by bars, M drops a
//! marker, / turns the loop on or off, G and H zoom out and in, Delete deletes the
//! selected take, Ctrl+R renders / prints what's selected, Ctrl+Z / Ctrl+Y undo and redo,
//! Ctrl+S saves (while no text field has focus).
//! Over the lanes, Shift+wheel scrolls in time, Ctrl+wheel zooms.
//!
//! **Inserts** (docs/SESSION_FX_PLAN.md, F2): under each track's strip its chain of devices
//! (+ adds one; a click selects one, its panel opens at the bottom; right-click bypasses,
//! moves or removes it). **Prints are made when asked for** (docs/SESSION_EDITING_PLAN.md
//! SE1, decision 2): Print on the insert row or in the panel, Print inserts (n) in the
//! session line, Ctrl+R with the track selected. The chain is rendered on the active take
//! in the background (`varimu_app::print`, at most [`MAX_PRINT_JOBS`] at a time, none
//! while recording or while a knob is held), and the track plays that render (a preview:
//! the inserts stay editable): ✓ printed, ◔ printing, … waiting, ○ changed and not printed
//! (the last print plays, stale, or the take dry), ! failed. A chain that isn't current is
//! looked up in the prints' cache by itself (undo finds the old print), never rendered.
//! The first insert's trim is set once from the take's loudest stretch to the alignment
//! level (-18 dBFS); later ones start at 0 dB.
//!
//! **Event takes** (docs/MIDI_TAKES_PLAN.md N1, N3, N4): Record with a device played from
//! the MIDI keyboard records its performance: the device restarts fresh (a defined start,
//! PREPARING while it settles), then the count-in and the take. The lane plays the audio
//! heard; a take's ♪ badge says what it plays (draft (live), proxy, draft, PROD, stale) and
//! what renders. Double-click an event take (or its context menu) for the piano roll
//! (`crate::piano_roll`): each edit is a new revision of the take, one undo step, and
//! **nothing renders until asked** (SE1): the roll's Render, the take's menu, Render edits
//! (n) in the session line, Ctrl+R. Until then an edited take plays its revision through
//! the device's proxy where it has one (made offline at once, `proxy::render_performance`;
//! decision 1), else its last render, stale. Render at production is on demand too (the
//! take's context menu, the roll's ⤓ PROD, or ⤓ Production for every event take); a
//! production render, once there, is what plays
//! unless the track plays drafts (context menu). Each track's strip has ⤓ PROD for its own
//! take (◔ while it renders, PROD ✓ once it plays), and a take's context menu bounces it
//! to audio: its production render (made first if it isn't there) as a new audio take on the
//! track, the MIDI take kept in the lane. Renders run below normal priority, one at a time
//! while a device plays live, none while recording.
//!
//! **Export** (RECORDING_PLAN.md T4's bounce): ⤓ Export mix… writes what ▶ plays
//! ([`Session::mixdown`]) to a stereo float WAV from bar 1 (or the earliest take), a .json
//! of what it was made from beside it, and with "stems" each audible track's part (its
//! fader and pan: they sum to the mix); it waits until every audible track plays what it
//! will ([`Session::export_problems`]). ⤓ Export final… first sets the audible tracks'
//! inserts to production and renders their MIDI takes at production, then waits for that.
//! The track strip's ⤓ Draft bakes a chain at its inserts' play qualities (⤓ Render:
//! production).
//!
//! **Audition** (F3): while an insert's panel is open, that device plays live in the
//! session's player (the Play view's device stops: one live device), fed by the track's
//! audio where the transport is (the prints of the inserts before it, else the take), so
//! Space plays the session with it and its knobs, trim, make-up and bypass are heard as
//! they turn (an instrument playing from the Play view gives way only to a panel just
//! opened, and plays again when it closes; one started while a panel is open closes the
//! panel). The other tracks play their prints; the inserts after it aren't heard. Closing
//! the panel prints nothing (Print does). No recording while auditioning.
//!
//! **Export** with something not rendered or printed waits, and offers "Render them and
//! export"; Export final… asks for every render and print it needs itself.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::mpsc::{self, Receiver};
use std::time::{Duration, Instant};

use eframe::egui::{self, Color32, Pos2, Rect, RichText, Sense, Stroke, StrokeKind};
use serde_json::{Value, json};
use varimu_app::audio;
use varimu_app::deck::{self, Deck, DeckJob};
use varimu_app::live::{Circuit, Values};
use varimu_app::loop_render::{self, Excerpt, Rendered};
use varimu_app::loopback::{self, Analysis, Calibration, Run};
use varimu_app::panel::{self as vpanel, DEVICES, Kind, Knob};
use varimu_app::performance::Performance;
use varimu_app::player::{BLOCK, InputDevice, Player, Source, State, TimelineKey, input_devices};
use varimu_app::prefs::ALIGNMENT_DBFS;
use varimu_app::print::{Job, KeyRoute, NOT_PRINTED, Slot, find_device};
use varimu_app::session::{
    Clip, Marker, Mix, MixClip, Monitor, NO_TRACK, OVERVIEW_BIN, Overview, Placed, Printed,
    Session, Take, Track, default_fade, new_clip_id, take_dir,
};
use varimu_app::settings::{Quality, Settings};
use varimu_app::take_render::{self, NOT_RENDERED};
use varimu_app::transport::{ClickMode, Grid, Phase, Snap, TransportSettings};
use varimu_circuit::spec;
use varimu_circuit::yaml::Value as YValue;

use crate::piano_roll::{self, Roll};
use crate::play_view::{AUDIO_EXT, PlayView};

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
const TRACK_H: f32 = 124.0;
/// The lowest a track's height goes (its strip's controls need it).
const MIN_TRACK_H: f32 = 124.0;
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
    /// A MIDI take's notes so far (the performance's sample of its first sample, the notes).
    notes: Option<(u64, Vec<varimu_app::performance::Note>)>,
}

/// What a drag on a clip does (decided where the press went down).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DragKind {
    Move,
    TrimLeft,
    TrimRight,
    FadeIn,
    FadeOut,
    Gain,
    /// The audio slid under the clip, the clip staying put (SE8).
    Slip,
}

/// The arrangement's tools (SE8; keys 1-5 with the pointer off the piano roll).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Tool {
    /// Select, move, trim, fades and gain (Ctrl+drag slips, Shift+drag copies).
    Pointer,
    /// A click splits the clip there.
    Blade,
    /// A click deletes the clip.
    Erase,
    /// A drag slides the audio inside the clip.
    Slip,
    /// Points on the clip's gain envelope.
    Envelope,
}

impl Tool {
    const ALL: [Tool; 5] = [
        Tool::Pointer,
        Tool::Blade,
        Tool::Erase,
        Tool::Slip,
        Tool::Envelope,
    ];

    fn label(self) -> &'static str {
        match self {
            Tool::Pointer => "⬉ Pointer",
            Tool::Blade => "✂ Blade",
            Tool::Erase => "⌫ Erase",
            Tool::Slip => "⇔ Slip",
            Tool::Envelope => "↗ Envelope",
        }
    }

    fn key(self) -> egui::Key {
        match self {
            Tool::Pointer => egui::Key::Num1,
            Tool::Blade => egui::Key::Num2,
            Tool::Erase => egui::Key::Num3,
            Tool::Slip => egui::Key::Num4,
            Tool::Envelope => egui::Key::Num5,
        }
    }

    fn tip(self) -> &'static str {
        match self {
            Tool::Pointer => {
                "(1) Select and move clips, trim by the edges, fades by the top corners, gain by \
                 the top middle; Ctrl+drag slips the audio, Shift+drag copies the clip"
            }
            Tool::Blade => {
                "(2) A click on a clip splits it there (on the snap; Alt inverts it; on a zero \
                 crossing with that switched on)"
            }
            Tool::Erase => "(3) A click on a clip deletes it (with Ripple, what follows moves up)",
            Tool::Slip => {
                "(4) Drag a clip to slide its audio inside it: the clip stays where it is (by the \
                 snap; Alt inverts it)"
            }
            Tool::Envelope => {
                "(5) The clip's gain envelope: a click adds a point (or removes the one under the \
                 pointer), a drag moves one; from -48 dB at the clip's bottom to +12 dB at its top"
            }
        }
    }
}

/// What a clip's menu (or the toolbar's Clip menu) asks for (SE8).
#[derive(Debug, Clone, Copy, PartialEq)]
enum ClipOp {
    Invert,
    Curve(varimu_app::session::FadeCurve),
    /// Crossfade into the next clip over this many seconds, in this shape.
    Crossfade(f64, varimu_app::session::FadeCurve),
    Reverse,
    Varispeed(f64),
    Transients,
    StripSilence,
    Quantize,
    Consolidate,
    ClearEnvelope,
}

/// A clip being dragged: its track and index, what the drag does, the clip as it was, where
/// the press was.
struct Drag {
    track: usize,
    clip: usize,
    kind: DragKind,
    from: Clip,
    press: Pos2,
}

/// A track's chain printing: what it is made from, the take, the job; `lookup`: only
/// looking for the print in the cache (SE1: a print is made when asked for).
struct PrintJob {
    signature: String,
    lane: String,
    start: i64,
    /// Its lane is stereo: each insert printed dual-mono.
    stereo: bool,
    job: Job,
    cancelled: bool,
    lookup: bool,
    /// The master chain's print (else a track's).
    master: bool,
}

/// An audition's or a selection's track index for the master's inserts.
const MASTER: usize = usize::MAX;

/// The master's input as last summed: the tracks' signature it was made from, and where it
/// starts, its left and right (None: nothing sounds).
type MasterInput = (String, Option<varimu_app::session::Stereo>);

/// A take's proxy stand-in being made on a thread (take id, revision).
struct ProxyJob {
    id: String,
    rev: u32,
    handle: std::thread::JoinHandle<Vec<f32>>,
}

/// An insert playing live (F3): which, what its input is (to see it change), and what
/// was last sent to the player.
/// What a live audition of an insert on a stereo track plays into its one instance
/// (docs/STEREO_PLAN.md ST3: prints run both channels; live, one device fits).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Hear {
    /// The left channel, up the middle: exactly what its print gets.
    Left,
    Right,
    /// (L + R) / 2: exactly neither (a level-dependent device's print will differ).
    Mid,
}

struct Audition {
    track: usize,
    slot: usize,
    device: String,
    input: String,
    values: Values,
    gains: (f64, f64, bool, f64),
}

/// The open insert's loop render (the panel's "⟲ loop": `varimu_app::loop_render`): the
/// render wanted (waiting out a knob being turned), the one rendering, the last one finished
/// and the clip it plays (for its make-up, wet and bypass).
struct LoopState {
    track: usize,
    slot: usize,
    wanted: Option<(String, Instant)>,
    job: Option<(String, Excerpt, Job)>,
    done: Option<Rendered>,
    /// The clip playing: the render's key and the gains it was made with.
    clip: Option<(String, (f64, f64, bool), MixClip)>,
    error: Option<String>,
}

impl Drop for LoopState {
    fn drop(&mut self) {
        if let Some((_, _, j)) = &self.job {
            j.cancel();
        }
    }
}

/// How long the panel's knobs hold still before a loop render starts (a turn renders once).
const LOOP_SETTLE: Duration = Duration::from_millis(300);

/// The loop toggle's hover text (both insert panels).
const LOOP_TIP: &str = "Render the transport's loop through this insert instead of playing it live (for a device too slow to play live): at its play quality, both channels as its print takes them, from 2 s before the loop so it is warmed up; a change of the knobs renders again in the background, the last render plays meanwhile. Make-up, wet and bypass are heard at once.";

/// A track's chain rendering into a new take (⤓ Render): the track, its source take, the
/// job.
struct Bake {
    track: usize,
    /// Where its lane started, and the clips it was made from.
    start: i64,
    /// Its lane is stereo: the render is too (each insert dual-mono).
    stereo: bool,
    clips: Vec<Clip>,
    slots: Vec<Slot>,
    /// At production, else a draft: each insert at its device's play quality.
    production: bool,
    job: Job,
}

/// An event take's render running, or a cache lookup (`wanted` false): which take,
/// revision and quality.
struct TakeJob {
    id: String,
    rev: u32,
    quality: Quality,
    wanted: bool,
    job: take_render::Job,
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
    /// The ruler's context menu: where it was opened and the marker under it.
    ruler_menu: Option<(i64, Option<usize>)>,
    /// The cursor moved while the transport ran: play on from it (next frame).
    relocate: bool,
    /// Insert (true) or delete time between the locators, asked from the ruler's menu.
    time_edit: Option<bool>,
    /// The tracks' height (px; Ctrl+wheel over the strips), the keys overlay shown.
    track_h: f32,
    /// What a stereo track's audition plays (ST3), and the last mid made for one.
    hear: Hear,
    mid_cache: std::cell::RefCell<Option<(String, Arc<Vec<f32>>)>>,
    /// The master's input (the tracks' sum), made once per change of the tracks.
    master_input: std::cell::RefCell<Option<MasterInput>>,
    show_keys: bool,
    /// The clip menu's normalize targets (dBFS): its peak, its level (as an import's).
    normalize_peak_dbfs: f64,
    normalize_level_dbfs: f64,
    /// SE8's editing: the arrangement's tool, deletes closing their gaps (Ripple), splits
    /// moved to the nearest zero crossing (prefs, both); an envelope point being dragged
    /// (track, clip, point); the clip menu's settings (transient sensitivity, strip silence's
    /// threshold, varispeed, a crossfade's length); a bounce mutes its sources; the last
    /// edit's outcome, shown on the toolbar.
    tool: Tool,
    ripple: bool,
    zero_cross: bool,
    env_drag: Option<(usize, usize, usize)>,
    transient_db: f64,
    silence_dbfs: f64,
    varispeed_st: f64,
    xfade_ms: f64,
    bounce_mute: bool,
    /// The tape deck's window shown (docs/PERIOD_GEAR_BACKLOG.md MT6).
    deck_open: bool,
    /// The deck's print (or its lookup in the cache) running.
    deck_job: Option<DeckJob>,
    /// Deck signatures already looked up in the cache, and why the last print failed.
    deck_looked_up: HashSet<String>,
    deck_error: Option<String>,
    edit_note: Option<String>,
    /// Where play last stopped (Shift+Space plays from there).
    stopped_at: Option<i64>,
    /// The lanes' width as last drawn (px): G and H zoom about its middle.
    lanes_w: f64,
    /// A drag on the scrollbar's thumb: where it started (px) and the view then (s).
    scroll_drag: Option<(f32, f64)>,
    /// The selected clip (track, index), a drag in progress, the right-clicked clip, a
    /// comp being dragged across a take's row (track, take, where it started).
    selected: Option<(usize, usize)>,
    drag: Option<Drag>,
    menu_clip: Option<(usize, usize)>,
    comp: Option<(usize, usize, i64)>,
    /// The clipboard (SE6), a range selected across tracks (from, to, first and last
    /// track), the range being dragged (its track and start), the roll's area last frame
    /// (keys over it are the roll's).
    clipboard: Vec<varimu_app::session::Copied>,
    range_sel: Option<(i64, i64, usize, usize)>,
    range_drag: Option<(usize, i64)>,
    roll_rect: Option<Rect>,
    /// The lanes as last frame drew them (a clip dropped on another track finds it).
    prev_lanes: Vec<(usize, Rect)>,
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
    /// Tracks (by id) whose print was asked for and hasn't started (SE1); chains already
    /// looked up in the cache (by signature).
    print_wanted: HashSet<String>,
    looked_up: HashSet<String>,
    /// Renders of event takes asked for and not started yet (take, revision, quality).
    render_queue: Vec<(String, u32, Quality)>,
    /// Each device's proxy tables (None: it has none), and the stand-ins being made.
    proxy_tables: HashMap<String, Option<Arc<varimu_app::proxy::Tables>>>,
    proxy_jobs: Vec<ProxyJob>,
    proxy_tried: HashSet<(String, u32)>,
    insert_sel: Option<(usize, usize)>,
    /// The master's insert whose panel is open (a track's insert closes it, and it theirs).
    master_sel: Option<usize>,
    /// The master's print asked for (SE1: made when asked for).
    master_wanted: bool,
    knobs: HashMap<String, Result<Vec<Knob>, String>>,
    audition: Option<Audition>,
    /// The audition's state as the panel shows it (set each frame).
    audition_status: Option<String>,
    /// The insert panel renders the loop instead of playing its device live ("⟲ loop").
    loop_mode: bool,
    loop_render: Option<LoopState>,
    bake: Option<Bake>,
    /// The tracks-only player couldn't start (don't retry every frame).
    mix_failed: bool,
    /// Record was pressed while no instrument played: record once it plays.
    record_pending: bool,
    /// The user opened an insert's panel this frame (an audition may take an instrument's
    /// place only then), and the instrument to start again when the audition ends.
    audition_request: bool,
    resume_instrument: bool,
    /// Event takes' renders and lookups running, the ones started (take, revision,
    /// quality, rendering or only looking), the ones that failed, the last piano-roll edit.
    take_jobs: Vec<TakeJob>,
    tried: HashSet<(String, u32, Quality, bool)>,
    take_errors: HashMap<(String, u32, Quality), String>,
    roll: Option<Roll>,
    /// The Play view's device has a proxy (set every frame: the strips offer it).
    proxy_available: bool,
    /// Event takes to bounce to audio once their production render lands (take, revision).
    bounces: HashSet<(String, u32)>,
    /// ⤓ Export: waiting for the tracks, or writing.
    export: Option<Export>,
    /// ⤓ Export writes each track's part too.
    export_stems: bool,
    /// The last export's outcome (the file, its peak).
    export_note: Option<String>,
    /// Import…: audio files decoding into new tracks.
    import: Option<Import>,
    /// The last import's outcome.
    import_note: Option<String>,
    /// How Import… normalizes, and to what level (dBFS: the loudest 8 s' rms as a sine's
    /// peak); prefs.
    import_normalize: ImportNormalize,
    import_target_dbfs: f64,
    /// This frame's track lanes as seen (the part inside the scroll area), for files
    /// dragged in from a folder: (track, rect).
    lanes: Vec<(usize, Rect)>,
    /// The tracks' and the master's meters as shown (SE4).
    meters: crate::mixer::MeterBank,
}

/// Audio files picked by Import… or dropped on the view, decoding on a thread (each its
/// path and its samples, mono or stereo at the session's rate), and where they go.
struct Import {
    files: usize,
    normalize: ImportNormalize,
    dest: ImportDest,
    handle: std::thread::JoinHandle<Vec<Decoded>>,
}

/// Where imported files go: new tracks at bar 1 (Import…, or files dropped off the lanes),
/// or takes on the track they were dropped on (by id) at `position`, one file per track
/// from there down, new tracks past the last.
#[derive(Clone, Debug)]
enum ImportDest {
    NewTracks,
    Onto { track: String, position: i64 },
}

/// An imported file and its samples (left or mono, and a stereo file's right) with the
/// gain (dB) normalizing gave them, or why it couldn't be read.
type Decoded = (PathBuf, Result<(Vec<f32>, Option<Vec<f32>>, f64), String>);

/// A new audio track: its name, pan, its take's samples (left or mono, a stereo take's
/// right), timeline position and what it came from.
type NewAudioTrack = (String, f64, Vec<f32>, Option<Vec<f32>>, i64, Value);

/// How Import… normalizes: not at all, each file's loudest stretch to the target, or one
/// gain for all the files picked together, from their sum (stems keep their balance).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ImportNormalize {
    Off,
    Each,
    Together,
}

impl ImportNormalize {
    const ALL: [ImportNormalize; 3] = [
        ImportNormalize::Off,
        ImportNormalize::Each,
        ImportNormalize::Together,
    ];

    fn name(self) -> &'static str {
        match self {
            ImportNormalize::Off => "off",
            ImportNormalize::Each => "each",
            ImportNormalize::Together => "together",
        }
    }

    fn label(self) -> &'static str {
        match self {
            ImportNormalize::Off => "don't normalize",
            ImportNormalize::Each => "normalize each file",
            ImportNormalize::Together => "normalize together",
        }
    }

    fn from_name(s: &str) -> ImportNormalize {
        Self::ALL
            .into_iter()
            .find(|m| m.name() == s)
            .unwrap_or(ImportNormalize::Off)
    }
}

/// The stretch normalizing measures (s): a file's loudest, as the Play view does.
const NORMALIZE_LOUDEST_S: f64 = 8.0;

/// An export of the mix ([`Session::mixdown`]): waiting until every audible track plays
/// what it will (`fin`: at production), then written on a thread.
enum Export {
    Waiting {
        path: PathBuf,
        stems: bool,
        fin: bool,
    },
    Writing {
        path: PathBuf,
        handle: std::thread::JoinHandle<Result<f64, String>>,
    },
}

/// The view's prefs (`%APPDATA%\varimu\recording.json`); none in tests, which must never
/// read or write the user's.
fn prefs_path() -> Option<PathBuf> {
    if cfg!(test) {
        return None;
    }
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

/// A new session in its own new folder, everything at the defaults: the rate, the transport
/// (tempo, meter, click, locators), no tracks; its room starts as the default room (it has
/// no `rooms/scene.json`).
fn fresh_session(repo: &Path) -> Session {
    Session::new(
        new_session_dir(repo),
        DEFAULT_RATE,
        TransportSettings::default(),
    )
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
    // Moving the cursor isn't an edit (SE2).
    v["transport"]["cursor"] = Value::Null;
    if let Some(tracks) = v["tracks"].as_array_mut() {
        for t in tracks {
            t["show_takes"] = Value::Null;
        }
    }
    v
}

impl SessionView {
    /// The app starts on a fresh session (the defaults' rate and transport, an empty
    /// room), never the last one: Open… brings that back.
    pub fn new(repo: &Path) -> SessionView {
        let (calibrations, (import_normalize, import_target_dbfs)) = load_prefs();
        let mut v = SessionView::with_session(repo, fresh_session(repo), false, calibrations);
        v.import_normalize = import_normalize;
        v.import_target_dbfs = import_target_dbfs;
        (v.ripple, v.zero_cross) = load_edit_prefs();
        v
    }

    /// A view on `session` (its prefs not read: tests use this on a scratch session).
    pub(crate) fn with_session(
        repo: &Path,
        session: Session,
        saved: bool,
        calibrations: Vec<Calibration>,
    ) -> SessionView {
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
            ruler_menu: None,
            relocate: false,
            time_edit: None,
            track_h: TRACK_H,
            hear: Hear::Left,
            mid_cache: std::cell::RefCell::new(None),
            master_input: std::cell::RefCell::new(None),
            show_keys: false,
            normalize_peak_dbfs: -1.0,
            normalize_level_dbfs: -18.0,
            tool: Tool::Pointer,
            ripple: false,
            zero_cross: false,
            env_drag: None,
            transient_db: 9.0,
            silence_dbfs: -45.0,
            varispeed_st: 0.0,
            xfade_ms: 10.0,
            bounce_mute: false,
            deck_open: false,
            deck_job: None,
            deck_looked_up: HashSet::new(),
            deck_error: None,
            edit_note: None,
            stopped_at: None,
            lanes_w: 800.0,
            scroll_drag: None,
            selected: None,
            drag: None,
            menu_clip: None,
            comp: None,
            clipboard: Vec::new(),
            range_sel: None,
            range_drag: None,
            roll_rect: None,
            prev_lanes: Vec::new(),
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
            error: None,
            jobs: Vec::new(),
            print_errors: HashMap::new(),
            print_wanted: HashSet::new(),
            looked_up: HashSet::new(),
            render_queue: Vec::new(),
            proxy_tables: HashMap::new(),
            proxy_jobs: Vec::new(),
            proxy_tried: HashSet::new(),
            insert_sel: None,
            master_sel: None,
            master_wanted: false,
            knobs: HashMap::new(),
            audition: None,
            audition_status: None,
            loop_mode: false,
            loop_render: None,
            bake: None,
            mix_failed: false,
            record_pending: false,
            audition_request: false,
            resume_instrument: false,
            take_jobs: Vec::new(),
            tried: HashSet::new(),
            take_errors: HashMap::new(),
            roll: None,
            proxy_available: false,
            bounces: HashSet::new(),
            export: None,
            export_stems: false,
            export_note: None,
            import: None,
            import_note: None,
            lanes: Vec::new(),
            meters: crate::mixer::MeterBank::default(),
            import_normalize: ImportNormalize::Off,
            import_target_dbfs: ALIGNMENT_DBFS,
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
            "calibrations": cals,
            "import_normalize": self.import_normalize.name(),
            "import_target_dbfs": self.import_target_dbfs,
            "ripple": self.ripple,
            "zero_crossings": self.zero_cross,
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

    /// The session, for the Room view.
    pub fn session(&self) -> &Session {
        &self.session
    }

    /// New audio tracks (name, pan, samples at the session's rate, timeline position, what
    /// they came from: a room's render, an imported file), each its rendered take; the
    /// next frame of this view makes them one undo step.
    pub fn add_audio_tracks(
        &mut self,
        tracks: Vec<(String, f64, Vec<f32>, i64, Value)>,
    ) -> Result<(), String> {
        self.add_audio_tracks_lr(
            tracks
                .into_iter()
                .map(|(name, pan, x, position, from)| (name, pan, x, None, position, from))
                .collect(),
        )
    }

    /// [`Self::add_audio_tracks`] whose takes may be stereo (left, then `Some(right)`).
    fn add_audio_tracks_lr(&mut self, tracks: Vec<NewAudioTrack>) -> Result<(), String> {
        self.saved = true;
        for (name, pan, samples, right, position, from) in tracks {
            let mut t = Track::new(&name);
            t.pan = pan;
            t.midi = false;
            self.session.tracks.push(t);
            let i = self.session.tracks.len() - 1;
            self.session
                .add_rendered_take(i, samples, right, position, from)?;
        }
        self.save();
        Ok(())
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
        self.show(ui, play, false);
    }

    /// The Mixer tab (SE4): the same session, transport and panels, the strips side by
    /// side in place of the arrangement.
    pub fn mixer_ui(&mut self, ui: &mut egui::Ui, play: &mut PlayView) {
        self.show(ui, play, true);
    }

    fn show(&mut self, ui: &mut egui::Ui, play: &mut PlayView, mixer: bool) {
        play.tick(ui.ctx());
        // The meters: the player's readings since the last frame (none: they fall).
        let readings = play.player().map(|p| p.take_meters());
        self.meters
            .update(readings.as_ref(), self.session.tracks.len());
        play.live_controls();
        self.poll_calibration(play);
        let idle = matches!(self.calibrate, Calibrate::Idle);
        self.sync_audition(play, idle);
        // A loop render waiting for the knobs or rendering: its line keeps moving.
        if self
            .loop_render
            .as_ref()
            .is_some_and(|l| l.wanted.is_some() || l.job.is_some())
        {
            ui.ctx().request_repaint_after(Duration::from_millis(100));
        }
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
        self.poll_export(ui.ctx());
        self.poll_import(ui.ctx());
        if idle {
            if self.audition.is_none() {
                play.apply_monitor();
            }
            if let Some(p) = play.player() {
                p.set_transport(&self.session.transport);
                let mix = match &self.audition {
                    Some(a) if a.track == MASTER => self.session.mix_master_audition(),
                    Some(a) => self.session.mix_audition(a.track),
                    None => self.loop_mix().unwrap_or_else(|| self.session.mix()),
                };
                p.set_mix(Arc::new(mix));
            }
        }
        // The armed track's monitor: the device or its proxy (a keyboard playing restarts on
        // the other, never while recording).
        if self.recording.is_none()
            && !play.player().is_some_and(|p| p.take_armed())
            && let Some(t) = self.session.armed.and_then(|i| self.session.tracks.get(i))
        {
            play.set_monitor_proxy(t.monitor == Monitor::Proxy && t.midi && play.has_proxy());
        }
        self.proxy_available = play.has_proxy();
        self.poll_recording(play);
        let armed = play.player().is_some_and(|p| p.take_armed());
        self.poll_prints(ui.ctx(), armed);
        self.poll_deck(ui.ctx());
        let live = play.player().is_some() && !play.adopted();
        self.poll_take_renders(ui.ctx(), armed, live);
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
        if self.master_selected().is_some() {
            egui::Panel::bottom("session_master_insert")
                .frame(
                    egui::Frame::NONE
                        .fill(theme::CHROME2)
                        .inner_margin(egui::Margin::symmetric(14, 10)),
                )
                .show(ui, |ui| self.master_panel(ui));
        } else if self.insert_selected().is_some() {
            egui::Panel::bottom("session_insert")
                .frame(
                    egui::Frame::NONE
                        .fill(theme::CHROME2)
                        .inner_margin(egui::Margin::symmetric(14, 10)),
                )
                .show(ui, |ui| self.insert_panel(ui));
        }
        if self.roll.is_none() || mixer {
            self.roll_rect = None;
        }
        if self.roll.is_some() && !mixer {
            egui::Panel::bottom("session_roll")
                .resizable(true)
                .default_size(320.0)
                .frame(
                    egui::Frame::NONE
                        .fill(theme::CHROME2)
                        .inner_margin(egui::Margin::symmetric(10, 6)),
                )
                .show(ui, |ui| self.roll_ui(ui, play));
        }
        egui::CentralPanel::default()
            .frame(egui::Frame::NONE.fill(theme::CANVAS))
            .show(ui, |ui| {
                if mixer {
                    self.mixer(ui);
                } else {
                    self.arrangement(ui, play);
                }
            });
        if self.deck_open {
            let mut open = true;
            egui::Window::new("Tape deck")
                .open(&mut open)
                .collapsible(false)
                .resizable(false)
                .default_pos(ui.max_rect().center() - egui::vec2(220.0, 160.0))
                .show(ui.ctx(), |ui| self.deck_window(ui));
            self.deck_open = open;
        }
        if self.show_keys {
            let mut open = true;
            egui::Window::new("Keys")
                .open(&mut open)
                .collapsible(false)
                .resizable(false)
                .default_pos(ui.max_rect().center() - egui::vec2(260.0, 220.0))
                .show(ui.ctx(), keys_overlay);
            self.show_keys = open;
        }
        // The cursor moved while playing: play on from there (not while recording).
        if std::mem::take(&mut self.relocate)
            && !play.player().is_some_and(|p| p.take_armed())
            && self.recording.is_none()
        {
            let keep = self.session.transport.cursor;
            self.stop(play);
            self.session.transport.cursor = keep;
            if let Some(p) = play.player() {
                p.set_transport(&self.session.transport);
            }
            self.play(play, false);
        }
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
        let (redo, save, render) = ui.input(|i| {
            (
                i.modifiers.command
                    && (i.key_pressed(egui::Key::Y)
                        || (i.key_pressed(egui::Key::Z) && i.modifiers.shift)),
                i.modifiers.command && i.key_pressed(egui::Key::S),
                i.modifiers.command && i.key_pressed(egui::Key::R),
            )
        });
        // Ctrl+R: the roll's take, else the selected take, else the selected track: its
        // take's render and its print, whichever isn't current (SE1).
        if render {
            let at = match (&self.roll, self.selected) {
                (Some(r), _) => self.session.tracks.get(r.track).and_then(|t| {
                    t.takes
                        .iter()
                        .position(|k| k.id == r.take)
                        .map(|k| (r.track, Some(k)))
                }),
                (None, Some((t, c))) => self.session.tracks.get(t).and_then(|x| {
                    let id = &x.clips.get(c)?.take;
                    Some((t, x.take_index(id)))
                }),
                (None, None) => self.session.armed.map(|t| (t, None)),
            };
            if let Some((t, k)) = at {
                self.render_track(t, k);
            }
        }
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
        // The cursor: Home to bar 1, End to the session's end, Ctrl+← / → by bars, M
        // drops a marker.
        let (home, end, left, right, marker, shift_space) = ui.input(|i| {
            (
                i.key_pressed(egui::Key::Home),
                i.key_pressed(egui::Key::End),
                i.modifiers.command && i.key_pressed(egui::Key::ArrowLeft),
                i.modifiers.command && i.key_pressed(egui::Key::ArrowRight),
                i.key_pressed(egui::Key::M) && !i.modifiers.command,
                i.modifiers.shift && i.key_pressed(egui::Key::Space),
            )
        });
        let grid = Grid::new(self.session.rate, &self.session.transport);
        if home {
            self.move_cursor(0, play);
        }
        if end {
            self.move_cursor(self.session.end(), play);
        }
        if left || right {
            let c = self.session.transport.cursor;
            let bar = grid.bar_at(c);
            let to = if right {
                grid.bar(bar + 1)
            } else if grid.bar(bar) < c {
                grid.bar(bar)
            } else {
                grid.bar(bar - 1)
            };
            self.move_cursor(to, play);
        }
        if marker {
            let at = play
                .player()
                .map(|p| p.status().transport)
                .filter(|t| t.running)
                .map_or(self.session.transport.cursor, |t| t.heard.max(0));
            self.add_marker(at);
        }
        // ? (Shift+/) shows the keys; / turns the loop on or off.
        let question = ui.input(|i| {
            i.events
                .iter()
                .any(|e| matches!(e, egui::Event::Text(t) if t == "?"))
        });
        if question {
            self.show_keys = !self.show_keys;
        } else if slash {
            self.session.transport.loop_on = !self.session.transport.loop_on;
            self.save();
        }
        if zoom_out {
            self.zoom(0.5, Some(self.lanes_w * 0.5));
        }
        if zoom_in {
            self.zoom(2.0, Some(self.lanes_w * 0.5));
        }
        // Delete removes the selected range or clip (its take stays in the pool), S splits it
        // (none selected: the armed track's clip under the cursor) at the cursor.
        let over_roll = self
            .roll_rect
            .zip(ui.input(|i| i.pointer.hover_pos()))
            .is_some_and(|(r, p)| r.contains(p));
        if delete && self.roll.is_none() && self.recording.is_none() {
            self.delete_selection();
        }
        // The tools (1-5) and nudges (← / →: a snap step, or 10 ms with the snap off; Alt:
        // a sample), with the pointer off the roll (SE8).
        if !over_roll && self.recording.is_none() {
            let (tool, nudge) = ui.input(|i| {
                let tool = (!i.modifiers.any())
                    .then(|| Tool::ALL.into_iter().find(|t| i.key_pressed(t.key())))
                    .flatten();
                let dir = if i.modifiers.command {
                    0
                } else if i.key_pressed(egui::Key::ArrowLeft) {
                    -1
                } else if i.key_pressed(egui::Key::ArrowRight) {
                    1
                } else {
                    0
                };
                (tool, (dir, i.modifiers.alt))
            });
            if let Some(t) = tool {
                self.tool = t;
            }
            if nudge.0 != 0 {
                self.nudge(nudge.0, nudge.1);
            }
        }
        // The clipboard (SE6): Ctrl+C / X / V / D on the selected range or clip.
        if !over_roll && self.recording.is_none() {
            let (copy, cut, paste, dup) = ui.input(|i| {
                let mut c = (false, false, false, false);
                for e in &i.events {
                    match e {
                        egui::Event::Copy => c.0 = true,
                        egui::Event::Cut => c.1 = true,
                        egui::Event::Paste(_) => c.2 = true,
                        egui::Event::Key {
                            key: egui::Key::C,
                            pressed: true,
                            modifiers,
                            ..
                        } if modifiers.command => c.0 = true,
                        egui::Event::Key {
                            key: egui::Key::X,
                            pressed: true,
                            modifiers,
                            ..
                        } if modifiers.command => c.1 = true,
                        egui::Event::Key {
                            key: egui::Key::V,
                            pressed: true,
                            modifiers,
                            ..
                        } if modifiers.command => c.2 = true,
                        egui::Event::Key {
                            key: egui::Key::D,
                            pressed: true,
                            modifiers,
                            ..
                        } if modifiers.command => c.3 = true,
                        _ => {}
                    }
                }
                c
            });
            if copy || cut {
                self.copy_selection(cut);
            }
            if paste {
                self.paste_clipboard();
            }
            if dup {
                self.duplicate_selection();
            }
        }
        let split = ui.input(|i| i.key_pressed(egui::Key::S) && !i.modifiers.command);
        if split
            && self.roll.is_none()
            && self.recording.is_none()
            && let Some((t, c)) = self.split_target()
            && self.clip_action(t, c, "split")
        {
            self.save();
        }
        if undo {
            self.undo();
        }
        let running = play.player().is_some_and(|p| p.status().transport.running);
        if space {
            if running {
                self.stop(play);
            } else {
                // Shift+Space: from where play last stopped.
                if shift_space && let Some(at) = self.stopped_at {
                    self.session.transport.cursor = at;
                    self.save();
                }
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
        let midi = self
            .session
            .armed
            .and_then(|i| self.session.tracks.get(i))
            .is_none_or(|t| t.midi);
        if record && midi && play.plays_keys() {
            // The device restarts fresh, then the transport and the take (PREPARING).
            let (_, id) = play.device_label_id();
            p.begin_event_take(&id);
        } else {
            p.arm_take(record);
            p.transport_run(true);
        }
        self.error = None;
    }

    /// Stop: the playhead back at the cursor, or (return off) the cursor where play
    /// stopped, so the next play goes on from there.
    fn stop(&mut self, play: &PlayView) {
        if let Some(p) = play.player() {
            let st = p.status().transport;
            p.arm_take(false);
            p.transport_run(false);
            if st.running {
                self.stopped_at = Some(st.heard.max(0));
                if !self.session.transport.return_to_cursor {
                    self.session.transport.cursor = st.heard.max(0);
                    self.save();
                }
            }
        }
    }

    /// A marker at `pos`, named by its count.
    fn add_marker(&mut self, pos: i64) {
        let n = (1..)
            .find(|n| !self.session.markers.iter().any(|m| m.name == n.to_string()))
            .unwrap_or(1);
        self.session.markers.push(Marker {
            position: pos,
            name: n.to_string(),
        });
        self.session.markers.sort_by_key(|m| m.position);
        self.save();
    }

    /// Move the cursor to `pos` (from bar 1), relocating a running transport (not while
    /// recording).
    fn move_cursor(&mut self, pos: i64, play: &PlayView) {
        self.session.transport.cursor = pos.max(0);
        self.relocate = play.player().is_some_and(|p| p.status().transport.running);
        self.save();
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

    /// New: a fresh session (everything at its defaults) in place of this one.
    pub(crate) fn new_session(&mut self) {
        let s = fresh_session(&self.root);
        self.switch_to(s, false);
        self.error = None;
    }

    /// Another session in place of this one (its history with it). Nothing of the old one
    /// carries over: work running for it is cancelled (a print, a render or a bake would
    /// land on the new session's tracks and takes, whose indices and ids can repeat), its
    /// selections, panels, clipboard and caches are dropped, and the view goes back to the
    /// first bar. An insert playing live stops with its panel (next frame). The Room view follows
    /// the session's folder (`RoomView::sync_session`).
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
        // Work running for the old session.
        for j in self.jobs.drain(..) {
            j.job.cancel();
        }
        for j in self.take_jobs.drain(..) {
            j.job.cancel();
        }
        if let Some(b) = self.bake.take() {
            b.job.cancel();
        }
        self.proxy_jobs.clear();
        self.import = None;
        self.import_note = None;
        if matches!(self.export, Some(Export::Waiting { .. })) {
            self.export = None;
        }
        self.export_note = None;
        self.render_queue.clear();
        self.loop_render = None;
        if let Some(j) = self.deck_job.take() {
            j.cancel();
        }
        self.deck_looked_up.clear();
        self.deck_error = None;
        self.record_pending = false;
        self.recording = None;
        // What pointed into it: selections, menus, panels, the roll.
        self.selected = None;
        self.drag = None;
        self.menu_clip = None;
        self.comp = None;
        self.clipboard.clear();
        self.range_sel = None;
        self.range_drag = None;
        self.roll = None;
        self.roll_rect = None;
        self.ruler_drag = None;
        self.ruler_menu = None;
        self.time_edit = None;
        self.relocate = false;
        self.insert_sel = None;
        self.master_sel = None;
        self.master_wanted = false;
        self.save_as = None;
        self.prev_lanes.clear();
        self.lanes.clear();
        // What was learned about it.
        self.print_errors.clear();
        self.print_wanted.clear();
        self.looked_up.clear();
        self.proxy_tried.clear();
        self.tried.clear();
        self.take_errors.clear();
        self.bounces.clear();
        *self.mid_cache.borrow_mut() = None;
        *self.master_input.borrow_mut() = None;
        self.meters = crate::mixer::MeterBank::default();
        self.mix_failed = false;
        // The view: bar 1 at the default zoom.
        self.stopped_at = None;
        self.scroll_drag = None;
        self.view_s = -0.5;
        self.px_per_s = 40.0;
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
        let id = track.takes.remove(k).id;
        // Its clips leave the lane with it.
        track.clips.retain(|c| c.take != id);
        track.active = match track.active {
            _ if track.takes.is_empty() => None,
            Some(a) if a == k => Some(track.takes.len() - 1),
            Some(a) if a > k => Some(a - 1),
            a => a,
        };
        self.selected = None;
        self.save();
    }

    /// Track `t` moved to place `to` (the others shift; ids, routes and the armed track
    /// follow it).
    fn move_track(&mut self, t: usize, to: usize) {
        let n = self.session.tracks.len();
        if t >= n || to >= n || t == to || self.recording.is_some() {
            return;
        }
        let armed = self
            .session
            .armed
            .map(|a| self.session.tracks[a].id.clone());
        let track = self.session.tracks.remove(t);
        self.session.tracks.insert(to, track);
        self.session.armed = armed.and_then(|id| self.session.track_index(&id));
        self.selected = None;
        self.range_sel = None;
        self.insert_sel = None;
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
                    notes: None,
                });
                r.overview.extend(&tail);
                r.len = len;
                r.notes = p.take_notes();
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
            let monitor = if play.monitor_proxy() {
                Monitor::Proxy
            } else {
                Monitor::Device
            };
            self.saved = true;
            match self.session.add_take_heard(track, rec, &device, monitor) {
                Ok(_) => self.save_prefs(),
                Err(e) => self.error = Some(e),
            }
        }
    }

    /// The selected insert's input for an audition: the print of the inserts before it
    /// (if the track's print holds it), else the active take; where it starts, and a key
    /// that changes when it does.
    fn audition_input(&self, t: usize, k: usize) -> Option<(Arc<Vec<f32>>, i64, String)> {
        let track = self.session.tracks.get(t)?;
        let (start, lane, lane_r) = track.lane_lr()?;
        let sig = track.source_signature();
        let stage = track.inserts[..k].iter().filter(|s| !s.bypass).count();
        let printed = track
            .printed
            .as_ref()
            .filter(|p| p.lane == sig && stage > 0 && p.stages.len() >= stage);
        let (audio, right) = match printed {
            Some(p) => (
                p.stages[stage - 1].clone(),
                p.stages_right.get(stage - 1).cloned(),
            ),
            None => (lane, lane_r),
        };
        // A stereo input plays one instance (docs/STEREO_PLAN.md ST3): the channel picked,
        // or their mid (made once per input).
        let (audio, hear) = match (right, self.hear) {
            (None, _) | (Some(_), Hear::Left) => (audio, ""),
            (Some(r), Hear::Right) => (r, "R"),
            (Some(r), Hear::Mid) => {
                let id = format!("{:p}|{:p}", Arc::as_ptr(&audio), Arc::as_ptr(&r));
                let mut cache = self.mid_cache.borrow_mut();
                let mid = match cache.as_ref() {
                    Some((i, m)) if *i == id => m.clone(),
                    _ => {
                        let m: Arc<Vec<f32>> = Arc::new(
                            audio
                                .iter()
                                .zip(r.iter())
                                .map(|(a, b)| 0.5 * (a + b))
                                .collect(),
                        );
                        *cache = Some((id, m.clone()));
                        m
                    }
                };
                (mid, "M")
            }
        };
        let key = format!(
            "{}|{}|{}|{}|{:p}|{}|{hear}",
            sig,
            stage,
            start,
            audio.len(),
            Arc::as_ptr(&audio),
            self.session.key_signature(t, &track.inserts[k])
        );
        Some((audio, start, key))
    }

    /// Track `t`'s insert `k`'s input, both channels: the print of the inserts before it (if
    /// the track's print holds it), else the active take; where it starts.
    fn insert_input_lr(&self, t: usize, k: usize) -> Option<Placed> {
        let track = self.session.tracks.get(t)?;
        let (start, lane, lane_r) = track.lane_lr()?;
        let sig = track.source_signature();
        let stage = track.inserts[..k].iter().filter(|s| !s.bypass).count();
        let printed = track
            .printed
            .as_ref()
            .filter(|p| p.lane == sig && stage > 0 && p.stages.len() >= stage);
        Some(match printed {
            Some(p) => (
                start,
                p.stages[stage - 1].clone(),
                p.stages_right.get(stage - 1).cloned(),
            ),
            None => (start, lane, lane_r),
        })
    }

    /// The master's insert `k`'s input, both channels: the master print's stage before it (if
    /// that print is of the tracks as they are), else the tracks' sum; where it starts.
    fn master_input_lr(&self, k: usize) -> Option<Placed> {
        let (start, l, r) = self.master_input()?;
        let mix = self.session.master_mix_signature();
        let stage = self.session.master_inserts[..k]
            .iter()
            .filter(|s| !s.bypass)
            .count();
        let printed = self
            .session
            .master_printed
            .as_ref()
            .filter(|p| p.lane == mix && stage > 0 && p.stages.len() >= stage);
        Some(match printed {
            Some(p) => (
                p.start,
                p.stages[stage - 1].clone(),
                Some(
                    p.stages_right
                        .get(stage - 1)
                        .cloned()
                        .unwrap_or_else(|| p.stages[stage - 1].clone()),
                ),
            ),
            None => (start, l, Some(r)),
        })
    }

    /// The loop render of insert `k` on track `t` (or the master): its excerpt over the
    /// transport's loop, rendered again in the background once the panel holds still for
    /// [`LOOP_SETTLE`], the last render's clip kept for the mix ([`SessionView::loop_mix`]),
    /// and the panel's status line.
    fn sync_loop(&mut self, t: usize, k: usize, running: bool) {
        let rate = self.session.rate;
        let slot = if t == MASTER {
            self.session.master_inserts.get(k).cloned()
        } else {
            self.session
                .tracks
                .get(t)
                .and_then(|x| x.inserts.get(k).cloned())
        };
        let Some(slot) = slot else {
            self.loop_render = None;
            return;
        };
        if self
            .loop_render
            .as_ref()
            .is_none_or(|l| l.track != t || l.slot != k)
        {
            self.loop_render = Some(LoopState {
                track: t,
                slot: k,
                wanted: None,
                job: None,
                done: None,
                clip: None,
                error: None,
            });
        }
        let quality = find_device(&slot.device).map_or(slot.quality, |d| d.quality);
        let rs = loop_render::render_slot(&slot, quality);
        // What would render: the input as the session holds it (its buffers, stable from
        // frame to frame, and what they are of), the loop, the slot. The excerpt is cut only
        // when a render starts.
        let tr = &self.session.transport;
        let wanted = if !tr.loop_on {
            Err("turn the loop on (its L and R are what renders)")
        } else {
            let grid = Grid::new(rate, tr);
            let range = (grid.beat(tr.left_beat), grid.beat(tr.right_beat));
            let (input, what) = if t == MASTER {
                (
                    self.master_input_lr(k),
                    format!("master|{}", self.session.master_mix_signature()),
                )
            } else {
                (
                    self.insert_input_lr(t, k),
                    format!(
                        "{}|{}",
                        self.session.tracks[t].source_signature(),
                        self.session.key_signature(t, &slot)
                    ),
                )
            };
            input
                .and_then(|placed| {
                    let (start, l, r) = &placed;
                    let span = loop_render::span(*start, l.len(), range, rate)?;
                    let id = format!(
                        "{what}|{k}|{start}|{}|{:p}|{:?}",
                        l.len(),
                        Arc::as_ptr(l),
                        r.as_ref().map(Arc::as_ptr)
                    );
                    Some((loop_render::key(&rs, &id, span), placed, range))
                })
                .ok_or("nothing to play in the loop")
        };
        let config = self.root.join("config");
        let settled = self
            .loop_render
            .as_ref()
            .and_then(|st| st.wanted.as_ref())
            .is_some_and(|(_, at)| at.elapsed() >= LOOP_SETTLE);
        // The excerpt (and the key track's audio), cut when a render starts.
        let excerpt = match &wanted {
            Ok((_, (start, l, r), range)) if settled => {
                let side = if t == MASTER {
                    None
                } else {
                    self.session.sidechain(t, &slot)
                };
                loop_render::excerpt(
                    *start,
                    l,
                    r.as_deref().map(Vec::as_slice),
                    side.as_deref().map(Vec::as_slice),
                    *range,
                    rate,
                )
            }
            _ => None,
        };
        let st = self.loop_render.as_mut().expect("just made");
        // A render finished.
        if st.job.as_ref().is_some_and(|(_, _, j)| j.is_finished()) {
            let (key, ex, job) = st.job.take().expect("a job");
            match job.join() {
                Some(Ok(prints)) => {
                    st.done = prints.first().map(|p| Rendered::new(key, &ex, p));
                    st.error = None;
                }
                Some(Err(e)) => st.error = Some(e),
                None => {}
            }
        }
        let status = match wanted {
            Err(m) => format!("⟲ loop: {m}"),
            Ok((key, _, _)) => {
                let current = st.done.as_ref().is_some_and(|d| d.key == key)
                    || st.job.as_ref().is_some_and(|(j, _, _)| *j == key);
                if current {
                    st.wanted = None;
                } else if st.wanted.as_ref().is_none_or(|(w, _)| *w != key) {
                    st.wanted = Some((key, Instant::now()));
                } else if let Some(ex) = excerpt {
                    // The panel held still: render.
                    let (key, _) = st.wanted.take().expect("wanted");
                    if let Some((_, _, old)) = st.job.take() {
                        old.cancel();
                    }
                    let job = Job::spawn(
                        config,
                        vec![rs],
                        vec![ex.side.clone()],
                        ex.left.clone(),
                        ex.right.clone(),
                        rate,
                        None,
                    );
                    st.job = Some((key, ex, job));
                }
                let heard = if running {
                    ", playing"
                } else {
                    " (Space plays)"
                };
                match (&st.job, &st.done, &st.error) {
                    (Some((_, _, j)), done, _) => format!(
                        "⟲ loop: rendering {:.0}% at {}{}",
                        j.progress().1 * 100.0,
                        quality.name(),
                        if done.is_some() {
                            " (the last render plays)"
                        } else {
                            ""
                        }
                    ),
                    (None, _, Some(e)) => format!("⟲ loop: the render failed ({e})"),
                    (None, Some(_), None) if st.wanted.is_some() => {
                        format!("⟲ loop: rendered{heard} · a change waits")
                    }
                    (None, Some(_), None) => format!("⟲ loop: rendered{heard}"),
                    (None, None, None) => "⟲ loop: about to render".to_string(),
                }
            }
        };
        // The clip that plays, made again when the render or its gains change.
        let gains = (slot.makeup_db, slot.wet, slot.bypass);
        if let Some(d) = &st.done
            && st
                .clip
                .as_ref()
                .is_none_or(|(k, g, _)| *k != d.key || *g != gains)
        {
            let track = if t == MASTER { NO_TRACK } else { t };
            st.clip = Some((d.key.clone(), gains, d.clip(&slot, (1.0, 1.0), track)));
        }
        self.audition_status = Some(status);
    }

    /// The mix while the open insert's loop render plays: the track's own audio from the
    /// render (through its strip), the rest as an audition's mix; the master's render alone
    /// through the master fader. None: no loop render to play.
    fn loop_mix(&self) -> Option<Mix> {
        if !self.loop_mode {
            return None;
        }
        let l = self.loop_render.as_ref()?;
        let (_, _, clip) = l.clip.as_ref()?;
        if l.track == MASTER {
            return Some(Mix {
                clips: vec![clip.clone()],
                ..self.session.mix_master_audition()
            });
        }
        let mut m = self.session.mix_audition(l.track);
        m.clips.push(MixClip {
            gain: m.live,
            ..clip.clone()
        });
        Some(m)
    }

    /// The tracks' sum (the master's input), summed once per change of the tracks.
    fn master_input(&self) -> Option<varimu_app::session::Stereo> {
        let sig = self.session.master_mix_signature();
        let mut cache = self.master_input.borrow_mut();
        if cache.as_ref().is_none_or(|(s, _)| *s != sig) {
            *cache = Some((sig, self.session.master_input()));
        }
        cache.as_ref().and_then(|(_, i)| i.clone())
    }

    /// The master's insert `k`'s input for an audition: the master print's stage before it
    /// (if that print is of the tracks as they are), else the tracks' sum; the channel the
    /// panel's "hear" picks (the mid made once per input), where it starts, and a key that
    /// changes when it does.
    fn master_audition_input(&self, k: usize) -> Option<(Arc<Vec<f32>>, i64, String)> {
        let (start, l, r) = self.master_input()?;
        let mix = self.session.master_mix_signature();
        let stage = self.session.master_inserts[..k]
            .iter()
            .filter(|s| !s.bypass)
            .count();
        let printed = self
            .session
            .master_printed
            .as_ref()
            .filter(|p| p.lane == mix && stage > 0 && p.stages.len() >= stage);
        let (start, l, r) = match printed {
            Some(p) => (
                p.start,
                p.stages[stage - 1].clone(),
                p.stages_right
                    .get(stage - 1)
                    .cloned()
                    .unwrap_or_else(|| p.stages[stage - 1].clone()),
            ),
            None => (start, l, r),
        };
        let (audio, hear) = match self.hear {
            Hear::Left => (l, "L"),
            Hear::Right => (r, "R"),
            Hear::Mid => {
                let id = format!("{:p}|{:p}", Arc::as_ptr(&l), Arc::as_ptr(&r));
                let mut cache = self.mid_cache.borrow_mut();
                let mid = match cache.as_ref() {
                    Some((i, m)) if *i == id => m.clone(),
                    _ => {
                        let m: Arc<Vec<f32>> =
                            Arc::new(l.iter().zip(r.iter()).map(|(a, b)| 0.5 * (a + b)).collect());
                        *cache = Some((id, m.clone()));
                        m
                    }
                };
                (mid, "M")
            }
        };
        let key = format!(
            "master|{mix}|{stage}|{start}|{}|{:p}|{hear}",
            audio.len(),
            Arc::as_ptr(&audio)
        );
        Some((audio, start, key))
    }

    /// Every insert panel closed (a track's and the master's).
    fn close_insert_panels(&mut self) {
        self.insert_sel = None;
        self.master_sel = None;
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
            self.close_insert_panels();
            self.resume_instrument = false;
            return;
        }
        let want = self
            .master_selected()
            .map(|k| (MASTER, k))
            .or_else(|| self.insert_selected())
            .filter(|_| idle && self.recording.is_none());
        match want {
            Some((t, k)) if self.loop_mode => {
                // The loop render plays in the mix: no device live.
                if self.audition.take().is_some() {
                    self.end_audition(play);
                }
                self.sync_loop(
                    t,
                    k,
                    play.player().is_some_and(|p| p.status().transport.running),
                );
                return;
            }
            _ => self.loop_render = None,
        }
        let Some((t, k)) = want else {
            if self.audition.take().is_some() {
                self.end_audition(play);
            }
            return;
        };
        let input = if t == MASTER {
            self.master_audition_input(k)
        } else {
            self.audition_input(t, k)
        };
        let Some((audio, start, input)) = input else {
            // Nothing to play into it yet (no take).
            if self.audition.take().is_some() {
                self.end_audition(play);
            }
            return;
        };
        let slot = if t == MASTER {
            self.session.master_inserts[k].clone()
        } else {
            self.session.tracks[t].inserts[k].clone()
        };
        let same = self.audition.as_ref().is_some_and(|a| {
            a.track == t && a.slot == k && a.device == slot.device && a.input == input
        }) && play.adopted();
        if !same {
            // An instrument plays: only a panel the user just opened takes its place (it
            // comes back when the panel closes); a panel left open closes instead.
            if self.audition.is_none() && instrument {
                if !requested {
                    self.close_insert_panels();
                    return;
                }
                self.resume_instrument = true;
            }
            let running = play.player().is_some_and(|p| p.status().transport.running);
            let side = if t == MASTER {
                None
            } else {
                self.session.sidechain(t, &slot)
            };
            match self.start_audition(&slot, audio, start, side) {
                Ok(p) => {
                    if p.rate != self.session.rate && self.session.end() > 0 {
                        self.error = Some(format!(
                            "{} plays at {} Hz, the session is at {} Hz",
                            slot.device, p.rate, self.session.rate
                        ));
                        self.close_insert_panels();
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
                    self.close_insert_panels();
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
                "● live{} · load {:.0}%{}",
                if st.transport.running {
                    ", playing"
                } else {
                    " (Space plays)"
                },
                st.load * 100.0,
                if st.load > 1.0 {
                    " · too slow live: try ⟲ loop"
                } else {
                    ""
                }
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
    /// position `start` (and its key input by `side` from there, if it is keyed).
    fn start_audition(
        &self,
        slot: &Slot,
        audio: Arc<Vec<f32>>,
        start: i64,
        side: Option<Arc<Vec<f32>>>,
    ) -> Result<Player, String> {
        let config = self.root.join("config");
        let d = find_device(&slot.device).ok_or(format!("no device {}", slot.device))?;
        let s = d.play_settings(&Settings::load(&config, d.quality)?);
        let circuit = d
            .live(Circuit::load(&config, d.circuit, s.cores()?)?)
            .with_events(s.events)
            .with_noise(slot.noise);
        let key = match (side, d.key, &slot.key) {
            (Some(audio), Some(name), Some(route)) => {
                let inputs = &circuit.spec().cv_inputs;
                Some(TimelineKey {
                    audio,
                    control: inputs
                        .iter()
                        .position(|(n, _)| n == name)
                        .ok_or(format!("no control input {name}"))?,
                    controls: inputs.len(),
                    volts: 10f64.powf(route.trim_db / 20.0) * circuit.full_scale(&s).input_v,
                })
            }
            _ => None,
        };
        let p = Player::start(
            Source::Timeline { audio, start, key },
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

    /// Prints: finished ones to their tracks, ones no track wants any more cancelled. A
    /// print is made only when asked for ([`SessionView::request_print`]; SE1, decision 2);
    /// a chain not current is looked up in the cache (undo, a session opened), never
    /// rendered by itself. Nothing starts while recording or while a gesture is in progress.
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
                    // A stereo lane printed dual-mono: each insert's right channel too (a
                    // right equal to the left printed once: the left's). A stereo insert (a
                    // reverb with STEREO on) makes a mono lane's print stereo from there.
                    let stereo = j.stereo || prints.iter().any(|p| p.right.is_some());
                    let right_of = |p: &varimu_app::print::Print| {
                        p.right.clone().unwrap_or_else(|| p.audio.clone())
                    };
                    let right = stereo.then(|| prints.last().map(right_of)).flatten();
                    let printed = Printed {
                        signature: j.signature.clone(),
                        lane: j.lane.clone(),
                        start: j.start,
                        overview: Arc::new(Overview::of_lr(
                            &audio,
                            right.as_deref().map(Vec::as_slice),
                            OVERVIEW_BIN,
                        )),
                        audio,
                        right,
                        stages: prints.iter().map(|p| p.audio.clone()).collect(),
                        stages_right: if stereo {
                            prints.iter().map(right_of).collect()
                        } else {
                            Vec::new()
                        },
                    };
                    if j.master {
                        if self.session.master_signature().as_deref() == Some(j.signature.as_str())
                        {
                            self.session.master_printed = Some(printed);
                        }
                        continue;
                    }
                    for i in 0..self.session.tracks.len() {
                        if self.session.chain_signature(i).as_deref() == Some(j.signature.as_str())
                        {
                            self.session.tracks[i].printed = Some(printed.clone());
                        }
                    }
                }
                Some(Err(e)) if !j.cancelled && !j.lookup => {
                    self.print_errors.insert(j.signature, e);
                }
                _ => {}
            }
        }
        let wanted: HashSet<String> = (0..self.session.tracks.len())
            .filter_map(|i| self.session.chain_signature(i))
            .chain(self.session.master_signature())
            .collect();
        for j in &mut self.jobs {
            if !j.cancelled && !wanted.contains(&j.signature) {
                j.job.cancel();
                j.cancelled = true;
            }
        }
        // Asked for: a track's key tracks print first when they aren't current.
        let asked: Vec<usize> = (0..self.session.tracks.len())
            .filter(|&i| self.print_wanted.contains(&self.session.tracks[i].id))
            .collect();
        for t in asked {
            if self.session.print_current(t) {
                let id = self.session.tracks[t].id.clone();
                self.print_wanted.remove(&id);
                continue;
            }
            for k in self.session.key_tracks(t) {
                if !self.session.print_current(k) {
                    self.print_wanted.insert(self.session.tracks[k].id.clone());
                }
            }
        }
        let ids: HashSet<String> = self.session.tracks.iter().map(|t| t.id.clone()).collect();
        self.print_wanted.retain(|id| ids.contains(id));
        let busy = recording
            || self.recording.is_some()
            || ctx.input(|i| i.pointer.any_down())
            || ctx.egui_wants_keyboard_input();
        if !busy {
            let config = self.root.join("config");
            let cache = self.session.dir.join("prints");
            for ti in 0..self.session.tracks.len() {
                let t = &self.session.tracks[ti];
                let (Some(sig), Some((start, lane, lane_r))) =
                    (self.session.chain_signature(ti), t.lane_lr())
                else {
                    continue;
                };
                if self.session.print_current(ti)
                    || self.print_errors.contains_key(&sig)
                    || self
                        .jobs
                        .iter()
                        .any(|j| !j.cancelled && !j.lookup && j.signature == sig)
                {
                    continue;
                }
                let asked = self.print_wanted.contains(&t.id);
                let lookup = !asked;
                if lookup
                    && (self.looked_up.contains(&sig)
                        || self.jobs.iter().any(|j| !j.cancelled && j.signature == sig))
                {
                    continue;
                }
                // A keyed track waits for its key tracks' prints (one print per change).
                if asked && !self.session.keys_ready(ti) {
                    continue;
                }
                let running = self
                    .jobs
                    .iter()
                    .filter(|j| !j.cancelled && j.lookup == lookup)
                    .count();
                if running >= MAX_PRINT_JOBS {
                    continue;
                }
                let slots: Vec<Slot> = t.inserts.iter().filter(|s| !s.bypass).cloned().collect();
                let input = lane;
                let stereo = lane_r.is_some();
                let sides = self.session.sidechains(ti);
                let job = if lookup {
                    Job::lookup(
                        config.clone(),
                        slots,
                        sides,
                        input,
                        lane_r,
                        rate,
                        cache.clone(),
                    )
                } else {
                    Job::spawn(
                        config.clone(),
                        slots,
                        sides,
                        input,
                        lane_r,
                        rate,
                        Some(cache.clone()),
                    )
                };
                let (id, lane) = (t.id.clone(), t.source_signature());
                if lookup {
                    self.looked_up.insert(sig.clone());
                } else {
                    self.print_wanted.remove(&id);
                }
                self.jobs.push(PrintJob {
                    job,
                    signature: sig,
                    lane,
                    start,
                    stereo,
                    cancelled: false,
                    lookup,
                    master: false,
                });
            }
            self.poll_master_print();
        }
        if !self.jobs.is_empty() || !self.print_wanted.is_empty() {
            ctx.request_repaint_after(Duration::from_millis(100));
        }
    }

    /// The master chain's print: looked up in the cache when it isn't current, made when
    /// asked for once every audible track's print is current (the tracks' prints are asked
    /// for with it).
    /// The deck's print: a finished one taken in (the assigned tracks play their tape
    /// tracks); while none is current, the cache looked up once per signature (nothing is
    /// printed until asked: SE1).
    fn poll_deck(&mut self, ctx: &egui::Context) {
        if let Some(j) = &self.deck_job {
            if !j.is_finished() {
                ctx.request_repaint_after(Duration::from_millis(250));
                return;
            }
            match j.join() {
                Some(Ok(p)) => {
                    self.session.set_deck_print(p);
                    self.deck_error = None;
                }
                Some(Err(e)) if e == NOT_PRINTED => {}
                Some(Err(e)) => self.deck_error = Some(e),
                None => {}
            }
            self.deck_job = None;
        }
        if self.session.deck_current() {
            return;
        }
        let (Some(sig), Some(deck), Some(input)) = (
            self.session.deck_signature(),
            self.session.deck.clone(),
            self.session.deck_input(),
        ) else {
            return;
        };
        if !self.deck_looked_up.insert(sig) {
            return;
        }
        self.deck_job = Some(DeckJob::spawn(
            &self.root.join("config"),
            deck,
            input,
            self.session.rate,
            Some(self.session.dir.join("prints")),
            false,
        ));
    }

    /// The tape deck's window: its tape tracks' assignment and record trims, its noise, the
    /// print and where it stands.
    fn deck_window(&mut self, ui: &mut egui::Ui) {
        let idle = self.recording.is_none();
        let Some(mut deck) = self.session.deck.clone() else {
            ui.label(
                RichText::new(
                    "No tape deck. An Ampex 300-4 records up to four tracks on one 1/2 in \
                     tape: one transport, neighbouring tracks crosstalk, each track's own hiss.",
                )
                .small()
                .color(theme::MUTED),
            );
            if ui
                .add_enabled(idle, egui::Button::new("Add an Ampex 300-4"))
                .clicked()
            {
                self.session.deck = Some(Deck::default());
                self.save();
            }
            return;
        };
        let names: Vec<(String, String)> = self
            .session
            .tracks
            .iter()
            .map(|t| (t.id.clone(), t.name.clone()))
            .collect();
        let rate = self.session.rate;
        egui::Grid::new("deck_tracks")
            .num_columns(3)
            .show(ui, |ui| {
                for k in 0..deck::TRACKS {
                    let edge = if k == 0 || k == deck::TRACKS - 1 {
                        "edge"
                    } else {
                        "inner"
                    };
                    ui.label(RichText::new(format!("Tape track {} ({edge})", k + 1)).small());
                    let shown = deck.tracks[k]
                        .as_ref()
                        .and_then(|id| names.iter().find(|(i, _)| i == id))
                        .map_or("none".to_string(), |(_, n)| n.clone());
                    let before = deck.tracks[k].clone();
                    egui::ComboBox::from_id_salt(("deck_track", k))
                        .selected_text(shown)
                        .show_ui(ui, |ui| {
                            ui.selectable_value(&mut deck.tracks[k], None, "none");
                            for (id, name) in &names {
                                ui.selectable_value(&mut deck.tracks[k], Some(id.clone()), name);
                            }
                        });
                    if deck.tracks[k] != before {
                        // One tape track per session track: taken off any other.
                        if let Some(id) = deck.tracks[k].clone() {
                            for (j, t) in deck.tracks.iter_mut().enumerate() {
                                if j != k && t.as_ref() == Some(&id) {
                                    *t = None;
                                }
                            }
                        }
                        // Its record trim, set once from the lane (as an insert's first trim).
                        deck.trims_db[k] = deck.tracks[k]
                            .as_ref()
                            .and_then(|id| self.session.tracks.iter().find(|t| &t.id == id))
                            .and_then(|t| t.clips_lr())
                            .map_or(0.0, |(_, l, r)| {
                                let m: Vec<f32> = match r {
                                    Some(r) => {
                                        l.iter().zip(r.iter()).map(|(a, b)| 0.5 * (a + b)).collect()
                                    }
                                    None => l.to_vec(),
                                };
                                deck::trim_for(&m, rate)
                            });
                    }
                    ui.add(
                        egui::DragValue::new(&mut deck.trims_db[k])
                            .range(-40.0..=40.0)
                            .speed(0.1)
                            .suffix(" dB"),
                    )
                    .on_hover_text(
                        "The record trim: the fader in front of the channel (set from the lane's \
                     loudest 8 s to 0 VU, +0.5 dB for 202's operating level); the playback \
                     comes back at the lane's level",
                    );
                    ui.end_row();
                }
            });
        ui.checkbox(&mut deck.noise, "Noise (the tape's hiss, the tubes')");
        if Some(&deck) != self.session.deck.as_ref() {
            self.session.deck = Some(deck);
            self.save();
        }
        ui.separator();
        let input = self.session.deck_input();
        let status = match (&self.deck_job, &self.session.deck_printed) {
            (Some(j), _) if self.session.deck_signature().as_deref() == Some(&j.signature) => {
                format!("printing… {:.0} %", 100.0 * j.progress())
            }
            _ if input.is_none() => "no assigned track has a sound".into(),
            (_, Some(p)) if self.session.deck_current() => format!(
                "printed: the assigned tracks play their tape tracks{}",
                if p.realtime_factor > 0.0 {
                    format!(" ({:.0}x real time)", p.realtime_factor)
                } else {
                    String::new()
                }
            ),
            (_, Some(_)) => "printed for other settings or lanes: print again".into(),
            (_, None) => "not printed".into(),
        };
        ui.label(RichText::new(status).small().color(theme::MUTED));
        if let Some(e) = &self.deck_error {
            ui.label(RichText::new(e).small().color(theme::FAULT));
        }
        let printing = self.deck_job.is_some();
        ui.horizontal(|ui| {
            if ui
                .add_enabled(
                    idle && !printing && input.is_some() && !self.session.deck_current(),
                    egui::Button::new("Print to tape"),
                )
                .on_hover_text(
                    "Every assigned track recorded at once, as one pass, at production (in \
                     pieces, the tape on the GPU when there is one): about two hours of wall \
                     clock for three minutes of four tracks",
                )
                .clicked()
                && let (Some(deck), Some(input)) = (self.session.deck.clone(), input)
            {
                self.deck_error = None;
                self.deck_job = Some(DeckJob::spawn(
                    &self.root.join("config"),
                    deck,
                    input,
                    rate,
                    Some(self.session.dir.join("prints")),
                    true,
                ));
            }
            if printing && ui.button("Cancel").clicked() {
                if let Some(j) = &self.deck_job {
                    j.cancel();
                }
            }
            if ui
                .add_enabled(idle && !printing, egui::Button::new("Remove the deck"))
                .on_hover_text("The tracks play their lanes again (the print stays in the cache)")
                .clicked()
            {
                self.session.deck = None;
                self.session.deck_printed = None;
                self.session.attach_tape();
                self.save();
            }
        });
    }

    fn poll_master_print(&mut self) {
        if !self.session.master_print_current() && self.master_wanted {
            let any_solo = self.session.tracks.iter().any(|t| t.solo);
            for t in 0..self.session.tracks.len() {
                let x = &self.session.tracks[t];
                let audible = if any_solo { x.solo } else { !x.mute };
                if audible && !self.session.print_current(t) && !self.printing(t) {
                    self.request_print(t);
                }
            }
        }
        let Some(sig) = self.session.master_signature() else {
            self.master_wanted = false;
            return;
        };
        if self.session.master_print_current() {
            self.master_wanted = false;
            return;
        }
        if self.print_errors.contains_key(&sig)
            || self
                .jobs
                .iter()
                .any(|j| !j.cancelled && !j.lookup && j.signature == sig)
        {
            return;
        }
        let lookup = !self.master_wanted;
        if lookup
            && (self.looked_up.contains(&sig)
                || self.jobs.iter().any(|j| !j.cancelled && j.signature == sig))
        {
            return;
        }
        // The tracks it sums play their prints as they are first (one print per change).
        let any_solo = self.session.tracks.iter().any(|t| t.solo);
        let tracks_ready = (0..self.session.tracks.len()).all(|i| {
            let t = &self.session.tracks[i];
            (any_solo && !t.solo) || (!any_solo && t.mute) || self.session.print_current(i)
        });
        if !lookup && !tracks_ready {
            return;
        }
        let running = self
            .jobs
            .iter()
            .filter(|j| !j.cancelled && j.lookup == lookup)
            .count();
        if running >= MAX_PRINT_JOBS {
            return;
        }
        let Some((start, l, r)) = self.master_input() else {
            return;
        };
        let slots: Vec<Slot> = self
            .session
            .master_inserts
            .iter()
            .filter(|s| !s.bypass)
            .cloned()
            .collect();
        let sides = vec![None; slots.len()];
        let (config, cache, rate) = (
            self.root.join("config"),
            self.session.dir.join("prints"),
            self.session.rate,
        );
        let job = if lookup {
            Job::lookup(config, slots, sides, l, Some(r), rate, cache)
        } else {
            Job::spawn(config, slots, sides, l, Some(r), rate, Some(cache))
        };
        if lookup {
            self.looked_up.insert(sig.clone());
        } else {
            self.master_wanted = false;
        }
        self.jobs.push(PrintJob {
            job,
            signature: sig,
            lane: self.session.master_mix_signature(),
            start,
            stereo: true,
            cancelled: false,
            lookup,
            master: true,
        });
    }

    /// Print the master's chain (its Print buttons): the tracks' prints first when they
    /// aren't current. A print that failed is tried again.
    fn request_master_print(&mut self) {
        if let Some(sig) = self.session.master_signature() {
            self.print_errors.remove(&sig);
        }
        self.master_wanted = true;
    }

    /// Whether the master's print is asked for or running.
    fn master_printing(&self) -> bool {
        self.master_wanted
            || self.session.master_signature().is_some_and(|sig| {
                self.jobs
                    .iter()
                    .any(|j| !j.cancelled && !j.lookup && j.signature == sig)
            })
    }

    /// The master's selected insert, if it still exists.
    fn master_selected(&self) -> Option<usize> {
        self.master_sel
            .filter(|&k| k < self.session.master_inserts.len())
    }

    /// The master's insert `k`'s state: its glyph, colour and what it says on hover.
    fn master_insert_state(&self, k: usize) -> (String, Color32, String) {
        let slot = &self.session.master_inserts[k];
        if slot.bypass {
            return ("⏻".into(), theme::FAINT, "bypassed".into());
        }
        let Some(sig) = self.session.master_signature() else {
            return ("".into(), theme::MUTED, "nothing to print".into());
        };
        if let Some(e) = self.print_errors.get(&sig) {
            return ("!".into(), theme::FAULT, format!("the render failed: {e}"));
        }
        if let Some(j) = self
            .jobs
            .iter()
            .find(|j| !j.cancelled && !j.lookup && j.signature == sig)
        {
            let stage = self.session.master_inserts[..k]
                .iter()
                .filter(|s| !s.bypass)
                .count();
            let (at, f) = j.job.progress();
            return match stage.cmp(&at) {
                std::cmp::Ordering::Less => ("✓".into(), theme::OK, "rendered".into()),
                std::cmp::Ordering::Equal => (
                    format!("◔ {:.0}%", f * 100.0),
                    theme::ACCENT,
                    "rendering the mix through it".into(),
                ),
                std::cmp::Ordering::Greater => (
                    "…".into(),
                    theme::MUTED,
                    "waiting for the inserts before it".into(),
                ),
            };
        }
        let plays = if self.session.master_print_playing().is_some() {
            "the last print plays, stale"
        } else {
            "the mix plays without it"
        };
        if self.session.master_print_current() {
            (
                "✓".into(),
                theme::OK,
                "printed: the mix plays through it (still editable)".into(),
            )
        } else if self.master_printing() {
            (
                "…".into(),
                theme::WARN,
                format!("waiting for the tracks' prints ({plays} meanwhile)"),
            )
        } else {
            (
                "○".into(),
                theme::WARN,
                format!("the mix or its inserts changed · not printed ({plays}; Print)"),
            )
        }
    }

    /// `device` added at the end of the master's chain, its panel opened. The first insert
    /// that isn't bypassed gets its trim from the mix (its louder channel's loudest stretch
    /// to the alignment level), set once.
    fn add_master_insert(&mut self, device: &str) {
        let rate = self.session.rate;
        let mut slot = Slot::new(device);
        if self.session.master_inserts.iter().all(|s| s.bypass)
            && let Some((_, l, r)) = self.master_input()
        {
            let level = [l, r]
                .iter()
                .map(|x| {
                    let y: Vec<f64> = x.iter().map(|&v| v as f64).collect();
                    audio::level_dbfs(&y, rate, 8.0)
                })
                .fold(f64::NEG_INFINITY, f64::max);
            if level > -200.0 {
                slot.trim_db = ((ALIGNMENT_DBFS - level).clamp(-40.0, 40.0) * 10.0).round() / 10.0;
            }
        }
        self.session.master_inserts.push(slot);
        self.insert_sel = None;
        self.master_sel = Some(self.session.master_inserts.len() - 1);
        self.audition_request = true;
        self.save();
    }

    /// The master's selected insert's panel: gains, bypass, quality, place, knobs.
    fn master_panel(&mut self, ui: &mut egui::Ui) {
        let Some(k) = self.master_selected() else {
            self.master_sel = None;
            return;
        };
        let device = self.session.master_inserts[k].device.clone();
        let label = find_device(&device).map_or(device.clone(), |d| d.label.to_string());
        let (glyph, colour, state) = self.master_insert_state(k);
        let knobs = self.knobs_for(&device);
        let rate = self.session.rate;
        let n = self.session.master_inserts.len();
        let last_on = self.session.master_inserts.iter().rposition(|s| !s.bypass) == Some(k);
        let (mut changed, mut remove, mut print) = (false, false, false);
        let mut moved: Option<usize> = None;
        // The mix's and the print's levels (their louder channels), for Match.
        let levels = match (self.master_input(), &self.session.master_printed) {
            (Some((_, l, r)), Some(p)) if self.session.master_print_current() => {
                let lv = |chans: [&[f32]; 2]| {
                    chans
                        .iter()
                        .map(|x| {
                            let y: Vec<f64> = x.iter().map(|&v| v as f64).collect();
                            audio::level_dbfs(&y, rate, 8.0)
                        })
                        .fold(f64::NEG_INFINITY, f64::max)
                };
                let pr = p.right.as_deref().unwrap_or(&p.audio);
                Some((lv([&l, &r]), lv([&p.audio, pr])))
            }
            _ => None,
        };
        let live_line = match self.audition_status.as_ref() {
            Some(s) if self.audition.is_some() || self.loop_mode => s.clone(),
            _ => "not playing live".to_string(),
        };
        let loop_mode = self.loop_mode;
        ui.horizontal(|ui| {
            ui.label(
                RichText::new(format!("Master · {label}"))
                    .strong()
                    .color(theme::INK),
            );
            ui.label(RichText::new(glyph).color(colour))
                .on_hover_text(&state);
            ui.label(RichText::new(&state).small().color(theme::MUTED));
            ui.add_space(12.0);
            if ui
                .selectable_label(loop_mode, RichText::new("⟲ loop").small())
                .on_hover_text(LOOP_TIP)
                .clicked()
            {
                self.loop_mode = !loop_mode;
            }
            ui.add_space(12.0);
            ui.label(RichText::new("hear").small().color(theme::MUTED))
                .on_hover_text(
                    "The mix prints each channel through its own copy of the device with the                      same knobs (a tape machine's right side its own grain, the same                      transport). Live, one copy plays: the channel you pick, up the middle.",
                );
            for (h, name) in [(Hear::Left, "L"), (Hear::Right, "R"), (Hear::Mid, "mid")] {
                if ui
                    .selectable_label(self.hear == h, RichText::new(name).small())
                    .clicked()
                {
                    self.hear = h;
                }
            }
            ui.add_space(12.0);
            ui.label(RichText::new(&live_line).small().color(theme::ACCENT))
                .on_hover_text(
                    "While this panel is open the device plays live on the mix (Space plays the                      session); Print renders the mix through the master's chain for playback                      and export (nothing prints by itself). The inserts after it aren't heard                      meanwhile.",
                );
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.button("✕").on_hover_text("Close the panel").clicked() {
                    self.master_sel = None;
                }
                if !self.session.master_print_current()
                    && !self.master_printing()
                    && ui
                        .button(RichText::new("Print").color(theme::ACCENT))
                        .on_hover_text(
                            "Render the mix through the master's chain for playback (in the                              background; the tracks' prints first)",
                        )
                        .clicked()
                {
                    print = true;
                }
                if ui.button("Remove").clicked() {
                    remove = true;
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
        let slot = &mut self.session.master_inserts[k];
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
                .on_hover_text(
                    "The fader in front of the device: how hard the mix drives it (a tape                      machine: 0 VU at -18 dBFS rms; +6 dB is ~4% THD at 400 Hz, +12 ~13%)",
                )
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
                        "Make-up so the print is as loud as the mix (mix {a:.1} dBFS, print                          {b:.1} dBFS)"
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
                .on_hover_text("The device's share of the mix: 100% is the device only")
                .changed();
            ui.add_space(8.0);
            changed |= ui.checkbox(&mut slot.bypass, "Bypass").changed();
            ui.add_space(8.0);
            egui::ComboBox::from_id_salt(("master_insert_quality", k))
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
                    "The quality it prints at: its play quality while iterating, production                      for the final mix (a tape machine prints in 30 s pieces at once)",
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
                        changed |= knob_ui(ui, knob, &mut slot.values, (MASTER, k));
                    }
                });
            }
        }
        if let Some(to) = moved {
            let ins = &mut self.session.master_inserts;
            let s = ins.remove(k);
            ins.insert(to, s);
            self.master_sel = Some(to);
            changed = true;
        }
        if remove {
            self.session.master_inserts.remove(k);
            self.master_sel = None;
            changed = true;
        }
        if print {
            self.request_master_print();
        }
        if changed {
            self.save();
        }
    }

    /// Print track `t`'s chain (SE1: the Print buttons, Ctrl+R): its key tracks first when
    /// they aren't current. A print that failed is tried again.
    fn request_print(&mut self, t: usize) {
        let Some(track) = self.session.tracks.get(t) else {
            return;
        };
        let id = track.id.clone();
        if let Some(sig) = self.session.chain_signature(t) {
            self.print_errors.remove(&sig);
        }
        self.print_wanted.insert(id);
    }

    /// Tracks whose chain isn't printed as it is now (and has something to print), not
    /// asked for or printing yet.
    fn prints_missing(&self) -> Vec<usize> {
        (0..self.session.tracks.len())
            .filter(|&i| !self.session.print_current(i) && !self.printing(i))
            .collect()
    }

    /// Whether track `t`'s print is asked for or running.
    fn printing(&self, t: usize) -> bool {
        let Some(track) = self.session.tracks.get(t) else {
            return false;
        };
        self.print_wanted.contains(&track.id)
            || self.session.chain_signature(t).is_some_and(|sig| {
                self.jobs
                    .iter()
                    .any(|j| !j.cancelled && !j.lookup && j.signature == sig)
            })
    }

    /// Insert `k` of track `t`'s state: its glyph, colour and what it says on hover.
    fn insert_state(&self, t: usize, k: usize) -> (String, Color32, String) {
        let track = &self.session.tracks[t];
        let slot = &track.inserts[k];
        if slot.bypass {
            return ("⏻".into(), theme::FAINT, "bypassed".into());
        }
        let Some(sig) = self.session.chain_signature(t) else {
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
        let plays = if track.playing(self.session.rate).is_some_and(|p| p.2) {
            "the last print plays, stale"
        } else {
            "the track plays dry"
        };
        if self.session.print_current(t) {
            (
                "✓".into(),
                theme::OK,
                "printed for playback (still editable; ⤓ Render bakes it into a new take)".into(),
            )
        } else if self.printing(t) && !self.session.keys_ready(t) {
            (
                "…".into(),
                theme::WARN,
                format!("waiting for its key track to print ({plays} meanwhile)"),
            )
        } else if self.printing(t) {
            (
                "…".into(),
                theme::WARN,
                format!("waiting to print ({plays} meanwhile)"),
            )
        } else {
            (
                "○".into(),
                theme::WARN,
                format!("inserts changed · not printed ({plays}; Print, or Ctrl+R)"),
            )
        }
    }

    /// The Mixer tab (SE4): a strip per track left to right, the master at the right. The
    /// strips' values are the tracks' (the arrangement's strips show the same ones).
    fn mixer(&mut self, ui: &mut egui::Ui) {
        const STRIP: f32 = 104.0;
        let full = ui.available_rect_before_wrap();
        let master_rect = Rect::from_min_max(
            Pos2::new(full.right() - STRIP - 12.0, full.top()),
            full.max - egui::vec2(8.0, 4.0),
        );
        let tracks_rect =
            Rect::from_min_max(full.min, Pos2::new(master_rect.left() - 4.0, full.bottom()));
        let mut changed = false;
        let mut tui = ui.new_child(
            egui::UiBuilder::new()
                .id_salt("mixer_tracks")
                .max_rect(tracks_rect)
                .layout(egui::Layout::left_to_right(egui::Align::Min)),
        );
        egui::ScrollArea::horizontal()
            .auto_shrink([false, false])
            .show(&mut tui, |ui| {
                ui.horizontal_top(|ui| {
                    for i in 0..self.session.tracks.len() {
                        changed |= self.mixer_strip(ui, i, STRIP, full.height());
                    }
                    if self.session.tracks.is_empty() {
                        ui.label(RichText::new("no tracks yet").color(theme::MUTED));
                    }
                });
            });
        // The master: its fader on the stereo sum (export follows it) and its meter.
        let mut mui = ui.new_child(
            egui::UiBuilder::new()
                .id_salt("mixer_master")
                .max_rect(master_rect)
                .layout(egui::Layout::top_down(egui::Align::Center)),
        );
        let p = mui.painter_at(master_rect);
        p.rect_filled(master_rect, 4.0, theme::CHROME);
        p.rect_filled(
            Rect::from_min_size(master_rect.min, egui::vec2(master_rect.width(), 4.0)),
            0.0,
            theme::ACCENT,
        );
        mui.add_space(8.0);
        mui.label(RichText::new("MASTER").strong().color(theme::INK));
        let clipped = self.meters.master.clipped;
        let clip = egui::Button::new(RichText::new("CLIP").small().color(if clipped {
            Color32::WHITE
        } else {
            theme::FAINT
        }))
        .fill(if clipped {
            theme::FAULT
        } else {
            theme::CHROME2
        });
        if mui
            .add(clip)
            .on_hover_text("Lit when the mix went over full scale (click to clear)")
            .clicked()
        {
            self.meters.master.clipped = false;
        }
        changed |= self.master_inserts_ui(&mut mui, STRIP);
        // The fader takes what the inserts' chips, "+ insert" and Print leave.
        let chips = self.session.master_inserts.len() as f32 + 3.0;
        let h = (master_rect.height() - 150.0 - chips * 22.0).max(80.0);
        mui.horizontal(|ui| {
            ui.add_space(12.0);
            changed |= crate::mixer::fader(
                ui,
                &mut self.session.master_db,
                egui::vec2(30.0, h),
                true,
                ui.id().with("master_fader"),
            );
            ui.add_space(4.0);
            let (r, _) = ui.allocate_exact_size(egui::vec2(22.0, h), Sense::hover());
            crate::mixer::draw_meter(&ui.painter_at(r), r, &self.meters.master);
        });
        changed |= mui
            .add(
                egui::DragValue::new(&mut self.session.master_db)
                    .range(crate::mixer::FADER_MIN_DB..=crate::mixer::FADER_MAX_DB)
                    .speed(0.2)
                    .max_decimals(1)
                    .suffix(" dB"),
            )
            .on_hover_text("The master fader (on the stereo sum; exports follow it)")
            .changed();
        let m = &self.meters.master;
        mui.label(
            RichText::new(format!(
                "pk {:.1} · rms {:.1}",
                m.hold_db[0].max(m.hold_db[1]),
                m.rms_db[0].max(m.rms_db[1])
            ))
            .small()
            .color(theme::MUTED),
        );
        if changed {
            self.save();
        }
    }

    /// The master's inserts in its strip: chips (click: the panel; right-click: bypass,
    /// earlier, remove), "+ insert" and Print. Returns whether they changed.
    fn master_inserts_ui(&mut self, s: &mut egui::Ui, width: f32) -> bool {
        let mut changed = false;
        s.label(RichText::new("INSERTS").small().color(theme::FAINT))
            .on_hover_text(
                "On the tracks' stereo sum, before the master fader: printed dual-mono when                  you press Print, then the mix plays (and exports) the print",
            );
        let mut action: Option<(usize, &'static str)> = None;
        let mut add: Option<&'static str> = None;
        for k in 0..self.session.master_inserts.len() {
            let slot = &self.session.master_inserts[k];
            let short =
                find_device(&slot.device).map_or(slot.device.clone(), |d| d.short.to_string());
            let (glyph, colour, state) = self.master_insert_state(k);
            let selected = self.master_selected() == Some(k);
            let bypass = slot.bypass;
            let b = egui::Button::new(
                RichText::new(format!("{short} {glyph}"))
                    .small()
                    .color(if bypass { theme::FAINT } else { colour }),
            )
            .fill(if selected { theme::CHROME3 } else { theme::BG })
            .stroke(Stroke::new(
                1.0,
                if selected { theme::ACCENT } else { theme::LINE },
            ))
            .min_size(egui::vec2(width - 18.0, 18.0));
            let r = s.add(b).on_hover_text(state);
            if r.clicked() {
                self.insert_sel = None;
                self.master_sel = if selected { None } else { Some(k) };
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
                if k > 0 && ui.button("Earlier").clicked() {
                    action = Some((k, "up"));
                    ui.close();
                }
                if ui.button("Remove").clicked() {
                    action = Some((k, "remove"));
                    ui.close();
                }
            });
        }
        s.menu_button(RichText::new("+ insert").small(), |ui| {
            for (group, ids) in vpanel::insert_menu() {
                theme::menu_heading(ui, group.title());
                for j in ids {
                    let d = &DEVICES[j];
                    if ui.button(d.label).on_hover_text(d.about).clicked() {
                        add = Some(d.id);
                        ui.close();
                    }
                }
            }
        });
        if self.session.master_signature().is_some()
            && !self.session.master_print_current()
            && !self.master_printing()
            && s.add(
                egui::Button::new(RichText::new("Print").small().color(theme::ACCENT))
                    .min_size(egui::vec2(0.0, 18.0)),
            )
            .on_hover_text("Render the mix through the master's chain (the tracks' prints first)")
            .clicked()
        {
            self.request_master_print();
        }
        if let Some((k, what)) = action {
            let ins = &mut self.session.master_inserts;
            match what {
                "bypass" => ins[k].bypass = !ins[k].bypass,
                "up" => ins.swap(k, k - 1),
                _ => {
                    ins.remove(k);
                    self.master_sel = None;
                }
            }
            changed = true;
        }
        if let Some(d) = add {
            self.add_master_insert(d);
            changed = true;
        }
        changed
    }

    /// One track's strip in the mixer. Returns whether it changed.
    fn mixer_strip(&mut self, ui: &mut egui::Ui, i: usize, width: f32, height: f32) -> bool {
        let colour = COLOURS[i % COLOURS.len()];
        let (rect, _) = ui.allocate_exact_size(egui::vec2(width, height), Sense::hover());
        let armed = self.session.armed == Some(i);
        let p = ui.painter_at(rect);
        p.rect_filled(
            rect.shrink2(egui::vec2(2.0, 0.0)),
            4.0,
            if armed { theme::CHROME3 } else { theme::CHROME },
        );
        p.rect_filled(
            Rect::from_min_size(
                rect.min + egui::vec2(2.0, 0.0),
                egui::vec2(width - 4.0, 4.0),
            ),
            0.0,
            colour,
        );
        let mut changed = false;
        let mut s = ui.new_child(
            egui::UiBuilder::new()
                .id_salt(("mixer_strip", i))
                .max_rect(rect.shrink2(egui::vec2(8.0, 8.0)))
                .layout(egui::Layout::top_down(egui::Align::Center)),
        );
        s.spacing_mut().item_spacing.y = 4.0;
        s.add_space(2.0);
        let t = &mut self.session.tracks[i];
        changed |= s
            .add(
                egui::TextEdit::singleline(&mut t.name)
                    .id_salt(("mixer_name", i))
                    .desired_width(width - 18.0),
            )
            .lost_focus();
        let mut arm = false;
        s.horizontal(|ui| {
            ui.spacing_mut().item_spacing.x = 3.0;
            let b = egui::Button::new(RichText::new("●").color(if armed {
                Color32::WHITE
            } else {
                REC
            }))
            .fill(if armed { REC } else { theme::CHROME2 })
            .min_size(egui::vec2(24.0, 18.0));
            if ui
                .add(b)
                .on_hover_text("Arm: records and plays the live device")
                .clicked()
            {
                arm = true;
            }
            for (on, text, col) in [
                (&mut t.mute, "M", theme::WARN),
                (&mut t.solo, "S", theme::OK),
            ] {
                let b = egui::Button::new(RichText::new(text).color(if *on {
                    theme::ACCENT_INK
                } else {
                    theme::MUTED
                }))
                .fill(if *on { col } else { theme::CHROME2 })
                .min_size(egui::vec2(24.0, 18.0));
                if ui.add(b).clicked() {
                    *on = !*on;
                    changed = true;
                }
            }
        });
        if arm && self.recording.is_none() {
            self.session.armed = Some(i);
            changed = true;
        }
        // The inserts, top to bottom (the same chips and panel as the arrangement's).
        s.label(RichText::new("INSERTS").small().color(theme::FAINT));
        let mut action: Option<(usize, &'static str)> = None;
        let mut add: Option<&'static str> = None;
        for k in 0..self.session.tracks[i].inserts.len() {
            let slot = &self.session.tracks[i].inserts[k];
            let short =
                find_device(&slot.device).map_or(slot.device.clone(), |d| d.short.to_string());
            let (glyph, colour, state) = self.insert_state(i, k);
            let selected = self.insert_selected() == Some((i, k));
            let bypass = slot.bypass;
            let b = egui::Button::new(
                RichText::new(format!("{short} {glyph}"))
                    .small()
                    .color(if bypass { theme::FAINT } else { colour }),
            )
            .fill(if selected { theme::CHROME3 } else { theme::BG })
            .stroke(Stroke::new(
                1.0,
                if selected { theme::ACCENT } else { theme::LINE },
            ))
            .min_size(egui::vec2(width - 18.0, 18.0));
            let r = s.add(b).on_hover_text(state);
            if r.clicked() {
                self.master_sel = None;
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
                if k > 0 && ui.button("Earlier").clicked() {
                    action = Some((k, "up"));
                    ui.close();
                }
                if ui.button("Remove").clicked() {
                    action = Some((k, "remove"));
                    ui.close();
                }
            });
        }
        s.menu_button(RichText::new("+ insert").small(), |ui| {
            for (group, ids) in vpanel::insert_menu() {
                theme::menu_heading(ui, group.title());
                for j in ids {
                    let d = &DEVICES[j];
                    if ui.button(d.label).on_hover_text(d.about).clicked() {
                        add = Some(d.id);
                        ui.close();
                    }
                }
            }
        });
        // Room for the most inserts any strip has and its Print, so the faders line up.
        let most = self
            .session
            .tracks
            .iter()
            .map(|t| t.inserts.len())
            .max()
            .unwrap_or(0);
        let have = self.session.tracks[i].inserts.len();
        s.add_space((most - have) as f32 * (18.0 + s.spacing().item_spacing.y));
        let mut print = false;
        if self.session.chain_signature(i).is_some()
            && !self.session.print_current(i)
            && !self.printing(i)
        {
            print = s
                .add(
                    egui::Button::new(RichText::new("Print").small().color(theme::ACCENT))
                        .min_size(egui::vec2(0.0, 18.0)),
                )
                .clicked();
        } else {
            s.add_space(18.0);
        }
        if let Some((k, what)) = action {
            let ins = &mut self.session.tracks[i].inserts;
            match what {
                "bypass" => ins[k].bypass = !ins[k].bypass,
                "up" => ins.swap(k, k - 1),
                _ => {
                    ins.remove(k);
                    if self.insert_sel.is_some_and(|(t, _)| t == i) {
                        self.insert_sel = None;
                    }
                }
            }
            changed = true;
        }
        if let Some(d) = add {
            self.add_insert(i, d);
            changed = true;
        }
        if print {
            self.request_print(i);
        }
        // Sends: their row is reserved until F4 builds them.
        s.label(RichText::new("SENDS —").small().color(theme::FAINT))
            .on_hover_text("Sends come with docs/SESSION_FX_PLAN.md F4");
        let t = &mut self.session.tracks[i];
        let stereo = t.is_stereo();
        changed |=
            crate::mixer::pan_knob(&mut s, &mut t.pan, 30.0, egui::Id::new(("mixer_pan", i)));
        // A stereo track's knob is a balance (each side turned down past the centre).
        let label = crate::mixer::pan_label(t.pan);
        s.label(
            RichText::new(if stereo {
                format!("BAL {label}")
            } else {
                label
            })
            .small()
            .color(theme::MUTED),
        )
        .on_hover_text(if stereo {
            "A stereo track: the knob is a balance (the other side turns down)"
        } else {
            "Pan"
        });
        let used = s.min_rect().height();
        let h = (height - used - 60.0).max(60.0);
        let meter = self.meters.tracks.get(i).cloned().unwrap_or_default();
        let t = &mut self.session.tracks[i];
        s.horizontal(|ui| {
            ui.add_space(10.0);
            changed |= crate::mixer::fader(
                ui,
                &mut t.volume_db,
                egui::vec2(26.0, h),
                true,
                egui::Id::new(("mixer_fader", i)),
            );
            ui.add_space(4.0);
            let (r, _) = ui.allocate_exact_size(egui::vec2(18.0, h), Sense::hover());
            crate::mixer::draw_meter(&ui.painter_at(r), r, &meter);
        });
        changed |= s
            .add(
                egui::DragValue::new(&mut t.volume_db)
                    .range(crate::mixer::FADER_MIN_DB..=crate::mixer::FADER_MAX_DB)
                    .speed(0.2)
                    .max_decimals(1)
                    .suffix(" dB"),
            )
            .on_hover_text("Fader (click to type)")
            .changed();
        s.label(
            RichText::new(format!("pk {:.1}", meter.hold_db[0].max(meter.hold_db[1])))
                .small()
                .color(if meter.clipped {
                    theme::FAULT
                } else {
                    theme::MUTED
                }),
        );
        changed
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
            && let Some((_, lane)) = track.lane()
        {
            let x: Vec<f64> = lane.iter().map(|&v| v as f64).collect();
            let level = audio::level_dbfs(&x, rate, 8.0);
            slot.trim_db = ((ALIGNMENT_DBFS - level).clamp(-40.0, 40.0) * 10.0).round() / 10.0;
        }
        track.inserts.push(slot);
        self.master_sel = None;
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
        let mut print = false;
        let mut render: Option<bool> = None;
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
            match (tr.lane(), &tr.printed) {
                (Some((_, lane)), Some(p)) if self.session.print_current(t) => {
                    let a: Vec<f64> = lane.iter().map(|&v| v as f64).collect();
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
        let live_line = match self.audition_status.as_ref() {
            Some(s) if self.audition.is_some() || self.loop_mode => s.clone(),
            _ => "not playing live".to_string(),
        };
        let stereo = self.session.tracks[t].is_stereo();
        let loop_mode = self.loop_mode;
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
            if ui
                .selectable_label(loop_mode, RichText::new("⟲ loop").small())
                .on_hover_text(LOOP_TIP)
                .clicked()
            {
                self.loop_mode = !loop_mode;
            }
            if stereo && !loop_mode {
                ui.add_space(12.0);
                ui.label(RichText::new("hear").small().color(theme::MUTED))
                    .on_hover_text(
                        "A stereo track prints each channel through its own copy of the \
                         device with the same knobs. Live, one copy plays: the channel you \
                         pick, up the middle.",
                    );
                for (h, name, tip) in [
                    (
                        Hear::Left,
                        "L",
                        "The left channel: exactly what its print gets",
                    ),
                    (
                        Hear::Right,
                        "R",
                        "The right channel: exactly what its print gets",
                    ),
                    (
                        Hear::Mid,
                        "mid",
                        "(L + R) / 2: near the whole for an EQ; a compressor or anything that \
                         saturates prints differently (each side has its own level)",
                    ),
                ] {
                    if ui
                        .selectable_label(self.hear == h, RichText::new(name).small())
                        .on_hover_text(tip)
                        .clicked()
                    {
                        self.hear = h;
                    }
                }
            }
            ui.add_space(12.0);
            ui.label(RichText::new(&live_line).small().color(theme::ACCENT))
                .on_hover_text(
                    "While this panel is open the device plays live on the track (Space plays \
                     the session); Print renders the chain for playback when you're happy \
                     with it (nothing prints by itself). The inserts after it aren't heard \
                     meanwhile.",
                );
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui.button("✕").on_hover_text("Close the panel").clicked() {
                    self.insert_sel = None;
                }
                if !self.session.print_current(t)
                    && !self.printing(t)
                    && ui
                        .button(RichText::new("Print").color(theme::ACCENT))
                        .on_hover_text(
                            "Render the track's chain for playback (in the background; Ctrl+R)",
                        )
                        .clicked()
                {
                    print = true;
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
                    render = Some(true);
                }
                if ui
                    .add_enabled(self.bake.is_none(), egui::Button::new("⤓ Draft"))
                    .on_hover_text(
                        "The same at draft quality (each insert at its play quality, as the \
                         mix's print: at once when the print is current), for demos",
                    )
                    .clicked()
                {
                    render = Some(false);
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
        if find_device(&device).is_some_and(|d| d.key.is_some()) {
            changed |= self.key_row(ui, t, k);
        }
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
        if let Some(production) = render {
            self.insert_sel = None;
            self.start_bake(t, production);
        }
        if print {
            self.request_print(t);
        }
        if changed {
            self.save();
        }
    }

    /// A keyed insert's KEY row: the track its key input listens to (none: the stock
    /// sidechain, KEY INT), the key's trim. Choosing a track sets KEY EXT and the trim (the
    /// key track's loudest stretch to the alignment level, set once); none sets INT.
    fn key_row(&mut self, ui: &mut egui::Ui, t: usize, k: usize) -> bool {
        let rate = self.session.rate;
        let route = self.session.tracks[t].inserts[k].key.clone();
        let current = route
            .as_ref()
            .and_then(|r| self.session.track_index(&r.track));
        let choices: Vec<(usize, String, bool)> = (0..self.session.tracks.len())
            .filter(|&i| i != t)
            .map(|i| {
                let ok = !self.session.would_cycle(t, i);
                (i, self.session.tracks[i].name.clone(), ok)
            })
            .collect();
        let shown = match (&route, current) {
            (None, _) => "none (INT: its own output)".to_string(),
            (Some(_), Some(i)) => self.session.tracks[i].name.clone(),
            (Some(_), None) => "a deleted track (silent)".to_string(),
        };
        let mut chosen: Option<Option<usize>> = None;
        let mut changed = false;
        ui.horizontal(|ui| {
            ui.label(RichText::new("KEY").strong().color(theme::ACCENT));
            egui::ComboBox::from_id_salt(("insert_key", t, k))
                .selected_text(shown)
                .show_ui(ui, |ui| {
                    if ui.selectable_label(route.is_none(), "none (INT)").clicked() {
                        chosen = Some(None);
                    }
                    for (i, name, ok) in &choices {
                        let r = ui
                            .add_enabled(*ok, egui::Button::selectable(current == Some(*i), name))
                            .on_disabled_hover_text("it is keyed from this track: a loop");
                        if r.clicked() {
                            chosen = Some(Some(*i));
                        }
                    }
                })
                .response
                .on_hover_text(
                    "Which track drives the sidechain (the KEY jack, KEY EXT): what it plays \
                     after its inserts, before its fader, muted or not. None: the 670's own \
                     output (KEY INT)",
                );
            if let Some(r) = &mut self.session.tracks[t].inserts[k].key {
                ui.label("Key trim");
                changed |= ui
                    .add(
                        egui::DragValue::new(&mut r.trim_db)
                            .range(-40.0..=40.0)
                            .speed(0.1)
                            .max_decimals(1)
                            .suffix(" dB"),
                    )
                    .on_hover_text(
                        "The fader in front of the key input. Keyed, the 670 has no ratio: \
                         a few dB more key goes from a light duck to the bass cut off \
                         (AC THRESHOLD sets where); DEPTH limits how deep it ducks (fully \
                         clockwise: no limit)",
                    )
                    .changed();
            }
        });
        if let Some(c) = chosen {
            let slot_key = match c {
                None => None,
                Some(i) => {
                    let level = self.session.tracks[i]
                        .playing(rate)
                        .map(|(_, a, _)| {
                            let x: Vec<f64> = a.iter().map(|&v| v as f64).collect();
                            audio::level_dbfs(&x, rate, 8.0)
                        })
                        .filter(|l| *l > -200.0);
                    Some(KeyRoute {
                        track: self.session.tracks[i].id.clone(),
                        trim_db: level.map_or(0.0, |l| {
                            ((ALIGNMENT_DBFS - l).clamp(-40.0, 40.0) * 10.0).round() / 10.0
                        }),
                    })
                }
            };
            let slot = &mut self.session.tracks[t].inserts[k];
            let mode = YValue::Int(i64::from(slot_key.is_some()));
            match slot.values.iter_mut().find(|(n, _)| n == "key_mode") {
                Some((_, v)) => *v = mode,
                None => slot.values.push(("key_mode".into(), mode)),
            }
            slot.key = slot_key;
            changed = true;
        }
        changed
    }

    /// The row of insert chips under a track's strip (+ adds one).
    fn inserts_row(&mut self, ui: &mut egui::Ui, i: usize) -> bool {
        let mut changed = false;
        let mut print = false;
        let mut bake: Option<bool> = None;
        let mut add: Option<&'static str> = None;
        let mut action: Option<(usize, &'static str)> = None;
        ui.horizontal(|ui| {
            ui.spacing_mut().item_spacing.x = 4.0;
            for k in 0..self.session.tracks[i].inserts.len() {
                let slot = &self.session.tracks[i].inserts[k];
                let (name, mut short) = find_device(&slot.device).map_or_else(
                    || (slot.device.clone(), slot.device.clone()),
                    |d| (d.label.to_string(), d.short.to_string()),
                );
                if let Some(r) = slot.key.as_ref().filter(|_| print_key_input(slot)) {
                    let key = self
                        .session
                        .track_index(&r.track)
                        .map_or("?", |j| self.session.tracks[j].name.as_str());
                    short = format!("{short} ⚷ {key}");
                }
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
                    self.master_sel = None;
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
                for (group, ids) in vpanel::insert_menu() {
                    theme::menu_heading(ui, group.title());
                    for j in ids {
                        let d = &DEVICES[j];
                        if ui.button(d.label).on_hover_text(d.about).clicked() {
                            add = Some(d.id);
                            ui.close();
                        }
                    }
                }
            })
            .response
            .on_hover_text(
                "Add a device to this track's chain (open it to hear it live while you turn \
                 it; Print renders the chain for playback)",
            );
            let has_chain = self.session.chain_signature(i).is_some();
            if has_chain && !self.session.print_current(i) && !self.printing(i) {
                let b = egui::Button::new(RichText::new("Print").small().color(theme::ACCENT))
                    .min_size(egui::vec2(0.0, 18.0));
                if ui
                    .add(b)
                    .on_hover_text(
                        "The inserts changed since the last print: render the chain for \
                         playback (in the background; Ctrl+R with the track selected)",
                    )
                    .clicked()
                {
                    print = true;
                }
            }
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
                        .on_hover_text(if b.production {
                            "Rendering into a new take at production quality"
                        } else {
                            "Rendering into a new take at draft quality"
                        });
                        if ui
                            .small_button("✕")
                            .on_hover_text("Cancel the render")
                            .clicked()
                        {
                            b.job.cancel();
                        }
                    }
                    _ => {
                        let free = self.bake.is_none() && self.recording.is_none();
                        if ui
                            .add_enabled(free, egui::Button::new(RichText::new("⤓ Render").small()))
                            .on_hover_text(
                                "Render this track through its inserts at production quality \
                                 into a new take, and remove the inserts (the effect is baked \
                                 in; the old take stays in the lane, Undo brings the inserts \
                                 back)",
                            )
                            .clicked()
                        {
                            bake = Some(true);
                        }
                        if ui
                            .add_enabled(free, egui::Button::new(RichText::new("⤓ Draft").small()))
                            .on_hover_text(
                                "The same at draft quality (each insert at its play quality, \
                                 as the mix's print: at once when the print is current), for \
                                 demos; Undo brings the inserts back for the final render",
                            )
                            .clicked()
                        {
                            bake = Some(false);
                        }
                    }
                }
            }
        });
        if let Some(production) = bake {
            self.start_bake(i, production);
        }
        if print {
            self.request_print(i);
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

    /// Render track `t`'s chain (its inserts not bypassed) into a new take: at production,
    /// or a draft (each insert at its device's play quality, the quality the mix's print
    /// is made at by default, so a current print comes from the cache at once).
    fn start_bake(&mut self, t: usize, production: bool) {
        if self.bake.is_some() {
            self.error = Some("one render at a time".into());
            return;
        }
        let Some(track) = self.session.tracks.get(t) else {
            return;
        };
        let Some((start, lane, lane_r)) = track.lane_lr() else {
            self.error = Some("the track has nothing in its lane to render".into());
            return;
        };
        let stereo = lane_r.is_some();
        let slots: Vec<Slot> = track
            .inserts
            .iter()
            .filter(|s| !s.bypass)
            .map(|s| Slot {
                quality: if production {
                    Quality::Production
                } else {
                    find_device(&s.device).map_or(Quality::Draft1x, |d| d.quality)
                },
                ..s.clone()
            })
            .collect();
        if slots.is_empty() {
            return;
        }
        let job = Job::spawn(
            self.root.join("config"),
            slots.clone(),
            self.session.sidechains(t),
            lane,
            lane_r,
            self.session.rate,
            Some(self.session.dir.join("prints")),
        );
        self.bake = Some(Bake {
            track: t,
            start,
            stereo,
            clips: track.clips.clone(),
            slots,
            production,
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
        let (audio, right) = match b.job.join() {
            Some(Ok(prints)) => match prints.last() {
                // A stereo insert (a reverb with STEREO on) makes a mono track's take stereo.
                Some(p) => (
                    (*p.audio).clone(),
                    (b.stereo || p.right.is_some())
                        .then(|| (*p.right.clone().unwrap_or_else(|| p.audio.clone())).clone()),
                ),
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
        if b.track >= self.session.tracks.len() {
            self.error = Some("the rendered track is gone".into());
            return;
        }
        let pos = b.start;
        // A keyed insert's key: the track and the lane it played then.
        let keys: Vec<Value> = b
            .slots
            .iter()
            .filter_map(|s| s.key.as_ref())
            .filter_map(|r| {
                let i = self.session.track_index(&r.track)?;
                let t = &self.session.tracks[i];
                let (start, _) = t.lane_span()?;
                Some(json!({"track": r.track, "lane": t.source_signature(), "position": start}))
            })
            .collect();
        let from = json!({
            "clips": b.clips.iter().map(Clip::to_json).collect::<Vec<_>>(),
            "keys": keys,
            "inserts": b.slots.iter().map(Slot::to_json).collect::<Vec<_>>(),
            "quality": if b.production { Quality::Production.name() } else { "draft" },
            "code": circuitsim::SOURCE_HASH,
        });
        self.saved = true;
        match self
            .session
            .add_rendered_take(b.track, audio, right, pos, from)
        {
            Ok(_) => {
                // The lane is the render now (its clips baked in; Undo brings them back).
                let t = &mut self.session.tracks[b.track];
                if let Some(k) = t.active {
                    t.set_active(k);
                }
                t.inserts.retain(|s| s.bypass);
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
                    "Record into the armed track (R): the count-in, then from the cursor",
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
                    .on_hover_text(
                        "Play from the cursor (Space; Shift+Space: from where it stopped)",
                    )
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
                _ if st.take_preparing => ("PREPARING", theme::WARN),
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
                    if play.monitor_proxy() {
                        format!("{} through its proxy", play.device_label_id().0)
                    } else {
                        play.device_label_id().0
                    },
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
        let rate = self.session.rate;
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
            .on_hover_text("The tracks play before the cursor; a take starts at it");
            ui.checkbox(&mut s.punch, "punch").on_hover_text(
                "Punch in / out: a take records only between the locators (the loop off); \
                 the tracks play before and after it",
            );
            ui.add_space(8.0);
            ui.label("cursor");
            let grid = Grid::new(rate, s);
            let spb = grid.samples_per_beat();
            ui.add(
                egui::DragValue::new(&mut s.cursor)
                    .range(0..=i64::MAX / 4)
                    .speed(spb / 16.0)
                    .custom_formatter(move |v, _| grid.label(v as i64))
                    .custom_parser(move |t| {
                        let mut it = t.split('.');
                        let bar: i64 = it.next()?.trim().parse().ok()?;
                        let beat: i64 = it.next().map_or(Some(1), |b| b.trim().parse().ok())?;
                        let six: i64 = it.next().map_or(Some(1), |b| b.trim().parse().ok())?;
                        let k = (bar - 1) * grid.beats_per_bar as i64 + beat - 1;
                        Some(grid.beat(k) as f64 + (six - 1) as f64 * spb / 4.0)
                    }),
            )
            .on_hover_text(
                "Where play starts and a take records (bar.beat.sixteenth): click the ruler \
                 or empty lane space, Home / End, Ctrl+← / →",
            );
            ui.checkbox(&mut s.return_to_cursor, "return")
                .on_hover_text(
                    "Stop puts the playhead back at the cursor; off, the cursor stays where \
                     play stopped (Shift+Space always plays from there)",
                );
            ui.add_space(8.0);
            ui.label("snap");
            egui::ComboBox::from_id_salt("snap")
                .width(56.0)
                .selected_text(s.snap.label())
                .show_ui(ui, |ui| {
                    for m in Snap::ALL {
                        ui.selectable_value(&mut s.snap, m, m.label());
                    }
                })
                .response
                .on_hover_text(
                    "What moving takes, the cursor and the locators snap to (Alt inverts it \
                     for the gesture: free when on, the beat when off). A snapped move keeps \
                     a take's offset from the grid",
                );
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
                "The right locator (bar.beat): Shift+click the ruler",
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
        if ui
            .small_button("New")
            .on_hover_text(
                "A new session with everything at its defaults: tempo, meter, click, \
                 locators and the room (this one stays as saved)",
            )
            .clicked()
        {
            self.new_session();
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
        self.export_controls(ui);
        let (edits, prints) = (self.renders_missing(), self.prints_missing());
        if !edits.is_empty()
            && ui
                .small_button(format!("Render edits ({})", edits.len()))
                .on_hover_text(
                    "Render every edited MIDI take that isn't rendered on its device yet (a \
                     draft, at the quality it was played at; they play the proxy or their \
                     last render until then)",
                )
                .clicked()
        {
            for &(t, k) in &edits {
                self.request_render(t, k, false);
            }
        }
        if !prints.is_empty()
            && ui
                .small_button(format!("Print inserts ({})", prints.len()))
                .on_hover_text(
                    "Print every track whose inserts changed since its last print (it plays \
                     that print, stale, or dry until then)",
                )
                .clicked()
        {
            for &t in &prints {
                self.request_print(t);
            }
        }
        if !edits.is_empty()
            && !prints.is_empty()
            && ui
                .small_button(format!("Render all ({})", edits.len() + prints.len()))
                .on_hover_text("Both: the edited takes' renders and the inserts' prints")
                .clicked()
        {
            for (t, k) in edits {
                self.request_render(t, k, false);
            }
            for t in prints {
                self.request_print(t);
            }
        }
        let missing = self.production_missing();
        if !missing.is_empty()
            && ui
                .small_button(format!("⤓ Production ({})", missing.len()))
                .on_hover_text("Render every event take that has no production render yet (one at a time, in the background)")
                .clicked()
        {
            for (t, k) in missing {
                self.render_production(t, k);
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
        ui.add_space(4.0);
        self.toolbar(ui);
        ui.add_space(4.0);
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
            // Ctrl+wheel over the strips: the tracks' height (SE7); over the lanes: zoom.
            let over_strips = pointer.is_some_and(|p| p.x < full.left() + STRIP_W);
            if zoom != 1.0 && over_strips {
                self.track_h = (self.track_h * zoom).clamp(MIN_TRACK_H, 320.0);
            } else if zoom != 1.0 {
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
        // Clicks and drags on the bars. Locators sit on beats (on bars with the bar snap).
        let bar_snap = self.session.transport.snap == Snap::Bar;
        let snap = |x: f32| {
            let p = view.position(x);
            if bar_snap {
                let per = grid.beats_per_bar as i64;
                let k = grid.beat_at(p + (grid.samples_per_beat() * per as f64 * 0.5) as i64);
                k - k.rem_euclid(per)
            } else {
                grid.beat_at(p + (grid.samples_per_beat() * 0.5) as i64)
            }
        };
        let marker_at = |x: f32, markers: &[Marker]| {
            markers
                .iter()
                .position(|m| (view.x(m.position) - x).abs() < 6.0)
        };
        if resp.secondary_clicked()
            && let Some(p) = resp.interact_pointer_pos()
        {
            self.ruler_menu = Some((view.position(p.x), marker_at(p.x, &self.session.markers)));
        }
        let mut marker_action: Option<(Option<usize>, i64)> = None;
        resp.context_menu(|ui| {
            let Some((pos, m)) = self.ruler_menu else {
                return;
            };
            if let Some(i) = m.filter(|&i| i < self.session.markers.len()) {
                let name = self.session.markers[i].name.clone();
                ui.label(RichText::new(format!("marker {name}")).color(theme::MUTED));
                ui.text_edit_singleline(&mut self.session.markers[i].name);
                if ui.button("Delete marker").clicked() {
                    marker_action = Some((Some(i), pos));
                    ui.close();
                }
            } else if ui.button("Add a marker here").clicked() {
                marker_action = Some((None, pos));
                ui.close();
            }
            ui.separator();
            if ui
                .button("Insert time between the locators")
                .on_hover_text("Every track's clips (and the markers) from the left locator on move later by the locators' span; clips across it are split")
                .clicked()
            {
                self.time_edit = Some(true);
                ui.close();
            }
            if ui
                .button("Delete time between the locators")
                .on_hover_text("Everything between the locators goes on every track; what comes after moves earlier to close the gap")
                .clicked()
            {
                self.time_edit = Some(false);
                ui.close();
            }
        });
        if let Some(insert) = self.time_edit.take() {
            let t = &self.session.transport;
            let (a, b) = (grid.beat(t.left_beat), grid.beat(t.right_beat));
            if insert {
                self.session.insert_time(a, b - a);
            } else {
                self.session.delete_time(a, b);
            }
            self.selected = None;
            self.range_sel = None;
            self.save();
        }
        match marker_action {
            Some((Some(i), _)) => {
                self.session.markers.remove(i);
                self.save();
            }
            Some((None, pos)) => {
                let snap = self.session.transport.snap;
                self.add_marker(grid.snap(pos, snap).max(0));
            }
            None => {}
        }
        let (markers, snap_setting) = (self.session.markers.clone(), self.session.transport.snap);
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
            let (ctrl, shift, alt) =
                ui.input(|i| (i.modifiers.command, i.modifiers.shift, i.modifiers.alt));
            let k = snap(p.x).max(0);
            if ctrl {
                t.left_beat = k.min(t.right_beat - 1);
            } else if shift {
                t.right_beat = k.max(t.left_beat + 1);
            } else if let Some(i) =
                marker_at(p.x, &markers).filter(|_| p.y < ruler.top() + RULER_H * 0.5)
            {
                t.cursor = markers[i].position;
                self.relocate = running;
            } else {
                let pos = grid.snap(view.position(p.x), snap_setting.inverted(alt));
                t.cursor = pos.max(0);
                self.relocate = running;
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
        draw_markers(&painter, lanes_rect, &view, &self.session.markers);
        // The tracks, above the scrollbar.
        const BAR_H: f32 = 16.0;
        let mut changed = false;
        let tracks_h = (ui.available_height() - BAR_H - 4.0).max(40.0);
        self.prev_lanes = std::mem::take(&mut self.lanes);
        let tracks_area = egui::ScrollArea::vertical()
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
                    if let Some(imp) = &self.import {
                        ui.add_enabled(false, egui::Button::new("Import…"));
                        ui.label(
                            RichText::new(format!("importing {} files…", imp.files))
                                .small()
                                .color(theme::MUTED),
                        );
                    } else {
                        if ui
                            .button("Import…")
                            .on_hover_text(
                                "Audio files (WAV, AIFF, FLAC, Ogg, MP3) as new tracks, one per \
                                 file, at bar 1: several picked at once line up as stems. \
                                 Converted to the session's rate; a stereo file is averaged \
                                 to mono (tracks are mono, panned)",
                            )
                            .clicked()
                        {
                            self.start_import();
                        }
                        let before = (self.import_normalize, self.import_target_dbfs);
                        egui::ComboBox::from_id_salt("import_normalize")
                            .selected_text(self.import_normalize.label())
                            .show_ui(ui, |ui| {
                                for m in ImportNormalize::ALL {
                                    ui.selectable_value(&mut self.import_normalize, m, m.label());
                                }
                            })
                            .response
                            .on_hover_text(
                                "Normalize brings a file's loudest 8 s (its rms, as a sine's                                  peak) to the level, as the Play view does; -18 dBFS is what                                  the devices are aligned to. Each: every file on its own.                                  Together: one gain for all the files picked, from their sum,                                  so a multitrack's stems keep their balance",
                            );
                        if self.import_normalize != ImportNormalize::Off {
                            ui.add(
                                egui::DragValue::new(&mut self.import_target_dbfs)
                                    .range(-60.0..=0.0)
                                    .speed(0.1)
                                    .fixed_decimals(1)
                                    .suffix(" dBFS"),
                            );
                        }
                        if (self.import_normalize, self.import_target_dbfs) != before {
                            self.save_prefs();
                        }
                        if let Some(n) = &self.import_note {
                            ui.label(RichText::new(n).small().color(theme::MUTED));
                        }
                    }
                });
            })
            .inner_rect;
        self.file_drop(ui, tracks_area, &view, &grid);
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
            egui::vec2(width, self.track_h + shown as f32 * TAKE_H),
            Sense::hover(),
        );
        let row = Rect::from_min_size(whole.min, egui::vec2(width, self.track_h));
        let strip = Rect::from_min_size(row.min, egui::vec2(STRIP_W, self.track_h));
        let lane = Rect::from_min_max(Pos2::new(row.left() + STRIP_W, row.top()), row.max);
        self.lanes.push((i, lane.intersect(ui.clip_rect())));
        // The strip and lane take clicks and drags; the strip's controls, added after, sit
        // on top of them.
        let strip_resp = ui.interact(strip, ui.id().with(("strip", i)), Sense::click());
        let lane_resp = ui.interact(lane, ui.id().with(("lane", i)), Sense::click_and_drag());
        let mut changed = false;
        // The lane's clips (SE5): a click selects one, a drag moves it (to another track
        // too), a drag on an edge trims it, on a top corner's handle sets its fade, on the
        // gain handle (top middle) its gain. What a press grabs is decided where it went
        // down.
        let rects: Vec<(usize, Rect)> = {
            let t = &self.session.tracks[i];
            t.clips
                .iter()
                .enumerate()
                .map(|(c, clip)| (c, clip_box(view, lane, clip.position, clip.end())))
                .collect()
        };
        let rate = self.session.rate;
        let grab_at = |p: Pos2, t: &Track| -> Option<(usize, DragKind)> {
            let (c, r) = rects.iter().rev().find(|(_, r)| r.contains(p))?;
            let clip = &t.clips[*c];
            let px = |n: usize| (n as f64 / rate as f64 * view.px_per_s) as f32;
            let near = |x: f32| (p.x - x).abs() < 5.0;
            let top = p.y < r.top() + 12.0;
            let kind = if top && near(r.left() + px(clip.fade_in).max(6.0)) {
                DragKind::FadeIn
            } else if top && near(r.right() - px(clip.fade_out).max(6.0)) {
                DragKind::FadeOut
            } else if top && (p.x - r.center().x).abs() < 14.0 && r.width() > 60.0 {
                DragKind::Gain
            } else if r.width() > 16.0 && p.x < r.left() + 5.0 {
                DragKind::TrimLeft
            } else if r.width() > 16.0 && p.x > r.right() - 5.0 {
                DragKind::TrimRight
            } else {
                DragKind::Move
            };
            Some((*c, kind))
        };
        let origin = ui.input(|x| x.pointer.press_origin());
        let (ctrl, shift, alt) =
            ui.input(|x| (x.modifiers.command, x.modifiers.shift, x.modifiers.alt));
        // SE8: the Blade, Erase and Envelope tools act on the clip under a press (on empty
        // lane space every tool does what the pointer does).
        let mut tool_used = false;
        if (lane_resp.clicked() || lane_resp.drag_started())
            && self.recording.is_none()
            && let Some(p) = origin
                .or(lane_resp.interact_pointer_pos())
                .filter(|p| lane.contains(*p))
            && let Some(&(c, r)) = rects.iter().rev().find(|(_, r)| r.contains(p))
        {
            match self.tool {
                Tool::Blade | Tool::Erase => {
                    tool_used = true;
                    if lane_resp.clicked() {
                        if self.tool == Tool::Blade {
                            let snap = self.session.transport.snap.inverted(alt);
                            let mut at = grid.snap(view.position(p.x), snap);
                            if self.zero_cross {
                                at = self.session.tracks[i].zero_crossing(c, at, rate);
                            }
                            if let Some(k) = self.session.tracks[i].split_clip(c, at, rate) {
                                self.selected = Some((i, k));
                                changed = true;
                            }
                        } else {
                            self.session.tracks[i].delete_clip(c, self.ripple);
                            self.selected = None;
                            changed = true;
                        }
                    }
                }
                Tool::Envelope => {
                    tool_used = true;
                    let clip = &mut self.session.tracks[i].clips[c];
                    let near = clip.env.iter().position(|&(o, d)| {
                        (view.x(clip.position + o) - p.x).abs() < 6.0
                            && (env_y(r, d) - p.y).abs() < 6.0
                    });
                    let off = ((p.x - view.x(clip.position)) as f64 / view.px_per_s * view.rate)
                        .round() as i64;
                    let db = env_db_at(r, p.y);
                    if lane_resp.drag_started() {
                        let k = near.unwrap_or_else(|| {
                            clip.set_env_point(off, db);
                            let off = off.clamp(0, clip.len as i64);
                            clip.env.iter().position(|q| q.0 == off).unwrap_or(0)
                        });
                        self.env_drag = Some((i, c, k));
                    } else {
                        match near {
                            Some(k) => {
                                clip.env.remove(k);
                            }
                            None => clip.set_env_point(off, db),
                        }
                        changed = true;
                    }
                    self.selected = Some((i, c));
                    self.range_sel = None;
                }
                Tool::Pointer | Tool::Slip => {}
            }
            if tool_used && self.session.armed != Some(i) {
                self.session.armed = Some(i);
                changed = true;
            }
        }
        if lane_resp.dragged()
            && let Some((ti, c, k)) = self.env_drag
            && ti == i
            && let Some(p) = ui.ctx().pointer_interact_pos()
            && let Some(&(_, r)) = rects.get(c)
            && let Some(clip) = self.session.tracks[i].clips.get_mut(c)
            && k < clip.env.len()
        {
            let lo = if k == 0 { 0 } else { clip.env[k - 1].0 + 1 };
            let hi = match clip.env.get(k + 1) {
                Some(q) => q.0 - 1,
                None => clip.len as i64,
            };
            let off =
                ((p.x - view.x(clip.position)) as f64 / view.px_per_s * view.rate).round() as i64;
            clip.env[k] = (off.clamp(lo, hi.max(lo)), env_db_at(r, p.y));
        }
        if lane_resp.drag_stopped() && self.env_drag.is_some_and(|d| d.0 == i) {
            self.env_drag = None;
            changed = true;
        }
        // Select (and arm) the track; select a clip, drag it.
        if !tool_used && (strip_resp.clicked() || lane_resp.clicked() || lane_resp.drag_started()) {
            if self.session.armed != Some(i) && self.recording.is_none() {
                self.session.armed = Some(i);
                changed = true;
            }
            let at = origin
                .or(lane_resp.interact_pointer_pos())
                .filter(|p| lane.contains(*p));
            let hit = at.and_then(|p| grab_at(p, &self.session.tracks[i]));
            if strip_resp.clicked() {
                self.selected = None;
            } else {
                self.selected = hit.map(|(c, _)| (i, c));
            }
            if hit.is_some() || lane_resp.clicked() {
                self.range_sel = None;
            }
            // A drag on empty lane space selects a range (time x tracks: SE6).
            if lane_resp.drag_started()
                && hit.is_none()
                && let Some(p) = at
            {
                let alt = ui.input(|x| x.modifiers.alt);
                let snap = self.session.transport.snap.inverted(alt);
                self.range_drag = Some((i, grid.snap(view.position(p.x), snap)));
            }
            // A click on empty lane space puts the cursor there (snapped; Alt: inverted).
            if lane_resp.clicked()
                && hit.is_none()
                && let Some(p) = lane_resp.interact_pointer_pos()
                && lane.contains(p)
            {
                let alt = ui.input(|x| x.modifiers.alt);
                let snap = self.session.transport.snap.inverted(alt);
                self.session.transport.cursor = grid.snap(view.position(p.x), snap).max(0);
                self.relocate = playhead.is_some();
                changed = true;
            }
            if lane_resp.drag_started()
                && let (Some((mut c, mut kind)), Some(p)) = (hit, at)
            {
                // The Slip tool slides the audio wherever the clip is grabbed; the pointer
                // does with Ctrl on its body, and Shift drags a copy (SE8).
                if self.tool == Tool::Slip || (kind == DragKind::Move && ctrl) {
                    kind = DragKind::Slip;
                } else if kind == DragKind::Move && shift {
                    let t = &mut self.session.tracks[i];
                    let mut copy = t.clips[c].clone();
                    copy.id = new_clip_id();
                    t.clips.push(copy);
                    c = t.clips.len() - 1;
                    self.selected = Some((i, c));
                }
                self.drag = Some(Drag {
                    track: i,
                    clip: c,
                    kind,
                    from: self.session.tracks[i].clips[c].clone(),
                    press: p,
                });
            }
        }
        if lane_resp.dragged()
            && let Some((t0, a)) = self.range_drag
            && t0 == i
            && let Some(p) = ui.ctx().pointer_interact_pos()
        {
            let alt = ui.input(|x| x.modifiers.alt);
            let b = grid.snap(
                view.position(p.x),
                self.session.transport.snap.inverted(alt),
            );
            let t1 = self
                .prev_lanes
                .iter()
                .find(|(_, r)| p.y >= r.top() && p.y < r.bottom())
                .map_or(i, |(j, _)| *j);
            self.range_sel = Some((a.min(b), a.max(b), t0.min(t1), t0.max(t1)));
        }
        if lane_resp.drag_stopped() && self.range_drag.is_some_and(|(t0, _)| t0 == i) {
            self.range_drag = None;
            if self.range_sel.is_some_and(|(a, b, _, _)| b <= a) {
                self.range_sel = None;
            }
        }
        if lane_resp.dragged()
            && let Some(d) = &self.drag
            && d.track == i
            && let Some(p) = ui.ctx().pointer_interact_pos()
        {
            let alt = ui.input(|x| x.modifiers.alt);
            let snap = self.session.transport.snap.inverted(alt);
            let delta = ((p.x - d.press.x) as f64 / view.px_per_s * view.rate).round() as i64;
            let (c, from, kind) = (d.clip, d.from.clone(), d.kind);
            let t = &mut self.session.tracks[i];
            let take_len = t
                .take_of(&from)
                .map_or(from.src_start + from.len, Take::len);
            let fade = default_fade(rate);
            if let Some(clip) = t.clips.get_mut(c) {
                match kind {
                    // Whole steps of the snap (SE2, decision 4: a clip off the grid stays as
                    // far off it).
                    DragKind::Move => clip.position = from.position + grid.snap_delta(delta, snap),
                    DragKind::TrimLeft => {
                        let lo = from.position - from.src_start as i64;
                        let edge = grid
                            .snap(from.position + delta, snap)
                            .clamp(lo, from.end() - 1);
                        let d = edge - from.position;
                        clip.position = edge;
                        clip.src_start = (from.src_start as i64 + d) as usize;
                        clip.len = (from.len as i64 - d) as usize;
                        if clip.src_start > 0 && from.fade_in == 0 {
                            clip.fade_in = fade;
                        }
                        // The envelope stays where it was on the timeline.
                        if !from.env.is_empty() {
                            clip.env = from.env_window(d, from.len as i64);
                        }
                    }
                    DragKind::Slip => {
                        let d = grid.snap_delta(delta, snap);
                        let max = take_len.saturating_sub(from.len) as i64;
                        clip.src_start = (from.src_start as i64 - d).clamp(0, max) as usize;
                    }
                    DragKind::TrimRight => {
                        let hi = from.position + (take_len - from.src_start) as i64;
                        let end = grid
                            .snap(from.end() + delta, snap)
                            .clamp(from.position + 1, hi.max(from.position + 1));
                        clip.len = (end - from.position) as usize;
                        if (clip.src_start + clip.len) < take_len && from.fade_out == 0 {
                            clip.fade_out = fade;
                        }
                    }
                    DragKind::FadeIn => {
                        let n = ((p.x - view.x(from.position)) as f64 / view.px_per_s * view.rate)
                            .round()
                            .max(0.0) as usize;
                        clip.fade_in = n.min(from.len / 2);
                    }
                    DragKind::FadeOut => {
                        let n = ((view.x(from.end()) - p.x) as f64 / view.px_per_s * view.rate)
                            .round()
                            .max(0.0) as usize;
                        clip.fade_out = n.min(from.len / 2);
                    }
                    DragKind::Gain => {
                        let db = from.gain_db + (d.press.y - p.y) as f64 * 0.1;
                        clip.gain_db = (db * 10.0).round().clamp(-400.0, 120.0) / 10.0;
                    }
                }
            }
        }
        if lane_resp.drag_stopped()
            && let Some(d) = self.drag.take()
        {
            let moved = self.session.tracks[d.track]
                .clips
                .get(d.clip)
                .is_some_and(|c| *c != d.from);
            changed |= moved;
            // Dropped on another track's lane: the clip goes there (its take with it).
            if d.kind == DragKind::Move
                && let Some(p) = ui.ctx().pointer_interact_pos()
                && let Some(&(j, _)) = self
                    .prev_lanes
                    .iter()
                    .find(|(j, r)| *j != d.track && r.contains(p))
            {
                changed |= self.move_clip(d.track, d.clip, j);
            }
        }
        if lane_resp.secondary_clicked() {
            let p = lane_resp.interact_pointer_pos();
            self.menu_clip = p
                .and_then(|p| grab_at(p, &self.session.tracks[i]))
                .map(|(c, _)| (i, c));
            if let Some(m) = self.menu_clip {
                self.selected = Some(m);
            }
        }
        let mut delete_take = None;
        let mut take_action: Option<(usize, u8)> = None;
        let mut place_take: Option<(usize, bool)> = None;
        let mut clip_action: Option<(usize, &'static str)> = None;
        let mut normalize: Option<(usize, bool)> = None;
        let mut clip_op: Option<(usize, ClipOp)> = None;
        lane_resp.context_menu(|ui| {
            let t = &self.session.tracks[i];
            let Some(c) = self
                .menu_clip
                .filter(|m| m.0 == i)
                .map(|m| m.1)
                .filter(|&c| c < t.clips.len())
            else {
                ui.label(RichText::new("no clip here").color(theme::MUTED));
                return;
            };
            let clip = &t.clips[c];
            let Some(k) = t.take_index(&clip.take) else {
                return;
            };
            ui.label(
                RichText::new(format!("clip of take {}", clip.take))
                    .small()
                    .color(theme::MUTED),
            );
            let cursor = self.session.transport.cursor;
            if ui
                .add_enabled(
                    cursor > clip.position && cursor < clip.end(),
                    egui::Button::new("Split at the cursor (S)"),
                )
                .clicked()
            {
                clip_action = Some((c, "split"));
                ui.close();
            }
            if ui
                .button(if clip.muted { "Unmute clip" } else { "Mute clip" })
                .clicked()
            {
                clip_action = Some((c, "mute"));
                ui.close();
            }
            if ui
                .button("Reset gain and fades")
                .on_hover_text("0 dB; no fades at the take's own ends, the default at cuts, a linear shape (its envelope and polarity stay)")
                .clicked()
            {
                clip_action = Some((c, "reset"));
                ui.close();
            }
            if ui.button("Delete clip (Delete)").clicked() {
                clip_action = Some((c, "delete"));
                ui.close();
            }
            ui.separator();
            // Normalize: the clip's gain set so its stretch of the take meets a target (the
            // take untouched; Undo, or "Reset gain and fades", takes it back).
            ui.horizontal(|ui| {
                if ui
                    .button("Normalize peak to")
                    .on_hover_text(
                        "The clip's gain set so its loudest sample (either channel) is at the \
                         target",
                    )
                    .clicked()
                {
                    normalize = Some((c, true));
                    ui.close();
                }
                ui.add(
                    egui::DragValue::new(&mut self.normalize_peak_dbfs)
                        .range(-60.0..=0.0)
                        .speed(0.1)
                        .max_decimals(1)
                        .suffix(" dBFS"),
                );
            });
            ui.horizontal(|ui| {
                if ui
                    .button("Normalize level to")
                    .on_hover_text(
                        "The clip's gain set so its loudest 8 s is at the target as a sine's \
                         peak (as an import's normalize; a stereo clip: its louder channel)",
                    )
                    .clicked()
                {
                    normalize = Some((c, false));
                    ui.close();
                }
                ui.add(
                    egui::DragValue::new(&mut self.normalize_level_dbfs)
                        .range(-60.0..=0.0)
                        .speed(0.1)
                        .max_decimals(1)
                        .suffix(" dBFS"),
                );
            });
            ui.separator();
            if let Some(o) = self.clip_ops_ui(ui, i, c) {
                clip_op = Some((c, o));
            }
            ui.separator();
            let t = &self.session.tracks[i];
            let take = &t.takes[k];
            if take.latency != 0 {
                let ms = take.latency as f64 / self.session.rate as f64 * 1e3;
                let (label, hover, heard) = if take.heard {
                    (
                        format!("Place on the click ({ms:.0} ms earlier)"),
                        "Where you meant it if you played to the click, not to what you heard: the monitor's latency taken off (its clips move with it)",
                        false,
                    )
                } else {
                    (
                        format!("Place as heard ({ms:.0} ms later)"),
                        "Where it was recorded: it plays against the click and the other tracks exactly as the monitor played it (its clips move with it)",
                        true,
                    )
                };
                if ui.button(label).on_hover_text(hover).clicked() {
                    place_take = Some((k, heard));
                    ui.close();
                }
                ui.separator();
            }
            if t.takes[k].events.is_some() {
                if ui.button("Piano roll").clicked() {
                    take_action = Some((k, 0));
                    ui.close();
                }
                let needs = t.takes[k].needs_render(t.drafts);
                if ui
                    .add_enabled(needs, egui::Button::new("Render the edit (draft)"))
                    .on_hover_text("Render this revision on the device at the quality it was played at (Ctrl+R)")
                    .on_disabled_hover_text("Its revision is rendered")
                    .clicked()
                {
                    take_action = Some((k, 4));
                    ui.close();
                }
                let has = t.takes[k].has_render(Quality::Production);
                if ui
                    .add_enabled(!has, egui::Button::new("Render at production"))
                    .clicked()
                {
                    take_action = Some((k, 1));
                    ui.close();
                }
                if ui
                    .button("Bounce to audio (production)")
                    .on_hover_text("Its production render (rendered first if it isn't there yet) as audio clips on this track where its MIDI clips are; the MIDI clips muted beside them")
                    .clicked()
                {
                    take_action = Some((k, 3));
                    ui.close();
                }
                let mut drafts = t.drafts;
                if ui
                    .checkbox(&mut drafts, "Play drafts on this track")
                    .on_hover_text("Its event takes play their draft renders over production ones (to compare)")
                    .clicked()
                {
                    take_action = Some((k, 2));
                    ui.close();
                }
                ui.separator();
            }
            if ui
                .button(format!("Delete take {} and its clips", t.takes[k].id))
                .on_hover_text("Out of the track (its files stay in the session's folder; Undo brings it back)")
                .clicked()
            {
                delete_take = Some(k);
                ui.close();
            }
        });
        let mut delete_track = false;
        let mut move_track: Option<usize> = None;
        let n_tracks = self.session.tracks.len();
        strip_resp.context_menu(|ui| {
            if ui
                .add_enabled(i > 0, egui::Button::new("Move up"))
                .clicked()
            {
                move_track = Some(i - 1);
                ui.close();
            }
            if ui
                .add_enabled(i + 1 < n_tracks, egui::Button::new("Move down"))
                .clicked()
            {
                move_track = Some(i + 1);
                ui.close();
            }
            ui.separator();
            if ui
                .button(format!("Delete track {}", self.session.tracks[i].name))
                .clicked()
            {
                delete_track = true;
                ui.close();
            }
        });
        if let Some(to) = move_track {
            self.move_track(i, to);
            changed = true;
        }
        if let Some((c, what)) = clip_action {
            changed |= self.clip_action(i, c, what);
        }
        if let Some((c, o)) = clip_op {
            changed |= self.apply_clip_op(i, c, o);
        }
        if let Some((c, peak)) = normalize {
            let target = if peak {
                self.normalize_peak_dbfs
            } else {
                self.normalize_level_dbfs
            };
            match self.session.tracks[i].normalize_clip(c, peak, target, self.session.rate) {
                Some(_) => changed = true,
                None => self.error = Some("the clip is silent: nothing to normalize".into()),
            }
        }
        // Paint.
        let armed = self.session.armed == Some(i);
        let painter = ui.painter_at(row);
        painter.rect_filled(
            strip,
            0.0,
            if armed { theme::CHROME3 } else { theme::CHROME },
        );
        painter.rect_filled(
            Rect::from_min_size(strip.min, egui::vec2(4.0, self.track_h)),
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
        let printed = track.playing(self.session.rate).is_some_and(|p| p.2);
        let no_wave = Overview::new(OVERVIEW_BIN);
        for (c, clip) in track.clips.iter().enumerate() {
            let Some(k) = track.take_of(clip) else {
                continue;
            };
            let ki = track.take_index(&clip.take).unwrap_or(0);
            let mut label = match &k.events {
                Some(_) => format!("{} · ♪ {}", k.id, self.take_status(i, ki)),
                None => k.id.clone(),
            };
            if printed {
                label.push_str(" · with inserts");
            }
            if clip.gain_db != 0.0 {
                label.push_str(&format!(" · {:+.1} dB", clip.gain_db));
            }
            if clip.invert {
                label.push_str(" · Ø");
            }
            if clip.muted {
                label.push_str(" · muted");
            }
            // A MIDI take shows its notes, not the audio it plays.
            let (_, ov, _) = k.sound(track.drafts);
            let ov = if k.events.is_some() { &no_wave } else { ov };
            let col = if clip.muted { theme::FAINT } else { colour };
            let r = clip_box(view, lane, clip.position, clip.end());
            draw_clip_from(
                &lp,
                lane,
                view,
                clip.position,
                clip.len,
                ov,
                clip.src_start,
                clip.gain_db,
                col,
                &label,
            );
            draw_fades(&lp, r, view, clip, col);
            if !clip.env.is_empty() || self.tool == Tool::Envelope {
                draw_envelope(&lp, r, view, clip, self.tool == Tool::Envelope);
            }
            if let Some(e) = &k.events {
                draw_notes(
                    &lp,
                    r,
                    view,
                    clip.position - clip.src_start as i64,
                    e.from,
                    &e.perf.notes(),
                    col,
                );
            }
            if self.selected == Some((i, c)) {
                lp.rect_stroke(r, 3.0, Stroke::new(2.0, theme::INK), StrokeKind::Inside);
            }
        }
        if armed && let Some(r) = &self.recording {
            // A MIDI take draws its notes as they're played, an audio take its waveform.
            let (ov, label) = match &r.notes {
                Some(_) => (&no_wave, "recording MIDI"),
                None => (&r.overview, "recording audio"),
            };
            let at = if self.session.place_heard {
                r.start
            } else {
                r.start - r.latency
            };
            draw_clip(&lp, lane, view, at, r.len, ov, REC, label);
            if let Some((from, notes)) = &r.notes {
                let rect = clip_box(view, lane, at, at + r.len as i64);
                draw_notes(&lp, rect, view, at, *from, notes, REC);
            }
        }
        if let Some((a, b, lo, hi)) = self.range_sel
            && (lo..=hi).contains(&i)
        {
            lp.rect_filled(
                Rect::from_min_max(
                    Pos2::new(view.x(a), lane.top()),
                    Pos2::new(view.x(b), lane.bottom()),
                ),
                0.0,
                theme::INK.gamma_multiply(0.12),
            );
        }
        draw_cursor(&lp, lane, view, self.session.transport.cursor);
        if let Some(h) = playhead {
            let x = view.x(h);
            if x >= lane.left() {
                lp.line_segment(
                    [Pos2::new(x, lane.top()), Pos2::new(x, lane.bottom())],
                    Stroke::new(1.5, theme::INK),
                );
            }
        }
        if lane_resp.hovered()
            && let Some(p) = ui.ctx().pointer_hover_pos()
            && let Some((c, kind)) = grab_at(p, track)
        {
            ui.ctx().set_cursor_icon(match (self.tool, kind) {
                (Tool::Blade, _) => egui::CursorIcon::Crosshair,
                (Tool::Erase, _) => egui::CursorIcon::NotAllowed,
                (Tool::Envelope, _) => egui::CursorIcon::PointingHand,
                (Tool::Slip, _) => egui::CursorIcon::AllScroll,
                (_, DragKind::Move) if ctrl => egui::CursorIcon::AllScroll,
                (_, DragKind::Move) if shift => egui::CursorIcon::Copy,
                (_, DragKind::Move) => egui::CursorIcon::Grab,
                (_, DragKind::Gain) => egui::CursorIcon::ResizeVertical,
                _ => egui::CursorIcon::ResizeHorizontal,
            });
            // The Blade shows where it would cut.
            if self.tool == Tool::Blade
                && let Some(&(_, r)) = rects.get(c)
            {
                let snap = self.session.transport.snap.inverted(alt);
                let mut at = grid.snap(view.position(p.x), snap);
                if self.zero_cross {
                    at = track.zero_crossing(c, at, rate);
                }
                let x = view.x(at);
                if x > r.left() && x < r.right() {
                    lp.line_segment(
                        [Pos2::new(x, r.top()), Pos2::new(x, r.bottom())],
                        Stroke::new(1.5, theme::WARN),
                    );
                }
            }
        }
        if lane_resp.double_clicked()
            && let Some(p) = lane_resp.interact_pointer_pos()
            && let Some((c, _)) = grab_at(p, track)
            && let Some(k) = track.take_index(&track.clips[c].take)
            && track.takes[k].events.is_some()
        {
            self.open_roll(i, k);
        }
        // The strip's controls.
        let inner = strip.shrink2(egui::vec2(12.0, 8.0));
        let mut child = ui.new_child(
            egui::UiBuilder::new()
                .id_salt(("strip_controls", i))
                .max_rect(inner),
        );
        let mut arm_clicked = false;
        // Its MIDI take at production: rendering, there, or to start.
        let prod = self.session.tracks[i].active.and_then(|k| {
            let take = self.session.tracks[i].takes.get(k)?;
            let e = take.events.as_ref()?;
            let job = self.take_jobs.iter().find(|j| {
                j.wanted && j.id == take.id && j.rev == e.rev && j.quality == Quality::Production
            });
            Some(match job {
                Some(j) => (
                    format!("◔ {:.0}%", j.job.progress() * 100.0),
                    theme::ACCENT,
                    "Rendering this track's take at production in the background",
                    false,
                ),
                None if take.has_render(Quality::Production) => (
                    "PROD ✓".to_string(),
                    theme::OK,
                    "Rendered at production: the track plays it (unless it plays drafts). Bounce it to an audio take from the take's menu",
                    false,
                ),
                None => (
                    "⤓ PROD".to_string(),
                    theme::MUTED,
                    "Render this track's take at production in the background (the full-quality circuit; tube_synth runs ~25x slower than real time)",
                    true,
                ),
            })
        });
        let mut prod_clicked = false;
        let t = &mut self.session.tracks[i];
        child.horizontal(|ui| {
            changed |= ui
                .add(
                    egui::TextEdit::singleline(&mut t.name)
                        .id_salt(("track_name", i))
                        .desired_width(if prod.is_some() { 64.0 } else { 118.0 }),
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
            if let Some((text, colour, tip, can)) = &prod {
                let b = egui::Button::new(RichText::new(text).small().color(*colour))
                    .fill(theme::CHROME2)
                    .min_size(egui::vec2(50.0, 20.0));
                if ui
                    .add_enabled(*can, b)
                    .on_hover_text(*tip)
                    .on_disabled_hover_text(*tip)
                    .clicked()
                {
                    prod_clicked = true;
                }
            }
        });
        if prod_clicked && let Some(k) = self.session.tracks[i].active {
            self.render_production(i, k);
        }
        if arm_clicked && self.recording.is_none() {
            self.session.armed = Some(i);
            changed = true;
        }
        let meter = self.meters.tracks.get(i).cloned().unwrap_or_default();
        let t = &mut self.session.tracks[i];
        child.horizontal(|ui| {
            // The fader as a slider with the track's meter behind it (SE4).
            let (r, _) = ui.allocate_exact_size(egui::vec2(70.0, 18.0), Sense::hover());
            crate::mixer::draw_meter_h(&ui.painter_at(r), r.shrink(1.0), &meter);
            let mut fui = ui.new_child(egui::UiBuilder::new().max_rect(r));
            changed |= crate::mixer::fader(
                &mut fui,
                &mut t.volume_db,
                r.size(),
                false,
                egui::Id::new(("strip_fader", i)),
            );
            changed |= ui
                .add(
                    egui::DragValue::new(&mut t.volume_db)
                        .range(crate::mixer::FADER_MIN_DB..=crate::mixer::FADER_MAX_DB)
                        .speed(0.2)
                        .max_decimals(1),
                )
                .on_hover_text("Fader (dB)")
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
                    .on_hover_text("The earlier take, whole, in place of the lane's clips")
                    .clicked()
                {
                    t.set_active(a - 1);
                    changed = true;
                }
                ui.label(
                    RichText::new(format!("{}/{n}", a + 1))
                        .small()
                        .color(theme::MUTED),
                );
                if ui
                    .add_enabled(a + 1 < n, egui::Button::new("›").small())
                    .on_hover_text("The later take, whole, in place of the lane's clips")
                    .clicked()
                {
                    t.set_active(a + 1);
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
        // What a take from the keyboard records, and what it's heard through while armed.
        let proxy_available = self.proxy_available;
        let t = &mut self.session.tracks[i];
        child.horizontal(|ui| {
            ui.spacing_mut().item_spacing.x = 2.0;
            let seg = |ui: &mut egui::Ui, on: bool, text: &str, tip: &str| {
                ui.selectable_label(on, RichText::new(text).small())
                    .on_hover_text(tip)
                    .clicked()
            };
            ui.label(RichText::new("rec").small().color(theme::FAINT));
            if seg(ui, t.midi, "MIDI", "A take from the keyboard records its notes (edit them in the piano roll; it renders on the device at draft and, on demand, production). The audio heard is kept as its first draft.") && !t.midi {
                t.midi = true;
                changed = true;
            }
            if seg(ui, !t.midi, "AUDIO", "A take records only the audio (the device's output as heard), no notes") && t.midi {
                t.midi = false;
                changed = true;
            }
            ui.add_space(8.0);
            ui.label(RichText::new("hear").small().color(theme::FAINT));
            ui.add_enabled_ui(t.midi && proxy_available, |ui| {
                if seg(ui, t.monitor == Monitor::Device, "DEVICE", "While armed, play the device itself, live (its full cost)") {
                    t.monitor = Monitor::Device;
                    changed = true;
                }
                if seg(ui, t.monitor == Monitor::Proxy, "PROXY", "While armed, play the device's proxy: a cheap digital stand-in (tube_synth's follows the panel through tables measured on it; the Clavinet's is a simple plucked string). The take renders on the device behind the recording") {
                    t.monitor = Monitor::Proxy;
                    changed = true;
                }
            })
            .response
            .on_disabled_hover_text(if t.midi {
                "The device chosen in Play has no proxy (tube_synth and the Clavinet have one)"
            } else {
                "A proxy only stands in for MIDI takes: an audio take records what the device plays"
            });
        });
        if let Some(k) = self.session.tracks[i].active_take() {
            child.label(
                RichText::new(take_line(k, self.session.rate))
                    .small()
                    .color(theme::FAINT),
            );
        }
        changed |= self.inserts_row(&mut child, i);
        // Every take, stacked under the track: the ones in the lane marked; a click puts a
        // take in the lane whole, a drag across one promotes that stretch into the lane on
        // top (comping, SE5).
        if shown > 0 {
            for j in 0..self.session.tracks[i].takes.len() {
                let y = row.bottom() + j as f32 * TAKE_H;
                let srow = Rect::from_min_size(Pos2::new(row.left(), y), egui::vec2(width, TAKE_H));
                let sstrip = Rect::from_min_size(srow.min, egui::vec2(STRIP_W, TAKE_H));
                let slane = Rect::from_min_max(Pos2::new(srow.left() + STRIP_W, y), srow.max);
                let resp = ui
                    .interact(
                        srow,
                        ui.id().with(("take_lane", i, j)),
                        Sense::click_and_drag(),
                    )
                    .on_hover_text(
                        "Click: this take in the lane, whole (replacing its clips); drag across \
                         it: that stretch into the lane on top (comping)",
                    );
                let alt = ui.input(|x| x.modifiers.alt);
                let snap = self.session.transport.snap.inverted(alt);
                if resp.drag_started()
                    && let Some(p) = ui.input(|x| x.pointer.press_origin())
                {
                    self.comp = Some((i, j, grid.snap(view.position(p.x), snap)));
                }
                let mut comp_band = None;
                if let Some((ti, tj, a)) = self.comp
                    && ti == i
                    && tj == j
                    && let Some(p) = ui.ctx().pointer_interact_pos()
                {
                    let b = grid.snap(view.position(p.x), snap);
                    comp_band = Some((a.min(b), a.max(b)));
                    if resp.drag_stopped() {
                        self.comp = None;
                        changed |= self.comp_in(i, j, a.min(b), a.max(b));
                    }
                }
                let t = &self.session.tracks[i];
                let k = &t.takes[j];
                let active = t.lane_takes().contains(&j);
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
                        k.len() as f64 / self.session.rate as f64
                    ),
                    egui::FontId::proportional(11.0),
                    if active { theme::ACCENT } else { theme::MUTED },
                );
                let lp = ui.painter_at(slane);
                draw_grid(&lp, slane, view, grid);
                let (sound, ov, _) = k.sound(t.drafts);
                draw_clip(
                    &lp,
                    slane,
                    view,
                    k.position,
                    sound.len(),
                    ov,
                    if active { colour } else { theme::FAINT },
                    "",
                );
                if let Some((a, b)) = comp_band {
                    lp.rect_filled(
                        Rect::from_min_max(
                            Pos2::new(view.x(a), slane.top()),
                            Pos2::new(view.x(b), slane.bottom()),
                        ),
                        0.0,
                        theme::ACCENT.gamma_multiply(0.25),
                    );
                }
                if resp.clicked() {
                    self.session.tracks[i].set_active(j);
                    self.selected = None;
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
        match take_action {
            Some((k, 0)) => self.open_roll(i, k),
            Some((k, 1)) => self.render_production(i, k),
            Some((k, 4)) => self.request_render(i, k, false),
            Some((k, 3)) => self.bounce(i, k),
            Some((_, 2)) => {
                let t = &mut self.session.tracks[i];
                t.drafts = !t.drafts;
                changed = true;
            }
            _ => {}
        }
        if let Some((k, heard)) = place_take {
            changed |= self.session.tracks[i].place_take(k, heard);
        }
        if let Some(k) = delete_take {
            self.delete_take(i, k);
        }
        if delete_track {
            self.delete_track(i);
        }
        changed
    }

    /// What is selected as a span: the range, else the selected clip (from, to, first and
    /// last track).
    fn selection_span(&self) -> Option<(i64, i64, usize, usize)> {
        if let Some(r) = self.range_sel {
            return Some(r);
        }
        let (t, c) = self.selected?;
        let clip = self.session.tracks.get(t)?.clips.get(c)?;
        Some((clip.position, clip.end(), t, t))
    }

    /// The selection copied (a range: every clip in it, cut at its edges; a clip: itself);
    /// `cut` also takes it out of the lanes.
    fn copy_selection(&mut self, cut: bool) {
        let items = if let Some((a, b, lo, hi)) = self.range_sel {
            self.session.copy_range(a, b, lo..=hi)
        } else if let Some((t, c)) = self.selected
            && let Some(track) = self.session.tracks.get(t)
            && let Some(clip) = track.clips.get(c)
            && let Some(take) = track.take_of(clip)
        {
            let mut clip = clip.clone();
            clip.position = 0;
            vec![varimu_app::session::Copied {
                track: 0,
                clip,
                take: take.clone(),
            }]
        } else {
            return;
        };
        if items.is_empty() {
            return;
        }
        self.clipboard = items;
        if cut {
            self.delete_selection();
        }
    }

    /// The selected range (on its tracks) or clip deleted; with Ripple, what follows on
    /// those tracks moves up to close the gap (SE8).
    fn delete_selection(&mut self) {
        if let Some((a, b, lo, hi)) = self.range_sel {
            let rate = self.session.rate;
            for t in lo..=hi.min(self.session.tracks.len().saturating_sub(1)) {
                self.session.tracks[t].delete_range_ripple(a, b, rate, self.ripple);
            }
            if self.ripple {
                self.range_sel = None;
            }
            self.save();
        } else if let Some((t, c)) = self.selected {
            self.clip_action(t, c, "delete");
            self.save();
        }
    }

    /// The clipboard laid at the cursor on the armed track (a range keeps its tracks'
    /// offsets), the pasted clips selected.
    fn paste_clipboard(&mut self) {
        if self.clipboard.is_empty() {
            return;
        }
        let t = self
            .selected
            .map(|s| s.0)
            .or(self.session.armed)
            .unwrap_or(0);
        let at = self.session.transport.cursor;
        let items = self.clipboard.clone();
        let new = self.session.paste(&items, at, t);
        self.after_paste(&items, at, t, new);
    }

    /// The selection duplicated right after itself (a range: its length later; a clip: from
    /// its end), the copy selected so a second press repeats it again.
    fn duplicate_selection(&mut self) {
        let Some((a, b, lo, hi)) = self.selection_span() else {
            return;
        };
        let items = match self.range_sel {
            Some(_) => self.session.copy_range(a, b, lo..=hi),
            None => {
                let Some((t, c)) = self.selected else { return };
                let track = &self.session.tracks[t];
                let clip = track.clips[c].clone();
                let Some(take) = track.take_of(&clip).cloned() else {
                    return;
                };
                vec![varimu_app::session::Copied {
                    track: 0,
                    clip: varimu_app::session::Clip {
                        position: 0,
                        ..clip
                    },
                    take,
                }]
            }
        };
        let new = self.session.paste(&items, b, lo);
        self.after_paste(&items, b, lo, new);
        if self.range_sel.is_some() {
            self.range_sel = Some((b, b + (b - a), lo, hi));
        }
    }

    fn after_paste(
        &mut self,
        items: &[varimu_app::session::Copied],
        at: i64,
        t: usize,
        new: Vec<(usize, usize)>,
    ) {
        if new.is_empty() {
            return;
        }
        if items.len() == 1 && self.range_sel.is_none() {
            self.selected = new.first().copied();
        } else if self.range_sel.is_none() {
            let len = items
                .iter()
                .map(|i| i.clip.position + i.clip.len as i64)
                .max()
                .unwrap_or(0);
            let hi = t + items.iter().map(|i| i.track).max().unwrap_or(0);
            self.range_sel = Some((at, at + len, t, hi));
            self.selected = None;
        }
        self.saved = true;
        self.save();
    }

    /// Clip `c` of track `t` moved to the top of track `to`'s lane (its take copied into
    /// that track's pool if it isn't there). Whether it moved.
    fn move_clip(&mut self, t: usize, c: usize, to: usize) -> bool {
        if t == to || self.recording.is_some() {
            return false;
        }
        let Some(clip) = self
            .session
            .tracks
            .get(t)
            .and_then(|x| x.clips.get(c))
            .cloned()
        else {
            return false;
        };
        let Some(take) = self.session.tracks[t].take_of(&clip).cloned() else {
            return false;
        };
        let Some(dest) = self.session.tracks.get_mut(to) else {
            return false;
        };
        if dest.take_index(&take.id).is_none() {
            dest.takes.push(take);
        }
        dest.clips.push(clip);
        let n = dest.clips.len() - 1;
        self.session.tracks[t].clips.remove(c);
        self.selected = Some((to, n));
        true
    }

    /// What a clip's menu (or a key) asks: split it at the cursor, mute it, reset its gain
    /// and fades, delete it. Whether the session changed.
    fn clip_action(&mut self, t: usize, c: usize, what: &str) -> bool {
        let rate = self.session.rate;
        let cursor = self.session.transport.cursor;
        let Some(track) = self.session.tracks.get_mut(t) else {
            return false;
        };
        if c >= track.clips.len() {
            return false;
        }
        match what {
            "split" => {
                let at = if self.zero_cross {
                    track.zero_crossing(c, cursor, rate)
                } else {
                    cursor
                };
                let r = track.split_clip(c, at, rate);
                if let Some(r) = r {
                    self.selected = Some((t, r));
                }
                r.is_some()
            }
            "mute" => {
                track.clips[c].muted = !track.clips[c].muted;
                true
            }
            "reset" => {
                let take_len = track.take_of(&track.clips[c]).map_or(0, Take::len);
                let fade = default_fade(rate);
                let clip = &mut track.clips[c];
                clip.gain_db = 0.0;
                clip.curve = varimu_app::session::FadeCurve::Linear;
                clip.fade_in = if clip.src_start > 0 { fade } else { 0 };
                clip.fade_out = if clip.src_start + clip.len < take_len {
                    fade
                } else {
                    0
                };
                true
            }
            "delete" => {
                track.delete_clip(c, self.ripple);
                self.selected = None;
                true
            }
            _ => false,
        }
    }

    /// Take `j` of track `t` from `a` to `b` (timeline) promoted into the lane on top, the
    /// cuts with the default fade (comping). Whether it was.
    fn comp_in(&mut self, t: usize, j: usize, a: i64, b: i64) -> bool {
        let rate = self.session.rate;
        let Some(track) = self.session.tracks.get_mut(t) else {
            return false;
        };
        let Some(take) = track.takes.get(j) else {
            return false;
        };
        let (a, b) = (a.max(take.position), b.min(take.end()));
        if b - a < 2 {
            return false;
        }
        let src = (a - take.position) as usize;
        let len = (b - a) as usize;
        let fade = default_fade(rate);
        let clip = Clip {
            fade_in: if src > 0 { fade } else { 0 },
            fade_out: if src + len < take.len() { fade } else { 0 },
            ..Clip::of(&take.id, src, len, a)
        };
        track.clips.push(clip);
        self.selected = Some((t, track.clips.len() - 1));
        true
    }

    /// The clip S splits: the selected one, else the armed track's under the cursor.
    fn split_target(&self) -> Option<(usize, usize)> {
        let cursor = self.session.transport.cursor;
        self.selected.or_else(|| {
            let t = self.session.armed?;
            let c = self
                .session
                .tracks
                .get(t)?
                .clips
                .iter()
                .rposition(|c| !c.muted && c.position < cursor && c.end() > cursor)?;
            Some((t, c))
        })
    }

    /// The selected clip, or the clips wholly inside the selected range, moved by a step
    /// (SE8): `dir` steps of the snap (10 ms with it off), or with `sample` one sample.
    fn nudge(&mut self, dir: i64, sample: bool) {
        let rate = self.session.rate;
        let grid = Grid::new(rate, &self.session.transport);
        let step = if sample {
            1
        } else {
            grid.snap_step(self.session.transport.snap)
                .unwrap_or(0.01 * rate as f64)
                .round() as i64
        };
        let d = dir * step.max(1);
        if let Some((a, b, lo, hi)) = self.range_sel {
            let mut moved = false;
            for t in lo..=hi.min(self.session.tracks.len().saturating_sub(1)) {
                for c in self.session.tracks[t]
                    .clips
                    .iter_mut()
                    .filter(|c| c.position >= a && c.end() <= b)
                {
                    c.position += d;
                    moved = true;
                }
            }
            if moved {
                self.range_sel = Some((a + d, b + d, lo, hi));
                self.save();
            }
        } else if let Some((t, c)) = self.selected
            && let Some(clip) = self
                .session
                .tracks
                .get_mut(t)
                .and_then(|x| x.clips.get_mut(c))
        {
            clip.position += d;
            self.save();
        }
    }

    /// The range a bounce covers: the selected range, else the loop while it's on, else
    /// None (everything).
    fn bounce_range(&self) -> Option<(i64, i64)> {
        if let Some((a, b, _, _)) = self.range_sel {
            return Some((a, b));
        }
        let t = &self.session.transport;
        let grid = Grid::new(self.session.rate, t);
        t.loop_on
            .then(|| (grid.beat(t.left_beat), grid.beat(t.right_beat)))
    }

    /// What plays (the soloed tracks, else the unmuted ones) bounced to a new track (SE8),
    /// stereo or `mono` ((L + R) / 2).
    fn bounce_audible(&mut self, mono: bool) {
        if self.recording.is_some() {
            return;
        }
        let range = self.bounce_range();
        self.saved = true;
        match self.session.bounce_audible(range, self.bounce_mute, mono) {
            Ok(nt) => {
                self.selected = Some((nt, 0));
                self.range_sel = None;
                self.edit_note = Some(format!("bounced to \"{}\"", self.session.tracks[nt].name));
                self.save();
            }
            Err(e) => self.error = Some(format!("Bounce: {e}")),
        }
    }

    /// The selected range glued into a take per track it covers, else clip `fallback`'s
    /// span (SE8, Consolidate). Whether anything changed.
    fn consolidate_selection(&mut self, fallback: Option<(usize, usize)>) -> bool {
        let spans: Vec<(usize, i64, i64)> = match (self.range_sel, fallback) {
            (Some((a, b, lo, hi)), _) => (lo..=hi.min(self.session.tracks.len().saturating_sub(1)))
                .map(|t| (t, a, b))
                .collect(),
            (None, Some((t, c))) => match self.session.tracks.get(t).and_then(|x| x.clips.get(c)) {
                Some(clip) => vec![(t, clip.position, clip.end())],
                None => Vec::new(),
            },
            (None, None) => Vec::new(),
        };
        self.saved = true;
        let mut done = Vec::new();
        for (t, a, b) in spans {
            match self.session.consolidate(t, a, b) {
                Ok(k) => done.push((t, k)),
                // A track with nothing in the range is left alone.
                Err(e) if e.starts_with("nothing sounds") => {}
                Err(e) => self.error = Some(format!("Consolidate: {e}")),
            }
        }
        if done.len() == 1 && self.range_sel.is_none() {
            self.selected = done.first().copied();
        }
        self.edit_note = Some(format!(
            "consolidated {} track{}",
            done.len(),
            if done.len() == 1 { "" } else { "s" }
        ));
        !done.is_empty()
    }

    /// A clip operation (SE8) on clip `c` of track `t`. Whether the session changed.
    fn apply_clip_op(&mut self, t: usize, c: usize, op: ClipOp) -> bool {
        use varimu_app::session::Process;
        let rate = self.session.rate;
        if self.recording.is_some()
            || self
                .session
                .tracks
                .get(t)
                .is_none_or(|x| c >= x.clips.len())
        {
            return false;
        }
        self.edit_note = None;
        match op {
            ClipOp::Invert => {
                let clip = &mut self.session.tracks[t].clips[c];
                clip.invert = !clip.invert;
                true
            }
            ClipOp::Curve(k) => {
                self.session.tracks[t].clips[c].curve = k;
                true
            }
            ClipOp::ClearEnvelope => {
                let env = &mut self.session.tracks[t].clips[c].env;
                let had = !env.is_empty();
                env.clear();
                had
            }
            ClipOp::Crossfade(s, k) => {
                let len = (s * rate as f64).round() as usize;
                match self.session.tracks[t].crossfade(c, len, k, rate) {
                    Ok((a, b)) => {
                        let n = self.session.tracks[t].clips[b].fade_in;
                        self.selected = Some((t, a));
                        self.edit_note = Some(format!(
                            "crossfaded over {:.1} ms",
                            n as f64 / rate as f64 * 1e3
                        ));
                        true
                    }
                    Err(e) => {
                        self.error = Some(format!("Crossfade: {e}"));
                        false
                    }
                }
            }
            ClipOp::Reverse | ClipOp::Varispeed(_) => {
                let how = match op {
                    ClipOp::Varispeed(st) => Process::Varispeed(st),
                    _ => Process::Reverse,
                };
                if how == Process::Varispeed(0.0) {
                    return false;
                }
                self.saved = true;
                match self.session.process_clip(t, c, how) {
                    Ok(k) => {
                        self.selected = Some((t, k));
                        true
                    }
                    Err(e) => {
                        self.error = Some(e);
                        false
                    }
                }
            }
            ClipOp::Transients => {
                let s = self.session.tracks[t].split_at_transients(c, rate, self.transient_db);
                if s.len() <= 1 {
                    self.edit_note = Some("no hits found: lower the sensitivity's dB".into());
                    return false;
                }
                let clips = &self.session.tracks[t].clips;
                let (a, b) = (clips[s[0]].position, clips[s[s.len() - 1]].end());
                self.range_sel = Some((a, b, t, t));
                self.selected = None;
                self.edit_note = Some(format!(
                    "{} slices, selected: Quantize puts their hits on the snap",
                    s.len()
                ));
                true
            }
            ClipOp::StripSilence => {
                let s =
                    self.session.tracks[t].strip_silence(c, rate, self.silence_dbfs, 0.25, 0.02);
                if s.is_empty() {
                    self.edit_note = Some("all of it is below the threshold: nothing kept".into());
                    return false;
                }
                self.selected = None;
                self.edit_note = Some(format!("{} clips kept", s.len()));
                true
            }
            ClipOp::Quantize => {
                let snap = self.session.transport.snap;
                if snap == Snap::Off {
                    self.error = Some("Quantize: pick a snap (the transport's second row)".into());
                    return false;
                }
                let grid = Grid::new(rate, &self.session.transport);
                let mut n = 0;
                if let Some((a, b, lo, hi)) = self.range_sel {
                    for tt in lo..=hi.min(self.session.tracks.len().saturating_sub(1)) {
                        let cs: Vec<usize> = self.session.tracks[tt]
                            .clips
                            .iter()
                            .enumerate()
                            .filter(|(_, x)| {
                                x.position >= a - (0.05 * rate as f64) as i64 && x.position < b
                            })
                            .map(|(k, _)| k)
                            .collect();
                        n += self.session.tracks[tt].quantize_clips(&cs, &grid, snap, rate);
                    }
                } else {
                    n = self.session.tracks[t].quantize_clips(&[c], &grid, snap, rate);
                }
                self.edit_note = Some(format!("{n} clips moved onto the {}", snap.label()));
                n > 0
            }
            ClipOp::Consolidate => self.consolidate_selection(Some((t, c))),
        }
    }

    /// The clip operations' menu items (SE8), in a clip's context menu and the toolbar's
    /// Clip menu. What was picked.
    fn clip_ops_ui(&mut self, ui: &mut egui::Ui, t: usize, c: usize) -> Option<ClipOp> {
        use varimu_app::edit::{SPLICES, splice_s, varispeed_ratio};
        use varimu_app::session::FadeCurve;
        let clip = self.session.tracks.get(t)?.clips.get(c)?.clone();
        let mut op = None;
        if ui
            .button(if clip.invert {
                "Polarity back to normal"
            } else {
                "Invert polarity"
            })
            .on_hover_text("The clip's audio upside down (Ø): a mic's phase, a snare's bottom mic")
            .clicked()
        {
            op = Some(ClipOp::Invert);
        }
        ui.horizontal(|ui| {
            ui.label(RichText::new("fades").small().color(theme::FAINT));
            for (k, name, tip) in [
                (
                    FadeCurve::Linear,
                    "linear",
                    "A straight line in amplitude: a tape splice; correlated audio crossfades to unity",
                ),
                (
                    FadeCurve::EqualPower,
                    "equal power",
                    "Sine / cosine: unrelated sounds crossfade at a constant loudness",
                ),
            ] {
                if ui
                    .selectable_label(clip.curve == k, RichText::new(name).small())
                    .on_hover_text(tip)
                    .clicked()
                {
                    op = Some(ClipOp::Curve(k));
                }
            }
        });
        ui.menu_button("Crossfade into the next clip", |ui| {
            ui.label(
                RichText::new(
                    "The clip that starts at this one's end (within 50 ms): both stretched over \
                     the join, this one fading out under it",
                )
                .small()
                .color(theme::MUTED),
            );
            for (label, angle, ips) in SPLICES {
                let s = splice_s(angle, ips);
                if ui
                    .button(format!("Splice {label} ({:.1} ms)", s * 1e3))
                    .on_hover_text(
                        "As a razor-blade splice on 1/4-inch tape crosses the reproduce head: a \
                         linear crossfade as long as the cut takes to pass it",
                    )
                    .clicked()
                {
                    op = Some(ClipOp::Crossfade(s, FadeCurve::Linear));
                }
            }
            ui.separator();
            ui.horizontal(|ui| {
                ui.add(
                    egui::DragValue::new(&mut self.xfade_ms)
                        .range(1.0..=2000.0)
                        .speed(0.5)
                        .max_decimals(1)
                        .suffix(" ms"),
                );
                if ui.button("linear").clicked() {
                    op = Some(ClipOp::Crossfade(self.xfade_ms * 1e-3, FadeCurve::Linear));
                }
                if ui.button("equal power").clicked() {
                    op = Some(ClipOp::Crossfade(
                        self.xfade_ms * 1e-3,
                        FadeCurve::EqualPower,
                    ));
                }
            });
        });
        ui.separator();
        if ui
            .button("Reverse")
            .on_hover_text(
                "The clip's audio backwards, as a new take (the old one stays in the pool)",
            )
            .clicked()
        {
            op = Some(ClipOp::Reverse);
        }
        ui.horizontal(|ui| {
            if ui
                .add_enabled(self.varispeed_st != 0.0, egui::Button::new("Varispeed"))
                .on_hover_text(
                    "Played faster or slower, pitch and time together, as a tape machine's \
                     capstan does it (no time-stretching): a new take",
                )
                .clicked()
            {
                op = Some(ClipOp::Varispeed(self.varispeed_st));
            }
            ui.add(
                egui::DragValue::new(&mut self.varispeed_st)
                    .range(-24.0..=24.0)
                    .speed(0.05)
                    .max_decimals(2)
                    .suffix(" st"),
            );
            let r = varispeed_ratio(self.varispeed_st);
            ui.label(
                RichText::new(format!("{:.1}% speed", r * 100.0))
                    .small()
                    .color(theme::MUTED),
            );
        });
        ui.separator();
        ui.horizontal(|ui| {
            if ui
                .button("Split at transients")
                .on_hover_text(
                    "A cut 3 ms before each hit (a rise of this many dB in the attack's \
                     brightness over the 30 ms before it); the slices end up selected",
                )
                .clicked()
            {
                op = Some(ClipOp::Transients);
            }
            ui.add(
                egui::DragValue::new(&mut self.transient_db)
                    .range(3.0..=40.0)
                    .speed(0.2)
                    .max_decimals(1)
                    .suffix(" dB"),
            );
        });
        let snap = self.session.transport.snap;
        if ui
            .add_enabled(
                snap != Snap::Off,
                egui::Button::new(format!("Quantize to the {}", snap.label())),
            )
            .on_hover_text(
                "Each clip's hit (its attack, in its first 50 ms) moved onto the nearest line of \
                 the snap: the selected range's clips, else this one",
            )
            .on_disabled_hover_text("Pick a snap in the transport's second row")
            .clicked()
        {
            op = Some(ClipOp::Quantize);
        }
        ui.horizontal(|ui| {
            if ui
                .button("Strip silence below")
                .on_hover_text(
                    "A clip per stretch that sounds above the level (silences under 250 ms \
                     kept, 20 ms of room around each)",
                )
                .clicked()
            {
                op = Some(ClipOp::StripSilence);
            }
            ui.add(
                egui::DragValue::new(&mut self.silence_dbfs)
                    .range(-90.0..=-6.0)
                    .speed(0.2)
                    .max_decimals(1)
                    .suffix(" dBFS"),
            );
        });
        ui.separator();
        if ui
            .button("Consolidate")
            .on_hover_text(
                "The selected range (each track in it), else this clip, glued into one new take \
                 as it plays: gains, fades, envelopes and polarity baked in (before inserts)",
            )
            .clicked()
        {
            op = Some(ClipOp::Consolidate);
        }
        if ui
            .add_enabled(!clip.env.is_empty(), egui::Button::new("Clear envelope"))
            .clicked()
        {
            op = Some(ClipOp::ClearEnvelope);
        }
        if op.is_some() {
            ui.close();
        }
        op
    }

    /// The arrangement's toolbar (SE8): the tools, the clipboard, split, the editing
    /// switches, the Clip menu and Bounce (Undo and Redo are in the bottom bar).
    fn toolbar(&mut self, ui: &mut egui::Ui) {
        let mut op: Option<(usize, usize, ClipOp)> = None;
        let mut action: Option<&'static str> = None;
        ui.horizontal(|ui| {
            ui.add_space(10.0);
            ui.spacing_mut().item_spacing.x = 3.0;
            for tool in Tool::ALL {
                if ui
                    .selectable_label(self.tool == tool, RichText::new(tool.label()).small())
                    .on_hover_text(tool.tip())
                    .clicked()
                {
                    self.tool = tool;
                }
            }
            ui.separator();
            let idle = self.recording.is_none();
            let small = |s: &str| egui::Button::new(RichText::new(s).small());
            let sel = idle && self.selection_span().is_some();
            for (label, tip, on, what) in [
                ("Cut", "The selected clip or range (Ctrl+X)", sel, "cut"),
                ("Copy", "Ctrl+C", sel, "copy"),
                (
                    "Paste",
                    "At the cursor, on the selected (else the armed) track (Ctrl+V)",
                    idle && !self.clipboard.is_empty(),
                    "paste",
                ),
                ("Duplicate", "Right after itself (Ctrl+D)", sel, "dup"),
                (
                    "Delete",
                    "The selected clip or range (Delete; with Ripple, what follows moves up)",
                    sel,
                    "delete",
                ),
                (
                    "Split",
                    "The selected clip (else the armed track's under the cursor) at the cursor (S)",
                    idle && self.split_target().is_some(),
                    "split",
                ),
            ] {
                if ui
                    .add_enabled(on, small(label))
                    .on_hover_text(tip)
                    .clicked()
                {
                    action = Some(what);
                }
            }
            ui.separator();
            let before = (self.zero_cross, self.ripple);
            if ui
                .selectable_label(self.zero_cross, RichText::new("Zero crossings").small())
                .on_hover_text(
                    "Splits (S, the Blade) move to the nearest zero crossing within 5 ms of where \
                     they were asked",
                )
                .clicked()
            {
                self.zero_cross = !self.zero_cross;
            }
            if ui
                .selectable_label(self.ripple, RichText::new("Ripple").small())
                .on_hover_text(
                    "Deleting a clip or a range (Delete, Cut, the Erase tool) moves what follows \
                     on that track earlier to close the gap",
                )
                .clicked()
            {
                self.ripple = !self.ripple;
            }
            if (self.zero_cross, self.ripple) != before {
                self.save_prefs();
            }
            ui.separator();
            ui.add_enabled_ui(idle && self.selected.is_some(), |ui| {
                ui.menu_button(RichText::new("Clip ▾").small(), |ui| {
                    if let Some((t, c)) = self.selected
                        && let Some(o) = self.clip_ops_ui(ui, t, c)
                    {
                        op = Some((t, c, o));
                    }
                })
                .response
                .on_disabled_hover_text("Select a clip");
            });
            if ui
                .selectable_label(self.deck_open, RichText::new("Tape deck").small())
                .on_hover_text(
                    "The session's multitrack tape (an Ampex 300-4, four tracks on 1/2 in): \
                     tracks assigned to its tape tracks, recorded together in one print, each \
                     then playing its tape track",
                )
                .clicked()
            {
                self.deck_open = !self.deck_open;
            }
            ui.add_enabled_ui(idle, |ui| {
                ui.menu_button(RichText::new("⤓ Bounce ▾").small(), |ui| {
                    let any_solo = self.session.tracks.iter().any(|t| t.solo);
                    let what = if any_solo {
                        "the soloed tracks"
                    } else {
                        "the mix"
                    };
                    let rate = self.session.rate as f64;
                    let span = match self.bounce_range() {
                        Some((a, b)) => format!(
                            "{:.2} s from {}",
                            (b - a) as f64 / rate,
                            Grid::new(self.session.rate, &self.session.transport).label(a)
                        ),
                        None => "from start to end".into(),
                    };
                    ui.label(
                        RichText::new(format!(
                            "{what}, {span} (the selected range, else the loop)"
                        ))
                        .small()
                        .color(theme::MUTED),
                    );
                    if ui
                        .button(format!("Bounce {what} to a new stereo track"))
                        .on_hover_text(
                            "What you hear (each track's inserts as printed, its fader and pan; \
                             not the master's chain or fader) as a stereo take on a new track",
                        )
                        .clicked()
                    {
                        action = Some("bounce");
                        ui.close();
                    }
                    if ui
                        .button(format!("Bounce {what} to a new mono track"))
                        .on_hover_text(
                            "The same, summed to mono as (L + R) / 2: a track panned to the \
                             centre comes back as it was, one panned hard to a side at -6 dB",
                        )
                        .clicked()
                    {
                        action = Some("bounce_mono");
                        ui.close();
                    }
                    ui.checkbox(&mut self.bounce_mute, "then mute the tracks bounced");
                    ui.separator();
                    if ui
                        .add_enabled(
                            self.selection_span().is_some(),
                            egui::Button::new("Consolidate the selection"),
                        )
                        .on_hover_text(
                            "Each track in the selected range (else the selected clip) glued into \
                             one new take as it plays, before its inserts",
                        )
                        .clicked()
                    {
                        action = Some("consolidate");
                        ui.close();
                    }
                });
            });
            ui.separator();
            if ui.add(small("?")).on_hover_text("The keys (?)").clicked() {
                self.show_keys = !self.show_keys;
            }
            if let Some(n) = &self.edit_note {
                ui.label(RichText::new(n).small().color(theme::MUTED));
            }
        });
        match action {
            Some("cut") => self.copy_selection(true),
            Some("copy") => self.copy_selection(false),
            Some("paste") => self.paste_clipboard(),
            Some("dup") => self.duplicate_selection(),
            Some("delete") => self.delete_selection(),
            Some("split") => {
                if let Some((t, c)) = self.split_target()
                    && self.clip_action(t, c, "split")
                {
                    self.save();
                }
            }
            Some("bounce") => self.bounce_audible(false),
            Some("bounce_mono") => self.bounce_audible(true),
            Some("consolidate") => {
                if self.consolidate_selection(self.selected) {
                    self.save();
                }
            }
            _ => {}
        }
        if let Some((t, c, o)) = op
            && self.apply_clip_op(t, c, o)
        {
            self.save();
        }
    }

    /// What event take `k` of track `t` plays and what renders for it, for its lane.
    fn take_status(&self, t: usize, k: usize) -> String {
        let Some(track) = self.session.tracks.get(t) else {
            return String::new();
        };
        let Some(take) = track.takes.get(k) else {
            return String::new();
        };
        let Some(e) = &take.events else {
            return String::new();
        };
        let mut line = take.sound(track.drafts).2.badge().to_string();
        if e.rev > 0 {
            line.push_str(&format!(" · rev {}", e.rev));
        }
        if take.needs_render(track.drafts) {
            let pending = self
                .render_queue
                .iter()
                .any(|(i, r, _)| *i == take.id && *r == e.rev);
            line.push_str(if pending {
                " · render queued"
            } else {
                " · edited, not rendered (Ctrl+R)"
            });
        }
        for j in self
            .take_jobs
            .iter()
            .filter(|j| j.wanted && j.id == take.id && j.rev == e.rev)
        {
            let q = if j.quality == Quality::Production {
                "PROD"
            } else {
                "draft"
            };
            line.push_str(&format!(" · ◔ {q} {:.0}%", j.job.progress() * 100.0));
        }
        for q in [Quality::Production, e.perf.quality] {
            if let Some(err) = self.take_errors.get(&(take.id.clone(), e.rev, q)) {
                line.push_str(&format!(" · ! {}: {err}", q.name()));
            }
        }
        line
    }

    /// Event takes (track, take) whose revision has no production render, active ones.
    /// ⤓ Export: a file picked, then the mix written once every audible track plays what
    /// it will. `fin`: first every insert of the audible tracks set to production, their
    /// event takes rendered at production and played so (prints follow; Undo restores).
    fn start_export(&mut self, fin: bool) {
        let name = self
            .session
            .dir
            .file_name()
            .map_or("session".into(), |n| n.to_string_lossy().to_string());
        let dir = self.session.dir.join("exports");
        let _ = std::fs::create_dir_all(&dir);
        let file = format!("{name} {}.wav", if fin { "final" } else { "mix" });
        let Some(path) = rfd::FileDialog::new()
            .set_directory(&dir)
            .set_file_name(file)
            .add_filter("WAV", &["wav"])
            .save_file()
        else {
            return;
        };
        let path = path.with_extension("wav");
        if fin {
            let any_solo = self.session.tracks.iter().any(|t| t.solo);
            for t in &mut self.session.tracks {
                if (any_solo && !t.solo) || (!any_solo && t.mute) {
                    continue;
                }
                t.drafts = false;
                for s in t.inserts.iter_mut().filter(|s| !s.bypass) {
                    s.quality = Quality::Production;
                }
            }
            for s in self.session.master_inserts.iter_mut().filter(|s| !s.bypass) {
                s.quality = Quality::Production;
            }
            let audible: Vec<bool> = self
                .session
                .tracks
                .iter()
                .map(|t| if any_solo { t.solo } else { !t.mute })
                .collect();
            for (t, k) in self.production_missing() {
                if audible[t] {
                    self.render_production(t, k);
                }
            }
            self.save();
            // A final asks for its renders: the prints follow the inserts' new quality.
            self.render_audible();
        }
        self.export_note = None;
        self.export = Some(Export::Waiting {
            path,
            stems: self.export_stems,
            fin,
        });
    }

    /// An export waiting: written once the tracks are ready (given up when a print or a
    /// render it waits for failed); one writing: its outcome.
    /// Audio files dragged in from a folder: while they hover, the lane under the cursor
    /// lights up with where they'll land; dropped on a lane, each becomes a take on that
    /// track and the ones below (new tracks past the last) at the beat nearest the drop;
    /// dropped anywhere else over the tracks, new tracks at bar 1 (as Import…). A dropped
    /// folder brings its audio files. Decoded and normalized as Import… is.
    fn file_drop(&mut self, ui: &egui::Ui, area: Rect, view: &View, grid: &Grid) {
        let (hovering, dropped) = ui.input(|i| {
            (
                i.raw.hovered_files.len(),
                i.raw
                    .dropped_files
                    .iter()
                    .filter_map(|f| f.path.clone())
                    .collect::<Vec<_>>(),
            )
        });
        if hovering == 0 && dropped.is_empty() {
            return;
        }
        let Some(p) = file_drag_pos(ui.ctx()) else {
            return;
        };
        let on_lane = self.lanes.iter().find(|(_, r)| r.contains(p)).copied();
        let beat = grid
            .beat_at(view.position(p.x) + (grid.samples_per_beat() * 0.5) as i64)
            .max(0);
        if hovering > 0 {
            ui.ctx().request_repaint();
            let painter = ui.ctx().layer_painter(egui::LayerId::new(
                egui::Order::Foreground,
                egui::Id::new("file_drop"),
            ));
            let files = if hovering == 1 {
                "1 file".to_string()
            } else {
                format!("{hovering} files")
            };
            let (rect, text) = match on_lane {
                Some((i, r)) => {
                    let x = view.x(grid.beat(beat)).clamp(r.left(), r.right());
                    painter.line_segment(
                        [Pos2::new(x, r.top()), Pos2::new(x, r.bottom())],
                        Stroke::new(2.0, theme::ACCENT),
                    );
                    let bpb = grid.beats_per_bar.max(1) as i64;
                    let below = if hovering > 1 {
                        " and the tracks below"
                    } else {
                        ""
                    };
                    (
                        r,
                        format!(
                            "{files} onto {}{below}, bar {} beat {}",
                            self.session.tracks[i].name,
                            beat / bpb + 1,
                            beat % bpb + 1
                        ),
                    )
                }
                None => (area, format!("{files} as new tracks at bar 1")),
            };
            painter.rect_filled(rect, 4.0, theme::ACCENT.gamma_multiply(0.12));
            painter.rect_stroke(
                rect,
                4.0,
                Stroke::new(1.5, theme::ACCENT),
                egui::StrokeKind::Inside,
            );
            painter.text(
                rect.left_top() + egui::vec2(10.0, 8.0),
                egui::Align2::LEFT_TOP,
                text,
                egui::FontId::proportional(14.0),
                theme::INK,
            );
        }
        if dropped.is_empty() || !(area.contains(p) || on_lane.is_some()) {
            return;
        }
        let audio_file = |f: &std::path::Path| {
            f.extension()
                .and_then(|e| e.to_str())
                .is_some_and(|e| AUDIO_EXT.contains(&e.to_ascii_lowercase().as_str()))
        };
        let mut files = Vec::new();
        for f in dropped {
            if f.is_dir() {
                let mut inside: Vec<PathBuf> = std::fs::read_dir(&f)
                    .map(|d| d.filter_map(|e| Some(e.ok()?.path())).collect())
                    .unwrap_or_default();
                inside.sort();
                files.extend(inside.into_iter().filter(|f| audio_file(f)));
            } else if audio_file(&f) {
                files.push(f);
            }
        }
        if files.is_empty() {
            self.error = Some(format!(
                "nothing to import: drop audio files ({})",
                AUDIO_EXT.join(", ")
            ));
            return;
        }
        let dest = match on_lane {
            Some((i, _)) => ImportDest::Onto {
                track: self.session.tracks[i].id.clone(),
                position: grid.beat(beat),
            },
            None => ImportDest::NewTracks,
        };
        self.import_files(files, dest);
    }

    /// Import…: audio files picked (several at once), decoded on a thread at the session's
    /// rate (`audio::load_channels`: a stereo file a stereo take, more channels averaged,
    /// resampled as Python does), then normalized as [`ImportNormalize`] says.
    fn start_import(&mut self) {
        let Some(files) = rfd::FileDialog::new()
            .add_filter("Audio", &AUDIO_EXT)
            .pick_files()
        else {
            return;
        };
        self.import_files(files, ImportDest::NewTracks);
    }

    /// Decode `files` on a thread (as Import… does) into `dest`.
    fn import_files(&mut self, files: Vec<PathBuf>, dest: ImportDest) {
        if files.is_empty() {
            return;
        }
        if self.import.is_some() {
            self.error = Some("an import is still running: drop the files again after it".into());
            return;
        }
        let rate = self.session.rate;
        let n = files.len();
        let (normalize, target) = (self.import_normalize, self.import_target_dbfs);
        let handle = std::thread::spawn(move || {
            type Channels = Result<Vec<Vec<f64>>, String>;
            let loaded: Vec<(PathBuf, Channels)> = files
                .into_iter()
                .map(|p| {
                    let x = audio::load_channels(&p, rate).and_then(|x| {
                        if x.first().is_none_or(Vec::is_empty) {
                            Err(format!("{}: no audio in it", p.display()))
                        } else {
                            Ok(x)
                        }
                    });
                    (p, x)
                })
                .collect();
            let ok: Vec<Vec<Vec<f64>>> = loaded
                .iter()
                .filter_map(|(_, x)| x.as_ref().ok().cloned())
                .collect();
            let mut gains = match normalize {
                ImportNormalize::Off => vec![0.0; ok.len()],
                ImportNormalize::Each | ImportNormalize::Together => {
                    audio::normalize_gains_db_channels(
                        &ok,
                        rate,
                        NORMALIZE_LOUDEST_S,
                        target,
                        normalize == ImportNormalize::Together,
                    )
                }
            }
            .into_iter();
            loaded
                .into_iter()
                .map(|(p, x)| {
                    let x = x.map(|chans| {
                        let g_db = gains.next().unwrap_or(0.0);
                        let g = 10f64.powf(g_db / 20.0);
                        let scaled = |x: &[f64]| x.iter().map(|&v| (v * g) as f32).collect();
                        let left = scaled(&chans[0]);
                        let right = chans.get(1).map(|r| scaled(r));
                        (left, right, g_db)
                    });
                    (p, x)
                })
                .collect()
        });
        self.import_note = None;
        self.import = Some(Import {
            files: n,
            normalize,
            dest,
            handle,
        });
    }

    /// The import, once decoded: a track per file, named after it, its take at bar 1 (one
    /// undo step); files that failed are listed in the error line.
    fn poll_import(&mut self, ctx: &egui::Context) {
        let Some(imp) = &self.import else { return };
        if !imp.handle.is_finished() {
            ctx.request_repaint_after(Duration::from_millis(200));
            return;
        }
        let Some(imp) = self.import.take() else {
            return;
        };
        let Ok(decoded) = imp.handle.join() else {
            self.error = Some("the import failed (its thread panicked)".into());
            return;
        };
        let bar1 = Grid::new(self.session.rate, &self.session.transport).bar(1);
        // dropped on a track: from that track down, at the drop's position
        let (mut next, position) = match &imp.dest {
            ImportDest::NewTracks => (None, bar1),
            ImportDest::Onto { track, position } => (self.session.track_index(track), *position),
        };
        let mut takes = Vec::new();
        let mut tracks = Vec::new();
        let mut failed = Vec::new();
        for (path, x) in decoded {
            match x {
                Ok((samples, right, gain_db)) => {
                    let file = path
                        .file_name()
                        .map_or("?".into(), |n| n.to_string_lossy().to_string());
                    let name = path
                        .file_stem()
                        .map_or(file.clone(), |n| n.to_string_lossy().to_string());
                    let from = json!({
                        "device": format!("import of {file}"),
                        "import": {
                            "file": path.to_string_lossy(),
                            "rate": self.session.rate,
                            "normalize": imp.normalize.name(),
                            "gain_db": gain_db,
                            "channels": if right.is_some() { 2 } else { 1 },
                        },
                    });
                    match next {
                        Some(i) if i < self.session.tracks.len() => {
                            takes.push((i, samples, right, from));
                            next = Some(i + 1);
                        }
                        _ => tracks.push((name, 0.0, samples, right, position, from)),
                    }
                }
                Err(e) => failed.push(e),
            }
        }
        let n = takes.len() + tracks.len();
        for (i, samples, right, from) in takes {
            self.saved = true;
            if let Err(e) = self
                .session
                .add_rendered_take(i, samples, right, position, from)
            {
                self.error = Some(format!("the import failed: {e}"));
                return;
            }
        }
        if let Err(e) = self.add_audio_tracks_lr(tracks) {
            self.error = Some(format!("the import failed: {e}"));
            return;
        }
        self.import_note = Some(format!(
            "imported {n} of {} file{}",
            imp.files,
            if imp.files == 1 { "" } else { "s" }
        ));
        if !failed.is_empty() {
            self.error = Some(format!("not imported: {}", failed.join("; ")));
        }
    }

    fn poll_export(&mut self, ctx: &egui::Context) {
        match &self.export {
            None => return,
            Some(Export::Waiting { path, stems, fin }) => {
                let failed = (0..self.session.tracks.len()).find_map(|i| {
                    let t = &self.session.tracks[i];
                    let sig = self.session.chain_signature(i);
                    if let Some(e) = sig.and_then(|s| self.print_errors.get(&s)) {
                        return Some(format!("{}: its print failed: {e}", t.name));
                    }
                    t.lane_takes().into_iter().find_map(|k| {
                        let k = &t.takes[k];
                        let rev = k.events.as_ref()?.rev;
                        self.take_errors
                            .iter()
                            .find(|((id, r, _), _)| *id == k.id && *r == rev)
                            .map(|(_, e)| format!("{}: its render failed: {e}", t.name))
                    })
                });
                let failed = failed.or_else(|| {
                    let e = self
                        .session
                        .master_signature()
                        .and_then(|s| self.print_errors.get(&s))?;
                    Some(format!("Master: its print failed: {e}"))
                });
                if let Some(e) = failed {
                    self.error = Some(format!("the export stopped: {e}"));
                    self.export = None;
                    return;
                }
                if self.session.export_problems(*fin).is_empty() {
                    let (path, stems) = (path.clone(), *stems);
                    let md = self.session.mixdown();
                    let mut record = self.session.export_record();
                    record["final"] = json!(*fin);
                    let p = path.clone();
                    let handle = std::thread::spawn(move || md.write(&p, stems, &record));
                    self.export = Some(Export::Writing { path, handle });
                }
            }
            Some(Export::Writing { handle, .. }) => {
                if handle.is_finished() {
                    let Some(Export::Writing { path, handle }) = self.export.take() else {
                        return;
                    };
                    let file = path
                        .file_name()
                        .map_or("?".into(), |n| n.to_string_lossy().to_string());
                    match handle.join() {
                        Ok(Ok(peak)) => {
                            self.export_note = Some(if peak > 0.0 {
                                format!(
                                    "exported {file}: peaks at {peak:+.1} dBFS (kept in the float file; turn the mix down before a fixed-point copy)"
                                )
                            } else {
                                format!("exported {file} (peak {peak:.1} dBFS)")
                            });
                        }
                        Ok(Err(e)) => self.error = Some(format!("the export failed: {e}")),
                        Err(_) => {
                            self.error = Some("the export failed (its thread panicked)".into())
                        }
                    }
                    return;
                }
            }
        }
        ctx.request_repaint_after(Duration::from_millis(200));
    }

    /// The export's controls in the session line: ⤓ Export mix… / final…, stems, and what
    /// a running export waits for.
    fn export_controls(&mut self, ui: &mut egui::Ui) {
        ui.add_space(12.0);
        match &self.export {
            None => {
                if ui
                    .small_button("⤓ Export mix…")
                    .on_hover_text(
                        "The mix as ▶ plays it (each audible track through its fader and pan, \
                         no click) to a stereo float WAV from bar 1, with a .json of what it \
                         was made from; waits for prints still running",
                    )
                    .clicked()
                {
                    self.start_export(false);
                }
                if ui
                    .small_button("⤓ Export final…")
                    .on_hover_text(
                        "The same at production: every insert of the audible tracks set to \
                         production and every MIDI take rendered at production first (this \
                         takes a while; Undo restores the inserts' qualities)",
                    )
                    .clicked()
                {
                    self.start_export(true);
                }
                ui.checkbox(&mut self.export_stems, "stems").on_hover_text(
                    "Also each track's part of the mix (its fader and pan) as a stereo WAV, \
                         from the same start: the stems sum to the mix",
                );
                if let Some(n) = &self.export_note {
                    ui.label(RichText::new(n).small().color(theme::MUTED));
                }
            }
            Some(Export::Waiting { fin, .. }) => {
                let problems = self.session.export_problems(*fin);
                let first = problems.first().cloned().unwrap_or_default();
                let more = problems.len().saturating_sub(1);
                ui.label(
                    RichText::new(if more > 0 {
                        format!("⤓ export waits: {first} (+{more} more)")
                    } else {
                        format!("⤓ export waits: {first}")
                    })
                    .small()
                    .color(theme::ACCENT),
                )
                .on_hover_text(problems.join("\n"));
                let idle = !self.audible_stale().is_empty()
                    || (!self.session.master_print_current() && !self.master_printing());
                if idle
                    && ui
                        .small_button("Render them and export")
                        .on_hover_text(
                            "Render and print what the export waits for (in the background); \
                             the export follows once they land",
                        )
                        .clicked()
                {
                    self.render_audible();
                }
                if ui
                    .small_button("✕")
                    .on_hover_text("Cancel the export")
                    .clicked()
                {
                    self.export = None;
                }
            }
            Some(Export::Writing { .. }) => {
                ui.label(RichText::new("⤓ writing…").small().color(theme::ACCENT));
            }
        }
    }

    /// The audible tracks whose take isn't rendered or whose print isn't current, not asked
    /// for yet (what an export waits for).
    fn audible_stale(&self) -> Vec<usize> {
        let any_solo = self.session.tracks.iter().any(|t| t.solo);
        let edits: HashSet<usize> = self.renders_missing().into_iter().map(|(t, _)| t).collect();
        let prints: HashSet<usize> = self.prints_missing().into_iter().collect();
        (0..self.session.tracks.len())
            .filter(|&i| {
                let t = &self.session.tracks[i];
                (if any_solo { t.solo } else { !t.mute })
                    && (edits.contains(&i) || prints.contains(&i))
            })
            .collect()
    }

    /// Every audible track's stale take rendered and its print made (an export asked).
    fn render_audible(&mut self) {
        for t in self.audible_stale() {
            self.render_track(t, None);
        }
        if !self.session.master_print_current() && !self.master_printing() {
            self.request_master_print();
        }
    }

    /// Event takes in the lanes (track, take) whose revision has no production render.
    fn production_missing(&self) -> Vec<(usize, usize)> {
        let mut out = Vec::new();
        for (t, track) in self.session.tracks.iter().enumerate() {
            for k in track.lane_takes() {
                let take = &track.takes[k];
                let Some(e) = &take.events else { continue };
                if !take.has_render(Quality::Production)
                    && !self.render_pending(&take.id, e.rev, Quality::Production)
                {
                    out.push((t, k));
                }
            }
        }
        out
    }

    /// Render event take `k` of track `t` at production, in the background.
    fn render_production(&mut self, t: usize, k: usize) {
        self.request_render(t, k, true);
    }

    /// Render event take `k` of track `t`'s revision (SE1: only when asked for): at
    /// production, or a draft at the quality it was played at. It waits in a queue while
    /// recording, and runs one at a time while a device plays live.
    fn request_render(&mut self, t: usize, k: usize, production: bool) {
        let Some(take) = self.session.tracks.get(t).and_then(|x| x.takes.get(k)) else {
            return;
        };
        let Some(e) = &take.events else { return };
        let q = if production {
            Quality::Production
        } else {
            e.perf.quality
        };
        let (id, rev) = (take.id.clone(), e.rev);
        if take.has_render(q) || self.render_pending(&id, rev, q) {
            return;
        }
        self.take_errors.remove(&(id.clone(), rev, q));
        self.render_queue.push((id, rev, q));
    }

    /// Whether take `id`'s revision `rev` at `q` is queued or rendering.
    fn render_pending(&self, id: &str, rev: u32, q: Quality) -> bool {
        self.render_queue
            .iter()
            .any(|(i, r, x)| i == id && *r == rev && *x == q)
            || self
                .take_jobs
                .iter()
                .any(|j| j.wanted && j.id == id && j.rev == rev && j.quality == q)
    }

    /// Event takes (track, take) that play the proxy or an older render: edited and not
    /// rendered, active ones, none asked for yet.
    fn renders_missing(&self) -> Vec<(usize, usize)> {
        let mut out = Vec::new();
        for (t, track) in self.session.tracks.iter().enumerate() {
            for k in track.lane_takes() {
                let take = &track.takes[k];
                let Some(e) = &take.events else { continue };
                if take.needs_render(track.drafts)
                    && !self.render_pending(&take.id, e.rev, e.perf.quality)
                {
                    out.push((t, k));
                }
            }
        }
        out
    }

    /// Ctrl+R / Render: what is asked for at track `t` (with take `k` when one is meant):
    /// the take's draft render if it needs one, and the track's print if it isn't current.
    fn render_track(&mut self, t: usize, k: Option<usize>) {
        let Some(track) = self.session.tracks.get(t) else {
            return;
        };
        let takes = match k {
            Some(k) => vec![k],
            None => track.lane_takes(),
        };
        let needs: Vec<usize> = takes
            .into_iter()
            .filter(|&k| {
                track
                    .takes
                    .get(k)
                    .is_some_and(|x| x.needs_render(track.drafts))
            })
            .collect();
        for k in needs {
            self.request_render(t, k, false);
        }
        if !self.session.print_current(t) {
            self.request_print(t);
        }
    }

    /// Event take `k` of track `t` bounced to audio: now if its production render is there,
    /// else once it lands (started now).
    fn bounce(&mut self, t: usize, k: usize) {
        let Some(take) = self.session.tracks.get(t).and_then(|x| x.takes.get(k)) else {
            return;
        };
        let Some(e) = &take.events else { return };
        let (id, rev) = (take.id.clone(), e.rev);
        if take.has_render(Quality::Production) {
            self.bounce_now(&id, rev);
        } else {
            self.bounces.insert((id, rev));
            self.render_production(t, k);
        }
    }

    /// Take `id`'s production render of revision `rev` as a new audio take on its track,
    /// where the take sits (the MIDI take stays in the lane).
    fn bounce_now(&mut self, id: &str, rev: u32) {
        let found = self
            .session
            .tracks
            .iter()
            .enumerate()
            .find_map(|(t, track)| {
                let k = track.takes.iter().find(|k| k.id == id)?;
                let r = k
                    .renders
                    .iter()
                    .find(|r| r.rev == rev && r.quality == Quality::Production)?;
                Some((t, k.position, r.audio.clone(), r.right.clone()))
            });
        let Some((t, position, audio, right)) = found else {
            self.error = Some(format!("{id}: its production render isn't there to bounce"));
            return;
        };
        let from = json!({
            "take": id,
            "revision": rev,
            "quality": Quality::Production.name(),
            "bounced": "the MIDI take's production render",
            "code": circuitsim::SOURCE_HASH,
        });
        self.saved = true;
        match self.session.add_rendered_take(
            t,
            (*audio).clone(),
            right.map(|r| (*r).clone()),
            position,
            from,
        ) {
            Ok(new) => {
                self.session.tracks[t].bounce_clips(id, &new);
                self.save();
            }
            Err(e) => self.error = Some(e),
        }
    }

    /// Event takes' renders: finished ones attached to their takes, ones for revisions no
    /// take plays cancelled, a lookup of every revision's renders in the cache, the renders
    /// asked for started from the queue (SE1: none by itself), the proxy's stand-in made for
    /// an edited take whose device has one (decision 1); none while recording or a roll
    /// edit is in progress.
    fn poll_take_renders(&mut self, ctx: &egui::Context, recording: bool, live: bool) {
        self.poll_proxies(ctx);
        let mut i = 0;
        while i < self.take_jobs.len() {
            if !self.take_jobs[i].job.is_finished() {
                i += 1;
                continue;
            }
            let j = self.take_jobs.remove(i);
            match j.job.join() {
                Some(Ok(done)) => {
                    self.session.attach_render(
                        &j.id,
                        j.rev,
                        j.quality,
                        &done.audio,
                        done.right.as_deref().map(Vec::as_slice),
                    );
                    if j.quality == Quality::Production
                        && self.bounces.remove(&(j.id.clone(), j.rev))
                    {
                        self.bounce_now(&j.id, j.rev);
                    }
                }
                Some(Err(e)) if e != NOT_RENDERED && e != "cancelled" => {
                    self.take_errors.insert((j.id, j.rev, j.quality), e);
                }
                _ => {}
            }
        }
        let current: HashSet<(String, u32)> = self
            .session
            .tracks
            .iter()
            .flat_map(|t| &t.takes)
            .filter_map(|k| k.events.as_ref().map(|e| (k.id.clone(), e.rev)))
            .collect();
        for j in &self.take_jobs {
            if j.wanted && !current.contains(&(j.id.clone(), j.rev)) {
                j.job.cancel();
            }
        }
        if !self.take_jobs.is_empty() {
            ctx.request_repaint_after(Duration::from_millis(200));
        }
        // Queued renders no take plays any more are dropped.
        self.render_queue
            .retain(|(id, rev, _)| current.contains(&(id.clone(), *rev)));
        let editing = self.roll.as_ref().is_some_and(Roll::busy);
        if recording || self.recording.is_some() || editing {
            if editing {
                ctx.request_repaint_after(Duration::from_millis(250));
            }
            return;
        }
        let limit = if live { 1 } else { MAX_PRINT_JOBS };
        let mut rendering = self.take_jobs.iter().filter(|j| j.wanted).count();
        let mut start = Vec::new();
        // Lookups: every revision's renders found in the cache (never rendered here).
        for t in &self.session.tracks {
            for k in &t.takes {
                let Some(e) = &k.events else { continue };
                for q in [Quality::Production, e.perf.quality] {
                    let key = (k.id.clone(), e.rev, q, false);
                    if k.has_render(q) || self.tried.contains(&key) {
                        continue;
                    }
                    start.push((key, e.perf.clone()));
                }
            }
        }
        // The renders asked for, in the order asked.
        while rendering < limit && !self.render_queue.is_empty() {
            let (id, rev, q) = self.render_queue.remove(0);
            let perf = self
                .session
                .tracks
                .iter()
                .flat_map(|t| &t.takes)
                .find(|k| k.id == id)
                .and_then(|k| k.events.as_ref())
                .filter(|e| e.rev == rev)
                .map(|e| e.perf.clone());
            if let Some(perf) = perf {
                rendering += 1;
                start.push(((id, rev, q, true), perf));
            }
        }
        if !self.render_queue.is_empty() {
            ctx.request_repaint_after(Duration::from_millis(250));
        }
        let config = self.root.join("config");
        for ((id, rev, q, render), perf) in start {
            self.tried.insert((id.clone(), rev, q, render));
            let job = take_render::Job::spawn(
                config.clone(),
                perf,
                q,
                take_dir(&self.session.dir, &id).join("renders"),
                render,
            );
            self.take_jobs.push(TakeJob {
                id,
                rev,
                quality: q,
                wanted: render,
                job,
            });
        }
    }

    /// The proxy's stand-ins (decision 1): an active event take edited and not rendered,
    /// whose device has a proxy, plays its revision through the proxy, played offline on a
    /// thread (a fraction of a second for a long take) as soon as the edit lands.
    fn poll_proxies(&mut self, ctx: &egui::Context) {
        let mut i = 0;
        while i < self.proxy_jobs.len() {
            if !self.proxy_jobs[i].handle.is_finished() {
                i += 1;
                continue;
            }
            let j = self.proxy_jobs.remove(i);
            if let Ok(audio) = j.handle.join() {
                self.session.attach_proxy(&j.id, j.rev, &audio);
            }
        }
        let config = self.root.join("config");
        let mut start = Vec::new();
        for k in self
            .session
            .tracks
            .iter()
            .flat_map(|t| t.lane_takes().into_iter().map(move |k| &t.takes[k]))
        {
            let Some(e) = &k.events else { continue };
            if e.rev == 0
                || k.has_proxy()
                || k.has_render(e.perf.quality)
                || k.has_render(Quality::Production)
                || self.proxy_tried.contains(&(k.id.clone(), e.rev))
            {
                continue;
            }
            start.push((k.id.clone(), e.rev, e.perf.clone()));
        }
        for (id, rev, perf) in start {
            self.proxy_tried.insert((id.clone(), rev));
            let tables = self
                .proxy_tables
                .entry(perf.device.clone())
                .or_insert_with(|| {
                    varimu_app::proxy::Tables::load(&config, &perf.device)
                        .ok()
                        .flatten()
                        .map(Arc::new)
                })
                .clone();
            let Some(tables) = tables else { continue };
            let handle =
                std::thread::spawn(move || varimu_app::proxy::render_performance(tables, &perf));
            self.proxy_jobs.push(ProxyJob { id, rev, handle });
        }
        if !self.proxy_jobs.is_empty() {
            ctx.request_repaint_after(Duration::from_millis(50));
        }
    }

    /// A device's proxy tables (loaded once; None: it has none).
    fn proxy_for(&mut self, device: &str) -> Option<Arc<varimu_app::proxy::Tables>> {
        let config = self.root.join("config");
        self.proxy_tables
            .entry(device.to_string())
            .or_insert_with(|| {
                varimu_app::proxy::Tables::load(&config, device)
                    .ok()
                    .flatten()
                    .map(Arc::new)
            })
            .clone()
    }

    /// What the roll's previews of `device`'s take play through (decision 8): the device
    /// itself when Play plays it from keys, else its proxy, else the test oscillator.
    fn preview_via(&mut self, play: &PlayView, device: &str) -> &'static str {
        if play.player().is_some()
            && !play.adopted()
            && play.plays_keys()
            && play.device_label_id().1 == device
        {
            "through the device, playing live in Play"
        } else if self.proxy_for(device).is_some() {
            "through the device's proxy"
        } else {
            "through the test oscillator: the device has no proxy"
        }
    }

    /// A preview of a note of `perf`'s take, through what [`SessionView::preview_via`] says
    /// (the preview voice rides on whatever player plays: the session's tracks-only one
    /// when nothing else does). Heard only, never recorded.
    fn preview_note(&mut self, play: &PlayView, perf: &Performance, note: u8, vel: u8, on: bool) {
        if play.player().is_some()
            && !play.adopted()
            && play.plays_keys()
            && play.device_label_id().1 == perf.device
        {
            play.preview_key(note, vel, on);
            return;
        }
        let tables = self.proxy_for(&perf.device);
        if let Some(p) = play.player() {
            p.set_preview_voice(tables, perf.values.clone(), perf.playing);
            p.preview_key(note, vel, on);
        }
    }

    /// The other tracks' MIDI notes where their clips play them (timeline start, end, key):
    /// the roll's ghosts.
    fn ghost_notes(&self, t: usize) -> Vec<(i64, i64, u8)> {
        let mut out = Vec::new();
        for (i, track) in self.session.tracks.iter().enumerate() {
            if i == t {
                continue;
            }
            for c in track.clips.iter().filter(|c| !c.muted) {
                let Some(k) = track.take_of(c) else { continue };
                let Some(e) = &k.events else { continue };
                // The clip plays the take's samples src_start.. at its position.
                let origin = c.position - c.src_start as i64 - e.from as i64;
                for n in e.perf.notes() {
                    let (a, b) = (origin + n.start as i64, origin + n.end as i64);
                    let (a, b) = (a.max(c.position), b.min(c.end()));
                    if b > a {
                        out.push((a, b, n.note));
                    }
                }
            }
        }
        out
    }

    /// The piano roll's view of event take `k` of track `t`.
    fn roll_place(&self, t: usize, k: usize, playhead: Option<i64>) -> Option<piano_roll::Place> {
        let take = self.session.tracks.get(t)?.takes.get(k)?;
        let e = take.events.as_ref()?;
        Some(piano_roll::Place {
            notes: e.perf.notes(),
            rev: e.rev,
            id: take.id.clone(),
            position: take.position,
            from: e.from,
            len: take.len() as u64,
            grid: Grid::new(self.session.rate, &self.session.transport),
            rate: self.session.rate,
            playhead,
            colour: COLOURS[t % COLOURS.len()],
            status: self.take_status(t, k),
            needs_render: take.needs_render(self.session.tracks[t].drafts)
                && !self.render_pending(&take.id, e.rev, e.perf.quality),
            has_production: take.has_render(Quality::Production)
                || self.render_pending(&take.id, e.rev, Quality::Production),
            cursor: self.session.transport.cursor,
            preview_via: String::new(),
            ghosts: self.ghost_notes(t),
            pressure: e
                .perf
                .events
                .iter()
                .filter_map(|&(at, ev)| match ev {
                    varimu_app::performance::Ev::Pressure(v) => {
                        Some((take.position + at as i64 - e.from as i64, v))
                    }
                    _ => None,
                })
                .collect(),
            pedal: e
                .perf
                .events
                .iter()
                .filter_map(|&(at, ev)| match ev {
                    varimu_app::performance::Ev::Pedal(d) => {
                        Some((take.position + at as i64 - e.from as i64, d))
                    }
                    _ => None,
                })
                .collect(),
        })
    }

    /// Open the piano roll on event take `k` of track `t`.
    fn open_roll(&mut self, t: usize, k: usize) {
        if let Some(place) = self.roll_place(t, k, None) {
            let mut r = Roll::new(t, &place);
            // Its grid starts at the session's snap (it edits notes: finer as it likes).
            if let Some(d) = self.session.transport.snap.per_beat() {
                r.set_division(d);
            }
            self.roll = Some(r);
        }
    }

    /// The piano roll's pane: its edits saved as the take's revisions, its previews played.
    fn roll_ui(&mut self, ui: &mut egui::Ui, play: &PlayView) {
        let Some((t, id)) = self.roll.as_ref().map(|r| (r.track, r.take.clone())) else {
            return;
        };
        let Some(k) = self
            .session
            .tracks
            .get(t)
            .and_then(|tr| tr.takes.iter().position(|x| x.id == id))
        else {
            self.roll = None;
            return;
        };
        let playhead = play
            .player()
            .map(|p| p.status().transport)
            .filter(|s| s.running)
            .map(|s| s.heard);
        let Some(mut place) = self.roll_place(t, k, playhead) else {
            self.roll = None;
            return;
        };
        let Some(perf) = self.session.tracks[t].takes[k]
            .events
            .as_ref()
            .map(|e| e.perf.clone())
        else {
            return;
        };
        place.preview_via = self.preview_via(play, &perf.device).to_string();
        self.roll_rect = Some(ui.max_rect());
        let outs = match &mut self.roll {
            Some(r) => r.ui(ui, &place),
            None => return,
        };
        for o in outs {
            match o {
                piano_roll::Out::Edited(notes) => {
                    let range = find_device(&perf.device)
                        .and_then(|d| d.pitch)
                        .and_then(|p| p.range)
                        .map(|r| r.control);
                    match self.session.revise(t, k, perf.edited(&notes, range)) {
                        Ok(rev) => {
                            if let Some(r) = &mut self.roll {
                                r.saved_as(rev);
                            }
                            self.saved = true;
                        }
                        Err(e) => self.error = Some(e),
                    }
                }
                piano_roll::Out::Preview(note, vel, on) => {
                    self.preview_note(play, &perf, note, vel, on);
                }
                piano_roll::Out::Render(production) => self.request_render(t, k, production),
                piano_roll::Out::Cursor(pos) => {
                    self.session.transport.cursor = pos;
                    self.save();
                }
                piano_roll::Out::Close => self.roll = None,
            }
        }
    }

    /// Where takes land: new ones, and every one recorded so far (an edit, undoable).
    fn placement_ui(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.label("New takes:");
            let mut heard = self.session.place_heard;
            ui.radio_value(&mut heard, true, "as heard").on_hover_text(
                "Where they were recorded: they play back against the click and the other tracks exactly as the monitor played them",
            );
            ui.radio_value(&mut heard, false, "on the click").on_hover_text(
                "The monitor's latency taken off: where you meant them if you played to the click, not to what you heard",
            );
            if heard != self.session.place_heard {
                self.session.place_heard = heard;
                self.save();
            }
            ui.separator();
            let busy = self.recording.is_some();
            if ui
                .add_enabled(!busy, egui::Button::new("Every take as heard"))
                .clicked()
                && self.session.place_all(true)
            {
                self.save();
            }
            if ui
                .add_enabled(!busy, egui::Button::new("Every take on the click"))
                .clicked()
                && self.session.place_all(false)
            {
                self.save();
            }
        });
    }

    fn latency_ui(&mut self, ui: &mut egui::Ui, play: &PlayView) {
        self.placement_ui(ui);
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
            "output device {:.1} ms (cpal) · queue {:.1} ms · block {:.1} ms: the tracks and the click are heard {:.0} ms after they are computed, a key about {:.0} ms after it is played (a take on the click is placed that much earlier)",
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

/// The calibrations and Import…'s normalizing (`recording.json`; its `last_session` and
/// `transport` from before the app started fresh are ignored).
/// The editing switches kept in the prefs (SE8): Ripple, splits on zero crossings.
fn load_edit_prefs() -> (bool, bool) {
    let v: Value = prefs_path()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or(Value::Null);
    (
        v["ripple"].as_bool().unwrap_or(false),
        v["zero_crossings"].as_bool().unwrap_or(false),
    )
}

fn load_prefs() -> (Vec<Calibration>, (ImportNormalize, f64)) {
    let Some(text) = prefs_path().and_then(|p| std::fs::read_to_string(p).ok()) else {
        return (Vec::new(), (ImportNormalize::Off, ALIGNMENT_DBFS));
    };
    let v: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
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
    let normalize = (
        ImportNormalize::from_name(v["import_normalize"].as_str().unwrap_or("off")),
        v["import_target_dbfs"]
            .as_f64()
            .unwrap_or(ALIGNMENT_DBFS)
            .clamp(-60.0, 0.0),
    );
    (cals, normalize)
}

fn show_folder(dir: &Path) {
    #[cfg(windows)]
    let _ = std::process::Command::new("explorer").arg(dir).spawn();
    #[cfg(not(windows))]
    let _ = std::process::Command::new("xdg-open").arg(dir).spawn();
}

/// The keys overlay (?): the Session view's keys and the piano roll's.
fn keys_overlay(ui: &mut egui::Ui) {
    let rows: [(&str, &[(&str, &str)]); 3] = [
        (
            "SESSION",
            &[
                (
                    "Space / Shift+Space",
                    "play, stop / play from where it stopped",
                ),
                ("R", "record into the armed track"),
                ("Home / End", "cursor to bar 1 / the session's end"),
                ("Ctrl+← / →", "cursor by bars"),
                ("M", "a marker at the cursor (playing: the playhead)"),
                ("S", "split the selected clip at the cursor"),
                ("Delete", "delete the selected clip or range"),
                (
                    "1 / 2 / 3 / 4 / 5",
                    "Pointer / Blade / Erase / Slip / Envelope",
                ),
                (
                    "← / → (Alt: a sample)",
                    "nudge the selected clip or range a snap step",
                ),
                (
                    "Ctrl+C / X / V / D",
                    "copy, cut, paste at the cursor, duplicate",
                ),
                ("Ctrl+R", "render / print what's selected"),
                ("/", "loop on / off"),
                (
                    "G / H, Ctrl+wheel",
                    "zoom out / in (over the strips: track height)",
                ),
                ("X", "Mixer / Session"),
                ("Ctrl+Z / Ctrl+Y, Ctrl+S", "undo / redo, save"),
                ("Alt (dragging)", "the snap inverted"),
                ("?", "these keys"),
            ],
        ),
        (
            "PIANO ROLL (pointer over it)",
            &[
                ("1 / 2 / 3", "Select / Draw / Erase"),
                ("↑ / ↓ (Shift, Ctrl: octave)", "transpose the selection"),
                ("← / →", "nudge a grid step"),
                ("Q", "quantize (none selected: every note)"),
                (
                    "Ctrl+C / X / V / D",
                    "copy, cut, paste at the cursor, duplicate",
                ),
                ("Ctrl+A, Delete", "select every note, delete the selection"),
                ("Shift+drag a note", "copy it"),
            ],
        ),
        (
            "MOUSE",
            &[
                (
                    "ruler: click / Ctrl / Shift",
                    "cursor / left / right locator",
                ),
                (
                    "ruler: drag, right-click",
                    "draw the loop; markers, time edits",
                ),
                ("clip: drag, edges, corners, top", "move, trim, fades, gain"),
                (
                    "clip: Ctrl+drag / Shift+drag",
                    "slip its audio / drag a copy",
                ),
                (
                    "clip: right-click",
                    "split, fades, crossfade, reverse, varispeed, slice, ...",
                ),
                ("empty lane: click / drag", "cursor / select a range"),
                (
                    "take row: click / drag",
                    "the take whole / comp a stretch in",
                ),
            ],
        ),
    ];
    for (title, keys) in rows {
        ui.label(RichText::new(title).small().strong().color(theme::ACCENT));
        egui::Grid::new(title)
            .num_columns(2)
            .spacing([16.0, 2.0])
            .show(ui, |ui| {
                for (k, what) in keys {
                    ui.label(RichText::new(*k).monospace().small().color(theme::INK));
                    ui.label(RichText::new(*what).small().color(theme::MUTED));
                    ui.end_row();
                }
            });
        ui.add_space(6.0);
    }
}

/// A take's line under its strip: its id, device, length and placement.
fn take_line(k: &Take, rate: u32) -> String {
    let placed = if k.latency == 0 {
        String::new()
    } else if k.heard {
        " · as heard".to_string()
    } else {
        format!(
            " · on the click ({:.0} ms early)",
            k.latency as f64 / rate as f64 * 1e3
        )
    };
    format!(
        "{} · {} · {:.1} s{}{placed}",
        k.id,
        if k.device.is_empty() { "?" } else { &k.device },
        k.len() as f64 / rate as f64,
        if k.is_stereo(false) { " · stereo" } else { "" },
    )
}

/// The timeline's mapping between positions (samples) and x (px).
/// A knob of an insert's panel as an egui widget, its value in `values` (the circuit's
/// default while it isn't there). Returns whether it changed.
/// Whether a slot's device has a key input (its route is heard).
fn print_key_input(slot: &Slot) -> bool {
    find_device(&slot.device).is_some_and(|d| d.key.is_some())
}

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
                let (f, suffix) = knob.display_scale();
                let mut x = cur.as_f64().unwrap_or(*min) * f;
                if ui
                    .add(
                        egui::Slider::new(&mut x, *min * f..=*max * f)
                            .max_decimals(3)
                            .suffix(suffix),
                    )
                    .changed()
                {
                    set = Some(YValue::Float(x / f));
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
            Kind::Toggle => {
                let mut on = cur.as_f64().is_some_and(|x| x != 0.0);
                if ui.checkbox(&mut on, "").changed() {
                    set = Some(YValue::Int(i64::from(on)));
                }
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

/// Where the cursor is while files are dragged in from another program, in this window's
/// points: winit 0.30 reports no position during an OS drag (egui's pointer stays where it
/// last was), so on Windows the OS cursor over the window's client area.
fn file_drag_pos(ctx: &egui::Context) -> Option<Pos2> {
    #[cfg(windows)]
    {
        use windows_sys::Win32::Foundation::POINT;
        use windows_sys::Win32::UI::WindowsAndMessaging::GetCursorPos;
        let mut p = POINT { x: 0, y: 0 };
        // SAFETY: GetCursorPos writes the point it is given, nothing else.
        if unsafe { GetCursorPos(&mut p) } != 0
            && let Some(inner) = ctx.input(|i| i.viewport().inner_rect)
        {
            let ppp = ctx.pixels_per_point();
            return Some(Pos2::new(p.x as f32 / ppp, p.y as f32 / ppp) - inner.min.to_vec2());
        }
    }
    ctx.input(|i| i.pointer.latest_pos())
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
    // The cursor: where play starts.
    let x = view.x(s.cursor);
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

/// The markers on the ruler: a flag at each with its name.
fn draw_markers(painter: &egui::Painter, rect: Rect, view: &View, markers: &[Marker]) {
    for m in markers {
        let x = view.x(m.position);
        if x < rect.left() || x > rect.right() + 40.0 {
            continue;
        }
        painter.line_segment(
            [Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())],
            Stroke::new(1.0, theme::WARN.gamma_multiply(0.8)),
        );
        let label = painter.layout_no_wrap(
            m.name.clone(),
            egui::FontId::proportional(9.0),
            theme::ACCENT_INK,
        );
        let flag = Rect::from_min_size(
            Pos2::new(x, rect.top()),
            egui::vec2(label.size().x + 6.0, 11.0),
        );
        painter.rect_filled(flag, 2.0, theme::WARN);
        painter.galley(Pos2::new(x + 3.0, rect.top()), label, theme::ACCENT_INK);
    }
}

/// The cursor through a lane (a thin line where play starts).
fn draw_cursor(painter: &egui::Painter, rect: Rect, view: &View, cursor: i64) {
    let x = view.x(cursor);
    if x >= rect.left() && x <= rect.right() {
        painter.line_segment(
            [Pos2::new(x, rect.top()), Pos2::new(x, rect.bottom())],
            Stroke::new(1.0, theme::ACCENT.gamma_multiply(0.55)),
        );
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

/// A clip's box in a lane, from `start` to `end` (timeline).
fn clip_box(view: &View, lane: Rect, start: i64, end: i64) -> Rect {
    Rect::from_min_max(
        Pos2::new(view.x(start), lane.top() + 4.0),
        Pos2::new(view.x(end).max(view.x(start) + 1.0), lane.bottom() - 4.0),
    )
}

/// A clip's fades as lines across its top corners, and its gain handle (top middle).
fn draw_fades(painter: &egui::Painter, r: Rect, view: &View, clip: &Clip, colour: Color32) {
    let px = |n: usize| (n as f64 / view.rate * view.px_per_s) as f32;
    let stroke = Stroke::new(1.0, colour.gamma_multiply(0.9));
    let (fi, fo) = (px(clip.fade_in), px(clip.fade_out));
    // A linear fade is a straight line; an equal-power one bows up (SE8).
    let ramp = |x0: f32, w: f32, rising: bool| -> Vec<Pos2> {
        let n = 16;
        (0..=n)
            .map(|k| {
                let u = k as f32 / n as f32;
                let g = match clip.curve {
                    varimu_app::session::FadeCurve::Linear => u,
                    varimu_app::session::FadeCurve::EqualPower => {
                        (u * std::f32::consts::FRAC_PI_2).sin()
                    }
                };
                let x = if rising { x0 + u * w } else { x0 + w - u * w };
                Pos2::new(x, r.bottom() - g * r.height())
            })
            .collect()
    };
    if fi > 1.0 {
        painter.add(egui::Shape::line(ramp(r.left(), fi, true), stroke));
    }
    if fo > 1.0 {
        painter.add(egui::Shape::line(ramp(r.right() - fo, fo, false), stroke));
    }
    // The handles: small squares where a drag sets the fades.
    for x in [r.left() + fi.max(6.0), r.right() - fo.max(6.0)] {
        painter.rect_filled(
            Rect::from_center_size(Pos2::new(x, r.top() + 3.0), egui::vec2(5.0, 5.0)),
            1.0,
            colour.gamma_multiply(0.7),
        );
    }
    if r.width() > 60.0 {
        painter.rect_stroke(
            Rect::from_center_size(
                Pos2::new(r.center().x, r.top() + 4.0),
                egui::vec2(16.0, 6.0),
            ),
            2.0,
            Stroke::new(1.0, colour.gamma_multiply(0.6)),
            StrokeKind::Inside,
        );
    }
}

/// Where `db` sits on a clip's envelope, in its box `r` (SE8: -48 dB at the bottom, +12 at
/// the top).
fn env_y(r: Rect, db: f64) -> f32 {
    use varimu_app::session::{ENV_MAX_DB, ENV_MIN_DB};
    let u = ((db - ENV_MIN_DB) / (ENV_MAX_DB - ENV_MIN_DB)).clamp(0.0, 1.0) as f32;
    r.bottom() - u * r.height()
}

/// The envelope's dB at height `y` in a clip's box `r` (to a tenth of a dB).
fn env_db_at(r: Rect, y: f32) -> f64 {
    use varimu_app::session::{ENV_MAX_DB, ENV_MIN_DB};
    let u = ((r.bottom() - y) / r.height().max(1.0)).clamp(0.0, 1.0) as f64;
    ((ENV_MIN_DB + u * (ENV_MAX_DB - ENV_MIN_DB)) * 10.0).round() / 10.0
}

/// A clip's gain envelope as a line across it (none: 0 dB), with its points as handles
/// while the Envelope tool is out.
fn draw_envelope(painter: &egui::Painter, r: Rect, view: &View, clip: &Clip, handles: bool) {
    let col = theme::WARN;
    let mut pts: Vec<(i64, f64)> = vec![(0, clip.env_db(0))];
    pts.extend(
        clip.env
            .iter()
            .copied()
            .filter(|p| p.0 > 0 && p.0 < clip.len as i64),
    );
    pts.push((clip.len as i64, clip.env_db(clip.len as i64)));
    let line: Vec<Pos2> = pts
        .iter()
        .map(|&(o, d)| Pos2::new(view.x(clip.position + o), env_y(r, d)))
        .collect();
    painter.add(egui::Shape::line(
        line,
        Stroke::new(1.2, col.gamma_multiply(0.9)),
    ));
    if handles {
        for &(o, d) in &clip.env {
            painter.circle_filled(Pos2::new(view.x(clip.position + o), env_y(r, d)), 3.5, col);
        }
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
    draw_clip_from(painter, lane, view, start, len, ov, 0, 0.0, colour, label);
}

/// [`draw_clip`] of a stretch whose first sample is the outline's sample `offset`, drawn
/// at the clip's gain `gain_db` (as it plays: louder than full scale draws flat at the
/// edges). A stereo outline draws as two waveforms, left above right.
#[allow(clippy::too_many_arguments)]
fn draw_clip_from(
    painter: &egui::Painter,
    lane: Rect,
    view: &View,
    start: i64,
    len: usize,
    ov: &Overview,
    offset: usize,
    gain_db: f64,
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
    let g = 10f64.powf(gain_db / 20.0) as f32;
    // (channel, its centre line, its half height): one for mono, two halves for stereo
    let lanes: Vec<(usize, f32, f32)> = if ov.is_stereo() {
        let h = half * 0.5;
        painter.line_segment(
            [
                Pos2::new(x0.max(lane.left()), mid),
                Pos2::new(x1.min(lane.right()), mid),
            ],
            Stroke::new(1.0, colour.gamma_multiply(0.25)),
        );
        vec![(0, mid - h, h * 0.92), (1, mid + h, h * 0.92)]
    } else {
        vec![(0, mid, half)]
    };
    for px in a..b {
        let s0 = (px as f32 - x0) as f64 * spp + offset as f64;
        for &(ch, m, h) in &lanes {
            if let Some((lo, hi)) = ov.range_ch(ch, s0, s0 + spp) {
                let (lo, hi) = ((lo * g).clamp(-1.0, 1.0), (hi * g).clamp(-1.0, 1.0));
                painter.line_segment(
                    [
                        Pos2::new(px as f32 + 0.5, m - hi * h),
                        Pos2::new(px as f32 + 0.5, m - lo * h + 0.5),
                    ],
                    Stroke::new(1.0, wave),
                );
            }
        }
    }
}

/// An event take's notes drawn small inside its clip `r` (pitch upward), so a lane shows
/// what was played.
fn draw_notes(
    painter: &egui::Painter,
    r: Rect,
    view: &View,
    position: i64,
    from: u64,
    notes: &[varimu_app::performance::Note],
    colour: Color32,
) {
    let (Some(lo), Some(hi)) = (
        notes.iter().map(|n| n.note).min(),
        notes.iter().map(|n| n.note).max(),
    ) else {
        return;
    };
    let span = ((hi - lo) as f32 + 1.0).max(12.0);
    let (top, h) = (r.top() + 15.0, (r.height() - 19.0).max(4.0));
    let row = (h / span).clamp(2.0, 6.0);
    let fill = colour.gamma_multiply(0.9);
    for n in notes {
        let at = |t: u64| view.x(position + t as i64 - from as i64);
        let (x0, x1) = (at(n.start).max(r.left()), at(n.end).min(r.right()));
        if x1 <= x0 {
            continue;
        }
        let y = top + h * (1.0 - (n.note - lo + 1) as f32 / span);
        painter.rect_filled(
            Rect::from_min_max(Pos2::new(x0, y), Pos2::new(x1.max(x0 + 2.0), y + row - 0.5)),
            1.0,
            fill,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use varimu_app::performance::{Ev, Performance, Playing};
    use varimu_app::session::{Monitor, Recorded};

    fn repo() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
    }

    /// A view on a scratch session in the temp folder (never the user's).
    fn scratch(name: &str) -> (SessionView, PathBuf) {
        let dir = std::env::temp_dir().join(format!("varimu_view_{name}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let s = Session::new(dir.clone(), 48_000, TransportSettings::default());
        (SessionView::with_session(&repo(), s, true, Vec::new()), dir)
    }

    fn wait(jobs: &[PrintJob]) {
        for j in jobs {
            while !j.job.is_finished() {
                std::thread::sleep(Duration::from_millis(20));
            }
        }
    }

    #[test]
    fn new_starts_at_the_defaults_and_drops_the_old_session() {
        let (mut v, dir) = scratch("new_defaults");
        v.session.transport.bpm = 87.0;
        v.session.transport.beats_per_bar = 3;
        v.session.transport.loop_on = true;
        let tone: Vec<f32> = (0..4800).map(|i| (i as f32 * 0.05).sin() * 0.3).collect();
        v.session
            .add_rendered_take(0, tone, None, 0, json!({"device": "test"}))
            .unwrap();
        v.session.tracks.push(Track::new("Bass"));
        v.selected = Some((0, 0));
        v.insert_sel = Some((1, 0));
        v.range_sel = Some((0, 4800, 0, 1));
        v.view_s = 30.0;
        v.new_session();
        assert_eq!(v.session.transport, TransportSettings::default());
        assert_eq!(v.session.rate, DEFAULT_RATE);
        assert_eq!(v.session.tracks.len(), 1);
        assert!(v.session.tracks[0].takes.is_empty());
        assert_ne!(v.session.dir, dir);
        assert!(!v.saved && v.undo.is_empty());
        assert_eq!((v.selected, v.insert_sel, v.range_sel), (None, None, None));
        assert_eq!(v.view_s, -0.5);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_editing_tools_split_ripple_nudge_process_and_bounce() {
        let (mut v, dir) = scratch("editing");
        let ctx = egui::Context::default();
        let tone: Vec<f32> = (0..48_000).map(|i| (i as f32 * 0.05).sin() * 0.3).collect();
        v.session
            .add_rendered_take(0, tone.clone(), None, 0, json!({"device": "test"}))
            .unwrap();
        v.commit(&ctx, false);
        // A split on a zero crossing (S with the switch on).
        v.zero_cross = true;
        v.session.transport.cursor = 24_000;
        v.selected = Some((0, 0));
        assert!(v.clip_action(0, 0, "split"));
        let at = v.session.tracks[0].clips[1].position as usize;
        assert!((at as i64 - 24_000).abs() <= 240, "{at}");
        assert!((tone[at - 1] < 0.0) != (tone[at] < 0.0) || tone[at] == 0.0);
        // Ripple: deleting the first half pulls the second up to where it began.
        v.ripple = true;
        v.selected = Some((0, 0));
        v.delete_selection();
        assert_eq!(v.session.tracks[0].clips.len(), 1);
        assert_eq!(v.session.tracks[0].clips[0].position, 0);
        // Nudges: 10 ms with the snap off, a sample with Alt.
        v.session.transport.snap = Snap::Off;
        v.selected = Some((0, 0));
        v.nudge(1, false);
        v.nudge(-1, true);
        assert_eq!(v.session.tracks[0].clips[0].position, 479);
        // Polarity, then Reverse as a new take, undone back to the old one.
        assert!(v.apply_clip_op(0, 0, ClipOp::Invert));
        assert!(v.session.tracks[0].clips[0].invert);
        v.commit(&ctx, false);
        let take = v.session.tracks[0].clips[0].take.clone();
        assert!(v.apply_clip_op(0, 0, ClipOp::Reverse));
        assert_ne!(v.session.tracks[0].clips[0].take, take);
        assert!(v.session.tracks[0].clips[0].invert);
        v.commit(&ctx, false);
        v.undo();
        assert_eq!(v.session.tracks[0].clips[0].take, take);
        // Bounce the soloed track to a new one, muting it.
        v.session.tracks[0].solo = true;
        v.bounce_mute = true;
        v.range_sel = None;
        v.bounce_audible(false);
        assert_eq!(v.error, None);
        assert_eq!(v.session.tracks.len(), 2);
        assert!(v.session.tracks[0].mute && v.session.tracks[1].is_stereo());
        assert_eq!(v.selected, Some((1, 0)));
        // ... and that bounce to mono.
        v.session.tracks[1].solo = true;
        v.bounce_audible(true);
        assert_eq!(v.error, None);
        assert!(!v.session.tracks[2].is_stereo());
        // The envelope's height and dB map onto each other.
        let r = Rect::from_min_size(Pos2::new(0.0, 100.0), egui::vec2(50.0, 60.0));
        for db in [-48.0, -6.0, 0.0, 12.0] {
            assert!((env_db_at(r, env_y(r, db)) - db).abs() < 0.11, "{db}");
        }
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_stereo_file_imports_as_a_stereo_take() {
        let (mut v, dir) = scratch("import_lr");
        let wav = |name: &str, right: f32| {
            let path = dir.join(name);
            std::fs::create_dir_all(&dir).unwrap();
            let spec = hound::WavSpec {
                channels: 2,
                sample_rate: 48_000,
                bits_per_sample: 32,
                sample_format: hound::SampleFormat::Float,
            };
            let mut w = hound::WavWriter::create(&path, spec).unwrap();
            for i in 0..4800 {
                let l = (i as f32 * 0.02).sin() * 0.5;
                w.write_sample(l).unwrap();
                w.write_sample(if right < 0.0 { l } else { right }).unwrap();
            }
            w.finalize().unwrap();
            path
        };
        let files = vec![wav("wide.wav", 0.1), wav("dual.wav", -1.0)];
        let before = v.session.tracks.len();
        v.import_files(files, ImportDest::NewTracks);
        let ctx = egui::Context::default();
        while v.import.is_some() {
            std::thread::sleep(Duration::from_millis(10));
            v.poll_import(&ctx);
        }
        assert_eq!(v.error, None);
        let t = &v.session.tracks[before..];
        assert_eq!(t.len(), 2);
        let wide = t[0].active_take().unwrap();
        assert!(
            wide.right
                .as_ref()
                .is_some_and(|r| r.iter().all(|&x| x == 0.1))
        );
        assert!(wide.overview.is_stereo());
        let dual = t[1].active_take().unwrap();
        assert!(dual.right.is_none() && !dual.overview.is_stereo());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_chain_change_prints_nothing_until_asked() {
        let (mut v, dir) = scratch("prints");
        let ctx = egui::Context::default();
        let tone: Vec<f32> = (0..24_000).map(|i| (i as f32 * 0.05).sin() * 0.3).collect();
        v.session
            .add_rendered_take(0, tone, None, 0, json!({"device": "test"}))
            .unwrap();
        v.session.tracks[0].inserts.push(Slot::new("pultec_eqp1a"));
        // A chain added: a lookup in the cache, no print.
        v.poll_prints(&ctx, false);
        assert!(!v.jobs.is_empty() && v.jobs.iter().all(|j| j.lookup));
        wait(&v.jobs);
        v.poll_prints(&ctx, false);
        assert!(v.jobs.is_empty(), "a lookup once per chain");
        assert!(!v.session.print_current(0));
        assert_eq!(v.prints_missing(), vec![0]);
        // A knob turned, bypassed, another added, moved, removed: lookups only.
        for step in 0..5 {
            let ins = &mut v.session.tracks[0].inserts;
            match step {
                0 => ins[0].trim_db = -3.0,
                1 => ins[0].bypass = true,
                2 => {
                    ins[0].bypass = false;
                    ins.push(Slot::new("pultec_eqp1a"));
                }
                3 => ins.swap(0, 1),
                _ => {
                    ins.remove(1);
                }
            }
            v.poll_prints(&ctx, false);
            assert!(v.jobs.iter().all(|j| j.lookup), "step {step}");
            wait(&v.jobs);
            v.poll_prints(&ctx, false);
        }
        // Asked: one print.
        v.request_print(0);
        assert!(v.printing(0) && v.prints_missing().is_empty());
        v.poll_prints(&ctx, false);
        let prints: Vec<&PrintJob> = v.jobs.iter().filter(|j| !j.lookup).collect();
        assert_eq!(prints.len(), 1);
        for j in &v.jobs {
            j.job.cancel();
        }
        wait(&v.jobs);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_master_prints_the_stereo_sum_once_its_tracks_are_printed() {
        let (mut v, dir) = scratch("master");
        let ctx = egui::Context::default();
        for (t, (f, pan)) in [(0.05f32, -1.0), (0.11, 1.0)].into_iter().enumerate() {
            if t > 0 {
                v.session.tracks.push(Track::new("2"));
            }
            let tone: Vec<f32> = (0..12_000).map(|i| (i as f32 * f).sin() * 0.3).collect();
            v.session
                .add_rendered_take(t, tone, None, 0, json!({"device": "test"}))
                .unwrap();
            v.session.tracks[t].pan = pan;
        }
        v.session.master_inserts.push(Slot::new("pultec_eqp1a"));
        // Added: a lookup in the cache, no print.
        v.poll_prints(&ctx, false);
        assert!(v.jobs.iter().any(|j| j.master) && v.jobs.iter().all(|j| j.lookup));
        wait(&v.jobs);
        v.poll_prints(&ctx, false);
        assert!(v.jobs.is_empty() && !v.session.master_print_current());
        // A track's chain not printed: asked, the master waits for it.
        v.session.tracks[1].inserts.push(Slot::new("pultec_eqp1a"));
        v.request_master_print();
        assert!(v.master_printing());
        v.poll_prints(&ctx, false);
        assert!(v.printing(1));
        assert!(!v.jobs.iter().any(|j| j.master && !j.lookup));
        for _ in 0..200 {
            wait(&v.jobs);
            v.poll_prints(&ctx, false);
            if v.session.master_print_current() {
                break;
            }
        }
        assert!(v.session.print_current(1) && v.session.master_print_current());
        // The mix plays the print: each side through its own copy of the device.
        let p = v.session.master_print_playing().expect("the print plays");
        let r = p.right.as_ref().expect("stereo");
        assert_ne!(p.audio, *r);
        assert_eq!(v.session.mix().clips.len(), 1);
        assert!(v.session.export_problems(false).is_empty());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn an_edit_renders_nothing_until_asked_and_plays_the_proxy() {
        let (mut v, dir) = scratch("renders");
        let ctx = egui::Context::default();
        let perf = Performance {
            device: "tube_synth".into(),
            quality: Quality::Draft2x,
            rate: 48_000,
            values: Vec::new(),
            playing: Playing::default(),
            gain: 1.0,
            noise: false,
            start_note: 57,
            start_low: false,
            events: vec![
                (
                    4_800,
                    Ev::On {
                        note: 60,
                        velocity: 100,
                    },
                ),
                (24_000, Ev::Off { note: 60 }),
            ],
            knobs: Vec::new(),
            knobs_applied: true,
            end: 48_000,
        };
        let rec = Recorded {
            start: 0,
            latency: 0,
            samples: vec![0.0; 48_000],
            right: None,
            performance: Some((Arc::new(perf), 0)),
        };
        v.session
            .add_take_heard(0, rec, "tube_synth", Monitor::Device)
            .unwrap();
        let k = v.session.tracks[0].active_take().unwrap();
        let mut notes = k.events.as_ref().unwrap().perf.notes();
        notes[0].note = 64;
        let edited = k.events.as_ref().unwrap().perf.edited(&notes, None);
        v.session.revise(0, 0, edited).unwrap();
        // The edit: lookups only, and the proxy's stand-in plays.
        for _ in 0..200 {
            v.poll_take_renders(&ctx, false, false);
            if v.proxy_jobs.is_empty() && v.session.tracks[0].takes[0].has_proxy() {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        assert!(v.take_jobs.iter().all(|j| !j.wanted));
        let k = &v.session.tracks[0].takes[0];
        assert_eq!(k.sound(false).2, varimu_app::session::Plays::Proxy);
        let peak = k.sound(false).0.iter().fold(0.0f32, |m, x| m.max(x.abs()));
        assert!(peak > 1e-3, "the stand-in sounds ({peak})");
        assert_eq!(v.renders_missing(), vec![(0, 0)]);
        // Asked: one render, at the quality it was played at.
        v.request_render(0, 0, false);
        assert!(v.renders_missing().is_empty());
        v.poll_take_renders(&ctx, false, false);
        let wanted: Vec<&TakeJob> = v.take_jobs.iter().filter(|j| j.wanted).collect();
        assert_eq!(wanted.len(), 1);
        assert_eq!((wanted[0].rev, wanted[0].quality), (1, Quality::Draft2x));
        // Not while recording: a second request waits in the queue.
        v.request_render(0, 0, true);
        v.poll_take_renders(&ctx, true, false);
        assert_eq!(v.render_queue.len(), 1);
        for j in &v.take_jobs {
            j.job.cancel();
        }
        let _ = std::fs::remove_dir_all(&dir);
    }
}
