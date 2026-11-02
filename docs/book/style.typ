// The book's look: page, type, chapter and part openers, callouts.
//
// Build with the repo root as Typst's root, so figures can come straight from reports/:
//   typst compile --root ../.. book.typ build/varimu-book.pdf
// Hide the planning boxes for a reader's copy:
//   typst compile --root ../.. --input sketch=false book.typ build/varimu-book.pdf

#let accent = rgb("#b4541c") // a heater's glow
#let ink = rgb("#1f1d1a")
#let muted = rgb("#6b645c")
#let rule-color = rgb("#d8cfc4")

#let show-sketch = sys.inputs.at("sketch", default: "true") == "true"

// ---------------------------------------------------------------- callouts

#let _callout(label, tint, edge, body) = block(
  width: 100%,
  fill: tint,
  stroke: (left: 2pt + edge),
  inset: (x: 10pt, y: 8pt),
  radius: (right: 3pt),
  breakable: true,
)[
  #text(size: 7.5pt, weight: "bold", fill: edge, tracking: 0.1em, upper(label))
  #v(4pt, weak: true)
  #set text(size: 9.5pt)
  #set par(spacing: 0.8em)
  #body
]

// The plan for a chapter or section: shown while drafting, gone with --input sketch=false.
#let sketch(body) = if show-sketch {
  _callout("Sketch", rgb("#fff6d6"), rgb("#a07c00"), body)
}

// Optional maths for readers who want it; the main text never depends on it.
#let deeper(title, body) = _callout(
  "Going deeper: " + title,
  rgb("#eef2f6"),
  rgb("#3f5f7f"),
  body,
)

// A sound example from the audio companion.
#let listen(name, body) = _callout(
  "Listen: " + name,
  rgb("#f3efe8"),
  accent,
  body,
)

// Where an idea lives in the repository.
#let incode(..paths) = _callout(
  "In the code",
  rgb("#f1f1ef"),
  muted,
  paths.pos().map(p => raw(p)).join(linebreak()),
)

// A figure still to be made: what it shows and where its data comes from.
#let todo-figure(caption, from: none) = figure(
  block(
    width: 100%,
    height: 4.2cm,
    stroke: (paint: rule-color, thickness: 1pt, dash: "dashed"),
    radius: 3pt,
    inset: 10pt,
  )[
    #set align(center + horizon)
    #text(size: 9pt, fill: muted)[
      *Figure to make*\
      #if from != none [from #raw(from)]
    ]
  ],
  kind: image,
  caption: caption,
)

// An existing plot from reports/ (paths are from the repo root, e.g. "/reports/tape/x.png").
#let report-figure(path, caption, width: 100%) = figure(
  image(path, width: width),
  caption: caption,
)

// ---------------------------------------------------------------- parts

