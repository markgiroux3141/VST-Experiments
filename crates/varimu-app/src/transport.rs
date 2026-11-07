//! The session's transport and click (docs/RECORDING_PLAN.md, T1).
//!
//! **One clock.** The session position counts the samples the player's worker computes
//! at the host rate; 0 is bar 1, beat 1. Beat `k` starts at `round(k * 60 * rate / bpm)`,
//! computed from `k` each time (never accumulated), so the grid can't drift from the
//! sample count however long the transport runs.
//!
//! **The click** is made in the worker and mixed into the output after the device and the
//! monitor (bypass, gain compensation): it never goes through a device and never into a
//! take. Each click starts exactly on its beat's sample: a sine (2 kHz on the downbeat,
//! 1.25 kHz on the other beats) under a smooth envelope (0.5 ms raised-cosine attack, a
//! 5 ms decay, faded out by 30 ms), so it is band-limited and has no step at its start.
//! It is a function of continuous time ([`click_wave`]): the loopback analysis samples
//! the same click at the capture's rate (`crate::loopback`).
//!
//! **Starting.** Play starts at the cursor (a timeline sample, docs/SESSION_EDITING_PLAN.md
//! SE2), after `pre_roll_bars` (the timeline plays, recording waits) and before them
//! `count_in_bars` (click only), counted back in bars from the bar the cursor is in: a
//! start runs from `bar(b - pre_roll - count_in)` (b: the cursor's bar), the timeline plays
//! from bar b's start and a take records from the cursor itself. Without count-in or
//! pre-roll, play starts at the cursor. Positions in the count-in can be negative. Stop
//! keeps the position; the next play starts from the cursor again.
//!
//! **Locators and the loop.** The left and right locators are beats. With the loop on,
//! play starts at the left locator (after the count-in; no pre-roll) and, on reaching the
//! right one, goes on from the left one within the block: [`Clock::segments`] says which
//! positions a block's samples have (one stretch, or two across the jump), and the click,
//! the tracks and the recorder follow it. A loop on while the position is past its end
//! jumps back at the next block.

use std::f64::consts::PI;

/// The click's length (s).
pub const CLICK_S: f64 = 0.030;
const ATTACK_S: f64 = 0.0005;
const DECAY_S: f64 = 0.005;
const FADE_S: f64 = 0.003;
/// The click's pitch on the downbeat and on the other beats (Hz).
pub const ACCENT_HZ: f64 = 2000.0;
pub const BEAT_HZ: f64 = 1250.0;

/// The click at `t_s` seconds from its start (0 outside it), peak about 1.
pub fn click_wave(t_s: f64, accent: bool) -> f64 {
    if !(0.0..CLICK_S).contains(&t_s) {
        return 0.0;
    }
    let attack = if t_s < ATTACK_S {
        0.5 - 0.5 * (PI * t_s / ATTACK_S).cos()
    } else {
        1.0
    };
    let left = CLICK_S - t_s;
    let fade = if left < FADE_S {
        0.5 - 0.5 * (PI * left / FADE_S).cos()
    } else {
        1.0
    };
    let decay = (-(t_s - ATTACK_S).max(0.0) / DECAY_S).exp();
    let hz = if accent { ACCENT_HZ } else { BEAT_HZ };
    attack * decay * fade * (2.0 * PI * hz * t_s).sin()
}

/// The click sampled at `rate`, its first sample at its start.
pub fn click_table(rate: u32, accent: bool) -> Vec<f32> {
    let n = (CLICK_S * rate as f64).ceil() as usize;
    (0..n)
        .map(|i| click_wave(i as f64 / rate as f64, accent) as f32)
        .collect()
}

/// When the click sounds while the transport runs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ClickMode {
    Off,
    /// During the count-in only.
    CountIn,
    On,
}

impl ClickMode {
    pub const ALL: [ClickMode; 3] = [ClickMode::Off, ClickMode::CountIn, ClickMode::On];

