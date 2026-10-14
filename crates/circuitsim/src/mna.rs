//! Modified nodal analysis: the circuit as `G x + C dx/dt = b + u(t) e_in`.
//!
//! Unknowns `x`: every non-ground node voltage (in order of first appearance
//! in the IR), then one branch current per DC voltage source and inductor (in
//! element order), then the current of the audio input source.
//!
//! - Resistor: conductance stamp in `G`.
//! - Capacitor: capacitance stamp in `C`.
//! - Voltage source and the input (`input_node` to ground): KCL entries plus a
//!   row `v_pos - v_neg = V`.
//! - Inductor k from a to b: KCL entries (current leaves a, enters b) plus a
//!   row `v_a - v_b - sum_j M_kj di_j/dt = 0`, with `M_kk = L_k` and, for each
//!   coupling, `M_kj = M_jk = k sqrt(L_k L_j)` (dotted ends are the `a` ends,
//!   like SPICE `K`). Stamping the inductance matrix directly means a
//!   k = 0.999 transformer never needs its ill-conditioned inverse.

use std::collections::HashMap;

use crate::Error;
use crate::ir::{CircuitIr, Element, GROUND, Probe};
use crate::linalg::Matrix;

/// What an entry of the unknown vector is.
#[derive(Debug, Clone, PartialEq)]
pub enum Unknown {
    /// Node voltage.
    Node(String),
    /// Branch current of a voltage source or inductor (element name).
    Branch(String),
    /// Current of the audio input source.
    Input,
}

impl Unknown {
    /// Human-readable, for error messages.
    pub fn describe(&self) -> String {
        match self {
            Unknown::Node(n) => format!("node {n}"),
            Unknown::Branch(e) => format!("branch current of {e}"),
            Unknown::Input => "input source current".to_string(),
        }
    }
}

/// The linear circuit, ready for DC and transient analysis.
#[derive(Debug, Clone)]
pub struct Mna {
    pub unknowns: Vec<Unknown>,
    /// Conductance part (including the incidence entries of branch rows).
    pub g: Matrix,
    /// Reactive part: capacitances and the (negated) inductance matrix.
    pub c: Matrix,
    /// Constant sources.
    pub b: Vec<f64>,
    /// Row of the input equation (`b[input_row] += u(t)`).
    pub input_row: usize,
    /// Index into `x` of each probe, `None` for ground.
    pub probes: Vec<(String, Option<usize>)>,
}

impl Mna {
    pub fn from_ir(ir: &CircuitIr) -> Result<Mna, Error> {
        ir.validate()?;
        let mut unknowns = Vec::new();
        let mut node_index: HashMap<&str, usize> = HashMap::new();
        for el in ir.elements() {
            if let Element::Device(d) = el {
                return Err(Error::new(format!(
                    "{}: nonlinear devices are not supported yet (M3)",
                    d.name
                )));
            }
            for n in el.nodes() {
                if n != GROUND && !node_index.contains_key(n) {
                    node_index.insert(n, unknowns.len());
                    unknowns.push(Unknown::Node(n.to_string()));
                }
            }
        }
        let mut branch_index: HashMap<&str, usize> = HashMap::new();
        for el in ir.elements() {
            if let Element::VoltageSource(_) | Element::Inductor(_) = el {
                branch_index.insert(el.name(), unknowns.len());
                unknowns.push(Unknown::Branch(el.name().to_string()));
            }
        }
        let input_row = unknowns.len();
        unknowns.push(Unknown::Input);

        let n = unknowns.len();
        let mut g = Matrix::zeros(n);
        let mut c = Matrix::zeros(n);
        let mut b = vec![0.0; n];
        let node = |name: &str| node_index.get(name).copied(); // None = ground

        // Two-terminal admittance-like stamp.
        fn stamp(m: &mut Matrix, a: Option<usize>, b: Option<usize>, y: f64) {
            if let Some(i) = a {
                m.add(i, i, y);
            }
            if let Some(j) = b {
                m.add(j, j, y);
            }
            if let (Some(i), Some(j)) = (a, b) {
                m.add(i, j, -y);
                m.add(j, i, -y);
            }
        }
        // Branch current k flowing from `pos` to `neg` through the element,
        // and the row `v_pos - v_neg (...)`.
        fn incidence(m: &mut Matrix, k: usize, pos: Option<usize>, neg: Option<usize>) {
            if let Some(i) = pos {
                m.add(i, k, 1.0);
                m.add(k, i, 1.0);
            }
            if let Some(j) = neg {
                m.add(j, k, -1.0);
                m.add(k, j, -1.0);
            }
        }

        let mut inductance: HashMap<&str, f64> = HashMap::new();
        for el in ir.elements() {
            match el {
                Element::Resistor(r) => stamp(&mut g, node(&r.a), node(&r.b), 1.0 / r.r_ohm),
                Element::Capacitor(cap) => stamp(&mut c, node(&cap.a), node(&cap.b), cap.c_f),
                Element::VoltageSource(v) => {
                    let k = branch_index[v.name.as_str()];
                    incidence(&mut g, k, node(&v.pos), node(&v.neg));
                    b[k] = v.dc_v;
                }
                Element::Inductor(l) => {
                    let k = branch_index[l.name.as_str()];
                    incidence(&mut g, k, node(&l.a), node(&l.b));
                    c.add(k, k, -l.l_h);
                    inductance.insert(&l.name, l.l_h);
                }
                Element::Coupling(_) | Element::Device(_) => {}
            }
        }
        for el in ir.elements() {
            if let Element::Coupling(k) = el {
                let m = k.k * (inductance[k.l_a.as_str()] * inductance[k.l_b.as_str()]).sqrt();
                let (i, j) = (branch_index[k.l_a.as_str()], branch_index[k.l_b.as_str()]);
                c.add(i, j, -m);
                c.add(j, i, -m);
            }
        }
        incidence(&mut g, input_row, node(&ir.input_node), None);

        let probes = ir
            .probes
            .iter()
            .map(|p| {
                let Probe::Voltage { node: name } = p;
                (format!("v({name})"), node(name))
            })
            .collect();
        Ok(Mna {
            unknowns,
            g,
            c,
            b,
            input_row,
            probes,
        })
    }

    pub fn len(&self) -> usize {
        self.unknowns.len()
    }

    pub fn is_empty(&self) -> bool {
        self.unknowns.is_empty()
    }

    /// The probe values for the solution `x`.
    pub fn probe_values<'a>(&'a self, x: &'a [f64]) -> impl Iterator<Item = f64> + 'a {
        self.probes.iter().map(|(_, i)| i.map_or(0.0, |i| x[i]))
    }
}
