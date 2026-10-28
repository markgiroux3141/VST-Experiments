//! The drawing document: what the editor saves (`config/circuits/<name>.drawing.json`),
//! `varimu/editor/drawing.py`'s Rust side, written byte for byte as Python writes it.
//!
//! A drawing is the source of a circuit made in the editor; compiling it writes the
//! circuit file renders read. Its JSON:
//!
//! ```text
//! {"format": "varimu-drawing", "version": 1,
//!  "circuit": {...},       // what isn't a part (the importer's sidecar keys)
//!  "frames": [{"title", "x", "y", "w", "h"}],      // the sections, in order
//!  "symbols": {"RPL1A": {"symbol": "R", "value": "200K",
//!                        "fields": {"Source": "...", ...},
//!                        "units": {"1": {"x", "y", "rot", "mirror"}}}},
//!  "wires": [[[x, y], [x, y], ...], ...],           // polylines
//!  "labels": [{"name", "x", "y", "rot"}],          // a net's name at a point
//!  "grounds": [{"x", "y", "rot"}]}                  // node 0 at a point
//! ```
//!
//! Coordinates are mm, y down, on the 1.27 mm grid (`symbols` has the placement
//! transform); written with 4 decimals, as ints when whole.

use std::path::Path;

use crate::Error;
use crate::json;
use crate::yaml::{Map, Value};

pub const FORMAT: &str = "varimu-drawing";
pub const VERSION: i64 = 1;
pub const GRID_MM: f64 = 1.27;

/// Where a symbol's unit, a ground: a point, a rotation (0, 90, 180, 270) and a mirror.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Placement {
    pub x: f64,
    pub y: f64,
    pub rot: i64,
    pub mirror: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Symbol {
    /// Its name in the symbol table (`symbols::SYMBOLS`).
    pub symbol: String,
    pub value: String,
    /// Field name -> text, in file order.
    pub fields: Vec<(String, String)>,
    /// Placed units (1-based), in order.
    pub units: Vec<(i64, Placement)>,
}

