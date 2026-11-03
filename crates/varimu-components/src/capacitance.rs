//! Layer and interwinding capacitance.
//!
//! Two neighbouring layers form a capacitor whose plates are the facing layers (area: the
//! turn length at their interface times their overlap), across the wires' enamel, any
//! sheet between them, and the space between round wires ([`layer_c_per_area`]: Shen,
//! Wang, Shen, Qin & Blaabjerg, "An Improved Stray Capacitance Model for Inductors", IEEE
//! TPEL 34(11) 2019, eqs. (2)-(4), after Snelling and Biela & Kolar 2008).
//!
//! A section of m layers wound back and forth (each layer starts where the last ended)
//! has, between layers i and i+1, a voltage rising linearly from 0 at their joined end to
//! 2 V / m at the other; the energy (4/3) C_i (V / m)^2 / 2 per pair gives the section's
//! equivalent capacitance across its terminals, (4 / 3) sum_i C_i / m^2 (for equal C_i,
//! 4 (m - 1) C / (3 m^2): Shen et al. 2019 eq. (10) with beta = 1/3 for a regular
//! winding, after Snelling and Zuhrt 1934; the energy per plate pair with end voltages
//! U1, U2 is C (U1^2 + U1 U2 + U2^2) / 6, Shen et al. 2019 eq. (A.1)). A winding of
//! several sections in series adds its sections' energies at their share of its voltage,
//! sum_s C_s (N_s / N)^2. Turn-to-turn capacitance within a layer is left out (it
//! matters for single-layer windings, not for the many-layer windings of audio
//! transformers).
//!
//! Between neighbouring sections: the static capacitance of their facing layers
//! (`Interwinding`, `ToShield`), connected by [`network`]: the facing layers' potentials
//! run linearly between their ends, so the energy C (U0^2 + U0 U1 + U1^2) / 6 (U0, U1 the
//! potential differences at the two ends) is a quadratic form in the windings' terminal
//! voltages (and a shield's), which capacitors between every pair of terminals represent
//! exactly; the ones across one winding add to its self-capacitance.

use circuitsim::devices::core::MU0;

use crate::design::Arrangement;
use crate::geometry::{Layer, Layout, Placed};

/// The permittivity of free space, from mu0 and c (F/m).
pub fn eps0() -> f64 {
    let c = 299_792_458.0_f64;
    1.0 / (MU0 * c * c)
}

/// One side's wire: bare and overall diameters, the enamel's relative permittivity.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct WireSide {
    pub bare_m: f64,
    pub overall_m: f64,
    pub enamel_eps: f64,
}

/// Capacitance per unit area (F/m^2) between two facing layers of round wire with
/// insulation between them: `sheet_m` thick in all, `sheet_over_eps` the sum of each
/// sheet's thickness over its relative permittivity (0, 0: wire on wire).
///
/// Shen et al. 2019 eqs. (3)-(4) for an orthogonal (layer on layer) winding: across a
/// distance between the bare conductors a_iso = 2 delta_wire + delta_t, the effective
/// distance d_eff = a_iso - 0.15 d_i + 0.26 (h_iso + d_i) (h_iso = 2 delta_wire, the
/// enamel between neighbouring turns in a layer) and the mixed permittivity
/// eps = eps_wire eps_t a_iso / (eps_wire delta_t + 2 eps_t delta_wire). With two different
/// wires each side brings its own enamel and the diameters are averaged (our extension:
/// it reduces to theirs for one wire).
pub fn layer_c_per_area(a: WireSide, b: WireSide, sheet_m: f64, sheet_over_eps: f64) -> f64 {
    let (da, db) = (
        0.5 * (a.overall_m - a.bare_m),
        0.5 * (b.overall_m - b.bare_m),
    );
    let a_iso = da + db + sheet_m;
    let h_iso = da + db;
    let d_i = 0.5 * (a.bare_m + b.bare_m);
    let d_eff = a_iso - 0.15 * d_i + 0.26 * (h_iso + d_i);
    let eps = a_iso / (da / a.enamel_eps + db / b.enamel_eps + sheet_over_eps);
    eps0() * eps / d_eff
}