#let part(title, blurb) = {
  pagebreak(weak: true)
  counter("part").step()
  context {
    let n = counter("part").get().first()
    [#metadata((num: n, title: title)) <part>]
    v(28%)
    text(size: 10pt, weight: "bold", fill: accent, tracking: 0.3em)[PART #numbering("I", n)]
    v(10pt)
    text(size: 30pt, weight: "bold", fill: ink, title)
    v(14pt)
    line(length: 25%, stroke: 1.5pt + accent)
    v(14pt)
    block(width: 78%, text(size: 11pt, style: "italic", fill: muted, blurb))
  }
}

// ---------------------------------------------------------------- contents

#let contents() = {
  heading(level: 1, numbering: none, outlined: false)[Contents]
  context {
    let items = query(selector(<part>).or(heading.where(level: 1, outlined: true)))
    let in-body = false
    for it in items {
      let loc = it.location()
      let page-num = {
        let style = loc.page-numbering()
        if style == none { style = "1" }
        numbering(style, ..counter(page).at(loc))
      }
      if it.func() == metadata {
        v(12pt)
        link(loc, text(weight: "bold", fill: accent, tracking: 0.05em)[
          Part #numbering("I", it.value.num) #h(0.6em) #it.value.title
        ])
        v(2pt)
      } else {
        // A gap between the last part's chapters and the unnumbered back matter.
        if it.numbering != none { in-body = true } else if in-body { v(12pt); in-body = false }
        let num = if it.numbering != none {
          numbering(it.numbering, ..counter(heading).at(loc))
        }
        link(loc, grid(
          columns: (2.2em, 1fr, auto),
          column-gutter: 0.3em,
          text(fill: muted, if num != none { num }),
          [#it.body #box(width: 1fr, repeat[#h(3pt).#h(3pt)])],
          page-num,
        ))
        v(1pt)
      }
    }
  }
}

// ---------------------------------------------------------------- the template

#let book(title: none, subtitle: none, author: none, date: none, body) = {
  set document(title: title, author: author)
  set text(font: ("Libertinus Serif", "New Computer Modern"), size: 10.5pt, fill: ink, lang: "en")
  set par(justify: true, leading: 0.68em, spacing: 1.05em)
  show raw: set text(font: ("DejaVu Sans Mono",), size: 8.5pt)
  show link: set text(fill: ink)

  set page(
    width: 7in,
    height: 10in,
    margin: (inside: 24mm, outside: 19mm, top: 24mm, bottom: 22mm),
    numbering: "i",
    header: context {
      let p = here().page()
      let opens = query(heading.where(level: 1)).any(h => h.location().page() == p)
      let part-page = query(<part>).any(m => m.location().page() == p)
      if not opens and not part-page {
        let before = query(heading.where(level: 1).before(here()))
        if before.len() > 0 {
          set text(size: 8pt, fill: muted, tracking: 0.05em)
          let chapter = before.last()
          if calc.even(p) [#smallcaps(title) #h(1fr)] else [#h(1fr) #smallcaps(chapter.body)]
          v(-4pt)
          line(length: 100%, stroke: 0.4pt + rule-color)
        }
      }
    },
    footer: context {
      let p = here().page()
      let part-page = query(<part>).any(m => m.location().page() == p)
      if not part-page {
        set text(size: 8.5pt, fill: muted)
        set align(if calc.even(p) { left } else { right })
        counter(page).display()
      }
    },
  )

  set heading(numbering: "1.1")
  show heading: set text(hyphenate: false)
  show heading.where(level: 1): it => {
    pagebreak(weak: true)
    v(16%)
    if it.numbering != none {
      text(size: 10pt, weight: "bold", fill: accent, tracking: 0.25em)[
        CHAPTER #counter(heading).display("1")
      ]
      v(6pt)
    }
    text(size: 25pt, weight: "bold", it.body)
    v(10pt)
    line(length: 25%, stroke: 1.5pt + accent)
    v(26pt)
  }
  show heading.where(level: 2): it => block(above: 1.8em, below: 0.9em)[
    #set text(size: 13pt, weight: "bold")
    #if it.numbering != none {
      text(fill: accent, counter(heading).display())
      h(0.7em)
    }
    #it.body
  ]
  show heading.where(level: 3): set text(size: 11pt, style: "italic", weight: "regular")
  set figure(gap: 8pt)
  show figure.caption: set text(size: 9pt, fill: muted)

  // Title page
  page(numbering: none, header: none, footer: none)[
    #v(30%)
    #text(size: 34pt, weight: "bold", title)
    #v(8pt)
    #line(length: 30%, stroke: 2pt + accent)
    #v(10pt)
    #text(size: 14pt, style: "italic", fill: muted, subtitle)
    #v(1fr)
    #text(size: 11pt, author)\
    #text(size: 9pt, fill: muted, date)
    #if show-sketch {
      v(8pt)
      text(size: 8pt, fill: rgb("#a07c00"))[Working draft: yellow boxes are the plan, not the text.]
    }
  ]

  body
}
