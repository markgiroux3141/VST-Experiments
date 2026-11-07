//! The mixer's widgets (docs/SESSION_EDITING_PLAN.md SE4): a fader with a console's law,
//! a pan knob, stereo meters with peak hold and RMS, and the meters' state as the window
//! keeps it between frames. The Session view lays them out (`session_view`'s Mixer tab
//! and the arrangement's strips); the player measures the levels
//! (`varimu_app::player::Player::take_meters`), these only draw them.

use std::time::{Duration, Instant};

use eframe::egui::{self, Color32, Pos2, Rect, Sense, Stroke, StrokeKind};
use varimu_app::session::{Meters, to_dbfs};

use crate::theme;

/// The fader's range (dB): its bottom is off (−∞ in the mix: the law's floor plays at
/// −60 dB, as the strips' drag values always did).
pub const FADER_MIN_DB: f64 = -60.0;
pub const FADER_MAX_DB: f64 = 12.0;

/// The fader's law: dB at points of its travel (0 bottom, 1 top), linear in dB between
/// them, most of the travel between −30 and +6 dB as a console's.
const LAW: [(f64, f64); 6] = [
    (0.0, -60.0),
    (0.12, -30.0),
    (0.45, -10.0),
    (0.70, 0.0),
    (0.87, 6.0),
    (1.0, 12.0),
];

/// The fader's position (0-1) for `db`.
pub fn fader_pos(db: f64) -> f64 {
    let db = db.clamp(FADER_MIN_DB, FADER_MAX_DB);
    for w in LAW.windows(2) {
        let ((x0, d0), (x1, d1)) = (w[0], w[1]);
        if db <= d1 {
            return x0 + (x1 - x0) * (db - d0) / (d1 - d0);
        }
    }
    1.0
}

/// The dB at the fader's position `x` (0-1).
pub fn fader_db(x: f64) -> f64 {
    let x = x.clamp(0.0, 1.0);
    for w in LAW.windows(2) {
        let ((x0, d0), (x1, d1)) = (w[0], w[1]);
        if x <= x1 {
            return d0 + (d1 - d0) * (x - x0) / (x1 - x0);
        }
    }
    FADER_MAX_DB
}

/// How a meter's bar falls (dB/s) and how long its peak holds.
const FALL_DB_PER_S: f64 = 24.0;
const HOLD: Duration = Duration::from_millis(1500);
/// The meter's floor (dBFS).
pub const METER_FLOOR_DB: f64 = -60.0;

/// One stereo meter as shown: the bar (peak, falling), the held peak, the RMS, a clip.
#[derive(Debug, Clone)]
pub struct MeterState {
    pub peak_db: [f64; 2],
    pub hold_db: [f64; 2],
    hold_at: [Instant; 2],
    pub rms_db: [f64; 2],
    /// A sample above full scale since the light was last cleared.
    pub clipped: bool,
}

impl Default for MeterState {
    fn default() -> MeterState {
        let now = Instant::now();
        MeterState {
            peak_db: [METER_FLOOR_DB; 2],
            hold_db: [METER_FLOOR_DB; 2],
            hold_at: [now; 2],
            rms_db: [METER_FLOOR_DB; 2],
            clipped: false,
        }
    }
}

impl MeterState {
    /// A reading (peak and sum of squares per side over `frames`) `dt` after the last.
    pub fn update(&mut self, m: Option<&[f32; 4]>, frames: usize, dt: f64) {
        let now = Instant::now();
        let fall = FALL_DB_PER_S * dt;
        for s in 0..2 {
            let (peak, rms) = match m {
                Some(m) if frames > 0 => {
                    (to_dbfs(m[s]), to_dbfs((m[2 + s] / frames as f32).sqrt()))
                }
                _ => (METER_FLOOR_DB - 1.0, METER_FLOOR_DB - 1.0),
            };
            if m.is_some_and(|m| m[s] > 1.0) {
                self.clipped = true;
            }
            self.peak_db[s] = peak.max(self.peak_db[s] - fall).max(METER_FLOOR_DB);
            // RMS: a short smoothing (about 300 ms), so it reads as loudness.
            let a = (dt / 0.3).min(1.0);
            let r = rms.max(METER_FLOOR_DB);
            self.rms_db[s] = if r > self.rms_db[s] {
                r
            } else {
                self.rms_db[s] + (r - self.rms_db[s]) * a
            };
            if peak >= self.hold_db[s] || now.duration_since(self.hold_at[s]) > HOLD {
                self.hold_db[s] = peak.max(METER_FLOOR_DB);
                self.hold_at[s] = now;
            }
        }
    }
}

