//! The piano roll (docs/MIDI_TAKES_PLAN.md N4): an event take's notes, edited in a pane
//! under the Session view's lanes.
//!
//! Keys down the left, the session's bars and beats across (the take placed where it sits
//! on the timeline), the notes as bars, their velocities in a lane underneath. Notes stay
//! in the performance's samples; the roll shows beats and writes samples.
//!
//! **Tools** (the header's buttons, or 1 / 2 / 3 over the roll):
//! - **Select**: a click selects a note (Shift adds to the selection) and plays it on the
//!   keyboard playing; a drag on a note moves the selection (by the grid; Alt: freely; up and
//!   down by semitones), a drag on a note's right end (its last few pixels, on a note wide
//!   enough to have one: the cursor says so) resizes it, a drag on empty space selects what
//!   it covers, a double-click on empty space draws a note one grid step long.
//! - **Draw**: a click on empty space draws a note one grid step long, a drag draws it as long
//!   as the drag (by the grid); on a note it moves and resizes as Select does.
//! - **Erase**: a click or a drag deletes the notes under it.
//!
//! What a press grabs is decided where the button went down, not where the pointer is once
//! the drag has begun. Right-click deletes the note under the pointer with any tool. In the
//! velocity lane a drag sets the velocity of the note under it (of every selected note, when
//! it is one of them).
//!
//! Keys (over the roll): Delete deletes the selection, ↑ / ↓ transpose it (Shift: an
//! octave), Q quantizes it (none selected: every note) to the grid at the strength, Ctrl+A
//! selects every note. The wheel scrolls the keys, Shift+wheel scrolls in time, Ctrl+wheel
//! zooms.
//!
//! Every gesture is one edit: when it ends the roll hands back the notes, and the Session
//! view saves them as the take's next revision (one undo step; the take renders again
//! behind, `crate::session_view`).

use std::collections::BTreeSet;

use eframe::egui::{self, Color32, Pos2, Rect, RichText, Sense, Stroke, StrokeKind};
use varimu_app::performance::Note;
use varimu_app::transport::Grid;

use crate::theme;

const KEYS_W: f32 = 44.0;
const VEL_H: f32 = 56.0;
/// Grid divisions of a beat on offer.
const DIVISIONS: [(u32, &str); 5] = [
    (1, "1/4"),
    (2, "1/8"),
    (3, "1/8T"),
    (4, "1/16"),
    (8, "1/32"),
];

/// What the mouse does in the roll.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tool {
    Select,
    Draw,
    Erase,
}

/// A note's right end: this many pixels (on a note at least `EDGE_MIN_W` wide) resize it.
const EDGE_PX: f32 = 5.0;
const EDGE_MIN_W: f32 = 14.0;

/// What a gesture in progress does.
#[derive(Debug, Clone)]
enum Gesture {
    /// A note being drawn (its index): its end follows the pointer.
    Draw(usize),
    /// Notes under the pointer deleted as it goes.
    Erase,
    /// The selection moved: the notes before, where the press was.
    Move { from: Vec<Note>, press: Pos2 },
    /// A note's end: the notes before, where the press was.
    Resize { from: Vec<Note>, press: Pos2 },
    /// A selection box from a point.
    Band { start: Pos2 },
    /// Velocities set by the pointer in the lane.
    Velocity,
}

/// What the roll asks of the Session view after a frame.
#[derive(Debug, Clone, PartialEq)]
pub enum Out {
    /// The notes edited (a gesture ended): save them as the take's next revision.
    Edited(Vec<Note>),
    /// A note to play (on) or let go.
    Preview(u8, u8, bool),
    Close,
}

/// Where the take is: what maps its samples onto the timeline.
pub struct Place {
    /// The take's notes in the revision it plays, and that revision.
    pub notes: Vec<Note>,
    pub rev: u32,
    /// Its id, its timeline position and the performance's sample of its first sample.
    pub id: String,
    pub position: i64,
    pub from: u64,
    /// Its length (samples from `from`).
    pub len: u64,
    pub grid: Grid,
    pub rate: u32,
    /// The transport's position heard, while it runs.
    pub playhead: Option<i64>,
    pub colour: Color32,
    /// What it plays now, for the header.
    pub status: String,
}

