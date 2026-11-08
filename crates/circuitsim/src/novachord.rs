//! The Hammond Novachord's keys as a medium beside the circuit (docs/NOVACHORD_PLAN.md, NV4:
//! the live tier). The reference is the literal instrument, `config/circuits/novachord.yaml`;
//! the live circuit (`novachord_live.yaml`) keeps its oscillators, reeds, control box,
//! preamplifier and amplifier, and hands this medium the rest:
//!
//! - **The oscillators as compiled phases.** Each of the twelve is a phase whose
//!   frequency follows its vibrato triode's grid (`grids`, sensed a sample late; the reeds
//!   and the vibrato's bias network stay in the circuit, the grid's network as a load on
//!   them): the reference oscillator's frequency against that grid, measured per vibrato
//!   switch state by holding the reed line at DC (`varimu/novachord/compile.py`; the grid
//!   moves at the reeds' ~7 Hz through ~1 ms of RC, the tank follows within cycles:
//!   quasi-static). Its coil's tap (the top octave's grid drive) is a table over a cycle.
//! - **The dividers as locked waveforms.** Each divider's cathode voltage (what its control
//!   tube's grid network is fed) is a table over 32 cycles of its oscillator, recorded from a
//!   reference run with every key up, read at the oscillator's phase: the vibrato's pitch
//!   reaches every octave as it does through the literal dividers.
//! - **The 72 keys, literally.** Per key the control tube's grid network (RN1, CN5, RN2,
//!   CN29, CN30 at MELLOW; the top octave's RN19 from the tap and RN2 / RN8), the 6W7-G (the
//!   circuit's own Koren pentode with its grid current and capacitances), its cathode
//!   (CN15, RN7) and the playing key's springs and charge stores (CN7, RN10, RN12, CN8,
//!   RN11 between the attack switch's buses A and C, the cut-off taps and the keying
//!   supply's + rail), the same network as the reference's, solved per sample: trapezoidal
//!   (backward Euler for the sample after a spring moves), Newton on the tube's grid and
//!   cathode. The key's springs move with note events (spring 3 with the key; spring 1 with
//!   the key or the sustaining pedal), as `scripts/novachord_render.py` works the
//!   reference's rheostat contacts.
//! - **Sleeping keys.** A key up whose tube is cut off and whose envelope has settled
//!   sleeps and costs nothing: its cathode, keying lead and charge store at their rest (the
//!   tap, the buses' divide), its grid network in the periodic steady state its divider's
//!   waveform drives it into (computed once per key and BRIGHT-MELLOW setting over the
//!   table's 32 cycles, `Steady`). A key that wakes starts from that state at its
//!   oscillator's phase, so the cost goes with the keys sounding.
//! - **Coupling.** The medium senses the vibrato grids, the buses, the keying supply's
//!   positive rail, the cut-off taps and the shared plate leads (their sag) a sample late, and
//!   drives each plate lead's current (the sum of its four tubes' plate currents) at the
//!   next sample: an output per lead, volts = amperes x `v_per_a`, which the circuit's `G`
//!   parts turn into the current drawn from the lead.
//!
//! What it leaves out against the reference: the control tubes' grid current loading the
//! dividers and the oscillators' taps (the tables were recorded with every key up), the
//! oscillators' amplitude and waveform moving with the vibrato (the tap's table is the
//! vibrato off's), the
//! keys' load on the buses, the + rail and the cut-off taps (stiff sources), the dividers'
//! response to anything but their oscillator's phase (they run on ideal rails in the
//! reference too).

use std::collections::{HashMap, VecDeque};
use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock};

use serde::Deserialize;

use crate::devices::triode::grid_current;
use crate::devices::{Device, Pentode};
use crate::ir::NovaKeys;
use crate::media::NoteEvent;

/// Key 1 is F1 (MIDI 29), key 72 E7 (MIDI 100); notes outside fold into range by octaves.
pub const LOW_MIDI: u8 = 29;
pub const HIGH_MIDI: u8 = 100;
/// Senses before the plate leads: 12 vibrato grids, bus A, bus C, the + rail, 3 cut-off
/// taps.
pub const FIXED_SENSES: usize = 18;

/// One key's values, as the reference circuit has them (`varimu/novachord/compile.py`).
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KeyData {
    /// 1..=72.
    pub key: usize,
    /// Its plate lead (four keys a lead), 0..=17.
    pub group: usize,
    /// Its note name (0 = F ... 11 = E): the oscillator.
    pub note: usize,
    /// Its octave: 1..=5 a divider's channel, 6 the oscillator's own (the top octave).
    pub ch: usize,
    /// The grid network: RN1 and CN5 from the divider (lower octaves), RN19 from the
    /// oscillator's tap (the top octave; 0 elsewhere); RN2, CN29 (0 on the top octave), CN30
    /// at MELLOW (0 where there is none), RN8 at MELLOW (the top octave's; 0 elsewhere).
    pub rn1_ohm: f64,
    pub cn5_f: f64,
    pub rn19_ohm: f64,
    pub rn2_ohm: f64,
    pub cn29_f: f64,
    pub cn30_f: f64,
    pub rn8_ohm: f64,
    /// The cathode: CN15 to ground, RN7 to the keying lead.
    pub cn15_f: f64,
    pub rn7_ohm: f64,
    /// The playing key: CN7 (lead to the + rail), RN10 (spring 1 to the cut-off tap), RN12
    /// (spring 3 to the charge store), CN8 (the store to the + rail), RN11 (the store to
    /// bus C).
    pub cn7_f: f64,
    pub rn10_ohm: f64,
    pub rn12_ohm: f64,
    pub cn8_f: f64,
    pub rn11_ohm: f64,
    /// Its cut-off tap: 0 notes 45-72, 1 notes 13-44, 2 notes 5-12, 3 notes 1-4 (the + rail).
    pub tap: usize,
}

/// One note name's dividers: channel ch's cathode voltage over `cycles` of the oscillator
/// (`points_per_cycle` a cycle, cycle 0 starting at an upward zero crossing of the tap).
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NoteData {
    pub name: String,
    /// The oscillator's frequency (the trimmed reference's, measured).
    pub f0_hz: f64,
    /// Channels 1..=5 (index ch - 1).
    pub tables: Vec<Vec<f64>>,
    /// Its coil's tap over one cycle (`points_per_cycle`, from an upward zero crossing).
    pub tap: Vec<f64>,
    /// Its frequency against its vibrato triode's grid, per vibrato state (NORMAL, SMALL):
    /// (0, 0), (0, 1), (1, 0), (1, 1).
    pub vibrato: Vec<Curve>,
}

