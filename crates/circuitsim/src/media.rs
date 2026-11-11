//! Media beside the circuit (a plate, `crate::plate`; tape, `crate::tape_stream`; a Rhodes
//! harp, `crate::harp`; a Clavinet's strings, `crate::clavinet`; the Nickel Organ's keys,
//! `crate::nickel`): each senses a voltage in
//! the circuit after every sample (the keyboards' media sense nothing: their keys are note
//! events) and drives its outputs' nodes at the next one, like control inputs
//! ([`crate::mna::Mna::media`]); most have one output, `out`.

use crate::ir::{ClavStrings, Harp, NickelKeys, NovaKeys, Plate, Spring, Tape};

/// A medium's element in the IR.
#[derive(Debug, Clone, PartialEq)]
pub enum MediumElement {
    Plate(Plate),
    Spring(Spring),
    Tape(Tape),
    Harp(Harp),
    ClavStrings(ClavStrings),
    NovaKeys(NovaKeys),
    NickelKeys(NickelKeys),
}

/// A keyboard's event for a medium played by keys (a harp): queued for the step it lands at
/// ([`crate::transient::Transient::queue_note`], [`crate::stream::Stream::queue_notes`]).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NoteEvent {
    /// A key down (MIDI note, velocity 1-127; 0 is a key up).
    On {
        note: u8,
        velocity: u8,
    },
    Off {
        note: u8,
    },
    /// The sustain pedal (MIDI CC 64, down at 64 and over).
    Pedal {
        down: bool,
    },
    /// Aftertouch, 0-127: channel pressure, every key held (the Clavinet's finger
    /// pressure; a harp has none).
    Pressure {
        value: u8,
    },
}

impl MediumElement {
    pub fn name(&self) -> &str {
        match self {
            MediumElement::Plate(p) => &p.name,
            MediumElement::Spring(p) => &p.name,
            MediumElement::Tape(t) => &t.name,
            MediumElement::Harp(h) => &h.name,
            MediumElement::ClavStrings(c) => &c.name,
            MediumElement::NovaKeys(k) => &k.name,
            MediumElement::NickelKeys(k) => &k.name,
        }
    }

    /// The nodes its outputs drive, in order.
    pub fn outs(&self) -> Vec<&str> {
        match self {
            MediumElement::Plate(p) => vec![&p.out],
            MediumElement::Spring(p) => vec![&p.out],
            MediumElement::Tape(t) => std::iter::once(t.out.as_str())
                .chain(t.sync_out.as_deref())
                .collect(),
            MediumElement::Harp(h) => vec![&h.out],
            MediumElement::ClavStrings(c) => vec![&c.centre, &c.bridge, &c.bridge_neg],
            MediumElement::NovaKeys(k) => k.outs.iter().map(String::as_str).collect(),
            MediumElement::NickelKeys(k) => vec![&k.out],
        }
    }

    /// A tape's capstan supply node (varispeed), if any.
    pub fn supply(&self) -> Option<&str> {
        match self {
            MediumElement::Plate(_)
            | MediumElement::Spring(_)
            | MediumElement::Harp(_)
            | MediumElement::ClavStrings(_)
            | MediumElement::NovaKeys(_)
            | MediumElement::NickelKeys(_) => None,
            MediumElement::Tape(t) => t.supply.as_deref(),
        }
    }

    /// The sense's (positive, negative) nodes (a harp's: ground).
    pub fn sense(&self) -> (&str, &str) {
        match self {
            MediumElement::Plate(p) => (&p.sense_pos, &p.sense_neg),
            MediumElement::Spring(p) => (&p.sense_pos, &p.sense_neg),
            MediumElement::Tape(t) => (&t.sense_pos, &t.sense_neg),
            MediumElement::Harp(_)
            | MediumElement::ClavStrings(_)
            | MediumElement::NovaKeys(_)
            | MediumElement::NickelKeys(_) => (crate::ir::GROUND, crate::ir::GROUND),
        }
    }