pub struct Roll {
    pub track: usize,
    pub take: String,
    /// The notes as edited (the take's, until a gesture changes them) and their revision.
    notes: Vec<Note>,
    rev: u32,
    selected: BTreeSet<usize>,
    gesture: Option<Gesture>,
    /// The note being heard (a click's preview), let go when the press ends.
    sounding: Option<u8>,
    /// The view: the timeline's left edge (s), px per s, the top key and a key's height.
    view_s: f64,
    px_per_s: f64,
    top_key: f64,
    key_h: f32,
    division: u32,
    /// Quantize strength (0-1).
    strength: f64,
    tool: Tool,
}

impl Roll {
    /// A roll on take `take` of `track`, fitted to it.
    pub fn new(track: usize, place: &Place) -> Roll {
        let mut r = Roll {
            track,
            take: place.id.clone(),
            notes: place.notes.clone(),
            rev: place.rev,
            selected: BTreeSet::new(),
            gesture: None,
            sounding: None,
            view_s: place.position as f64 / place.rate as f64 - 0.25,
            px_per_s: 120.0,
            top_key: 84.0,
            key_h: 12.0,
            division: 4,
            strength: 1.0,
            tool: Tool::Select,
        };
        if let (Some(lo), Some(hi)) = (
            place.notes.iter().map(|n| n.note).min(),
            place.notes.iter().map(|n| n.note).max(),
        ) {
            r.top_key = (hi as f64 + 6.0).min(127.0).max(lo as f64 + 24.0);
        }
        r
    }

    /// Its edit was saved as revision `rev`.
    pub fn saved_as(&mut self, rev: u32) {
        self.rev = rev;
    }

    /// Whether a gesture is in progress (the Session view holds renders and commits).
    pub fn busy(&self) -> bool {
        self.gesture.is_some()
    }

    fn snap(&self, place: &Place, pos: i64) -> i64 {
        snap(place, self.division, pos)
    }

    fn timeline(&self, place: &Place, t: u64) -> i64 {
        timeline(place, t)
    }

    fn sample(&self, place: &Place, pos: i64) -> u64 {
        sample(place, pos)
    }