    pub fn label(self) -> &'static str {
        match self {
            ClickMode::Off => "off",
            ClickMode::CountIn => "count-in only",
            ClickMode::On => "on",
        }
    }

    pub fn id(self) -> &'static str {
        match self {
            ClickMode::Off => "off",
            ClickMode::CountIn => "count_in",
            ClickMode::On => "on",
        }
    }

    pub fn from_id(s: &str) -> Option<ClickMode> {
        ClickMode::ALL.into_iter().find(|m| m.id() == s)
    }
}

/// What the arrangement's gestures snap to (SE2): a bar, a beat, a division of it, or
/// nothing (free).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Snap {
    Bar,
    Beat,
    Eighth,
    EighthTriplet,
    Sixteenth,
    ThirtySecond,
    Off,
}

impl Snap {
    pub const ALL: [Snap; 7] = [
        Snap::Bar,
        Snap::Beat,
        Snap::Eighth,
        Snap::EighthTriplet,
        Snap::Sixteenth,
        Snap::ThirtySecond,
        Snap::Off,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Snap::Bar => "Bar",
            Snap::Beat => "Beat",
            Snap::Eighth => "1/8",
            Snap::EighthTriplet => "1/8T",
            Snap::Sixteenth => "1/16",
            Snap::ThirtySecond => "1/32",
            Snap::Off => "Off",
        }
    }

    pub fn id(self) -> &'static str {
        match self {
            Snap::Bar => "bar",
            Snap::Beat => "beat",
            Snap::Eighth => "1/8",
            Snap::EighthTriplet => "1/8t",
            Snap::Sixteenth => "1/16",
            Snap::ThirtySecond => "1/32",
            Snap::Off => "off",
        }
    }

    pub fn from_id(s: &str) -> Option<Snap> {
        Snap::ALL.into_iter().find(|m| m.id() == s)
    }

    /// Steps per beat (a bar: none, it's per bar; off: none).
    pub fn per_beat(self) -> Option<u32> {
        match self {
            Snap::Beat => Some(1),
            Snap::Eighth => Some(2),
            Snap::EighthTriplet => Some(3),
            Snap::Sixteenth => Some(4),
            Snap::ThirtySecond => Some(8),
            Snap::Bar | Snap::Off => None,
        }
    }

    /// For a gesture with Alt held: free when snapping, the beat when not.
    pub fn inverted(self, alt: bool) -> Snap {
        match (alt, self) {
            (false, s) => s,
            (true, Snap::Off) => Snap::Beat,
            (true, _) => Snap::Off,
        }
    }
}

/// Tempo, meter, click and where play starts.
#[derive(Debug, Clone, PartialEq)]
pub struct TransportSettings {
    pub bpm: f64,
    /// The meter: beats per bar, and the note value of a beat (display only).
    pub beats_per_bar: u32,
    pub beat_unit: u32,
    pub click: ClickMode,
    /// The click's peak level (dBFS).
    pub click_db: f64,
    pub count_in_bars: u32,
    pub pre_roll_bars: u32,
    /// Where play starts (a timeline sample at the session's rate, from bar 1; recording
    /// starts here): the cursor.
    pub cursor: i64,
    /// What the arrangement's gestures snap to.
    pub snap: Snap,
    /// Stop puts the cursor back where play started (else it stays where play stopped,
    /// and the next play goes on from there).
    pub return_to_cursor: bool,
    /// The left and right locators (beats from bar 1's downbeat) and whether play loops
    /// between them.
    pub left_beat: i64,
    pub right_beat: i64,
    pub loop_on: bool,
}

impl Default for TransportSettings {
    fn default() -> TransportSettings {
        TransportSettings {
            bpm: 120.0,
            beats_per_bar: 4,
            beat_unit: 4,
            click: ClickMode::On,
            click_db: -12.0,
            count_in_bars: 1,
            pre_roll_bars: 0,
            cursor: 0,
            snap: Snap::Beat,
            return_to_cursor: true,
            left_beat: 0,
            right_beat: 16,
            loop_on: false,
        }
    }
}

