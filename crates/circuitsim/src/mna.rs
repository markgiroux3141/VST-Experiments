//! Modified nodal analysis: the circuit as
//! `G x + C dx/dt = b + u(t) e_in + sum_k a_k sin(w_k t + phi_k) e_k`.
//!
//! Unknowns `x`: every non-ground node voltage (in order of first appearance
//! in the IR), then one branch current per DC voltage source and inductor (in
//! element order), then the current of the audio input source.
//!
//! - Resistor: conductance stamp in `G`.
//! - Capacitor: capacitance stamp in `C`.
//! - Voltage source and the input (`input_node` to ground): KCL entries plus a
//!   row `v_pos - v_neg = V`.
//! - Sine source: the same, its offset in `b` and its sine a [`Wave`] on its
//!   row. The DC operating point takes it at t = 0 ([`Mna::add_waves`]).
//! - Inductor k from a to b: KCL entries (current leaves a, enters b) plus a
//!   row `v_a - v_b - sum_j M_kj di_j/dt = 0`, with `M_kk = L_k` and, for each
//!   coupling, `M_kj = M_jk = k sqrt(L_k L_j)` (dotted ends are the `a` ends,
//!   like SPICE `K`). Stamping the inductance matrix directly means a
//!   k = 0.999 transformer never needs its ill-conditioned inverse.
//! - Winding k from a to b on core node u: KCL entries plus a row
//!   `v_a - v_b - turns area TESLA_PER_V du/dt = 0` (so `C` is not symmetric
//!   here), and `-turns` in u's KCL row: the winding feeds `turns i` into the
//!   core node, whose KCL is `sum(turns i)` = what the core device draws.
//! - Voltage-controlled current source (SPICE `G`): `gm` in `G` from the
//!   control's columns into the output's KCL rows (not symmetric), so the
//!   control draws nothing.
//! - Device (tube, diode, core): its interelectrode capacitances go into `C`, and
//!   each junction diode gets SPICE's GMIN across it in `G` (ngspice puts
//!   1e-12 S across every `D` junction). The nonlinear currents themselves are
//!   the [`DeviceInstance`]s, which the Newton solver stamps each iteration.
//!   Stateless devices of one kind on the same pins (a bank of triodes in
//!   parallel) become one instance, a [`devices::Parallel`], named after all
//!   of them ("XV101A+XV102A+..."): the same equations, one set of ports.

use std::collections::HashMap;

use crate::Error;
use crate::devices::{self, Device};
use crate::ir::{CircuitIr, DeviceModel, Element, GROUND, Probe, TESLA_PER_V};
use crate::linalg::{Matrix, SparseRows};

/// SPICE's default GMIN (S), across every junction diode.
pub const SPICE_GMIN: f64 = 1e-12;

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

/// The sinusoidal part of a sine source: `amplitude sin(omega t + phase)` on
/// the right-hand side's row `row`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Wave {
    pub row: usize,
    pub amplitude: f64,
    pub omega: f64,
    pub phase: f64,
}

impl Wave {
    pub fn at(&self, t: f64) -> f64 {
        self.amplitude * (self.omega * t + self.phase).sin()
    }
}

/// A nonlinear device placed in the circuit.
#[derive(Debug)]
pub struct DeviceInstance {
    /// Element name, e.g. `XVA`.
    pub name: String,
    pub device: Box<dyn Device>,
    /// Unknown index of each pin, in the model's pin order (`None` = ground).
    /// The last pin is the ports' reference (see [`devices`]).
    pub pins: Vec<Option<usize>>,
    /// Pin names, for messages.
    pub pin_names: &'static [&'static str],
}

/// The circuit as matrices, ready for DC and transient analysis.
#[derive(Debug)]
pub struct Mna {
    pub unknowns: Vec<Unknown>,
    /// Conductance part (including the incidence entries of branch rows).
    pub g: Matrix,
    /// Reactive part: capacitances and the (negated) inductance matrix.
    pub c: Matrix,
    /// `c`'s nonzeros, for the products taken every step.
    pub c_sparse: SparseRows,
    /// Constant sources (a sine source's offset).
    pub b: Vec<f64>,
    /// The sine sources' sinusoidal parts, added to `b` at each stage's time.
    pub waves: Vec<Wave>,
    /// Row of the input equation (`b[input_row] += u(t)`).
    pub input_row: usize,
    /// Index into `x` of each probe, `None` for ground.
    pub probes: Vec<(String, Option<usize>)>,
    pub devices: Vec<DeviceInstance>,
    /// Rows of `b` driven from outside the circuit (empty from
    /// [`Mna::from_ir`]): a partitioned run couples two circuits through them
    /// (`partition.rs`). Their values, added to `b`, are set per step
    /// ([`crate::transient::Transient::set_externals`]); DK solver only.
    pub externals: Vec<usize>,
    /// Unknowns a probes-only run computes at every step besides the probes
    /// (the coupling values a partitioned run reads).
    pub outputs: Vec<usize>,
}

