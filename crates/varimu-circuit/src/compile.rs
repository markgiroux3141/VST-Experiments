//! A drawing -> a circuit file, and the pre-flight checks mapped back onto the drawing
//! (`varimu/editor/compile.py`).
//!
//! `compile_drawing` runs the connectivity (`connect`) and the importer (`importer`), so
//! a drawn circuit gets the importer's rules: a number without a source is an error,
//! switch decks resolve into `switch` parts, windings join their core, dual tubes are
//! two instances. `check_drawing` builds the circuit file's spec (from its text, as the
//! Python editor reads the file it writes) and runs `preflight` at every switch
//! combination; each problem comes back with the nets and symbols it is about.

use std::path::Path;

use crate::connect::{Connectivity, connect, netlist};
use crate::devices::Library;
use crate::drawing::Drawing;
use crate::importer::{import_netlist, set};
use crate::preflight::{Problem, check_circuit};
use crate::spec::{CircuitSpec, circuit_from_value};
use crate::symbols::{self, Kind};
use crate::yaml::{self, Map, Value};
use crate::yaml_out::to_yaml;
use crate::{Cores, Error};

/// The node renders save as their output.
pub const OUTPUT_NODE: &str = "out";
pub const GENERATED_MARK: &str = "Generated from";

#[derive(Debug, Clone)]
pub struct Compiled {
    /// The circuit file's content (None: it didn't compile).
    pub data: Option<Map>,
    /// What stopped it.
    pub errors: Vec<String>,
    /// The importer's netlist-level findings (pins without a connection).
    pub problems: Vec<String>,
    pub conn: Connectivity,
    pub warnings: Vec<String>,
}

impl Compiled {
    pub fn ok(&self) -> bool {
        self.data.is_some()
    }
}

pub fn compile_drawing(d: &Drawing, lib: &Library) -> Compiled {
    let conn = connect(d);
    if !conn.errors.is_empty() {
        return Compiled {
            data: None,
            errors: conn.errors.clone(),
            problems: Vec::new(),
            warnings: conn.warnings.clone(),
            conn,
        };
    }
    let imp = match import_netlist(&netlist(d, &conn), &d.circuit, lib) {
        Ok(i) => i,
        Err(errors) => {
            return Compiled {
                data: None,
                errors,
                problems: Vec::new(),
                warnings: conn.warnings.clone(),
                conn,
            };
        }
    };
    let mut data = imp.data;
    // Renders read node `out` from the saved probes: a drawing with an `out` node probes
    // it, whatever its probes say.
    let probes: Vec<Value> = data
        .get("probes")
        .and_then(Value::as_list)
        .map(<[Value]>::to_vec)
        .unwrap_or_default();
    let has_out = probes.iter().any(|p| p.py_str() == OUTPUT_NODE);
    if !has_out && conn.nets.iter().any(|n| n.node == OUTPUT_NODE) {
        let mut new = vec![Value::Str(OUTPUT_NODE.into())];
        new.extend(probes);
        let mut out = Map::default();
        for (k, v) in data.0 {
            if k != "probes" {
                set(&mut out, &k, v);
            }
            if k == "input" {
                set(&mut out, "probes", Value::List(new.clone()));
            }
        }
        if !out.contains("probes") {
            set(&mut out, "probes", Value::List(new));
        }
        data = out;
    }
    Compiled {
        data: Some(data),
        errors: Vec::new(),
        problems: imp.problems,
        warnings: conn.warnings.clone(),
        conn,
    }
}

/// The compiled circuit file's text, headed as generated from `origin`.
pub fn circuit_text(c: &Compiled, origin: &str) -> Result<String, Error> {
    let data = c.data.as_ref().ok_or_else(|| {
        Error(format!(
            "the drawing doesn't compile: {}",
            c.errors.join("; ")
        ))
    })?;
    Ok(to_yaml(
        data,
        &format!(
            "{GENERATED_MARK} {origin} by the schematic editor (varimu.editor): edit the \
             drawing, not this file."
        ),
    ))
}

/// The compiled circuit's spec, read back from its text (as Python reads the file it
/// writes).
pub fn compiled_spec(c: &Compiled) -> Result<CircuitSpec, Error> {
    let text = circuit_text(c, "a drawing")?;
    let v = yaml::parse(&text, "the compiled drawing")?;
    circuit_from_value(&v, Path::new("<drawing>"))
}

/// Save a drawing as circuit `name` in `dir`: `<name>.drawing.json` (the source) and
/// `<name>.yaml` (compiled, what renders read). A hand-written circuit (a .yaml without
/// a drawing) is never overwritten.
pub fn save_circuit(
    d: &Drawing,
    name: &str,
    origin: &str,
    dir: &Path,
    lib: &Library,
) -> Result<Vec<std::path::PathBuf>, Error> {
    let yaml_path = dir.join(format!("{name}.yaml"));
    let json_path = dir.join(format!("{name}.drawing.json"));
    if yaml_path.exists() && !json_path.exists() {
        return Err(Error(format!(
            "{name} is a hand-written circuit: save under a new name"
        )));
    }
    let c = compile_drawing(d, lib);
    let note = if origin.is_empty() {
        String::new()
    } else {
        format!(" (from {origin})")
    };
    let file_name = json_path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_default();
    let text = circuit_text(&c, &format!("{file_name}{note}"))?;
    crate::drawing::save_drawing(d, &json_path)?;
    std::fs::write(&yaml_path, text).map_err(|e| Error(format!("{}: {e}", yaml_path.display())))?;
    Ok(vec![json_path, yaml_path])
}

// --- Problems on the drawing ------------------------------------------------------------------

