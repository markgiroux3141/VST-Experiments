//! Topology edits on the drawing (`varimu/listen/editor/geom.js`): placing, moving,
//! rotating, mirroring, deleting, copying and pasting, drawing wires. Pure functions of
//! the drawing and the symbol table.
//!
//! Coordinates are mm, y down, on the 1.27 mm grid; a placed unit is mirrored, rotated
//! counter-clockwise on the screen, then moved (`varimu_circuit::symbols::transform`).
//! Wires stay attached: a wire end on a moved pin (or on a moved wire's end, label or
//! ground) follows it, and its first segment keeps its direction by bending
//! (rubber-banding). Rounding is JavaScript's (`Math.round`), so the page and the app
//! write the same drawing.

use std::collections::HashMap;

use varimu_circuit::drawing::{Drawing, Label, Placement, Symbol};
use varimu_circuit::symbols::{self, Kind, SymbolDef};

use super::eng::js_round;

pub const GRID: f64 = 1.27;
const EPS: f64 = 1e-3;

pub type Pt = (f64, f64);
type Key = (i64, i64);

pub fn round4(v: f64) -> f64 {
    js_round(v * 1e4) / 1e4
}

/// To the grid.
pub fn snap(v: f64) -> f64 {
    round4(js_round(v / GRID) * GRID)
}

fn key(p: Pt) -> Key {
    (js_round(p.0 / EPS) as i64, js_round(p.1 / EPS) as i64)
}

fn same(a: Pt, b: Pt) -> bool {
    (a.0 - b.0).abs() < EPS && (a.1 - b.1).abs() < EPS
}

fn sub(a: Pt, b: Pt) -> Pt {
    (a.0 - b.0, a.1 - b.1)
}

/// A symbol point (y down) placed: mirrored, rotated `rot` counter-clockwise, moved.
pub fn tf(x: f64, y: f64, pl: &Placement) -> Pt {
    let x = if pl.mirror { -x } else { x };
    let (c, s) = match pl.rot.rem_euclid(360) {
        90 => (0.0, 1.0),
        180 => (-1.0, 0.0),
        270 => (0.0, -1.0),
        _ => (1.0, 0.0),
    };
    (round4(pl.x + x * c + y * s), round4(pl.y - x * s + y * c))
}

/// (pin number, point) of a placed unit (y down; none for an unknown symbol).
pub fn pin_points(s: &Symbol, unit: i64) -> Vec<(String, Pt)> {
    let (Some(sym), Some(pl)) = (symbols::get(&s.symbol), s.unit(unit)) else {
        return Vec::new();
    };
    unit_pins(sym, unit)
        .iter()
        .map(|p| (p.number.clone(), tf(p.x, -p.y, pl)))
        .collect()
}

fn unit_pins(sym: &SymbolDef, unit: i64) -> &[symbols::Pin] {
    usize::try_from(unit - 1)
        .ok()
        .and_then(|u| sym.units.get(u))
        .map_or(&[], Vec::as_slice)
}

/// The next free reference with `prefix`: R7 after R1..R6.
pub fn next_ref(d: &Drawing, prefix: &str) -> String {
    let clean: String = prefix
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '_')
        .collect();
    let mut n = 0u64;
    for (r, _) in &d.symbols {
        if let Some(rest) = r.strip_prefix(&clean)
            && !rest.is_empty()
            && rest.bytes().all(|b| b.is_ascii_digit())
            && let Ok(k) = rest.parse::<u64>()
        {
            n = n.max(k);
        }
    }
    format!("{prefix}{}", n + 1)
}

/// Placeholder values for a new part: shown in the inspector to be replaced, never
/// compiled without a source (the importer blocks a number without one).
fn default_value(name: &str) -> Option<&'static str> {
    Some(match name {
        "R" => "10k",
        "C" => "100n",
        "L" => "10m",
        "Pot" => "100k",
        "Rheostat" => "10k",
        "Pot_Tapped" => "1M",
        "T_Pad" => "600",
        "V" => "250",
        "Sine" => "1",
        "Mains" => "117",
        "Triode" | "Triode_Dual" => "12AX7",
        "Pentode" => "6973",
        "Diode" | "Diode_Dual" => "6X4",
        "Winding" => "p",
        "K" => "0.99",
        "VR_Tube" => "150",
        _ => return None,
    })
}

/// Place a new unit of symbol `name` at (x, y); returns its reference (None: no such
/// symbol).
pub fn place_symbol(
    d: &mut Drawing,
    name: &str,
    x: f64,
    y: f64,
    rot: i64,
    mirror: bool,
) -> Option<String> {
    let sym = symbols::get(name)?;
    let r = next_ref(
        d,
        if sym.prefix == "#PWR" {
            "G"
        } else {
            sym.prefix
        },
    );
    let pl = Placement {
        x: snap(x),
        y: snap(y),
        rot,
        mirror,
    };
    let mut units = vec![(1, pl)];
    if sym.units.len() > 1 {
        units.push((
            2,
            Placement {
                x: snap(x + 25.4),
                ..pl
            },
        ));
    }
    let value = default_value(name).map_or_else(
        || {
            if sym.kind == Kind::Switch {
                "SW".to_string()
            } else {
                sym.value.clone()
            }
        },
        str::to_string,
    );
    d.symbols.push((
        r.clone(),
        Symbol {
            symbol: name.into(),
            value,
            fields: Vec::new(),
            units,
        },
    ));
    Some(r)
}

