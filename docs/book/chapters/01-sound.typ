#import "../style.typ": *

#part[Sound and Signals][
  What sound is, how we describe it and how a computer holds it. Everything later is
  judged by ear and by these measurements.
]

= What Sound Is

#sketch[
  *The reader leaves knowing:* sound is pressure changing in time; a waveform; frequency
  and pitch; harmonics and timbre; why we use decibels; that "the same loudness" is
  harder than it sounds.

  *Bridge to what follows:* every effect in this book (saturation, sag, flutter) is
  described in these terms: which harmonics appear, how much, and when.
]

== Pressure in time

#sketch[
  - Air pushed and pulled; a microphone or speaker turns pressure into voltage and back.
  - A waveform is a graph of one number against time. A sine wave as the simplest case.
  - Hook: the 5E3 guitar amp's output in this project is literally pascals at one metre
    (C3's speaker model), a nice concrete example to come back to.
]

== Frequency, pitch and harmonics

#sketch[
  - Period and frequency (Hz); pitch as perceived frequency; octaves as doubling; cents.
  - Fourier's idea, without equations: any periodic wave is a sum of sines at whole-number
    multiples. Harmonics give timbre.
  - The spectrum as a second way to look at a sound (side by side: a sawtooth's waveform and
    spectrum).
  - Why cents matter for the synth: two oscillators a few cents apart beat audibly.
]

#todo-figure([A sine, a square and a sawtooth: waveforms and spectra.], from: "a small script, new")

== Decibels and loudness

#sketch[
  - Ratios, not differences; 6 dB is a doubling of amplitude; dBFS for digital level
    (0 dBFS = a sine of amplitude 1, the project's convention).
  - Distortion measured as harmonics: THD, as a number and as a spectrum.
  - Loudness isn't level: louder sounds "better" to everyone, so every comparison here is
    matched in loudness (LUFS). Set up the rule "loudness lies" from the project's hard rules.
]

#deeper("decibels")[
  $L = 20 log_10 (A / A_"ref")$ for amplitudes, $10 log_10$ for powers.
]

= Sound in a Computer

#sketch[
  *The reader leaves knowing:* sampling, the Nyquist frequency, aliasing (and why
  distortion makes it worse), oversampling, and the time budget of real-time audio.

  *Bridge:* aliasing is the reason the synth and the tape machine run faster inside than
  the audio rate, and the real-time budget is the reason there are two qualities, draft
  and production.
]

== Samples

#sketch[
  - A waveform measured at regular instants; sample rate; this project's 96 kHz.
  - Bits and noise floor, briefly (floats in practice).
]

== Nyquist and aliasing

#sketch[
  - Nothing above half the sample rate can be represented; it folds back as a different pitch.
  - Distortion creates harmonics, possibly above Nyquist, which fold into inharmonic junk.
    Show a hard-clipped sine with and without oversampling.
  - Real example: the 5E3 at draft-1x aliased at -8 dB relative to the harmonics, which is why
    it plays at draft-2x (CLAUDE.md, B9 step 5).
]

#todo-figure([Aliasing: a clipped 5 kHz sine at 48 kHz versus 4x oversampled.], from: "varimu/measure/amp_suite.py (aliasing per quality)")

== Real time

#sketch[
  - Blocks and buffers; latency; a dropout when one block takes longer than its playing time.
  - "x real time" as this book's unit of speed (1.0 = just keeps up).
  - Rendering versus playing: a print can take as long as it likes.
]
