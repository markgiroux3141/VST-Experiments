//! The winding window laid out: every layer's place, turns and mean turn length.
//!
//! Coordinates: `r` from the wound leg's surface outward (across the window's width),
//! `z` along the leg from the start of the traverse (the inside of one cheek plus its
//! margin). A layer winding stacks its sections in `r`; a disc winding places them side
//! by side in `z`, each section's layers stacked in `r` within it.
//!
//! Assumptions (each is checked against the 2D field solution in step 4 where it bears on
//! leakage):
//! - a turn at distance r from the leg goes around the bobbin's tube (wall w, square
//!   corners) and is rounded over the build above it: its length is
//!   2 (a + 2w) + 2 (s + 2w) + 2 pi (r - w) (McLyman, Transformer and Inductor Design
//!   Handbook, 3rd ed., eq. [4-23]: MLT = 2(D + 2F) + 2(E + 2F) + pi A for a build A, the
//!   turn at its middle);
//! - a layer is one wire's overall diameter thick (or the drawn build / layers), its
//!   turns at the pitch `pitch_factor` x the overall diameter; a section's turns are spread
//!   evenly over its layers (N / layers each);
//! - for the leakage field a layer's copper is the equal-area square of its wire,
//!   (sqrt(pi) / 2) x the bare diameter thick, in the middle of the layer, the rest of the
//!   layer's thickness counted as insulation (Shen et al., IEEE TPEL 36(2) 2021, eq. (2));
//!   a disc's copper is spread over its width (McLyman eq. [17-5]);
//! - layers start at the traverse's start (z = 0).

use std::f64::consts::PI;

use crate::design::{Arrangement, Design, Section};
use crate::tables::{Lamination, Tables, Wire};
use crate::{Error, err};

/// The length of a turn at distance `r` (>= `wall`) from a leg of width `leg` and stack
/// `stack` wound on a tube of wall `wall`.
pub fn turn_length(leg: f64, stack: f64, wall: f64, r: f64) -> f64 {
    2.0 * (leg + 2.0 * wall) + 2.0 * (stack + 2.0 * wall) + 2.0 * PI * (r - wall).max(0.0)
}

#[derive(Debug, Clone, PartialEq)]
pub struct Layer {
    /// Index into `Design::sections`.
    pub section: usize,
    /// Index into `Design::windings`.
    pub winding: usize,
    pub turns: f64,
    pub r0_m: f64,
    pub r1_m: f64,
    pub z0_m: f64,
    pub z1_m: f64,
    /// The turn length at the layer's middle.
    pub mlt_m: f64,
}

/// A slab of the 1D leakage model: an interval of the stacking coordinate (r for layer
/// windings, z for disc windings) carrying `turns` of a winding spread evenly, or none.
#[derive(Debug, Clone, PartialEq)]
pub struct Slab {
    pub x0_m: f64,
    pub x1_m: f64,
    pub winding: Option<usize>,
    pub turns: f64,
}

/// What a section occupies: winding sections their layers, insulation its slab.
#[derive(Debug, Clone, PartialEq)]
pub enum Placed {
    Winding {
        winding: usize,
        wire: Wire,
        layers: Vec<usize>,
        /// Between layers: thickness and relative permittivity (none: 0 and 1).
        interlayer_m: f64,
        interlayer_eps: f64,
        enamel_eps: f64,
        /// The section's extent.
        r0_m: f64,
        r1_m: f64,
        z0_m: f64,
        z1_m: f64,
    },
    Insulation {
        thickness_m: f64,
        eps: f64,
        /// Along the stacking coordinate.
        x0_m: f64,
    },
    Shield {
        name: String,
        thickness_m: f64,
        x0_m: f64,
    },
}

