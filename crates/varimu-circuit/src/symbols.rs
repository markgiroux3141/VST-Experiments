//! The symbol table: one symbol per macro part of the circuit format
//! (`varimu/kicad/symbols.py`'s SYMBOLS, the KiCad library's and the editor's), and the
//! placement transform the editor and the connectivity share
//! (`varimu/editor/symbols.py`).
//!
//! Each symbol has its kind, macro, pins (number -> the macro's node order, or a device
//! pin's role) and fields: Reference = the part's name, Value = the macro's main value
//! (`primary`); capitalized fields are metadata (Source, Param, Genome, Tol, ...),
//! lowercase ones the macro's other params. Pin and graphic coordinates are mm, y up
//! (KiCad's symbol editor); a pin's `at` is its connection point, its `angle` points
//! from there into the body.

use std::sync::OnceLock;

pub const LIBRARY: &str = "varimu";
const META: [&str; 4] = ["Source", "Param", "Genome", "Tol"];

#[derive(Debug, Clone, PartialEq)]
pub struct Pin {
    pub number: String,
    /// A device pin's role (p, g, k, g2, g1, a), else the number.
    pub name: String,
    pub x: f64,
    pub y: f64,
    /// Direction from the connection point into the body (degrees, y up).
    pub angle: i32,
    pub length: f64,
    pub kind: &'static str,
}

