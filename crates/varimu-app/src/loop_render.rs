//! Loop renders: an insert too slow to play live, heard anyway (the insert panel's "⟳ loop").
//!
//! Instead of the device playing live, the insert's input over the transport's loop is
//! printed offline at the device's play quality (draft-1x for most) and the print plays as a
//! clip on its track in the mix, looped by the transport. A change of the panel renders the
//! loop again in the background; the last render plays meanwhile.
//!
//! - **Stereo as printed**: a stereo input goes through the device as its print would take it
//!   (a two-input device such as the stereo 670 in one run, a stereo device from the mid,
//!   others dual-mono), so there is no "hear L / R / mid" choice: both channels are heard.
//! - **A warm-up**: the render starts [`WARMUP_S`] before the loop (not before the input
//!   starts) and drops it, so a compressor's gain reduction at the loop's start is what the
//!   music before it left, not a rest. What happened earlier than that isn't in it (a long
//!   release, a tape's whole run): the print is the reference.
//! - **What renders again**: the input over the warmed loop, the device, its values and the
//!   trim in front ([`key`]). Make-up, wet and bypass apply at playback ([`Rendered::clip`]),
//!   so turning them is heard at once: the render is fully wet, no make-up.
//! - The inserts after this one aren't heard (as live).

use std::sync::Arc;

use crate::print::{Print, Slot};
use crate::session::MixClip;
use crate::settings::Quality;

/// How long before the loop a render starts (s), dropped from what plays.
pub const WARMUP_S: f64 = 2.0;

/// The input of a loop render: its samples from timeline position `from` (the warm-up's start)
/// to the loop's end, the loop's start, a key track's audio over the same span.
#[derive(Debug, Clone, PartialEq)]
pub struct Excerpt {
    pub from: i64,
    pub start: i64,
    pub end: i64,
    pub left: Arc<Vec<f32>>,
    pub right: Option<Arc<Vec<f32>>>,
    pub side: Option<Arc<Vec<f32>>>,
}

/// The excerpt of an input placed at `input_start` (left, right, a key track's audio aligned
/// with it) for the loop `[a, b)`: from [`WARMUP_S`] before `a`, not before the input's start,
/// to `b`; silence where the input has none. None: the loop is empty or before the input.
pub fn excerpt(
    input_start: i64,
    left: &[f32],
    right: Option<&[f32]>,
    side: Option<&[f32]>,
    loop_range: (i64, i64),
    rate: u32,
) -> Option<Excerpt> {
    let (from, start, b) = span(input_start, left.len(), loop_range, rate)?;
    let cut = |x: &[f32]| -> Arc<Vec<f32>> {
        Arc::new(
            (from..b)
                .map(|p| x.get((p - input_start) as usize).copied().unwrap_or(0.0))
                .collect(),
        )
    };
    Some(Excerpt {
        from,
        start,
        end: b,
        left: cut(left),
        right: right.map(cut),
        side: side.map(cut),
    })
}

/// The span an excerpt covers, for an input of `len` samples placed at `input_start` and the
/// loop `[a, b)`: (the warm-up's start, the loop's start within the input, the loop's end).
/// None: the loop is empty or outside the input.
pub fn span(
    input_start: i64,
    len: usize,
    loop_range: (i64, i64),
    rate: u32,
) -> Option<(i64, i64, i64)> {
    let (a, b) = loop_range;
    if b <= a || b <= input_start || a >= input_start + len as i64 {
        return None;
    }
    let warm = (WARMUP_S * rate as f64).round() as i64;
    Some(((a - warm).max(input_start), a.max(input_start), b))
}

/// The slot as a loop render prints it: at `quality` (its device's play quality), no tail,
/// fully wet, no make-up, not bypassed ([`Rendered::clip`] applies those).
pub fn render_slot(slot: &Slot, quality: Quality) -> Slot {
    Slot {
        quality,
        tail_s: 0.0,
        makeup_db: 0.0,
        wet: 1.0,
        bypass: false,
        ..slot.clone()
    }
}