/// Capacitance per unit area between a layer of wire and a foil (a shield) with
/// insulation between them (`sheet_m` thick, `sheet_over_eps` as for
/// [`layer_c_per_area`]): by the layer's image in the foil, twice the capacitance between
/// the layer and its image at twice the distance (the foil is the pair's midplane; our
/// derivation on Shen et al.'s layer formula).
pub fn plane_c_per_area(w: WireSide, sheet_m: f64, sheet_over_eps: f64) -> f64 {
    2.0 * layer_c_per_area(w, w, 2.0 * sheet_m, 2.0 * sheet_over_eps)
}

#[derive(Debug, Clone, PartialEq)]
pub struct Interwinding {
    pub a: usize,
    pub b: usize,
    /// Indices into `Design::sections` of the two facing sections.
    pub sections: (usize, usize),
    pub c_f: f64,
}

/// A winding's capacitance to a shield (a foil between sections, its own terminal).
#[derive(Debug, Clone, PartialEq)]
pub struct ToShield {
    pub shield: String,
    pub winding: usize,
    /// Indices into `Design::sections`: the winding section and the shield.
    pub sections: (usize, usize),
    pub c_f: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Capacitances {
    /// Per winding, across its terminals.
    pub self_f: Vec<f64>,
    /// Per section: its own equivalent capacitance (None for insulation and shields).
    pub section_f: Vec<Option<f64>>,
    /// Neighbouring sections of windings (a == b: two sections of one winding).
    pub between: Vec<Interwinding>,
    pub to_shields: Vec<ToShield>,
}

fn overlap(a0: f64, a1: f64, b0: f64, b1: f64) -> f64 {
    (a1.min(b1) - a0.max(b0)).max(0.0)
}

fn side(p: &Placed) -> Option<WireSide> {
    match p {
        Placed::Winding {
            wire, enamel_eps, ..
        } => Some(WireSide {
            bare_m: wire.bare_m,
            overall_m: wire.overall_m,
            enamel_eps: *enamel_eps,
        }),
        _ => None,
    }
}

pub fn capacitances(layout: &Layout, n: usize, turns: &[f64]) -> Capacitances {
    let layers = &layout.layers;
    let mut self_f = vec![0.0; n];
    let mut section_f = vec![None; layout.placed.len()];
    for (si, p) in layout.placed.iter().enumerate() {
        let Placed::Winding {
            winding,
            layers: ids,
            interlayer_m,
            interlayer_eps,
            ..
        } = p
        else {
            continue;
        };
        let w = side(p).unwrap();
        let c_area = layer_c_per_area(w, w, *interlayer_m, *interlayer_m / *interlayer_eps);
        let m = ids.len() as f64;
        let sum: f64 = ids
            .windows(2)
            .map(|pair| {
                let (l0, l1) = (&layers[pair[0]], &layers[pair[1]]);
                let r = 0.5 * (l0.r1_m + l1.r0_m);
                c_area * layout.turn(r) * overlap(l0.z0_m, l0.z1_m, l1.z0_m, l1.z1_m)
            })
            .sum();
        let c_sec = 4.0 / 3.0 * sum / (m * m);
        section_f[si] = Some(c_sec);
        let n_sec: f64 = ids.iter().map(|&i| layers[i].turns).sum();
        let share = n_sec / turns[*winding];
        self_f[*winding] += c_sec * share * share;
    }

    // Neighbouring conductors (winding sections and shields) across the insulation
    // between them.
    let mut between = Vec::new();
    let mut to_shields = Vec::new();
    let mut prev: Option<usize> = None;
    let mut sheet_m = 0.0;
    let mut sheet_over_eps = 0.0;
    for (si, p) in layout.placed.iter().enumerate() {
        if let Placed::Insulation {
            thickness_m, eps, ..
        } = p
        {
            sheet_m += thickness_m;
            sheet_over_eps += thickness_m / eps;
            continue;
        }
        if let Some(pi) = prev {
            let pa = &layout.placed[pi];
            match (pa, p) {
                (Placed::Winding { winding: a, .. }, Placed::Winding { winding: b, .. }) => {
                    let c_area = layer_c_per_area(
                        side(pa).unwrap(),
                        side(p).unwrap(),
                        sheet_m,
                        sheet_over_eps,
                    );
                    between.push(Interwinding {
                        a: *a,
                        b: *b,
                        sections: (pi, si),
                        c_f: c_area * facing_area(layout, layers, pa, p),
                    });
                }
                (Placed::Winding { winding, .. }, Placed::Shield { name, .. })
                | (Placed::Shield { name, .. }, Placed::Winding { winding, .. }) => {
                    let (wp, wi) = if matches!(pa, Placed::Winding { .. }) {
                        (pa, pi)
                    } else {
                        (p, si)
                    };
                    let c_area = plane_c_per_area(side(wp).unwrap(), sheet_m, sheet_over_eps);
                    to_shields.push(ToShield {
                        shield: name.clone(),
                        winding: *winding,
                        sections: (wi, if wi == pi { si } else { pi }),
                        c_f: c_area * face_area(layout, layers, wp, wi == pi),
                    });
                }
                // Two foils facing each other: no winding involved.
                _ => {}
            }
        }
        prev = Some(si);
        sheet_m = 0.0;
        sheet_over_eps = 0.0;
    }
    Capacitances {
        self_f,
        section_f,
        between,
        to_shields,
    }
}

/// The overlap of two neighbouring winding sections' facing sides.
fn facing_area(layout: &Layout, layers: &[Layer], pa: &Placed, pb: &Placed) -> f64 {
    let (
        Placed::Winding {
            layers: la,
            r0_m: ar0,
            r1_m: ar1,
            ..
        },
        Placed::Winding {
            layers: lb,
            r0_m: br0,
            r1_m: br1,
            ..
        },
    ) = (pa, pb)
    else {
        unreachable!()
    };
    match layout.arrangement {
        Arrangement::Layer => {
            let (l0, l1) = (&layers[*la.last().unwrap()], &layers[lb[0]]);
            let r = 0.5 * (l0.r1_m + l1.r0_m);
            layout.turn(r) * overlap(l0.z0_m, l0.z1_m, l1.z0_m, l1.z1_m)
        }
        Arrangement::Disc => {
            // Side faces: the radial overlap of the two discs, at its middle radius.
            let r = 0.5 * (ar0.max(*br0) + ar1.min(*br1));
            layout.turn(r) * overlap(*ar0, *ar1, *br0, *br1)
        }
    }
}

/// A winding section's side facing the next conductor (`toward_next`) or the previous.
fn face_area(layout: &Layout, layers: &[Layer], p: &Placed, toward_next: bool) -> f64 {
    let Placed::Winding {
        layers: ids,
        r0_m,
        r1_m,
        ..
    } = p
    else {
        unreachable!()
    };
    match layout.arrangement {
        Arrangement::Layer => {
            let l = if toward_next {
                &layers[*ids.last().unwrap()]
            } else {
                &layers[ids[0]]
            };
            let r = if toward_next { l.r1_m } else { l.r0_m };
            layout.turn(r) * (l.z1_m - l.z0_m)
        }
        Arrangement::Disc => layout.turn(0.5 * (r0_m + r1_m)) * (r1_m - r0_m),
    }
}

/// A transformer terminal: a winding's dotted end or its other end, or a shield.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Terminal {
    Dot(usize),
    Other(usize),
    Shield(String),
}