/// The meters of a session's tracks and master, updated from the player's readings.
#[derive(Debug, Clone, Default)]
pub struct MeterBank {
    pub tracks: Vec<MeterState>,
    pub master: MeterState,
    last: Option<Instant>,
}

impl MeterBank {
    /// A reading for `n` tracks (none: they fall).
    pub fn update(&mut self, m: Option<&Meters>, n: usize) {
        let now = Instant::now();
        let dt = self
            .last
            .map_or(0.0, |t| now.duration_since(t).as_secs_f64())
            .min(0.5);
        self.last = Some(now);
        self.tracks.resize_with(n, MeterState::default);
        let frames = m.map_or(0, |m| m.frames);
        for (i, t) in self.tracks.iter_mut().enumerate() {
            let r = m.and_then(|m| m.tracks.get(i));
            // A track the reading has no entry for is silent this frame.
            let silent = [0.0f32; 4];
            t.update(Some(r.unwrap_or(&silent)), frames.max(1), dt);
        }
        let silent = [0.0f32; 4];
        self.master
            .update(Some(m.map_or(&silent, |m| &m.master)), frames.max(1), dt);
    }
}

fn level_y(rect: Rect, db: f64) -> f32 {
    let x = fader_pos(db.clamp(METER_FLOOR_DB, FADER_MAX_DB));
    rect.bottom() - rect.height() * x as f32
}

/// A meter's colour at `db`: green, amber near the top, red over.
fn meter_colour(db: f64) -> Color32 {
    if db > 0.0 {
        theme::FAULT
    } else if db > -6.0 {
        theme::WARN
    } else {
        theme::OK
    }
}

/// A vertical stereo meter in `rect` (on the fader's scale): bars falling from the peak,
/// a hold line, the RMS as a brighter inner bar.
pub fn draw_meter(painter: &egui::Painter, rect: Rect, m: &MeterState) {
    painter.rect_filled(rect, 2.0, theme::BG);
    let w = (rect.width() - 1.0) / 2.0;
    for s in 0..2 {
        let col = Rect::from_min_size(
            Pos2::new(rect.left() + s as f32 * (w + 1.0), rect.top()),
            egui::vec2(w, rect.height()),
        );
        let peak = m.peak_db[s];
        if peak > METER_FLOOR_DB {
            let bar = Rect::from_min_max(Pos2::new(col.left(), level_y(col, peak)), col.max);
            painter.rect_filled(bar, 0.0, meter_colour(peak).gamma_multiply(0.45));
        }
        let rms = m.rms_db[s];
        if rms > METER_FLOOR_DB {
            let bar = Rect::from_min_max(
                Pos2::new(col.left() + w * 0.2, level_y(col, rms)),
                Pos2::new(col.right() - w * 0.2, col.bottom()),
            );
            painter.rect_filled(bar, 0.0, meter_colour(rms));
        }
        if m.hold_db[s] > METER_FLOOR_DB {
            let y = level_y(col, m.hold_db[s]);
            painter.line_segment(
                [Pos2::new(col.left(), y), Pos2::new(col.right(), y)],
                Stroke::new(1.5, meter_colour(m.hold_db[s])),
            );
        }
    }
    // 0 dBFS.
    let y = level_y(rect, 0.0);
    painter.line_segment(
        [Pos2::new(rect.left(), y), Pos2::new(rect.right(), y)],
        Stroke::new(1.0, theme::FAINT),
    );
}

