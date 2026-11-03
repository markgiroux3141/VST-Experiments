//! The transformer's source format: what the component editor edits and a version
//! keeps beside its compiled form. Every physical value is `{value, source}`.
//!
//! ```yaml
//! name: OT_5E3
//! kind: transformer
//! source: "what the design is and where its construction comes from"
//! core:
//!   lamination: {value: EI-75, source: ...}          # a laminations.yaml size
//!   material: {value: grain_oriented_si_steel, source: ...}   # config/magnetics.yaml
//!   stack_m: {value: 0.0254, source: ...}            # the stack's height
//!   stacking_factor: {value: 0.95, source: ...}      # iron share of the stack
//!   stacking: {value: interleaved, source: ...}      # or butt
//!   joint_gap_m: {value: 5.0e-6, source: ...}        # effective gap per E-I joint
//!   spacer_m: {value: 0.0, source: ...}              # butt only: a spacer per joint
//! bobbin:
//!   wall_m: {value, source}         # between the leg and the first layer
//!   cheek_m: {value, source}        # each end's flange
//!   margin_m: {value, source}       # each end's unwound margin (creepage)
//!   pitch_factor: {value, source}   # a layer's turn pitch / the wire's overall diameter
//! arrangement: {value: layer, source}   # layer: sections wound over each other;
//!                                       # disc: sections side by side along the leg
//! windings: [pa, pb, s]   # the circuit's windings, the first the reference (ratio 1)
//! sections:               # in order: from the leg outward (layer), along it (disc)
//!   - winding: pa
//!     turns: {value, source}
//!     layers: {value, source}
//!     wire: {value: AWG 33 heavy, source}       # wire.yaml (or 0.13 mm grade 1)
//!     enamel: {value: polyvinyl_formal, source} # dielectrics.yaml
//!     interlayer: {thickness_m: {value, source}, dielectric: {value, source}}
//!     width_m: {value, source}    # optional: the section's length along its layers
//!     build_m: {value, source}    # optional: its thickness across them (both as drawn,
//!                                 # e.g. a wild-wound disc; else from wire and layers)
//!   - insulation: {thickness_m: {value, source}, dielectric: {value, source}}
//!   - shield: {name: S, thickness_m: {value, source}}   # a foil (a terminal of its own)
//!   - winding: s
//!     ...
//! leakage_method: formula   # optional: formula (the 1D energy method, default) or field
//!                           # (the pairs from the 2D field solution, crate::fem)
//! rating:                 # the flux density check
//!   windings: [pa, pb]    # the voltage is across these in series
//!   v_rms: {value, source}
//!   f_hz: {value, source}
//!   b_limit_t: {value, source}   # optional: warn above it (always above saturation)
//! ```
//!
//! A winding may have several sections (in series, in the order listed); a tap is the
//! junction of two windings (a centre-tapped primary is two windings, `pa` and `pb`).

use varimu_circuit::yaml::{Map, Value};