#[derive(Debug, Clone)]
pub struct Layout {
    pub arrangement: Arrangement,
    pub leg_m: f64,
    pub stack_m: f64,
    /// The bobbin tube's wall.
    pub wall_m: f64,
    pub window_width_m: f64,
    pub window_height_m: f64,
    /// The winding length between the cheeks' margins.
    pub traverse_m: f64,
    pub layers: Vec<Layer>,
    pub placed: Vec<Placed>,
    /// The 1D leakage model's slabs, in order along the stacking coordinate.
    pub slabs: Vec<Slab>,
    /// The field's length across the slabs (layer: along the leg; disc: across the
    /// window) and the turn length weighting each slab's volume.
    pub field_length_m: f64,
    pub field_turn: FieldTurn,
    pub warnings: Vec<String>,
}

/// The turn length that weights the field's volume at x.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum FieldTurn {
    /// Layer windings: the turn at r = x.
    AtRadius,
    /// Disc windings: the field fills the window's width at every z; its mean turn.
    Fixed(f64),
}

impl Layout {
    /// The turn length at distance r from the leg.
    pub fn turn(&self, r: f64) -> f64 {
        turn_length(self.leg_m, self.stack_m, self.wall_m, r)
    }

    pub fn turn_at(&self, x: f64) -> f64 {
        match self.field_turn {
            FieldTurn::AtRadius => self.turn(x),
            FieldTurn::Fixed(p) => p,
        }
    }

    /// The radial build (layer) or the axial length (disc) the sections occupy.
    pub fn extent_m(&self) -> f64 {
        self.slabs.last().map_or(0.0, |s| s.x1_m)
    }
}

/// Rogowski's factor for a winding of height `b` and radial extent `lambda` (the
/// leakage field's effective length is b / K_R; W. Rogowski 1909, as transformer texts
/// quote it).
pub fn rogowski(b: f64, lambda: f64) -> f64 {
    if lambda <= 0.0 {
        return 1.0;
    }
    let x = PI * b / lambda;
    1.0 - (1.0 - (-x).exp()) / x
}

