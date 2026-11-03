//! A compiled transformer's frequency response between a stated source and load: the
//! small-signal network the `transformer` macro builds from the compiled values
//! (`varimu_circuit::parts::transformer`), solved at each frequency.
//!
//! Each winding k runs from its dotted end through its DC resistance and its series
//! leakage (the compiled star, or the coupled leakage matrix) into its share of the core:
//! v = N_k A dB/dt. The core node is the circuit's (B in mT as volts): the windings' MMF
//! sum_k N_k i_k drives its linear-limit conductance with the gap's (`Compiled::core_g`)
//! and the laminations' eddy-current capacitance (`Compiled::eddy_c`). Each winding's own
//! capacitance sits across its ends and the compiled facing capacitances between their
//! terminals. The core is in its linear limit: the response is the small-signal one, with
//! no hysteresis and no saturation (those are heard in the circuit).
//!
//! The source is an EMF behind `source_ohm`, driving the `drive` windings in series (each
//! one's other end to the next one's dotted end): grounded at the last winding's other end,
//! or balanced (two halves of the EMF and of the source resistance at the two ends, the
//! junction in the middle grounded: a push-pull pair's plates). The load is `load_ohm`
//! across the `load` winding, its other end grounded. Shields are grounded; windings in
//! neither are open. The answer is the load's voltage over the EMF.

use std::f64::consts::PI;

use num_complex::Complex64 as C;

use crate::capacitance::Terminal;
use crate::compile::Compiled;

/// Where the drive is grounded.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ground {
    /// At the last drive winding's other end.
    End,
    /// At the middle junction (an even number of drive windings): a balanced source.
    Middle,
}

/// The stated source and load.
#[derive(Debug, Clone, PartialEq)]
pub struct Setup {
    /// Winding indices, in series in this order.
    pub drive: Vec<usize>,
    pub ground: Ground,
    pub source_ohm: f64,
    pub load: usize,
    pub load_ohm: f64,
}

impl Setup {
    /// A default for `c`: the rating's windings driven (else the first), balanced when
    /// there are two of them; the load across the remaining winding with the fewest turns,
    /// 8 ohm when it steps down by 10 or more (a loudspeaker), else 100 kOhm (a grid); the
    /// source the load reflected through the turns ratio (a matched source, as output
    /// transformers' responses are commonly measured). The view states it and lets it be
    /// changed.
    pub fn default_for(c: &Compiled) -> Option<Setup> {
        let d = &c.design;
        let n = c.windings.len();
        if n < 2 {
            return None;
        }
        let drive: Vec<usize> = match &d.rating {
            Some(r) if r.windings.len() < n => {
                r.windings.iter().map(|w| d.winding_index(w)).collect()
            }
            _ => vec![0],
        };
        let load = (0..n)
            .filter(|k| !drive.contains(k))
            .min_by(|&a, &b| c.windings[a].turns.total_cmp(&c.windings[b].turns))?;
        let nd: f64 = drive.iter().map(|&k| c.windings[k].turns).sum();
        let ratio = nd / c.windings[load].turns;
        let load_ohm = if ratio >= 10.0 { 8.0 } else { 100e3 };
        Some(Setup {
            ground: if drive.len() == 2 {
                Ground::Middle
            } else {
                Ground::End
            },
            drive,
            source_ohm: load_ohm * ratio * ratio,
            load,
            load_ohm,
        })
    }
}

/// The small-signal network, from a compiled transformer.
#[derive(Debug, Clone, PartialEq)]
pub struct Network {
    /// Per winding: turns, DC resistance, capacitance across it.
    pub turns: Vec<f64>,
    pub r_ohm: Vec<f64>,
    pub c_f: Vec<f64>,
    /// The series leakages (H; diagonal for a star).
    pub leak_h: Vec<Vec<f64>>,
    /// The core's area and its node's conductance and eddy capacitance.
    pub area_m2: f64,
    pub core_g: f64,
    pub eddy_c: f64,
    pub caps: Vec<(Terminal, Terminal, f64)>,
}

impl Network {
    pub fn of(c: &Compiled) -> Network {
        Network {
            turns: c.windings.iter().map(|w| w.turns).collect(),
            r_ohm: c.windings.iter().map(|w| w.r_ohm).collect(),
            c_f: c.windings.iter().map(|w| w.c_f).collect(),
            leak_h: c.leak_matrix_h.clone(),
            area_m2: c.area_m2,
            core_g: c.core_g,
            eddy_c: c.eddy_c,
            caps: c.network.caps.clone(),
        }
    }
}

