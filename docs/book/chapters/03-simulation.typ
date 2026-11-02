#import "../style.typ": *

#part[Simulating a Circuit][
  How a schematic becomes equations, how a computer steps them through time, how it gets
  fast enough to play, and how we know the answers are right.
]

= From Schematic to Equations

#sketch[
  *The reader leaves knowing:* that Kirchhoff's laws at every node give a system of
  equations; nodal analysis in pictures; that tubes and iron make the equations nonlinear;
  the circuit file and its intermediate representation (IR).
]

== One equation per node
#sketch[Nodal analysis on a three-node example, then what changes with a voltage source (MNA) in words.]

#deeper("modified nodal analysis")[$G v + C (d v) / (d t) = i(t)$, plus device currents $i_"dev"(v)$.]

== Circuit files
#sketch[
  - A circuit as a YAML file of sourced values, devices and parts (macros); the builder
    expands it into the IR; Python and Rust read the same IR.
  - Show an excerpt of `config/circuits/tube_synth.yaml` with a `source` field.
]

#incode("config/circuits/", "varimu/circuit/builder.py", "varimu/circuit/ir.py", "crates/circuitsim/src/ir.rs")

== Nonlinear parts
#sketch[Tubes, diodes and cores make the equations curve; Newton's method as "guess, check the slope, improve" with a picture.]

= Stepping Through Time

#sketch[
  *The reader leaves knowing:* time-stepping (Euler, trapezoidal, higher-order methods);
  stiffness; why trapezoidal warps high frequencies; error control; what "converged
  solution" means as a reference.
]

== Euler's step and its cousins
#sketch[
  - Approximating change over a small step; backward versus forward; trapezoidal.
  - Real example: trapezoidal put the 670's transformer resonance 0.8 dB off at 20 kHz;
    production uses ESDIRK4 at 2x (CLAUDE.md, fixed-step engine accuracy).
]

== Stiffness and error control
#sketch[Fast and slow things in one circuit (a 3.84 MHz bias and a 7 s heater lag); substeps where diodes switch.]

= Fast Enough to Play

#sketch[
  *The reader leaves knowing:* why a naive simulator is 25-40x slower than real time
  (ngspice on the 670); nodal DK (do the linear work once, Newton only on the device
  ports); tables for tubes; splitting a circuit into threads at its stiff supply rails;
  draft versus production.
]

== Nodal DK
#sketch[Fold the linear part into precomputed responses; Newton on the devices only. Numbers: ngspice 20.6x real time against DK 3.3x on the same burst.]

== Partitions and threads
#sketch[
  - A shared node owned by one part, seen by the others one sample late; only across
    capacitor-held rails.
  - The synth on six threads (VCA, resonance pair, filter, oscillator, LFO, supplies).
  - Multi-rate parts: a section on its own thread at many steps per sample (the 351's bias).
]

#todo-figure([The synth's partition: which section runs on which thread.], from: "config/circuits/tube_synth.yaml (partition) and panel::Device::partition")

== Two qualities
#sketch[Draft to play, production to render the take; a take stored as its events; the native app's production render equal to Python's bit for bit.]

#incode("crates/circuitsim/src/dk.rs", "crates/circuitsim/src/partition.rs", "crates/varimu-app/")

= Keeping Ourselves Honest

#sketch[
  *The reader leaves knowing:* the project's hard rules and why each exists; how a
  simulation can be wrong in ways that still sound fine.

  - Every value has a source (datasheet, web, or marked provisional). Nothing invented passes as data.
  - Physical parameters only: no EQ curves or saturation knobs.
  - One coupled simulation: audio path, controls and supply in one netlist.
  - Two implementations per device model, tested against each other; ngspice as the independent check.
  - Reproducible from (parameters, signal, settings, code version); seeded randomness.
  - Loudness-matched listening.
  - A short story to end the part: the 670 experiment. Units built with realistic part
    tolerances couldn't be told apart in blind A/B until the differences were exaggerated
    6-8x. A lesson about what physics is audible, and why an instrument (where cents are
    audible) is a better place to hear it.
]

#report-figure("/reports/slice/agreement.png", [Agreement between the fast engine and the reference simulator on the 670.])