// --- Selections ---------------------------------------------------------------------------

/// Selected items: symbols by reference, the rest by index.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Sel {
    pub symbols: Vec<String>,
    pub wires: Vec<usize>,
    pub labels: Vec<usize>,
    pub grounds: Vec<usize>,
    pub frames: Vec<usize>,
}

/// One item of a selection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Item {
    Symbol(String),
    Wire(usize),
    Label(usize),
    Ground(usize),
    Frame(usize),
}

impl Sel {
    pub fn size(&self) -> usize {
        self.symbols.len()
            + self.wires.len()
            + self.labels.len()
            + self.grounds.len()
            + self.frames.len()
    }

    pub fn is_empty(&self) -> bool {
        self.size() == 0
    }

    pub fn only(item: Item) -> Sel {
        let mut s = Sel::default();
        s.toggle(&item);
        s
    }

    pub fn symbol(r: &str) -> Sel {
        Sel::only(Item::Symbol(r.into()))
    }

    pub fn has(&self, item: &Item) -> bool {
        match item {
            Item::Symbol(r) => self.symbols.contains(r),
            Item::Wire(i) => self.wires.contains(i),
            Item::Label(i) => self.labels.contains(i),
            Item::Ground(i) => self.grounds.contains(i),
            Item::Frame(i) => self.frames.contains(i),
        }
    }

    /// Add `item`, or take it out when it is in.
    pub fn toggle(&mut self, item: &Item) {
        fn flip<T: PartialEq + Clone>(v: &mut Vec<T>, x: &T) {
            match v.iter().position(|y| y == x) {
                Some(i) => {
                    v.remove(i);
                }
                None => v.push(x.clone()),
            }
        }
        match item {
            Item::Symbol(r) => flip(&mut self.symbols, r),
            Item::Wire(i) => flip(&mut self.wires, i),
            Item::Label(i) => flip(&mut self.labels, i),
            Item::Ground(i) => flip(&mut self.grounds, i),
            Item::Frame(i) => flip(&mut self.frames, i),
        }
    }

    /// Everything in `self` and `other`.
    pub fn union(&self, other: &Sel) -> Sel {
        fn add<T: PartialEq + Clone>(a: &mut Vec<T>, b: &[T]) {
            for x in b {
                if !a.contains(x) {
                    a.push(x.clone());
                }
            }
        }
        let mut s = self.clone();
        add(&mut s.symbols, &other.symbols);
        add(&mut s.wires, &other.wires);
        add(&mut s.labels, &other.labels);
        add(&mut s.grounds, &other.grounds);
        add(&mut s.frames, &other.frames);
        s
    }

    /// Without items that no longer exist in `d`.
    pub fn existing(&self, d: &Drawing) -> Sel {
        Sel {
            symbols: self
                .symbols
                .iter()
                .filter(|r| d.symbol(r).is_some())
                .cloned()
                .collect(),
            wires: self
                .wires
                .iter()
                .copied()
                .filter(|&i| i < d.wires.len())
                .collect(),
            labels: self
                .labels
                .iter()
                .copied()
                .filter(|&i| i < d.labels.len())
                .collect(),
            grounds: self
                .grounds
                .iter()
                .copied()
                .filter(|&i| i < d.grounds.len())
                .collect(),
            frames: self
                .frames
                .iter()
                .copied()
                .filter(|&i| i < d.frames.len())
                .collect(),
        }
    }

    /// Everything in a drawing but its frames (Ctrl+A).
    pub fn all(d: &Drawing) -> Sel {
        Sel {
            symbols: d.symbols.iter().map(|(r, _)| r.clone()).collect(),
            wires: (0..d.wires.len()).collect(),
            labels: (0..d.labels.len()).collect(),
            grounds: (0..d.grounds.len()).collect(),
            frames: Vec::new(),
        }
    }

    /// How an edit's label names the selection: a part's reference, an item's kind, or
    /// a count.
    pub fn describe(&self) -> String {
        let n = self.size();
        if self.symbols.len() == 1 && n == 1 {
            return self.symbols[0].clone();
        }
        if n == 1 {
            let kind = if !self.wires.is_empty() {
                "wire"
            } else if !self.labels.is_empty() {
                "label"
            } else if !self.grounds.is_empty() {
                "ground"
            } else {
                "frame"
            };
            return kind.into();
        }
        format!("{n} items")
    }
}