/// Merge stateless instances of one kind on the same pins into one
/// [`devices::Parallel`] each, in order of first appearance.
fn merge_parallel(instances: Vec<DeviceInstance>) -> Vec<DeviceInstance> {
    let mut groups: Vec<Vec<DeviceInstance>> = Vec::new();
    for inst in instances {
        let same = |g: &Vec<DeviceInstance>| {
            let first = &g[0];
            !inst.device.has_state()
                && !first.device.has_state()
                && first.pins == inst.pins
                && first.pin_names == inst.pin_names
        };
        match groups.iter_mut().find(|g| same(g)) {
            Some(g) => g.push(inst),
            None => groups.push(vec![inst]),
        }
    }
    groups
        .into_iter()
        .map(|mut g| {
            if g.len() == 1 {
                return g.pop().expect("one");
            }
            let name = g
                .iter()
                .map(|d| d.name.as_str())
                .collect::<Vec<_>>()
                .join("+");
            let (pins, pin_names) = (g[0].pins.clone(), g[0].pin_names);
            DeviceInstance {
                name,
                device: Box::new(devices::Parallel::new(
                    g.into_iter().map(|d| d.device).collect(),
                )),
                pins,
                pin_names,
            }
        })
        .collect()
}

impl Mna {
    /// `gmin` (S) goes across every junction diode; [`SPICE_GMIN`] matches ngspice.
    pub fn from_ir(ir: &CircuitIr, gmin: f64) -> Result<Mna, Error> {
        ir.validate()?;
        if !(gmin.is_finite() && gmin >= 0.0) {
            return Err(Error::new(format!("gmin = {gmin} must be >= 0")));
        }
        let mut unknowns = Vec::new();
        let mut node_index: HashMap<&str, usize> = HashMap::new();
        for el in ir.elements() {
            for n in el.nodes() {
                if n != GROUND && !node_index.contains_key(n) {
                    node_index.insert(n, unknowns.len());
                    unknowns.push(Unknown::Node(n.to_string()));
                }
            }
        }
        let mut branch_index: HashMap<&str, usize> = HashMap::new();
        for el in ir.elements() {
            if let Element::VoltageSource(_)
            | Element::SineSource(_)
            | Element::Inductor(_)
            | Element::Winding(_) = el
            {
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

        let mut waves = Vec::new();
        let mut inductance: HashMap<&str, f64> = HashMap::new();
        let mut instances = Vec::new();
        for el in ir.elements() {
            match el {
                Element::Resistor(r) => stamp(&mut g, node(&r.a), node(&r.b), 1.0 / r.r_ohm),
                Element::Capacitor(cap) => stamp(&mut c, node(&cap.a), node(&cap.b), cap.c_f),
                Element::VoltageSource(v) => {
                    let k = branch_index[v.name.as_str()];
                    incidence(&mut g, k, node(&v.pos), node(&v.neg));
                    b[k] = v.dc_v;
                }
                Element::SineSource(v) => {
                    let k = branch_index[v.name.as_str()];
                    incidence(&mut g, k, node(&v.pos), node(&v.neg));
                    b[k] = v.offset_v;
                    let (omega, phase) = v.omega_phase();
                    waves.push(Wave {
                        row: k,
                        amplitude: v.amplitude_v,
                        omega,
                        phase,
                    });
                }
                Element::Inductor(l) => {
                    let k = branch_index[l.name.as_str()];
                    incidence(&mut g, k, node(&l.a), node(&l.b));
                    c.add(k, k, -l.l_h);
                    inductance.insert(&l.name, l.l_h);
                }
                Element::Winding(w) => {
                    let k = branch_index[w.name.as_str()];
                    incidence(&mut g, k, node(&w.a), node(&w.b));
                    let u = node(&w.core).expect("validated: the core node isn't ground");
                    c.add(k, u, -w.turns * w.area_m2 * TESLA_PER_V);
                    g.add(u, k, -w.turns);
                }
                Element::Device(d) => {
                    let model = ir.model(&d.model).expect("validated");
                    let pins: Vec<Option<usize>> = d.nodes.iter().map(|n| node(n)).collect();
                    // Interelectrode capacitances, as the SPICE subcircuits have them.
                    let caps: Vec<(usize, usize, f64)> = match model {
                        // pins (p, g, k)
                        DeviceModel::Triode(t) => {
                            vec![(1, 2, t.c_gk), (1, 0, t.c_gp), (0, 2, t.c_pk)]
                        }
                        // pins (p, g2, g1, k)
                        DeviceModel::Pentode(p) => {
                            vec![(2, 3, p.c_g1k), (2, 0, p.c_g1p), (0, 3, p.c_pk)]
                        }
                        DeviceModel::JunctionDiode(_) => {
                            stamp(&mut g, pins[0], pins[1], gmin);
                            vec![]
                        }
                        DeviceModel::VacuumDiode(_) | DeviceModel::MagneticCore(_) => vec![],
                    };
                    for (a, b, cf) in caps {
                        if cf > 0.0 {
                            stamp(&mut c, pins[a], pins[b], cf);
                        }
                    }
                    instances.push(DeviceInstance {
                        name: d.name.clone(),
                        device: devices::from_model(model),
                        pins,
                        pin_names: model.pins(),
                    });
                }
                Element::Vccs(s) => {
                    // gm (v_cp - v_cn) leaves `pos` and enters `neg`.
                    for (row, sr) in [(node(&s.pos), 1.0), (node(&s.neg), -1.0)] {
                        for (col, sc) in [(node(&s.ctrl_pos), 1.0), (node(&s.ctrl_neg), -1.0)] {
                            if let (Some(i), Some(j)) = (row, col) {
                                g.add(i, j, sr * sc * s.gm_s);
                            }
                        }
                    }
                }
                Element::Coupling(_) => {}
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
        let instances = merge_parallel(instances);

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
            c_sparse: SparseRows::new(&c),
            c,
            b,
            waves,
            input_row,
            probes,
            devices: instances,
            externals: Vec::new(),
            outputs: Vec::new(),
        })
    }

    /// Rows of the sources whose values change during a run: every sine
    /// source's (see [`Mna::waves`]), then the [`Mna::externals`].
    pub fn source_rows(&self) -> Vec<usize> {
        self.waves
            .iter()
            .map(|w| w.row)
            .chain(self.externals.iter().copied())
            .collect()
    }

    /// The unknown index of node `name` (`None` for ground or no such node).
    pub fn node(&self, name: &str) -> Option<usize> {
        self.unknowns
            .iter()
            .position(|u| matches!(u, Unknown::Node(n) if n == name))
    }

    /// The unknown index of the branch current of element `name`.
    pub fn branch(&self, name: &str) -> Option<usize> {
        self.unknowns
            .iter()
            .position(|u| matches!(u, Unknown::Branch(n) if n == name))
    }

    /// Add every sine source's sinusoidal part at time `t` to `rhs`.
    pub fn add_waves(&self, t: f64, rhs: &mut [f64]) {
        for w in &self.waves {
            rhs[w.row] += w.at(t);
        }
    }

    pub fn len(&self) -> usize {
        self.unknowns.len()
    }

    pub fn is_empty(&self) -> bool {
        self.unknowns.is_empty()
    }

    /// Replace every device that has a tabulated form ([`Device::tabulate`]:
    /// variable-mu triodes, banks of triodes) by it. Returns how many.
    pub fn tabulate_tubes(&mut self) -> usize {
        let mut n = 0;
        for d in &mut self.devices {
            if let Some(t) = d.device.tabulate() {
                d.device = t;
                n += 1;
            }
        }
        n
    }

    /// The probe values for the solution `x`.
    pub fn probe_values<'a>(&'a self, x: &'a [f64]) -> impl Iterator<Item = f64> + 'a {
        self.probes.iter().map(|(_, i)| i.map_or(0.0, |i| x[i]))
    }
}
