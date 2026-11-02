#import "../style.typ": *

#part[A Synthesizer That Never Existed][
  An instrument built only from parts available before the transistor: tubes,
  transformers, saturable reactors, lamps and selenium. Every sound it makes comes from
  those parts.
]

= The Idea

#sketch[
  *The reader leaves knowing:* the rules of the instrument and why each makes it
  interesting.

  - No transistors, op-amps or ICs; every part existed and is used within its ratings.
  - Drift is character: no tuning compensation; drift only from modelled physics, never an
    added wobble.
  - Draft to play, production to render the take.
  - History: the Hammond Novachord, the Trautonium, the Clavioline, Metasonix today.
  - Why an instrument and not another compressor: pitch makes small physics audible (link
    back to the 670 story).
  - The block diagram: keyboard -> oscillator -> filter -> VCA, envelope and LFO, one supply.
]

#todo-figure([The voice as a block diagram, every block labelled with its tubes.], from: "config/circuits/tube_synth.yaml")

#incode("docs/TUBE_SYNTH_PLAN.md", "docs/SYNTH_IDEAS.md", "config/circuits/tube_synth.yaml")

= The Filter: An Inductor Tuned by Current

#sketch[
  *The reader leaves knowing:* how a saturable-reactor low-pass works and what it sounds
  like; how the circuit around it controls it.

  - Two cores, control windings in anti-series so the audio cancels in the control circuit.
  - A 6V6GT sets the control current (the cutoff); a 12AX7 Q multiplier makes resonance; a
    6386 VCA; its own 6X4 and selenium supply.
  - What the iron adds: the cutoff moves with the signal itself; resonance that saturates.
  - The open problem told honestly: Jiles-Atherton's ratcheting minor loops (S1's status).
]

#listen("the reactor filter swept")[A sawtooth through the reactor low-pass while the CUTOFF knob turns.]

= The Oscillator

#sketch[
  *The reader leaves knowing:* how the reactor-tuned LC oscillator makes a pitch, why it
  needs measured tuning tables, and where its drift comes from.

  - Three prototypes measured; the reactor-tuned LC one works (the diode-timed
    multivibrator doesn't run cleanly yet: say so).
  - Range: LOW 18.8-789 Hz, HIGH 26-1736 Hz; AUTO switches per key.
  - Keys to pitch through a measured tuning table, because the reactor's law isn't
    exponential.
  - The glide that comes for free (the core's ratchet: 0.57 s) and the GLIDE control.
  - Drift: heater, flicker noise, supply sag. Figure: pitch noise.
]

#report-figure("/reports/tube_synth/vco/lc.png", [The reactor-tuned LC oscillator: frequency against control.])
#report-figure("/reports/tube_synth/noise/pitch.png", [Pitch wander from the tubes' own noise.])

= A Voice

#sketch[
  *The reader leaves knowing:* how a key becomes a note: the keyboard bus, the envelope,
  the VCA, and the touch controls.

  - Gate and pitch as control inputs (the circuit's `cv_inputs`).
  - The ADSR from tubes: a 12AX7 comparator ends the attack, latched by two 12AU7
    inverters; 6AL5 clamps; fragile at the extremes when the rails sag (kept, as character).
  - A push-pull 6386 VCA.
  - Velocity, aftertouch (PRESSURE) and KEY TRACK as voltages on real wires.
]

#listen("envelope shapes")[Pluck, organ, brass and a soft pad from the same voice.]

= Colour and Movement

#sketch[
  *The reader leaves knowing:* the modulation and the "physical condition" controls.

  - The LFO: a Wien bridge held steady by a \#327 pilot lamp (its tungsten's temperature
    as a circuit node); 0.08-19 Hz, and an AUDIO range up to about 1.9 kHz. VIBRATO and WOBBLE.
  - The ring modulator: a selenium diode ring between two mumetall transformers.
  - HEATER: run the tubes cool, out of rating below 0.9.
  - RESERVOIR: shrink the supply's capacitor and hear hum growl, then the pitch warble.
  - Noise: Johnson, shot and flicker noise in every part (B5).
  - The principle: realistic first, then bend a real part out of range as a control.
]

#listen("the reservoir")[The same phrase at 40, 6 and 2 uF.]

= Playing It

#sketch[
  *The reader leaves knowing:* what it takes to play this live and what it costs.

  - The native app, a MIDI keyboard, draft-2x; the voice on six threads, about 62% load.
  - Recording a take as events, rendering at production.
  - A coda: the tube kick drum, built from the synth's oscillator.
]

#todo-figure([Load per thread while a chord is held.], from: "examples/play.rs --hold NOTE")