/// The facing capacitances as capacitors between terminals.
#[derive(Debug, Clone, PartialEq)]
pub struct Network {
    /// Per winding: capacitance across its own terminals (add to its self-capacitance;
    /// may be negative: the facing layers' share of its voltage).
    pub across_f: Vec<f64>,
    /// Between terminals of different windings, or a winding and a shield (>= 0).
    pub caps: Vec<(Terminal, Terminal, f64)>,
}

/// Each layer's share of its winding's turns from the dotted end at its two ends along
/// the leg, (at z0, at z1): a winding starts at its dotted end, its sections in the order
/// listed, each section's first layer from z0 to z1 and every next layer back (a section
/// starting at z0 is an assumption: a lead out at the same flange).
fn layer_shares(layout: &Layout, turns: &[f64]) -> Vec<(f64, f64)> {
    let mut cum = vec![0.0; turns.len()];
    let mut out = Vec::with_capacity(layout.layers.len());
    let mut prev_section = usize::MAX;
    let mut index = 0;
    for l in &layout.layers {
        if l.section != prev_section {
            prev_section = l.section;
            index = 0;
        }
        let f0 = cum[l.winding] / turns[l.winding];
        cum[l.winding] += l.turns;
        let f1 = cum[l.winding] / turns[l.winding];
        out.push(if index % 2 == 0 { (f0, f1) } else { (f1, f0) });
        index += 1;
    }
    out
}

