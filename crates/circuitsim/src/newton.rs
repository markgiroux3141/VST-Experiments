//! Newton's method on the full MNA system, solved by block elimination.
//!
//! Each time step (and the DC operating point) solves
//!
//! ```text
//! A x + d(x) = r
//! ```
//!
//! with `A` the constant step matrix (`G + 2C/h`, or `G` at DC), `r` the
//! sources and history, and `d(x)` the device currents leaving each node.
//! Devices only touch a few unknowns. Ordering those last (the set N; the
//! rest is L), the linear unknowns can be eliminated once per step size:
//!
//! ```text
//! S   = A_NN - A_NL A_LL^-1 A_LN          (Schur complement, factored once)
//! r_N' = r_N - A_NL A_LL^-1 r_L            (once per step)
//! S x_N + d(x_N) = r_N'                    (Newton, on N unknowns only)
//! x_L = A_LL^-1 r_L - A_LL^-1 A_LN x_N     (once per step)
//! ```
//!
//! The Newton iterates are exactly those of Newton on all unknowns; only the
//! linear algebra is reorganized. For the 670 that is a 27 x 27 refactor per
//! iteration instead of 83 x 83. (The nodal DK method of M5 goes further and
//! also folds the reactive state into a state-space system.)
//!
//! N is the set of device-pin nodes, in a fixed order, plus any unknown that
//! `A_LL` can't do without: a voltage source or inductor whose branch row
//! only involves device nodes leaves `A_LL` singular, so it joins N.
//!
//! The iteration is SPICE's: each device is linearized at its (limited) port
//! voltages and stamped as conductances plus an equivalent current; the
//! iteration has converged when no device was limited and no device-node
//! voltage moved by more than `reltol * |v| + vntol`.

use crate::devices::Device;
use crate::linalg::{Lu, Matrix, Singular};
use crate::mna::DeviceInstance;

/// `A` split into the device-touched unknowns N and the rest L.
#[derive(Debug, Clone)]
pub struct Reduced {
    /// Full index of each N unknown: the device nodes first (in the order
    /// given to [`Reduced::new`]), then any that had to join them.
    pub n_idx: Vec<usize>,
    l_idx: Vec<usize>,
    lu_ll: Lu,
    /// `A_LL^-1 A_LN`, n_L x n_N, row-major.
    w: Vec<f64>,
    /// `A_NL`, n_N x n_L, row-major.
    a_nl: Vec<f64>,
    /// The Schur complement.
    pub s: Matrix,
}

impl Reduced {
    /// Partition and factor `a`. Never fails: if `a` itself is singular, the
    /// unknowns responsible end up in N, and Newton reports the singular
    /// Jacobian there (naming the unknown).
    pub fn new(a: &Matrix, device_nodes: &[usize]) -> Reduced {
        let n = a.n();
        let mut n_idx = device_nodes.to_vec();
        let mut in_n = vec![false; n];
        for &i in &n_idx {
            in_n[i] = true;
        }
        loop {
            let l_idx: Vec<usize> = (0..n).filter(|&i| !in_n[i]).collect();
            let nl = l_idx.len();
            let mut a_ll = Matrix::zeros(nl);
            for (r, &i) in l_idx.iter().enumerate() {
                for (c, &j) in l_idx.iter().enumerate() {
                    a_ll.set(r, c, a.get(i, j));
                }
            }
            let lu_ll = match Lu::factor(&a_ll) {
                Ok(lu) => lu,
                Err(Singular { column }) => {
                    in_n[l_idx[column]] = true;
                    n_idx.push(l_idx[column]);
                    continue;
                }
            };
            let nn = n_idx.len();
            let mut w = vec![0.0; nl * nn];
            let (mut col, mut work) = (vec![0.0; nl], vec![0.0; nl]);
            for (c, &j) in n_idx.iter().enumerate() {
                for (r, &i) in l_idx.iter().enumerate() {
                    col[r] = a.get(i, j);
                }
                lu_ll.solve(&mut col, &mut work);
                for (r, x) in col.iter().enumerate() {
                    w[r * nn + c] = *x;
                }
            }
            let mut a_nl = vec![0.0; nn * nl];
            let mut s = Matrix::zeros(nn);
            for (r, &i) in n_idx.iter().enumerate() {
                for (c, &j) in l_idx.iter().enumerate() {
                    a_nl[r * nl + c] = a.get(i, j);
                }
                for (c, &j) in n_idx.iter().enumerate() {
                    let corr: f64 = (0..nl).map(|k| a_nl[r * nl + k] * w[k * nn + c]).sum();
                    s.set(r, c, a.get(i, j) - corr);
                }
            }
            return Reduced {
                n_idx,
                l_idx,
                lu_ll,
                w,
                a_nl,
                s,
            };
        }
    }

