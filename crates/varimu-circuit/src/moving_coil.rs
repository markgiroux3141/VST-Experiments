//! Moving-coil microphone cartridges: the port of `varimu/devices/moving_coil.py`
//! (`MovingCoil`, `moving_coil_from_data`) and of the moving_coil part in
//! `varimu/circuit/parts.py`, in Python's order of floating-point operations so the IR
//! agrees bit for bit (docs/SM57_PLAN.md, SM2). The component file carries the compiled
//! elements (the acoustic network derived from the geometry at fit time), so nothing here
//! needs more than instantiating them.

use circuitsim::ir::{Capacitor, Element, GROUND, Inductor, Resistor, Vccs};

use crate::Error;
use crate::yaml::{Map, Value};

/// A compiled element: kind R, L, C between a and b, or G (the gyrator: its acoustic port
/// a -> b, ratio `value` = B l / S in ohms, its electrical port from `c` to the part's minus:
/// `@v`, the coil's node, unless a dome mode's). `@v` and `@minus` name the coil's port node
/// and the part's minus terminal.
#[derive(Debug, Clone, PartialEq)]
pub struct McElement {
    pub name: String,
    pub kind: String,
    pub a: String,
    pub b: String,
    pub value: f64,
    pub c: String,
}

#[derive(Debug, Clone, PartialEq)]
pub struct MovingCoil {
    pub name: String,
    pub bl_tm: f64,
    pub sd_m2: f64,
    pub re_ohm: f64,
    pub le_h: f64,
    pub l2_h: f64,
    pub r2_ohm: f64,
    pub elements: Vec<McElement>,
}

fn num(m: &Map, key: &str, what: &str) -> Result<f64, Error> {
    m.get(key)
        .and_then(Value::as_f64)
        .ok_or_else(|| Error(format!("{what}: lumped needs `{key}`")))
}

fn text(m: &Map, key: &str, what: &str) -> Result<String, Error> {
    m.get(key)
        .map(Value::py_str)
        .ok_or_else(|| Error(format!("{what}: an element needs `{key}`")))
}

/// A cartridge version's data (kind moving_coil), as `moving_coil_from_data`.
pub fn from_data(data: &Value, what: &str) -> Result<MovingCoil, Error> {
    let d = data
        .as_map()
        .ok_or_else(|| Error(format!("{what}: not a mapping")))?;
    let kind = d.get("kind").and_then(Value::as_str).unwrap_or("");
    if kind != "moving_coil" {
        return Err(Error(format!(
            "{what} is not a moving-coil cartridge (kind '{kind}')"
        )));
    }
    let name = d
        .get("name")
        .map(Value::py_str)
        .ok_or_else(|| Error(format!("{what}: needs `name`")))?;
    let lp = d
        .get("lumped")
        .and_then(Value::as_map)
        .ok_or_else(|| Error(format!("{what}: needs `lumped`")))?;
    let list = lp
        .get("elements")
        .and_then(Value::as_list)
        .ok_or_else(|| Error(format!("{what}: lumped needs `elements`")))?;
    let mut elements = Vec::with_capacity(list.len());
    for e in list {
        let m = e
            .as_map()
            .ok_or_else(|| Error(format!("{what}: an element is not a mapping")))?;
        elements.push(McElement {
            name: text(m, "name", what)?,
            kind: text(m, "kind", what)?,
            a: text(m, "a", what)?,
            b: text(m, "b", what)?,
            value: m
                .get("value")
                .and_then(Value::as_f64)
                .ok_or_else(|| Error(format!("{what}: an element needs `value`")))?,
            c: m.get("c").map(Value::py_str).unwrap_or_else(|| "@v".into()),
        });
    }
    if elements
        .iter()
        .filter(|e| e.kind == "G" && e.c == "@v")
        .count()
        != 1
    {
        return Err(Error(format!(
            "{what}: one gyrator (G) on the coil in lumped.elements"
        )));
    }
    Ok(MovingCoil {
        name,
        bl_tm: num(lp, "bl_tm", what)?,
        sd_m2: num(lp, "sd_m2", what)?,
        re_ohm: num(lp, "re_ohm", what)?,
        le_h: num(lp, "le_h", what)?,
        l2_h: num(lp, "l2_h", what)?,
        r2_ohm: num(lp, "r2_ohm", what)?,
        elements,
    })
}

fn r(name: String, a: &str, b: &str, r_ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name,
        a: a.into(),
        b: b.into(),
        r_ohm,
    })
}

fn l(name: String, a: &str, b: &str, l_h: f64) -> Element {
    Element::Inductor(Inductor {
        name,
        a: a.into(),
        b: b.into(),
        l_h,
    })
}

fn vccs(name: String, pos: &str, neg: &str, ctrl_pos: &str, ctrl_neg: &str, gm_s: f64) -> Element {
    Element::Vccs(Vccs {
        name,
        pos: pos.into(),
        neg: neg.into(),
        ctrl_pos: ctrl_pos.into(),
        ctrl_neg: ctrl_neg.into(),
        gm_s,
    })
}

/// The moving_coil part (`parts.moving_coil`).
pub fn moving_coil(
    name: &str,
    front: &str,
    rear: &str,
    plus: &str,
    minus: &str,
    c: &MovingCoil,
) -> Result<Vec<Element>, Error> {
    let (n, upper) = (name.to_lowercase(), name.to_uppercase());
    let v = format!("{n}_v");
    let node = |x: &str| -> String {
        match x {
            "front" => front.to_string(),
            "rear" => rear.to_string(),
            "0" => GROUND.to_string(),
            "@v" => v.clone(),
            "@minus" => minus.to_string(),
            _ => format!("{n}_{x}"),
        }
    };
    let lnode = format!("{n}_l");
    let mut els = vec![r(format!("R{upper}_re"), plus, &lnode, c.re_ohm)];
    if c.l2_h > 0.0 {
        let e = format!("{n}_e");
        els.extend([
            l(format!("L{upper}_le"), &lnode, &e, c.le_h),
            l(format!("L{upper}_l2"), &e, &v, c.l2_h),
            r(format!("R{upper}_r2"), &e, &v, c.r2_ohm),
        ]);
    } else {
        els.push(l(format!("L{upper}_le"), &lnode, &v, c.le_h));
    }
    for e in &c.elements {
        let (a, b) = (node(&e.a), node(&e.b));
        match e.kind.as_str() {
            "R" => els.push(r(format!("R{upper}_{}", e.name), &a, &b, e.value)),
            "L" => els.push(l(format!("L{upper}_{}", e.name), &a, &b, e.value)),
            "C" => els.push(Element::Capacitor(Capacitor {
                name: format!("C{upper}_{}", e.name),
                a,
                b,
                c_f: e.value,
                v0_v: None,
            })),
            "G" => {
                let g = 1.0 / e.value;
                let c_ = node(&e.c);
                els.push(vccs(format!("G{upper}_{}a", e.name), &a, &b, &c_, minus, g));
                els.push(vccs(
                    format!("G{upper}_{}e", e.name),
                    &c_,
                    minus,
                    &a,
                    &b,
                    -g,
                ));
            }
            k => {
                return Err(Error(format!(
                    "moving coil {name}: element {} has kind '{k}'",
                    e.name
                )));
            }
        }
    }
    Ok(els)
}
