//! The drawing laid out for painting, and what is under a point
//! (`varimu/listen/editor/view.js` without the SVG, and `varimu/editor/symbols.py`'s
//! `symbol_json`: the symbol table with y down).
//!
//! A [`Scene`] is built from a drawing and its [`Analysis`] (nets, junctions): every
//! pin's point and net, each placed unit's box, the parts' name and value texts (upright
//! whatever a symbol's rotation, as on a printed schematic), open pins, and the
//! transformer cores drawn the length of their windings. The window paints it; the tools
//! hit-test it.

use std::collections::HashMap;
use std::sync::OnceLock;

use varimu_circuit::drawing::{Drawing, Label, Placement, Symbol};
use varimu_circuit::symbols::{self, Graphic, Kind, SymbolDef};
use varimu_circuit::yaml::Value;

use super::analysis::Analysis;
use super::eng::{js_str, parse_num, to_precision, unit_of};
use super::geom::{Pt, tf};

/// A pin of the table, y down.
#[derive(Debug, Clone)]
pub struct PinDef {
    pub number: String,
    pub name: String,
    pub x: f64,
    pub y: f64,
    pub length: f64,
    /// From the connection point into the body (y down).
    pub into: Pt,
}

/// A graphic of a symbol's body, y down.
#[derive(Debug, Clone)]
pub enum Shape {
    /// An open polyline (filled: closed and filled, as SVG fills a path).
    Line {
        pts: Vec<Pt>,
        filled: bool,
    },
    /// A closed outline.
    Closed {
        pts: Vec<Pt>,
    },
    Circle {
        c: Pt,
        r: f64,
        filled: bool,
    },
    Text {
        text: &'static str,
        at: Pt,
        size: f64,
    },
}

/// A symbol as the editor draws it.
#[derive(Debug)]
pub struct SymGeom {
    pub def: &'static SymbolDef,
    pub units: Vec<Vec<PinDef>>,
    pub shapes: Vec<Shape>,
    /// Its graphics and pins: x0, y0, x1, y1.
    pub bbox: [f64; 4],
    pub text_ref: Pt,
    pub text_value: Pt,
}

fn into_of(angle: i32) -> Pt {
    match angle.rem_euclid(360) {
        90 => (0.0, -1.0),
        180 => (-1.0, 0.0),
        270 => (0.0, 1.0),
        _ => (1.0, 0.0),
    }
}

/// An arc through three points (y down), as a polyline.
fn arc_points(a: Pt, b: Pt, c: Pt) -> Vec<Pt> {
    let d = 2.0 * (a.0 * (b.1 - c.1) + b.0 * (c.1 - a.1) + c.0 * (a.1 - b.1));
    if d.abs() < 1e-12 {
        return vec![a, c];
    }
    let sq = |p: Pt| p.0 * p.0 + p.1 * p.1;
    let ux = (sq(a) * (b.1 - c.1) + sq(b) * (c.1 - a.1) + sq(c) * (a.1 - b.1)) / d;
    let uy = (sq(a) * (c.0 - b.0) + sq(b) * (a.0 - c.0) + sq(c) * (b.0 - a.0)) / d;
    let r = (a.0 - ux).hypot(a.1 - uy);
    let ang = |p: Pt| (p.1 - uy).atan2(p.0 - ux);
    let tau = std::f64::consts::TAU;
    let (a0, am, a1) = (ang(a), ang(b), ang(c));
    let sweep = (a1 - a0).rem_euclid(tau);
    let to_mid = (am - a0).rem_euclid(tau);
    let sweep = if to_mid <= sweep { sweep } else { sweep - tau };
    let n = 24;
    (0..=n)
        .map(|i| {
            let t = a0 + sweep * i as f64 / n as f64;
            (ux + r * t.cos(), uy + r * t.sin())
        })
        .collect()
}