/// A graphic of a symbol's body (y up).
#[derive(Debug, Clone, PartialEq)]
pub enum Graphic {
    Poly {
        pts: Vec<(f64, f64)>,
        filled: bool,
    },
    Rect {
        x0: f64,
        y0: f64,
        x1: f64,
        y1: f64,
    },
    Circle {
        cx: f64,
        cy: f64,
        r: f64,
        filled: bool,
    },
    /// Through three points.
    Arc {
        start: (f64, f64),
        mid: (f64, f64),
        end: (f64, f64),
    },
    Text {
        text: &'static str,
        x: f64,
        y: f64,
        size: f64,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Macro,
    Device,
    Winding,
    Core,
    Coupling,
    Switch,
    Power,
}

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Kind::Macro => "macro",
            Kind::Device => "device",
            Kind::Winding => "winding",
            Kind::Core => "core",
            Kind::Coupling => "coupling",
            Kind::Switch => "switch",
            Kind::Power => "power",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct SymbolDef {
    pub name: String,
    pub kind: Kind,
    /// The Reference's letters.
    pub prefix: &'static str,
    pub description: String,
    /// Pins per unit (one entry: a single-unit symbol).
    pub units: Vec<Vec<Pin>>,
    pub graphics: Vec<Graphic>,
    /// The circuit format's macro, and the macro param the Value carries.
    pub macro_: Option<&'static str>,
    pub primary: Option<&'static str>,
    /// Fields the library lists (empty defaults).
    pub fields: Vec<&'static str>,
    pub value: String,
    /// Pin numbers in the macro's node order (one unit).
    pub order: Vec<String>,
    /// Where Reference and Value go: x, y of the reference, y of the value, justify.
    pub text: (f64, f64, f64, &'static str),
}

impl SymbolDef {
    pub fn pins(&self) -> impl Iterator<Item = &Pin> {
        self.units.iter().flatten()
    }

    pub fn pin(&self, number: &str) -> Option<&Pin> {
        self.pins().find(|p| p.number == number)
    }
}

fn pin(number: &str, name: &str, x: f64, y: f64, angle: i32, length: f64) -> Pin {
    Pin {
        number: number.into(),
        name: name.into(),
        x,
        y,
        angle,
        length,
        kind: "passive",
    }
}

fn poly(pts: &[(f64, f64)]) -> Graphic {
    Graphic::Poly {
        pts: pts.to_vec(),
        filled: false,
    }
}

fn rect(x0: f64, y0: f64, x1: f64, y1: f64) -> Graphic {
    Graphic::Rect { x0, y0, x1, y1 }
}

fn circle(cx: f64, cy: f64, r: f64, filled: bool) -> Graphic {
    Graphic::Circle { cx, cy, r, filled }
}

fn text(text: &'static str, x: f64, y: f64, size: f64) -> Graphic {
    Graphic::Text { text, x, y, size }
}

/// Four bumps to the right from y = top down to bottom.
fn coil(top: f64, bottom: f64) -> Vec<Graphic> {
    let h = (top - bottom) / 4.0;
    (0..4)
        .map(|i| {
            let i = i as f64;
            Graphic::Arc {
                start: (0.0, top - i * h),
                mid: (h / 2.0, top - (i + 0.5) * h),
                end: (0.0, top - (i + 1.0) * h),
            }
        })
        .collect()
}

fn vertical() -> Vec<Pin> {
    vec![
        pin("1", "1", 0.0, 3.81, 270, 1.27),
        pin("2", "2", 0.0, -3.81, 90, 1.27),
    ]
}

fn r_body() -> Graphic {
    rect(-1.016, -2.54, 1.016, 2.54)
}

fn triode() -> Vec<Graphic> {
    let mut g = vec![
        circle(0.0, 0.0, 5.08, false),
        poly(&[(-2.54, 2.54), (2.54, 2.54)]),
    ];
    for x in [-2.54, -1.27, 0.0, 1.27] {
        g.push(poly(&[(x, 0.0), (x + 0.762, 0.0)]));
    }
    g.push(poly(&[(-2.54, -1.778), (-2.54, -2.54), (2.54, -2.54)]));
    g
}

fn diode() -> Vec<Graphic> {
    vec![
        poly(&[(-1.27, 1.016), (1.27, 1.016), (0.0, -1.016), (-1.27, 1.016)]),
        poly(&[(-1.27, -1.016), (1.27, -1.016)]),
    ]
}

const DEFAULT_TEXT: (f64, f64, f64, &str) = (2.54, 1.27, -1.27, "left");

#[allow(clippy::too_many_arguments)]
fn macro_sym(
    name: &str,
    macro_: &'static str,
    prefix: &'static str,
    desc: &str,
    pins: Vec<Pin>,
    graphics: Vec<Graphic>,
    primary: Option<&'static str>,
    extra: &[&'static str],
    toleranced: bool,
    text: (f64, f64, f64, &'static str),
) -> SymbolDef {
    let meta: &[&str] = if toleranced { &META } else { &META[..3] };
    SymbolDef {
        name: name.into(),
        kind: Kind::Macro,
        prefix,
        description: desc.into(),
        order: pins.iter().map(|p| p.number.clone()).collect(),
        units: vec![pins],
        graphics,
        macro_: Some(macro_),
        primary,
        fields: meta.iter().chain(extra).copied().collect(),
        value: name.into(),
        text,
    }
}

fn source(
    name: &str,
    macro_: &'static str,
    desc: &str,
    mark: Vec<Graphic>,
    primary: &'static str,
    extra: &[&'static str],
) -> SymbolDef {
    let pins = vec![
        pin("1", "1", 0.0, 5.08, 270, 2.54),
        pin("2", "2", 0.0, -5.08, 90, 2.54),
    ];
    let mut g = vec![circle(0.0, 0.0, 2.54, false), text("+", 0.0, 1.524, 1.0)];
    g.extend(mark);
    macro_sym(
        name,
        macro_,
        "V",
        desc,
        pins,
        g,
        Some(primary),
        extra,
        false,
        (3.302, 1.27, -1.27, "left"),
    )
}

const DEVICE_FIELDS: [&str; 9] = [
    "Tol",
    "Model",
    "emission",
    "mu",
    "grid_contact_v",
    "parallel",
    "area",
    "instance",
    "name",
];

fn device(
    name: &str,
    desc: &str,
    units: Vec<Vec<Pin>>,
    graphics: Vec<Graphic>,
    value: &str,
    prefix: &'static str,
    text: (f64, f64, f64, &'static str),
) -> SymbolDef {
    SymbolDef {
        name: name.into(),
        kind: Kind::Device,
        prefix,
        description: desc.into(),
        units,
        graphics,
        macro_: None,
        primary: None,
        fields: DEVICE_FIELDS.to_vec(),
        value: value.into(),
        order: Vec::new(),
        text,
    }
}

fn triode_pins(p: &str, g: &str, k: &str) -> Vec<Pin> {
    vec![
        pin(p, "p", 0.0, 7.62, 270, 5.08),
        pin(g, "g", -7.62, 0.0, 0, 5.08),
        pin(k, "k", 0.0, -7.62, 90, 5.08),
    ]
}

fn diode_pins(a: &str, k: &str) -> Vec<Pin> {
    vec![
        pin(a, "a", 0.0, 3.81, 270, 2.794),
        pin(k, "k", 0.0, -3.81, 90, 2.794),
    ]
}

fn rotary(n: usize) -> SymbolDef {
    let top = (n as f64 - 1.0) * 1.27;
    let mut pins = vec![pin("C", "C", -7.62, 0.0, 0, 2.54)];
    let mut g = vec![
        circle(-4.572, 0.0, 0.508, false),
        poly(&[(-4.064, 0.0), (4.064, top)]),
    ];
    for k in 1..=n {
        let y = top - (k as f64 - 1.0) * 2.54;
        pins.push(pin(&k.to_string(), &k.to_string(), 7.62, y, 180, 2.54));
        g.push(circle(4.572, y, 0.508, false));
    }
    SymbolDef {
        name: format!("SW_Rotary_{n}"),
        kind: Kind::Switch,
        prefix: "S",
        description: format!(
            "Rotary switch deck, {n} positions: contact k is the control's k-th choice \
             (or position min + k - 1); decks with the same Control are ganged"
        ),
        units: vec![pins],
        graphics: g,
        macro_: None,
        primary: None,
        fields: vec!["Control"],
        value: "SW".into(),
        order: Vec::new(),
        text: (-5.08, top + 4.064, top + 2.54, "left"),
    }
}

fn table() -> Vec<SymbolDef> {
    let arrow_wiper = poly(&[(2.032, 0.508), (1.27, 0.0), (2.032, -0.508)]);
    let mut coil_dot = coil(2.54, -2.54);
    coil_dot.push(circle(-1.27, 2.54, 0.254, true));
    let mut v = vec![
        macro_sym(
            "R",
            "R",
            "R",
            "Resistor (pins 1, 2)",
            vertical(),
            vec![r_body()],
            Some("r"),
            &["parallel"],
            true,
            DEFAULT_TEXT,
        ),
        macro_sym(
            "C",
            "C",
            "C",
            "Capacitor (pins 1, 2)",
            vec![
                pin("1", "1", 0.0, 3.81, 270, 3.048),
                pin("2", "2", 0.0, -3.81, 90, 3.048),
            ],
            vec![
                poly(&[(-2.032, 0.762), (2.032, 0.762)]),
                poly(&[(-2.032, -0.762), (2.032, -0.762)]),
            ],
            Some("c"),
            &[],
            true,
            DEFAULT_TEXT,
        ),
        macro_sym(
            "L",
            "L",
            "L",
            "Inductor (current from pin 1, the dotted end, to pin 2)",
            vertical(),
            coil_dot.clone(),
            Some("l"),
            &[],
            false,
            DEFAULT_TEXT,
        ),
        macro_sym(
            "Pot",
            "pot",
            "R",
            "Potentiometer: pin 1 end_a, 2 wiper, 3 end_b; at = 0 puts the wiper at pin 1",
            vec![
                pin("1", "1", 0.0, 3.81, 270, 1.27),
                pin("2", "2", 3.81, 0.0, 180, 2.54),
                pin("3", "3", 0.0, -3.81, 90, 1.27),
            ],
            vec![r_body(), arrow_wiper.clone()],
            Some("r"),
            &["at", "taper_mid"],
            true,
            (-2.54, 1.27, -1.27, "right"),
        ),
        macro_sym(
            "Rheostat",
            "rheostat",
            "R",
            "Variable resistor (pins 1, 2): at = 0 is no resistance",
            vertical(),
            vec![
                r_body(),
                poly(&[(-2.032, -2.032), (2.032, 2.032)]),
                poly(&[(1.016, 2.032), (2.032, 2.032), (2.032, 1.016)]),
            ],
            Some("r"),
            &["at", "taper_mid"],
            true,
            (3.302, 1.27, -1.27, "left"),
        ),
        macro_sym(
            "Pot_Tapped",
            "tapped_pot",
            "R",
            "Tapped potentiometer: pin 1 end_a, 2 tap, 3 wiper, 4 end_b (at, tap: from end_a)",
            vec![
                pin("1", "1", 0.0, 5.08, 270, 1.27),
                pin("2", "2", -3.81, 0.0, 0, 2.794),
                pin("3", "3", 3.81, 0.0, 180, 2.54),
                pin("4", "4", 0.0, -5.08, 90, 1.27),
            ],
            vec![rect(-1.016, -3.81, 1.016, 3.81), arrow_wiper],
            Some("r"),
            &["at", "tap"],
            true,
            (-1.524, 4.064, 2.54, "right"),
        ),
        macro_sym(
            "T_Pad",
            "t_pad",
            "AT",
            "T attenuator: pin 1 a, 2 b, 3 common; Value is its impedance z",
            vec![
                pin("1", "1", -6.35, 0.0, 0, 2.54),
                pin("2", "2", 6.35, 0.0, 180, 2.54),
                pin("3", "3", 0.0, -5.08, 90, 2.54),
            ],
            vec![rect(-3.81, -2.54, 3.81, 2.54), text("T", 0.0, 0.0, 1.27)],
            Some("z"),
            &["atten_db"],
            true,
            (-3.81, 5.08, 3.302, "left"),
        ),
        source(
            "V",
            "V",
            "DC voltage source: pin 1 +, 2 -",
            vec![],
            "v",
            &[],
        ),
        source(
            "Sine",
            "sine",
            "Sine source: pin 1 +, 2 -; Value is its amplitude",
            vec![text("~", 0.0, -0.508, 1.524)],
            "amplitude_v",
            &["freq_hz", "offset_v", "phase_deg"],
        ),
        source(
            "Mains",
            "mains",
            "A winding fed from the mains (the circuit's `mains` block): pin 1 +, 2 -; Value \
             is its rms voltage at the rated mains",
            vec![text("~", 0.0, -0.508, 1.524), text("AC", 0.0, -3.81, 1.0)],
            "v_rms",
            &["phase_deg"],
        ),
        macro_sym(
            "Bridge",
            "bridge",
            "D",
            "Bridge rectifier: pin 1 ac_a, 2 ac_b, 3 +, 4 -; Value is the device file",
            vec![
                pin("1", "1", -5.08, 0.0, 0, 2.54),
                pin("2", "2", 5.08, 0.0, 180, 2.54),
                pin("3", "3", 0.0, 5.08, 270, 2.54),
                pin("4", "4", 0.0, -5.08, 90, 2.54),
            ],
            vec![poly(&[
                (-2.54, 0.0),
                (0.0, 2.54),
                (2.54, 0.0),
                (0.0, -2.54),
                (-2.54, 0.0),
            ])],
            None,
            &["Model", "arm_c_f_per_area", "area", "instance", "parallel"],
            false,
            (2.54, 3.81, 2.286, "left"),
        ),
        macro_sym(
            "VR_Tube",
            "vr_tube",
            "V",
            "Glow-discharge voltage reference: pin 1 anode, 2 cathode; Value is its operating \
             voltage, `device` its device file (a junction diode: the slope)",
            vec![
                pin("1", "1", 0.0, 5.08, 270, 2.54),
                pin("2", "2", 0.0, -5.08, 90, 2.54),
            ],
            vec![
                circle(0.0, 0.0, 2.54, false),
                circle(0.762, 0.762, 0.381, true),
                poly(&[(-1.27, -1.27), (1.27, -1.27)]),
            ],
            Some("operating_v"),
            &["device", "Model", "Mid", "ref_current_a", "instance"],
            false,
            (3.302, 1.27, -1.27, "left"),
        ),
        macro_sym(
            "Speaker",
            "speaker",
            "LS",
            "Speaker in its cabinet (varimu.devices.speaker): pin 1 +, 2 -, 3 the sound pressure at the listening point (pascals as volts); Value is its component version",
            vec![
                pin("1", "1", -5.08, 2.54, 0, 2.54),
                pin("2", "2", -5.08, -2.54, 0, 2.54),
                pin("3", "3", 6.35, 0.0, 180, 2.54),
            ],
            vec![
                rect(-2.54, -1.524, 0.0, 1.524),
                poly(&[
                    (0.0, 1.524),
                    (3.81, 3.81),
                    (3.81, -3.81),
                    (0.0, -1.524),
                    (0.0, 1.524),
                ]),
            ],
            Some("component"),
            &[
                "distance_m",
                "width_m",
                "height_m",
                "depth_m",
                "offset_x_m",
                "offset_y_m",
            ],
            false,
            (0.0, 6.35, 4.826, "left"),
        ),
    ];
    let dev_text = (5.842, 1.27, -1.27, "left");
    v.push(device(
        "Triode",
        "Triode (p, g, k); Value is the device file",
        vec![triode_pins("1", "2", "3")],
        triode(),
        "12AX7@1",
        "V",
        dev_text,
    ));
    v.push(device(
        "Triode_Dual",
        "Dual triode, units A (pins 1-3) and B (6-8); each unit is one device instance",
        vec![triode_pins("1", "2", "3"), triode_pins("6", "7", "8")],
        triode(),
        "12AX7@1",
        "V",
        dev_text,
    ));
    let mut pentode = vec![
        circle(0.0, 0.0, 6.35, false),
        poly(&[(-2.54, 3.81), (2.54, 3.81)]),
    ];
    for y in [1.27, -1.27] {
        for x in [-2.54, -1.27, 0.0, 1.27] {
            pentode.push(poly(&[(x, y), (x + 0.762, y)]));
        }
    }
    pentode.push(poly(&[(-2.54, -3.048), (-2.54, -3.81), (2.54, -3.81)]));
    v.push(device(
        "Pentode",
        "Pentode (p, g2, g1, k); Value is the device file",
        vec![vec![
            pin("1", "p", 0.0, 8.89, 270, 5.08),
            pin("2", "g2", 8.89, 1.27, 180, 6.35),
            pin("3", "g1", -8.89, -1.27, 0, 6.35),
            pin("4", "k", 0.0, -8.89, 90, 5.08),
        ]],
        pentode,
        "6973@1",
        "V",
        (-3.81, 8.89, 7.366, "right"),
    ));
    v.push(device(
        "Diode",
        "Diode, vacuum or junction (a, k); Value is the device file",
        vec![diode_pins("1", "2")],
        diode(),
        "6X4@1",
        "D",
        dev_text,
    ));
    v.push(device(
        "Diode_Dual",
        "Dual diode (a full-wave rectifier), units A (pins 1, 2) and B (3, 4)",
        vec![diode_pins("1", "2"), diode_pins("3", "4")],
        diode(),
        "6X4@1",
        "V",
        dev_text,
    ));
    v.push(SymbolDef {
        name: "Winding".into(),
        kind: Kind::Winding,
        prefix: "W",
        description: "Transformer winding: pin 1 the dotted end; Value is its label, \
                      Transformer its core's Reference; ratio (turns over the reference \
                      winding's), r, c"
            .into(),
        units: vec![vertical()],
        graphics: coil_dot,
        macro_: None,
        primary: None,
        fields: vec!["Transformer", "ratio", "r", "c"],
        value: "p".into(),
        order: Vec::new(),
        text: DEFAULT_TEXT,
    });
    v.push(SymbolDef {
        name: "Core".into(),
        kind: Kind::Core,
        prefix: "T",
        description: "Transformer core (no pins): its Reference names the transformer, whose \
                      Winding symbols name it; material, area_m2, path_m, gap_m, turns, \
                      leakage_h, interwinding ({ends: [<label>.dot, <label>.other], to: \
                      <label>.dot, c})"
            .into(),
        units: vec![vec![]],
        graphics: vec![
            poly(&[(-0.508, 5.08), (-0.508, -5.08)]),
            poly(&[(0.508, 5.08), (0.508, -5.08)]),
        ],
        macro_: None,
        primary: None,
        fields: vec![
            "material",
            "area_m2",
            "path_m",
            "gap_m",
            "turns",
            "leakage_h",
            "interwinding",
        ],
        value: "core".into(),
        order: Vec::new(),
        text: DEFAULT_TEXT,
    });
    v.push(SymbolDef {
        name: "K".into(),
        kind: Kind::Coupling,
        prefix: "K",
        description: "Coupling of two inductors (no pins): `inductors` [L_a, L_b]; Value is k"
            .into(),
        units: vec![vec![]],
        graphics: vec![text("K", 0.0, 0.0, 1.27)],
        macro_: Some("K"),
        primary: Some("k"),
        fields: vec!["Source", "Param", "Genome", "inductors"],
        value: "K".into(),
        order: Vec::new(),
        text: DEFAULT_TEXT,
    });
    v.extend((2..13).map(rotary));
    v.push(SymbolDef {
        name: "GND".into(),
        kind: Kind::Power,
        prefix: "#PWR",
        description: "Ground: node 0".into(),
        units: vec![vec![Pin {
            kind: "power_in",
            ..pin("1", "GND", 0.0, 0.0, 270, 0.0)
        }]],
        graphics: vec![poly(&[
            (0.0, 0.0),
            (0.0, -1.27),
            (1.27, -1.27),
            (0.0, -2.54),
            (-1.27, -1.27),
            (0.0, -1.27),
        ])],
        macro_: None,
        primary: None,
        fields: Vec::new(),
        value: "GND".into(),
        order: Vec::new(),
        text: DEFAULT_TEXT,
    });
    v
}

/// Every symbol, in the library's order.
pub fn all() -> &'static [SymbolDef] {
    static TABLE: OnceLock<Vec<SymbolDef>> = OnceLock::new();
    TABLE.get_or_init(table)
}

/// The symbol called `name`.
pub fn get(name: &str) -> Option<&'static SymbolDef> {
    all().iter().find(|s| s.name == name)
}

/// The placement rotations.
pub const ROTATIONS: [i64; 4] = [0, 90, 180, 270];

/// A point of a symbol (y down) placed at `at`, mirrored (x -> -x) if asked, then
/// rotated `rot` degrees counter-clockwise on the screen.
pub fn transform(x: f64, y: f64, at: (f64, f64), rot: i64, mirror: bool) -> (f64, f64) {
    let x = if mirror { -x } else { x };
    let (c, s) = match rot.rem_euclid(360) {
        90 => (0.0, 1.0),
        180 => (-1.0, 0.0),
        270 => (0.0, -1.0),
        _ => (1.0, 0.0),
    };
    (at.0 + x * c + y * s, at.1 - x * s + y * c)
}

/// The connection points of a placed unit's pins (1-based unit), by pin number.
pub fn pin_points(
    sym: &SymbolDef,
    unit: usize,
    at: (f64, f64),
    rot: i64,
    mirror: bool,
) -> Vec<(String, (f64, f64))> {
    sym.units[unit - 1]
        .iter()
        .map(|p| (p.number.clone(), transform(p.x, -p.y, at, rot, mirror)))
        .collect()
}