    /// The nodes a medium of many senses reads, in its order (the Novachord's keys; the
    /// others sense one voltage, [`MediumElement::sense`]: none here).
    pub fn senses(&self) -> Vec<&str> {
        match self {
            MediumElement::NovaKeys(k) => k.senses(),
            _ => Vec::new(),
        }
    }
}

/// A tape element's stream and its sense's scale.
#[derive(Debug)]
pub struct TapeMedium {
    pub tape: Tape,
    stream: crate::tape_stream::TapeStream,
    fs: f64,
    noise_seed: Option<u64>,
    /// The run's origin (`Medium::set_origin`), for a stream made anew.
    origin: u64,
    /// The recording kernel on the GPU (`Medium::set_tape_gpu`), for a stream made anew.
    gpu: bool,
    /// Scratch: a push's fields and its EMF (and its other readouts: crosstalk's,
    /// Sel-Sync's).
    fields: Vec<f64>,
    emf: Vec<f64>,
    readouts: crate::tape_stream::Readouts,
}

impl TapeMedium {
    /// The stream, with the coating's grain keyed by (the circuit's seed, the element's
    /// name) when the circuit's noise is on and the tape's particles are fitted; the
    /// transport's random parts keyed by the circuit's seed (0 without noise).
    fn stream(
        t: &Tape,
        fs: f64,
        seed: Option<u64>,
    ) -> Result<crate::tape_stream::TapeStream, String> {
        let fitted = t.medium.particle_volume_m3 > 0.0 && t.medium.packing > 0.0;
        let grain = seed.filter(|_| fitted).map(|s| (s, t.name.as_str()));
        let mut st =
            crate::tape_stream::TapeStream::build(&t.medium, fs, grain, seed.unwrap_or(0))?;
        // Leave four logical cores to the circuit's own threads (its parts, a multi-rate
        // part, the stream's worker): the Ampex 351 runs 72.9x real time with 12 of 16,
        // 80x with all 16 (TAPE_PLAN.md, "Speed").
        // CIRCUITSIM_TAPE_THREADS overrides it (pieces of a print run at once:
        // TAPE_SPEED_PLAN.md P3); the output doesn't depend on it.
        let cores = std::thread::available_parallelism().map_or(1, |n| n.get());
        let threads = std::env::var("CIRCUITSIM_TAPE_THREADS")
            .ok()
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(cores.saturating_sub(4))
            .max(1);
        st.set_threads(threads)?;
        Ok(st)
    }

    /// Push sensed voltages (one, or the literal bias's samples per push) as fields; the
    /// EMF at the next sample.
    /// With the capstan's supply frequency (varispeed), if it has one.
    fn push(&mut self, vs: impl Iterator<Item = f64>, supply_hz: Option<f64>) -> f64 {
        let k = self.tape.h_per_v;
        self.fields.clear();
        self.fields.extend(vs.map(|v| k * v));
        self.emf.clear();
        if self.tape.medium.crosstalk.is_some() || self.tape.medium.sync.is_some() {
            let sup = supply_hz.map(|f| [f]);
            self.stream.push_many_readouts(
                &self.fields,
                sup.as_ref().map(|s| &s[..]),
                &mut self.emf,
                &mut self.readouts,
            )
        } else {
            match supply_hz {
                Some(f) => self
                    .stream
                    .push_many_supply(&self.fields, &[f], &mut self.emf),
                None => self.stream.push_many(&self.fields, &mut self.emf),
            }
        }
        .expect("the tape's blocks are recorded before the repro head reads them");
        self.emf[0]
    }
}