/// A frequency against a voltage, ascending in volts; linear between, held at the ends.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Curve {
    pub v: Vec<f64>,
    pub f_hz: Vec<f64>,
}

impl Curve {
    pub fn at(&self, v: f64) -> f64 {
        let (x, y) = (&self.v, &self.f_hz);
        if v <= x[0] {
            return y[0];
        }
        let n = x.len();
        if v >= x[n - 1] {
            return y[n - 1];
        }
        let j = x.partition_point(|&a| a <= v).clamp(1, n - 1);
        let w = (v - x[j - 1]) / (x[j] - x[j - 1]);
        y[j - 1] + w * (y[j] - y[j - 1])
    }
}

/// The compiled keys (a component version of kind `nova_keys`).
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct KeysModel {
    pub format: u32,
    pub cycles: usize,
    pub points_per_cycle: usize,
    /// The control tubes' screen supply (+34 V, an ideal rail in the reference).
    pub screen_v: f64,
    /// The control tube (the reference's 6W7-G).
    pub tube: crate::ir::Pentode,
    pub notes: Vec<NoteData>,
    pub keys: Vec<KeyData>,
    /// What the compile recorded (provenance: the reference, its quality, the fit).
    #[serde(default)]
    pub provenance: serde_json::Value,
}

impl KeysModel {
    pub fn check(&self) -> Result<(), String> {
        if self.format != 1 {
            return Err(format!("format {} (this build reads 1)", self.format));
        }
        if self.notes.len() != 12 || self.keys.len() != 72 {
            return Err("12 notes and 72 keys".into());
        }
        let n = self.cycles * self.points_per_cycle;
        if n == 0 {
            return Err("empty tables".into());
        }
        for nd in &self.notes {
            if nd.tables.len() != 5 || nd.tables.iter().any(|t| t.len() != n) {
                return Err(format!("note {}: five tables of {n} points", nd.name));
            }
            if nd.f0_hz.is_nan() || nd.f0_hz <= 0.0 {
                return Err(format!("note {}: f0_hz", nd.name));
            }
            if nd.tap.len() != self.points_per_cycle {
                return Err(format!("note {}: a tap table of a cycle", nd.name));
            }
            let curve_ok = |c: &Curve| {
                c.v.len() >= 2
                    && c.v.len() == c.f_hz.len()
                    && c.v.windows(2).all(|w| w[1] > w[0])
                    && c.f_hz.iter().all(|&f| f > 0.0)
            };
            if nd.vibrato.len() != 4 || !nd.vibrato.iter().all(curve_ok) {
                return Err(format!("note {}: four vibrato curves", nd.name));
            }
        }
        for (i, k) in self.keys.iter().enumerate() {
            let top = k.ch == 6;
            let ok = k.key == i + 1
                && k.group == i / 4
                && k.note == i % 12
                && k.ch == i / 12 + 1
                && k.tap <= 3
                && k.rn2_ohm > 0.0
                && k.cn15_f > 0.0
                && k.rn7_ohm > 0.0
                && k.cn7_f > 0.0
                && k.rn10_ohm > 0.0
                && k.rn12_ohm > 0.0
                && k.cn8_f > 0.0
                && k.rn11_ohm > 0.0
                && k.cn30_f >= 0.0
                && k.rn8_ohm >= 0.0
                && if top {
                    k.rn19_ohm > 0.0
                } else {
                    k.rn1_ohm > 0.0 && k.cn5_f > 0.0 && k.cn29_f > 0.0
                };
            if !ok {
                return Err(format!("key {}: its values", i + 1));
            }
        }
        Ok(())
    }
}

/// The repository's root, against which the IR's relative data paths resolve
/// (`crate::clavinet::data_root`).
fn data_path(rel: &str) -> PathBuf {
    let p = PathBuf::from(rel);
    if p.is_absolute() {
        p
    } else {
        crate::clavinet::data_root().join(p)
    }
}

/// The model the element names, loaded once per process (by its path and sha256; the
/// builders check the file against the sha256 the component version gives).
pub fn load(el: &NovaKeys) -> Result<Arc<KeysModel>, String> {
    type Loaded = Mutex<HashMap<(String, String), Arc<KeysModel>>>;
    static LOADED: OnceLock<Loaded> = OnceLock::new();
    let cache = LOADED.get_or_init(Default::default);
    let id = (el.data.clone(), el.sha256.clone());
    if let Some(m) = cache.lock().expect("keys").get(&id) {
        return Ok(m.clone());
    }
    let path = data_path(&el.data);
    let raw = std::fs::read_to_string(&path)
        .map_err(|e| format!("{}: {}: {e}", el.name, path.display()))?;
    let m: KeysModel =
        serde_json::from_str(&raw).map_err(|e| format!("{}: {}: {e}", el.name, path.display()))?;
    m.check().map_err(|e| format!("{}: {e}", el.name))?;
    let m = Arc::new(m);
    cache.lock().expect("keys").insert(id, m.clone());
    Ok(m)
}

/// A terminal of a key's network: one of its nodes, ground, or a value from outside.
#[derive(Debug, Clone, Copy, PartialEq)]
enum T {
    N(usize),
    Gnd,
    /// The grid network's drive: the divider's cathode (a table) or the oscillator's tap.
    Src,
    Abus,
    Cbus,
    Keyp,
    Tap,
    Plate,
}

/// A terminal's place in a step's values ([`Key::values`]): the key's nodes 0-4, then
/// the outside values, ground last.
const SRC: usize = 5;
const ABUS: usize = 6;
const CBUS: usize = 7;
const KEYP: usize = 8;
const TAP: usize = 9;
const PLATE: usize = 10;
const GND: usize = 11;
const VALUES: usize = 12;

impl T {
    fn idx(self) -> usize {
        match self {
            T::N(j) => j,
            T::Gnd => GND,
            T::Src => SRC,
            T::Abus => ABUS,
            T::Cbus => CBUS,
            T::Keyp => KEYP,
            T::Tap => TAP,
            T::Plate => PLATE,
        }
    }
}

/// The outside values a step sees, in [`T`]'s order from `Src`.
#[derive(Debug, Clone, Copy, Default)]
struct Ext {
    src: f64,
    abus: f64,
    cbus: f64,
    keyp: f64,
    tap: f64,
    plate: f64,
    screen: f64,
}

