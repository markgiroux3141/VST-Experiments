//! Media beside the circuit (a plate, `crate::plate`; tape, `crate::tape_stream`): each
//! senses a voltage in the circuit after every sample and drives its `out` node at the
//! next one, like a control input ([`crate::mna::Mna::media`]).

use crate::ir::{Plate, Tape};

/// A medium's element in the IR.
#[derive(Debug, Clone, PartialEq)]
pub enum MediumElement {
    Plate(Plate),
    Tape(Tape),
}

impl MediumElement {
    pub fn name(&self) -> &str {
        match self {
            MediumElement::Plate(p) => &p.name,
            MediumElement::Tape(t) => &t.name,
        }
    }

    pub fn out(&self) -> &str {
        match self {
            MediumElement::Plate(p) => &p.out,
            MediumElement::Tape(t) => &t.out,
        }
    }

    /// The sense's (positive, negative) nodes.
    pub fn sense(&self) -> (&str, &str) {
        match self {
            MediumElement::Plate(p) => (&p.sense_pos, &p.sense_neg),
            MediumElement::Tape(t) => (&t.sense_pos, &t.sense_neg),
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
    /// Scratch: a push's fields and its EMF.
    fields: Vec<f64>,
    emf: Vec<f64>,
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
        crate::tape_stream::TapeStream::build(&t.medium, fs, grain, seed.unwrap_or(0))
    }

    /// Push sensed voltages (one, or the literal bias's samples per push) as fields; the
    /// EMF at the next sample.
    fn push(&mut self, vs: impl Iterator<Item = f64>) -> f64 {
        let k = self.tape.h_per_v;
        self.fields.clear();
        self.fields.extend(vs.map(|v| k * v));
        self.emf.clear();
        self.stream
            .push_many(&self.fields, &mut self.emf)
            .expect("the tape's blocks are recorded before the repro head reads them");
        self.emf[0]
    }
}

/// A medium running beside the circuit at the step rate.
#[derive(Debug)]
pub enum Medium {
    Plate(Box<crate::plate::Medium>),
    Tape(Box<TapeMedium>),
}

impl Medium {
    /// The medium at step rate fs; `noise_seed`: the circuit's, if its noise is on.
    pub fn new(el: &MediumElement, fs: f64, noise_seed: Option<u64>) -> Result<Medium, String> {
        Ok(match el {
            MediumElement::Plate(p) => Medium::Plate(Box::new(crate::plate::Medium::new(p, fs))),
            MediumElement::Tape(t) => Medium::Tape(Box::new(TapeMedium {
                tape: t.clone(),
                stream: TapeMedium::stream(t, fs, noise_seed)?,
                fs,
                noise_seed,
                fields: Vec::new(),
                emf: Vec::new(),
            })),
        })
    }

    /// The sensed voltage at this sample; the output at the next. A tape with the literal
    /// bias takes it as its every sample over the step (the DC point's).
    pub fn push(&mut self, v: f64) -> f64 {
        match self {
            Medium::Plate(m) => m.push(v),
            Medium::Tape(m) => {
                let k = m.stream.substeps();
                m.push(std::iter::repeat_n(v, k))
            }
        }
    }

    /// Samples sensed per step (a tape with the literal bias: its `bias_substeps`; else 1).
    pub fn substeps(&self) -> usize {
        match self {
            Medium::Plate(_) => 1,
            Medium::Tape(m) => m.stream.substeps(),
        }
    }

    /// The sensed voltages over a step, [`Medium::substeps`] of them (a multi-rate part's,
    /// `partition.rs`); the output at the next sample.
    pub fn push_batch(&mut self, vs: &[f64]) -> f64 {
        match self {
            Medium::Plate(m) => m.push(*vs.last().expect("a sample")),
            Medium::Tape(m) => m.push(vs.iter().copied()),
        }
    }

    /// New values mid-run. A plate keeps ringing; tape with the same medium keeps its
    /// recording (a new sense scale only), and a changed medium starts on erased tape.
    /// A medium of another kind is a change of structure.
    pub fn update(&mut self, el: &MediumElement) -> Result<(), String> {
        match (self, el) {
            (Medium::Plate(m), MediumElement::Plate(p)) => m.update(p),
            (Medium::Tape(m), MediumElement::Tape(t)) => {
                if t.medium != m.tape.medium || t.name != m.tape.name {
                    m.stream = TapeMedium::stream(t, m.fs, m.noise_seed)?;
                }
                m.tape = t.clone();
            }
            _ => return Err("a medium changed kind".into()),
        }
        Ok(())
    }
}