/// The crosstalk between a circuit's tapes (PERIOD_GEAR_BACKLOG.md PG1, MT3): for media
/// `els` whose outputs' rows start at `first_row` (in order, [`MediumElement::outs`] each),
/// the triples (row of a head's output, the medium beside it on the same tape, which of
/// its outputs) whose cross EMF ([`Medium::cross`]) that output adds: tapes of one
/// crosstalk group, tracks one apart (an edge track has one neighbour); the repro head's
/// output (0) the neighbour's repro cross, a Sel-Sync output (1) its record head's. Two
/// tapes of a group on one track are refused.
pub fn crosstalk_pairs(
    els: &[&MediumElement],
    first_row: usize,
) -> Result<Vec<(usize, usize, usize)>, String> {
    let mut rows = Vec::with_capacity(els.len());
    let mut row = first_row;
    for e in els {
        rows.push(row);
        row += e.outs().len();
    }
    let track = |e: &MediumElement| match e {
        MediumElement::Tape(t) => t
            .medium
            .crosstalk
            .as_ref()
            .map(|x| (x.group.clone(), x.track)),
        _ => None,
    };
    let mut pairs = Vec::new();
    for (i, a) in els.iter().enumerate() {
        let Some((ga, ta)) = track(a) else { continue };
        for (j, b) in els.iter().enumerate() {
            let Some((gb, tb)) = track(b) else { continue };
            if i == j || ga != gb {
                continue;
            }
            if ta == tb {
                return Err(format!(
                    "tape: {} and {} are both track {ta} of {ga}",
                    a.name(),
                    b.name()
                ));
            }
            if ta.abs_diff(tb) == 1 {
                for o in 0..a.outs().len() {
                    pairs.push((rows[i] + o, j, o));
                }
            }
        }
    }
    Ok(pairs)
}

/// A medium running beside the circuit at the step rate.
#[derive(Debug)]
pub enum Medium {
    Plate(Box<crate::plate::Medium>),
    Spring(Box<crate::spring::Medium>),
    Tape(Box<TapeMedium>),
    Harp(Box<crate::harp::Medium>),
    Clav(Box<ClavMedium>),
    Nova(Box<crate::novachord::Medium>),
    Nickel(Box<crate::nickel::Medium>),
}

/// A Clavinet's strings and their last outputs (centre, bridge, bridge negated).
#[derive(Debug)]
pub struct ClavMedium {
    pub strings: crate::clavinet::Medium,
    last: [f64; 3],
}

impl ClavMedium {
    fn push(&mut self) -> f64 {
        let [c, b] = self.strings.push();
        self.last = [c, b, -b];
        c
    }
}

impl Medium {
    /// The medium at step rate fs; `noise_seed`: the circuit's, if its noise is on.
    pub fn new(el: &MediumElement, fs: f64, noise_seed: Option<u64>) -> Result<Medium, String> {
        Ok(match el {
            MediumElement::Plate(p) => Medium::Plate(Box::new(crate::plate::Medium::new(p, fs))),
            MediumElement::Spring(p) => Medium::Spring(Box::new(crate::spring::Medium::new(p, fs))),
            MediumElement::Tape(t) => Medium::Tape(Box::new(TapeMedium {
                tape: t.clone(),
                stream: TapeMedium::stream(t, fs, noise_seed)?,
                fs,
                noise_seed,
                origin: 0,
                gpu: false,
                fields: Vec::new(),
                emf: Vec::new(),
                readouts: Default::default(),
            })),
            MediumElement::Harp(h) => Medium::Harp(Box::new(crate::harp::Medium::new(h, fs))),
            MediumElement::ClavStrings(c) => Medium::Clav(Box::new(ClavMedium {
                strings: crate::clavinet::Medium::new(c, fs)?,
                last: [0.0; 3],
            })),
            MediumElement::NovaKeys(k) => {
                Medium::Nova(Box::new(crate::novachord::Medium::new(k, fs)?))
            }
            MediumElement::NickelKeys(k) => {
                Medium::Nickel(Box::new(crate::nickel::Medium::new(k, fs, noise_seed)?))
            }
        })
    }