/// A horizontal meter (the arrangement's strip: behind its fader), peak and RMS.
pub fn draw_meter_h(painter: &egui::Painter, rect: Rect, m: &MeterState) {
    let x_of = |db: f64| rect.left() + rect.width() * fader_pos(db) as f32;
    for s in 0..2 {
        let h = rect.height() / 2.0;
        let row = Rect::from_min_size(
            Pos2::new(rect.left(), rect.top() + s as f32 * h),
            egui::vec2(rect.width(), h),
        );
        let peak = m.peak_db[s];
        if peak > METER_FLOOR_DB {
            let bar = Rect::from_min_max(row.min, Pos2::new(x_of(peak), row.bottom()));
            painter.rect_filled(bar, 0.0, meter_colour(peak).gamma_multiply(0.35));
        }
        let rms = m.rms_db[s];
        if rms > METER_FLOOR_DB {
            let bar = Rect::from_min_max(
                Pos2::new(row.left(), row.top() + h * 0.25),
                Pos2::new(x_of(rms), row.bottom() - h * 0.25),
            );
            painter.rect_filled(bar, 0.0, meter_colour(rms).gamma_multiply(0.8));
        }
    }
}

/// A fader (vertical, or horizontal) on `db` through the law: drag it, Ctrl+click for
/// 0 dB, the wheel nudges by 0.5 dB. Returns whether it changed.
pub fn fader(
    ui: &mut egui::Ui,
    db: &mut f64,
    size: egui::Vec2,
    vertical: bool,
    id: egui::Id,
) -> bool {
    let (rect, _) = ui.allocate_exact_size(size, Sense::hover());
    let resp = ui.interact(rect, id, Sense::click_and_drag());
    let before = *db;
    let ctrl = ui.input(|i| i.modifiers.command);
    if resp.clicked() && ctrl {
        *db = 0.0;
    } else if (resp.dragged() || resp.drag_started())
        && let Some(p) = resp.interact_pointer_pos()
    {
        let x = if vertical {
            (rect.bottom() - p.y) / rect.height()
        } else {
            (p.x - rect.left()) / rect.width()
        };
        *db = (fader_db(x as f64) * 10.0).round() / 10.0;
    }
    if resp.hovered() {
        let wheel = ui.input(|i| i.smooth_scroll_delta.y);
        if wheel != 0.0 {
            *db = (*db + 0.5 * wheel.signum() as f64).clamp(FADER_MIN_DB, FADER_MAX_DB);
        }
    }
    let p = ui.painter_at(rect.expand(2.0));
    let x = fader_pos(*db) as f32;
    let hot = resp.hovered() || resp.dragged();
    if vertical {
        let slot = Rect::from_center_size(rect.center(), egui::vec2(4.0, rect.height()));
        p.rect_filled(slot, 2.0, theme::BG);
        // Ticks at the law's points.
        for (_, d) in LAW {
            let y = rect.bottom() - rect.height() * fader_pos(d) as f32;
            p.line_segment(
                [Pos2::new(rect.left(), y), Pos2::new(rect.left() + 5.0, y)],
                Stroke::new(1.0, if d == 0.0 { theme::MUTED } else { theme::DOT }),
            );
        }
        let y = rect.bottom() - rect.height() * x;
        let cap = Rect::from_center_size(
            Pos2::new(rect.center().x, y),
            egui::vec2(rect.width() - 4.0, 12.0),
        );
        p.rect_filled(cap, 2.0, if hot { theme::CHROME3 } else { theme::CHROME2 });
        p.rect_stroke(cap, 2.0, Stroke::new(1.0, theme::LINE), StrokeKind::Inside);
        p.line_segment(
            [
                Pos2::new(cap.left() + 2.0, y),
                Pos2::new(cap.right() - 2.0, y),
            ],
            Stroke::new(1.5, theme::INK),
        );
    } else {
        let xx = rect.left() + rect.width() * x;
        p.line_segment(
            [Pos2::new(xx, rect.top()), Pos2::new(xx, rect.bottom())],
            Stroke::new(if hot { 3.0 } else { 2.0 }, theme::INK),
        );
        let x0 = rect.left() + rect.width() * fader_pos(0.0) as f32;
        p.line_segment(
            [
                Pos2::new(x0, rect.bottom() - 3.0),
                Pos2::new(x0, rect.bottom()),
            ],
            Stroke::new(1.0, theme::MUTED),
        );
        p.rect_stroke(rect, 2.0, Stroke::new(1.0, theme::LINE), StrokeKind::Inside);
    }
    let resp = resp.on_hover_text(format!("{:+.1} dB · drag, wheel; Ctrl+click: 0 dB", *db));
    let _ = resp;
    *db != before
}