use crate::sourced::{Sourced, count, get, label, map, non_negative, only, positive, text};
use crate::{Error, err};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stacking {
    /// All E's one way, all I's the other: two joints in every flux path, a spacer
    /// possible.
    Butt,
    /// E's and I's alternated: the joints overlap; an effective gap per joint.
    Interleaved,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Arrangement {
    /// Sections wound over each other (concentric): the leakage field runs along the leg.
    Layer,
    /// Sections side by side along the leg (disc, pancake, chamber): the leakage field
    /// runs across the window.
    Disc,
}

/// Where the compiled leakage comes from: the 1D formula, or the 2D field solution of
/// the window (every winding pair solved; for disc windings, whose field the formula
/// misses by 8-17%: tests/fem_check.rs).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeakageMethod {
    Formula,
    Field,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Insulation {
    pub thickness_m: Sourced<f64>,
    pub dielectric: Sourced<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WindingSection {
    pub winding: String,
    pub turns: Sourced<u32>,
    pub layers: Sourced<u32>,
    pub wire: Sourced<String>,
    pub enamel: Sourced<String>,
    /// Between this section's layers (none: layer on layer).
    pub interlayer: Option<Insulation>,
    /// The section's dimensions as drawn: along its layers and across them.
    pub width_m: Option<Sourced<f64>>,
    pub build_m: Option<Sourced<f64>>,
}

/// A conducting foil between sections (an electrostatic screen), its own terminal.
/// It isn't a closed turn, so it carries no leakage current: for the field it is space.
#[derive(Debug, Clone, PartialEq)]
pub struct Shield {
    pub name: String,
    pub thickness_m: Sourced<f64>,
}

// A design has a handful of sections: boxing the winding variant buys nothing.
#[allow(clippy::large_enum_variant)]
#[derive(Debug, Clone, PartialEq)]
pub enum Section {
    Winding(WindingSection),
    Insulation(Insulation),
    Shield(Shield),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Core {
    pub lamination: Sourced<String>,
    pub material: Sourced<String>,
    pub stack_m: Sourced<f64>,
    pub stacking_factor: Sourced<f64>,
    pub stacking: Sourced<Stacking>,
    pub joint_gap_m: Sourced<f64>,
    pub spacer_m: Option<Sourced<f64>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Bobbin {
    pub wall_m: Sourced<f64>,
    pub cheek_m: Sourced<f64>,
    pub margin_m: Sourced<f64>,
    pub pitch_factor: Sourced<f64>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Rating {
    pub windings: Vec<String>,
    pub v_rms: Sourced<f64>,
    pub f_hz: Sourced<f64>,
    pub b_limit_t: Option<Sourced<f64>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Design {
    pub name: String,
    pub source: String,
    pub core: Core,
    pub bobbin: Bobbin,
    pub arrangement: Sourced<Arrangement>,
    /// The circuit's windings; the first is the reference.
    pub windings: Vec<String>,
    pub sections: Vec<Section>,
    pub rating: Option<Rating>,
    pub leakage_method: LeakageMethod,
}

fn insulation(v: &Value, what: &str) -> Result<Insulation, Error> {
    let m = map(v, what)?;
    only(m, &["thickness_m", "dielectric"], what)?;
    Ok(Insulation {
        thickness_m: positive(get(m, "thickness_m", what)?, &format!("{what}.thickness_m"))?,
        dielectric: label(get(m, "dielectric", what)?, &format!("{what}.dielectric"))?,
    })
}

fn winding_section(m: &Map, what: &str) -> Result<WindingSection, Error> {
    only(
        m,
        &[
            "winding",
            "turns",
            "layers",
            "wire",
            "enamel",
            "interlayer",
            "width_m",
            "build_m",
        ],
        what,
    )?;
    let f = |k: &str| format!("{what}.{k}");
    let s = WindingSection {
        winding: text(get(m, "winding", what)?, &f("winding"))?,
        turns: count(get(m, "turns", what)?, &f("turns"))?,
        layers: count(get(m, "layers", what)?, &f("layers"))?,
        wire: label(get(m, "wire", what)?, &f("wire"))?,
        enamel: label(get(m, "enamel", what)?, &f("enamel"))?,
        interlayer: m
            .get("interlayer")
            .map(|v| insulation(v, &f("interlayer")))
            .transpose()?,
        width_m: m
            .get("width_m")
            .map(|v| positive(v, &f("width_m")))
            .transpose()?,
        build_m: m
            .get("build_m")
            .map(|v| positive(v, &f("build_m")))
            .transpose()?,
    };
    if s.build_m.is_some() && s.interlayer.is_some() {
        return err(format!(
            "{what}: a drawn build_m spreads the layers through it; leave out interlayer"
        ));
    }
    if s.layers.value > s.turns.value {
        return err(format!(
            "{what}: {} layers for {} turns",
            s.layers.value, s.turns.value
        ));
    }
    Ok(s)
}

impl Design {
    pub fn parse(data: &Value) -> Result<Design, Error> {
        let top = map(data, "design")?;
        let name = text(get(top, "name", "design")?, "design.name")?;
        let w = |k: &str| format!("{name}.{k}");
        only(
            top,
            &[
                "name",
                "kind",
                "source",
                "core",
                "bobbin",
                "arrangement",
                "windings",
                "sections",
                "rating",
                "leakage_method",
                "notes",
            ],
            &name,
        )?;
        let kind = text(get(top, "kind", &name)?, &w("kind"))?;
        if kind != "transformer" {
            return err(format!("{name}: kind is transformer (got {kind})"));
        }
        let source = text(get(top, "source", &name)?, &w("source"))?;

        let cw = w("core");
        let c = map(get(top, "core", &name)?, &cw)?;
        only(
            c,
            &[
                "lamination",
                "material",
                "stack_m",
                "stacking_factor",
                "stacking",
                "joint_gap_m",
                "spacer_m",
            ],
            &cw,
        )?;
        let cf = |k: &str| format!("{cw}.{k}");
        let stacking = label(get(c, "stacking", &cw)?, &cf("stacking"))?;
        let stacking = Sourced::new(
            match stacking.value.as_str() {
                "butt" => Stacking::Butt,
                "interleaved" => Stacking::Interleaved,
                s => return err(format!("{cw}.stacking: butt or interleaved (got {s})")),
            },
            stacking.source,
        );
        let spacer_m = c
            .get("spacer_m")
            .map(|v| non_negative(v, &cf("spacer_m")))
            .transpose()?;
        if stacking.value == Stacking::Interleaved
            && spacer_m.as_ref().is_some_and(|s| s.value > 0.0)
        {
            return err(format!("{cw}: a spacer needs butt stacking"));
        }
        let stacking_factor = positive(get(c, "stacking_factor", &cw)?, &cf("stacking_factor"))?;
        if stacking_factor.value > 1.0 {
            return err(format!("{cw}.stacking_factor: at most 1"));
        }
        let core = Core {
            lamination: label(get(c, "lamination", &cw)?, &cf("lamination"))?,
            material: label(get(c, "material", &cw)?, &cf("material"))?,
            stack_m: positive(get(c, "stack_m", &cw)?, &cf("stack_m"))?,
            stacking_factor,
            stacking,
            joint_gap_m: non_negative(get(c, "joint_gap_m", &cw)?, &cf("joint_gap_m"))?,
            spacer_m,
        };

        let bw = w("bobbin");
        let b = map(get(top, "bobbin", &name)?, &bw)?;
        only(b, &["wall_m", "cheek_m", "margin_m", "pitch_factor"], &bw)?;
        let bf = |k: &str| format!("{bw}.{k}");
        let bobbin = Bobbin {
            wall_m: non_negative(get(b, "wall_m", &bw)?, &bf("wall_m"))?,
            cheek_m: non_negative(get(b, "cheek_m", &bw)?, &bf("cheek_m"))?,
            margin_m: non_negative(get(b, "margin_m", &bw)?, &bf("margin_m"))?,
            pitch_factor: positive(get(b, "pitch_factor", &bw)?, &bf("pitch_factor"))?,
        };
        if bobbin.pitch_factor.value < 1.0 {
            return err(format!(
                "{bw}.pitch_factor: at least 1 (turns can't overlap)"
            ));
        }

        let arrangement = label(get(top, "arrangement", &name)?, &w("arrangement"))?;
        let arrangement = Sourced::new(
            match arrangement.value.as_str() {
                "layer" => Arrangement::Layer,
                "disc" => Arrangement::Disc,
                s => return err(format!("{name}.arrangement: layer or disc (got {s})")),
            },
            arrangement.source,
        );

        let windings: Vec<String> = get(top, "windings", &name)?
            .as_list()
            .ok_or_else(|| Error(format!("{name}.windings: a list of winding labels")))?
            .iter()
            .map(|v| text(v, &w("windings")))
            .collect::<Result<_, _>>()?;
        if windings.is_empty() {
            return err(format!("{name}.windings: at least one"));
        }
        for (i, a) in windings.iter().enumerate() {
            if windings[..i].contains(a) {
                return err(format!("{name}.windings: {a} twice"));
            }
        }

        let sw = w("sections");
        let list = get(top, "sections", &name)?
            .as_list()
            .ok_or_else(|| Error(format!("{sw}: a list")))?;
        let mut sections = Vec::new();
        for (i, s) in list.iter().enumerate() {
            let what = format!("{sw}[{i}]");
            let m = map(s, &what)?;
            if m.contains("winding") {
                let ws = winding_section(m, &what)?;
                if !windings.contains(&ws.winding) {
                    return err(format!(
                        "{what}: winding {} isn't in `windings` ({})",
                        ws.winding,
                        windings.join(", ")
                    ));
                }
                sections.push(Section::Winding(ws));
            } else if m.contains("insulation") {
                only(m, &["insulation"], &what)?;
                sections.push(Section::Insulation(insulation(
                    get(m, "insulation", &what)?,
                    &format!("{what}.insulation"),
                )?));
            } else if m.contains("shield") {
                only(m, &["shield"], &what)?;
                let sw = format!("{what}.shield");
                let sm = map(get(m, "shield", &what)?, &sw)?;
                only(sm, &["name", "thickness_m"], &sw)?;
                let name = text(get(sm, "name", &sw)?, &format!("{sw}.name"))?;
                if windings.contains(&name) {
                    return err(format!("{sw}: {name} is a winding's label"));
                }
                sections.push(Section::Shield(Shield {
                    name,
                    thickness_m: positive(
                        get(sm, "thickness_m", &sw)?,
                        &format!("{sw}.thickness_m"),
                    )?,
                }));
            } else {
                return err(format!(
                    "{what}: a `winding: ...` section, an `insulation:` or a `shield:`"
                ));
            }
        }
        for wd in &windings {
            if !sections
                .iter()
                .any(|s| matches!(s, Section::Winding(x) if &x.winding == wd))
            {
                return err(format!("{name}: winding {wd} has no section"));
            }
        }

        let rating = match top.get("rating") {
            None => None,
            Some(v) => {
                let rw = w("rating");
                let r = map(v, &rw)?;
                only(r, &["windings", "v_rms", "f_hz", "b_limit_t"], &rw)?;
                let ws: Vec<String> = get(r, "windings", &rw)?
                    .as_list()
                    .ok_or_else(|| Error(format!("{rw}.windings: a list")))?
                    .iter()
                    .map(|v| text(v, &rw))
                    .collect::<Result<_, _>>()?;
                for x in &ws {
                    if !windings.contains(x) {
                        return err(format!("{rw}.windings: {x} isn't a winding"));
                    }
                }
                Some(Rating {
                    windings: ws,
                    v_rms: positive(get(r, "v_rms", &rw)?, &format!("{rw}.v_rms"))?,
                    f_hz: positive(get(r, "f_hz", &rw)?, &format!("{rw}.f_hz"))?,
                    b_limit_t: r
                        .get("b_limit_t")
                        .map(|v| positive(v, &format!("{rw}.b_limit_t")))
                        .transpose()?,
                })
            }
        };

        let leakage_method = match top
            .get("leakage_method")
            .map(|v| text(v, &w("leakage_method")))
        {
            None => LeakageMethod::Formula,
            Some(m) => match m?.as_str() {
                "formula" => LeakageMethod::Formula,
                "field" => LeakageMethod::Field,
                s => return err(format!("{name}.leakage_method: formula or field (got {s})")),
            },
        };
        Ok(Design {
            leakage_method,
            name,
            source,
            core,
            bobbin,
            arrangement,
            windings,
            sections,
            rating,
        })
    }

    pub fn winding_index(&self, label: &str) -> usize {
        self.windings.iter().position(|w| w == label).unwrap()
    }
}