pub fn layout(d: &Design, t: &Tables, lam: &Lamination) -> Result<Layout, Error> {
    let a = lam.leg_m;
    let s = d.core.stack_m.value;
    let width = lam.window_width_m;
    let height = lam.window_height_m;
    let traverse = height - 2.0 * (d.bobbin.cheek_m.value + d.bobbin.margin_m.value);
    if traverse <= 0.0 {
        return err(format!(
            "{}: the cheeks and margins ({} m each end) leave no traverse in the {} window ({} m)",
            d.name,
            d.bobbin.cheek_m.value + d.bobbin.margin_m.value,
            lam.name,
            height
        ));
    }
    let wall = d.bobbin.wall_m.value;
    let pitch = d.bobbin.pitch_factor.value;
    let mut layers = Vec::new();
    let mut placed = Vec::new();
    let mut slabs: Vec<Slab> = Vec::new();
    let mut warnings = Vec::new();
    let push_gap = |slabs: &mut Vec<Slab>, x0: f64, x1: f64| {
        if x1 > x0 {
            slabs.push(Slab {
                x0_m: x0,
                x1_m: x1,
                winding: None,
                turns: 0.0,
            });
        }
    };
    // The stacking coordinate: r from the bobbin wall (layer), z from 0 (disc).
    let mut x = match d.arrangement.value {
        Arrangement::Layer => wall,
        Arrangement::Disc => 0.0,
    };
    for (si, sec) in d.sections.iter().enumerate() {
        match sec {
            Section::Insulation(ins) => {
                let eps = t.dielectric(&ins.dielectric.value)?.eps_r;
                let th = ins.thickness_m.value;
                placed.push(Placed::Insulation {
                    thickness_m: th,
                    eps,
                    x0_m: x,
                });
                push_gap(&mut slabs, x, x + th);
                x += th;
            }
            Section::Shield(sh) => {
                let th = sh.thickness_m.value;
                placed.push(Placed::Shield {
                    name: sh.name.clone(),
                    thickness_m: th,
                    x0_m: x,
                });
                push_gap(&mut slabs, x, x + th);
                x += th;
            }
            Section::Winding(ws) => {
                let k = d.winding_index(&ws.winding);
                let wire = t.wire(&ws.wire.value)?;
                let enamel_eps = t.dielectric(&ws.enamel.value)?.eps_r;
                let (il, il_eps) = match &ws.interlayer {
                    Some(i) => (
                        i.thickness_m.value,
                        t.dielectric(&i.dielectric.value)?.eps_r,
                    ),
                    None => (0.0, 1.0),
                };
                let n = f64::from(ws.turns.value);
                let m = ws.layers.value;
                let per_layer = n / f64::from(m);
                let natural_span = (n / f64::from(m)).ceil() * wire.overall_m * pitch;
                let span = ws.width_m.as_ref().map_or(natural_span, |w| w.value);
                // A layer's thickness: the wire's overall diameter, or the drawn build
                // shared by the layers (then no separate interlayer).
                let d_o = ws
                    .build_m
                    .as_ref()
                    .map_or(wire.overall_m, |b| b.value / f64::from(m));
                if let (Some(w), Some(b)) = (&ws.width_m, &ws.build_m) {
                    // Hexagonal packing is the densest round wire can go.
                    let need = n * wire.overall_m * wire.overall_m * 3f64.sqrt() / 2.0;
                    if need > w.value * b.value * (1.0 + 1e-9) {
                        warnings.push(format!(
                            "section {si} ({}): {n} turns of {} don't fit {:.2} x {:.2} mm even hexagonally packed",
                            ws.winding,
                            wire.name,
                            w.value * 1e3,
                            b.value * 1e3
                        ));
                    }
                } else if ws.width_m.is_some() && natural_span > span * (1.0 + 1e-9) {
                    warnings.push(format!(
                        "section {si} ({}): {:.0} turns per layer need {:.2} mm, drawn {:.2} mm",
                        ws.winding,
                        (n / f64::from(m)).ceil(),
                        natural_span * 1e3,
                        span * 1e3
                    ));
                }
                let first = layers.len();
                let (r0, r1, z0, z1);
                match d.arrangement.value {
                    Arrangement::Layer => {
                        if span > traverse * (1.0 + 1e-9) {
                            warnings.push(format!(
                                "section {si} ({}): {:.0} turns per layer need {:.2} mm, the traverse is {:.2} mm",
                                ws.winding,
                                (n / f64::from(m)).ceil(),
                                span * 1e3,
                                traverse * 1e3
                            ));
                        }
                        r0 = x;
                        for i in 0..m {
                            let lr0 = x;
                            layers.push(Layer {
                                section: si,
                                winding: k,
                                turns: per_layer,
                                r0_m: lr0,
                                r1_m: lr0 + d_o,
                                z0_m: 0.0,
                                z1_m: span,
                                mlt_m: turn_length(a, s, wall, lr0 + 0.5 * d_o),
                            });
                            // The copper: the wire's equal-area square, centred.
                            let cu = (0.5 * PI.sqrt() * wire.bare_m).min(d_o);
                            let c0 = lr0 + 0.5 * (d_o - cu);
                            push_gap(&mut slabs, lr0, c0);
                            slabs.push(Slab {
                                x0_m: c0,
                                x1_m: c0 + cu,
                                winding: Some(k),
                                turns: per_layer,
                            });
                            push_gap(&mut slabs, c0 + cu, lr0 + d_o);
                            x = lr0 + d_o;
                            if i + 1 < m {
                                push_gap(&mut slabs, x, x + il);
                                x += il;
                            }
                        }
                        r1 = x;
                        (z0, z1) = (0.0, span);
                    }
                    Arrangement::Disc => {
                        z0 = x;
                        z1 = x + span;
                        r0 = wall;
                        let mut r = wall;
                        for i in 0..m {
                            layers.push(Layer {
                                section: si,
                                winding: k,
                                turns: per_layer,
                                r0_m: r,
                                r1_m: r + d_o,
                                z0_m: z0,
                                z1_m: z1,
                                mlt_m: turn_length(a, s, wall, r + 0.5 * d_o),
                            });
                            r += d_o;
                            if i + 1 < m {
                                r += il;
                            }
                        }
                        r1 = r;
                        if r1 > width * (1.0 + 1e-9) {
                            warnings.push(format!(
                                "section {si} ({}): its build {:.2} mm (with the {:.2} mm wall) exceeds the window's width {:.2} mm",
                                ws.winding,
                                r1 * 1e3,
                                wall * 1e3,
                                width * 1e3
                            ));
                        }
                        slabs.push(Slab {
                            x0_m: z0,
                            x1_m: z1,
                            winding: Some(k),
                            turns: n,
                        });
                        x = z1;
                    }
                }
                placed.push(Placed::Winding {
                    winding: k,
                    wire,
                    layers: (first..layers.len()).collect(),
                    interlayer_m: il,
                    interlayer_eps: il_eps,
                    enamel_eps,
                    r0_m: r0,
                    r1_m: r1,
                    z0_m: z0,
                    z1_m: z1,
                });
            }
        }
    }
    // The slabs span the windings only: under balanced ampere-turns the field is zero
    // inside the first and outside the last.
    while slabs.first().is_some_and(|s| s.winding.is_none()) {
        slabs.remove(0);
    }
    while slabs.last().is_some_and(|s| s.winding.is_none()) {
        slabs.pop();
    }
    let (field_length, field_turn) = match d.arrangement.value {
        Arrangement::Layer => {
            if x > width * (1.0 + 1e-9) {
                warnings.push(format!(
                    "the build {:.2} mm (with the {:.2} mm wall) exceeds the window's width {:.2} mm",
                    x * 1e3,
                    wall * 1e3,
                    width * 1e3
                ));
            }
            let b = layers.iter().map(|l| l.z1_m - l.z0_m).fold(0.0, f64::max);
            let lambda =
                slabs.last().map_or(0.0, |s| s.x1_m) - slabs.first().map_or(0.0, |s| s.x0_m);
            ((b / rogowski(b, lambda)).min(height), FieldTurn::AtRadius)
        }
        Arrangement::Disc => {
            if x > traverse * (1.0 + 1e-9) {
                warnings.push(format!(
                    "the sections' length {:.2} mm exceeds the traverse {:.2} mm",
                    x * 1e3,
                    traverse * 1e3
                ));
            }
            // The field crosses the discs' radial build (McLyman eq. [17-5]: the build is
            // the flux path's width), Rogowski-corrected, at most the window's width; the
            // turn weighting it is the build's middle.
            let (b0, b1) = layers.iter().fold((f64::INFINITY, 0.0f64), |(lo, hi), l| {
                (lo.min(l.r0_m), hi.max(l.r1_m))
            });
            let b = (b1 - b0).max(0.0);
            let lambda =
                slabs.last().map_or(0.0, |s| s.x1_m) - slabs.first().map_or(0.0, |s| s.x0_m);
            (
                (b / rogowski(b, lambda)).min(width),
                FieldTurn::Fixed(turn_length(a, s, wall, 0.5 * (b0 + b1))),
            )
        }
    };
    Ok(Layout {
        arrangement: d.arrangement.value,
        leg_m: a,
        stack_m: s,
        wall_m: wall,
        window_width_m: width,
        window_height_m: height,
        traverse_m: traverse,
        layers,
        placed,
        slabs,
        field_length_m: field_length,
        field_turn,
        warnings,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rogowski_tends_to_one_for_tall_windings() {
        assert!((rogowski(1.0, 1e-6) - 1.0).abs() < 1e-5);
        // b = lambda: 1 - (1 - e^-pi) / pi
        let k = rogowski(1.0, 1.0);
        assert!((k - (1.0 - (1.0 - (-PI).exp()) / PI)).abs() < 1e-15);
    }

    #[test]
    fn a_turn_on_the_leg_is_its_perimeter() {
        assert_eq!(turn_length(0.02, 0.03, 0.0, 0.0), 0.1);
        // McLyman [4-23]: 2(D + 2F) + 2(E + 2F) + pi A, the turn at A / 2 above the tube.
        let (d, e, f, a) = (0.02, 0.03, 1e-3, 4e-3);
        let want = 2.0 * (d + 2.0 * f) + 2.0 * (e + 2.0 * f) + PI * a;
        assert!((turn_length(d, e, f, f + 0.5 * a) - want).abs() < 1e-15);
    }
}