/// The facing side's shares at its two ends: a layer winding's facing layer along the leg
/// (z0, z1); a disc's side face from its inner layer to its outer (the section's first and
/// last turn).
fn face_shares(
    layout: &Layout,
    shares: &[(f64, f64)],
    p: &Placed,
    toward_next: bool,
) -> (f64, f64) {
    let Placed::Winding { layers: ids, .. } = p else {
        unreachable!()
    };
    match layout.arrangement {
        Arrangement::Layer => {
            shares[if toward_next {
                *ids.last().unwrap()
            } else {
                ids[0]
            }]
        }
        Arrangement::Disc => {
            // The first layer's start and the last layer's end: the section's first and
            // last turn.
            let (a, b) = (shares[ids[0]], shares[*ids.last().unwrap()]);
            (a.0.min(a.1), b.0.max(b.1))
        }
    }
}

pub fn network(layout: &Layout, n: usize, turns: &[f64], caps: &Capacitances) -> Network {
    let shares = layer_shares(layout, turns);
    let mut shields: Vec<String> = Vec::new();
    for s in &caps.to_shields {
        if !shields.contains(&s.shield) {
            shields.push(s.shield.clone());
        }
    }
    let size = 2 * n + shields.len();
    let mut q = vec![vec![0.0; size]; size];
    // x(f) of winding k: (1 - f) at its dotted end, f at its other end.
    let x = |k: usize, f: f64| {
        let mut v = vec![0.0; size];
        v[2 * k] = 1.0 - f;
        v[2 * k + 1] = f;
        v
    };
    let mut add = |a0: Vec<f64>, a1: Vec<f64>, c: f64| {
        for i in 0..size {
            for j in 0..size {
                q[i][j] += c / 3.0
                    * (a0[i] * a0[j] + a1[i] * a1[j] + 0.5 * (a0[i] * a1[j] + a1[i] * a0[j]));
            }
        }
    };
    let sub = |a: Vec<f64>, b: Vec<f64>| a.iter().zip(&b).map(|(x, y)| x - y).collect::<Vec<f64>>();
    for b in &caps.between {
        let (pa, pb) = (&layout.placed[b.sections.0], &layout.placed[b.sections.1]);
        let fa = face_shares(layout, &shares, pa, true);
        let fb = face_shares(layout, &shares, pb, false);
        add(
            sub(x(b.a, fa.0), x(b.b, fb.0)),
            sub(x(b.a, fa.1), x(b.b, fb.1)),
            b.c_f,
        );
    }
    for s in &caps.to_shields {
        let (wi, si) = s.sections;
        let fa = face_shares(layout, &shares, &layout.placed[wi], wi < si);
        let mut e = vec![0.0; size];
        e[2 * n + shields.iter().position(|x| *x == s.shield).unwrap()] = 1.0;
        add(
            sub(x(s.winding, fa.0), e.clone()),
            sub(x(s.winding, fa.1), e),
            s.c_f,
        );
    }
    let term = |i: usize| {
        if i < 2 * n {
            if i.is_multiple_of(2) {
                Terminal::Dot(i / 2)
            } else {
                Terminal::Other(i / 2)
            }
        } else {
            Terminal::Shield(shields[i - 2 * n].clone())
        }
    };
    let mut across_f = vec![0.0; n];
    let mut out = Vec::new();
    for (i, row) in q.iter().enumerate() {
        for (j, qij) in row.iter().enumerate().skip(i + 1) {
            let c = -qij;
            if i < 2 * n && j == i + 1 && i.is_multiple_of(2) {
                across_f[i / 2] += c;
            } else if c.abs() > 1e-21 {
                out.push((term(i), term(j), c));
            }
        }
    }
    Network {
        across_f,
        caps: out,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn eps0_is_right() {
        assert!((eps0() / 8.8541878128e-12 - 1.0).abs() < 1e-9);
    }

    #[test]
    fn a_thick_sheet_dominates() {
        let w = WireSide {
            bare_m: 0.1e-3,
            overall_m: 0.11e-3,
            enamel_eps: 3.5,
        };
        let c = layer_c_per_area(w, w, 1e-3, 1e-3 / 2.0);
        let plate = eps0() * 2.0 / 1e-3;
        assert!(c < plate && c > 0.9 * plate);
    }

    /// The network's energy equals the facing layers' for any terminal voltages: a P | S
    /// pair, voltages at random.
    #[test]
    fn the_network_holds_the_facing_energy() {
        // C (U0^2 + U0 U1 + U1^2) / 6 with U = x_A(f) - x_B(g) at both ends.
        let (fa, fb, c) = ((0.75, 1.0), (0.0, 0.5), 100e-12);
        let mut q = vec![vec![0.0; 4]; 4];
        let xa = |f: f64| [1.0 - f, f, 0.0, 0.0];
        let xb = |f: f64| [0.0, 0.0, 1.0 - f, f];
        let a0: Vec<f64> = (0..4).map(|i| xa(fa.0)[i] - xb(fb.0)[i]).collect();
        let a1: Vec<f64> = (0..4).map(|i| xa(fa.1)[i] - xb(fb.1)[i]).collect();
        for i in 0..4 {
            for j in 0..4 {
                q[i][j] = c / 3.0
                    * (a0[i] * a0[j] + a1[i] * a1[j] + 0.5 * (a0[i] * a1[j] + a1[i] * a0[j]));
            }
        }
        for v in [
            [1.0, -2.0, 0.5, 3.0],
            [0.3, 0.3, 0.3, 0.3],
            [5.0, 0.0, 0.0, 0.0],
        ] {
            let u0: f64 = (0..4).map(|i| a0[i] * v[i]).sum();
            let u1: f64 = (0..4).map(|i| a1[i] * v[i]).sum();
            let want = c / 6.0 * (u0 * u0 + u0 * u1 + u1 * u1);
            // Capacitors -Q_ij between every pair: sum over pairs of C_ij (v_i - v_j)^2 / 2.
            let mut w = 0.0;
            for i in 0..4 {
                for j in (i + 1)..4 {
                    w += 0.5 * -q[i][j] * (v[i] - v[j]) * (v[i] - v[j]);
                }
            }
            assert!(
                (w - want).abs() <= 1e-12 * want.abs().max(1e-30),
                "{w} vs {want}"
            );
        }
        // Cross capacitors (A to B) are never negative.
        for row in &q[..2] {
            assert!(row[2..].iter().all(|qij| -qij >= 0.0));
        }
    }

    /// Shen et al. 2019 eqs. (3)-(4) by hand: 0.1 mm wire, 5 um enamel (eps 3.5), 50 um of
    /// tape (eps 2.0).
    #[test]
    fn shen_by_hand() {
        let w = WireSide {
            bare_m: 0.1e-3,
            overall_m: 0.11e-3,
            enamel_eps: 3.5,
        };
        let (dw, dt) = (5e-6, 50e-6);
        let a_iso = 2.0 * dw + dt;
        let d_eff = a_iso - 0.15 * 0.1e-3 + 0.26 * (2.0 * dw + 0.1e-3);
        let eps = 3.5 * 2.0 * a_iso / (3.5 * dt + 2.0 * 2.0 * dw);
        let want = eps0() * eps / d_eff;
        let got = layer_c_per_area(w, w, dt, dt / 2.0);
        assert!((got / want - 1.0).abs() < 1e-12);
    }
}