/// A pan knob on `pan` (−1 left .. 1 right): drag up / right to turn right, Ctrl+click or
/// a double-click centres it. Returns whether it changed.
pub fn pan_knob(ui: &mut egui::Ui, pan: &mut f64, size: f32, id: egui::Id) -> bool {
    let (rect, _) = ui.allocate_exact_size(egui::vec2(size, size), Sense::hover());
    let resp = ui.interact(rect, id, Sense::click_and_drag());
    let before = *pan;
    let ctrl = ui.input(|i| i.modifiers.command);
    if resp.double_clicked() || (resp.clicked() && ctrl) {
        *pan = 0.0;
    } else if resp.dragged() {
        let d = resp.drag_delta();
        *pan = (*pan + (d.x - d.y) as f64 / 120.0).clamp(-1.0, 1.0);
        if pan.abs() < 0.01 {
            *pan = 0.0;
        }
    }
    let p = ui.painter_at(rect.expand(1.0));
    let c = rect.center();
    let r = size * 0.42;
    p.circle_filled(c, r, theme::CHROME2);
    p.circle_stroke(c, r, Stroke::new(1.0, theme::LINE));
    // −135° (left) .. +135° (right), 0 up.
    let a = (*pan as f32) * 135f32.to_radians();
    let tip = Pos2::new(c.x + r * a.sin(), c.y - r * a.cos());
    p.line_segment([c, tip], Stroke::new(2.0, theme::ACCENT));
    let _ = resp.on_hover_text(format!(
        "pan {} · drag; double-click: centre",
        pan_label(*pan)
    ));
    *pan != before
}

/// A pan as a console marks it: C, L40, R100.
pub fn pan_label(v: f64) -> String {
    match v {
        v if v.abs() < 0.005 => "C".into(),
        v if v < 0.0 => format!("L{:.0}", -v * 100.0),
        v => format!("R{:.0}", v * 100.0),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_fader_law_round_trips_and_spends_its_travel_where_mixing_happens() {
        for db in [-60.0, -45.0, -30.0, -12.0, -3.0, 0.0, 4.5, 12.0] {
            assert!((fader_db(fader_pos(db)) - db).abs() < 1e-9, "{db}");
        }
        assert!(fader_pos(6.0) - fader_pos(-30.0) >= 0.7);
        assert_eq!(fader_pos(-200.0), 0.0);
        assert_eq!(fader_db(2.0), FADER_MAX_DB);
    }

    #[test]
    fn a_meter_reads_a_sine_peak_and_rms_and_falls_after() {
        // A sine of amplitude 0.5 (-6 dBFS peak, its rms 3 dB under).
        let n = 4800;
        let x: Vec<f32> = (0..n).map(|i| 0.5 * (i as f32 * 0.1).sin()).collect();
        let peak = x.iter().fold(0.0f32, |m, v| m.max(v.abs()));
        let sq: f32 = x.iter().map(|v| v * v).sum();
        let mut m = MeterState::default();
        m.update(Some(&[peak, peak, sq, sq]), n, 0.03);
        assert!((m.peak_db[0] - -6.02).abs() < 0.05, "{}", m.peak_db[0]);
        assert!((m.rms_db[0] - -9.03).abs() < 0.1, "{}", m.rms_db[0]);
        assert!(!m.clipped);
        // Silence: the bar falls at its rate, the hold stays.
        m.update(Some(&[0.0; 4]), n, 0.5);
        assert!((m.peak_db[0] - (-6.02 - 12.0)).abs() < 0.1);
        assert!((m.hold_db[0] - -6.02).abs() < 0.05);
        m.update(Some(&[1.5, 0.0, 2.25, 0.0]), 1, 0.03);
        assert!(m.clipped);
    }
}