impl TransportSettings {
    /// Within what the transport takes: 20-400 bpm, 1-16 beats, the cursor from bar 1.
    pub fn clamped(mut self) -> TransportSettings {
        self.bpm = if self.bpm.is_finite() {
            self.bpm.clamp(20.0, 400.0)
        } else {
            120.0
        };
        self.beats_per_bar = self.beats_per_bar.clamp(1, 16);
        if ![1, 2, 4, 8, 16].contains(&self.beat_unit) {
            self.beat_unit = 4;
        }
        self.click_db = self.click_db.clamp(-60.0, 0.0);
        self.count_in_bars = self.count_in_bars.min(4);
        self.pre_roll_bars = self.pre_roll_bars.min(16);
        self.cursor = self.cursor.max(0);
        self.left_beat = self.left_beat.max(0);
        self.right_beat = self.right_beat.max(self.left_beat + 1);
        self
    }
}

/// Tempo and meter at a rate: where beats and bars fall, in samples.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Grid {
    pub rate: u32,
    pub bpm: f64,
    pub beats_per_bar: u32,
}

impl Grid {
    pub fn new(rate: u32, s: &TransportSettings) -> Grid {
        Grid {
            rate,
            bpm: s.bpm,
            beats_per_bar: s.beats_per_bar.max(1),
        }
    }

    pub fn samples_per_beat(&self) -> f64 {
        60.0 * self.rate as f64 / self.bpm
    }

    /// Where beat `k` starts (beat 0: bar 1's downbeat; negative: before it).
    pub fn beat(&self, k: i64) -> i64 {
        (k as f64 * self.samples_per_beat()).round() as i64
    }

    /// Where bar `bar` starts (from 1; 0 and below: the bars before bar 1).
    pub fn bar(&self, bar: i64) -> i64 {
        self.beat((bar - 1) * self.beats_per_bar as i64)
    }

    pub fn is_downbeat(&self, k: i64) -> bool {
        k.rem_euclid(self.beats_per_bar as i64) == 0
    }

    /// The bar (from 1) `pos` is in.
    pub fn bar_at(&self, pos: i64) -> i64 {
        self.beat_at(pos).div_euclid(self.beats_per_bar as i64) + 1
    }

    /// One step of `snap` (samples; none for Off).
    pub fn snap_step(&self, snap: Snap) -> Option<f64> {
        match snap {
            Snap::Off => None,
            Snap::Bar => Some(self.samples_per_beat() * self.beats_per_bar as f64),
            s => s.per_beat().map(|d| self.samples_per_beat() / d as f64),
        }
    }

    /// `pos` on the nearest line of `snap` (from bar 1's downbeat; Off: as it is).
    pub fn snap(&self, pos: i64, snap: Snap) -> i64 {
        match self.snap_step(snap) {
            None => pos,
            Some(step) => ((pos as f64 / step).round() * step).round() as i64,
        }
    }

    /// `pos` on the line of `snap` at or before it.
    pub fn snap_floor(&self, pos: i64, snap: Snap) -> i64 {
        match self.snap_step(snap) {
            None => pos,
            Some(step) => {
                let k = (pos as f64 / step).floor();
                let at = (k * step).round() as i64;
                if at > pos {
                    ((k - 1.0) * step).round() as i64
                } else {
                    at
                }
            }
        }
    }

    /// A move of `delta` samples in whole steps of `snap` (what a drag does: whatever sat
    /// off the grid stays as far off it).
    pub fn snap_delta(&self, delta: i64, snap: Snap) -> i64 {
        match self.snap_step(snap) {
            None => delta,
            Some(step) => ((delta as f64 / step).round() * step).round() as i64,
        }
    }

    /// The last beat at or before `pos`.
    pub fn beat_at(&self, pos: i64) -> i64 {
        let mut k = (pos as f64 / self.samples_per_beat()).floor() as i64;
        while self.beat(k) > pos {
            k -= 1;
        }
        while self.beat(k + 1) <= pos {
            k += 1;
        }
        k
    }