impl Symbol {
    pub fn field(&self, name: &str) -> Option<&str> {
        self.fields
            .iter()
            .find(|(k, _)| k == name)
            .map(|(_, v)| v.as_str())
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Frame {
    pub title: String,
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

impl Frame {
    pub fn contains(&self, x: f64, y: f64) -> bool {
        self.x <= x && x <= self.x + self.w && self.y <= y && y <= self.y + self.h
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct Label {
    pub name: String,
    pub x: f64,
    pub y: f64,
    pub rot: i64,
}

#[derive(Debug, Clone, PartialEq, Default)]
pub struct Drawing {
    /// What isn't a part, as the file has it.
    pub circuit: Map,
    pub frames: Vec<Frame>,
    /// Reference -> symbol, in file order.
    pub symbols: Vec<(String, Symbol)>,
    pub wires: Vec<Vec<(f64, f64)>>,
    pub labels: Vec<Label>,
    pub grounds: Vec<Placement>,
}

/// A coordinate as written: 4 decimals (the grid is 1.27 mm), an int when whole.
fn coord(x: f64) -> Value {
    let y: f64 = format!("{x:.4}").parse().expect("a number");
    if y == y.trunc() && y.abs() < 1e15 {
        Value::Int(y as i64)
    } else {
        Value::Float(y)
    }
}

fn map(entries: Vec<(&str, Value)>) -> Value {
    Value::Map(Map(entries
        .into_iter()
        .map(|(k, v)| (k.to_string(), v))
        .collect()))
}

fn placement_json(p: &Placement) -> Value {
    let mut e = vec![("x", coord(p.x)), ("y", coord(p.y))];
    if p.rot != 0 {
        e.push(("rot", Value::Int(p.rot)));
    }
    if p.mirror {
        e.push(("mirror", Value::Bool(true)));
    }
    map(e)
}

fn num(v: Option<&Value>, what: &str) -> Result<f64, Error> {
    v.and_then(Value::as_f64)
        .ok_or_else(|| Error(format!("drawing: {what} is not a number")))
}

fn int(v: Option<&Value>, default: i64) -> i64 {
    match v {
        Some(Value::Int(i)) => *i,
        Some(Value::Float(x)) => *x as i64,
        Some(Value::Bool(b)) => i64::from(*b),
        _ => default,
    }
}

fn truthy(v: Option<&Value>) -> bool {
    match v {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Int(i)) => *i != 0,
        Some(Value::Float(x)) => *x != 0.0,
        Some(Value::Str(s)) => !s.is_empty(),
        Some(Value::List(l)) => !l.is_empty(),
        Some(Value::Map(m)) => !m.is_empty(),
    }
}

fn place(v: &Value) -> Result<Placement, Error> {
    let m = v
        .as_map()
        .ok_or_else(|| Error("drawing: a placement is not a mapping".into()))?;
    Ok(Placement {
        x: num(m.get("x"), "x")?,
        y: num(m.get("y"), "y")?,
        rot: int(m.get("rot"), 0),
        mirror: truthy(m.get("mirror")),
    })
}

fn list<'a>(m: &'a Map, key: &str) -> &'a [Value] {
    m.get(key).and_then(Value::as_list).unwrap_or(&[])
}

impl Drawing {
    pub fn to_json(&self) -> Value {
        let frames = self
            .frames
            .iter()
            .map(|f| {
                map(vec![
                    ("title", Value::Str(f.title.clone())),
                    ("x", coord(f.x)),
                    ("y", coord(f.y)),
                    ("w", coord(f.w)),
                    ("h", coord(f.h)),
                ])
            })
            .collect();
        let symbols = self
            .symbols
            .iter()
            .map(|(r, s)| {
                let mut units = s.units.clone();
                units.sort_by_key(|(u, _)| *u);
                let fields = s
                    .fields
                    .iter()
                    .map(|(k, v)| (k.clone(), Value::Str(v.clone())))
                    .collect();
                let units = units
                    .iter()
                    .map(|(u, p)| (u.to_string(), placement_json(p)))
                    .collect();
                let v = map(vec![
                    ("symbol", Value::Str(s.symbol.clone())),
                    ("value", Value::Str(s.value.clone())),
                    ("fields", Value::Map(Map(fields))),
                    ("units", Value::Map(Map(units))),
                ]);
                (r.clone(), v)
            })
            .collect();
        let wires = self
            .wires
            .iter()
            .map(|w| {
                Value::List(
                    w.iter()
                        .map(|&(x, y)| Value::List(vec![coord(x), coord(y)]))
                        .collect(),
                )
            })
            .collect();
        let labels = self
            .labels
            .iter()
            .map(|lb| {
                let mut e = vec![
                    ("name", Value::Str(lb.name.clone())),
                    ("x", coord(lb.x)),
                    ("y", coord(lb.y)),
                ];
                if lb.rot != 0 {
                    e.push(("rot", Value::Int(lb.rot)));
                }
                map(e)
            })
            .collect();
        map(vec![
            ("format", Value::Str(FORMAT.into())),
            ("version", Value::Int(VERSION)),
            ("circuit", Value::Map(self.circuit.clone())),
            ("frames", Value::List(frames)),
            ("symbols", Value::Map(Map(symbols))),
            ("wires", Value::List(wires)),
            ("labels", Value::List(labels)),
            (
                "grounds",
                Value::List(self.grounds.iter().map(placement_json).collect()),
            ),
        ])
    }

    pub fn from_json(v: &Value) -> Result<Drawing, Error> {
        let d = v
            .as_map()
            .ok_or_else(|| Error("not a drawing (not a JSON object)".into()))?;
        let format = d.get("format").cloned().unwrap_or(Value::Null);
        if format != Value::Str(FORMAT.into()) {
            return Err(Error(format!(
                "not a drawing (format {format}, want '{FORMAT}')"
            )));
        }
        let version = d.get("version").cloned().unwrap_or(Value::Null);
        if !version.py_eq(&Value::Int(VERSION)) {
            return Err(Error(format!(
                "drawing version {}: this code reads {VERSION}",
                version.py_str()
            )));
        }
        let circuit = d
            .get("circuit")
            .and_then(Value::as_map)
            .cloned()
            .unwrap_or_default();
        let mut frames = Vec::new();
        for f in list(d, "frames") {
            let m = f
                .as_map()
                .ok_or_else(|| Error("drawing: a frame is not a mapping".into()))?;
            frames.push(Frame {
                title: m.get("title").map(Value::py_str).unwrap_or_default(),
                x: num(m.get("x"), "a frame's x")?,
                y: num(m.get("y"), "a frame's y")?,
                w: num(m.get("w"), "a frame's w")?,
                h: num(m.get("h"), "a frame's h")?,
            });
        }
        let mut symbols = Vec::new();
        if let Some(syms) = d.get("symbols").and_then(Value::as_map) {
            for (r, s) in syms.iter() {
                let m = s
                    .as_map()
                    .ok_or_else(|| Error(format!("drawing: symbol {r} is not a mapping")))?;
                let fields = m
                    .get("fields")
                    .and_then(Value::as_map)
                    .map(|f| f.iter().map(|(k, v)| (k.to_string(), v.py_str())).collect())
                    .unwrap_or_default();
                let mut units = Vec::new();
                if let Some(us) = m.get("units").and_then(Value::as_map) {
                    for (u, p) in us.iter() {
                        let n: i64 = u
                            .trim()
                            .parse()
                            .map_err(|_| Error(format!("drawing: {r}: unit {u:?}")))?;
                        units.push((n, place(p)?));
                    }
                }
                symbols.push((
                    r.to_string(),
                    Symbol {
                        symbol: m.get("symbol").map(Value::py_str).unwrap_or_default(),
                        value: m.get("value").map(Value::py_str).unwrap_or_default(),
                        fields,
                        units,
                    },
                ));
            }
        }
        let mut wires = Vec::new();
        for w in list(d, "wires") {
            let mut pts = Vec::new();
            for p in w.as_list().unwrap_or(&[]) {
                let xy = p.as_list().unwrap_or(&[]);
                pts.push((
                    num(xy.first(), "a wire's x")?,
                    num(xy.get(1), "a wire's y")?,
                ));
            }
            wires.push(pts);
        }
        let mut labels = Vec::new();
        for lb in list(d, "labels") {
            let m = lb
                .as_map()
                .ok_or_else(|| Error("drawing: a label is not a mapping".into()))?;
            labels.push(Label {
                name: m.get("name").map(Value::py_str).unwrap_or_default(),
                x: num(m.get("x"), "a label's x")?,
                y: num(m.get("y"), "a label's y")?,
                rot: int(m.get("rot"), 0),
            });
        }
        let grounds = list(d, "grounds")
            .iter()
            .map(place)
            .collect::<Result<_, _>>()?;
        Ok(Drawing {
            circuit,
            frames,
            symbols,
            wires,
            labels,
            grounds,
        })
    }

    pub fn symbol(&self, reference: &str) -> Option<&Symbol> {
        self.symbols
            .iter()
            .find(|(r, _)| r == reference)
            .map(|(_, s)| s)
    }

    pub fn frame_of(&self, x: f64, y: f64) -> Option<&Frame> {
        self.frames.iter().find(|f| f.contains(x, y))
    }

    /// The file's text (`json.dumps(indent=1, ensure_ascii=False)` and a newline).
    pub fn to_text(&self) -> String {
        json::dumps(&self.to_json(), 1) + "\n"
    }

    pub fn from_text(text: &str, what: &str) -> Result<Drawing, Error> {
        Drawing::from_json(&json::parse(text, what)?)
    }
}

pub fn load_drawing(path: &Path) -> Result<Drawing, Error> {
    let text =
        std::fs::read_to_string(path).map_err(|e| Error(format!("{}: {e}", path.display())))?;
    Drawing::from_text(&text, &path.display().to_string())
}

pub fn save_drawing(d: &Drawing, path: &Path) -> Result<(), Error> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| Error(format!("{}: {e}", dir.display())))?;
    }
    std::fs::write(path, d.to_text()).map_err(|e| Error(format!("{}: {e}", path.display())))
}
