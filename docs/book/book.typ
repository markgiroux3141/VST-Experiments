// The book: from first principles to a simulated tube synthesizer and tape machine.
// Build: see README.md in this folder.

#import "style.typ": *

#show: book.with(
  title: [Sound from Physics],
  subtitle: [Building a tube synthesizer and a tape machine from their parts, in simulation],
  author: "The varimu project",
  date: [Working draft, November 2026],
)

#include "chapters/00-front.typ"

#set page(numbering: "1")
#counter(page).update(1)
#counter(heading).update(0)

#include "chapters/01-sound.typ"
#include "chapters/02-parts.typ"
#include "chapters/03-simulation.typ"
#include "chapters/04-synth.typ"
#include "chapters/05-tape.typ"
#include "chapters/06-back.typ"