    /// Show the roll in `ui`; what it asks for.
    pub fn ui(&mut self, ui: &mut egui::Ui, place: &Place) -> Vec<Out> {
        let mut out = Vec::new();
        // The take changed under the roll (undo, redo): show it as it is now.
        if self.gesture.is_none() && place.rev != self.rev {
            self.notes = place.notes.clone();
            self.rev = place.rev;
            self.selected.clear();
        }
        self.header(ui, place, &mut out);
        let full = ui.available_rect_before_wrap();
        let (rect, resp) = ui.allocate_exact_size(full.size(), Sense::click_and_drag());
        let grid_rect = Rect::from_min_max(
            Pos2::new(rect.left() + KEYS_W, rect.top()),
            Pos2::new(rect.right(), rect.bottom() - VEL_H),
        );
        let vel_rect = Rect::from_min_max(
            Pos2::new(rect.left() + KEYS_W, rect.bottom() - VEL_H + 4.0),
            rect.max,
        );
        // Wheel and zoom over the roll.
        if ui.rect_contains_pointer(rect) {
            let (zoom, scroll, shift, pointer) = ui.input(|i| {
                (
                    i.zoom_delta(),
                    i.smooth_scroll_delta,
                    i.modifiers.shift,
                    i.pointer.hover_pos(),
                )
            });
            if zoom != 1.0 {
                let x = pointer.map_or(rect.center().x + KEYS_W / 2.0, |p| p.x)
                    - (rect.left() + KEYS_W);
                let at = self.view_s + x as f64 / self.px_per_s;
                self.px_per_s = (self.px_per_s * zoom as f64).clamp(5.0, 4000.0);
                self.view_s = at - x as f64 / self.px_per_s;
            } else if shift || scroll.x != 0.0 {
                let dx = if shift { scroll.y + scroll.x } else { scroll.x };
                self.view_s -= dx as f64 / self.px_per_s;
            } else if scroll.y != 0.0 {
                self.top_key = (self.top_key + (scroll.y / self.key_h) as f64).clamp(12.0, 127.0);
            }
        }
        let rate = place.rate as f64;
        let (view_s, px_per_s, top_key, key_h) =
            (self.view_s, self.px_per_s, self.top_key, self.key_h);
        let division = self.division;
        let x_of = |pos: i64| grid_rect.left() + ((pos as f64 / rate - view_s) * px_per_s) as f32;
        let pos_of =
            |x: f32| ((((x - grid_rect.left()) as f64) / px_per_s + view_s) * rate).round() as i64;
        let y_of = |key: f64| grid_rect.top() + ((top_key - key) as f32) * key_h;
        let key_of = |y: f32| (top_key - ((y - grid_rect.top()) / key_h) as f64).ceil();
        let note_rect = |n: &Note| {
            let (x0, x1) = (x_of(timeline(place, n.start)), x_of(timeline(place, n.end)));
            Rect::from_min_max(
                Pos2::new(x0, y_of(n.note as f64) + 1.0),
                Pos2::new(x1.max(x0 + 3.0), y_of(n.note as f64) + key_h - 1.0),
            )
        };
        let painter = ui.painter_at(rect);
        painter.rect_filled(rect, 0.0, theme::CANVAS);
        // Keys and rows.
        let (lo_key, hi_key) = (key_of(grid_rect.bottom()).max(0.0), self.top_key.min(127.0));
        let mut k = hi_key.floor();
        while k >= lo_key {
            let y = y_of(k);
            let black = matches!((k as i64).rem_euclid(12), 1 | 3 | 6 | 8 | 10);
            let row = Rect::from_min_max(
                Pos2::new(grid_rect.left(), y),
                Pos2::new(grid_rect.right(), y + key_h),
            );
            if black {
                painter.rect_filled(row, 0.0, theme::BG);
            }
            let key = Rect::from_min_max(
                Pos2::new(rect.left(), y),
                Pos2::new(rect.left() + KEYS_W - 2.0, y + key_h),
            );
            painter.rect_filled(key, 0.0, if black { theme::CHROME } else { theme::CHROME3 });
            if (k as i64).rem_euclid(12) == 0 {
                painter.text(
                    Pos2::new(key.left() + 3.0, key.center().y),
                    egui::Align2::LEFT_CENTER,
                    format!("C{}", k as i64 / 12 - 1),
                    egui::FontId::proportional(9.0),
                    theme::MUTED,
                );
                painter.line_segment(
                    [
                        Pos2::new(grid_rect.left(), y + key_h),
                        Pos2::new(grid_rect.right(), y + key_h),
                    ],
                    Stroke::new(1.0, theme::LINE),
                );
            }
            k -= 1.0;
        }
        // The grid: beats, bars, the take's span.
        let step = step(place, division);
        let (p0, p1) = (pos_of(grid_rect.left()), pos_of(grid_rect.right()));
        let spb = place.grid.samples_per_beat();
        let show_steps = step / rate * self.px_per_s > 6.0;
        let first = ((p0 as f64 - place.grid.beat(0) as f64) / step).floor() as i64;
        let mut i = first;
        loop {
            let pos = (place.grid.beat(0) as f64 + i as f64 * step).round() as i64;
            if pos > p1 {
                break;
            }
            let on_beat = (i as f64 * step / spb).fract().abs() < 1e-9;
            if on_beat || show_steps {
                let beat = (pos as f64 - place.grid.beat(0) as f64) / spb;
                let bar = on_beat && place.grid.is_downbeat(beat.round() as i64);
                let c = if bar {
                    theme::FAINT
                } else if on_beat {
                    theme::LINE
                } else {
                    theme::DOT
                };
                let x = x_of(pos);
                painter.line_segment(
                    [
                        Pos2::new(x, grid_rect.top()),
                        Pos2::new(x, vel_rect.bottom()),
                    ],
                    Stroke::new(1.0, c),
                );
            }
            i += 1;
        }
        let (t0, t1) = (
            x_of(place.position),
            x_of(place.position + place.len as i64),
        );
        painter.rect_filled(
            Rect::from_min_max(
                Pos2::new(t0, grid_rect.top()),
                Pos2::new(t1, grid_rect.bottom()),
            ),
            0.0,
            place.colour.gamma_multiply(0.05),
        );
        for x in [t0, t1] {
            painter.line_segment(
                [
                    Pos2::new(x, grid_rect.top()),
                    Pos2::new(x, vel_rect.bottom()),
                ],
                Stroke::new(1.0, place.colour.gamma_multiply(0.5)),
            );
        }
        painter.line_segment(
            [
                Pos2::new(grid_rect.left(), vel_rect.top() - 2.0),
                Pos2::new(grid_rect.right(), vel_rect.top() - 2.0),
            ],
            Stroke::new(1.0, theme::LINE),
        );
        // Notes and velocities.
        let gp = ui.painter_at(grid_rect);
        let vp = ui.painter_at(vel_rect);
        for (i, n) in self.notes.iter().enumerate() {
            let sel = self.selected.contains(&i);
            let r = note_rect(n);
            let fill = place
                .colour
                .gamma_multiply(0.35 + 0.65 * n.velocity as f32 / 127.0);
            gp.rect_filled(r, 2.0, if sel { theme::INK } else { fill });
            gp.rect_stroke(r, 2.0, Stroke::new(1.0, place.colour), StrokeKind::Inside);
            let x = r.left();
            let h = (vel_rect.height() - 4.0) * n.velocity as f32 / 127.0;
            vp.line_segment(
                [
                    Pos2::new(x + 1.0, vel_rect.bottom()),
                    Pos2::new(x + 1.0, vel_rect.bottom() - h),
                ],
                Stroke::new(3.0, if sel { theme::INK } else { place.colour }),
            );
        }
        if let Some(h) = place.playhead {
            let x = x_of(h);
            if x >= grid_rect.left() {
                painter.line_segment(
                    [
                        Pos2::new(x, grid_rect.top()),
                        Pos2::new(x, vel_rect.bottom()),
                    ],
                    Stroke::new(1.5, theme::INK),
                );
            }
        }
        // The pointer.
        let hit = |p: Pos2, notes: &[Note]| -> Option<(usize, bool)> {
            notes.iter().enumerate().rev().find_map(|(i, n)| {
                let r = note_rect(n);
                r.contains(p)
                    .then(|| (i, r.width() >= EDGE_MIN_W && p.x > r.right() - EDGE_PX))
            })
        };
        let vel_hit = |p: Pos2, notes: &[Note]| -> Option<usize> {
            notes
                .iter()
                .enumerate()
                .filter(|(_, n)| (note_rect(n).left() - p.x).abs() < 5.0)
                .map(|(i, _)| i)
                .next_back()
        };
        let (shift, alt, command) =
            ui.input(|i| (i.modifiers.shift, i.modifiers.alt, i.modifiers.command));
        if let Some(p) = resp.hover_pos()
            && grid_rect.contains(p)
        {
            let icon = match (self.tool, hit(p, &self.notes), &self.gesture) {
                (_, _, Some(Gesture::Move { .. })) => egui::CursorIcon::Grabbing,
                (_, _, Some(Gesture::Resize { .. } | Gesture::Draw(_))) => {
                    egui::CursorIcon::ResizeHorizontal
                }
                (Tool::Erase, _, _) => egui::CursorIcon::NotAllowed,
                (_, Some((_, true)), _) => egui::CursorIcon::ResizeHorizontal,
                (_, Some(_), _) => egui::CursorIcon::Grab,
                (Tool::Draw, None, _) => egui::CursorIcon::Crosshair,
                (Tool::Select, None, _) => egui::CursorIcon::Default,
            };
            ui.ctx().set_cursor_icon(icon);
        }
        // Where the button went down: what a drag grabs (the pointer has moved by the time
        // the drag begins).
        let origin = ui.input(|i| i.pointer.press_origin());
        if resp.drag_started()
            && let Some(p) = origin.or(resp.interact_pointer_pos())
        {
            if vel_rect.contains(p) {
                self.gesture = Some(Gesture::Velocity);
            } else if grid_rect.contains(p) {
                match (self.tool, hit(p, &self.notes)) {
                    (Tool::Erase, _) => {
                        self.selected.clear();
                        self.gesture = Some(Gesture::Erase);
                    }
                    (Tool::Draw, None) => {
                        let start = sample(
                            place,
                            snap(place, division, pos_of(p.x) - (step / 2.0) as i64),
                        );
                        self.notes.push(Note {
                            start,
                            end: start + step.round().max(1.0) as u64,
                            note: key_of(p.y).clamp(0.0, 127.0) as u8,
                            velocity: 100,
                        });
                        let i = self.notes.len() - 1;
                        self.selected = [i].into();
                        self.gesture = Some(Gesture::Draw(i));
                    }
                    (_, Some((i, edge))) => {
                        if !self.selected.contains(&i) {
                            if !shift {
                                self.selected.clear();
                            }
                            self.selected.insert(i);
                        }
                        let from = self.notes.clone();
                        self.gesture = Some(if edge {
                            Gesture::Resize { from, press: p }
                        } else {
                            Gesture::Move { from, press: p }
                        });
                    }
                    (Tool::Select, None) => self.gesture = Some(Gesture::Band { start: p }),
                }
            }
        }
        if resp.dragged()
            && let Some(p) = ui.ctx().pointer_interact_pos()
        {
            match self.gesture.clone() {
                Some(Gesture::Draw(i)) => {
                    let start = self.notes[i].start;
                    let end_pos = snap(place, division, pos_of(p.x));
                    self.notes[i].end =
                        sample(place, end_pos).max(start + step.round().max(1.0) as u64);
                }
                Some(Gesture::Erase) => {
                    if let Some((i, _)) = hit(p, &self.notes) {
                        self.notes.remove(i);
                    }
                }
                Some(Gesture::Move { from, press }) => {
                    let dpos = pos_of(p.x) - pos_of(press.x);
                    let dkey = ((press.y - p.y) / key_h).round() as i64;
                    // The first selected note's start lands on the grid (Alt: anywhere).
                    let lead = self
                        .selected
                        .iter()
                        .next()
                        .map(|&i| from[i].start)
                        .unwrap_or(0);
                    let lead_pos = timeline(place, lead) + dpos;
                    let target = if alt {
                        lead_pos
                    } else {
                        snap(place, division, lead_pos)
                    };
                    let shift_s = target - timeline(place, lead);
                    for &i in &self.selected {
                        let n = from[i];
                        let start = (n.start as i64 + shift_s).max(0) as u64;
                        self.notes[i] = Note {
                            start,
                            end: start + (n.end - n.start),
                            note: (n.note as i64 + dkey).clamp(0, 127) as u8,
                            velocity: n.velocity,
                        };
                    }
                }
                Some(Gesture::Resize { from, press }) => {
                    let dpos = pos_of(p.x) - pos_of(press.x);
                    for &i in &self.selected {
                        let n = from[i];
                        let end_pos = timeline(place, n.end) + dpos;
                        let end_pos = if alt {
                            end_pos
                        } else {
                            snap(place, division, end_pos)
                        };
                        let end = sample(place, end_pos).max(n.start + (step as u64 / 4).max(1));
                        self.notes[i].end = end;
                    }
                }
                Some(Gesture::Velocity) => {
                    let v = ((vel_rect.bottom() - p.y) / (vel_rect.height() - 4.0) * 127.0)
                        .round()
                        .clamp(1.0, 127.0) as u8;
                    if let Some(i) = vel_hit(p, &self.notes) {
                        if self.selected.contains(&i) {
                            for &j in &self.selected {
                                self.notes[j].velocity = v;
                            }
                        } else {
                            self.notes[i].velocity = v;
                        }
                    }
                }
                Some(Gesture::Band { start }) => {
                    let band = Rect::from_two_pos(start, p);
                    gp.rect_stroke(
                        band,
                        0.0,
                        Stroke::new(1.0, theme::ACCENT),
                        StrokeKind::Inside,
                    );
                }
                None => {}
            }
        }
        if resp.drag_stopped() {
            match self.gesture.take() {
                Some(Gesture::Band { start }) => {
                    let band =
                        Rect::from_two_pos(start, ui.ctx().pointer_interact_pos().unwrap_or(start));
                    if !shift {
                        self.selected.clear();
                    }
                    for (i, n) in self.notes.iter().enumerate() {
                        if band.intersects(note_rect(n)) {
                            self.selected.insert(i);
                        }
                    }
                }
                Some(_) => self.edited(&mut out, place),
                None => {}
            }
        }
        // Clicks: select and hear a note; draw one on empty space; delete.
        if resp.clicked()
            && let Some(p) = resp.interact_pointer_pos()
            && grid_rect.contains(p)
        {
            match (self.tool, hit(p, &self.notes)) {
                (Tool::Erase, Some((i, _))) => {
                    self.notes.remove(i);
                    self.selected.clear();
                    self.edited(&mut out, place);
                }
                (Tool::Erase, None) => {}
                (Tool::Draw, None) => {
                    let start = sample(
                        place,
                        snap(place, division, pos_of(p.x) - (step / 2.0) as i64),
                    );
                    let note = key_of(p.y).clamp(0.0, 127.0) as u8;
                    self.notes.push(Note {
                        start,
                        end: start + step.round().max(1.0) as u64,
                        note,
                        velocity: 100,
                    });
                    self.selected = [self.notes.len() - 1].into();
                    out.push(Out::Preview(note, 100, true));
                    self.sounding = Some(note);
                    self.edited(&mut out, place);
                }
                (_, Some((i, _))) => {
                    if !shift {
                        self.selected.clear();
                    }
                    self.selected.insert(i);
                    let n = self.notes[i];
                    out.push(Out::Preview(n.note, n.velocity, true));
                    self.sounding = Some(n.note);
                }
                (Tool::Select, None) if !shift => self.selected.clear(),
                (Tool::Select, None) => {}
            }
        }
        if resp.double_clicked()
            && self.tool == Tool::Select
            && let Some(p) = resp.interact_pointer_pos()
            && grid_rect.contains(p)
            && hit(p, &self.notes).is_none()
        {
            let pos = snap(place, division, pos_of(p.x) - (step / 2.0) as i64);
            let start = sample(place, pos);
            let note = key_of(p.y).clamp(0.0, 127.0) as u8;
            self.notes.push(Note {
                start,
                end: start + step.round().max(1.0) as u64,
                note,
                velocity: 100,
            });
            self.selected.clear();
            self.selected.insert(self.notes.len() - 1);
            self.edited(&mut out, place);
        }
        if resp.secondary_clicked()
            && let Some(p) = resp.interact_pointer_pos()
            && let Some((i, _)) = hit(p, &self.notes)
        {
            self.notes.remove(i);
            self.selected.clear();
            self.edited(&mut out, place);
        }
        if let Some(n) = self.sounding
            && !ui.input(|i| i.pointer.any_down())
        {
            out.push(Out::Preview(n, 0, false));
            self.sounding = None;
        }
        // Keys over the roll.
        if ui.rect_contains_pointer(rect) && !ui.ctx().egui_wants_keyboard_input() {
            let (del, up, down, q, all) = ui.input(|i| {
                (
                    i.key_pressed(egui::Key::Delete) || i.key_pressed(egui::Key::Backspace),
                    i.key_pressed(egui::Key::ArrowUp),
                    i.key_pressed(egui::Key::ArrowDown),
                    i.key_pressed(egui::Key::Q),
                    command && i.key_pressed(egui::Key::A),
                )
            });
            if all {
                self.selected = (0..self.notes.len()).collect();
            }
            let tool = ui.input(|i| {
                [
                    (egui::Key::Num1, Tool::Select),
                    (egui::Key::Num2, Tool::Draw),
                    (egui::Key::Num3, Tool::Erase),
                ]
                .into_iter()
                .find(|(k, _)| i.key_pressed(*k))
                .map(|(_, t)| t)
            });
            if let Some(t) = tool {
                self.tool = t;
            }
            if del && !self.selected.is_empty() {
                let keep: Vec<Note> = self
                    .notes
                    .iter()
                    .enumerate()
                    .filter(|(i, _)| !self.selected.contains(i))
                    .map(|(_, n)| *n)
                    .collect();
                self.notes = keep;
                self.selected.clear();
                self.edited(&mut out, place);
            }
            if (up || down) && !self.selected.is_empty() {
                let d: i64 = if shift { 12 } else { 1 } * if up { 1 } else { -1 };
                for &i in &self.selected {
                    self.notes[i].note = (self.notes[i].note as i64 + d).clamp(0, 127) as u8;
                }
                self.edited(&mut out, place);
            }
            if q {
                self.quantize(place);
                self.edited(&mut out, place);
            }
        }
        out
    }