/// What a loop render is of: its input (`input`, an id that changes with it: what it is of
/// and its buffers), the warmed loop's `span` ([`span`]) and the slot as printed. Equal keys
/// render the same.
pub fn key(slot: &Slot, input: &str, span: (i64, i64, i64)) -> String {
    let (from, start, end) = span;
    format!("{from}|{start}|{end}|{input}|{}", slot.to_json())
}

/// A finished loop render: from the loop's start to its end, the device's output (fully wet,
/// a mono print's right its left) and the dry input beside it.
#[derive(Debug, Clone)]
pub struct Rendered {
    pub key: String,
    pub start: i64,
    pub wet: (Arc<Vec<f32>>, Arc<Vec<f32>>),
    pub dry: (Arc<Vec<f32>>, Arc<Vec<f32>>),
    /// Whether it plays in stereo (the print is, or the input was).
    pub stereo: bool,
}

impl Rendered {
    /// The print of `ex` (its first insert's), the warm-up dropped.
    pub fn new(key: String, ex: &Excerpt, print: &Print) -> Rendered {
        let skip = (ex.start - ex.from) as usize;
        let n = (ex.end - ex.start) as usize;
        let tail = |x: &[f32]| -> Arc<Vec<f32>> {
            let mut v: Vec<f32> = x.iter().skip(skip).take(n).copied().collect();
            v.resize(n, 0.0);
            Arc::new(v)
        };
        let wl = tail(&print.audio);
        let wr = print.right.as_ref().map_or_else(|| wl.clone(), |r| tail(r));
        let dl = tail(&ex.left);
        let dr = ex.right.as_ref().map_or_else(|| dl.clone(), |r| tail(r));
        Rendered {
            key,
            start: ex.start,
            stereo: print.right.is_some() || ex.right.is_some(),
            wet: (wl, wr),
            dry: (dl, dr),
        }
    }