#[derive(Debug, Clone)]
struct Cap {
    a: T,
    b: T,
    c: f64,
    /// The voltage across it (a - b) and its current (a to b) at the last sample.
    u: f64,
    i: f64,
}

/// A capacitor's place in the solved system: rows of its ends (None: not solved), its
/// companion conductance.
#[derive(Debug, Clone, Copy)]
struct CapRow {
    cap: usize,
    ra: Option<usize>,
    rb: Option<usize>,
    /// Its ends' places in a step's values.
    ia: usize,
    ib: usize,
    gc: f64,
}

/// The linear system of a key's state of springs: its solved nodes' inverse admittance
/// and how outside values enter its right-hand side.
#[derive(Debug, Clone, Default)]
struct System {
    /// Solved nodes (key node indices), in row order.
    nodes: Vec<usize>,
    /// Row of each key node (None: held).
    row: [Option<usize>; 5],
    yinv: Vec<f64>,
    /// (row, conductance, the other end's place in a step's values): a conductance to a
    /// value not solved.
    ext: Vec<(usize, f64, usize)>,
    caps: Vec<CapRow>,
    be: bool,
}

/// The state of a key's springs and its system's method.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Config {
    down: bool,
    s1: bool,
    be: bool,
    mellow: bool,
}

/// One key: its network, its state, its system.
#[derive(Debug, Clone)]
struct Key {
    d: KeyData,
    top: bool,
    /// Node indices: grid, cathode, keying lead, charge store (c5 is node 0 below the top).
    g: usize,
    k: usize,
    kl: usize,
    nx: usize,
    n: usize,
    v: [f64; 5],
    caps: Vec<Cap>,
    /// CN30's index in `caps`, if the key has one.
    cn30: Option<usize>,
    cfg: Option<Config>,
    sys: System,
    down: bool,
    s1: bool,
    awake: bool,
    /// The next sample after a spring moved: backward Euler.
    be_next: bool,
    /// Plate current at the last sample (A).
    ip: f64,
    /// The keying lead held while asleep with spring 1 open (the pedal down).
    kl_hold: f64,
    /// Tube evaluations so far (statistics).
    evals: u64,
    /// The grid and cathode at the sample before the last (Newton's predictor).
    prev: (f64, f64),
    /// Woken by its springs, not stepped yet: its state is set from the steady one first.
    waking: bool,
}

/// Newton's tolerance on the grid and cathode (V) and its step limit per iteration.
const NEWTON_TOL_V: f64 = 1e-5;
/// Newton's last step below this is taken without another evaluation (the reference's
/// draft solves to 1 mV).
const NEWTON_LINEAR_V: f64 = 1e-3;
const NEWTON_MAX_STEP_V: f64 = 10.0;
const NEWTON_MAX_ITERATIONS: usize = 40;
/// A key sleeps below this cathode current (A) with its envelope settled within these:
/// its keying lead within 50 mV of its tap (RN10 x CN7 = 71 ms takes it there ~0.5 s after
/// a release; the tube is cut off volts before), its cathode within as much of the lead,
/// its charge store of its rest. Asleep they are held there.
const SLEEP_IK_A: f64 = 1e-10;
const SLEEP_V: f64 = 0.05;
const SLEEP_NX_V: f64 = 0.05;
/// A tube whose grid sits this far below Koren's cutoff (Vg1 = -Vg2 / mu) is left out of
/// the sample (its plate current is under 1e-12 A there): no Newton.
const CUTOFF_MARGIN_V: f64 = 3.0;

impl Key {
    fn new(d: &KeyData, tube: &crate::ir::Pentode) -> Key {
        let top = d.ch == 6;
        let (g, k, kl, nx, n) = if top {
            (0, 1, 2, 3, 4)
        } else {
            (1, 2, 3, 4, 5)
        };
        let mut caps = Vec::new();
        let cap = |a, b, c| Cap {
            a,
            b,
            c,
            u: 0.0,
            i: 0.0,
        };
        if !top {
            caps.push(cap(T::N(0), T::N(g), d.cn5_f));
            caps.push(cap(T::N(g), T::Gnd, d.cn29_f));
        }
        let cn30 = (d.cn30_f > 0.0).then(|| {
            caps.push(cap(T::N(g), T::Gnd, 0.0));
            caps.len() - 1
        });
        caps.push(cap(T::N(g), T::N(k), tube.c_g1k));
        caps.push(cap(T::N(g), T::Plate, tube.c_g1p));
        caps.push(cap(T::Plate, T::N(k), tube.c_pk));
        caps.push(cap(T::N(k), T::Gnd, d.cn15_f));
        caps.push(cap(T::N(kl), T::Keyp, d.cn7_f));
        caps.push(cap(T::N(nx), T::Keyp, d.cn8_f));
        Key {
            d: d.clone(),
            top,
            g,
            k,
            kl,
            nx,
            n,
            v: [0.0; 5],
            caps,
            cn30,
            cfg: None,
            sys: System::default(),
            down: false,
            s1: true,
            awake: false,
            be_next: false,
            ip: 0.0,
            kl_hold: 0.0,
            evals: 0,
            prev: (0.0, 0.0),
            waking: false,
        }
    }

    /// The key's resistors in its state (the caps are `caps`).
    fn resistors(&self, mellow: bool) -> Vec<(T, T, f64)> {
        let d = &self.d;
        let (g, k, kl, nx) = (T::N(self.g), T::N(self.k), T::N(self.kl), T::N(self.nx));
        let mut r = Vec::with_capacity(8);
        if self.top {
            r.push((T::Src, g, 1.0 / d.rn19_ohm));
            if mellow && d.rn8_ohm > 0.0 {
                r.push((g, T::Gnd, 1.0 / d.rn8_ohm));
            }
        } else {
            r.push((T::Src, T::N(0), 1.0 / d.rn1_ohm));
        }
        r.push((g, T::Gnd, 1.0 / d.rn2_ohm));
        r.push((k, kl, 1.0 / d.rn7_ohm));
        if self.s1 {
            r.push((kl, T::Tap, 1.0 / d.rn10_ohm));
        }
        // Spring 3: on bus A with the key up, on the keying lead with it down.
        r.push((if self.down { kl } else { T::Abus }, nx, 1.0 / d.rn12_ohm));
        r.push((nx, T::Cbus, 1.0 / d.rn11_ohm));
        r
    }