    /// `pos` as bar.beat.sixteenth (from 1; bars before bar 1 are 0, -1, ...).
    pub fn label(&self, pos: i64) -> String {
        let k = self.beat_at(pos);
        let per = self.beats_per_bar as i64;
        let bar = k.div_euclid(per) + 1;
        let beat = k.rem_euclid(per) + 1;
        let into = (pos - self.beat(k)) as f64 / self.samples_per_beat();
        let sixteenth = ((into * 4.0).floor() as i64).clamp(0, 3) + 1;
        if bar < 0 {
            format!("-{:02}.{beat}.{sixteenth}", -bar)
        } else {
            format!("{bar:03}.{beat}.{sixteenth}")
        }
    }
}

/// Where a running transport is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    CountIn,
    PreRoll,
    /// At or past the start bar (where a take records).
    Rolling,
}

/// The worker's transport: runs with the samples it computes and mixes the click in.
#[derive(Debug, Clone)]
pub struct Clock {
    pub settings: TransportSettings,
    grid: Grid,
    accent: Vec<f32>,
    beat: Vec<f32>,
    running: bool,
    pos: i64,
}

impl Clock {
    pub fn new(rate: u32, settings: TransportSettings) -> Clock {
        let settings = settings.clamped();
        Clock {
            grid: Grid::new(rate, &settings),
            accent: click_table(rate, true),
            beat: click_table(rate, false),
            settings,
            running: false,
            pos: 0,
        }
    }

    pub fn grid(&self) -> Grid {
        self.grid
    }

    /// New settings. The position stays where it is (in samples): a tempo change moves
    /// the beats under it.
    pub fn configure(&mut self, s: &TransportSettings) {
        let s = s.clone().clamped();
        if s != self.settings {
            self.grid = Grid::new(self.grid.rate, &s);
            self.settings = s;
        }
    }

    /// Where a start begins: the count-in's first sample.
    pub fn start_position(&self) -> i64 {
        let s = &self.settings;
        if s.loop_on {
            let per = self.grid.beats_per_bar as i64;
            return self.grid.beat(s.left_beat - s.count_in_bars as i64 * per);
        }
        if s.count_in_bars == 0 && s.pre_roll_bars == 0 {
            return s.cursor;
        }
        self.grid
            .bar(self.grid.bar_at(s.cursor) - s.pre_roll_bars as i64 - s.count_in_bars as i64)
    }

    /// Where the count-in ends (the loop's start, looping).
    pub fn count_in_end(&self) -> i64 {
        let s = &self.settings;
        if s.loop_on {
            return self.grid.beat(s.left_beat);
        }
        if s.count_in_bars == 0 && s.pre_roll_bars == 0 {
            return s.cursor;
        }
        self.grid
            .bar(self.grid.bar_at(s.cursor) - s.pre_roll_bars as i64)
    }

    /// Where recording starts: the cursor (the loop's start, looping).
    pub fn record_from(&self) -> i64 {
        if self.settings.loop_on {
            return self.grid.beat(self.settings.left_beat);
        }
        self.settings.cursor
    }

    /// The loop's start and end (positions), while it is on.
    pub fn loop_range(&self) -> Option<(i64, i64)> {
        let s = &self.settings;
        s.loop_on
            .then(|| (self.grid.beat(s.left_beat), self.grid.beat(s.right_beat)))
    }

    /// The positions of the next `n` samples while running: (position, offset in the
    /// block, length) per stretch, two across the loop's jump (none while stopped).
    pub fn segments(&self, n: usize) -> Vec<(i64, usize, usize)> {
        let mut v = Vec::new();
        if !self.running {
            return v;
        }
        let (mut pos, mut off) = (self.pos, 0);
        while off < n {
            let mut len = n - off;
            if let Some((a, b)) = self.loop_range() {
                if pos >= b {
                    pos = a;
                }
                len = len.min((b - pos) as usize);
            }
            v.push((pos, off, len));
            pos += len as i64;
            off += len;
        }
        v
    }

    pub fn start(&mut self) {
        self.pos = self.start_position();
        self.running = true;
    }

