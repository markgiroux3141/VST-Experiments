//! Pre-flight checks: what makes a circuit fail before it renders (`varimu/preflight.py`).
//!
//! `check_circuit` builds the circuit's IR at every combination of its switches'
//! positions and checks each one; `check_ir` checks one IR:
//!
//! - unconnected: a node only one element terminal touches (the audio input counts as a
//!   source from the input node to ground);
//! - floating: nodes with no DC path to ground through resistors, inductors, windings,
//!   sources or transformer cores (tube and diode pins don't count);
//! - loop: a loop of voltage sources, inductors and windings alone (no resistance);
//! - rectifier: a diode's node that an inductor or winding reaches with no capacitor on
//!   it;
//! - probe: a probe or the input naming no node.

use std::collections::{BTreeMap, HashMap};

use circuitsim::ir::{CircuitIr, DeviceModel, Element, Probe};

use crate::devices::Library;
use crate::spec::{CircuitSpec, resolve};
use crate::yaml::{Map, Value};
use crate::{Cores, build_ir};

const GROUND: &str = "0";
const INPUT: &str = "<input>";
pub const MAX_CONFIGS: usize = 4096;

#[derive(Debug, Clone, PartialEq)]
pub struct Problem {
    /// unconnected | floating | loop | rectifier | probe | build
    pub check: String,
    pub message: String,
    /// The switch positions it shows at ("" = all, or no switches).
    pub config: String,
    /// What it is about, for the editor to mark: circuit nodes and IR element names.
    pub nodes: Vec<String>,
    pub elements: Vec<String>,
}

impl std::fmt::Display for Problem {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if self.config.is_empty() {
            write!(f, "{}: {}", self.check, self.message)
        } else {
            write!(f, "{}: {} [{}]", self.check, self.message, self.config)
        }
    }
}

/// Union-find over node names, with Python's joins and path halving.
#[derive(Default)]
struct Union {
    up: HashMap<String, String>,
}

impl Union {
    fn find(&mut self, x: &str) -> String {
        let mut x = x.to_string();
        self.up.entry(x.clone()).or_insert_with(|| x.clone());
        while self.up[&x] != x {
            let grand = self.up[&self.up[&x]].clone();
            self.up.insert(x.clone(), grand.clone());
            x = grand;
        }
        x
    }

    /// Join a and b; false when they were already joined.
    fn join(&mut self, a: &str, b: &str) -> bool {
        let (ra, rb) = (self.find(a), self.find(b));
        if ra == rb {
            return false;
        }
        self.up.insert(ra, rb);
        true
    }
}

/// The circuit terminals of an element (a winding's core node is the core's own).
fn terminals(el: &Element) -> Vec<String> {
    match el {
        Element::Winding(w) => vec![w.a.clone(), w.b.clone()],
        e => e.nodes().into_iter().map(String::from).collect(),
    }
}

/// The elements on the way from node a to node b in a forest of joined elements.
fn path(tree: &HashMap<String, Vec<(String, String)>>, a: &str, b: &str) -> Vec<String> {
    let mut back: HashMap<String, Option<(String, String)>> = HashMap::new();
    back.insert(a.into(), None);
    let mut queue = std::collections::VecDeque::from([a.to_string()]);
    while let Some(n) = queue.pop_front() {
        if n == b {
            break;
        }
        for (m, el) in tree.get(&n).into_iter().flatten() {
            if !back.contains_key(m) {
                back.insert(m.clone(), Some((n.clone(), el.clone())));
                queue.push_back(m.clone());
            }
        }
    }
    let mut out = Vec::new();
    let mut n = b.to_string();
    while let Some(Some((prev, el))) = back.get(&n) {
        out.push(el.clone());
        n = prev.clone();
    }
    out.reverse();
    out.into_iter().filter(|e| e != INPUT).collect()
}