    /// Build the system for `cfg` (h the step).
    fn build(&mut self, cfg: Config, h: f64) {
        if let Some(i) = self.cn30 {
            let c = if cfg.mellow { self.d.cn30_f } else { 0.0 };
            if self.caps[i].c == 0.0 && c > 0.0 {
                // switched in: it takes the grid's voltage, no current
                self.caps[i].u = self.v[self.g];
                self.caps[i].i = 0.0;
            }
            self.caps[i].c = c;
        }
        let nodes: Vec<usize> = (0..self.n).collect();
        let mut row = [None; 5];
        for (r, &j) in nodes.iter().enumerate() {
            row[j] = Some(r);
        }
        let ns = nodes.len();
        let mut y = vec![0.0; ns * ns];
        let mut ext = Vec::new();
        let rowof = |t: T| match t {
            T::N(j) => row[j],
            _ => None,
        };
        let stamp = |a: T, b: T, gv: f64, ext: &mut Vec<(usize, f64, usize)>, y: &mut Vec<f64>| {
            let (ra, rb) = (rowof(a), rowof(b));
            if let Some(i) = ra {
                y[i * ns + i] += gv;
                match rb {
                    Some(j) => y[i * ns + j] -= gv,
                    None => ext.push((i, gv, b.idx())),
                }
            }
            if let Some(j) = rb {
                y[j * ns + j] += gv;
                match ra {
                    Some(i) => y[j * ns + i] -= gv,
                    None => ext.push((j, gv, a.idx())),
                }
            }
        };
        for (a, b, gv) in self.resistors(cfg.mellow) {
            stamp(a, b, gv, &mut ext, &mut y);
        }
        let mut caps = Vec::new();
        for (ci, c) in self.caps.iter().enumerate() {
            let (ra, rb) = (rowof(c.a), rowof(c.b));
            let gc = if cfg.be { c.c / h } else { 2.0 * c.c / h };
            stamp(c.a, c.b, gc, &mut ext, &mut y);
            caps.push(CapRow {
                cap: ci,
                ra,
                rb,
                ia: c.a.idx(),
                ib: c.b.idx(),
                gc,
            });
        }
        let yinv = invert(&y, ns).expect("a key's network has a DC path at every node");
        self.sys = System {
            nodes,
            row,
            yinv,
            ext,
            caps,
            be: cfg.be,
        };
        self.cfg = Some(cfg);
    }

    fn val(&self, t: T, e: &Ext) -> f64 {
        match t {
            T::N(j) => self.v[j],
            T::Gnd => 0.0,
            T::Src => e.src,
            T::Abus => e.abus,
            T::Cbus => e.cbus,
            T::Keyp => e.keyp,
            T::Tap => e.tap,
            T::Plate => e.plate,
        }
    }

    /// A step's values: its nodes, then the outside values, ground.
    fn values(&self, e: &Ext) -> [f64; VALUES] {
        let mut w = [0.0; VALUES];
        w[..5].copy_from_slice(&self.v);
        w[SRC] = e.src;
        w[ABUS] = e.abus;
        w[CBUS] = e.cbus;
        w[KEYP] = e.keyp;
        w[TAP] = e.tap;
        w[PLATE] = e.plate;
        w
    }

    /// The charge store's rest with the key up: bus A through RN12, bus C through RN11.
    fn nx_rest(&self, e: &Ext) -> f64 {
        let (ga, gc) = (1.0 / self.d.rn12_ohm, 1.0 / self.d.rn11_ohm);
        (ga * e.abus + gc * e.cbus) / (ga + gc)
    }

    /// Start at rest, asleep (its state is set when it wakes).
    fn start(&mut self, e: &Ext) {
        self.kl_hold = e.tap;
        self.awake = false;
        self.waking = false;
        self.cfg = None;
    }

    /// Wake at the sample whose outside values are `e`: the cathode and keying lead where
    /// they rested (the tap, or where a pedal left the lead), the store at the buses'
    /// divide, the grid network in its steady state (`c5`, `g`; the top octave's grid the
    /// tap's divide); every cap's voltage from its ends, no current (the sample after a
    /// spring moves is backward Euler's).
    fn wake(&mut self, e: &Ext, c5: f64, g: f64, mellow: bool) {
        let held = if self.s1 { e.tap } else { self.kl_hold };
        self.v = [0.0; 5];
        if self.top {
            let mut gg = 1.0 / self.d.rn2_ohm;
            if mellow && self.d.rn8_ohm > 0.0 {
                gg += 1.0 / self.d.rn8_ohm;
            }
            let g19 = 1.0 / self.d.rn19_ohm;
            self.v[self.g] = e.src * g19 / (g19 + gg);
        } else {
            self.v[0] = c5;
            self.v[self.g] = g;
        }
        self.v[self.k] = held;
        self.v[self.kl] = held;
        self.v[self.nx] = self.nx_rest(e);
        if let Some(i) = self.cn30 {
            self.caps[i].c = if mellow { self.d.cn30_f } else { 0.0 };
        }
        for ci in 0..self.caps.len() {
            let (a, b) = (self.caps[ci].a, self.caps[ci].b);
            let u = self.val(a, e) - self.val(b, e);
            self.caps[ci].u = u;
            self.caps[ci].i = 0.0;
        }
        self.prev = (self.v[self.g], self.v[self.k]);
        self.cfg = None;
        self.be_next = true;
        self.waking = false;
    }