/// What lies inside a box: whole symbols (their origin), wires (every point), labels,
/// grounds, frames (wholly inside).
pub fn select_box(d: &Drawing, b: [f64; 4]) -> Sel {
    let [x0, y0, x1, y1] = b;
    let inside = |(x, y): Pt| x >= x0 && x <= x1 && y >= y0 && y <= y1;
    let mut sel = Sel::default();
    for (r, s) in &d.symbols {
        if s.units.iter().any(|(_, pl)| inside((pl.x, pl.y))) {
            sel.symbols.push(r.clone());
        }
    }
    for (i, w) in d.wires.iter().enumerate() {
        if w.iter().all(|&p| inside(p)) {
            sel.wires.push(i);
        }
    }
    for (i, l) in d.labels.iter().enumerate() {
        if inside((l.x, l.y)) {
            sel.labels.push(i);
        }
    }
    for (i, g) in d.grounds.iter().enumerate() {
        if inside((g.x, g.y)) {
            sel.grounds.push(i);
        }
    }
    for (i, f) in d.frames.iter().enumerate() {
        if inside((f.x, f.y)) && inside((f.x + f.w, f.y + f.h)) {
            sel.frames.push(i);
        }
    }
    sel
}

/// A frame with everything whose position is in it.
pub fn frame_contents(d: &Drawing, i: usize) -> Sel {
    let f = &d.frames[i];
    let mut sel = select_box(d, [f.x, f.y, f.x + f.w, f.y + f.h]);
    sel.frames = vec![i];
    sel
}

/// The top-left corner of a selection's points.
pub fn sel_bounds(d: &Drawing, sel: &Sel) -> Option<Pt> {
    let pts = sel_points(d, sel);
    if pts.is_empty() {
        return None;
    }
    Some((
        pts.iter().map(|p| p.0).fold(f64::INFINITY, f64::min),
        pts.iter().map(|p| p.1).fold(f64::INFINITY, f64::min),
    ))
}

fn sel_points(d: &Drawing, sel: &Sel) -> Vec<Pt> {
    let mut pts = Vec::new();
    for r in &sel.symbols {
        if let Some(s) = d.symbol(r) {
            pts.extend(s.units.iter().map(|(_, pl)| (pl.x, pl.y)));
        }
    }
    for &i in &sel.wires {
        pts.extend(d.wires[i].iter().copied());
    }
    for &i in &sel.labels {
        pts.push((d.labels[i].x, d.labels[i].y));
    }
    for &i in &sel.grounds {
        pts.push((d.grounds[i].x, d.grounds[i].y));
    }
    pts
}

// --- Moving -------------------------------------------------------------------------------

/// Points that move (old key -> new point) when `sel` moves by `f` (a point map).
fn moved_points(
    d: &Drawing,
    sel: &Sel,
    f: impl Fn(Pt) -> Pt,
    before: &Drawing,
) -> HashMap<Key, Pt> {
    let mut moves = HashMap::new();
    for r in &sel.symbols {
        let (Some(s), Some(old)) = (d.symbol(r), before.symbol(r)) else {
            continue;
        };
        for (u, _) in &s.units {
            let b = pin_points(s, *u);
            for (n, a) in pin_points(old, *u) {
                if let Some((_, q)) = b.iter().find(|(m, _)| *m == n) {
                    moves.insert(key(a), *q);
                }
            }
        }
    }
    for &i in &sel.wires {
        for &p in &before.wires[i] {
            moves.insert(key(p), f(p));
        }
    }
    for &i in &sel.labels {
        let l = &before.labels[i];
        moves.insert(key((l.x, l.y)), f((l.x, l.y)));
    }
    for &i in &sel.grounds {
        let g = &before.grounds[i];
        moves.insert(key((g.x, g.y)), f((g.x, g.y)));
    }
    moves
}

/// Wires, labels and grounds not in `sel` that touch a moved point follow it.
fn reattach(d: &mut Drawing, sel: &Sel, moves: &HashMap<Key, Pt>) {
    for (i, l) in d.labels.iter_mut().enumerate() {
        if !sel.labels.contains(&i)
            && let Some(m) = moves.get(&key((l.x, l.y)))
        {
            (l.x, l.y) = *m;
        }
    }
    for (i, g) in d.grounds.iter_mut().enumerate() {
        if !sel.grounds.contains(&i)
            && let Some(m) = moves.get(&key((g.x, g.y)))
        {
            (g.x, g.y) = *m;
        }
    }
    for (i, w) in d.wires.iter_mut().enumerate() {
        if sel.wires.contains(&i) || w.is_empty() {
            continue;
        }
        let n = w.len();
        let (m0, m1) = (moves.get(&key(w[0])), moves.get(&key(w[n - 1])));
        if let (Some(&m0), Some(&m1)) = (m0, m1)
            && same(sub(m0, w[0]), sub(m1, w[n - 1]))
        {
            // Both ends move alike: the whole wire moves.
            let dd = sub(m0, w[0]);
            for p in w.iter_mut() {
                *p = (round4(p.0 + dd.0), round4(p.1 + dd.1));
            }
            continue;
        }
        let mut pts = w.clone();
        if let Some(&m0) = m0 {
            pts = follow(&pts, m0);
        }
        if let Some(&m1) = m1 {
            pts.reverse();
            pts = follow(&pts, m1);
            pts.reverse();
        }
        *w = pts;
    }
    tidy(d);
}

