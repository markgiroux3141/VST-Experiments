//! The leakage formulas against measured leakage of a published construction.
//!
//! Z. Ouyang, O. C. Thomsen, M. A. E. Andersen, "The Analysis and Comparison of Leakage
//! Inductance in Different Winding Arrangements for Planar Transformer", PEDS 2009,
//! pp. 1143-1148 (web: https://backend.orbit.dtu.dk/ws/files/4594800/Ouyang.pdf), Sec. II-V,
//! Table I: an EI 64/5/50 planar core, turn length 202 mm, copper 20 mm wide and 0.2 mm
//! thick, 0.3 mm insulation between layers, four primary and four secondary turns, one turn
//! per layer, stacked along the leg (a disc arrangement: the field runs across the 20 mm
//! copper width). Measured: PPPPSSSS 252.2 nH, PPSSPPSS 68.27 nH, PSPSPSPS 26.32 nH (the
//! paper puts the last one's excess on its connections and terminations).

use varimu_components::design::Arrangement;
use varimu_components::geometry::{FieldTurn, Layout, Slab, rogowski};
use varimu_components::leakage;

fn planar(order: &str) -> Layout {
    let (cu, ins) = (0.2e-3, 0.3e-3);
    let mut slabs = Vec::new();
    let mut x = 0.0;
    for (i, c) in order.chars().enumerate() {
        if i > 0 {
            slabs.push(Slab {
                x0_m: x,
                x1_m: x + ins,
                winding: None,
                turns: 0.0,
            });
            x += ins;
        }
        slabs.push(Slab {
            x0_m: x,
            x1_m: x + cu,
            winding: Some(usize::from(c == 'S')),
            turns: 1.0,
        });
        x += cu;
    }
    let b = 20e-3;
    Layout {
        arrangement: Arrangement::Disc,
        leg_m: 0.0,
        stack_m: 0.0,
        wall_m: 0.0,
        window_width_m: b,
        window_height_m: 0.0,
        traverse_m: 0.0,
        layers: vec![],
        placed: vec![],
        slabs,
        field_length_m: b / rogowski(b, x),
        field_turn: FieldTurn::Fixed(0.202),
        warnings: vec![],
    }
}

#[test]
fn ouyang_2009_planar_cases() {
    for (order, measured_nh, tol) in [
        ("PPPPSSSS", 252.2, 0.04),
        ("PPSSPPSS", 68.27, 0.04),
        // The paper's own 1D formulas miss this one by 2-16% (connections, terminations).
        ("PSPSPSPS", 26.32, 0.25),
    ] {
        let l = planar(order);
        let got_nh = 16.0 * leakage::pairs(&l, 2)[0][1] * 1e9;
        let err = got_nh / measured_nh - 1.0;
        println!(
            "{order}: {got_nh:.1} nH vs measured {measured_nh} nH ({:+.1}%)",
            100.0 * err
        );
        assert!(err.abs() < tol, "{order}: {got_nh} nH vs {measured_nh}");
    }
}
