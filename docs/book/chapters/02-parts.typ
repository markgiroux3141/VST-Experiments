#import "../style.typ": *

#part[The Old Parts][
  Electricity from the beginning, then the three kinds of part this book lives on: the
  vacuum tube, iron and copper, and the power supply that feeds them all.
]

= Voltage, Current and the Passive Parts

#sketch[
  *The reader leaves knowing:* voltage, current, resistance and Ohm's law; power; what a
  capacitor and an inductor do (store energy, resist change); the RC low-pass as the first
  filter; frequency response.

  *Approach:* water analogies used once and then dropped; every idea grounded in a part
  from the synth or the 351.
]

== Charge, voltage and current
#sketch[Ohm's law; power as heat (why tubes need ratings); series and parallel.]

== Capacitors and inductors
#sketch[
  - A capacitor holds voltage, an inductor holds current; both make circuits depend on time.
  - The RC low-pass: a cutoff frequency, -6 dB per octave. The LC circuit: resonance, the
    seed of both the synth's filter and its oscillator.
]

#deeper("the RC cutoff")[$f_c = 1 / (2 pi R C)$, and the LC resonance $f_0 = 1 / (2 pi sqrt(L C))$.]

== Reading a schematic
#sketch[
  - Symbols, nodes, ground; the netlist as the same thing written as a list.
  - Show a small real schematic: the triode stage drawn in the project's editor
    (`triode_stage_drawn`), with its netlist beside it.
]

#todo-figure([The triode stage: drawing and netlist side by side.], from: "config/circuits/triode_stage_drawn.drawing.json (screenshot of varimu-app's Editor)")

= Circuits That Feed Themselves

#sketch[
  *The reader leaves knowing:* Kirchhoff's two laws; why every part of a device shares a
  power supply; rectifiers, reservoir capacitors, ripple and sag.

  *The point to land:* the power supply isn't a side detail. When the synth plays a chord,
  the supply sags and the pitch moves; the hum of a small reservoir is a sound in its own
  right (the RESERVOIR control). This is the reason for "one coupled simulation".
]

== Kirchhoff's laws
#sketch[Currents into a node sum to zero; voltages round a loop sum to zero. Everything later solves these.]

== From the mains to B+
#sketch[
  - Transformer, rectifier (vacuum diode, selenium), reservoir capacitor, choke, ripple.
  - Sag: a heavier load drops the rail. Example numbers from the synth: unregulated, the
    VCA's sag dropped held notes about 780 cents until the 6V6GT's screen got its own regulator.
  - Regulation with tubes (the 5651 reference), as used in the 670 and the synth.
]

#todo-figure([Rail voltage and pitch while a chord is held, with a small and a large reservoir.], from: "scripts/supply_study.py")

= The Vacuum Tube

#sketch[
  *The reader leaves knowing:* thermionic emission; the diode; the triode as a valve
  controlled by its grid; gain and plate curves; pentodes and variable-mu tubes; the
  heater and why a cold tube sounds different; how a datasheet becomes a model.
]

== Hot cathodes
#sketch[
  - Electrons boiled off a heated cathode; space charge; Child's law.
  - The heater's temperature matters: the project's HEATER control and cold start. Figure:
    warm-up.
]

#report-figure("/reports/tube_synth/heaters/warmup.png", [A tube warming up after power-on (the synth's cold start).])

== The triode
#sketch[
  - The grid as a tap on the flow; amplification factor mu; plate curves read like a map.
  - A one-tube amplifier stage, its gain and how it distorts (soft, mostly even harmonics).
]

== Pentodes, beam tetrodes and variable-mu
#sketch[
  - Screen grids; the 6V6GT; the 6386 whose gain falls smoothly with bias (the
    compressor's and the synth's VCA).
]

== From datasheet to model
#sketch[
  - Koren's triode equations in words; fitting to digitized datasheet curves.
  - Show the fit against the sheet. Every value has a source: introduce that rule here.
]

#report-figure("/reports/devices/6v6gt_fit.png", [The 6V6GT model against its datasheet curves.])

#deeper("Koren's triode")[
  $E_1 = V_p / K_p log(1 + exp(K_p (1 / mu + V_g / sqrt(K_"vb" + V_p^2))))$, plate current
  $I_p = E_1^(E_x) / K_(g 1)$ (sign handling omitted).
]

= Iron, Copper and Hysteresis

#sketch[
  *The reader leaves knowing:* magnetic field (H) and flux density (B); permeability;
  saturation; hysteresis loops; transformers; the saturable reactor as an inductor you can
  tune with a current; and that two different models of hysteresis appear in this book for
  good reasons.
]

== Fields, flux and permeability
#sketch[Coils, cores, why iron multiplies inductance; B against H.]

== Hysteresis and saturation
#sketch[
  - The loop: iron remembers. Saturation: iron runs out.
  - Jiles-Atherton as a smooth model of a whole core (used for every transformer here).
  - Its weakness, which matters later: small loops ratchet (they creep instead of closing).
    That is why the tape uses Preisach (Part V).
]

#report-figure("/reports/transformers/t101.png", [A transformer simulated standalone: the 670's input transformer (T101).])

== Transformers
#sketch[Turns ratio, impedance, leakage, winding capacitance; why transformers colour sound at both ends of the spectrum.]

== The saturable reactor
#sketch[
  - A DC control winding pushes the core toward saturation, and the inductance the audio
    sees falls. An inductor tuned by a current: the heart of the synth's filter and its
    oscillator.
  - Show incremental permeability against DC bias.
]

#report-figure("/reports/tube_synth/incremental_permeability_mumetall.png", [Mumetall's incremental permeability under DC bias: the reactor's tuning curve.])