/// Move a wire's first point to `to`, keeping its first segment's direction: an inner
/// corner slides with it, a straight two-point wire gets a bend at the moved end.
fn follow(pts: &[Pt], to: Pt) -> Vec<Pt> {
    if pts.len() < 2 {
        return vec![to];
    }
    let (e, q) = (pts[0], pts[1]);
    let horiz = (e.1 - q.1).abs() < EPS;
    let vert = (e.0 - q.0).abs() < EPS;
    let mut out = vec![to];
    if pts.len() > 2 && (horiz || vert) {
        out.push(if horiz { (q.0, to.1) } else { (to.0, q.1) });
        out.extend_from_slice(&pts[2..]);
    } else if horiz && (to.1 - e.1).abs() > EPS {
        out.push((to.0, q.1));
        out.extend_from_slice(&pts[1..]);
    } else if vert && (to.0 - e.0).abs() > EPS {
        out.push((q.0, to.1));
        out.extend_from_slice(&pts[1..]);
    } else {
        out.extend_from_slice(&pts[1..]);
    }
    out
}

/// Drop zero-length segments, merge straight runs, drop wires of one point.
pub fn tidy(d: &mut Drawing) {
    for w in d.wires.iter_mut() {
        let mut out: Vec<Pt> = Vec::with_capacity(w.len());
        for &p in w.iter() {
            if out.last().is_none_or(|&q| !same(q, p)) {
                out.push((round4(p.0), round4(p.1)));
            }
        }
        let mut i = 1;
        while i + 1 < out.len() {
            let (a, b, c) = (out[i - 1], out[i], out[i + 1]);
            if ((b.0 - a.0) * (c.1 - b.1) - (b.1 - a.1) * (c.0 - b.0)).abs() < EPS {
                out.remove(i);
            } else {
                i += 1;
            }
        }
        *w = out;
    }
    d.wires.retain(|w| w.len() >= 2);
}

/// Move `sel` by (dx, dy) (snapped to the grid); wires attached to it follow.
pub fn move_items(d: &mut Drawing, sel: &Sel, dx: f64, dy: f64) {
    let (dx, dy) = (snap(dx), snap(dy));
    if dx == 0.0 && dy == 0.0 {
        return;
    }
    let before = d.clone();
    let f = |p: Pt| (round4(p.0 + dx), round4(p.1 + dy));
    for r in &sel.symbols {
        if let Some(s) = d.symbol_mut(r) {
            for (_, pl) in s.units.iter_mut() {
                pl.x = round4(pl.x + dx);
                pl.y = round4(pl.y + dy);
            }
        }
    }
    for &i in &sel.wires {
        for p in d.wires[i].iter_mut() {
            *p = f(*p);
        }
    }
    for &i in &sel.labels {
        let l = &mut d.labels[i];
        (l.x, l.y) = f((l.x, l.y));
    }
    for &i in &sel.grounds {
        let g = &mut d.grounds[i];
        (g.x, g.y) = f((g.x, g.y));
    }
    for &i in &sel.frames {
        let fr = &mut d.frames[i];
        fr.x = round4(fr.x + dx);
        fr.y = round4(fr.y + dy);
    }
    let moves = moved_points(d, sel, f, &before);
    reattach(d, sel, &moves);
}

/// Rotate (90 degrees counter-clockwise) or mirror each selected symbol about its own
/// origin, and labels and grounds in place; attached wires follow.
pub fn turn_items(d: &mut Drawing, sel: &Sel, mirror: bool) {
    let before = d.clone();
    for r in &sel.symbols {
        if let Some(s) = d.symbol_mut(r) {
            for (_, pl) in s.units.iter_mut() {
                if mirror {
                    pl.mirror = !pl.mirror;
                } else {
                    pl.rot = (pl.rot + 90) % 360;
                }
            }
        }
    }
    let step = if mirror { 180 } else { 90 };
    for &i in &sel.labels {
        d.labels[i].rot = (d.labels[i].rot + step) % 360;
    }
    for &i in &sel.grounds {
        d.grounds[i].rot = (d.grounds[i].rot + step) % 360;
    }
    let parts = Sel {
        symbols: sel.symbols.clone(),
        ..Sel::default()
    };
    let moves = moved_points(d, &parts, |p| p, &before);
    let keep = Sel {
        wires: Vec::new(),
        ..sel.clone()
    };
    reattach(d, &keep, &moves);
}

fn drop_indexes<T>(v: &mut Vec<T>, idx: &[usize]) {
    let mut i = 0;
    v.retain(|_| {
        let keep = !idx.contains(&i);
        i += 1;
        keep
    });
}

