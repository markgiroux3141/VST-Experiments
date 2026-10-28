//! A drawing's connectivity: which pins, wires, labels and grounds are one net
//! (`varimu/editor/connect.py`), and the drawing as the netlist the importer reads.
//!
//! The rules:
//! - a pin joins every wire that passes through its connection point (at an end, a bend
//!   or mid-segment), and every other pin, label or ground at that point;
//! - a wire's end (or bend) on another wire joins them (a T junction); wires that only
//!   cross don't join;
//! - labels with the same name are one net; a ground is node 0;
//! - a label or ground joins the wire or pin at its point.
//!
//! Nets are named as kicad-cli names them (a label's name, GND, "Net-(REF-PadN)",
//! "unconnected-(REF-PadN)"), so the importer reads a drawing as it reads KiCad's.

use std::collections::{BTreeSet, HashMap};

use crate::drawing::Drawing;
use crate::symbols::{self, LIBRARY, pin_points};
use crate::values::natural_cmp;

pub const GROUND_NAME: &str = "GND";
const CELL_MM: f64 = 5.08;
const EPS: f64 = 1e-3; // mm: points closer than this are one point

#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PinRef {
    pub reference: String,
    pub unit: i64,
    pub number: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct DrawnNet {
    /// The netlist's name.
    pub name: String,
    /// The circuit node it becomes before switch resolution ("0" for ground).
    pub node: String,
    pub pins: Vec<PinRef>,
    pub wires: Vec<usize>,
    pub labels: Vec<usize>,
    pub grounds: Vec<usize>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Connectivity {
    pub nets: Vec<DrawnNet>,
    /// What stops compiling (two names on one net, unknown symbols).
    pub errors: Vec<String>,
    /// Labels and grounds that touch nothing.
    pub warnings: Vec<String>,
    pub pin_xy: Vec<(PinRef, (f64, f64))>,
    /// Where to draw a junction dot.
    pub junctions: Vec<(f64, f64)>,
    /// Wire ends that touch nothing.
    pub loose: Vec<(f64, f64)>,
}

type Key = (i64, i64);

fn key(x: f64, y: f64) -> Key {
    (
        (x / EPS).round_ties_even() as i64,
        (y / EPS).round_ties_even() as i64,
    )
}

fn on_segment(p: (f64, f64), a: (f64, f64), b: (f64, f64)) -> bool {
    let ((px, py), (ax, ay), (bx, by)) = (p, a, b);
    let dist = ((bx - ax).powi(2) + (by - ay).powi(2)).sqrt();
    if ((bx - ax) * (py - ay) - (by - ay) * (px - ax)).abs() > EPS * dist.max(1.0) {
        return false;
    }
    ax.min(bx) - EPS <= px
        && px <= ax.max(bx) + EPS
        && ay.min(by) - EPS <= py
        && py <= ay.max(by) + EPS
}

/// A wire's segment: the wire and its two ends.
type Segment = (usize, (f64, f64), (f64, f64));

/// Wire segments bucketed on a grid of cells, for point queries.
struct Segments {
    cells: HashMap<Key, Vec<Segment>>,
}

impl Segments {
    fn new(wires: &[Vec<(f64, f64)>]) -> Segments {
        let mut cells: HashMap<Key, Vec<_>> = HashMap::new();
        for (i, w) in wires.iter().enumerate() {
            let pts: Vec<(f64, f64)> = if w.len() > 1 {
                w.clone()
            } else {
                w.iter().chain(w).copied().collect()
            };
            for ab in pts.windows(2) {
                let (a, b) = (ab[0], ab[1]);
                let (x0, x1) = (a.0.min(b.0), a.0.max(b.0));
                let (y0, y1) = (a.1.min(b.1), a.1.max(b.1));
                let cx0 = ((x0 - EPS) / CELL_MM).floor() as i64;
                let cx1 = ((x1 + EPS) / CELL_MM).floor() as i64;
                let cy0 = ((y0 - EPS) / CELL_MM).floor() as i64;
                let cy1 = ((y1 + EPS) / CELL_MM).floor() as i64;
                for cx in cx0..=cx1 {
                    for cy in cy0..=cy1 {
                        cells.entry((cx, cy)).or_default().push((i, a, b));
                    }
                }
            }
        }
        Segments { cells }
    }

    fn wires_at(&self, p: (f64, f64)) -> BTreeSet<usize> {
        let cell = (
            (p.0 / CELL_MM).floor() as i64,
            (p.1 / CELL_MM).floor() as i64,
        );
        self.cells
            .get(&cell)
            .into_iter()
            .flatten()
            .filter(|(_, a, b)| on_segment(p, *a, *b))
            .map(|(i, _, _)| *i)
            .collect()
    }
}

/// What the union-find joins.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
enum Item {
    Pin(PinRef),
    Label(usize),
    Ground(usize),
    Wire(usize),
    Name(String),
}

/// Union-find with Python's dict order (keys in the order first seen) and its joins
/// (`up[root(a)] = root(b)`), so groups come out in the same order.
#[derive(Default)]
struct Union {
    index: HashMap<Item, usize>,
    items: Vec<Item>,
    up: Vec<usize>,
}

impl Union {
    fn id(&mut self, x: &Item) -> usize {
        if let Some(&i) = self.index.get(x) {
            return i;
        }
        let i = self.items.len();
        self.index.insert(x.clone(), i);
        self.items.push(x.clone());
        self.up.push(i);
        i
    }

    fn find_id(&mut self, mut i: usize) -> usize {
        while self.up[i] != i {
            self.up[i] = self.up[self.up[i]];
            i = self.up[i];
        }
        i
    }

    fn find(&mut self, x: &Item) -> usize {
        let i = self.id(x);
        self.find_id(i)
    }

    fn join(&mut self, a: &Item, b: &Item) {
        let (ra, rb) = (self.find(a), self.find(b));
        if ra != rb {
            self.up[ra] = rb;
        }
    }
}

/// An ordered map from points (Python's dict of points).
#[derive(Default)]
struct PointMap<T> {
    keys: Vec<Key>,
    map: HashMap<Key, T>,
}

impl<T: Default> PointMap<T> {
    fn entry(&mut self, k: Key) -> &mut T {
        if !self.map.contains_key(&k) {
            self.keys.push(k);
        }
        self.map.entry(k).or_default()
    }
}

/// Python's `f"{x:g}"`.
pub fn fmt_g(x: f64) -> String {
    if x == 0.0 {
        return if x.is_sign_negative() { "-0" } else { "0" }.into();
    }
    let sci = format!("{x:.5e}");
    let (mant, exp) = sci.split_once('e').expect("an exponent");
    let exp: i32 = exp.parse().expect("an exponent");
    if (-4..6).contains(&exp) {
        let decimals = (5 - exp).max(0) as usize;
        let s = format!("{x:.decimals$}");
        if s.contains('.') {
            s.trim_end_matches('0').trim_end_matches('.').to_string()
        } else {
            s
        }
    } else {
        let m = if mant.contains('.') {
            mant.trim_end_matches('0').trim_end_matches('.')
        } else {
            mant
        };
        format!("{m}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs())
    }
}

pub fn connect(d: &Drawing) -> Connectivity {
    let mut errors = Vec::new();
    let mut warnings = Vec::new();
    let mut pin_xy: Vec<(PinRef, (f64, f64))> = Vec::new();
    for (r, s) in &d.symbols {
        let Some(sym) = symbols::get(&s.symbol) else {
            errors.push(format!("{r}: no symbol '{}'", s.symbol));
            continue;
        };
        for (unit, pl) in &s.units {
            if !(1..=sym.units.len() as i64).contains(unit) {
                errors.push(format!("{r}: {} has no unit {unit}", s.symbol));
                continue;
            }
            for (num, xy) in pin_points(sym, *unit as usize, (pl.x, pl.y), pl.rot, pl.mirror) {
                let p = PinRef {
                    reference: r.clone(),
                    unit: *unit,
                    number: num,
                };
                match pin_xy.iter_mut().find(|(q, _)| *q == p) {
                    Some(e) => e.1 = xy,
                    None => pin_xy.push((p, xy)),
                }
            }
        }
    }

    let segs = Segments::new(&d.wires);
    let mut uf = Union::default();
    let mut at_point: PointMap<Vec<Item>> = PointMap::default();
    for (p, xy) in &pin_xy {
        let it = Item::Pin(p.clone());
        at_point.entry(key(xy.0, xy.1)).push(it.clone());
        uf.find(&it);
    }
    for (i, lb) in d.labels.iter().enumerate() {
        at_point.entry(key(lb.x, lb.y)).push(Item::Label(i));
        uf.join(&Item::Label(i), &Item::Name(lb.name.clone()));
    }
    for (i, g) in d.grounds.iter().enumerate() {
        at_point.entry(key(g.x, g.y)).push(Item::Ground(i));
        uf.join(&Item::Ground(i), &Item::Name(GROUND_NAME.into()));
    }
    for i in 0..d.wires.len() {
        uf.find(&Item::Wire(i));
    }

    let mut touched: HashMap<Key, usize> = HashMap::new();
    for k in at_point.keys.clone() {
        let items = at_point.map[&k].clone();
        let xy = (k.0 as f64 * EPS, k.1 as f64 * EPS);
        for it in &items[1..] {
            uf.join(&items[0], it);
        }
        let hit = segs.wires_at(xy);
        for &w in &hit {
            uf.join(&items[0], &Item::Wire(w));
        }
        if hit.is_empty() && items.len() == 1 {
            let kind = match &items[0] {
                Item::Label(i) => Some(format!("label {}", d.labels[*i].name)),
                Item::Ground(_) => Some("a ground".to_string()),
                _ => None,
            };
            if let Some(kind) = kind {
                warnings.push(format!(
                    "{kind} at ({}, {}) touches no wire or pin",
                    fmt_g(xy.0),
                    fmt_g(xy.1)
                ));
            }
        }
    }

    let mut junctions = Vec::new();
    let mut loose = Vec::new();
    let mut ends: PointMap<Vec<usize>> = PointMap::default();
    for (i, w) in d.wires.iter().enumerate() {
        let (Some(&first), Some(&last)) = (w.first(), w.last()) else {
            continue;
        };
        // A set of the two ends: one point when they are equal.
        let mut pts = vec![first];
        if last != first {
            pts.push(last);
        }
        for xy in pts {
            ends.entry(key(xy.0, xy.1)).push(i);
        }
    }
    for k in ends.keys.clone() {
        let ws = ends.map[&k].clone();
        let xy = (k.0 as f64 * EPS, k.1 as f64 * EPS);
        let hit = segs.wires_at(xy);
        for &w in &hit {
            uf.join(&Item::Wire(ws[0]), &Item::Wire(w));
        }
        let others = hit.iter().filter(|w| !ws.contains(w)).count();
        let here = at_point.map.get(&k);
        let pins_here = here.map_or(0, |v| {
            v.iter().filter(|it| matches!(it, Item::Pin(_))).count()
        });
        let n = ws.len() + 2 * others + pins_here;
        touched.insert(k, n);
        if n >= 3 {
            junctions.push(xy);
        } else if n == 1 && here.is_none_or(Vec::is_empty) {
            loose.push(xy);
        }
    }
    // A pin mid-wire is a junction too (the wire passes through it).
    for (_, xy) in &pin_xy {
        let k = key(xy.0, xy.1);
        if touched.contains_key(&k) {
            continue;
        }
        let through = segs.wires_at(*xy).into_iter().any(|w| {
            let wire = &d.wires[w];
            *xy != wire[0] && *xy != wire[wire.len() - 1]
        });
        if through {
            junctions.push(*xy);
        }
    }

    // Groups in the order of their first item (Python's dict of roots).
    let mut root_order: Vec<usize> = Vec::new();
    let mut groups: HashMap<usize, Vec<Item>> = HashMap::new();
    for i in 0..uf.items.len() {
        let r = uf.find_id(i);
        if !groups.contains_key(&r) {
            root_order.push(r);
        }
        groups.entry(r).or_default().push(uf.items[i].clone());
    }
    let mut nets = Vec::new();
    for r in root_order {
        let items = &groups[&r];
        let mut pins: Vec<PinRef> = items
            .iter()
            .filter_map(|it| match it {
                Item::Pin(p) => Some(p.clone()),
                _ => None,
            })
            .collect();
        pins.sort_by(|a, b| {
            natural_cmp(&a.reference, &b.reference)
                .then(a.unit.cmp(&b.unit))
                .then_with(|| natural_cmp(&a.number, &b.number))
        });
        let names: BTreeSet<&str> = items
            .iter()
            .filter_map(|it| match it {
                Item::Name(n) if n != GROUND_NAME => Some(n.as_str()),
                _ => None,
            })
            .collect();
        let grounded = items.contains(&Item::Name(GROUND_NAME.into()));
        let pick = |f: fn(&Item) -> Option<usize>| -> Vec<usize> {
            let mut v: Vec<usize> = items.iter().filter_map(f).collect();
            v.sort_unstable();
            v
        };
        let mut net = DrawnNet {
            name: String::new(),
            node: String::new(),
            wires: pick(|it| {
                if let Item::Wire(i) = it {
                    Some(*i)
                } else {
                    None
                }
            }),
            labels: pick(|it| {
                if let Item::Label(i) = it {
                    Some(*i)
                } else {
                    None
                }
            }),
            grounds: pick(|it| {
                if let Item::Ground(i) = it {
                    Some(*i)
                } else {
                    None
                }
            }),
            pins,
        };
        let names: Vec<&str> = names.into_iter().collect();
        if grounded && !names.is_empty() {
            errors.push(format!("label {} is on a ground net", names.join(", ")));
        } else if names.len() > 1 {
            errors.push(format!("labels {} name one net", names.join(", ")));
        }
        if grounded {
            net.name = GROUND_NAME.into();
            net.node = "0".into();
        } else if let Some(n) = names.first() {
            net.name = n.to_string();
            net.node = n.to_string();
        } else if let Some(first) = net.pins.first() {
            let kind = if net.pins.len() == 1 {
                "unconnected"
            } else {
                "Net"
            };
            net.name = format!("{kind}-({}-Pad{})", first.reference, first.number);
            net.node = format!("n_{}_{}", first.reference, first.number);
        } else {
            continue; // wires and labels without a pin: nothing to name
        }
        nets.push(net);
    }
    // Stable, as Python's sort: ground first, then nodes in natural order.
    nets.sort_by(|a, b| {
        (a.node != "0")
            .cmp(&(b.node != "0"))
            .then_with(|| natural_cmp(&a.node, &b.node))
    });
    Connectivity {
        nets,
        errors,
        warnings,
        pin_xy,
        junctions,
        loose,
    }
}

/// The frame title a symbol belongs to (its first placed unit's origin), or None.
pub fn section_of(d: &Drawing, reference: &str) -> Option<String> {
    let s = d.symbol(reference)?;
    let (_, pl) = s.units.iter().min_by_key(|(u, _)| *u)?;
    d.frame_of(pl.x, pl.y).map(|f| f.title.clone())
}

/// A component of the netlist the importer reads (`varimu.kicad.netlist.Component`).
#[derive(Debug, Clone, PartialEq)]
pub struct Component {
    pub reference: String,
    pub value: String,
    pub part: String,
    pub lib: String,
    pub sheet: String,
    /// Non-empty fields, in order.
    pub fields: Vec<(String, String)>,
    /// Unit name -> its pin numbers.
    pub units: Vec<(String, Vec<String>)>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct NetPin {
    pub reference: String,
    pub pin: String,
    pub no_connect: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Net {
    pub name: String,
    pub pins: Vec<NetPin>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Netlist {
    pub source: String,
    /// Sheet paths in page order.
    pub sheets: Vec<String>,
    /// Reference -> component, in the drawing's order.
    pub components: Vec<Component>,
    pub nets: Vec<Net>,
    pub title: String,
}

/// The drawing as the netlist the importer reads: frames are sheets (in order), a part
/// outside every frame is on the root sheet (section "main").
pub fn netlist(d: &Drawing, conn: &Connectivity) -> Netlist {
    let mut comps = Vec::new();
    for (r, s) in &d.symbols {
        let Some(sym) = symbols::get(&s.symbol) else {
            continue;
        };
        let title = section_of(d, r);
        let mut placed: Vec<i64> = s.units.iter().map(|(u, _)| *u).collect();
        placed.sort_unstable();
        placed.dedup();
        let units = placed
            .into_iter()
            .filter(|u| (1..=sym.units.len() as i64).contains(u))
            .map(|u| {
                let name = char::from(b'A' + (u - 1) as u8).to_string();
                let pins = sym.units[(u - 1) as usize]
                    .iter()
                    .map(|p| p.number.clone())
                    .collect();
                (name, pins)
            })
            .collect();
        comps.push(Component {
            reference: r.clone(),
            value: s.value.clone(),
            part: s.symbol.clone(),
            lib: LIBRARY.into(),
            sheet: title.map_or_else(|| "/".to_string(), |t| format!("/{t}/")),
            fields: s
                .fields
                .iter()
                .filter(|(_, v)| !v.trim().is_empty())
                .cloned()
                .collect(),
            units,
        });
    }
    let nets = conn
        .nets
        .iter()
        .filter(|n| !n.pins.is_empty())
        .map(|n| Net {
            name: n.name.clone(),
            pins: n
                .pins
                .iter()
                .map(|p| NetPin {
                    reference: p.reference.clone(),
                    pin: p.number.clone(),
                    no_connect: false,
                })
                .collect(),
        })
        .collect();
    let mut sheets = vec!["/".to_string()];
    sheets.extend(d.frames.iter().map(|f| format!("/{}/", f.title)));
    Netlist {
        source: "drawing".into(),
        sheets,
        components: comps,
        nets,
        title: d
            .circuit
            .get("title")
            .map(|v| v.py_str())
            .unwrap_or_default(),
    }
}