/// A tiny conductance from every node to ground: open windings and their capacitors
/// would otherwise float.
const GMIN: f64 = 1e-12;

/// Dense complex Gaussian elimination with partial pivoting: `a x = b`.
fn solve(mut a: Vec<Vec<C>>, mut b: Vec<C>) -> Option<Vec<C>> {
    let n = b.len();
    for col in 0..n {
        let p = (col..n).max_by(|&i, &j| a[i][col].norm().total_cmp(&a[j][col].norm()))?;
        if a[p][col].norm() == 0.0 {
            return None;
        }
        a.swap(col, p);
        b.swap(col, p);
        let (top, rest) = a.split_at_mut(col + 1);
        let pivot = &top[col];
        for (i, r) in rest.iter_mut().enumerate() {
            let f = r[col] / pivot[col];
            if f != C::new(0.0, 0.0) {
                for (x, &y) in r[col..].iter_mut().zip(&pivot[col..]) {
                    *x -= f * y;
                }
                let y = b[col];
                b[col + 1 + i] -= f * y;
            }
        }
    }
    let mut x = vec![C::new(0.0, 0.0); n];
    for row in (0..n).rev() {
        let s: C = ((row + 1)..n).map(|k| a[row][k] * x[k]).sum();
        x[row] = (b[row] - s) / a[row][row];
    }
    Some(x)
}

/// The load's voltage over the source's EMF at `f_hz`, and the impedance the source's
/// terminals see into the drive windings (ohm; the source resistance excluded).
pub fn at(net: &Network, s: &Setup, f_hz: f64) -> Option<(C, C)> {
    let n = net.turns.len();
    let w = 2.0 * PI * f_hz;
    let jw = C::new(0.0, w);
    // Nodes: each winding's dotted end, other end, and the point between its resistance
    // and its leakage; ground is fixed and has no unknown. Shields are grounded.
    const G: usize = usize::MAX;
    let mut dot = vec![0; n];
    let mut other = vec![0; n];
    let mut mid = vec![0; n];
    let mut count = 0;
    let mut node = || {
        count += 1;
        count - 1
    };
    let in_drive = |k: usize| s.drive.iter().position(|&x| x == k);
    let mut junction = Vec::new();
    for k in 0..n {
        dot[k] = node();
        mid[k] = node();
    }
    // The drive's series connection: each drive winding's other end is the next one's
    // dotted end.
    for (k, o) in other.iter_mut().enumerate() {
        *o = match in_drive(k) {
            Some(i) if i + 1 < s.drive.len() => dot[s.drive[i + 1]],
            Some(_) if s.ground == Ground::End => G,
            _ if k == s.load => G,
            _ => node(),
        };
    }
    if s.ground == Ground::Middle {
        if !s.drive.len().is_multiple_of(2) {
            return None;
        }
        let m = s.drive[s.drive.len() / 2];
        junction.push(dot[m]);
    }
    let nv = count;
    // Unknowns: node voltages, each winding's current (dot to other), the core node.
    let size = nv + n + 1;
    let core = nv + n;
    let zero = C::new(0.0, 0.0);
    let mut a = vec![vec![zero; size]; size];
    let mut b = vec![zero; size];
    let stamp_y = |a: &mut Vec<Vec<C>>, p: usize, q: usize, y: C| {
        if p != G {
            a[p][p] += y;
        }
        if q != G {
            a[q][q] += y;
        }
        if p != G && q != G {
            a[p][q] -= y;
            a[q][p] -= y;
        }
    };
    for (i, row) in a.iter_mut().enumerate().take(nv) {
        row[i] += C::new(GMIN, 0.0);
    }
    // A grounded junction: a large conductance (the node stays an unknown).
    for &j in &junction {
        a[j][j] += C::new(1e9, 0.0);
    }
    for k in 0..n {
        let r = net.r_ohm[k].max(1e-9);
        stamp_y(&mut a, dot[k], mid[k], C::new(1.0 / r, 0.0));
        stamp_y(&mut a, dot[k], other[k], jw * net.c_f[k]);
        // The winding's current leaves mid and enters other.
        let i = nv + k;
        a[mid[k]][i] += C::new(1.0, 0.0);
        if other[k] != G {
            a[other[k]][i] -= C::new(1.0, 0.0);
        }
        // Branch: v(mid) - v(other) - jw sum_j L_kj i_j - jw N_k A T v(core) = 0.
        a[i][mid[k]] += C::new(1.0, 0.0);
        if other[k] != G {
            a[i][other[k]] -= C::new(1.0, 0.0);
        }
        for j in 0..n {
            a[i][nv + j] -= jw * net.leak_h[k][j];
        }
        a[i][core] -= jw * (net.turns[k] * net.area_m2 * circuitsim::ir::TESLA_PER_V);
        // Core: sum_k N_k i_k - (g + jw C_e) v(core) = 0.
        a[core][i] += C::new(net.turns[k], 0.0);
    }
    a[core][core] -= C::new(net.core_g, 0.0) + jw * net.eddy_c;
    let term = |t: &Terminal| match t {
        Terminal::Dot(k) => dot[*k],
        Terminal::Other(k) => other[*k],
        Terminal::Shield(_) => G,
    };
    for (p, q, c) in &net.caps {
        stamp_y(&mut a, term(p), term(q), jw * *c);
    }
    // The load.
    stamp_y(
        &mut a,
        dot[s.load],
        other[s.load],
        C::new(1.0 / s.load_ohm, 0.0),
    );
    // The source: Norton equivalents of a unit EMF behind the source resistance.
    let first = dot[s.drive[0]];
    let last = s.drive[s.drive.len() - 1];
    let rs = s.source_ohm.max(1e-9);
    let (top, bottom) = match s.ground {
        Ground::End => (first, G),
        Ground::Middle => (first, other[last]),
    };
    match s.ground {
        Ground::End => {
            stamp_y(&mut a, top, G, C::new(1.0 / rs, 0.0));
            b[top] += C::new(1.0 / rs, 0.0);
        }
        Ground::Middle => {
            let half = 0.5 * rs;
            stamp_y(&mut a, top, G, C::new(1.0 / half, 0.0));
            b[top] += C::new(0.5 / half, 0.0);
            stamp_y(&mut a, bottom, G, C::new(1.0 / half, 0.0));
            b[bottom] -= C::new(0.5 / half, 0.0);
        }
    }
    let x = solve(a, b)?;
    let v = |p: usize| if p == G { zero } else { x[p] };
    let h = v(dot[s.load]) - v(other[s.load]);
    let v_in = v(top) - v(bottom);
    // The current out of the source's top terminal.
    let i_in = match s.ground {
        Ground::End => (C::new(1.0, 0.0) - v(top)) / rs,
        Ground::Middle => (C::new(0.5, 0.0) - v(top)) / (0.5 * rs),
    };
    let z_in = v_in / i_in;
    Some((h, z_in))
}

