//! Modified nodal analysis: the circuit as
//! `G x + C dx/dt = b + u(t) e_in + sum_k a_k sin(w_k t + phi_k) e_k`.
//!
//! Unknowns `x`: every non-ground node voltage (in order of first appearance
//! in the IR), then one branch current per DC voltage source and inductor (in
//! element order), then the current of the audio input source.
//!
//! - Resistor: conductance stamp in `G`.
//! - Capacitor: capacitance stamp in `C`. One with a start voltage is held at it
//!   for the DC operating point ([`Mna::dc_starts`]): a stiff conductance across it
//!   with the matching current source (a Norton source), in that solve only.
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
use crate::cathode::{Emission, HeatRun, Heated};
use crate::devices::{self, Device};
use crate::ir::{CircuitIr, DeviceModel, Element, GROUND, Probe, TESLA_PER_V};
use crate::linalg::{Matrix, SparseRows};
use crate::noise::{NoiseRun, NoiseSpec};

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
    /// Current of a control input's source (its name).
    Control(String),
}

impl Unknown {
    /// Human-readable, for error messages.
    pub fn describe(&self) -> String {
        match self {
            Unknown::Node(n) => format!("node {n}"),
            Unknown::Branch(e) => format!("branch current of {e}"),
            Unknown::Input => "input source current".to_string(),
            Unknown::Control(c) => format!("control {c} source current"),
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
    /// The IR's control inputs come first ([`Mna::n_controls`] of them, set by
    /// [`crate::transient::Transient::set_controls`]); a partition's couplings
    /// follow.
    pub externals: Vec<usize>,
    /// How many of [`Mna::externals`] are control inputs (IR order).
    pub n_controls: usize,
    /// Unknowns a probes-only run computes at every step besides the probes
    /// (the coupling values a partitioned run reads).
    pub outputs: Vec<usize>,
    /// Capacitors with a start voltage (`Capacitor::v0_v`): their nodes (None =
    /// ground) and the voltage, held during the DC operating point only.
    pub dc_starts: Vec<(Option<usize>, Option<usize>, f64)>,
    /// Noise sources (device builder B5; `None`: the IR has none), current columns
    /// after the time-varying sources' (see [`Mna::source_rows`]). DK solver only.
    pub noise: Option<NoiseRun>,
    /// Heated cathodes (device builder B6; `None`: the IR has none): the circuit's cathode
    /// temperature and the instances it heats (their devices are [`Heated`]). DK only.
    pub heat: Option<HeatRun>,
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

/// The model name of device element `device`.
fn ir_model(ir: &CircuitIr, device: &str) -> String {
    ir.elements()
        .find_map(|e| match e {
            Element::Device(d) if d.name == device => Some(d.model.clone()),
            _ => None,
        })
        .expect("validated: a device")
}

/// The IR's noise sources as a [`NoiseRun`] on these unknowns and device instances
/// (a tube merged into a bank takes its share of the bank's currents).
fn noise_run(
    ir: &CircuitIr,
    instances: &[DeviceInstance],
    node: &dyn Fn(&str) -> Option<usize>,
    wave_names: &[&str],
) -> Option<NoiseRun> {
    let spec = ir.noise.as_ref()?;
    let (mut specs, mut columns) = (Vec::new(), Vec::new());
    for el in ir.elements() {
        match el {
            Element::NoiseCurrent(n) => {
                specs.push(NoiseSpec::White {
                    name: n.name.clone(),
                    psd_a2_hz: n.psd_a2_hz,
                });
                columns.push((node(&n.a), node(&n.b)));
            }
            Element::TubeNoise(t) => {
                let (d, inst) = instances
                    .iter()
                    .enumerate()
                    .find(|(_, i)| i.name.split('+').any(|n| n == t.device))
                    .expect("validated: a tube instance");
                let bank = inst.name.split('+').count();
                // Triode pins (p, g, k), pentode (p, g2, g1, k): the control grid is the
                // last pin before the cathode, and its port has the same index.
                let k = inst.pins.len() - 1;
                let grid = k - 1;
                specs.push(NoiseSpec::Tube {
                    name: t.name.clone(),
                    device: d,
                    share: 1.0 / bank as f64,
                    grid_port: grid,
                    shot_k: t.shot_k,
                    partition: t.partition,
                    flicker_v2: t.flicker_v2,
                });
                columns.push((inst.pins[0], inst.pins[k]));
                columns.push((inst.pins[grid], inst.pins[k]));
            }
            _ => {}
        }
    }
    // The mains wander on the sine sources this circuit (or partition) has.
    let waves: Vec<usize> = spec
        .mains_sources
        .iter()
        .filter_map(|m| wave_names.iter().position(|w| w == m))
        .collect();
    // The wander's stream whenever it is on (heated cathodes follow it too), multiplying
    // the mains sources this part has.
    let mains = (spec.mains_rms > 0.0).then_some((spec.mains_rms, waves));
    Some(NoiseRun::new(
        spec.seed,
        spec.rate_hz,
        specs,
        columns,
        mains,
    ))
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
        // Control inputs after it: an IR without any has the same unknowns.
        let control_rows: Vec<usize> = ir
            .controls
            .iter()
            .map(|c| {
                unknowns.push(Unknown::Control(c.name.clone()));
                unknowns.len() - 1
            })
            .collect();

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
        let mut wave_names: Vec<&str> = Vec::new();
        let mut dc_starts = Vec::new();
        let mut inductance: HashMap<&str, f64> = HashMap::new();
        let mut instances = Vec::new();
        for el in ir.elements() {
            match el {
                Element::Resistor(r) => stamp(&mut g, node(&r.a), node(&r.b), 1.0 / r.r_ohm),
                Element::Capacitor(cap) => {
                    stamp(&mut c, node(&cap.a), node(&cap.b), cap.c_f);
                    if let Some(v0) = cap.v0_v {
                        dc_starts.push((node(&cap.a), node(&cap.b), v0));
                    }
                }
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
                    wave_names.push(&v.name);
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
                Element::Coupling(_)
                | Element::NoiseCurrent(_)
                | Element::TubeNoise(_)
                | Element::HeatedCathode(_) => {}
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
        for (c, &row) in ir.controls.iter().zip(&control_rows) {
            incidence(&mut g, row, node(&c.node), None);
        }
        // Heated cathodes: their tubes' devices wrapped before banks merge.
        let instances = match &ir.heaters {
            None => instances,
            Some(h) => {
                let heated: HashMap<&str, (usize, Emission)> = ir
                    .elements()
                    .filter_map(|e| match e {
                        Element::HeatedCathode(c) => {
                            let port = match ir.model(&ir_model(ir, &c.device)) {
                                Some(DeviceModel::Triode(_)) => 1,
                                Some(DeviceModel::Pentode(_)) => 2,
                                _ => 0,
                            };
                            let em = Emission {
                                is0_a: c.is0_a,
                                phi_ev: h.phi_ev,
                                n: h.n,
                                t0_k: h.t0_k,
                            };
                            Some((c.device.as_str(), (port, em)))
                        }
                        _ => None,
                    })
                    .collect();
                instances
                    .into_iter()
                    .map(|d| match heated.get(d.name.as_str()) {
                        Some(&(port, em)) => DeviceInstance {
                            device: Box::new(Heated::new(d.device, port, em)),
                            ..d
                        },
                        None => d,
                    })
                    .collect()
            }
        };
        let instances = merge_parallel(instances);
        let heat = ir.heaters.as_ref().map(|h| {
            let mut tubes: Vec<usize> = Vec::new();
            for el in ir.elements() {
                if let Element::HeatedCathode(c) = el
                    && let Some(i) = instances
                        .iter()
                        .position(|d| d.name.split('+').any(|n| n == c.device))
                    && !tubes.contains(&i)
                {
                    tubes.push(i);
                }
            }
            HeatRun::new(h.clone(), tubes)
        });
        let noise = noise_run(ir, &instances, &node, &wave_names);

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
            n_controls: control_rows.len(),
            externals: control_rows,
            outputs: Vec::new(),
            dc_starts,
            noise,
            heat,
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