    /// What plays: the slot's make-up and wet share over the device, the rest dry (bypassed:
    /// dry), as a clip at the loop's start through `gains` on track `track`'s meter.
    pub fn clip(&self, slot: &Slot, gains: (f32, f32), track: usize) -> MixClip {
        let side = |wet: &[f32], dry: &[f32]| -> Arc<Vec<f32>> {
            if slot.bypass {
                return Arc::new(dry.to_vec());
            }
            let g = 10f64.powf(slot.makeup_db / 20.0) as f32;
            let w = slot.wet.clamp(0.0, 1.0) as f32;
            Arc::new(
                wet.iter()
                    .zip(dry)
                    .map(|(&y, &d)| w * g * y + (1.0 - w) * d)
                    .collect(),
            )
        };
        let left = side(&self.wet.0, &self.dry.0);
        let right = self.stereo.then(|| side(&self.wet.1, &self.dry.1));
        MixClip {
            right,
            track,
            ..MixClip::whole(self.start, left, gains)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// What the Session view does: a stereo input's loop through the stereo 670 (a two-input
    /// device: one run), its warm-up dropped, a stereo clip as long as the loop.
    #[test]
    fn a_stereo_loop_renders_through_the_stereo_670() {
        let rate = 48_000u32;
        let n = (3.0 * rate as f64) as usize;
        let tone = |amp: f32, f: f32| -> Vec<f32> {
            (0..n)
                .map(|i| amp * (2.0 * std::f32::consts::PI * f * i as f32 / rate as f32).sin())
                .collect()
        };
        let (l, r) = (tone(0.3, 440.0), tone(0.03, 660.0));
        let loop_range = (rate as i64 * 2, rate as i64 * 2 + rate as i64 / 4);
        let ex = excerpt(0, &l, Some(&r), None, loop_range, rate).unwrap();
        assert_eq!((ex.from, ex.start), (0, loop_range.0));
        let mut slot = Slot::new("fairchild_670_stereo");
        slot.wet = 0.25; // applied at playback, not rendered
        let rs = render_slot(&slot, Quality::Draft1x);
        let config = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
        let job = crate::print::Job::spawn(
            config,
            vec![rs.clone()],
            vec![ex.side.clone()],
            ex.left.clone(),
            ex.right.clone(),
            rate,
            None,
        );
        let prints = job.join().expect("a result").expect("rendered");
        let done = Rendered::new(
            key(&rs, "test", (ex.from, ex.start, ex.end)),
            &ex,
            &prints[0],
        );
        let clip = done.clip(&slot, (1.0, 1.0), 0);
        assert_eq!(clip.len, (loop_range.1 - loop_range.0) as usize);
        let right = clip.right.as_ref().expect("stereo");
        let rms = |x: &[f32]| (x.iter().map(|v| v * v).sum::<f32>() / x.len() as f32).sqrt();
        // Each side its own: the quiet right stays quiet, the loud left is the device's.
        assert!(rms(right) < 0.3 * rms(&clip.audio));
        assert!(rms(&done.wet.0) > 0.0 && done.wet.0.as_ptr() != done.dry.0.as_ptr());
    }

    #[test]
    fn an_excerpt_starts_a_warm_up_before_the_loop_but_not_before_the_input() {
        let rate = 1000;
        let x: Vec<f32> = (0..10_000).map(|i| i as f32).collect();
        // Input at 500; the loop 4000..6000: from 2000 (2 s of warm-up), the samples there.
        let e = excerpt(500, &x, None, None, (4000, 6000), rate).unwrap();
        assert_eq!((e.from, e.start, e.end), (2000, 4000, 6000));
        assert_eq!(e.left.len(), 4000);
        assert_eq!(e.left[0], 1500.0);
        // A loop near the input's start: the warm-up is cut there.
        let e = excerpt(500, &x, None, None, (1000, 2000), rate).unwrap();
        assert_eq!((e.from, e.start), (500, 1000));
        // Past the input's end: silence; a loop before the input or empty: none.
        let e = excerpt(500, &x, Some(&x), None, (10_000, 11_000), rate).unwrap();
        assert_eq!(*e.left.last().unwrap(), 0.0);
        assert_eq!(e.right.as_ref().unwrap().len(), e.left.len());
        assert!(excerpt(500, &x, None, None, (0, 400), rate).is_none());
        assert!(excerpt(500, &x, None, None, (3000, 3000), rate).is_none());
    }

    #[test]
    fn make_up_wet_and_bypass_apply_at_playback() {
        let ex = Excerpt {
            from: 0,
            start: 2,
            end: 4,
            left: Arc::new(vec![9.0, 9.0, 1.0, 1.0]),
            right: None,
            side: None,
        };
        let print = Print {
            key: String::new(),
            audio: Arc::new(vec![7.0, 7.0, 2.0, 2.0]),
            right: Some(Arc::new(vec![7.0, 7.0, 4.0, 4.0])),
            cached: false,
            realtime_factor: 0.0,
        };
        let r = Rendered::new("k".into(), &ex, &print);
        assert_eq!((r.start, r.wet.0.len()), (2, 2));
        assert!(r.stereo);
        let mut slot = Slot::new("fairchild_670_stereo");
        slot.wet = 0.5;
        slot.makeup_db = 20.0 * 2f64.log10(); // x2
        let c = r.clip(&slot, (1.0, 1.0), 3);
        assert_eq!((c.start, c.track), (2, 3));
        assert_eq!(c.audio.as_slice(), &[2.5, 2.5]); // 0.5 * 2 * 2 + 0.5 * 1
        assert_eq!(c.right.as_deref().unwrap().as_slice(), &[4.5, 4.5]);
        slot.bypass = true;
        assert_eq!(r.clip(&slot, (1.0, 1.0), 3).audio.as_slice(), &[1.0, 1.0]);
        // The render itself: fully wet, no make-up, no tail, at the play quality.
        let s = render_slot(&slot, Quality::Draft1x);
        assert_eq!(
            (s.wet, s.makeup_db, s.tail_s, s.bypass),
            (1.0, 0.0, 0.0, false)
        );
    }
}