    /// One sample: the outside values `e` at its end.
    /// `mu`: the tube's (Koren's cutoff, [`CUTOFF_MARGIN_V`]).
    fn step(&mut self, e: &Ext, h: f64, mellow: bool, tube: &ControlTube, mu: f64) {
        let cfg = Config {
            down: self.down,
            s1: self.s1,
            be: self.be_next,
            mellow,
        };
        if self.cfg != Some(cfg) {
            self.build(cfg, h);
        }
        let sys = &self.sys;
        let ns = sys.nodes.len();
        let mut w = self.values(e);
        let mut rhs = [0.0; 5];
        for &(r, gv, i) in &sys.ext {
            rhs[r] += gv * w[i];
        }
        for cr in &sys.caps {
            let c = &self.caps[cr.cap];
            let hist = cr.gc * c.u + if sys.be { 0.0 } else { c.i };
            if let Some(a) = cr.ra {
                rhs[a] += hist;
            }
            if let Some(b) = cr.rb {
                rhs[b] -= hist;
            }
        }
        let mut x = [0.0; 5];
        for (r, xr) in x.iter_mut().enumerate().take(ns) {
            *xr = (0..ns).map(|c| sys.yinv[r * ns + c] * rhs[c]).sum();
        }
        self.ip = 0.0;
        {
            let (pg, pk) = (sys.row[self.g].expect("g"), sys.row[self.k].expect("k"));
            let z = |r: usize, c: usize| sys.yinv[r * ns + c];
            let (zgg, zgk, zkg, zkk) = (z(pg, pg), z(pg, pk), z(pk, pg), z(pk, pk));
            let (xl0, xl1) = (x[pg], x[pk]);
            let (mut vg, mut vk) = (self.v[self.g], self.v[self.k]);
            if !sys.be {
                vg += vg - self.prev.0;
                vk += vk - self.prev.1;
            }
            self.prev = (self.v[self.g], self.v[self.k]);
            let (mut cur, mut jac) = ([0.0; 3], [0.0; 9]);
            let mut f = (0.0, 0.0);
            // Cut off without any current this sample: a current into the cathode only
            // raises it, so the tube stays off (the linear solution is the sample's).
            let off = xl0 - xl1 < -(e.screen - xl1) / mu - CUTOFF_MARGIN_V;
            for it in 0..if off { 0 } else { NEWTON_MAX_ITERATIONS } {
                self.evals += 1;
                tube.eval(&[e.plate - vk, e.screen - vk, vg - vk], &mut cur, &mut jac);
                let ig = cur[2];
                let ik = cur[0] + cur[1] + cur[2];
                f = (-ig, ik);
                let r0 = vg - xl0 - (zgg * f.0 + zgk * f.1);
                let r1 = vk - xl1 - (zkg * f.0 + zkk * f.1);
                // d/dvg moves vg1; d/dvk moves every port by -1.
                let dig_g = jac[8];
                let dig_k = -(jac[6] + jac[7] + jac[8]);
                let dik_g = jac[2] + jac[5] + jac[8];
                let dik_k = -jac.iter().sum::<f64>();
                let (d0g, d0k, d1g, d1k) = (-dig_g, -dig_k, dik_g, dik_k);
                let j00 = 1.0 - (zgg * d0g + zgk * d1g);
                let j01 = -(zgg * d0k + zgk * d1k);
                let j10 = -(zkg * d0g + zkk * d1g);
                let j11 = 1.0 - (zkg * d0k + zkk * d1k);
                let det = j00 * j11 - j01 * j10;
                let mut dg = -(j11 * r0 - j01 * r1) / det;
                let mut dk = -(-j10 * r0 + j00 * r1) / det;
                let big = dg.abs().max(dk.abs());
                if big > NEWTON_MAX_STEP_V {
                    dg *= NEWTON_MAX_STEP_V / big;
                    dk *= NEWTON_MAX_STEP_V / big;
                }
                // Converged: the currents of the last evaluation (the update below the
                // tolerance moves them by its gm, nanoamperes), the update dropped.
                if big < NEWTON_TOL_V {
                    break;
                }
                // A small last step: taken, the currents moved along the Jacobian (their
                // error second order in it, ~1e-7 of them at 1 mV).
                if big < NEWTON_LINEAR_V {
                    f = (f.0 + d0g * dg + d0k * dk, f.1 + d1g * dg + d1k * dk);
                    cur[0] += -(jac[0] + jac[1]) * dk + jac[2] * (dg - dk);
                    break;
                }
                vg += dg;
                vk += dk;
                if it + 1 == NEWTON_MAX_ITERATIONS {
                    tube.eval(&[e.plate - vk, e.screen - vk, vg - vk], &mut cur, &mut jac);
                    f = (-cur[2], cur[0] + cur[1] + cur[2]);
                }
            }
            for (r, xr) in x.iter_mut().enumerate().take(ns) {
                *xr += z(r, pg) * f.0 + z(r, pk) * f.1;
            }
            self.ip = cur[0];
        }
        for (r, &j) in sys.nodes.iter().enumerate() {
            self.v[j] = x[r];
            w[j] = x[r];
        }
        // The caps' new voltages and currents.
        let be = sys.be;
        for cr in &self.sys.caps {
            let u = w[cr.ia] - w[cr.ib];
            let c = &mut self.caps[cr.cap];
            c.i = cr.gc * (u - c.u) - if be { 0.0 } else { c.i };
            c.u = u;
        }
        self.be_next = false;
        if !self.down {
            let ik = self.ip.abs() + 0.0;
            let settled = (!self.s1 || (self.v[self.kl] - e.tap).abs() < SLEEP_V)
                && (self.v[self.k] - self.v[self.kl]).abs() < SLEEP_V
                && (self.v[self.nx] - self.nx_rest(e)).abs() < SLEEP_NX_V;
            if ik < SLEEP_IK_A && settled {
                self.awake = false;
                self.kl_hold = self.v[self.kl];
            }
        }
    }

    /// Its springs move (spring 3 with the key, spring 1 with the key or a pedal).
    fn springs(&mut self, down: bool, s1: bool) {
        if down != self.down || s1 != self.s1 {
            self.down = down;
            self.s1 = s1;
            if !self.awake {
                self.awake = true;
                self.waking = true;
            }
            self.be_next = true;
        }
    }
}

/// Gauss-Jordan with partial pivoting of an n x n matrix (n <= 5).
fn invert(a: &[f64], n: usize) -> Option<Vec<f64>> {
    let mut m = a.to_vec();
    let mut inv = vec![0.0; n * n];
    for i in 0..n {
        inv[i * n + i] = 1.0;
    }
    for c in 0..n {
        let p = (c..n).max_by(|&i, &j| m[i * n + c].abs().total_cmp(&m[j * n + c].abs()))?;
        if m[p * n + c] == 0.0 {
            return None;
        }
        if p != c {
            for k in 0..n {
                m.swap(p * n + k, c * n + k);
                inv.swap(p * n + k, c * n + k);
            }
        }
        let d = 1.0 / m[c * n + c];
        for k in 0..n {
            m[c * n + k] *= d;
            inv[c * n + k] *= d;
        }
        for r in 0..n {
            if r != c {
                let f = m[r * n + c];
                if f != 0.0 {
                    for k in 0..n {
                        m[r * n + k] -= f * m[c * n + k];
                        inv[r * n + k] -= f * inv[c * n + k];
                    }
                }
            }
        }
    }
    Some(inv)
}

/// A lower key's grid network (RN1, CN5 into RN2 || CN29 (|| CN30) and the tube's grid
/// capacitances, the cathode and plate held) in the periodic steady state its divider's
/// table drives it into: (c5, g) at each of the table's points, for BRIGHT and MELLOW.
/// Trapezoidal at a table point a step, from the drive's mean across CN5, over frames of
/// the table until 8 of the network's slowest time constants have passed; the last frame
/// kept.
#[derive(Debug, Clone)]
struct Steady {
    by_mellow: [Vec<[f32; 2]>; 2],
}