pub fn check_ir(ir: &CircuitIr, config: &str) -> Vec<Problem> {
    let models: HashMap<&str, &DeviceModel> = ir.models.iter().map(|m| (m.name(), m)).collect();
    let els: Vec<&Element> = ir.sections.iter().flat_map(|s| &s.elements).collect();
    // node -> element names on it, nodes in first-seen order.
    let mut order: Vec<String> = Vec::new();
    let mut nodes: HashMap<String, Vec<String>> = HashMap::new();
    for el in &els {
        for n in el.nodes() {
            if !nodes.contains_key(n) {
                order.push(n.to_string());
            }
            nodes
                .entry(n.to_string())
                .or_default()
                .push(el.name().to_string());
        }
    }
    let mut out = Vec::new();
    let mut problem = |check: &str, msg: String, nodes: Vec<String>, elements: Vec<String>| {
        out.push(Problem {
            check: check.into(),
            message: msg,
            config: config.into(),
            nodes,
            elements,
        });
    };
    let probes: Vec<&str> = ir
        .probes
        .iter()
        .map(|p| match p {
            Probe::Voltage { node } => node.as_str(),
        })
        .collect();
    let driven: Vec<(String, String)> = std::iter::once((ir.input_node.clone(), INPUT.to_string()))
        .chain(
            ir.controls
                .iter()
                .map(|c| (c.node.clone(), format!("<control {}>", c.name))),
        )
        // A plate's pickup drives its node to ground, as a control input does.
        .chain(ir.elements().filter_map(|e| match e {
            Element::Plate(p) => Some((p.out.clone(), format!("<plate {}>", p.name))),
            _ => None,
        }))
        .collect();
    for n in driven.iter().map(|(n, _)| n.as_str()).chain(probes) {
        if !nodes.contains_key(n) {
            problem(
                "probe",
                format!("'{n}' is not a node of the circuit"),
                vec![n.into()],
                vec![],
            );
        }
    }
    for (n, label) in &driven {
        if let Some(v) = nodes.get_mut(n) {
            v.push(label.clone());
        }
    }
    let sorted: BTreeMap<&String, &Vec<String>> = nodes.iter().collect();
    for (n, names) in &sorted {
        if *n != GROUND && names.len() == 1 {
            problem(
                "unconnected",
                format!("node {n} has only {} on it", names[0]),
                vec![(*n).clone()],
                vec![names[0].clone()],
            );
        }
    }

    let (mut dc, mut loops) = (Union::default(), Union::default());
    dc.find(GROUND);
    let mut tree: HashMap<String, Vec<(String, String)>> = HashMap::new();
    for (n, label) in &driven {
        dc.join(n, GROUND);
        loops.join(n, GROUND);
        tree.entry(n.clone())
            .or_default()
            .push((GROUND.into(), label.clone()));
        tree.entry(GROUND.into())
            .or_default()
            .push((n.clone(), label.clone()));
    }
    for el in &els {
        let t = terminals(el);
        let conducts = matches!(
            el,
            Element::Resistor(_)
                | Element::Inductor(_)
                | Element::VoltageSource(_)
                | Element::SineSource(_)
                | Element::Winding(_)
        );
        if conducts {
            dc.join(&t[0], &t[1]);
        }
        if let Element::Device(d) = el
            && matches!(
                models.get(d.model.as_str()),
                Some(DeviceModel::MagneticCore(_))
            )
        {
            for n in &d.nodes[1..] {
                dc.join(&d.nodes[0], n);
            }
        }
        if matches!(
            el,
            Element::Inductor(_)
                | Element::VoltageSource(_)
                | Element::SineSource(_)
                | Element::Winding(_)
        ) {
            if !loops.join(&t[0], &t[1]) {
                let p = path(&tree, &t[0], &t[1]);
                let mut elements = vec![el.name().to_string()];
                elements.extend(p);
                problem(
                    "loop",
                    format!(
                        "{} closes a loop of sources, inductors and windings with no resistance",
                        el.name()
                    ),
                    t.clone(),
                    elements,
                );
            } else {
                tree.entry(t[0].clone())
                    .or_default()
                    .push((t[1].clone(), el.name().to_string()));
                tree.entry(t[1].clone())
                    .or_default()
                    .push((t[0].clone(), el.name().to_string()));
            }
        }
        if let Element::Winding(w) = el {
            dc.find(&w.core);
        }
    }
    let ground_root = dc.find(GROUND);
    let mut island_order: Vec<String> = Vec::new();
    let mut islands: HashMap<String, Vec<String>> = HashMap::new();
    for n in &order {
        let r = dc.find(n);
        if r != ground_root {
            if !islands.contains_key(&r) {
                island_order.push(r.clone());
            }
            islands.entry(r).or_default().push(n.clone());
        }
    }
    for r in island_order {
        let mut island = islands.remove(&r).expect("an island");
        island.sort();
        let more = if island.len() > 6 {
            format!(" (+{} more)", island.len() - 6)
        } else {
            String::new()
        };
        let shown: Vec<&str> = island.iter().take(6).map(String::as_str).collect();
        problem(
            "floating",
            format!("no DC path to ground from {}{more}", shown.join(", ")),
            island,
            vec![],
        );
    }

    let inductive: std::collections::HashSet<String> = els
        .iter()
        .filter(|e| matches!(e, Element::Inductor(_) | Element::Winding(_)))
        .flat_map(|e| terminals(e))
        .collect();
    let capacitive: std::collections::HashSet<String> = els
        .iter()
        .filter_map(|e| match e {
            Element::Capacitor(c) => Some([c.a.clone(), c.b.clone()]),
            _ => None,
        })
        .flatten()
        .collect();
    let mut rect: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for el in &els {
        if let Element::Device(d) = el
            && matches!(
                models.get(d.model.as_str()),
                Some(DeviceModel::JunctionDiode(_) | DeviceModel::VacuumDiode(_))
            )
        {
            for n in &d.nodes {
                rect.entry(n.clone()).or_default().push(d.name.clone());
            }
        }
    }
    for (n, names) in rect {
        if n != GROUND && inductive.contains(&n) && !capacitive.contains(&n) {
            problem(
                "rectifier",
                format!(
                    "node {n} ({}) is fed by an inductance and has no capacitor on it",
                    names.join(", ")
                ),
                vec![n],
                names,
            );
        }
    }
    out
}

