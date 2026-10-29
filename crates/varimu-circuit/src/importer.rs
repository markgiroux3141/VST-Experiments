//! A netlist plus its sidecar -> a circuit file's content: the core of
//! `varimu/kicad/importer.py`, which a drawing compiles through (`compile`).
//!
//! The parts are the netlist's components (symbols of `symbols`), their connections its
//! nets; the sidecar (a drawing's `circuit` block) has what isn't a part. How a drawing
//! maps onto the format:
//!
//! - sections are the sheets (a drawing's frames) in order; parts on the root sheet go
//!   in a section "main";
//! - nodes are the nets' labels, GND is node 0, an unlabeled net is n_<ref>_<pin>;
//! - a part's name is its Reference; a device unit is X<ref><unit> (D<ref><unit> for a
//!   junction diode) with `devices` key <ref><unit> (or Model);
//! - a Value that is a number makes an inline `{value, source}`, or with Param a
//!   `values` entry; several parts may share a Param when they agree;
//! - rotary switch decks are resolved, not emitted: at every combination of positions a
//!   deck's common joins its selected contact, and what an open contact leaves hanging
//!   (two-terminal parts in a chain) is dropped; a part present in some combinations
//!   only becomes a `switch` sub-part with `in:` its positions;
//! - transformers: a Core symbol and the Winding symbols naming it.
//!
//! Orders, messages and the content's key order follow Python's, so the circuit file
//! written from it (`yaml_out::to_yaml`) is the same text.

use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

use circuitsim::ir::DeviceModel;

use crate::connect::Netlist;
use crate::devices::Library;
use crate::symbols::{self, Kind, LIBRARY, SymbolDef};
use crate::values::{natural_cmp, parse_eng};
use crate::yaml::{self, Map, Value};

const GROUND: &str = "0";
const GROUND_NETS: [&str; 2] = ["GND", "0"];
pub const SIDECAR_KEYS: [&str; 10] = [
    "title",
    "input",
    "probes",
    "full_scale",
    "controls",
    "values",
    "device_params",
    "derived",
    "mains",
    "tolerance",
];
const TOLERANCED: [&str; 6] = ["R", "C", "pot", "rheostat", "tapped_pot", "t_pad"];
const PRUNABLE: [&str; 7] = ["R", "C", "L", "V", "sine", "mains", "rheostat"];
const ROOT_SECTION: &str = "main";
const MAX_COMBOS: usize = 4096;

/// The circuit file's content and the netlist-level problems (pins without a
/// connection).
#[derive(Debug, Clone, PartialEq)]
pub struct Imported {
    pub data: Map,
    pub problems: Vec<String>,
}

/// Insert or replace `k` keeping its place (a Python dict assignment).
pub fn set(m: &mut Map, k: &str, v: Value) {
    match m.0.iter_mut().find(|(key, _)| key == k) {
        Some(e) => e.1 = v,
        None => m.0.push((k.to_string(), v)),
    }
}

fn remove(m: &mut Map, k: &str) -> Option<Value> {
    let i = m.0.iter().position(|(key, _)| key == k)?;
    Some(m.0.remove(i).1)
}

fn map_of(entries: Vec<(&str, Value)>) -> Map {
    Map(entries
        .into_iter()
        .map(|(k, v)| (k.to_string(), v))
        .collect())
}

/// Python's repr of a list of strings.
fn repr_list(v: &[String]) -> String {
    let items: Vec<String> = v.iter().map(|s| format!("'{s}'")).collect();
    format!("[{}]", items.join(", "))
}

fn yaml_field(text: &str) -> Result<Value, String> {
    yaml::parse(text, "field").map_err(|e| format!("field '{text}' is not YAML: {e}"))
}

fn section_title(sheet: &str) -> String {
    sheet
        .split('/')
        .rfind(|p| !p.is_empty())
        .unwrap_or(ROOT_SECTION)
        .to_string()
}

#[derive(Debug, Clone)]
enum Place {
    List,
    None,
    /// A VR tube's inner node.
    Vr(String),
    /// A transformer's windings: label -> their fields.
    Transformer(Vec<(String, Map)>),
}

/// A part before switch resolution: its entry, with nets where the format has nodes.
#[derive(Debug, Clone)]
struct Item {
    name: String,
    sheet: String,
    entry: Map,
    /// The nets it touches, in `entry`'s node order (None: an inner node).
    nets: Vec<Option<String>>,
    prunable: bool,
    place: Place,
}

#[derive(Debug, Clone)]
struct Deck {
    reference: String,
    sheet: String,
    control: String,
    common: Option<String>,
    /// Contact number -> net, in pin order.
    contacts: Vec<(i64, String)>,
}

struct Importer<'a> {
    nl: &'a Netlist,
    side: &'a Map,
    lib: &'a Library,
    errors: Vec<String>,
    problems: Vec<String>,
    items: Vec<Item>,
    decks: Vec<Deck>,
    devices: Vec<(String, Map)>,
    device_owner: HashMap<String, String>,
    param_defs: BTreeMap<String, Vec<(String, Map)>>,
    classes: Vec<(String, Vec<String>)>,
    cores: Vec<(String, String, Map)>,
    windings: Vec<(String, Vec<WindingPart>)>,
    pin_net: HashMap<(String, String), String>,
    net_size: HashMap<String, usize>,
    auto: HashSet<String>,
    /// Net name -> node, in the netlist's order.
    node_of: Vec<(String, String)>,
    commons: HashSet<String>,
}

type Fail = String;

/// A winding: its Reference, label (Value), nets (dot, other) and fields.
type WindingPart = (String, String, Vec<String>, Map);