/// Remove `sel` (whole symbols, wires, labels, grounds; frames only, their contents
/// stay).
pub fn delete_items(d: &mut Drawing, sel: &Sel) {
    d.symbols.retain(|(r, _)| !sel.symbols.contains(r));
    drop_indexes(&mut d.wires, &sel.wires);
    drop_indexes(&mut d.labels, &sel.labels);
    drop_indexes(&mut d.grounds, &sel.grounds);
    drop_indexes(&mut d.frames, &sel.frames);
}

/// Remove one unit of a multi-unit symbol (the whole symbol when it is the last).
pub fn delete_unit(d: &mut Drawing, r: &str, unit: i64) {
    if let Some(s) = d.symbol_mut(r) {
        s.units.retain(|(u, _)| *u != unit);
        if s.units.is_empty() {
            d.symbols.retain(|(x, _)| x != r);
        }
    }
}

// --- Copy and paste -----------------------------------------------------------------------

/// Copied items, positioned relative to their top-left corner.
#[derive(Debug, Clone, PartialEq)]
pub struct Clip {
    pub symbols: Vec<(String, Symbol)>,
    pub wires: Vec<Vec<Pt>>,
    pub labels: Vec<Label>,
    pub grounds: Vec<Placement>,
}

/// The selection as a clipboard. Wires come along when both their ends are in it or on
/// its parts' pins.
pub fn copy_items(d: &Drawing, sel: &Sel) -> Option<Clip> {
    let pts = sel_points(d, sel);
    if pts.is_empty() {
        return None;
    }
    let ox = snap(pts.iter().map(|p| p.0).fold(f64::INFINITY, f64::min));
    let oy = snap(pts.iter().map(|p| p.1).fold(f64::INFINITY, f64::min));
    let mut pin_keys = std::collections::HashSet::new();
    for r in &sel.symbols {
        if let Some(s) = d.symbol(r) {
            for (u, _) in &s.units {
                pin_keys.extend(pin_points(s, *u).into_iter().map(|(_, p)| key(p)));
            }
        }
    }
    let mut wires = sel.wires.clone();
    for (i, w) in d.wires.iter().enumerate() {
        let ends = pin_keys.contains(&key(w[0])) && pin_keys.contains(&key(w[w.len() - 1]));
        if ends && !wires.contains(&i) {
            wires.push(i);
        }
    }
    let rel = |(x, y): Pt| (round4(x - ox), round4(y - oy));
    Some(Clip {
        symbols: sel
            .symbols
            .iter()
            .filter_map(|r| {
                let mut s = d.symbol(r)?.clone();
                for (_, pl) in s.units.iter_mut() {
                    (pl.x, pl.y) = rel((pl.x, pl.y));
                }
                Some((r.clone(), s))
            })
            .collect(),
        wires: wires
            .iter()
            .map(|&i| d.wires[i].iter().map(|&p| rel(p)).collect())
            .collect(),
        labels: sel
            .labels
            .iter()
            .map(|&i| {
                let l = &d.labels[i];
                let (x, y) = rel((l.x, l.y));
                Label { x, y, ..l.clone() }
            })
            .collect(),
        grounds: sel
            .grounds
            .iter()
            .map(|&i| {
                let g = d.grounds[i];
                let (x, y) = rel((g.x, g.y));
                Placement { x, y, ..g }
            })
            .collect(),
    })
}

/// Paste a clipboard with its top-left corner at (x, y); parts get new references (their
/// fields, a shared Param included, are copied). Returns the pasted selection.
pub fn paste_items(d: &mut Drawing, clip: &Clip, x: f64, y: f64) -> Sel {
    let (x, y) = (snap(x), snap(y));
    let mut sel = Sel::default();
    let mut names: Vec<(String, String)> = Vec::new();
    for (r, s) in &clip.symbols {
        let letters: String = r
            .chars()
            .take_while(|c| c.is_ascii_alphabetic() || *c == '_')
            .collect();
        let prefix = if letters.is_empty() {
            symbols::get(&s.symbol)
                .map_or("X", |sym| sym.prefix)
                .to_string()
        } else {
            letters
        };
        let new = next_ref(d, &prefix);
        names.push((r.clone(), new.clone()));
        let mut c = s.clone();
        for (_, pl) in c.units.iter_mut() {
            pl.x = round4(pl.x + x);
            pl.y = round4(pl.y + y);
        }
        d.symbols.push((new.clone(), c));
        sel.symbols.push(new);
    }
    // A pasted winding names its pasted core, when the core came along.
    for r in &sel.symbols {
        let s = d.symbol_mut(r).expect("pasted");
        if let Some(t) = s.field("Transformer").map(str::to_string)
            && let Some((_, new)) = names.iter().find(|(old, _)| *old == t)
        {
            s.set_field("Transformer", new);
        }
    }
    let at = |(px, py): Pt| (round4(px + x), round4(py + y));
    for w in &clip.wires {
        sel.wires.push(d.wires.len());
        d.wires.push(w.iter().map(|&p| at(p)).collect());
    }
    for l in &clip.labels {
        sel.labels.push(d.labels.len());
        let (lx, ly) = at((l.x, l.y));
        d.labels.push(Label {
            x: lx,
            y: ly,
            ..l.clone()
        });
    }
    for g in &clip.grounds {
        sel.grounds.push(d.grounds.len());
        let (gx, gy) = at((g.x, g.y));
        d.grounds.push(Placement { x: gx, y: gy, ..*g });
    }
    sel
}