impl Steady {
    fn new(
        d: &KeyData,
        table: &[f64],
        f0_hz: f64,
        ppc: usize,
        tube: &crate::ir::Pentode,
    ) -> Steady {
        let h = 1.0 / (f0_hz * ppc as f64);
        let n = table.len();
        let mean = table.iter().sum::<f64>() / n as f64;
        let frame_s = n as f64 * h;
        let tau = (d.rn1_ohm + d.rn2_ohm) * d.cn5_f;
        let frames = ((8.0 * tau / frame_s).ceil() as usize).max(3) + 1;
        let one = |mellow: bool| {
            let cg = d.cn29_f + if mellow { d.cn30_f } else { 0.0 } + tube.c_g1k + tube.c_g1p;
            let (g1, g2) = (1.0 / d.rn1_ohm, 1.0 / d.rn2_ohm);
            let (gc5, gcg) = (2.0 * d.cn5_f / h, 2.0 * cg / h);
            let (a, b, c, dd) = (g1 + gc5, -gc5, -gc5, g2 + gc5 + gcg);
            let det = a * dd - b * c;
            let (mut u5, mut i5, mut ug, mut ig) = (mean, 0.0, 0.0, 0.0);
            let mut out = vec![[0.0f32; 2]; n];
            for f in 0..frames {
                for (j, &src) in table.iter().enumerate() {
                    let h5 = gc5 * u5 + i5;
                    let hg = gcg * ug + ig;
                    let (r0, r1) = (g1 * src + h5, -h5 + hg);
                    let c5 = (dd * r0 - b * r1) / det;
                    let g = (-c * r0 + a * r1) / det;
                    let (nu5, nug) = (c5 - g, g);
                    i5 = gc5 * (nu5 - u5) - i5;
                    ig = gcg * (nug - ug) - ig;
                    u5 = nu5;
                    ug = nug;
                    if f + 1 == frames {
                        out[j] = [c5 as f32, g as f32];
                    }
                }
            }
            out
        };
        Steady {
            by_mellow: [one(false), one(true)],
        }
    }

    /// (c5, g) at phase `phi` (cycles, within the table).
    fn at(&self, mellow: bool, phi: f64, ppc: usize) -> (f64, f64) {
        let t = &self.by_mellow[usize::from(mellow)];
        let x = phi * ppc as f64;
        let i0 = x.floor();
        let w = x - i0;
        let i0 = (i0 as usize) % t.len();
        let i1 = (i0 + 1) % t.len();
        let lerp = |k: usize| f64::from(t[i0][k]) * (1.0 - w) + f64::from(t[i1][k]) * w;
        (lerp(0), lerp(1))
    }
}

/// The control tube's Koren law (`devices::Pentode`, the circuit's own model) with its
/// plate law's E1^Ex tabulated: E1 = (Vg2 / Kp) softplus(Kp (1 / mu + r)), r = Vg1 / Vg2,
/// so E1^Ex = (Vg2 / Kp)^Ex S(r) with S(r) = softplus(Kp (1 / mu + r))^Ex in a cubic
/// Hermite table over r (its values and derivatives; outside it, the exact law). The same
/// currents and Jacobian layout as `Pentode::eval` (ports plate, screen, grid, against the
/// cathode), within ~1e-9 of them (`tests`): the screen and grid laws are evaluated as
/// they are there.
#[derive(Debug, Clone)]
pub struct ControlTube {
    exact: Pentode,
    model: crate::ir::Pentode,
    r0: f64,
    inv_dr: f64,
    /// S and dS/dr at the table's points.
    s: Vec<(f64, f64)>,
}

impl ControlTube {
    /// r from just below the cutoff's floor (S under 1e-12 of its value at r = 0) to a grid
    /// half its screen's voltage above the cathode.
    const R_HI: f64 = 0.5;
    const POINTS: usize = 8192;

    pub fn new(m: &crate::ir::Pentode) -> ControlTube {
        let k = &m.model;
        let s_of = |r: f64| {
            let a = k.kp * (1.0 / k.mu + r);
            let sp = crate::devices::softplus(a);
            let sg = crate::devices::sigmoid(a);
            let v = sp.powf(k.ex);
            let d = if sp > 0.0 {
                k.ex * v / sp * sg * k.kp
            } else {
                0.0
            };
            (v, d)
        };
        // the cutoff's floor: kp (1 / mu + r) = -40 (softplus ~ 4e-18)
        let r0 = -40.0 / k.kp - 1.0 / k.mu;
        let dr = (Self::R_HI - r0) / (Self::POINTS - 1) as f64;
        let s = (0..Self::POINTS)
            .map(|i| s_of(r0 + i as f64 * dr))
            .collect();
        ControlTube {
            exact: Pentode::new(m),
            model: m.clone(),
            r0,
            inv_dr: 1.0 / dr,
            s,
        }
    }

    /// S(r) and dS/dr, or None outside the table.
    fn s_at(&self, r: f64) -> Option<(f64, f64)> {
        let x = (r - self.r0) * self.inv_dr;
        if x < 0.0 {
            return Some((0.0, 0.0));
        }
        let i = x as usize;
        if i + 1 >= self.s.len() {
            return None;
        }
        let t = x - i as f64;
        let dr = 1.0 / self.inv_dr;
        let ((y0, d0), (y1, d1)) = (self.s[i], self.s[i + 1]);
        let (m0, m1) = (d0 * dr, d1 * dr);
        let (t2, t3) = (t * t, t * t * t);
        let v = (2.0 * t3 - 3.0 * t2 + 1.0) * y0
            + (t3 - 2.0 * t2 + t) * m0
            + (-2.0 * t3 + 3.0 * t2) * y1
            + (t3 - t2) * m1;
        let dv = ((6.0 * t2 - 6.0 * t) * y0
            + (3.0 * t2 - 4.0 * t + 1.0) * m0
            + (-6.0 * t2 + 6.0 * t) * y1
            + (3.0 * t2 - 2.0 * t) * m1)
            * self.inv_dr;
        Some((v, dv))
    }