impl Importer<'_> {
    fn node_of(&self, net: &str) -> Option<&str> {
        self.node_of
            .iter()
            .find(|(n, _)| n == net)
            .map(|(_, v)| v.as_str())
    }

    fn input(&self) -> String {
        self.side
            .get("input")
            .map_or_else(|| "in".to_string(), Value::py_str)
    }

    // --- nets ----------------------------------------------------------------------------

    fn read_nets(&mut self) {
        for net in &self.nl.nets {
            for p in &net.pins {
                self.pin_net
                    .insert((p.reference.clone(), p.pin.clone()), net.name.clone());
            }
            self.net_size.insert(net.name.clone(), net.pins.len());
            let n = &net.name;
            let node = if GROUND_NETS.contains(&n.as_str()) {
                GROUND.to_string()
            } else if n.starts_with("Net-(") || n.starts_with("unconnected-(") {
                let first = net
                    .pins
                    .iter()
                    .min_by(|a, b| {
                        natural_cmp(&a.reference, &b.reference)
                            .then_with(|| natural_cmp(&a.pin, &b.pin))
                    })
                    .expect("a net with pins");
                self.auto.insert(n.clone());
                format!("n_{}_{}", first.reference, first.pin)
            } else {
                n.rsplit('/').next().unwrap_or(n).to_string()
            };
            if node != GROUND
                && let Some((other, _)) = self.node_of.iter().find(|(_, v)| *v == node)
            {
                self.errors.push(format!(
                    "nets '{other}' and '{n}' are both node '{node}': name them apart (a \
                     global label joins them)"
                ));
            }
            match self.node_of.iter_mut().find(|(k, _)| k == n) {
                Some(e) => e.1 = node,
                None => self.node_of.push((n.clone(), node)),
            }
        }
    }

    fn net(&self, reference: &str, pin: &str) -> Result<String, Fail> {
        self.pin_net
            .get(&(reference.to_string(), pin.to_string()))
            .cloned()
            .ok_or_else(|| format!("pin {pin} is in no net"))
    }

    // --- values --------------------------------------------------------------------------

    /// The Value as a param: a key, an inline {value, source}, or a Param's key.
    fn primary(&mut self, reference: &str, fields: &Map, value: &str) -> Result<Value, Fail> {
        let field = |k: &str| fields.get(k).map(Value::py_str);
        let Some(num) = parse_eng(value) else {
            let extra: Vec<&str> = ["Param", "Source", "Genome"]
                .into_iter()
                .filter(|k| fields.contains(k))
                .collect();
            if !extra.is_empty() {
                return Err(format!(
                    "Value '{value}' is a key; {} are for a number",
                    extra.join(", ")
                ));
            }
            return Ok(Value::Str(value.into()));
        };
        if let Some(param) = field("Param") {
            let mut d = map_of(vec![("value", num)]);
            for (f, k) in [
                ("Source", "source"),
                ("Genome", "genome"),
                ("Unit", "unit"),
                ("Notes", "notes"),
            ] {
                if let Some(t) = field(f) {
                    set(&mut d, k, Value::Str(t));
                }
            }
            self.param_defs
                .entry(param.clone())
                .or_default()
                .push((reference.to_string(), d));
            return Ok(Value::Str(param));
        }
        if fields.contains("Genome") {
            return Err("Genome needs a Param (the value's key)".into());
        }
        match field("Source").filter(|s| !s.is_empty()) {
            None => Err(format!(
                "Value {value} needs a Source (or a Param defined with one)"
            )),
            Some(src) => Ok(Value::Map(map_of(vec![
                ("value", num),
                ("source", Value::Str(src)),
            ]))),
        }
    }

    /// The lowercase fields, as YAML.
    fn params(fields: &Map, skip: &[&str]) -> Result<Map, Fail> {
        let mut m = Map::default();
        for (k, v) in fields.iter() {
            if k.chars().next().is_some_and(char::is_lowercase) && !skip.contains(&k) {
                set(&mut m, k, yaml_field(&v.py_str())?);
            }
        }
        Ok(m)
    }

    // --- parts ---------------------------------------------------------------------------

    fn read_parts(&mut self) {
        let mut comps: Vec<_> = self.nl.components.iter().collect();
        comps.sort_by(|a, b| natural_cmp(&a.reference, &b.reference));
        for c in comps {
            if c.reference.starts_with('#') {
                continue;
            }
            let sym = match symbols::get(&c.part) {
                Some(s) if c.lib == LIBRARY => s,
                _ => {
                    self.errors.push(format!(
                        "{}: symbol {}:{} is not one of {LIBRARY}'s",
                        c.reference, c.lib, c.part
                    ));
                    continue;
                }
            };
            let fields = Map(c
                .fields
                .iter()
                .map(|(k, v)| (k.clone(), Value::Str(v.clone())))
                .collect());
            let r = match sym.kind {
                Kind::Macro => self.macro_part(c, sym, &fields),
                Kind::Device => self.device(c, sym, &fields),
                Kind::Winding => self.winding(c, &fields),
                Kind::Core => Importer::params(&fields, &[]).map(|p| {
                    match self.cores.iter_mut().find(|(r, _, _)| *r == c.reference) {
                        Some(e) => *e = (c.reference.clone(), c.sheet.clone(), p),
                        None => self.cores.push((c.reference.clone(), c.sheet.clone(), p)),
                    }
                }),
                Kind::Coupling => self.coupling(c, &fields),
                Kind::Switch => self.switch(c, sym, &fields),
                Kind::Power => Ok(()),
            };
            if let Err(e) = r {
                self.errors
                    .push(format!("{} ({}): {e}", c.reference, c.part));
            }
        }
        // Netlist-level: unconnected pins. A pin alone on the input or the heard output
        // (`out`, e.g. a speaker's pressure pin) is connected: the render drives or reads it.
        let input = self.input();
        for c in &self.nl.components {
            let Some(sym) = symbols::get(&c.part) else {
                continue;
            };
            if matches!(sym.kind, Kind::Switch | Kind::Power) {
                continue;
            }
            for (_, pins) in &c.units {
                for pin in pins {
                    let Some(net) = self.pin_net.get(&(c.reference.clone(), pin.clone())) else {
                        continue;
                    };
                    let end = matches!(self.node_of(net), Some(n) if n == input || n == "out");
                    if self.net_size[net] == 1 && !end {
                        self.problems
                            .push(format!("unconnected: pin {pin} of {}", c.reference));
                    }
                }
            }
        }
    }

    fn tol(
        &mut self,
        reference: &str,
        macro_: &str,
        fields: &Map,
        entry: &mut Map,
    ) -> Result<(), Fail> {
        let Some(tol) = fields.get("Tol").map(Value::py_str) else {
            return Ok(());
        };
        if tol == "none" {
            set(entry, "tolerance", Value::Str("none".into()));
        } else if TOLERANCED.contains(&macro_) {
            match self.classes.iter_mut().find(|(c, _)| *c == tol) {
                Some(e) => e.1.push(reference.into()),
                None => self.classes.push((tol, vec![reference.into()])),
            }
        } else {
            return Err(format!(
                "a {macro_} part takes no tolerance draw (Tol '{tol}')"
            ));
        }
        Ok(())
    }

    fn macro_part(
        &mut self,
        c: &crate::connect::Component,
        sym: &SymbolDef,
        f: &Map,
    ) -> Result<(), Fail> {
        let macro_ = sym.macro_.expect("a macro symbol");
        let mut nets: Vec<Option<String>> = sym
            .order
            .iter()
            .map(|p| self.net(&c.reference, p).map(Some))
            .collect::<Result<_, _>>()?;
        let mut entry = map_of(vec![(macro_, Value::Null)]);
        if let Some(primary) = sym.primary {
            let v = self.primary(&c.reference, f, &c.value)?;
            set(&mut entry, primary, v);
        }
        let skip: &[&str] = if matches!(macro_, "bridge" | "vr_tube") {
            &["device", "instance", "parallel"]
        } else {
            &[]
        };
        for (k, v) in Importer::params(f, skip)?.0 {
            set(&mut entry, &k, v);
        }
        self.tol(&c.reference, macro_, f, &mut entry)?;
        let field = |k: &str| f.get(k).map(Value::py_str);
        if macro_ == "bridge" {
            let key = field("Model").unwrap_or_else(|| c.reference.clone());
            set(&mut entry, "model", Value::Str(key.clone()));
            let mut dev = map_of(vec![("device", Value::Str(c.value.clone()))]);
            for k in ["instance", "parallel", "area"] {
                if let Some(t) = field(k) {
                    set(&mut dev, k, yaml_field(&t)?);
                }
            }
            self.add_device(&key, dev, &c.reference)?;
        } else if macro_ == "vr_tube" {
            let key = field("Model").unwrap_or_else(|| c.reference.clone());
            set(&mut entry, "model", Value::Str(key.clone()));
            let Some(device) = field("device") else {
                return Err("needs `device` (its device file)".into());
            };
            let mut dev = map_of(vec![("device", Value::Str(yaml_field(&device)?.py_str()))]);
            if let Some(t) = field("instance") {
                set(&mut dev, "instance", yaml_field(&t)?);
            }
            self.add_device(&key, dev, &c.reference)?;
            nets.insert(1, None);
            let mid = field("Mid").unwrap_or_else(|| format!("{}_mid", c.reference.to_lowercase()));
            self.items.push(Item {
                name: c.reference.clone(),
                sheet: c.sheet.clone(),
                entry,
                nets,
                prunable: false,
                place: Place::Vr(mid),
            });
            return Ok(());
        }
        self.items.push(Item {
            name: c.reference.clone(),
            sheet: c.sheet.clone(),
            entry,
            nets,
            prunable: PRUNABLE.contains(&macro_),
            place: Place::List,
        });
        Ok(())
    }

    fn add_device(&mut self, key: &str, dev: Map, reference: &str) -> Result<(), Fail> {
        if let Some((_, have)) = self.devices.iter().find(|(k, _)| k == key) {
            if *have != dev {
                return Err(format!(
                    "Model {key} is {} on {}, {} here",
                    Value::Map(have.clone()),
                    self.device_owner[key],
                    Value::Map(dev)
                ));
            }
        } else {
            self.devices.push((key.to_string(), dev));
        }
        self.device_owner
            .entry(key.to_string())
            .or_insert_with(|| reference.to_string());
        Ok(())
    }

    fn device_file(&self, value: &str) -> String {
        match self
            .side
            .get("values")
            .and_then(Value::as_map)
            .and_then(|m| m.get(value))
        {
            Some(Value::Map(e)) => e.get("value").map(Value::py_str).unwrap_or_default(),
            _ => value.to_string(),
        }
    }

    fn device(
        &mut self,
        c: &crate::connect::Component,
        sym: &SymbolDef,
        f: &Map,
    ) -> Result<(), Fail> {
        let field = |k: &str| f.get(k).map(Value::py_str);
        let tol = field("Tol");
        if let Some(t) = &tol
            && t != "tube"
            && t != "none"
        {
            return Err(format!(
                "Tol '{t}': a device takes `tube` (emission and mu draws) or none"
            ));
        }
        let base = self
            .lib
            .device(&self.device_file(&c.value))
            .map_err(|e| format!("device '{}': {e}", c.value))?;
        let letter = if matches!(base, DeviceModel::JunctionDiode(_)) {
            "D"
        } else {
            "X"
        };
        let mut dev = map_of(vec![("device", Value::Str(c.value.clone()))]);
        if tol.as_deref() == Some("tube") {
            set(&mut dev, "tolerance", Value::Str("tube".into()));
        }
        for (k, v) in Importer::params(f, &[])?.0 {
            set(&mut dev, &k, v);
        }
        for k in ["Source", "Notes"] {
            if let Some(t) = field(k) {
                set(&mut dev, &k.to_lowercase(), Value::Str(t));
            }
        }
        let multi = sym.units.len() > 1;
        let mut placed = 0;
        for (i, pins) in sym.units.iter().enumerate() {
            let unit = if multi {
                char::from(b'A' + i as u8).to_string()
            } else {
                String::new()
            };
            if !pins.iter().any(|p| {
                self.pin_net
                    .contains_key(&(c.reference.clone(), p.number.clone()))
            }) {
                continue;
            }
            placed += 1;
            let key = field("Model").unwrap_or_else(|| format!("{}{unit}", c.reference));
            self.add_device(&key, dev.clone(), &c.reference)?;
            let nets = pins
                .iter()
                .map(|p| self.net(&c.reference, &p.number).map(Some))
                .collect::<Result<_, _>>()?;
            self.items.push(Item {
                name: format!("{letter}{}{unit}", c.reference),
                sheet: c.sheet.clone(),
                entry: map_of(vec![("device", Value::Null), ("model", Value::Str(key))]),
                nets,
                prunable: false,
                place: Place::List,
            });
        }
        if placed == 0 {
            return Err("no unit is placed".into());
        }
        Ok(())
    }

    fn winding(&mut self, c: &crate::connect::Component, f: &Map) -> Result<(), Fail> {
        let Some(t) = f
            .get("Transformer")
            .map(Value::py_str)
            .filter(|t| !t.is_empty())
        else {
            return Err("needs Transformer (its core's Reference)".into());
        };
        let nets = vec![self.net(&c.reference, "1")?, self.net(&c.reference, "2")?];
        let w = (
            c.reference.clone(),
            c.value.clone(),
            nets,
            Importer::params(f, &[])?,
        );
        match self.windings.iter_mut().find(|(k, _)| *k == t) {
            Some(e) => e.1.push(w),
            None => self.windings.push((t, vec![w])),
        }
        Ok(())
    }

    fn coupling(&mut self, c: &crate::connect::Component, f: &Map) -> Result<(), Fail> {
        let inductors = Importer::params(f, &[])?
            .get("inductors")
            .cloned()
            .unwrap_or(Value::Null);
        let k = self.primary(&c.reference, f, &c.value)?;
        self.items.push(Item {
            name: c.reference.clone(),
            sheet: c.sheet.clone(),
            entry: map_of(vec![("K", inductors), ("k", k)]),
            nets: Vec::new(),
            prunable: false,
            place: Place::None,
        });
        Ok(())
    }

    fn switch(
        &mut self,
        c: &crate::connect::Component,
        sym: &SymbolDef,
        f: &Map,
    ) -> Result<(), Fail> {
        let Some(control) = f
            .get("Control")
            .map(Value::py_str)
            .filter(|t| !t.is_empty())
        else {
            return Err("needs Control (the control it follows)".into());
        };
        let mut contacts: Vec<(i64, String)> = Vec::new();
        for pin in sym.pins() {
            let net = self.pin_net.get(&(c.reference.clone(), pin.number.clone()));
            if pin.number != "C"
                && let Some(net) = net
                && self.net_size[net] > 1
            {
                let k: i64 = pin.number.parse().expect("a contact number");
                match contacts.iter_mut().find(|(n, _)| *n == k) {
                    Some(e) => e.1 = net.clone(),
                    None => contacts.push((k, net.clone())),
                }
            }
        }
        let common = self
            .pin_net
            .get(&(c.reference.clone(), "C".to_string()))
            .cloned();
        self.decks.push(Deck {
            reference: c.reference.clone(),
            sheet: c.sheet.clone(),
            control,
            common,
            contacts,
        });
        Ok(())
    }

    // --- transformers ----------------------------------------------------------------------

    fn build_transformers(&mut self) {
        let cores: BTreeSet<&str> = self.cores.iter().map(|(r, _, _)| r.as_str()).collect();
        let mut orphans: Vec<&(String, Vec<_>)> = self
            .windings
            .iter()
            .filter(|(t, _)| !cores.contains(t.as_str()))
            .collect();
        orphans.sort_by(|a, b| a.0.cmp(&b.0));
        let mut errors = Vec::new();
        for (t, ws) in orphans {
            let refs: Vec<String> = ws.iter().map(|w| w.0.clone()).collect();
            errors.push(format!(
                "windings {} name core {t}, which isn't drawn",
                repr_list(&refs)
            ));
        }
        self.errors.extend(errors);
        for (t, sheet, f) in self.cores.clone() {
            let mut ws = self
                .windings
                .iter()
                .find(|(k, _)| *k == t)
                .map(|(_, w)| w.clone())
                .unwrap_or_default();
            ws.sort_by(|a, b| natural_cmp(&a.0, &b.0));
            if ws.is_empty() {
                self.errors.push(format!("{t}: a core without windings"));
                continue;
            }
            let labels: Vec<String> = ws.iter().map(|w| w.1.clone()).collect();
            if labels.iter().collect::<HashSet<_>>().len() != labels.len() {
                self.errors.push(format!(
                    "{t}: winding labels repeat: {}",
                    repr_list(&labels)
                ));
                continue;
            }
            let mut f = f;
            let mut entry = map_of(vec![("transformer", Value::Null)]);
            let mut core = Map::default();
            for k in ["material", "area_m2", "path_m", "gap_m"] {
                if let Some(v) = remove(&mut f, k) {
                    set(&mut core, k, v);
                }
            }
            set(&mut entry, "core", Value::Map(core));
            for k in ["turns", "leakage_h"] {
                if let Some(v) = remove(&mut f, k) {
                    set(&mut entry, k, v);
                }
            }
            let mut terminals: HashMap<String, String> = HashMap::new();
            let mut nets: Vec<Option<String>> = Vec::new();
            for (_, label, wnets, _) in &ws {
                terminals.insert(format!("{label}.dot"), wnets[0].clone());
                terminals.insert(format!("{label}.other"), wnets[1].clone());
                nets.extend(wnets.iter().cloned().map(Some));
            }
            if let Some(iw) = remove(&mut f, "interwinding") {
                let mut iw = iw.as_map().cloned().unwrap_or_default();
                let term = |v: &Value| terminals.get(&v.py_str()).cloned().ok_or(v.py_str());
                let ends: Result<Vec<Value>, String> = iw
                    .get("ends")
                    .and_then(Value::as_list)
                    .unwrap_or(&[])
                    .iter()
                    .map(|e| term(e).map(Value::Str))
                    .collect();
                let to = iw.get("to").map(term);
                match (ends, to) {
                    (Ok(ends), Some(Ok(to))) => {
                        set(&mut iw, "ends", Value::List(ends));
                        set(&mut iw, "to", Value::Str(to));
                    }
                    (Err(e), _) | (_, Some(Err(e))) => {
                        self.errors.push(format!(
                            "{t}: interwinding names '{e}', not <label>.dot / .other"
                        ));
                        continue;
                    }
                    (_, None) => {
                        self.errors.push(format!(
                            "{t}: interwinding names 'to', not <label>.dot / .other"
                        ));
                        continue;
                    }
                }
                set(&mut entry, "interwinding", Value::Map(iw));
            }
            if !f.is_empty() {
                let mut keys: Vec<String> = f.keys().map(String::from).collect();
                keys.sort();
                self.errors
                    .push(format!("{t}: unknown core fields {}", repr_list(&keys)));
            }
            let windings = ws
                .iter()
                .map(|(_, label, _, wf)| (label.clone(), wf.clone()))
                .collect();
            self.items.push(Item {
                name: t.clone(),
                sheet,
                entry,
                nets,
                prunable: false,
                place: Place::Transformer(windings),
            });
        }
    }

    // --- switches --------------------------------------------------------------------------

    /// Part name -> (control, positions it is in, its nodes): (None, None, nodes) for a
    /// part that is always in.
    #[allow(clippy::type_complexity)]
    fn resolve_switches(
        &mut self,
    ) -> Result<HashMap<String, (Option<String>, Option<Vec<Value>>, Vec<Option<String>>)>, Fail>
    {
        let controls = self
            .side
            .get("controls")
            .and_then(Value::as_map)
            .cloned()
            .unwrap_or_default();
        let mut positions: BTreeMap<String, Vec<Value>> = BTreeMap::new();
        for d in &self.decks {
            let Some(e) = controls.get(&d.control).and_then(Value::as_map) else {
                self.errors.push(format!(
                    "{}: Control '{}' is not a control",
                    d.reference, d.control
                ));
                continue;
            };
            let pos: Vec<Value> = if let Some(c) = e.get("choices").and_then(Value::as_list) {
                c.to_vec()
            } else if e.get("unit").map(Value::py_str).as_deref() == Some("position") {
                let lo = e.get("min").and_then(Value::as_f64).unwrap_or(0.0) as i64;
                let hi = e.get("max").and_then(Value::as_f64).unwrap_or(0.0) as i64;
                (lo..=hi).map(Value::Int).collect()
            } else {
                self.errors.push(format!(
                    "{}: control {} has no `choices` or `unit: position`",
                    d.reference, d.control
                ));
                continue;
            };
            if let Some(max) = d.contacts.iter().map(|(k, _)| *k).max()
                && max > pos.len() as i64
            {
                self.errors.push(format!(
                    "{}: contact {max} wired, but {} has {} positions",
                    d.reference,
                    d.control,
                    pos.len()
                ));
            }
            positions.insert(d.control.clone(), pos);
        }
        if !self.errors.is_empty() {
            return Err("switches".into());
        }
        let keys: Vec<String> = positions.keys().cloned().collect();
        // itertools.product: the last key varies fastest.
        let mut combos: Vec<Vec<Value>> = vec![Vec::new()];
        for k in &keys {
            let mut next = Vec::new();
            for c in &combos {
                for p in &positions[k] {
                    let mut c = c.clone();
                    c.push(p.clone());
                    next.push(c);
                }
            }
            combos = next;
            if combos.len() > MAX_COMBOS {
                return Err(format!("{} switch combinations", combos.len()));
            }
        }
        let contact_nets: BTreeSet<String> = self
            .decks
            .iter()
            .flat_map(|d| d.contacts.iter().map(|(_, n)| n.clone()))
            .collect();
        self.commons = self.decks.iter().filter_map(|d| d.common.clone()).collect();
        let protected = self.input();
        // part -> (combo index -> nodes), in first-seen order.
        let mut seen: HashMap<String, Vec<(usize, Vec<Option<String>>)>> = HashMap::new();
        for (ci, combo) in combos.iter().enumerate() {
            let mut uf: HashMap<String, String> = HashMap::new();
            fn find(uf: &mut HashMap<String, String>, x: &str) -> String {
                let mut x = x.to_string();
                uf.entry(x.clone()).or_insert_with(|| x.clone());
                while uf[&x] != x {
                    x = uf[&x].clone();
                }
                x
            }
            for d in &self.decks {
                let Some(ki) = keys.iter().position(|k| *k == d.control) else {
                    continue;
                };
                let Some(common) = &d.common else { continue };
                let k = positions[&d.control]
                    .iter()
                    .position(|p| p.py_eq(&combo[ki]))
                    .expect("a position")
                    + 1;
                if let Some((_, net)) = d.contacts.iter().find(|(c, _)| *c == k as i64) {
                    let a = find(&mut uf, net);
                    let b = find(&mut uf, common);
                    uf.insert(a, b);
                }
            }
            let commons: HashSet<String> = self
                .decks
                .iter()
                .filter_map(|d| d.common.as_ref())
                .map(|c| find(&mut uf, c))
                .collect();
            let mut live = vec![true; self.items.len()];
            let mut degree: HashMap<String, i64> = HashMap::new();
            let mut touching: HashMap<String, Vec<usize>> = HashMap::new();
            for (i, it) in self.items.iter().enumerate() {
                for n in it.nets.iter().flatten() {
                    let r = find(&mut uf, n);
                    *degree.entry(r.clone()).or_default() += 1;
                    touching.entry(r).or_default().push(i);
                }
            }
            let mut queue: Vec<String> = contact_nets
                .iter()
                .map(|n| find(&mut uf, n))
                .collect::<BTreeSet<_>>()
                .into_iter()
                .filter(|r| !commons.contains(r) && degree.get(r).copied().unwrap_or(0) <= 1)
                .collect();
            while let Some(r) = queue.pop() {
                for &i in touching.get(&r).cloned().unwrap_or_default().iter() {
                    if !live[i] || !self.items[i].prunable {
                        continue;
                    }
                    live[i] = false;
                    for n in self.items[i].nets.iter().flatten() {
                        let rn = find(&mut uf, n);
                        let d = degree.entry(rn.clone()).or_default();
                        *d -= 1;
                        let node = self.node_of(&rn).unwrap_or("");
                        if rn != r && *d == 1 && node != GROUND && node != protected {
                            queue.push(rn);
                        }
                    }
                }
            }
            let mut groups: HashMap<String, Vec<String>> = HashMap::new();
            for (n, _) in &self.node_of {
                groups.entry(find(&mut uf, n)).or_default().push(n.clone());
            }
            let mut named: HashMap<String, String> = HashMap::new();
            for (i, it) in self.items.iter().enumerate() {
                if !live[i] {
                    continue;
                }
                let nodes = it
                    .nets
                    .iter()
                    .map(|n| {
                        n.as_ref().map(|n| {
                            let r = find(&mut uf, n);
                            named
                                .entry(r.clone())
                                .or_insert_with(|| self.merged_name(&groups[&r]))
                                .clone()
                        })
                    })
                    .collect();
                seen.entry(it.name.clone()).or_default().push((ci, nodes));
            }
        }
        let mut out = HashMap::new();
        for it in &self.items {
            let present = seen.get(&it.name).cloned().unwrap_or_default();
            if present.is_empty() {
                self.errors
                    .push(format!("{}: connected at no switch position", it.name));
                continue;
            }
            let mut sets: Vec<&Vec<Option<String>>> = Vec::new();
            for (_, n) in &present {
                if !sets.contains(&n) {
                    sets.push(n);
                }
            }
            if sets.len() > 1 {
                self.errors
                    .push(format!("{}: its nodes change with the switches", it.name));
                continue;
            }
            let nodes = sets[0].clone();
            if present.len() == combos.len() {
                out.insert(it.name.clone(), (None, None, nodes));
                continue;
            }
            let in_combo: HashSet<usize> = present.iter().map(|(c, _)| *c).collect();
            let mut dep = None;
            for (ki, k) in keys.iter().enumerate() {
                // Presence must follow this key's position alone.
                let mut f: Vec<(Value, bool)> = Vec::new();
                let consistent = combos.iter().enumerate().all(|(ci, cb)| {
                    let here = in_combo.contains(&ci);
                    match f.iter().find(|(p, _)| p.py_eq(&cb[ki])) {
                        Some((_, was)) => *was == here,
                        None => {
                            f.push((cb[ki].clone(), here));
                            true
                        }
                    }
                });
                if consistent {
                    let pos = positions[k]
                        .iter()
                        .filter(|p| f.iter().any(|(q, on)| *on && q.py_eq(p)))
                        .cloned()
                        .collect();
                    dep = Some((k.clone(), pos));
                    break;
                }
            }
            match dep {
                None => self.errors.push(format!(
                    "{}: in or out depends on several switches",
                    it.name
                )),
                Some((k, pos)) => {
                    out.insert(it.name.clone(), (Some(k), Some(pos), nodes));
                }
            }
        }
        Ok(out)
    }

    /// The node a group of joined nets becomes: ground, else a deck common's label, else
    /// any label, else the common's (or the first net's) generated name.
    fn merged_name(&self, group: &[String]) -> String {
        let node = |n: &str| self.node_of(n).unwrap_or("").to_string();
        if group.iter().any(|n| node(n) == GROUND) {
            return GROUND.into();
        }
        let mut commons: Vec<&String> =
            group.iter().filter(|n| self.commons.contains(*n)).collect();
        commons.sort();
        for n in &commons {
            if !self.auto.contains(*n) {
                return node(n);
            }
        }
        let mut labelled: Vec<String> = group
            .iter()
            .filter(|n| !self.auto.contains(*n))
            .map(|n| node(n))
            .collect();
        labelled.sort();
        if let Some(l) = labelled.first() {
            return l.clone();
        }
        let mut sorted: Vec<&String> = group.iter().collect();
        sorted.sort();
        node(commons.first().copied().unwrap_or(sorted[0]))
    }

    // --- assembly ----------------------------------------------------------------------------

    fn place(it: &Item, nodes: &[Option<String>]) -> Map {
        let mut e = it.entry.clone();
        let kind = e.0[0].0.clone();
        let node = |n: &Option<String>| n.clone().map_or(Value::Null, Value::Str);
        match &it.place {
            Place::List => set(&mut e, &kind, Value::List(nodes.iter().map(node).collect())),
            Place::None => {}
            Place::Vr(mid) => set(
                &mut e,
                &kind,
                Value::List(vec![
                    node(&nodes[0]),
                    Value::Str(mid.clone()),
                    node(&nodes[2]),
                ]),
            ),
            Place::Transformer(windings) => {
                let mut ws = Map::default();
                for (i, (label, wf)) in windings.iter().enumerate() {
                    let mut w = map_of(vec![(
                        "nodes",
                        Value::List(vec![node(&nodes[2 * i]), node(&nodes[2 * i + 1])]),
                    )]);
                    for (k, v) in wf.iter() {
                        set(&mut w, k, v.clone());
                    }
                    set(&mut ws, label, Value::Map(w));
                }
                set(&mut e, &kind, Value::Map(ws));
            }
        }
        e
    }

    fn values(&mut self) -> Map {
        let mut side = self
            .side
            .get("values")
            .and_then(Value::as_map)
            .cloned()
            .unwrap_or_default();
        let keys_of = |k: &str| -> Vec<String> {
            self.side
                .get(k)
                .and_then(Value::as_map)
                .map(|m| m.keys().map(String::from).collect())
                .unwrap_or_default()
        };
        let mut known: HashSet<String> = side.keys().map(String::from).collect();
        known.extend(keys_of("controls"));
        known.extend(keys_of("device_params"));
        if let Some(d) = self
            .side
            .get("derived")
            .and_then(Value::as_map)
            .and_then(|d| d.get("values"))
            .and_then(Value::as_map)
        {
            known.extend(d.keys().map(String::from));
        }
        for (key, defs) in &self.param_defs {
            let refs: Vec<&str> = defs.iter().map(|(r, _)| r.as_str()).collect();
            if known.contains(key) {
                self.errors.push(format!(
                    "Param {key} ({}) is also defined in the sidecar",
                    refs.join(", ")
                ));
                continue;
            }
            let first = defs[0].1.get("value").cloned().unwrap_or(Value::Null);
            if defs
                .iter()
                .any(|(_, d)| !d.get("value").is_some_and(|v| v.py_eq(&first)))
            {
                let said: Vec<String> = defs
                    .iter()
                    .map(|(r, d)| {
                        format!(
                            "{r}={}",
                            d.get("value").map(Value::py_str).unwrap_or_default()
                        )
                    })
                    .collect();
                self.errors
                    .push(format!("Param {key}: {} disagree", said.join(", ")));
                continue;
            }
            let mut merged = map_of(vec![("value", first)]);
            for k in ["source", "genome", "unit", "notes"] {
                let mut got: Vec<&Value> = Vec::new();
                for (_, d) in defs {
                    if let Some(v) = d.get(k)
                        && !got.contains(&v)
                    {
                        got.push(v);
                    }
                }
                if got.len() > 1 {
                    self.errors
                        .push(format!("Param {key}: parts disagree on its {k}"));
                } else if let Some(v) = got.first() {
                    set(&mut merged, k, (*v).clone());
                }
            }
            if !merged.contains("source") {
                self.errors.push(format!(
                    "Param {key} ({}): no part gives a Source",
                    refs.join(", ")
                ));
            }
            set(&mut side, key, Value::Map(merged));
        }
        side
    }

    fn run(mut self) -> Result<Imported, Vec<String>> {
        self.read_nets();
        self.read_parts();
        self.build_transformers();
        if !self.errors.is_empty() {
            return Err(self.errors);
        }
        let resolved = match self.resolve_switches() {
            Ok(r) => r,
            Err(e) => {
                if e != "switches" {
                    self.errors.push(e);
                }
                HashMap::new()
            }
        };
        let values = self.values();
        if !self.errors.is_empty() {
            return Err(self.errors);
        }

        let order: HashMap<&str, usize> = self
            .nl
            .sheets
            .iter()
            .enumerate()
            .map(|(i, s)| (s.as_str(), i))
            .collect();
        let mut sheets: Vec<String> = Vec::new();
        for it in &self.items {
            if !sheets.contains(&it.sheet) {
                sheets.push(it.sheet.clone());
            }
        }
        sheets.sort_by_key(|s| order.get(s.as_str()).copied().unwrap_or(order.len()));
        let mut names_used: HashSet<String> = self.items.iter().map(|i| i.name.clone()).collect();
        let mut sections = Vec::new();
        for sheet in &sheets {
            let mut its: Vec<&Item> = self.items.iter().filter(|i| i.sheet == *sheet).collect();
            its.sort_by(|a, b| natural_cmp(&a.name, &b.name));
            let mut parts: Vec<(String, Value)> = Vec::new();
            // control -> (its part's name, its sub-parts)
            let mut switched: Vec<(String, String, Map)> = Vec::new();
            let mut rows: Vec<String> = Vec::new();
            for it in its {
                let Some((ctrl, pos, nodes)) = resolved.get(&it.name).cloned() else {
                    return Err(vec![format!("{}: not resolved", it.name)]);
                };
                let e = Importer::place(it, &nodes);
                let Some(ctrl) = ctrl else {
                    parts.push((it.name.clone(), Value::Map(e)));
                    rows.push(it.name.clone());
                    continue;
                };
                if !switched.iter().any(|(c, _, _)| *c == ctrl) {
                    let mut here: Vec<&str> = self
                        .decks
                        .iter()
                        .filter(|d| d.control == ctrl && d.sheet == *sheet)
                        .map(|d| d.reference.as_str())
                        .collect();
                    let mut all: Vec<&str> = self
                        .decks
                        .iter()
                        .filter(|d| d.control == ctrl)
                        .map(|d| d.reference.as_str())
                        .collect();
                    here.sort_by(|a, b| natural_cmp(a, b));
                    all.sort_by(|a, b| natural_cmp(a, b));
                    let mut name = here
                        .first()
                        .or(all.first())
                        .copied()
                        .unwrap_or("S")
                        .to_string();
                    while names_used.contains(&name) {
                        name.push('_');
                    }
                    names_used.insert(name.clone());
                    rows.push(name.clone());
                    switched.push((ctrl.clone(), name, Map::default()));
                }
                let sw = switched
                    .iter_mut()
                    .find(|(c, _, _)| *c == ctrl)
                    .expect("added");
                let mut sub = e;
                set(&mut sub, "in", Value::List(pos.unwrap_or_default()));
                set(&mut sw.2, &it.name, Value::Map(sub));
            }
            rows.sort_by(|a, b| natural_cmp(a, b));
            let mut ordered = Map::default();
            for name in &rows {
                if let Some((_, v)) = parts.iter().find(|(n, _)| n == name) {
                    set(&mut ordered, name, v.clone());
                } else if let Some((ctrl, _, sub)) = switched.iter().find(|(_, n, _)| n == name) {
                    let sw = map_of(vec![
                        ("switch", Value::Str(ctrl.clone())),
                        ("parts", Value::Map(sub.clone())),
                    ]);
                    set(&mut ordered, name, Value::Map(sw));
                }
            }
            sections.push(Value::Map(map_of(vec![
                ("title", Value::Str(section_title(sheet))),
                ("parts", Value::Map(ordered)),
            ])));
        }

        let mut data = Map::default();
        for k in ["title", "input", "probes", "full_scale", "controls"] {
            if let Some(v) = self.side.get(k) {
                set(&mut data, k, v.clone());
            }
        }
        if !data.contains("title") {
            set(&mut data, "title", Value::Str(self.nl.title.clone()));
        }
        set(&mut data, "values", Value::Map(values));
        for k in ["device_params", "derived", "mains"] {
            if let Some(v) = self.side.get(k) {
                set(&mut data, k, v.clone());
            }
        }
        if !self.classes.is_empty() {
            let mut tol = self
                .side
                .get("tolerance")
                .and_then(Value::as_map)
                .cloned()
                .unwrap_or_default();
            if tol.is_empty() {
                let mut names: Vec<&str> = self.classes.iter().map(|(c, _)| c.as_str()).collect();
                names.sort_unstable();
                let names: Vec<String> = names.into_iter().map(String::from).collect();
                return Err(vec![format!(
                    "Tol fields name classes {}, but the sidecar has no tolerance block",
                    repr_list(&names)
                )]);
            }
            let drawn: HashSet<String> = self.classes.iter().flat_map(|(_, r)| r.clone()).collect();
            if let Some(side_classes) = tol.get("classes").and_then(Value::as_map) {
                for (c, refs) in side_classes.iter() {
                    let refs: Vec<String> = refs
                        .as_list()
                        .unwrap_or(&[])
                        .iter()
                        .map(Value::py_str)
                        .collect();
                    let mut clash: Vec<String> = refs
                        .iter()
                        .filter(|r| drawn.contains(*r))
                        .cloned()
                        .collect();
                    clash.sort();
                    clash.dedup();
                    if !clash.is_empty() {
                        return Err(vec![format!(
                            "sidecar tolerance class {c} names drawn parts {}: their Tol \
                             fields give their class",
                            repr_list(&clash)
                        )]);
                    }
                    match self.classes.iter_mut().find(|(k, _)| k == c) {
                        Some(e) => e.1.extend(refs),
                        None => self.classes.push((c.to_string(), refs)),
                    }
                }
            }
            let bands: Vec<String> = tol
                .get("bands")
                .and_then(Value::as_map)
                .map(|b| b.keys().map(String::from).collect())
                .unwrap_or_default();
            let mut cls: Vec<&(String, Vec<String>)> = self.classes.iter().collect();
            cls.sort_by(|a, b| {
                let rank = |c: &str| bands.iter().position(|x| x == c).unwrap_or(99);
                rank(&a.0).cmp(&rank(&b.0)).then_with(|| a.0.cmp(&b.0))
            });
            let mut classes = Map::default();
            for (c, refs) in cls {
                let mut refs = refs.clone();
                refs.sort_by(|a, b| natural_cmp(a, b));
                set(
                    &mut classes,
                    c,
                    Value::List(refs.into_iter().map(Value::Str).collect()),
                );
            }
            set(&mut tol, "classes", Value::Map(classes));
            set(&mut data, "tolerance", Value::Map(tol));
        } else if let Some(t) = self.side.get("tolerance") {
            set(&mut data, "tolerance", t.clone());
        }
        let mut devices = self.devices.clone();
        devices.sort_by(|a, b| natural_cmp(&a.0, &b.0));
        set(
            &mut data,
            "devices",
            Value::Map(Map(devices
                .into_iter()
                .map(|(k, v)| (k, Value::Map(v)))
                .collect())),
        );
        set(&mut data, "sections", Value::List(sections));
        Ok(Imported {
            data,
            problems: self.problems,
        })
    }
}

/// Import `nl` with its sidecar; Err: the import's errors (one per line).
pub fn import_netlist(nl: &Netlist, sidecar: &Map, lib: &Library) -> Result<Imported, Vec<String>> {
    let mut unknown: Vec<&str> = sidecar
        .keys()
        .filter(|k| !SIDECAR_KEYS.contains(k))
        .collect();
    if !unknown.is_empty() {
        unknown.sort_unstable();
        let names: Vec<String> = unknown.into_iter().map(String::from).collect();
        return Err(vec![format!(
            "sidecar: unknown keys {} ({})",
            repr_list(&names),
            SIDECAR_KEYS.join(", ")
        )]);
    }
    Importer {
        nl,
        side: sidecar,
        lib,
        errors: Vec::new(),
        problems: Vec::new(),
        items: Vec::new(),
        decks: Vec::new(),
        devices: Vec::new(),
        device_owner: HashMap::new(),
        param_defs: BTreeMap::new(),
        classes: Vec::new(),
        cores: Vec::new(),
        windings: Vec::new(),
        pin_net: HashMap::new(),
        net_size: HashMap::new(),
        auto: HashSet::new(),
        node_of: Vec::new(),
        commons: HashSet::new(),
    }
    .run()
}