// --- Wires ---------------------------------------------------------------------------------

/// The L-shaped route from a to b: horizontal first, or vertical first.
pub fn route(a: Pt, b: Pt, horizontal_first: bool) -> Vec<Pt> {
    if (a.0 - b.0).abs() < EPS || (a.1 - b.1).abs() < EPS {
        return vec![a, b];
    }
    if horizontal_first {
        vec![a, (b.0, a.1), b]
    } else {
        vec![a, (a.0, b.1), b]
    }
}

/// Add a wire through `pts` (snapped, tidied); its index, or None when it is empty.
pub fn add_wire(d: &mut Drawing, pts: &[Pt]) -> Option<usize> {
    d.wires
        .push(pts.iter().map(|&(x, y)| (snap(x), snap(y))).collect());
    let n = d.wires.len();
    tidy(d);
    (d.wires.len() == n).then(|| n - 1)
}

/// A part's name: a letter, then letters, digits and _.
pub fn valid_ref(r: &str) -> bool {
    let mut c = r.chars();
    c.next().is_some_and(|f| f.is_ascii_alphabetic())
        && c.all(|x| x.is_ascii_alphanumeric() || x == '_')
}

/// Rename a part; windings naming a renamed core follow. False when the name is taken.
pub fn rename_ref(d: &mut Drawing, from: &str, to: &str) -> bool {
    if from == to {
        return true;
    }
    if !valid_ref(to) || d.symbol(to).is_some() {
        return false;
    }
    for (r, _) in d.symbols.iter_mut() {
        if r == from {
            *r = to.to_string();
        }
    }
    for (_, s) in d.symbols.iter_mut() {
        if s.field("Transformer") == Some(from) {
            s.set_field("Transformer", to);
        }
    }
    true
}

/// Drag segment `j` of wire `wi` sideways by (dx, dy): a horizontal segment moves up or
/// down, a vertical one left or right; the wire's ends stay put (a jog is added at an end
/// that moved), and wires ending on a moved corner follow it.
pub fn drag_segment(d: &mut Drawing, wi: usize, j: usize, dx: f64, dy: f64) {
    let w = d.wires[wi].clone();
    let (a, b) = (w[j], w[j + 1]);
    let horiz = (a.1 - b.1).abs() < EPS;
    let vert = (a.0 - b.0).abs() < EPS;
    let mx = snap(if vert || !horiz { dx } else { 0.0 });
    let my = snap(if horiz || !vert { dy } else { 0.0 });
    if mx == 0.0 && my == 0.0 {
        return;
    }
    let mut moves = HashMap::new();
    let shift = |p: Pt| (round4(p.0 + mx), round4(p.1 + my));
    let start_is_end = j == 0;
    let end_is_end = j + 1 == w.len() - 1;
    if !start_is_end {
        moves.insert(key(a), shift(a));
    }
    if !end_is_end {
        moves.insert(key(b), shift(b));
    }
    // What sits on the segment goes with it: labels, grounds, wires ending on it (T
    // junctions).
    let on_seg =
        |p: Pt| on_segment(p, a, b) && !(start_is_end && same(p, a)) && !(end_is_end && same(p, b));
    for l in d.labels.iter_mut() {
        if on_seg((l.x, l.y)) {
            (l.x, l.y) = shift((l.x, l.y));
        }
    }
    for g in d.grounds.iter_mut() {
        if on_seg((g.x, g.y)) {
            (g.x, g.y) = shift((g.x, g.y));
        }
    }
    for (i, o) in d.wires.iter().enumerate() {
        if i != wi {
            for p in [o[0], o[o.len() - 1]] {
                if on_seg(p) {
                    moves.insert(key(p), shift(p));
                }
            }
        }
    }
    let mut nw: Vec<Pt> = w[..j].to_vec();
    if start_is_end {
        nw.push(a);
    }
    nw.push(shift(a));
    nw.push(shift(b));
    if end_is_end {
        nw.push(b);
    }
    nw.extend_from_slice(&w[j + 2..]);
    d.wires[wi] = nw;
    let keep = Sel {
        wires: vec![wi],
        labels: (0..d.labels.len()).collect(),
        grounds: (0..d.grounds.len()).collect(),
        ..Sel::default()
    };
    reattach(d, &keep, &moves);
}

fn on_segment(p: Pt, a: Pt, b: Pt) -> bool {
    let cross = (b.0 - a.0) * (p.1 - a.1) - (b.1 - a.1) * (p.0 - a.0);
    if cross.abs() > EPS * 1f64.max((b.0 - a.0).hypot(b.1 - a.1)) {
        return false;
    }
    p.0 >= a.0.min(b.0) - EPS
        && p.0 <= a.0.max(b.0) + EPS
        && p.1 >= a.1.min(b.1) - EPS
        && p.1 <= a.1.max(b.1) + EPS
}