/// The controls the file's switch parts follow, in order of appearance.
pub fn switch_controls(spec: &CircuitSpec) -> Vec<String> {
    fn walk(parts: &Map, out: &mut Vec<String>) {
        for (_, entry) in parts.iter() {
            if let Some(e) = entry.as_map()
                && let Some(sw) = e.get("switch")
            {
                let sw = sw.py_str();
                if !out.contains(&sw) {
                    out.push(sw);
                }
                if let Some(p) = e.get("parts").and_then(Value::as_map) {
                    walk(p, out);
                }
            }
        }
    }
    let mut out = Vec::new();
    for s in &spec.sections {
        walk(&s.parts, &mut out);
    }
    out
}

/// A switch control's positions: its `choices`, or min..max for `unit: position`.
pub fn control_positions(spec: &CircuitSpec, key: &str) -> Result<Vec<Value>, String> {
    let e = spec
        .controls
        .get(key)
        .and_then(Value::as_map)
        .ok_or_else(|| format!("control {key}: not a control"))?;
    if let Some(c) = e.get("choices").and_then(Value::as_list) {
        return Ok(c.to_vec());
    }
    if e.get("unit").map(Value::py_str).as_deref() == Some("position") {
        let lo = e.get("min").and_then(Value::as_f64).unwrap_or(0.0) as i64;
        let hi = e.get("max").and_then(Value::as_f64).unwrap_or(0.0) as i64;
        return Ok((lo..=hi).map(Value::Int).collect());
    }
    Err(format!(
        "control {key}: a switch's control has `choices` or `unit: position`"
    ))
}

/// Every combination of the switch controls' positions ([[]] without switches).
pub fn switch_configs(spec: &CircuitSpec) -> Result<Vec<Vec<(String, Value)>>, String> {
    let mut combos: Vec<Vec<(String, Value)>> = vec![Vec::new()];
    for k in switch_controls(spec) {
        let pos = control_positions(spec, &k)?;
        let mut next = Vec::new();
        for c in &combos {
            for p in &pos {
                let mut c = c.clone();
                c.push((k.clone(), p.clone()));
                next.push(c);
            }
        }
        combos = next;
    }
    if combos.len() > MAX_CONFIGS {
        return Err(format!(
            "{} switch combinations (more than {MAX_CONFIGS})",
            combos.len()
        ));
    }
    Ok(combos)
}

/// The checks at every switch combination; a problem found at every combination is
/// reported once, without its positions.
pub fn check_circuit(
    lib: &Library,
    spec: &CircuitSpec,
    overrides: &[(String, Value)],
    cores: Cores,
) -> Result<Vec<Problem>, String> {
    let configs = switch_configs(spec)?;
    let mut found: Vec<((String, String), Problem, Vec<String>)> = Vec::new();
    for cfg in &configs {
        let tag: Vec<String> = cfg
            .iter()
            .map(|(k, v)| format!("{k}={}", v.py_str()))
            .collect();
        let tag = tag.join(", ");
        let mut values: Vec<(String, Value)> = overrides.to_vec();
        for (k, v) in cfg {
            match values.iter_mut().find(|(key, _)| key == k) {
                Some(e) => e.1 = v.clone(),
                None => values.push((k.clone(), v.clone())),
            }
        }
        let probs = match resolve(spec, &values).and_then(|p| build_ir(lib, spec, &p, cores)) {
            Ok(ir) => check_ir(&ir, ""),
            Err(e) => vec![Problem {
                check: "build".into(),
                message: format!("ConfigError: {e}"),
                config: String::new(),
                nodes: vec![],
                elements: vec![],
            }],
        };
        for p in probs {
            let key = (p.check.clone(), p.message.clone());
            match found.iter_mut().find(|(k, _, _)| *k == key) {
                Some(e) => e.2.push(tag.clone()),
                None => found.push((key, p, vec![tag.clone()])),
            }
        }
    }
    Ok(found
        .into_iter()
        .map(|(_, p, tags)| Problem {
            config: if tags.len() == configs.len() {
                String::new()
            } else {
                tags.join("; ")
            },
            ..p
        })
        .collect())
}