    pub fn stop(&mut self) {
        self.running = false;
    }

    pub fn running(&self) -> bool {
        self.running
    }

    /// The position of the next sample computed.
    pub fn position(&self) -> i64 {
        self.pos
    }

    pub fn phase_at(&self, pos: i64) -> Phase {
        if pos < self.count_in_end() {
            Phase::CountIn
        } else if pos < self.record_from() {
            Phase::PreRoll
        } else {
            Phase::Rolling
        }
    }

    /// Mix the click into the next `out.len()` samples (while running) and move on.
    pub fn process(&mut self, out: &mut [f32]) {
        let segments = self.segments(out.len());
        for &(pos, off, len) in &segments {
            self.click_into(pos, &mut out[off..off + len]);
        }
        if let Some(&(pos, _, len)) = segments.last() {
            self.pos = pos + len as i64;
        }
    }

    /// The click into `out`, which holds positions `a..`.
    fn click_into(&self, a: i64, out: &mut [f32]) {
        let n = out.len() as i64;
        let click_end = match self.settings.click {
            ClickMode::Off => return,
            ClickMode::CountIn => self.count_in_end(),
            ClickMode::On => i64::MAX,
        };
        let level = 10f64.powf(self.settings.click_db / 20.0) as f32;
        let len = self.accent.len().max(self.beat.len()) as i64;
        // Every click overlapping [a, a + n): from the beat before a - len on.
        let mut k = self.grid.beat_at(a - len);
        loop {
            let at = self.grid.beat(k);
            if at >= a + n || at >= click_end {
                break;
            }
            let table = if self.grid.is_downbeat(k) {
                &self.accent
            } else {
                &self.beat
            };
            // The click's samples i with a <= at + i < a + n.
            let from = (a - at).max(0);
            let to = (a + n - at).min(table.len() as i64);
            for i in from..to {
                out[(at + i - a) as usize] += level * table[i as usize];
            }
            k += 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings(bpm: f64) -> TransportSettings {
        TransportSettings {
            bpm,
            click_db: 0.0,
            ..TransportSettings::default()
        }
    }

    /// Where the click's blips start in `y`: the silent sample before a nonzero one (a
    /// click's first sample is 0: its attack starts there).
    fn onsets(y: &[f32]) -> Vec<usize> {
        (0..y.len().saturating_sub(1))
            .filter(|&i| y[i] == 0.0 && y[i + 1] != 0.0)
            .collect()
    }

    #[test]
    fn beats_never_drift() {
        // 97 bpm at 48 kHz: 29690.72 samples a beat, not an integer.
        let g = Grid::new(48_000, &settings(97.0));
        let k = 10_000; // ~1.7 hours
        let exact = k as f64 * 60.0 * 48_000.0 / 97.0;
        assert!((g.beat(k) as f64 - exact).abs() <= 0.5);
        for pos in [-100_000, -1, 0, 1, 29_690, 29_691, 10_000_000] {
            let b = g.beat_at(pos);
            assert!(g.beat(b) <= pos && g.beat(b + 1) > pos, "{pos}");
        }
        assert_eq!(g.label(0), "001.1.1");
        assert_eq!(g.label(g.beat(5)), "002.2.1");
        assert_eq!(g.label(g.beat(-1)), "000.4.1");
        assert_eq!(g.label(g.bar(-1)), "-01.1.1");
    }

    #[test]
    fn the_click_lands_on_its_samples_in_any_block_size() {
        let rate = 48_000;
        let s = TransportSettings {
            count_in_bars: 1,
            ..settings(137.0)
        };
        let whole = {
            let mut c = Clock::new(rate, s.clone());
            c.start();
            let mut y = vec![0.0f32; 20 * rate as usize];
            c.process(&mut y);
            y
        };
        // Blocks of an odd size equal the run in one block, bit for bit.
        let mut c = Clock::new(rate, s.clone());
        c.start();
        let mut y = Vec::new();
        while y.len() < whole.len() {
            let mut b = vec![0.0f32; 333.min(whole.len() - y.len())];
            c.process(&mut b);
            y.extend(b);
        }
        assert_eq!(y, whole);
        // A click on every beat from the count-in on, starting on its sample.
        let g = Grid::new(rate, &s);
        let start = g.bar(0);
        let expected: Vec<usize> = (-4..)
            .map(|k| (g.beat(k) - start) as usize)
            .take_while(|&i| i < whole.len())
            .collect();
        assert_eq!(onsets(&whole), expected);
        // Downbeats are the accented pitch: count the sign changes in 10 ms.
        let changes = |at: usize| {
            let w = &whole[at + 1..at + 481];
            w.windows(2)
                .filter(|p| (p[0] < 0.0) != (p[1] < 0.0))
                .count()
        };
        assert!((38..=40).contains(&changes(expected[0]))); // 2 kHz
        assert!((24..=26).contains(&changes(expected[1]))); // 1.25 kHz
        assert!(whole.iter().all(|v| v.abs() <= 1.0));
    }

    #[test]
    fn count_in_pre_roll_and_click_modes() {
        let rate = 48_000;
        let g = Grid::new(rate, &settings(120.0));
        let s = TransportSettings {
            count_in_bars: 2,
            pre_roll_bars: 1,
            cursor: g.bar(5),
            click: ClickMode::CountIn,
            ..settings(120.0)
        };
        let mut c = Clock::new(rate, s.clone());
        assert_eq!(c.start_position(), g.bar(2));
        assert_eq!(c.count_in_end(), g.bar(4));
        assert_eq!(c.record_from(), g.bar(5));
        c.start();
        assert_eq!(c.phase_at(c.position()), Phase::CountIn);
        assert_eq!(c.phase_at(g.bar(4)), Phase::PreRoll);
        assert_eq!(c.phase_at(g.bar(5)), Phase::Rolling);
        let mut y = vec![0.0f32; (g.bar(6) - g.bar(2)) as usize];
        c.process(&mut y);
        assert_eq!(c.position(), g.bar(6));
        // Count-in only: 8 clicks, then nothing.
        assert_eq!(onsets(&y).len(), 8);
        // Stopped: silent, and the position holds.
        c.stop();
        let mut z = vec![0.0f32; 4800];
        c.process(&mut z);
        assert!(z.iter().all(|&v| v == 0.0));
        assert_eq!(c.position(), g.bar(6));
        // Off: silent while running.
        c.configure(&TransportSettings {
            click: ClickMode::Off,
            ..s
        });
        c.start();
        c.process(&mut z);
        assert!(z.iter().all(|&v| v == 0.0));
    }

    #[test]
    fn a_cursor_mid_bar_counts_in_on_the_grid_and_records_from_itself() {
        let rate = 48_000;
        let g = Grid::new(rate, &settings(120.0));
        let cursor = g.bar(3) + (g.samples_per_beat() * 1.5) as i64;
        let s = TransportSettings {
            count_in_bars: 1,
            cursor,
            ..settings(120.0)
        };
        let mut c = Clock::new(rate, s.clone());
        // The count-in is the bar before the cursor's, the timeline plays from its bar's
        // start, the take from the cursor.
        assert_eq!(c.start_position(), g.bar(2));
        assert_eq!(c.count_in_end(), g.bar(3));
        assert_eq!(c.record_from(), cursor);
        assert_eq!(c.phase_at(g.bar(3) + 10), Phase::PreRoll);
        assert_eq!(c.phase_at(cursor), Phase::Rolling);
        // The click stays on its grid: every onset a beat's sample.
        c.start();
        let mut y = vec![0.0f32; (g.bar(4) - g.bar(2)) as usize];
        c.process(&mut y);
        let want: Vec<usize> = (4..12).map(|k| (g.beat(k) - g.bar(2)) as usize).collect();
        assert_eq!(onsets(&y), want);
        // Without count-in or pre-roll, play starts at the cursor itself.
        let c = Clock::new(
            rate,
            TransportSettings {
                count_in_bars: 0,
                ..s
            },
        );
        assert_eq!(c.start_position(), cursor);
        // Snaps: a 1/16 step, a move keeps its offset from the grid.
        let sixteenth = g.samples_per_beat() / 4.0;
        assert_eq!(
            g.snap((sixteenth * 3.4) as i64, Snap::Sixteenth),
            (sixteenth * 3.0).round() as i64
        );
        assert_eq!(g.snap(12_345, Snap::Off), 12_345);
        let bar = g.bar(2);
        assert_eq!(g.snap_delta(bar + 500, Snap::Bar), bar);
        assert_eq!(g.snap(g.bar(3) - 10, Snap::Bar), g.bar(3));
        assert_eq!(g.snap_floor(g.bar(3) - 10, Snap::Bar), g.bar(2));
        assert_eq!(Snap::Beat.inverted(true), Snap::Off);
        assert_eq!(Snap::Off.inverted(true), Snap::Beat);
    }

    #[test]
    fn the_loop_jumps_back_within_a_block() {
        let rate = 48_000;
        let s = TransportSettings {
            count_in_bars: 1,
            left_beat: 4,
            right_beat: 8,
            loop_on: true,
            ..settings(120.0)
        };
        let mut c = Clock::new(rate, s);
        let g = c.grid();
        c.start();
        assert_eq!(c.position(), g.beat(0)); // a bar of count-in before the left locator
        assert_eq!(c.record_from(), g.beat(4));
        assert_eq!(c.phase_at(g.beat(2)), Phase::CountIn);
        // Run to just before the right locator, then a block across it.
        let mut y = vec![0.0f32; (g.beat(8) - g.beat(0) - 100) as usize];
        c.process(&mut y);
        assert_eq!(
            c.segments(480),
            vec![(g.beat(8) - 100, 0, 100), (g.beat(4), 100, 380)]
        );
        let mut z = vec![0.0f32; 480];
        c.process(&mut z);
        assert_eq!(c.position(), g.beat(4) + 380);
        // The left locator's downbeat clicks right after the jump.
        assert!(z[100] == 0.0 && z[101] != 0.0);
        // Three passes later the position is still inside the loop.
        let mut w = vec![0.0f32; 3 * (g.beat(8) - g.beat(4)) as usize];
        c.process(&mut w);
        assert_eq!(c.position(), g.beat(4) + 380);
        // The loop turned on past its end: back to the start at the next block.
        let mut c2 = Clock::new(
            rate,
            TransportSettings {
                loop_on: false,
                ..c.settings.clone()
            },
        );
        c2.start();
        let mut y = vec![0.0f32; g.beat(20) as usize];
        c2.process(&mut y);
        c2.configure(&TransportSettings {
            loop_on: true,
            ..c2.settings.clone()
        });
        assert_eq!(c2.segments(10), vec![(g.beat(4), 0, 10)]);
    }

    #[test]
    fn the_click_costs_next_to_nothing() {
        // 10 minutes at 48 kHz in the player's blocks: the click's share of real time.
        let rate = 48_000;
        let mut c = Clock::new(rate, settings(240.0));
        c.start();
        let mut y = vec![0.0f32; 480];
        let t = std::time::Instant::now();
        for _ in 0..(600 * rate as usize / 480) {
            y.fill(0.0);
            c.process(&mut y);
        }
        let share = t.elapsed().as_secs_f64() / 600.0;
        println!("the click: {:.4}% of real time", share * 100.0);
        assert!(share < 0.001, "{share}");
    }

    #[test]
    fn the_click_is_smooth() {
        // No step at the start or the end; the same wave at any rate.
        assert_eq!(click_wave(0.0, true), 0.0);
        assert_eq!(click_wave(CLICK_S, true), 0.0);
        let t = click_table(96_000, false);
        let worst = t
            .windows(2)
            .map(|w| (w[1] - w[0]).abs())
            .fold(0.0, f32::max);
        assert!(worst < 0.1, "{worst}");
        assert_eq!(
            click_table(48_000, true)[100],
            click_table(96_000, true)[200]
        );
    }
}