#[cfg(test)]
mod tests {
    //! tests/editor_js/geom.test.mjs, ported.
    use super::*;

    fn pin(d: &Drawing, r: &str, unit: i64, n: &str) -> Pt {
        pin_points(d.symbol(r).unwrap(), unit)
            .into_iter()
            .find(|(m, _)| m == n)
            .unwrap()
            .1
    }

    fn orthogonal(w: &[Pt]) -> bool {
        w.windows(2).all(|p| p[0].0 == p[1].0 || p[0].1 == p[1].1)
    }

    #[test]
    fn snapping_and_references() {
        assert_eq!(snap(3.9), 3.81);
        assert_eq!(snap(-0.7), -1.27);
        let mut d = Drawing::default();
        assert_eq!(
            place_symbol(&mut d, "R", 10.0, 10.0, 0, false).unwrap(),
            "R1"
        );
        assert_eq!(
            place_symbol(&mut d, "R", 20.0, 10.0, 0, false).unwrap(),
            "R2"
        );
        assert_eq!(
            place_symbol(&mut d, "C", 30.0, 10.0, 0, false).unwrap(),
            "C1"
        );
        assert_eq!(
            place_symbol(&mut d, "Triode_Dual", 40.0, 10.0, 0, false).unwrap(),
            "V1"
        );
        let units: Vec<i64> = d.symbol("V1").unwrap().units.iter().map(|u| u.0).collect();
        assert_eq!(units, [1, 2]);
        assert_eq!(next_ref(&d, "R"), "R3");
        let pl = d.symbol("R1").unwrap().unit(1).unwrap();
        assert_eq!((pl.x, pl.y, pl.rot, pl.mirror), (10.16, 10.16, 0, false));
    }

    #[test]
    fn a_wire_on_a_moved_pin_follows_it_and_keeps_its_direction() {
        let mut d = Drawing::default();
        place_symbol(&mut d, "R", 0.0, 0.0, 0, false); // pins at (0, -3.81), (0, 3.81)
        place_symbol(&mut d, "R", 20.32, 0.0, 0, false);
        add_wire(
            &mut d,
            &[(0.0, 3.81), (0.0, 7.62), (20.32, 7.62), (20.32, 3.81)],
        );
        move_items(&mut d, &Sel::symbol("R1"), 2.54, -2.54);
        let p = pin(&d, "R1", 1, "2");
        assert_eq!(p, (2.54, 1.27));
        let w = &d.wires[0];
        assert_eq!(w[0], p); // the end followed the pin
        assert_eq!(w[0].0, w[1].0); // the first segment is still vertical
        assert_eq!(*w.last().unwrap(), (20.32, 3.81)); // the far end stayed
        assert!(orthogonal(w));
    }

    #[test]
    fn a_straight_wire_bends_at_the_moved_end() {
        let mut d = Drawing::default();
        place_symbol(&mut d, "R", 0.0, 0.0, 0, false);
        add_wire(&mut d, &[(0.0, 3.81), (0.0, 12.7)]);
        move_items(&mut d, &Sel::symbol("R1"), 5.08, 0.0);
        assert_eq!(d.wires[0], [(5.08, 3.81), (0.0, 3.81), (0.0, 12.7)]);
    }

    #[test]
    fn rotating_a_part_moves_its_pins_and_their_wires() {
        let mut d = Drawing::default();
        place_symbol(&mut d, "R", 0.0, 0.0, 0, false);
        add_wire(&mut d, &[(0.0, 3.81), (0.0, 10.16)]);
        turn_items(&mut d, &Sel::symbol("R1"), false);
        assert_eq!(d.symbol("R1").unwrap().unit(1).unwrap().rot, 90);
        let p2 = pin(&d, "R1", 1, "2");
        assert_eq!(p2, (3.81, 0.0)); // counter-clockwise: down becomes right
        assert_eq!(d.wires[0][0], p2);
        turn_items(&mut d, &Sel::symbol("R1"), true);
        assert!(d.symbol("R1").unwrap().unit(1).unwrap().mirror);
    }

    #[test]
    fn box_selection_delete_tidy() {
        let mut d = Drawing::default();
        place_symbol(&mut d, "R", 0.0, 0.0, 0, false);
        place_symbol(&mut d, "R", 50.0, 0.0, 0, false);
        add_wire(&mut d, &[(0.0, 3.81), (0.0, 6.35), (0.0, 8.89)]);
        assert_eq!(d.wires[0], [(0.0, 3.81), (0.0, 8.89)]);
        d.labels.push(Label {
            name: "a".into(),
            x: 0.0,
            y: 8.89,
            rot: 0,
        });
        let sel = select_box(&d, [-5.0, -5.0, 5.0, 10.0]);
        assert_eq!(sel.symbols, ["R1"]);
        assert_eq!(sel.wires, [0]);
        assert_eq!(sel.labels, [0]);
        delete_items(&mut d, &sel);
        assert_eq!(d.symbols.len(), 1);
        assert_eq!(d.symbols[0].0, "R2");
        assert!(d.wires.is_empty());
        d.wires = vec![vec![(0.0, 0.0), (0.0, 0.0)]];
        tidy(&mut d);
        assert!(d.wires.is_empty());
    }