    /// As `Pentode::eval`: v = (plate, screen, grid) against the cathode.
    pub fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]) {
        let (vp, vg2, vg1) = (v[0], v[1], v[2]);
        let k = &self.model.model;
        // the exact law where the table doesn't reach (a screen near its floor, r past it)
        if vg2 < 1.0 || k.screen.is_some() {
            return self.exact.eval(v, i, g);
        }
        let r = vg1 / vg2;
        let Some((sv, ds)) = self.s_at(r) else {
            return self.exact.eval(v, i, g);
        };
        g.fill(0.0);
        let scale = 2.0 / k.kg1;
        // (vg2 / kp)^ex and its derivative
        let q = (vg2 / k.kp).powf(k.ex);
        let dq = k.ex * q / vg2;
        let atan = (vp / k.kvb).atan();
        let e1x = q * sv;
        let p = scale * e1x;
        i[0] = p * atan;
        g[0] = p / k.kvb / (1.0 + (vp / k.kvb).powi(2));
        // d(q S(vg1 / vg2)) / dvg2 = dq S - q S' vg1 / vg2^2; / dvg1 = q S' / vg2
        g[1] = scale * atan * (dq * sv - q * ds * vg1 / (vg2 * vg2));
        g[2] = scale * atan * q * ds / vg2;
        // Koren's screen law, as Pentode's
        let x = vg1 + vg2 / k.mu;
        if x > 0.0 {
            let sx = x.sqrt();
            i[1] = x * sx / k.kg2;
            let d = 1.5 * sx / k.kg2;
            g[3 + 1] = d / k.mu;
            g[3 + 2] = d;
        } else {
            i[1] = 0.0;
        }
        let (ig, dig) = self
            .model
            .grid
            .as_ref()
            .map_or((0.0, 0.0), |gc| grid_current(gc, vg1));
        i[2] = ig;
        g[2 * 3 + 2] = dig;
    }
}

/// A compiled oscillator: its phase in cycles (modulo the tables' frame), advanced each
/// sample at the frequency its vibrato grid gives.
#[derive(Debug, Clone, Default)]
struct Osc {
    phi: f64,
}

/// The keys running beside the circuit.
#[derive(Debug)]
pub struct Medium {
    el: NovaKeys,
    model: Arc<KeysModel>,
    tube: ControlTube,
    h: f64,
    /// The keys in the element's range, in order, and the lower ones' steady states.
    keys: Vec<Key>,
    steady: Vec<Option<Steady>>,
    first_key: usize,
    /// Key downs per key (several MIDI notes fold onto one key).
    held: Vec<u32>,
    pedal: bool,
    oscs: Vec<Osc>,
    events: VecDeque<(usize, NoteEvent)>,
    pos: usize,
    started: bool,
    outs: Vec<f64>,
    /// Keys awake after the last push.
    awake: usize,
}

impl Medium {
    pub fn new(el: &NovaKeys, fs: f64) -> Result<Medium, String> {
        let model = load(el)?;
        let (lo, hi) = el.range();
        let keys = model.keys[lo - 1..hi]
            .iter()
            .map(|d| Key::new(d, &model.tube))
            .collect();
        let steady = model.keys[lo - 1..hi]
            .iter()
            .map(|d| {
                (d.ch < 6).then(|| {
                    let note = &model.notes[d.note];
                    Steady::new(
                        d,
                        &note.tables[d.ch - 1],
                        note.f0_hz,
                        model.points_per_cycle,
                        &model.tube,
                    )
                })
            })
            .collect();
        let oscs = vec![Osc::default(); model.notes.len()];
        Ok(Medium {
            el: el.clone(),
            tube: ControlTube::new(&model.tube),
            model,
            h: 1.0 / fs,
            keys,
            steady,
            first_key: lo,
            held: vec![0; hi - lo + 1],
            pedal: false,
            oscs,
            events: VecDeque::new(),
            pos: 0,
            started: false,
            outs: vec![0.0; el.outs.len()],
            awake: 0,
        })
    }

    /// Whether `el` is this medium with other knobs (MELLOW, the vibrato's switches): it
    /// plays on.
    pub fn same(&self, el: &NovaKeys) -> bool {
        NovaKeys {
            mellow: self.el.mellow,
            normal_vibrato: self.el.normal_vibrato,
            small_vibrato: self.el.small_vibrato,
            ..el.clone()
        } == self.el
    }

    /// New knobs (MELLOW, the vibrato's switches), the keys' and oscillators' state carried.
    pub fn update(&mut self, el: &NovaKeys) {
        self.el.mellow = el.mellow;
        self.el.normal_vibrato = el.normal_vibrato;
        self.el.small_vibrato = el.small_vibrato;
    }

    /// An event at step `at` (lands at the push for that step, or the next one if late).
    pub fn queue(&mut self, at: usize, ev: NoteEvent) {
        let ev = match ev {
            NoteEvent::On { note, velocity: 0 } => NoteEvent::Off { note },
            e => e,
        };
        self.events.push_back((at, ev));
    }

    /// The key a MIDI note plays (folded into F1-E7 by octaves).
    pub fn key_of(note: u8) -> usize {
        let mut n = note;
        while n < LOW_MIDI {
            n += 12;
        }
        while n > HIGH_MIDI {
            n -= 12;
        }
        (n - LOW_MIDI) as usize + 1
    }

    fn apply(&mut self, ev: NoteEvent) {
        match ev {
            NoteEvent::On { note, .. } | NoteEvent::Off { note } => {
                let k = Self::key_of(note);
                if k < self.first_key || k >= self.first_key + self.keys.len() {
                    return;
                }
                let i = k - self.first_key;
                if matches!(ev, NoteEvent::On { .. }) {
                    self.held[i] += 1;
                } else {
                    self.held[i] = self.held[i].saturating_sub(1);
                }
                let down = self.held[i] > 0;
                let pedal = self.pedal;
                self.keys[i].springs(down, !(down || pedal));
            }
            NoteEvent::Pedal { down } => {
                self.pedal = down;
                for (i, key) in self.keys.iter_mut().enumerate() {
                    let d = self.held[i] > 0;
                    key.springs(d, !(d || down));
                }
            }
            NoteEvent::Pressure { .. } => {}
        }
    }