/// A problem as the editor shows it.
#[derive(Debug, Clone, PartialEq)]
pub struct Marker {
    /// unconnected | floating | loop | rectifier | probe | build | import | drawing
    pub check: String,
    pub message: String,
    pub config: String,
    /// Indexes into `Connectivity::nets`.
    pub nets: Vec<usize>,
    /// References.
    pub symbols: Vec<String>,
}

impl Marker {
    fn new(check: &str, message: &str) -> Marker {
        Marker {
            check: check.into(),
            message: message.into(),
            config: String::new(),
            nets: Vec::new(),
            symbols: Vec::new(),
        }
    }
}

/// The symbols an IR element (or a part's name) comes from: the part itself, a winding
/// (T2's `RT2_sa` is the winding labelled sa on core T2), a tube's unit (`XV1A`: V1), a
/// pot's half (`RHBa`: RHB).
pub fn element_symbols(d: &Drawing, element: &str) -> Vec<String> {
    if d.symbol(element).is_some() {
        return vec![element.into()];
    }
    let rest = element.get(1..).unwrap_or("");
    for (r, s) in &d.symbols {
        if s.symbol == "Core" && rest.starts_with(&format!("{r}_")) {
            let label = &element[r.len() + 2..];
            let label = label.strip_suffix("_lk").unwrap_or(label);
            let windings: Vec<String> = d
                .symbols
                .iter()
                .filter(|(_, w)| {
                    w.symbol == "Winding"
                        && w.field("Transformer") == Some(r.as_str())
                        && w.value == label
                })
                .map(|(wr, _)| wr.clone())
                .collect();
            return if windings.is_empty() {
                vec![r.clone()]
            } else {
                windings
            };
        }
    }
    if element.starts_with(['X', 'D']) {
        for (r, s) in &d.symbols {
            let Some(sym) = symbols::get(&s.symbol) else {
                continue;
            };
            if sym.kind != Kind::Device {
                continue;
            }
            let multi = sym.units.len() > 1;
            for (u, _) in &s.units {
                let unit = if multi {
                    char::from(b'A' + (*u - 1) as u8).to_string()
                } else {
                    String::new()
                };
                if rest == format!("{r}{unit}") {
                    return vec![r.clone()];
                }
            }
        }
    }
    d.symbols
        .iter()
        .map(|(r, _)| r)
        .filter(|r| element.starts_with(r.as_str()) || rest.starts_with(r.as_str()))
        .fold(None::<&String>, |best, r| match best {
            Some(b) if b.len() >= r.len() => Some(b),
            _ => Some(r),
        })
        .map(|r| vec![r.clone()])
        .unwrap_or_default()
}

/// `re.match(rf"{re.escape(r)}\b", e)`: `e` starts with `r` at a word boundary.
fn starts_with_word(e: &str, r: &str) -> bool {
    let Some(rest) = e.strip_prefix(r) else {
        return false;
    };
    let word = |c: char| c.is_alphanumeric() || c == '_';
    let last = r.chars().next_back();
    let next = rest.chars().next();
    match (last, next) {
        (Some(a), Some(b)) => word(a) != word(b),
        (Some(a), None) => word(a),
        _ => false,
    }
}

/// The import's errors and findings and the checks' problems, mapped onto the drawing.
pub fn markers(d: &Drawing, c: &Compiled, problems: &[Problem]) -> Vec<Marker> {
    let mut out: Vec<Marker> = c
        .warnings
        .iter()
        .map(|w| Marker::new("drawing", w))
        .collect();
    for e in &c.errors {
        let mut m = Marker::new("import", e);
        if let Some((r, _)) = d.symbols.iter().find(|(r, _)| starts_with_word(e, r)) {
            m.symbols = vec![r.clone()];
        }
        out.push(m);
    }
    for msg in &c.problems {
        let mut m = Marker::new("unconnected", msg);
        let parsed = msg
            .strip_prefix("unconnected: pin ")
            .and_then(|r| r.split_once(" of "))
            .filter(|(p, r)| !p.contains(char::is_whitespace) && !r.contains(char::is_whitespace));
        if let Some((pin, r)) = parsed {
            let name = format!("unconnected-({r}-Pad{pin})");
            if let Some(i) = c.conn.nets.iter().position(|n| n.name == name) {
                m.nets = vec![i];
            }
            m.symbols = vec![r.to_string()];
        }
        out.push(m);
    }
    for p in problems {
        let mut nets: Vec<usize> = p
            .nodes
            .iter()
            .flat_map(|n| {
                c.conn
                    .nets
                    .iter()
                    .enumerate()
                    .filter(move |(_, net)| net.node == *n)
                    .map(|(i, _)| i)
            })
            .collect();
        nets.sort_unstable();
        nets.dedup();
        let mut syms: Vec<String> = p
            .elements
            .iter()
            .flat_map(|e| element_symbols(d, e))
            .collect();
        syms.sort();
        syms.dedup();
        out.push(Marker {
            check: p.check.clone(),
            message: p.message.clone(),
            config: p.config.clone(),
            nets,
            symbols: syms,
        });
    }
    out
}

/// Compile and run the pre-flight checks; everything found, as markers.
pub fn check_drawing(d: &Drawing, lib: &Library) -> (Compiled, Vec<Marker>) {
    let c = compile_drawing(d, lib);
    if !c.ok() {
        let m = markers(d, &c, &[]);
        return (c, m);
    }
    let problems = compiled_spec(&c)
        .map_err(|e| e.to_string())
        .and_then(|spec| check_circuit(lib, &spec, &[], Cores::Linear))
        .unwrap_or_else(|e| {
            vec![Problem {
                check: "build".into(),
                message: e,
                config: String::new(),
                nodes: vec![],
                elements: vec![],
            }]
        });
    let m = markers(d, &c, &problems);
    (c, m)
}