fn sym_geom(def: &'static SymbolDef) -> SymGeom {
    let mut pts: Vec<Pt> = def.pins().map(|p| (p.x, -p.y)).collect();
    let mut shapes = Vec::new();
    for g in &def.graphics {
        match g {
            Graphic::Poly { pts: ps, filled } => {
                let ps: Vec<Pt> = ps.iter().map(|&(x, y)| (x, -y)).collect();
                pts.extend(ps.iter().copied());
                shapes.push(Shape::Line {
                    pts: ps,
                    filled: *filled,
                });
            }
            Graphic::Rect { x0, y0, x1, y1 } => {
                let (y0, y1) = (-y0, -y1);
                pts.extend([(*x0, y0), (*x1, y1)]);
                shapes.push(Shape::Closed {
                    pts: vec![(*x0, y0), (*x1, y0), (*x1, y1), (*x0, y1)],
                });
            }
            Graphic::Circle { cx, cy, r, filled } => {
                let c = (*cx, -cy);
                pts.extend([(c.0 - r, c.1 - r), (c.0 + r, c.1 + r)]);
                shapes.push(Shape::Circle {
                    c,
                    r: *r,
                    filled: *filled,
                });
            }
            Graphic::Arc { start, mid, end } => {
                let (s, m, e) = ((start.0, -start.1), (mid.0, -mid.1), (end.0, -end.1));
                pts.extend([s, m, e]);
                shapes.push(Shape::Line {
                    pts: arc_points(s, m, e),
                    filled: false,
                });
            }
            Graphic::Text { text, x, y, size } => {
                pts.push((*x, -y));
                shapes.push(Shape::Text {
                    text,
                    at: (*x, -y),
                    size: *size,
                });
            }
        }
    }
    let bbox = if pts.is_empty() {
        [-2.54, -2.54, 2.54, 2.54]
    } else {
        [
            pts.iter().map(|p| p.0).fold(f64::INFINITY, f64::min),
            pts.iter().map(|p| p.1).fold(f64::INFINITY, f64::min),
            pts.iter().map(|p| p.0).fold(f64::NEG_INFINITY, f64::max),
            pts.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max),
        ]
    };
    let (tx, try_, tyv, _) = def.text;
    SymGeom {
        def,
        units: def
            .units
            .iter()
            .map(|u| {
                u.iter()
                    .map(|p| PinDef {
                        number: p.number.clone(),
                        name: p.name.clone(),
                        x: p.x,
                        y: -p.y,
                        length: p.length,
                        into: into_of(p.angle),
                    })
                    .collect()
            })
            .collect(),
        shapes,
        bbox,
        text_ref: (tx, -try_),
        text_value: (tx, -tyv),
    }
}

/// The symbol called `name`, as the editor draws it.
pub fn geom(name: &str) -> Option<&'static SymGeom> {
    static TABLE: OnceLock<HashMap<String, SymGeom>> = OnceLock::new();
    TABLE
        .get_or_init(|| {
            symbols::all()
                .iter()
                .map(|d| (d.name.clone(), sym_geom(d)))
                .collect()
        })
        .get(name)
}

impl SymGeom {
    pub fn unit_pins(&self, unit: i64) -> &[PinDef] {
        usize::try_from(unit - 1)
            .ok()
            .and_then(|u| self.units.get(u))
            .map_or(&[], Vec::as_slice)
    }

    /// The box of a placed unit's body (its graphics, without the pins).
    fn body_box(&self, pl: &Placement) -> [f64; 4] {
        let [mut x0, mut y0, mut x1, mut y1] = self.bbox;
        for p in self.units.iter().flatten() {
            if p.into.1 == 1.0 {
                y0 = y0.max(p.y + p.length);
            }
            if p.into.1 == -1.0 {
                y1 = y1.min(p.y - p.length);
            }
            if p.into.0 == 1.0 {
                x0 = x0.max(p.x + p.length);
            }
            if p.into.0 == -1.0 {
                x1 = x1.min(p.x - p.length);
            }
        }
        corners_box([(x0, y0), (x1, y0), (x0, y1), (x1, y1)], pl)
    }
}

fn corners_box(c: [Pt; 4], pl: &Placement) -> [f64; 4] {
    let c = c.map(|(x, y)| tf(x, y, pl));
    [
        c.iter().map(|p| p.0).fold(f64::INFINITY, f64::min),
        c.iter().map(|p| p.1).fold(f64::INFINITY, f64::min),
        c.iter().map(|p| p.0).fold(f64::NEG_INFINITY, f64::max),
        c.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max),
    ]
}

pub fn union_box(a: [f64; 4], b: [f64; 4]) -> [f64; 4] {
    [
        a[0].min(b[0]),
        a[1].min(b[1]),
        a[2].max(b[2]),
        a[3].max(b[3]),
    ]
}