    pub fn n_len(&self) -> usize {
        self.n_idx.len()
    }

    pub fn l_len(&self) -> usize {
        self.l_idx.len()
    }

    /// From the full right-hand side `r`: `y = A_LL^-1 r_L` and the reduced
    /// `rn = r_N - A_NL y`. `work` has length n_L.
    pub fn reduce(&self, r: &[f64], y: &mut [f64], rn: &mut [f64], work: &mut [f64]) {
        for (y, &i) in y.iter_mut().zip(&self.l_idx) {
            *y = r[i];
        }
        self.lu_ll.solve(y, work);
        let nl = self.l_idx.len();
        for (a, (rn, &i)) in rn.iter_mut().zip(&self.n_idx).enumerate() {
            let row = &self.a_nl[a * nl..(a + 1) * nl];
            *rn = r[i] - row.iter().zip(y.iter()).map(|(p, q)| p * q).sum::<f64>();
        }
    }

    /// The full solution from `y` (see [`Reduced::reduce`]) and `xn`.
    pub fn expand(&self, y: &[f64], xn: &[f64], x: &mut [f64]) {
        for (&i, &v) in self.n_idx.iter().zip(xn) {
            x[i] = v;
        }
        let nn = self.n_idx.len();
        for (k, &i) in self.l_idx.iter().enumerate() {
            let row = &self.w[k * nn..(k + 1) * nn];
            x[i] = y[k] - row.iter().zip(xn).map(|(p, q)| p * q).sum::<f64>();
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct NewtonOptions {
    /// Relative tolerance on device-node voltage updates.
    pub reltol: f64,
    /// Absolute tolerance on device-node voltage updates (V).
    pub vntol: f64,
    pub max_iter: usize,
    /// Conductance (S) from every device node to ground, for gmin stepping.
    pub gshunt: f64,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Failure {
    /// The Jacobian is singular at this N position.
    Singular { position: usize },
    /// No convergence in `max_iter`; the device node at `position` had the
    /// largest last update relative to its tolerance.
    NoConvergence { position: usize, update: f64 },
}

/// Newton's scratch space and the devices' linearization points.
///
/// The system may hold several copies of the circuit (the stages of a fully
/// implicit Runge-Kutta step, see `transient.rs`): copy c's unknowns are the
/// circuit's shifted by c x `stride`, and every device is placed once per
/// copy, placement `c * n_devices + d`.
#[derive(Debug, Clone)]
pub struct Newton {
    /// N position of each pin (`None` = ground), per placement. Device
    /// nodes are the first entries of every [`Reduced`]'s N.
    pin_pos: Vec<Vec<Option<usize>>>,
    /// Offset of each placement's ports in `v_lin`.
    offsets: Vec<usize>,
    n_devices: usize,
    n_device_nodes: usize,
    /// Port voltages at which each placement was last linearized. Callers
    /// set them before a solve (the previous accepted point, for limiting).
    pub v_lin: Vec<f64>,
    j: Matrix,
    lu: Lu,
    rhs: Vec<f64>,
    work: Vec<f64>,
    v: Vec<f64>,
    i: Vec<f64>,
    g: Vec<f64>,
}

impl Newton {
    /// `device_nodes`: the full indices of every device-pin node (N's prefix).
    pub fn new(devices: &[DeviceInstance], device_nodes: &[usize]) -> Newton {
        Newton::with_copies(devices, device_nodes, 1)
    }

    /// For a system of `copies` copies of the circuit, whose N starts with
    /// copy 0's `device_nodes`, then copy 1's, and so on (see
    /// [`Newton::copy_nodes`]).
    pub fn with_copies(
        devices: &[DeviceInstance],
        device_nodes: &[usize],
        copies: usize,
    ) -> Newton {
        let nd = device_nodes.len();
        let pos = |full: Option<usize>| {
            full.map(|f| {
                device_nodes
                    .iter()
                    .position(|&d| d == f)
                    .expect("device node")
            })
        };
        let mut pin_pos: Vec<Vec<Option<usize>>> = Vec::with_capacity(copies * devices.len());
        for c in 0..copies {
            for d in devices {
                pin_pos.push(d.pins.iter().map(|&p| pos(p).map(|a| a + c * nd)).collect());
            }
        }
        let mut offsets = Vec::with_capacity(pin_pos.len());
        let mut total = 0;
        let mut widest = 0;
        for _ in 0..copies {
            for d in devices {
                offsets.push(total);
                total += d.device.ports();
                widest = widest.max(d.device.ports());
            }
        }
        Newton {
            pin_pos,
            offsets,
            n_devices: devices.len(),
            n_device_nodes: copies * nd,
            v_lin: vec![0.0; total],
            j: Matrix::zeros(0),
            lu: Lu::with_size(0),
            rhs: Vec::new(),
            work: Vec::new(),
            v: vec![0.0; widest],
            i: vec![0.0; widest],
            g: vec![0.0; widest * widest],
        }
    }

    /// The full indices of a `copies`-copy system's device nodes, in the
    /// order [`Newton::with_copies`] expects (`stride`: unknowns per copy).
    pub fn copy_nodes(device_nodes: &[usize], copies: usize, stride: usize) -> Vec<usize> {
        (0..copies)
            .flat_map(|c| device_nodes.iter().map(move |&d| d + c * stride))
            .collect()
    }

    /// Port voltages of every device in copy 0 for the device-node voltages
    /// `xn` (the first entries of an N vector), into `out` (laid out like
    /// copy 0's part of `v_lin`).
    pub fn ports(&self, devices: &[DeviceInstance], xn: &[f64], out: &mut [f64]) {
        self.copy_ports(devices, xn, 0, out);
    }

    /// Like [`Newton::ports`], for copy `c`.
    pub fn copy_ports(&self, devices: &[DeviceInstance], xn: &[f64], c: usize, out: &mut [f64]) {
        let first = c * self.n_devices;
        let Some(&base) = self.offsets.get(first) else {
            return; // no devices
        };
        for (d, (pins, &off)) in devices.iter().zip(
            self.pin_pos[first..first + self.n_devices]
                .iter()
                .zip(&self.offsets[first..]),
        ) {
            let at = |p: Option<usize>| p.map_or(0.0, |a| xn[a]);
            let vref = at(*pins.last().expect("devices have pins"));
            for (j, o) in out[off - base..off - base + d.device.ports()]
                .iter_mut()
                .enumerate()
            {
                *o = at(pins[j]) - vref;
            }
        }
    }

    /// Solve `S x + d(x) = rn` for `xn` (the guess on entry). Returns the
    /// number of iterations.
    pub fn solve(
        &mut self,
        sys: &Reduced,
        devices: &[DeviceInstance],
        rn: &[f64],
        xn: &mut [f64],
        opts: &NewtonOptions,
    ) -> Result<usize, Failure> {
        let nn = sys.n_len();
        if self.j.n() != nn {
            self.j = Matrix::zeros(nn);
            self.lu = Lu::with_size(nn);
            self.rhs = vec![0.0; nn];
            self.work = vec![0.0; nn];
        }
        let mut worst = (0, f64::NAN);
        for iter in 1..=opts.max_iter {
            self.j.copy_from(&sys.s);
            self.rhs.copy_from_slice(rn);
            if opts.gshunt > 0.0 {
                for a in 0..self.n_device_nodes {
                    self.j.add(a, a, opts.gshunt);
                }
            }
            let mut limited = false;
            for p in 0..self.pin_pos.len() {
                limited |= self.stamp(p, &*devices[p % self.n_devices].device, xn);
            }
            self.lu
                .refactor(&self.j)
                .map_err(|Singular { column }| Failure::Singular { position: column })?;
            self.lu.solve(&mut self.rhs, &mut self.work);

            // Converged when no device was limited and the device nodes have
            // settled. A NaN update counts as not settled, and as the worst.
            let mut converged = !limited;
            worst = (0, 0.0);
            let mut worst_ratio = 0.0;
            let nd = self.n_device_nodes;
            for (a, (&old, &new)) in xn[..nd].iter().zip(&self.rhs[..nd]).enumerate() {
                let tol = opts.reltol * old.abs().max(new.abs()) + opts.vntol;
                let ratio = (new - old).abs() / tol;
                if ratio.is_nan() || ratio > 1.0 {
                    converged = false;
                }
                if ratio.is_nan() || ratio > worst_ratio {
                    worst_ratio = if ratio.is_nan() { f64::INFINITY } else { ratio };
                    worst = (a, new - old);
                }
            }
            xn.copy_from_slice(&self.rhs);
            if converged {
                return Ok(iter);
            }
            if xn.iter().any(|v| !v.is_finite()) {
                break;
            }
        }
        Err(Failure::NoConvergence {
            position: worst.0,
            update: worst.1,
        })
    }

    /// Solve with the Jacobian of the last iteration of the last [`Newton::solve`]
    /// (`b` is overwritten; `work` has the N length).
    pub fn solve_jacobian(&self, b: &mut [f64], work: &mut [f64]) {
        self.lu.solve(b, work);
    }

    /// Linearize device `d` at the (limited) port voltages of `xn` and stamp
    /// it into `j` and `rhs`. Returns whether limiting changed the voltages.
    fn stamp(&mut self, d: usize, dev: &dyn Device, xn: &[f64]) -> bool {
        let np = dev.ports();
        let pins = &self.pin_pos[d];
        let off = self.offsets[d];
        let at = |p: Option<usize>| p.map_or(0.0, |a| xn[a]);
        let r = *pins.last().expect("devices have pins");
        let vref = at(r);
        let v = &mut self.v[..np];
        for (j, v) in v.iter_mut().enumerate() {
            *v = at(pins[j]) - vref;
        }
        let v_lin = &mut self.v_lin[off..off + np];
        let limited = dev.limit(v, v_lin);
        v_lin.copy_from_slice(v);
        let (i, g) = (&mut self.i[..np], &mut self.g[..np * np]);
        dev.eval(v, i, g);

        // i_j(v') ~ i_j + sum_k g_jk (v'_k - v_k): conductances g_jk from port k
        // to port j, plus the equivalent current ieq_j = i_j - sum_k g_jk v_k,
        // flowing out of pin j and back into the reference pin.
        for j in 0..np {
            let pj = pins[j];
            let mut ieq = i[j];
            for k in 0..np {
                let gjk = g[j * np + k];
                if gjk == 0.0 {
                    continue;
                }
                ieq -= gjk * v[k];
                let pk = pins[k];
                for (row, sign) in [(pj, 1.0), (r, -1.0)] {
                    let Some(row) = row else { continue };
                    if let Some(c) = pk {
                        self.j.add(row, c, sign * gjk);
                    }
                    if let Some(c) = r {
                        self.j.add(row, c, -sign * gjk);
                    }
                }
            }
            if let Some(a) = pj {
                self.rhs[a] -= ieq;
            }
            if let Some(a) = r {
                self.rhs[a] += ieq;
            }
        }
        limited
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fixed, asymmetric, diagonally weighted test matrix.
    fn matrix(n: usize) -> Matrix {
        let mut m = Matrix::zeros(n);
        for i in 0..n {
            for j in 0..n {
                let x = ((i * 7 + j * 13) % 11) as f64 - 5.0;
                m.set(i, j, if i == j { 40.0 + x } else { x * 0.5 });
            }
        }
        m
    }

    #[test]
    fn reduced_solve_equals_the_full_solve() {
        let a = matrix(9);
        let r: Vec<f64> = (0..9).map(|i| (i as f64 * 0.7).sin()).collect();
        let mut full = r.clone();
        Lu::factor(&a).unwrap().solve(&mut full, &mut [0.0; 9]);

        let red = Reduced::new(&a, &[6, 2, 4]);
        assert_eq!(red.n_idx, [6, 2, 4]);
        let (mut y, mut rn, mut work) = (vec![0.0; 6], vec![0.0; 3], vec![0.0; 6]);
        red.reduce(&r, &mut y, &mut rn, &mut work);
        let mut xn = rn.clone();
        Lu::factor(&red.s).unwrap().solve(&mut xn, &mut [0.0; 3]);
        let mut x = vec![0.0; 9];
        red.expand(&y, &xn, &mut x);
        for (p, q) in x.iter().zip(&full) {
            assert!((p - q).abs() < 1e-14, "{p} vs {q}");
        }
    }

    #[test]
    fn unknowns_that_leave_a_ll_singular_join_n() {
        // Unknown 2 only couples to the device node 0 (like a voltage source
        // straight across a device), so A_LL without it is singular.
        let mut a = Matrix::zeros(3);
        for (i, j, x) in [
            (0, 0, 1.0),
            (0, 2, 1.0),
            (2, 0, 1.0),
            (1, 1, 2.0),
            (0, 1, -0.5),
        ] {
            a.set(i, j, x);
        }
        a.add(1, 0, -0.5);
        let red = Reduced::new(&a, &[0]);
        assert_eq!(red.n_idx, [0, 2]);
        assert_eq!(red.l_len(), 1);
    }
}