    /// The selection (or every note) quantized to the grid at the strength: each start moved
    /// that share of the way to its nearest grid line, its length kept.
    fn quantize(&mut self, place: &Place) {
        let which: Vec<usize> = if self.selected.is_empty() {
            (0..self.notes.len()).collect()
        } else {
            self.selected.iter().copied().collect()
        };
        for i in which {
            let n = self.notes[i];
            let pos = self.timeline(place, n.start);
            let target = self.snap(place, pos);
            let moved = pos + ((target - pos) as f64 * self.strength).round() as i64;
            let start = self.sample(place, moved);
            self.notes[i] = Note {
                start,
                end: start + (n.end - n.start),
                ..n
            };
        }
    }

    fn edited(&mut self, out: &mut Vec<Out>, place: &Place) {
        if self.notes != place.notes {
            out.push(Out::Edited(self.notes.clone()));
        }
    }

    fn header(&mut self, ui: &mut egui::Ui, place: &Place, out: &mut Vec<Out>) {
        ui.horizontal(|ui| {
            ui.label(
                RichText::new(format!(
                    "PIANO ROLL · {} · revision {}",
                    place.id, place.rev
                ))
                .small()
                .strong()
                .color(theme::INK),
            );
            ui.label(RichText::new(&place.status).small().color(theme::MUTED));
            ui.add_space(14.0);
            for (t, label, tip) in [
                (Tool::Select, "↖ Select", "1: select, move (drag a note), resize (drag its right end), box-select (drag on empty space)"),
                (Tool::Draw, "✎ Draw", "2: click to draw a note one grid step long, drag to draw it longer"),
                (Tool::Erase, "⌫ Erase", "3: click or drag over notes to delete them"),
            ] {
                if ui
                    .selectable_label(self.tool == t, RichText::new(label).small())
                    .on_hover_text(tip)
                    .clicked()
                {
                    self.tool = t;
                }
            }
            ui.add_space(10.0);
            ui.label(RichText::new("grid").small().color(theme::MUTED));
            let label = DIVISIONS
                .iter()
                .find(|(d, _)| *d == self.division)
                .map_or("?", |(_, l)| l);
            egui::ComboBox::from_id_salt("roll_grid")
                .width(60.0)
                .selected_text(label)
                .show_ui(ui, |ui| {
                    for (d, l) in DIVISIONS {
                        ui.selectable_value(&mut self.division, d, l);
                    }
                });
            ui.label(RichText::new("strength").small().color(theme::MUTED));
            ui.add(
                egui::DragValue::new(&mut self.strength)
                    .range(0.0..=1.0)
                    .speed(0.01)
                    .custom_formatter(|v, _| format!("{:.0}%", v * 100.0))
                    .custom_parser(|t| {
                        t.trim_end_matches('%')
                            .trim()
                            .parse::<f64>()
                            .ok()
                            .map(|v| v / 100.0)
                    }),
            );
            if ui
                .small_button("Quantize")
                .on_hover_text(
                    "Q: the selection (none selected: every note) to the grid, at the strength",
                )
                .clicked()
            {
                self.quantize(place);
                self.edited(out, place);
            }
            ui.label(
                RichText::new(format!(
                    "{} notes · {} selected",
                    self.notes.len(),
                    self.selected.len()
                ))
                .small()
                .color(theme::FAINT),
            );
            ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                if ui
                    .small_button("✕")
                    .on_hover_text("Close the piano roll")
                    .clicked()
                {
                    out.push(Out::Close);
                }
                if ui
                    .small_button("Fit")
                    .on_hover_text("The take in view")
                    .clicked()
                {
                    let len_s = place.len as f64 / place.rate as f64;
                    self.view_s = place.position as f64 / place.rate as f64 - 0.1 * len_s.max(0.5);
                    self.px_per_s = (900.0 / (len_s * 1.2).max(0.5)).clamp(5.0, 4000.0);
                }
            });
        });
        ui.add_space(2.0);
    }
}