    /// The senses at this sample ([`FIXED_SENSES`] then the plate leads); the plate
    /// leads' currents (x `v_per_a`) at the next, into [`Medium::output`]. Returns the
    /// first's.
    pub fn push(&mut self, s: &[f64]) -> f64 {
        while let Some(&(at, ev)) = self.events.front() {
            if at > self.pos {
                break;
            }
            self.events.pop_front();
            self.apply(ev);
        }
        let m = &*self.model;
        let (cycles, ppc) = (m.cycles, m.points_per_cycle);
        let len = cycles * ppc;
        let base = Ext {
            abus: s[12],
            cbus: s[13],
            keyp: s[14],
            screen: m.screen_v,
            ..Ext::default()
        };
        let cuts = [s[15], s[16], s[17], s[14]];
        let g0 = (self.first_key - 1) / 4;
        let mellow = self.el.mellow != 0.0;
        let mu = m.tube.model.mu;
        if !self.started {
            for key in &mut self.keys {
                let e = Ext {
                    tap: cuts[key.d.tap],
                    ..base
                };
                key.start(&e);
            }
            self.started = true;
        }
        // The oscillators to the next sample: each at its vibrato grid's frequency.
        let state = 2 * usize::from(self.el.normal_vibrato != 0.0)
            + usize::from(self.el.small_vibrato != 0.0);
        let frame = cycles as f64;
        let mut phis = [0.0; 12];
        for ((x, o), (nd, &vg)) in phis
            .iter_mut()
            .zip(&mut self.oscs)
            .zip(m.notes.iter().zip(&s[..12]))
        {
            o.phi += nd.vibrato[state].at(vg) * self.h;
            if o.phi >= frame {
                o.phi -= frame;
            }
            *x = o.phi;
        }
        self.outs.iter_mut().for_each(|o| *o = 0.0);
        let mut awake = 0;
        for (key, steady) in self.keys.iter_mut().zip(&self.steady) {
            if !key.awake {
                continue;
            }
            let d = &key.d;
            let src = if d.ch == 6 {
                let t = &m.notes[d.note].tap;
                let x = phis[d.note].fract() * ppc as f64;
                let i0 = x.floor();
                let w = x - i0;
                let i0 = (i0 as usize) % ppc;
                t[i0] * (1.0 - w) + t[(i0 + 1) % ppc] * w
            } else {
                let t = &m.notes[d.note].tables[d.ch - 1];
                let x = phis[d.note] * ppc as f64;
                let i0 = x.floor();
                let w = x - i0;
                let i0 = (i0 as usize) % len;
                t[i0] * (1.0 - w) + t[(i0 + 1) % len] * w
            };
            let gi = d.group - g0;
            let e = Ext {
                src,
                tap: cuts[d.tap],
                plate: s[FIXED_SENSES + gi],
                ..base
            };
            if key.waking {
                let (c5, g) = steady
                    .as_ref()
                    .map_or((0.0, 0.0), |st| st.at(mellow, phis[d.note], ppc));
                key.wake(&e, c5, g, mellow);
            }
            key.step(&e, self.h, mellow, &self.tube, mu);
            self.outs[gi] += key.ip;
            awake += usize::from(key.awake);
        }
        self.awake = awake;
        let k = self.el.v_per_a;
        self.outs.iter_mut().for_each(|o| *o *= k);
        self.pos += 1;
        self.outs[0]
    }

    pub fn outs(&self) -> usize {
        self.outs.len()
    }

    pub fn output(&self, j: usize) -> f64 {
        self.outs[j]
    }

    /// Keys awake after the last push.
    pub fn sounding(&self) -> usize {
        self.awake
    }

    /// The control tubes' evaluations so far (Newton's iterations; statistics).
    pub fn evaluations(&self) -> u64 {
        self.keys.iter().map(|k| k.evals).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inverts() {
        let a = [4.0, 1.0, 0.0, 1.0, 3.0, 1.0, 0.0, 1.0, 2.0];
        let inv = invert(&a, 3).unwrap();
        for r in 0..3 {
            for c in 0..3 {
                let s: f64 = (0..3).map(|k| a[r * 3 + k] * inv[k * 3 + c]).sum();
                assert!((s - f64::from(u8::from(r == c))).abs() < 1e-12);
            }
        }
    }

    #[test]
    fn the_tabulated_tube_is_the_exact_one() {
        let m = crate::ir::Pentode {
            name: "t".into(),
            model: crate::ir::KorenPentode {
                mu: 21.547562632351568,
                ex: 1.095136982308402,
                kg1: 2555.2638352759955,
                kg2: 4207.833968312556,
                kp: 162.37472229318652,
                kvb: 30.56537901315096,
                screen: None,
            },
            grid: Some(crate::ir::GridCurrent {
                perveance: 0.001,
                contact_v: -0.7,
                smooth_v: 0.05,
            }),
            c_g1k: 5e-12,
            c_g1p: 7e-15,
            c_pk: 8.5e-12,
        };
        let fast = ControlTube::new(&m);
        let exact = Pentode::new(&m);
        let (mut i0, mut g0, mut i1, mut g1) = ([0.0; 3], [0.0; 9], [0.0; 3], [0.0; 9]);
        let mut worst: f64 = 0.0;
        for vg2 in [20.0, 27.0, 60.0, 120.0, 250.0, 400.0] {
            for j in 0..2001 {
                let vg1 = -0.3 * vg2 + (0.3 * vg2 + 4.0) * j as f64 / 2000.0;
                for vp in [5.0, 60.0, 260.0, 400.0] {
                    let v = [vp, vg2, vg1];
                    exact.eval(&v, &mut i0, &mut g0);
                    fast.eval(&v, &mut i1, &mut g1);
                    // against the plate current's scale at this screen (no grid bias)
                    let mut ref0 = [0.0; 3];
                    exact.eval(&[vp, vg2, 0.0], &mut ref0, &mut [0.0; 9]);
                    let scale = ref0[0].abs().max(1e-6);
                    for c in 0..3 {
                        worst = worst.max((i0[c] - i1[c]).abs() / scale);
                    }
                    for c in 0..9 {
                        let s = g0[c].abs().max(scale / vg2.max(1.0));
                        worst = worst.max((g0[c] - g1[c]).abs() / s);
                    }
                }
            }
        }
        assert!(worst < 1e-7, "{worst:e}");
    }

    #[test]
    fn folds_notes() {
        assert_eq!(Medium::key_of(29), 1);
        assert_eq!(Medium::key_of(100), 72);
        assert_eq!(Medium::key_of(17), 1);
        assert_eq!(Medium::key_of(101), 61);
    }

    #[test]
    fn curves_interpolate_and_hold() {
        let c = Curve {
            v: vec![-20.0, -10.0, 0.0],
            f_hz: vec![1780.0, 1760.0, 1750.0],
        };
        assert_eq!(c.at(-30.0), 1780.0);
        assert_eq!(c.at(5.0), 1750.0);
        assert!((c.at(-15.0) - 1770.0).abs() < 1e-12);
        assert!((c.at(-10.0) - 1760.0).abs() < 1e-12);
    }
}
