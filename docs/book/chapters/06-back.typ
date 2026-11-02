#import "../style.typ": *

#set heading(numbering: none)

= Where This Goes Next

#sketch[
  - What the two machines showed: which physics is audible (pitch, sag, saturation, grain)
    and which isn't (realistic tolerances in a compressor).
  - Built and not covered: the Fairchild 670, the Pultec EQP-1A, the Fender 5E3 through its
    speaker, the EMT 140 plate reverb, the drums prototype.
  - Next: the 351 as a slapback (the repro head fed back to the record input), a GPU for the
    tape's recording kernel, more machines.
  - How to try it: the repository and the native app (to write once that is public).
]

= Appendix A: A Maths Refresher

#sketch[Exponentials and logarithms, sines, derivatives as slopes, integrals as areas, matrices as tables of equations. Two pages, pictures first.]

= Appendix B: Glossary

#sketch[
  One line per term, with the chapter it is introduced in: anhysteretic, B+, bias,
  cents, DK, dBFS, flutter, gap loss, grid, hysteresis, IR, Jiles-Atherton, LUFS, MNA,
  Newton's method, Nyquist, partition, pentode, Preisach, remanence, saturable reactor,
  screen, THD, triode, ...
]

= Appendix C: Reproducing the Results

#sketch[
  Every figure with the command that makes it (from CLAUDE.md's Commands); the code version
  the book was built against (a git hash printed here automatically?).
]

= Sources

#sketch[
  A bibliography (Typst's `bibliography` with a `sources.yml`): datasheets (RCA, GE, Tung-Sol),
  the Ampex 351 manuals, 3M's Sound Talk bulletins, Jiles and Atherton (1986), Preisach,
  Mayergoyz, Bertram's _Theory of Magnetic Recording_, Karlqvist, Koren, Yeh and Smith on DK,
  the EMT 140 brochure.
]
