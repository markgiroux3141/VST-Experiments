#import "../style.typ": *

#contents()

#set heading(numbering: none)

= Preface <preface>

#sketch[
  *Purpose:* say what the book is, who it is for and where it ends up, in about two pages.
  The three paragraphs below are a first try at the voice: plain, concrete and a bit
  enthusiastic, with no hype. Change them if the tone is wrong.
]

Most software that sounds "analog" is a good impression. Someone listened carefully to a
piece of old gear, measured it, and wrote a program that does something similar: a curve
that bends loud signals, a filter that dulls the highs, a little added noise. It works,
and some of it is excellent. This book is about a different way of doing it.

We don't imitate the sound. We simulate the parts. A vacuum tube, an iron-cored
transformer, a capacitor and the power supply that feeds them are each modelled from
their physics and their datasheets, wired together exactly as a schematic says, and
solved as one circuit, ninety-six thousand times a second. Whatever warmth, grit or
wobble comes out, nobody put it there. It falls out of the parts.

The book ends with two machines built this way. One is a synthesizer that never existed:
an instrument made only from parts available before the transistor, including
saturable-reactor filters, a light bulb that steadies a vibrato and power-supply sag that
pulls the pitch when you lean on a chord. The other is an Ampex 351 tape recorder from the
1950s. Its tape is simulated as a slab of magnetic particles, recorded with the machine's
own high-frequency bias just as the real heads did it. Getting there takes some physics,
some electronics and some numerical methods. This book assumes none of them.

== Who this book is for

#sketch[
  - Musicians and producers who are curious how analog gear really works and are willing to
    meet a little algebra.
  - Programmers who know audio plugins but not circuits, or circuits but not simulation.
  - Assumed: secondary-school algebra, a feel for what a graph says. Not assumed:
    calculus, electronics, physics beyond school.
  - Calculus and matrices appear only in "Going deeper" boxes; the main text never needs them.
]

== How to read it

#sketch[
  - Map of the five parts (a one-page diagram: sound -> parts -> simulation -> synth / tape).
  - Readers who know electronics can skip Part II; readers who know DSP can skim Part I.
  - The callouts: #text(fill: accent)[Listen] (the audio companion), Going deeper (maths),
    In the code (where it lives in the repository).
  - The audio companion: where the sound examples live (open: a web page with a QR code per
    example? the repository's `reports/`?).
]

#listen("an example")[
  This is what a sound-example callout looks like. Each one names a file in the audio
  companion and says what to listen for.
]

#deeper("an example")[
  This is a maths box. For example: a capacitor's current is $i = C (d v) / (d t)$.
]

#incode("varimu/devices/core.py", "crates/circuitsim/src/dk.rs")