/// The timeline position of the performance's sample `t`.
fn timeline(place: &Place, t: u64) -> i64 {
    place.position + t as i64 - place.from as i64
}

/// The performance's sample at timeline position `pos` (none before its start).
fn sample(place: &Place, pos: i64) -> u64 {
    (pos - place.position + place.from as i64).max(0) as u64
}

/// The grid step (samples) at `division` steps a beat.
fn step(place: &Place, division: u32) -> f64 {
    place.grid.samples_per_beat() / division as f64
}

/// `pos` on the nearest grid line.
fn snap(place: &Place, division: u32, pos: i64) -> i64 {
    let (o, step) = (place.grid.beat(0) as f64, step(place, division));
    (o + ((pos as f64 - o) / step).round() * step).round() as i64
}

#[cfg(test)]
mod tests {
    use super::*;
    use varimu_app::transport::TransportSettings;

    fn place(notes: Vec<Note>) -> Place {
        Place {
            notes,
            rev: 0,
            id: "t0001".into(),
            position: 1_000,
            from: 500,
            len: 96_000,
            grid: Grid::new(48_000, &TransportSettings::default()),
            rate: 48_000,
            playhead: None,
            colour: Color32::WHITE,
            status: String::new(),
        }
    }

    #[test]
    fn a_quantize_lands_every_note_on_its_grid_sample() {
        let notes = vec![
            Note {
                start: 7_777,
                end: 9_000,
                note: 60,
                velocity: 90,
            },
            Note {
                start: 20_111,
                end: 30_000,
                note: 62,
                velocity: 90,
            },
        ];
        let p = place(notes.clone());
        let mut r = Roll::new(0, &p);
        r.quantize(&p);
        let step = step(&p, r.division);
        for (n, before) in r.notes.iter().zip(&notes) {
            let pos = r.timeline(&p, n.start) as f64;
            let k = (pos - p.grid.beat(0) as f64) / step;
            assert!((k - k.round()).abs() * step < 0.51, "{pos} is on the grid");
            assert_eq!(n.end - n.start, before.end - before.start);
        }
        // At half strength, half way there.
        let mut r = Roll::new(0, &p);
        r.strength = 0.5;
        r.quantize(&p);
        let full = r.snap(&p, r.timeline(&p, notes[0].start));
        let half = r.timeline(&p, r.notes[0].start);
        let start = r.timeline(&p, notes[0].start);
        assert!((half - (start + (full - start) / 2)).abs() <= 1);
    }
}