pub fn pad_box(b: [f64; 4], m: f64) -> [f64; 4] {
    [b[0] - m, b[1] - m, b[2] + m, b[3] + m]
}

// --- The scene ----------------------------------------------------------------------------

/// A pin on the drawing, with its net (-1: none).
#[derive(Debug, Clone)]
pub struct ScenePin {
    pub x: f64,
    pub y: f64,
    pub r: String,
    pub unit: i64,
    pub number: String,
    pub name: String,
    pub net: i64,
}

/// A placed unit: its box (with a margin), and a core's span when it is drawn the
/// length of its windings.
#[derive(Debug, Clone)]
pub struct SceneUnit {
    pub r: String,
    pub unit: i64,
    pub bbox: [f64; 4],
    pub core_span: Option<(f64, f64)>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TextKind {
    Ref,
    Value,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Anchor {
    Start,
    Middle,
    End,
}

/// A part's name or value beside it.
#[derive(Debug, Clone)]
pub struct SceneText {
    pub kind: TextKind,
    pub text: String,
    pub at: Pt,
    pub anchor: Anchor,
}

/// What is under a point.
#[derive(Debug, Clone, PartialEq)]
pub enum Hit {
    /// Index into `Scene::pins`.
    Pin {
        i: usize,
        net: i64,
    },
    /// Segment `j` (from `a` to `b`) of wire `i`.
    Wire {
        i: usize,
        j: usize,
        a: Pt,
        b: Pt,
        net: i64,
    },
    Label {
        i: usize,
        net: i64,
    },
    Ground {
        i: usize,
        net: i64,
    },
    Symbol {
        r: String,
        unit: i64,
    },
}

impl Hit {
    pub fn net(&self) -> i64 {
        match self {
            Hit::Pin { net, .. }
            | Hit::Wire { net, .. }
            | Hit::Label { net, .. }
            | Hit::Ground { net, .. } => *net,
            Hit::Symbol { .. } => -1,
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct Scene {
    /// A drawing being dragged: its nets aren't recomputed.
    pub preview: bool,
    pub wire_net: Vec<i64>,
    pub label_net: Vec<i64>,
    pub ground_net: Vec<i64>,
    pub pins: Vec<ScenePin>,
    pub units: Vec<SceneUnit>,
    /// Each part's box (all its units).
    pub boxes: HashMap<String, [f64; 4]>,
    pub texts: Vec<SceneText>,
    /// Each part's section (its frame's title, else "main").
    pub section: HashMap<String, String>,
    pub junctions: Vec<Pt>,
    /// Pins with nothing on them: what still needs a wire.
    pub open_pins: Vec<Pt>,
    label_boxes: Vec<[f64; 4]>,
}

/// A label's box, from its text's length (view.js's estimate).
fn label_box(l: &Label) -> [f64; 4] {
    let w = 0.83 * 1.35 * l.name.chars().count() as f64 + 0.6;
    match l.rot.rem_euclid(360) {
        180 => [l.x - w, l.y - 1.6, l.x + 0.4, l.y + 0.4],
        90 => [l.x - w / 2.0, l.y - 1.8, l.x + w / 2.0, l.y + 0.4],
        270 => [l.x - w / 2.0, l.y - 0.4, l.x + w / 2.0, l.y + 1.8],
        _ => [l.x - 0.4, l.y - 1.6, l.x + w, l.y + 0.4],
    }
}

impl Scene {
    /// Lay out `d`. `preview`: a drawing being dragged, `a`'s nets not for it.
    pub fn build(d: &Drawing, a: &Analysis, preview: bool) -> Scene {
        let mut sc = Scene {
            preview,
            wire_net: vec![-1; d.wires.len()],
            label_net: vec![-1; d.labels.len()],
            ground_net: vec![-1; d.grounds.len()],
            ..Scene::default()
        };
        let mut pin_net: HashMap<(String, i64, String), i64> = HashMap::new();
        if !preview {
            for (i, n) in a.nets.iter().enumerate() {
                let i = i as i64;
                for &w in &n.wires {
                    if let Some(x) = sc.wire_net.get_mut(w) {
                        *x = i;
                    }
                }
                for &l in &n.labels {
                    if let Some(x) = sc.label_net.get_mut(l) {
                        *x = i;
                    }
                }
                for &g in &n.grounds {
                    if let Some(x) = sc.ground_net.get_mut(g) {
                        *x = i;
                    }
                }
                for p in &n.pins {
                    pin_net.insert((p.reference.clone(), p.unit, p.number.clone()), i);
                }
            }
        }
        let spans = core_spans(d);
        for (r, s) in &d.symbols {
            let Some(g) = geom(&s.symbol) else { continue };
            let multi = g.units.len() > 1;
            let mut all: Option<[f64; 4]> = None;
            for (u, pl) in &s.units {
                let span = if g.def.kind == Kind::Core {
                    spans.get(r).copied()
                } else {
                    None
                };
                for p in g.unit_pins(*u) {
                    let (x, y) = tf(p.x, p.y, pl);
                    sc.pins.push(ScenePin {
                        x,
                        y,
                        r: r.clone(),
                        unit: *u,
                        number: p.number.clone(),
                        name: p.name.clone(),
                        net: pin_net
                            .get(&(r.clone(), *u, p.number.clone()))
                            .copied()
                            .unwrap_or(-1),
                    });
                }
                let b = g.bbox;
                let ub = match span {
                    Some((y0, y1)) => [pl.x - 1.1, y0 - 0.6, pl.x + 1.1, y1 + 0.6],
                    None => pad_box(
                        corners_box([(b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3])], pl),
                        0.6,
                    ),
                };
                sc.units.push(SceneUnit {
                    r: r.clone(),
                    unit: *u,
                    bbox: ub,
                    core_span: span,
                });
                all = Some(all.map_or(ub, |a| union_box(a, ub)));
                let (rl, vl) = text_for(r, s, g.def, a);
                let ref_text = if multi {
                    format!("{rl}{}", char::from(b'@' + *u as u8))
                } else {
                    rl
                };
                let body = match span {
                    Some((y0, y1)) => [pl.x - 0.508, y0, pl.x + 0.508, y1],
                    None if !g.shapes.is_empty() => g.body_box(pl),
                    None => ub,
                };
                unit_texts(g, *u, pl, body, &ref_text, &vl, &mut sc.texts);
            }
            if let Some(b) = all {
                sc.boxes.insert(r.clone(), b);
            }
        }
        if !preview {
            sc.junctions = a.junctions.clone();
            // A deck's spare contacts need no wire.
            for p in &sc.pins {
                let spare = d
                    .symbol(&p.r)
                    .and_then(|s| symbols::get(&s.symbol))
                    .is_some_and(|sym| sym.kind == Kind::Switch && p.number != "C");
                if spare {
                    continue;
                }
                let lonely = p.net < 0
                    || a.nets.get(p.net as usize).is_some_and(|n| {
                        n.pins.len() == 1 && n.labels.is_empty() && n.grounds.is_empty()
                    });
                if lonely {
                    sc.open_pins.push((p.x, p.y));
                }
            }
        }
        for (r, s) in &d.symbols {
            let Some(pl) = s.units.iter().min_by_key(|(u, _)| *u).map(|(_, p)| p) else {
                continue;
            };
            let f = d
                .frames
                .iter()
                .find(|f| pl.x >= f.x && pl.x <= f.x + f.w && pl.y >= f.y && pl.y <= f.y + f.h);
            sc.section
                .insert(r.clone(), f.map_or("main".into(), |f| f.title.clone()));
        }
        sc.label_boxes = d.labels.iter().map(label_box).collect();
        sc
    }

    /// What is at world point (x, y), within `r` mm: a pin, a wire, a label or ground
    /// (all with their net), else a symbol. `only`: kinds to consider (pin, wire, label,
    /// ground, symbol).
    pub fn hit(&self, d: &Drawing, x: f64, y: f64, r: f64, only: Option<&[&str]>) -> Option<Hit> {
        let wants = |k: &str| only.is_none_or(|o| o.contains(&k));
        let mut best: Option<Hit> = None;
        let mut best_d = f64::INFINITY;
        let mut consider = |h: Hit, dist: f64, rank: f64| {
            let s = dist + rank * r;
            if s < best_d {
                best_d = s;
                best = Some(h);
            }
        };
        if wants("pin") {
            for (i, p) in self.pins.iter().enumerate() {
                let dd = (p.x - x).hypot(p.y - y);
                if dd <= r {
                    consider(Hit::Pin { i, net: p.net }, dd, 0.0);
                }
            }
        }
        if wants("wire") {
            for (i, w) in d.wires.iter().enumerate() {
                for j in 0..w.len().saturating_sub(1) {
                    let (a, b) = (w[j], w[j + 1]);
                    if !in_box(
                        x,
                        y,
                        [a.0.min(b.0), a.1.min(b.1), a.0.max(b.0), a.1.max(b.1)],
                        r,
                    ) {
                        continue;
                    }
                    let dd = seg_dist(x, y, a, b);
                    if dd <= r {
                        let net = self.wire_net.get(i).copied().unwrap_or(-1);
                        consider(Hit::Wire { i, j, a, b, net }, dd, 0.3);
                    }
                }
            }
        }
        if wants("label") {
            for (i, b) in self.label_boxes.iter().enumerate() {
                if in_box(x, y, *b, r * 0.3) {
                    let net = self.label_net.get(i).copied().unwrap_or(-1);
                    consider(Hit::Label { i, net }, 0.0, 0.5);
                }
            }
        }
        if wants("ground") {
            for (i, g) in d.grounds.iter().enumerate() {
                let b = [g.x - 1.7, g.y - 1.7, g.x + 1.7, g.y + 1.7];
                if in_box(x, y, b, r * 0.3) {
                    let net = self.ground_net.get(i).copied().unwrap_or(-1);
                    consider(Hit::Ground { i, net }, 0.0, 0.5);
                }
            }
        }
        if wants("symbol") {
            for u in &self.units {
                if in_box(x, y, u.bbox, 0.0) {
                    consider(
                        Hit::Symbol {
                            r: u.r.clone(),
                            unit: u.unit,
                        },
                        0.0,
                        2.0,
                    );
                }
            }
        }
        best
    }

    /// A connection point near (x, y): a pin, else a wire's end or bend.
    pub fn snap_point(&self, d: &Drawing, x: f64, y: f64, r: f64) -> Option<Pt> {
        let mut best = None;
        let mut bd = r;
        for p in &self.pins {
            let dd = (p.x - x).hypot(p.y - y);
            if dd < bd {
                bd = dd;
                best = Some((p.x, p.y));
            }
        }
        if best.is_some() {
            return best;
        }
        for w in &d.wires {
            for &p in w {
                let dd = (p.0 - x).hypot(p.1 - y);
                if dd < bd {
                    bd = dd;
                    best = Some(p);
                }
            }
        }
        best
    }

    /// Everything drawn: x0, y0, x1, y1.
    pub fn bounds(&self, d: &Drawing) -> [f64; 4] {
        let mut b: Option<[f64; 4]> = None;
        let mut add = |x: [f64; 4]| b = Some(b.map_or(x, |a| union_box(a, x)));
        for f in &d.frames {
            add([f.x, f.y - 6.0, f.x + f.w, f.y + f.h]);
        }
        for bx in self.boxes.values() {
            add(*bx);
        }
        for w in &d.wires {
            for &(x, y) in w {
                add([x, y, x, y]);
            }
        }
        b.unwrap_or([-60.0, -40.0, 60.0, 40.0])
    }

    /// The box of net `i`'s wires, pins and labels.
    pub fn net_box(&self, d: &Drawing, a: &Analysis, i: usize) -> Option<[f64; 4]> {
        let n = a.nets.get(i)?;
        let mut pts: Vec<Pt> = Vec::new();
        for &w in &n.wires {
            if let Some(w) = d.wires.get(w) {
                pts.extend(w.iter().copied());
            }
        }
        pts.extend(
            self.pins
                .iter()
                .filter(|p| p.net == i as i64)
                .map(|p| (p.x, p.y)),
        );
        for &l in &n.labels {
            if let Some(l) = d.labels.get(l) {
                pts.push((l.x, l.y));
            }
        }
        pts_box(&pts)
    }

    /// The boxes of a part's units.
    pub fn unit_boxes<'a>(&'a self, r: &'a str) -> impl Iterator<Item = [f64; 4]> + 'a {
        self.units.iter().filter(move |u| u.r == r).map(|u| u.bbox)
    }
}

pub fn pts_box(pts: &[Pt]) -> Option<[f64; 4]> {
    if pts.is_empty() {
        return None;
    }
    Some([
        pts.iter().map(|p| p.0).fold(f64::INFINITY, f64::min),
        pts.iter().map(|p| p.1).fold(f64::INFINITY, f64::min),
        pts.iter().map(|p| p.0).fold(f64::NEG_INFINITY, f64::max),
        pts.iter().map(|p| p.1).fold(f64::NEG_INFINITY, f64::max),
    ])
}

fn seg_dist(x: f64, y: f64, a: Pt, b: Pt) -> f64 {
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    let l = dx * dx + dy * dy;
    let t = if l > 0.0 {
        (((x - a.0) * dx + (y - a.1) * dy) / l).clamp(0.0, 1.0)
    } else {
        0.0
    };
    (x - (a.0 + t * dx)).hypot(y - (a.1 + t * dy))
}

fn in_box(x: f64, y: f64, b: [f64; 4], m: f64) -> bool {
    x >= b[0] - m && x <= b[2] + m && y >= b[1] - m && y <= b[3] + m
}

/// A part's Value as printed next to it: "200kΩ", "250nF", "12AX7".
fn compact(value: &str, sym: &SymbolDef, a: &Analysis) -> String {
    let Some(primary) = sym.primary else {
        return value.into();
    };
    let mut k = None;
    let mut x = parse_num(value);
    if x.is_none()
        && let Some(p) = a.param(value)
    {
        k = Some(value);
        x = p.value().and_then(Value::as_f64);
    }
    let Some(x) = x else { return value.into() };
    let unit = unit_of(k, Some(primary));
    let ab = x.abs();
    const PRE: [(f64, &str); 8] = [
        (1e9, "G"),
        (1e6, "M"),
        (1e3, "k"),
        (1.0, ""),
        (1e-3, "m"),
        (1e-6, "µ"),
        (1e-9, "n"),
        (1e-12, "p"),
    ];
    let (s, p) = PRE
        .iter()
        .copied()
        .find(|(s, _)| ab >= s * 0.9995)
        .unwrap_or((1e-12, "p"));
    if ab == 0.0 {
        return format!("0{unit}");
    }
    format!("{}{p}{unit}", js_str(to_precision(x / s, 4)))
}

/// [name line, value line] of a placed symbol.
fn text_for(r: &str, s: &Symbol, sym: &SymbolDef, a: &Analysis) -> (String, String) {
    let p = |k: &str| -> Option<String> {
        let f = s.field(k)?;
        Some(match a.param(f).and_then(|p| p.value()) {
            Some(v) => v.py_str(),
            None => f.to_string(),
        })
    };
    let v = match sym.kind {
        Kind::Winding => format!("{} · {}", s.field("Transformer").unwrap_or("?"), s.value),
        Kind::Core => p("material")
            .filter(|m| !m.is_empty())
            .unwrap_or_else(|| "core".into()),
        Kind::Switch => s.field("Control").unwrap_or("").to_string(),
        _ => compact(&s.value, sym, a),
    };
    (r.to_string(), v)
}

/// A placed unit's name and value, upright, the name above the value: beside an upright
/// part (a winding's on the side away from its turns), above and below a part on its
/// side (both on the side no pin leaves from; at its upper right when pins leave up and
/// down), above an upright switch deck and beside one on its side (clear of the wires
/// into its contacts), above a core. `body`: the unit's drawn body (world).
fn unit_texts(
    g: &SymGeom,
    unit: i64,
    pl: &Placement,
    body: [f64; 4],
    ref_text: &str,
    vl: &str,
    out: &mut Vec<SceneText>,
) {
    let mut put = |kind, txt: &str, x: f64, y: f64, anchor| {
        if !txt.is_empty() {
            out.push(SceneText {
                kind,
                text: txt.into(),
                at: (x, y),
                anchor,
            });
        }
    };
    let (rk, vk) = (TextKind::Ref, TextKind::Value);
    let cx = (body[0] + body[2]) / 2.0;
    let cy = (body[1] + body[3]) / 2.0;
    let sideways = pl.rot.rem_euclid(180) == 90;
    let pins: Vec<Pt> = g.unit_pins(unit).iter().map(|p| tf(p.x, p.y, pl)).collect();
    let over = |x: f64| x > body[0] - 1e-6 && x < body[2] + 1e-6;
    let kind = g.def.kind;
    if kind == Kind::Core {
        put(rk, ref_text, cx, body[1] - 4.4, Anchor::Middle);
        put(vk, vl, cx, body[1] - 2.6, Anchor::Middle);
        return;
    }
    if kind == Kind::Switch {
        if sideways {
            put(rk, ref_text, body[2] + 1.2, cy - 0.9, Anchor::Start);
            put(vk, vl, body[2] + 1.2, cy + 0.9, Anchor::Start);
        } else {
            put(rk, ref_text, cx, body[1] - 3.3, Anchor::Middle);
            put(vk, vl, cx, body[1] - 1.5, Anchor::Middle);
        }
        return;
    }
    if sideways && (kind != Kind::Device || pins.len() <= 2) {
        let down = pins.iter().any(|&(x, y)| over(x) && y > body[3] + 1e-6);
        let up = pins.iter().any(|&(x, y)| over(x) && y < body[1] - 1e-6);
        if down && !up {
            put(rk, ref_text, cx, body[1] - 3.3, Anchor::Middle);
            put(vk, vl, cx, body[1] - 1.5, Anchor::Middle);
        } else if up && !down {
            put(rk, ref_text, cx, body[3] + 1.6, Anchor::Middle);
            put(vk, vl, cx, body[3] + 3.3, Anchor::Middle);
        } else if up && down {
            put(rk, ref_text, body[2] + 0.6, body[1] - 2.2, Anchor::Start);
            put(vk, vl, body[2] + 0.6, body[1] - 0.5, Anchor::Start);
        } else {
            put(rk, ref_text, cx, body[1] - 1.5, Anchor::Middle);
            put(vk, vl, cx, body[3] + 1.6, Anchor::Middle);
        }
        return;
    }
    let side = if kind == Kind::Winding { -1.0 } else { 1.0 };
    let (ox, oy) = tf(0.0, 0.0, pl);
    let (rx, mut ry) = tf(side * g.text_ref.0, g.text_ref.1, pl);
    let (vx, mut vy) = tf(side * g.text_value.0, g.text_value.1, pl);
    if (rx - vx).abs() < 1e-6 && ry > vy {
        std::mem::swap(&mut ry, &mut vy); // flipped: keep the name on top
    }
    for (k, txt, x, y) in [(rk, ref_text, rx, ry), (vk, vl, vx, vy)] {
        let (dx, dy) = (x - ox, y - oy);
        let horiz = dx.abs() >= dy.abs() - 1e-6;
        let anchor = if !horiz {
            Anchor::Middle
        } else if dx >= 0.0 {
            Anchor::Start
        } else {
            Anchor::End
        };
        put(k, txt, x, y, anchor);
    }
}

/// ref -> (y0, y1): an upright core's lines run the length of the windings beside it
/// (within 12 mm), as a transformer is drawn; a core with none keeps its symbol.
fn core_spans(d: &Drawing) -> HashMap<String, (f64, f64)> {
    let mut spans = HashMap::new();
    for (r, s) in &d.symbols {
        let Some(pl) = s.unit(1) else { continue };
        if symbols::get(&s.symbol).is_none_or(|x| x.kind != Kind::Core)
            || pl.rot.rem_euclid(180) != 0
        {
            continue;
        }
        let (mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY);
        for (_, w) in &d.symbols {
            let Some(wg) = geom(&w.symbol) else { continue };
            if wg.def.kind != Kind::Winding || w.field("Transformer") != Some(r.as_str()) {
                continue;
            }
            for (u, wp) in &w.units {
                for p in wg.unit_pins(*u) {
                    let (x, y) = tf(p.x, p.y, wp);
                    if (x - pl.x).abs() <= 12.0 {
                        y0 = y0.min(y);
                        y1 = y1.max(y);
                    }
                }
            }
        }
        if y0 < y1 {
            spans.insert(
                r.clone(),
                ((y0 + 1.27).min(pl.y - 5.08), (y1 - 1.27).max(pl.y + 5.08)),
            );
        }
    }
    spans
}