    /// Start at sample `k0` of a longer run (`Options::origin_samples`): a tape's
    /// transport and grain; the other media don't depend on time alone. Before the first
    /// push.
    pub fn set_origin(&mut self, k0: u64) -> Result<(), String> {
        if let Medium::Tape(m) = self {
            m.origin = k0;
            m.stream.set_origin(k0)?;
        }
        Ok(())
    }

    /// A tape's recording kernel on the GPU (`Options::tape_gpu`; TAPE_SPEED_PLAN.md P5).
    /// Before the first push; the other media have none.
    pub fn set_tape_gpu(&mut self, gpu: bool) -> Result<(), String> {
        if let Medium::Tape(m) = self {
            m.gpu = gpu;
            m.stream.set_gpu(gpu)?;
        }
        Ok(())
    }

    /// The sensed voltage at this sample (and a tape's capstan supply, if it has one);
    /// the output at the next. A tape with the literal bias takes it as its every sample
    /// over the step (the DC point's).
    pub fn push(&mut self, v: f64, supply_hz: Option<f64>) -> f64 {
        match self {
            Medium::Plate(m) => m.push(v),
            Medium::Spring(m) => m.push(v),
            Medium::Tape(m) => {
                let k = m.stream.substeps();
                m.push(std::iter::repeat_n(v, k), supply_hz)
            }
            Medium::Harp(m) => m.push(),
            Medium::Clav(m) => m.push(),
            Medium::Nickel(m) => m.push(),
            Medium::Nova(_) => panic!("the Novachord's keys sense many nodes: push_senses"),
        }
    }

    /// The senses of a medium of many ([`MediumElement::senses`], in its order) at this
    /// sample; its first output at the next.
    pub fn push_senses(&mut self, vs: &[f64]) -> f64 {
        match self {
            Medium::Nova(m) => m.push(vs),
            _ => panic!("a medium of one sense"),
        }
    }

    /// The cross EMF of the last push for output j: what a head beside this tape's
    /// track reads of it, the repro head (0) or the record head (1, Sel-Sync) (a tape with
    /// crosstalk; 0 for every other medium).
    pub fn cross(&self, j: usize) -> f64 {
        match self {
            Medium::Tape(m) => {
                let r = &m.readouts;
                let v = if j == 0 { &r.cross } else { &r.sync_cross };
                v.first().copied().unwrap_or(0.0)
            }
            _ => 0.0,
        }
    }

    /// Its outputs (one but a Clavinet's strings: three; a tape with Sel-Sync: two).
    pub fn outs(&self) -> usize {
        match self {
            Medium::Clav(_) => 3,
            Medium::Nova(m) => m.outs(),
            Medium::Tape(m) if m.tape.sync_out.is_some() => 2,
            _ => 1,
        }
    }

    /// Output j's value after the last push (j = 0: the push's own).
    pub fn output(&self, j: usize) -> f64 {
        match self {
            Medium::Clav(m) => m.last[j],
            Medium::Nova(m) => m.output(j),
            Medium::Tape(m) if j == 1 => m.readouts.sync.first().copied().unwrap_or(0.0),
            _ => panic!("a medium of one output"),
        }
    }

    /// Samples sensed per step (a tape with the literal bias: its `bias_substeps`; else 1).
    pub fn substeps(&self) -> usize {
        match self {
            Medium::Plate(_)
            | Medium::Spring(_)
            | Medium::Harp(_)
            | Medium::Clav(_)
            | Medium::Nova(_)
            | Medium::Nickel(_) => 1,
            Medium::Tape(m) => m.stream.substeps(),
        }
    }

    /// The sensed voltages over a step, [`Medium::substeps`] of them (a multi-rate part's,
    /// `partition.rs`); the output at the next sample.
    pub fn push_batch(&mut self, vs: &[f64], supply_hz: Option<f64>) -> f64 {
        match self {
            Medium::Plate(m) => m.push(*vs.last().expect("a sample")),
            Medium::Spring(m) => m.push(*vs.last().expect("a sample")),
            Medium::Tape(m) => m.push(vs.iter().copied(), supply_hz),
            Medium::Harp(m) => m.push(),
            Medium::Clav(m) => m.push(),
            Medium::Nickel(m) => m.push(),
            Medium::Nova(_) => panic!("the Novachord's keys sense their own part"),
        }
    }