/// Log-spaced frequencies from `f0` to `f1` (Hz), `per_octave` a octave.
pub fn frequencies(f0: f64, f1: f64, per_octave: usize) -> Vec<f64> {
    let octaves = (f1 / f0).log2();
    let m = (octaves * per_octave as f64).ceil() as usize;
    (0..=m)
        .map(|i| f0 * 2f64.powf(octaves * i as f64 / m as f64))
        .collect()
}

/// A response over frequency, in dB relative to its value at 1 kHz, with the level at
/// 1 kHz relative to the ideal transformer's (the turns ratio into the load with the
/// source and load resistances only: the insertion loss of the windings) and the -3 dB
/// points.
#[derive(Debug, Clone, PartialEq)]
pub struct Curve {
    pub f_hz: Vec<f64>,
    pub db: Vec<f64>,
    /// |Z| the source sees (ohm) at each frequency.
    pub z_in_ohm: Vec<f64>,
    pub loss_1khz_db: f64,
    pub low_3db_hz: Option<f64>,
    pub high_3db_hz: Option<f64>,
}

pub fn curve(net: &Network, s: &Setup, f_hz: &[f64]) -> Option<Curve> {
    let (h1k, _) = at(net, s, 1000.0)?;
    let ref_db = 20.0 * h1k.norm().log10();
    let mut db = Vec::with_capacity(f_hz.len());
    let mut z = Vec::with_capacity(f_hz.len());
    for &f in f_hz {
        let (h, zi) = at(net, s, f)?;
        db.push(20.0 * h.norm().log10() - ref_db);
        z.push(zi.norm());
    }
    let nd: f64 = s.drive.iter().map(|&k| net.turns[k]).sum();
    let ratio = net.turns[s.load] / nd;
    let reflected = s.load_ohm / (ratio * ratio);
    let ideal = ratio * reflected / (reflected + s.source_ohm);
    let crossing = |range: Box<dyn Iterator<Item = usize>>| {
        let mut prev: Option<usize> = None;
        for i in range {
            if db[i] < -3.0 {
                let p = prev?;
                let t = (-3.0 - db[p]) / (db[i] - db[p]);
                return Some(f_hz[p] * (f_hz[i] / f_hz[p]).powf(t));
            }
            prev = Some(i);
        }
        None
    };
    let k1 = f_hz.iter().position(|&f| f >= 1000.0).unwrap_or(0);
    let low = crossing(Box::new((0..=k1).rev()));
    let high = crossing(Box::new(k1..f_hz.len()));
    Some(Curve {
        f_hz: f_hz.to_vec(),
        db,
        z_in_ohm: z,
        loss_1khz_db: ref_db - 20.0 * ideal.log10(),
        low_3db_hz: low,
        high_3db_hz: high,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Two windings, no capacitance: the T equivalent by hand.
    #[test]
    fn two_windings_match_the_t_equivalent() {
        let (n1, n2) = (1000.0, 50.0);
        let area = 4e-4;
        let lm = 10.0;
        // L = N^2 A T / g.
        let g = n1 * n1 * area * circuitsim::ir::TESLA_PER_V / lm;
        let (r1, r2, l1, l2) = (120.0, 0.4, 0.02, 3e-5);
        let net = Network {
            turns: vec![n1, n2],
            r_ohm: vec![r1, r2],
            c_f: vec![0.0, 0.0],
            leak_h: vec![vec![l1, 0.0], vec![0.0, l2]],
            area_m2: area,
            core_g: g,
            eddy_c: 0.0,
            caps: vec![],
        };
        let s = Setup {
            drive: vec![0],
            ground: Ground::End,
            source_ohm: 3000.0,
            load: 1,
            load_ohm: 8.0,
        };
        for f in [20.0, 100.0, 1000.0, 15e3] {
            let (h, _) = at(&net, &s, f).unwrap();
            let jw = C::new(0.0, 2.0 * PI * f);
            let n = n2 / n1;
            let z2 = (C::new(r2 + 8.0, 0.0) + jw * l2) / (n * n);
            let zm = jw * lm;
            let zp = z2 * zm / (z2 + zm);
            let vm = zp / (C::new(3000.0 + r1, 0.0) + jw * l1 + zp);
            let want = vm * n * 8.0 / (C::new(r2 + 8.0, 0.0) + jw * l2);
            assert!(
                (h - want).norm() < 1e-7 * want.norm(),
                "{f} Hz: {h} vs {want}"
            );
        }
    }

    /// A balanced drive of two equal halves gives the series drive's answer when nothing
    /// couples to the junction (unequal halves differ: each is driven by its own half of
    /// the source, as a push-pull pair's plates are).
    #[test]
    fn balanced_equals_grounded_without_capacitance() {
        let area = 4e-4;
        let g = 2000.0f64.powi(2) * area * circuitsim::ir::TESLA_PER_V / 40.0;
        let net = Network {
            turns: vec![1000.0, 1000.0, 60.0],
            r_ohm: vec![150.0, 150.0, 0.5],
            c_f: vec![0.0; 3],
            leak_h: vec![
                vec![0.03, 0.0, 0.0],
                vec![0.0, 0.03, 0.0],
                vec![0.0, 0.0, 2e-5],
            ],
            area_m2: area,
            core_g: g,
            eddy_c: 1e-9,
            caps: vec![],
        };
        let mut s = Setup {
            drive: vec![0, 1],
            ground: Ground::End,
            source_ohm: 8000.0,
            load: 2,
            load_ohm: 8.0,
        };
        let (a, za) = at(&net, &s, 3000.0).unwrap();
        s.ground = Ground::Middle;
        let (b, zb) = at(&net, &s, 3000.0).unwrap();
        assert!((a - b).norm() < 1e-6 * a.norm(), "{a} {b}");
        assert!((za - zb).norm() < 1e-6 * za.norm(), "{za} {zb}");
    }
}