    #[test]
    fn copy_and_paste_renumber_parts_and_keep_their_wiring_and_windings() {
        let mut d = Drawing::default();
        place_symbol(&mut d, "R", 0.0, 0.0, 0, false);
        place_symbol(&mut d, "C", 10.16, 0.0, 0, false);
        add_wire(&mut d, &[(0.0, 3.81), (10.16, 3.81)]); // R1.2 to C1.2
        d.symbol_mut("R1").unwrap().fields = vec![
            ("Param".into(), "r_x".into()),
            ("Source".into(), "s".into()),
        ];
        place_symbol(&mut d, "Core", 30.0, 0.0, 0, false);
        place_symbol(&mut d, "Winding", 35.0, 0.0, 0, false);
        d.symbol_mut("W1").unwrap().set_field("Transformer", "T1");
        let sel = Sel {
            symbols: vec!["R1".into(), "C1".into(), "T1".into(), "W1".into()],
            ..Sel::default()
        };
        let clip = copy_items(&d, &sel).unwrap();
        assert_eq!(clip.wires.len(), 1); // between two copied pins
        let got = paste_items(&mut d, &clip, 0.0, 25.4);
        assert_eq!(got.symbols, ["R2", "C2", "T2", "W2"]);
        assert_eq!(d.symbol("R2").unwrap().field("Param"), Some("r_x"));
        assert_eq!(d.symbol("W2").unwrap().field("Transformer"), Some("T2"));
        assert_eq!(d.wires[got.wires[0]], [(0.0, 29.21), (10.16, 29.21)]);
    }

    #[test]
    fn routes_and_renames() {
        assert_eq!(
            route((0.0, 0.0), (5.0, 5.0), true),
            [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0)]
        );
        assert_eq!(
            route((0.0, 0.0), (5.0, 5.0), false),
            [(0.0, 0.0), (0.0, 5.0), (5.0, 5.0)]
        );
        assert_eq!(
            route((0.0, 0.0), (0.0, 5.0), true),
            [(0.0, 0.0), (0.0, 5.0)]
        );
        let mut d = Drawing::default();
        place_symbol(&mut d, "Core", 0.0, 0.0, 0, false);
        place_symbol(&mut d, "Winding", 5.0, 0.0, 0, false);
        d.symbol_mut("W1").unwrap().set_field("Transformer", "T1");
        assert!(rename_ref(&mut d, "T1", "T9"));
        assert_eq!(d.symbol("W1").unwrap().field("Transformer"), Some("T9"));
        assert!(!rename_ref(&mut d, "W1", "T9"));
        assert!(!rename_ref(&mut d, "W1", "9x"));
    }

    #[test]
    fn dragging_a_wire_segment_sideways_keeps_its_ends() {
        let mut d = Drawing::default();
        place_symbol(&mut d, "R", 0.0, 0.0, 0, false);
        place_symbol(&mut d, "R", 20.32, 0.0, 0, false);
        add_wire(
            &mut d,
            &[(0.0, 3.81), (0.0, 7.62), (20.32, 7.62), (20.32, 3.81)],
        );
        drag_segment(&mut d, 0, 1, 3.0, 5.08); // the middle segment down by 5.08
        assert_eq!(
            d.wires[0],
            [(0.0, 3.81), (0.0, 12.7), (20.32, 12.7), (20.32, 3.81)]
        );
        drag_segment(&mut d, 0, 0, 2.54, 0.0); // the first (vertical) segment
        assert_eq!(d.wires[0][0], (0.0, 3.81));
        assert_eq!(d.wires[0][1], (2.54, 3.81));
        assert!(orthogonal(&d.wires[0]));
    }

    #[test]
    fn what_sits_on_a_dragged_segment_goes_with_it() {
        let mut d = Drawing::default();
        place_symbol(&mut d, "R", 0.0, 0.0, 0, false);
        place_symbol(&mut d, "R", 20.32, 0.0, 0, false);
        add_wire(
            &mut d,
            &[(0.0, -3.81), (0.0, -10.16), (20.32, -10.16), (20.32, -3.81)],
        );
        add_wire(&mut d, &[(10.16, -10.16), (10.16, -15.24)]); // a T on the top segment
        d.labels.push(Label {
            name: "bp".into(),
            x: 5.08,
            y: -10.16,
            rot: 0,
        });
        drag_segment(&mut d, 0, 1, 0.0, -2.54);
        assert_eq!((d.labels[0].x, d.labels[0].y), (5.08, -12.7));
        assert_eq!(d.wires[1][0], (10.16, -12.7));
        assert_eq!(d.wires[0][0], (0.0, -3.81));
    }
}