    /// A keyboard's event at step `at` (a harp's or a Clavinet's; other media have no
    /// keys).
    pub fn queue_note(&mut self, at: usize, ev: NoteEvent) {
        match self {
            Medium::Harp(m) => m.queue(at, ev),
            Medium::Clav(m) => m.strings.queue(at, ev),
            Medium::Nova(m) => m.queue(at, ev),
            Medium::Nickel(m) => m.queue(at, ev),
            _ => {}
        }
    }

    /// Every keyboard event up to step `at` is queued (the keys' media render that far
    /// ahead).
    pub fn notes_known_until(&mut self, at: usize) {
        match self {
            Medium::Harp(m) => m.known_until(at),
            Medium::Clav(m) => m.strings.known_until(at),
            Medium::Nickel(m) => m.known_until(at),
            _ => {}
        }
    }

    /// Whether it is played by keys (a harp, a Clavinet's strings, the Novachord's or
    /// the Nickel Organ's keys).
    pub fn has_keys(&self) -> bool {
        matches!(
            self,
            Medium::Harp(_) | Medium::Clav(_) | Medium::Nova(_) | Medium::Nickel(_)
        )
    }

    /// New values mid-run. A plate keeps ringing; tape with the same medium keeps its
    /// recording (a new sense scale only; a reduced medium's new bias records from the
    /// next block on: BIAS as a knob), and a changed medium starts on erased tape.
    /// A medium of another kind is a change of structure.
    pub fn update(&mut self, el: &MediumElement) -> Result<(), String> {
        match (self, el) {
            (Medium::Plate(m), MediumElement::Plate(p)) => m.update(p),
            (Medium::Spring(m), MediumElement::Spring(p)) => m.update(p),
            (Medium::Tape(m), MediumElement::Tape(t)) => {
                let old = &m.tape.medium;
                let same_but_bias = t.medium.reduced.is_some()
                    && t.medium.hg_bias_a_m != old.hg_bias_a_m
                    && crate::tape_stream::TapeParams {
                        hg_bias_a_m: old.hg_bias_a_m,
                        ..(*t.medium).clone()
                    } == **old;
                if t.name != m.tape.name || (t.medium != *old && !same_but_bias) {
                    m.stream = TapeMedium::stream(t, m.fs, m.noise_seed)?;
                    m.stream.set_origin(m.origin)?;
                    m.stream.set_gpu(m.gpu)?;
                } else if same_but_bias {
                    m.stream.set_bias(t.medium.hg_bias_a_m)?;
                }
                m.tape = t.clone();
            }
            // A harp has no knobs: the same one plays on, another is a change of structure.
            (Medium::Harp(m), MediumElement::Harp(h)) => {
                if !m.same(h) {
                    return Err("a harp changed".into());
                }
            }
            // Nor have the strings (the rockers and the volume are the circuit's).
            (Medium::Clav(m), MediumElement::ClavStrings(c)) => {
                if !m.strings.same(c) {
                    return Err("the strings changed".into());
                }
            }
            // The keys play on through MELLOW; anything else is another instrument.
            (Medium::Nova(m), MediumElement::NovaKeys(k)) => {
                if !m.same(k) {
                    return Err("the keys changed".into());
                }
                m.update(k);
            }
            // SUSTAIN and POLARIZE play on; anything else is another organ.
            (Medium::Nickel(m), MediumElement::NickelKeys(k)) => {
                if !m.same(k) {
                    return Err("the keys changed".into());
                }
                m.update(k);
            }
            _ => return Err("a medium changed kind".into()),
        }
        Ok(())
    }
}
