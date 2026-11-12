# The record head: a literature study on why No. 21's bias curves are wider than the model's

2026-11-12, overnight research (no code changed). The question, handed over by two studies of
the same night: the tape model's AC-bias curves are too narrow against 3M Sound Talk No. 21
(Ampex 300, 15 ips, 70 kHz bias, 0.002" record gap, #111): the rise from -20 dB to the peak
spans ~7.1 dB of bias in the model against 9.4 dB in No. 21, and the 15k - 1k spread at
over-bias is -6.6 dB against -10.4. The particle bench (`TAPE_PARTICLES.md`, worktree
agent-a7931fefe46225e86: interactions don't widen the rise) and the over-bias study
(`TAPE_PLAN.md` "Over-bias options", worktree agent-a6031a9ea9de4d671: a mean field doesn't
help, the head's current law is linear to ~1%, the astroid helps the rise but overshoots 15
kHz) both name the record head's field (profile, depth dependence, efficiency at the bias
frequency) as the next suspect. The particle literature is in `TAPE_PARTICLE_RESEARCH.md`.

Source tags as in `TAPE_PARTICLE_RESEARCH.md`: **[read]** = read in the source this session
(page given); **[abstract]** = only an abstract or index record; **[memory]** = recalled, not
checked; `provisional:` = no source, a range from physics; **[derived]** = computed here from
the cited inputs (formula and method given; a few seconds of numpy, nothing in the repo).

**Short answer.** Section 1 has the one result worth acting on: the model's head is
Karlqvist's (a linear potential across the gap mouth), and **the whole 12.7 um coating of No.
21 lies within 0.26 gap lengths of a 51 um gap's face, the region where Karlqvist is known to
be wrong**. The exact field of the same head (infinitely permeable poles, square corners:
Westmijze's geometry, solved here by its Schwarz-Christoffel map) is 17% weaker at the gap's
centre and up to 1.4x stronger near the corners at the coating's top micron. Measured as the
range of bias current that sweeps the "biased depth" through the coating, it widens the
geometric part of the rise by **+1.3 to +4.2 dB** (depending on which field component the
particles answer to), bracketing the missing ~2.3 dB, with no free parameter. It does **not**
change the over-bias 15 kHz loss: past Hg ~ 2 H_sw the exact and Karlqvist trailing contours
sit within ~1 um of each other. The over-bias loss stays a medium question (the astroid,
orientation, the coating's perpendicular self-field). Nothing in the head's current law,
eddy currents or saturation stretches the bias axis non-uniformly at No. 21's levels.

---

## 1. The field of a long-gap head near its face: exact against Karlqvist

### 1.1 What the model uses

`varimu/devices/tape.py` (module docstring and `head_hx`, `head_field`, `head_hx_spectrum`):
the head face carries the scalar potential +phi0/2 on one pole face, **falling linearly across
the gap g**, -phi0/2 on the other, finite poles p relaxing over r; the field above is the
Poisson integral of that surface potential. Near the gap (p = 3 mm >> g) this is Karlqvist's
field (Karlqvist, Trans. Roy. Inst. Technol. Stockholm No. 86, 1954, as cited by Tannous
2015, ref. 1 [read]):

    Hx = (Hg / pi) [atan((x + g/2) / y) - atan((x - g/2) / y)]
    Hy = -(Hg / 2 pi) ln[((x + g/2)^2 + y^2) / ((x - g/2)^2 + y^2)]

Its spectrum is the model's `g e^{-|k|y} [sinc(kg/2) - ...]`.

### 1.2 What the literature says about its accuracy

- Karlqvist assumes a constant field across the gap mouth; the exact problem (conformal
  mapping, Fourier methods) satisfies the edge condition at the corners, where the field is
  singular as r^(-1/3) (Tannous, "The Karlqvist approximation revisited", arXiv:1504.07625,
  2015, Sec. V and Fig. 9: the edge fields Hx(a, y), Hy(a, y) scale as y^(-1/3) [read]; Fig. 8
  plots Hx, Hy at y/a = 0.1, 0.01, 0.001 with a the half-gap [read]).
- Szczech, Perry & Palmquist, "Improved field equations for ring heads", IEEE Trans. Magn. 19,
  1740 (1983), DOI 10.1109/TMAG.1983.1062659: equations checked on a large-scale ring head that
  "remain accurate very close to the head surface, unlike Karlqvist's" [abstract].
- A search summary attributes to a 1987 study that Karlqvist's error is negligible at a
  spacing of about one gap length and significant at ~0.2 g or less [abstract, via search
  summary; the paper itself was not identified: treat as unverified].
- McCary & Tandon, IEEE Trans. Magn. 17, 3268 (1981): Davy's limiting form of the conformal
  solution has errors roughly complementary to Karlqvist's; their average is much better
  [abstract].
- The exact solutions: Westmijze, Philips Res. Rep. 8 (1953) (the "Westmijze head",
  semi-infinite poles with a deep gap; not found online, CRL holds the 89-page reprint: catalog
  record [read]); Fan, IBM J. Res. Dev. 5, 321 (1961) (typos corrected by Huang & Deng, IEEE
  Trans. Magn. 22, 1305 (1986), per Tannous ref. 4 [read]); Matzner & Shtrikman, "Some improved
  formulas for the Westmijze head", IEEE Trans. Magn. 33, 820 (1997); Wilton, Middleton & Aziz,
  "Exact harmonic coefficients for a magnetic ring head", IEEE Trans. Magn. 35, 2043 (1999)
  (Tannous refs. 7-8 [read]; the papers not opened).

**No. 21's geometry is the bad case**: the coating spans y = d to d + delta = 0.5 to 13.2 um
(the model's spacing plus #111's 12.7 um, Eilers [read via TAPE_PARTICLE_RESEARCH.md]), i.e.
y/g = 0.01 to 0.26 for g = 51 um. Every layer is inside the region where Karlqvist errs.

### 1.3 The exact field of the same head, computed [derived]

The deep-gap ring head with infinitely permeable poles and square corners (the gap running to
infinite depth, the faces flat; Westmijze's geometry) maps from the upper w half-plane by
Schwarz-Christoffel, dz/dw = (g / pi) sqrt(w^2 - 1) / w:

    z(w) = g/2 + (g / pi) [ s(w) - arccos(1/w) ],   s(w) = sqrt(w - 1) sqrt(w + 1)
    Hx - i Hy = i Hg / s(w)

(w = +-1 are the corners, w -> 0 the gap's depth, where Hx -> Hg; checked: w in (0, 1) lands
on the gap wall x = g/2, w > 1 on the pole face, w = i above the gap's centre). Each field
point was found by Newton on z(w) = x + iy. g = 51 um throughout, fields per unit deep-gap
field Hg.

**The maximum field a layer sees in passing** (the bias amplitude that decides whether the
layer is biased at all; `max|H|` the magnitude, `max|Hx|` the longitudinal part alone):

| y (um) | exact max\|H\| | exact max\|Hx\| | Karlqvist max\|H\| | Karlqvist max\|Hx\| |
|---|---|---|---|---|
| 0.5 (the surface at 0.5 um spacing) | 2.17 | 1.46 | 1.57 | 0.99 |
| 1.0 | 1.70 | 1.19 | 1.37 | 0.98 |
| 2.0 | 1.33 | 0.99 | 1.18 | 0.95 |
| 3.0 | 1.15 | 0.89 | 1.07 | 0.93 |
| 5.0 | 0.95 | 0.79 | 0.93 | 0.88 |
| 8.0 | 0.79 | 0.72 | 0.82 | 0.81 |
| 13.2 (the coating's back) | 0.65 | 0.64 | 0.70 | 0.70 |

- The maximum sits at the gap's corners for y <= ~10 um (exact) / ~8 um (Karlqvist), at the
  centre deeper down.
- At the gap's centre the exact field at the face is **0.83 Hg** (Karlqvist 1.0): the exact
  potential across the mouth isn't linear. Along the mouth (y -> 0) the exact Hx / Hg is 0.834
  at the centre, 0.886 at x = g/4, 1.05 at 0.4 g, 1.25 at 0.45 g, 1.98 at 0.49 g, singular at
  the corners; its integral over the mouth is g Hg (checked to 0.2%, the clipped corner tails).

**How much bias current sweeps the biased depth through the coating** (the field ratio between
two depths, in dB: the range of current over which a given switching field passes from the
first depth to the second):

| | surface (0.5 um) to back (13.2 um) | top 10% (1.77 um) to back |
|---|---|---|
| exact, \|H\| | **10.5 dB** | **6.7 dB** |
| Karlqvist, \|H\| | 7.1 dB | 4.8 dB |
| exact, \|Hx\| | **7.2 dB** | **4.1 dB** |
| Karlqvist, \|Hx\| | 3.0 dB | 2.8 dB |

So the exact head **widens the geometric depth sweep by 1.9-3.4 dB (|H|) or 1.3-4.2 dB
(|Hx|)**. The particle bench and the over-bias study place the missing width at ~2.3 dB of bias
(9.4 against 7.1). This is a sweep of field over depth, not the bias curve: the curve is that
sweep convolved with the medium's own partial-ARM rise (the switching-field distribution) and
weighted by each layer's playback contribution, so the widening in the model's rise will be
smaller than the sweep's and has to be measured. But it is the right size and sign, and it has
no free parameter.

Why it works: with Karlqvist, a long gap's longitudinal field is nearly uniform through a thin
coating (0.99 to 0.70 Hg: 3 dB), so once Hg passes the switching fields the whole coating is
biased within ~3 dB of current; the rise is then almost all the medium's own. The real head
puts a strong, mostly perpendicular field into the top microns at the corners (they start
recording at lower current: an earlier toe) and a weaker field at the centre and the back
(the back is reached ~0.6 dB later). Westmijze stated the qualitative point in 1956: "particles
deeper in the tape experience a smaller stray field", so recording takes place "in a small
area", larger for "the greater the spread in the coercive force and the thicker the tape"
(Westmijze, "The fundamentals of magnetic recording", NRG Publ. 56a, 1956, printed p. 5, PDF p. 8 [read]).

### 1.4 The over-bias side: the trailing contour [derived]

Where |H| last equals the switching field H_sw on the trailing side (x* in um downstream of the
gap's centre, at depths 0.5 / 2 / 4 / 7 / 10 / 13.2 um), and the field's angle from the tape's
plane there:

| Hg / H_sw | exact x* | Karlqvist x* | angle at x* (both) |
|---|---|---|---|
| 1.0 | 28.9 / 28.5 / 26.0 / - / - / - | 27.7 / 27.1 / - / ... | 86 / 75 / 55 deg |
| 1.5 | 33.8 / 33.7 / 33.0 / 31.2 / 27.5 / - | 32.6 / 32.4 / 31.8 / 30.0 / 26.5 / 18.4 | 88 ... 51 deg |
| 2.0 | 39.9 ... 34.6 (spread 5.4 um) | 38.9 ... 33.8 (5.0 um) | 89 ... 59 deg |
| 3.0 | 53.9 ... 51.4 (2.4 um) | 52.9 ... 50.6 (2.3 um) | 89 ... 72 deg |

- From Hg ~ 2 H_sw up (over-bias), the exact contour lies ~1 um farther out with the same depth
  spread: **the head's exact shape doesn't move the over-bias 15 kHz loss** (2.3-5.4 um of
  spread is 33-76 degrees of a 25.4 um wavelength, the same in both).
- Near the peak (Hg 1-1.5 H_sw) the exact head records the back layers later, not at all at
  1.5 H_sw below ~13 um where Karlqvist already reaches 18 um downstream: again the rise.
- The angle: **at the recording point the bias field is 50-89 degrees from the tape's plane**,
  nearly perpendicular at the surface at every bias. That is why the switching rule under a
  near-perpendicular, rotating field (the astroid, the particles) decides the over-bias
  behaviour, not the head's profile.
- The classical over-bias HF loss in this picture: the recording zone's width is the
  switching-field spread over the field gradient. In the far field |H| = Hg g / (pi r)
  (both heads, r >> g [derived from 1.1]), so the contour is a circle of radius
  r_c = Hg g / (pi H_sw) and a relative spread s of switching fields gives a zone ~ s r_c wide,
  growing linearly with bias (Westmijze 1956, printed p. 5 [read], qualitatively). The model has this.

Tjaden & Leyten's statement of the same theory, from Westmijze 1953 (Philips Res. Rep. 8, 250,
their ref. 3): recording takes place "in a ring-shaped zone situated just beyond the centre of
the air gap", where the bias amplitude "is roughly equal to the coercivity", and the signal
field there is, to first approximation, Hx = n i y / (pi r^2), Hy = n i sqrt(r^2 - y^2) /
(pi r^2), n the turns, i the signal current, r the zone's radius "partly determined by the bias
current" (Tjaden & Leyten, "A 5000:1 scale model of the magnetic recording process", Philips
Tech. Rev. 25, 319-329 (1963/64), p. 328 and Fig. 15 [read]). Consequence [derived]: once r
exceeds the coating, the longitudinal signal field at the zone falls as 1/r^2 (-2 dB per dB of
bias) and the perpendicular as 1/r (-1 dB per dB); the over-bias slope of the long-wave output
is set by how much the coating records and keeps the perpendicular part (orientation and the
perpendicular self-field: Tjaden & Leyten measured My "substantially reduced", "attributable to
the demagnetizing effect of the part of the tape which ... has already left the recording zone",
p. 329 [read]). That is a medium property, again.

### 1.5 What bounds the corner enhancement (physically)

The corner field is what matters, so what caps it decides the size of the effect:
- **Head-to-tape spacing.** The table's surface row assumes 0.5 um (the model's). At 1 um the
  exact top-layer field is 1.70 Hg (Karlqvist 1.37), at 2 um 1.33 (1.18): the widening shrinks
  as the spacing grows. 1950s acetate tape with a rough coating on a worn head: an effective
  spacing of 0.5-2 um is plausible (`provisional:` model knowledge; the 351 manual gives only
  "54.6 dB per wavelength" of spacing loss, `data/schematics/ampex_351/README.md` p 42 [read]).
- **Gap-edge rounding** (lapping, wear, chipped corners): a corner radius rho removes the
  singular part for distances below ~rho. A radius of 1-3 um would remove much of the effect
  in the top 2 um. Not found for Ampex heads in this search; `provisional: 0-3 um`.
- **Finite permeability** truncates the r^(-1/3) singularity only at r ~ g / mu_r (~0.05 um at
  mu_r ~ 1000) [derived, order of magnitude]: negligible.
- **Corner saturation**: the iron at the corner carries B ~ mu0 H_air there; it saturates where
  H_air > Bs / mu0 ~ 0.75 T / mu0 ~ 7,500 Oe (mumetall, `provisional:` its ~0.75-0.8 T), i.e. at
  10-25 Hg for Hg = 300-700 Oe (No. 21's range, the over-bias study's 670 Oe at 8 mA). The exact
  field reaches 2.75 Hg at y = 0.25 um; 10-25 Hg needs distances far below 0.01 um [derived]:
  **no corner saturation at No. 21's levels**. Fujiwara analysed record-head saturation in AC
  bias recording and gave a condition in terms of the core's Bm, g, Hc and delta (Fujiwara,
  IEEE Trans. Magn. 15, 1046 (1979), DOI 10.1109/TMAG.1979.1070325 [abstract]); the formula was
  not seen.
- **The magnetic gap is longer than the physical one.** "The MAGNETIC GAP length is ALWAYS
  greater than the physical gap length. The difference can range from only a few percent to
  15%", use "a factor of about 1.15" (Morrison, Standard Tape Laboratories, Standard Tape
  Manual, c. 1978, section on gap length [read]). The exact head explains it: its mouth
  spectrum's first null is at lambda = **1.135 g** [derived], against g for the sinc.
  The repro head (6.35 um, sinc in the model) inherits the same: its null at ~7.2 um, not
  6.35. For the record head, a magnetic gap 0-15% over 51 um puts the far-field contour
  0-15% farther out at a given current (a scale, not a shape) [derived].

### 1.6 How to put it in the model (cheap, no free parameter)

The Poisson-integral machinery in `tape.py` is exact for any head whose face potential is
known: the field in y > 0 is fixed by the potential on y = 0. The pole faces are exact as they
are; **only the gap mouth's linear ramp is Karlqvist's approximation**. Replacing it by the
exact mouth profile (Hx_s(x) / Hg on |x| < g/2 from the map above, tabulated once and scaled by
g) changes the spectrum's `sinc(kg/2)` into the exact mouth spectrum S(kg/2) = (1/g) integral
Hx_s(x) / Hg cos(kx) dx [derived; Tannous eq. 34 gives the same function in closed form via
Wilton et al.'s S [read]] and the space-domain `head_field` into the exact field (or the
mapping evaluated directly). S at lambda = 381 / 100 / 50 / 25.4 / 12.7 um: 0.962 / 0.550 /
-0.152 / 0.094 / 0.064, against the sinc's 0.971 / 0.624 / -0.020 / 0.004 / 0.004 [derived]:
S decays as k^(-2/3), slower than the sinc, so the cell size (0.714 um) and the zone tables
must resolve the corners; at the 0.5 um spacing e^(-ky) regularizes it. A corner radius and
the spacing are the only physical knobs (bounds above). Measure: No. 21's rise width and rms
with the base and the astroid variant, the 15k - 1k spread (expected unchanged), and the knee
(the corner field acts on the top layers, which carry the playback's largest share).

---

## 2. The Ampex 300 / 350 / 351 record head as built

What was found (nothing in this search gives the 300's record head drawing or data sheet):

| Quantity | Value | Source |
|---|---|---|
| Record gap (Ampex 300, No. 21's machine) | 0.002" (51 um) | 3M Sound Talk No. 21, Feb. 1953, p. 1 [read] (only source) |
| Record gaps of the period | "25 um (1 mil) for professional recording-only heads"; 1.5-3 um for combination heads | McKnight, "Biasing in magnetic tape recording", Electronics World, Aug. 1967, p. 35 [read] |
| Record gaps, practice | audio record gaps "rather long ... for example 1/4 to 1 mil"; avoid record gaps "much shorter than 1/2 mil"; "the shape of the bias field produced by a short gap record head" makes the tape susceptible to dropouts and is "difficult to drive" | Standard Tape Manual (Morrison, c. 1978), record head gap section [read] |
| Magnetic vs physical gap | magnetic gap always longer, a few % to 15%; use x1.15 | same [read] |
| Gap depth | "21 to 23 thousands [of an inch] usually found in the average professional head" (0.53-0.58 mm); Taber's new heads 27 thousandths (0.69 mm) | Taber Manufacturing & Engineering brochure (heads for Ampex 300 / 350 / 351 / 400), undated, p. 1 [read]: https://bh.hallikainen.org/uploads/harold/TaberBrochure.pdf |
| Core material | laminated Permalloy or mu-metal (record and playback heads); Taber's replacements "moly permalloy" | Westmijze 1956, PDF p. 34 ("Magnetic heads") [read]; Taber brochure p. 1 [read] |
| Gap spacer | "mostly of beryllium-copper or another wear-resistant material" | Westmijze 1956, PDF p. 34 [read] (a Philips playback head; Ampex's spacer not found) |
| Lamination thickness | not found in this search | `provisional:` 0.1-0.35 mm (the over-bias study's bounds) |
| Back gap, pole-face length, head contour radius | not found | - |
| Track width | full track 234 mil (5.94 mm) | Ampex 351 manual p 41 (`data/schematics/ampex_351/README.md` [read]) |
| Record head inductance | measured 13.5 / 13.9 mH, 19.8 ohm DC, on a 351 with later (Inovonics) electronics | GroupDIY, "Ampex 351 transport with Inovonics 380 electronics" (forum measurement, via search summary [abstract]): https://groupdiy.com/threads/ampex-351-transport-with-inovonics-380-electronics.84292 |
| Record head inductance, 351-type | "5-10 mHy record", 100 kHz bias; multitrack 4-5 mH | Inovonics 375 manual (via search summary [abstract]) |
| Bias current, Model 350 | the BIAS TEST position reads across a 500 ohm resistor (R459) in the record head's ground lead; at full resistance "a bias current of approximately 1.6 ma." reads 0 VU "at peak bias setting"; heads needing less than 1.6 mA need a 1 kohm pot "as is found on the newer Model 351" | Nortronics Form 7145C (Nov. 1966), p. 3, sec. 6-3 [read]: https://bh.hallikainen.org/uploads/harold/Nortronics7145C.pdf |
| Bias current, Ampex 300 | not printed in No. 21 beyond its axis (mA of the 300's head) | No. 21 p. 1 [read] |

**A consistency check on the model's head** [derived]: with a front gap of g = 51 um, track
w = 5.94 mm and depth D = 0.55 mm, the gap reluctance is R_g = g / (mu0 w D) = 1.24e7 A/Wb.
For a head of inductance L and front-gap efficiency eta, N = sqrt(L R_g / eta) and the deep-gap
field per ampere is N eta / g = sqrt(L R_g eta) / g. At the model's 3 mH this is at most
3.8e6 A/m per A (48 Oe/mA) at eta = 1, half the model's 8.0e6 A/m per A; at 13.7 mH (the
measured 351 head) it is 8.1e6 at eta = 1, 6.3-7.2e6 at eta 0.6-0.8. So **the model's 8.0e6
A/m per A needs a ~14 mH head, not 3 mH**, or a much shallower gap (D ~0.12 mm at 3 mH). This
moves no bias curve (No. 21 is fitted with its own scale, 68-84 Oe/mA in TAPE_PLAN.md), but the
3 mH sets the record circuit's load in the 351's IR; worth re-deriving from one consistent set
(L, N, D, eta).

---

## 3. The head at the bias frequency: efficiency, eddy currents, saturation

What would stretch the bias axis non-uniformly is a field per mA that depends on the current;
what changes the shape is a field profile that depends on the current or the frequency. A
uniform loss of efficiency (eddy currents, a lossy core) only rescales the axis, which No. 21's
fitted scale absorbs.

- **The current law is linear** (the over-bias study's `head_*` variants: Hg ~ I^1.003-1.008,
  I^1.06 at the lossy bound; the departure goes the wrong way). Nothing found here contradicts
  it: the gap field at 8 mA (~0.067 T) is a tenth of mumetall's saturation; the corners don't
  saturate either (1.5).
- **Eddy currents in the laminations** at 70 kHz: mumetall's skin depth there is ~10 um at
  mu_r 2e4, rho 0.55 uOhm m [derived: delta = sqrt(2 rho / (omega mu))], so a 0.1-0.35 mm
  lamination carries the bias flux in its skins and the core's effective permeability drops
  by ~an order of magnitude [derived]. This lowers eta (more current for the same Hg) but is
  linear in current: a scale, not a shape. It also lowers the bias-to-signal efficiency ratio,
  which the record EQ and the alignment absorb.
- **A conductive gap spacer** (beryllium copper, Westmijze 1956, PDF p. 34 [read]) is a shorted
  turn around the gap flux at the bias frequency; Otto (Siemens, 1972) reports that a
  conducting spacer lowers the head's high-frequency impedance through eddy currents in the
  gap region [abstract, via search summary]. Its screening parameter for a 51 um BeCu shim
  (sigma ~1.5e7 S/m, `provisional:`) 0.55 mm deep at 70 kHz: omega mu0 sigma t D ~ 0.2
  [derived], a few-percent, current-independent effect: a scale. Shute, Mapps & Wilton (IEEE
  Trans. Magn. 2001) show a copper layer at a gap edge redistributing flux and raising the
  field gradient, but at 100 MHz in thin-film heads [abstract].
- **Pole-tip saturation**: Fujiwara 1979 [abstract] treats it as a condition on Bm, g, Hc,
  delta; at No. 21's levels it doesn't occur (1.5). It would matter at erase-like currents or
  for high-coercivity tapes on narrow pole tips, not here.

Verdict for question 2: **no head mechanism at the bias frequency stretches No. 21's axis
non-uniformly**; the head acts on the shape only through its field's geometry (section 1).

---

## 4. Bias curves with a calibrated head (a better target than No. 21's axis?)

Searched for measured output against bias where the head's field per mA (or the bias field in
Oe) is known, on gamma-Fe2O3:

- **Levine & Daniel (NBS), "Determination of the recording performance of a tape from its
  magnetic properties", JAES 7(4), 181-188 and 222 (Oct. 1959)**; first given as AES Convention
  paper 45 (1958) [abstract]. Anhysteretic measurements of **thirteen tape types** fit one
  universal curve; with "a simple expression for the longitudinal field distribution of a ring
  type recording head", numerical integrations give the bias for maximum output and the
  recording sensitivity (remanent induction per deep-gap field) in absolute terms; only the
  coating thickness and gap length are needed besides two magnetic constants; "absolute
  measurements performed on an actual recording machine are in good agreement as far as the
  values of maximal bias are concerned" [abstract]. **The best candidate**: the period's
  calibrated measurement on period oxides, very likely including a #111-class tape, with a
  stated gap. Paywalled (AES e-library, 403 to this agent); the user would need to fetch it.
- **Bertram, "Long wavelength AC bias recording theory", IEEE Trans. Magn. 10(4), 1039-1048
  (Dec. 1974)**: longitudinal and vertical fields, an anhysteretic susceptibility tensor, the
  signal field taken "at each depth ... where the bias field amplitude is equal to the tape
  coercivity"; "excellent quantitative agreement with experimental sensitivity" and good
  correlation with "the shape of measured sensitivity vs. bias curves" [abstract]. Its
  experimental curves are the second candidate (head data presumably given; not seen).
- **Fujiwara, "Nonlinear distortion in long wavelength AC bias recording", IEEE Trans. Magn.
  15(1), 894-898 (1979)**: a normal distribution of switching fields, the coating in thin layers,
  "excellent quantitative agreement with experimental data" [abstract]; and the saturation paper
  (15(3), 1046) with experiments over Bm, g, Hc, delta [abstract]. Toshiba heads and tapes of
  the 1970s, not #111.
- **Tjaden & Leyten 1963/64** [read]: a 5000:1 scale model (gap 2 cm = 4 um, coating 5 cm =
  10 um, 175 turns, 35 mH, 50 Hz bias up to 60 A, the same gamma-Fe2O3 grains) measured the
  **magnetization against depth** (Fig. 14: a DC signal of 1 A with 20 A of bias, unoriented
  grains: Mx rising "more or less proportionately with y" up to a depth, the total lower near
  the surface). A calibrated depth profile, not a bias curve, and a short-gap geometry (g / delta
  0.4 against No. 21's 4). Useful as a check of the recording-zone picture (Fig. 16 its theory),
  not as a bias target. The deep-gap field per ampere at eta = 1 would be 175 / 0.02 m = 8,750
  A/m per A [derived].
- **Daniel & Levine, JASA 1960** ("Experimental and theoretical investigation of the magnetic
  properties of iron oxide recording tape", [memory], not checked): the anhysteretic data behind
  the 1959 paper.
- McKnight 1967, Fig. 1D-E: output against bias current in dB at several frequencies, relative
  only [read]. ATR / Quantegy sheets give over-bias settings per gap length (1.2 dB at 1 mil, 3.0
  at 5 mil, 3.5 at 0.25 mil: ATR Master Tape, via search summary [abstract]) but no curves.

Not found in this search: any bias curve plotted against bias field in Oe (or normalized to Hc)
with a head of known field per mA on a 1950s tape that is openly available.

---

## 5. Verdict

**Most likely head property behind the ~2.3 dB wider rise: the near-gap field's shape.** The
model's linear gap-mouth potential (Karlqvist) is the wrong approximation exactly where No. 21
records: a 51 um gap over a 12.7 um coating puts every layer within 0.26 g of the face. The
exact field (17% weaker at the centre, singular as r^(-1/3) at the corners) spreads the range
of current that biases the coating through its depth by +1.3 to +4.2 dB over Karlqvist's,
starting the top layers earlier and the back later. It is a correction of an approximation,
not a new parameter.

**Not the head: the stronger 15 kHz over-bias loss.** At over-bias the exact and Karlqvist
trailing contours agree within ~1 um, with the same depth spread; the field at the recording
point is 50-89 degrees from the tape there, so the over-bias fall and the treble loss are set by
how the coating switches and keeps perpendicular magnetization (the astroid, the orientation's
out-of-plane share, the perpendicular self-field), which is where the over-bias study already
points. The exact head may change how much the astroid overshoots (both act on the top layers),
so they should be re-measured together.

**Closed or nearly so for No. 21**: the head's current law (linear), eddy currents and a
conductive spacer (scales, not shapes), pole-tip and corner saturation (an order of magnitude
below the levels needed), the 70 kHz efficiency (a scale absorbed by the fitted axis).

**What to vary in the model, physically bounded:**

| Change | Bounds | Pinned by |
|---|---|---|
| The gap mouth's potential: linear -> exact (Westmijze / Fan geometry) | none (a correction) | Tannous 2015 [read]; Szczech et al. 1983 [abstract]; 1.3 here [derived] |
| Gap-edge (corner) radius | 0-3 um | `provisional:` not found for Ampex heads |
| Effective head-to-tape spacing | 0.5-2 um | `provisional:`; the 351 manual's spacing-loss rule only |
| Magnetic gap length | 51-59 um (x1.00-1.15) | No. 21 [read]; Standard Tape Manual [read]; the exact null at 1.135 g [derived] |
| Head L / N / gap depth / eta, one consistent set | L 5-14 mH, D 0.53-0.69 mm | Inovonics, GroupDIY [abstract]; Taber [read]; section 2's check |

Order: the exact mouth first (no free parameter, ~a table and a spectrum), measured on No. 21
with the base medium and with the astroid; then the spacing and corner radius only as bounded
sensitivities. If the exact head and the astroid together reach the 9.4 dB rise without the
15 kHz overshoot, No. 21 can stay the held-out test; if the rise still falls short, the
remaining width is the medium's (the switching-field distribution under rotating fields), and
Levine & Daniel 1959 is the calibrated measurement to ask the user for.

---

## Sources (opened this session)

- 3M Sound Talk No. 21 (Feb. 1953), `data/datasheets/tape/3m_Sound_Talk_21_195302.pdf`, p. 1
  (text via pdftotext).
- Tannous, "The Karlqvist approximation revisited", arXiv:1504.07625 (2015):
  https://arxiv.org/pdf/1504.07625
- Tjaden & Leyten, "A 5000:1 scale model of the magnetic recording process", Philips Tech.
  Rev. 25 (1963/64) 319-329, in the 1964 volume:
  https://worldradiohistory.com/Archive-Company-Publications/Philips-Technical-Review/60s/Philips-Technical-Review-1964.pdf
- Westmijze, "The fundamentals of magnetic recording" (NRG Publ. 56a, 1956):
  https://soundandscience.net/wp-content/uploads/2023/03/1126_NAG_Publicatie_No_56a_Westmijze_The_fundamentals_of_magnetic_recorder_1956.pdf
- McKnight, "Biasing in magnetic tape recording", Electronics World, Aug. 1967, pp. 34-36, 75:
  https://music-electronics-forum.com/filedata/fetch?id=928339
- Morrison, Standard Tape Laboratories, Standard Tape Manual (c. 1978):
  https://steampoweredradio.com/pdf/standard%20tape%20manual/Standard%20Tape%20Laboratories%20Standard%20Tape%20Manual.pdf
- Taber Manufacturing & Engineering brochure: https://bh.hallikainen.org/uploads/harold/TaberBrochure.pdf
- Nortronics Form 7145C (1966): https://bh.hallikainen.org/uploads/harold/Nortronics7145C.pdf
- Westmijze, "Studies on magnetic recording" (Philips Res. Rep. 8, 1953), CRL catalog record
  only: https://catalog.crl.edu/Record/570e2ec7-c9d3-580f-b150-a3317f4d1dd4
- Abstracts / index records only: Fujiwara 1979 (both papers, manuscript.isc.ac 1079812 and
  970649); Dolivo & Closs 1978 (967450); Bertram 1974 (via search summary); Levine & Daniel
  1958 / 1959 (AES e-library 175 / 547, via search summaries); Manly 1969 (AES 1398, via
  search summary: for long record gaps most variation in measured parameters is the coating
  thickness's); Szczech, Perry & Palmquist 1983; McCary & Tandon 1981 (985636); Shute, Mapps &
  Wilton 2001; Otto 1972; the GroupDIY 351 head measurement and the Inovonics 375 manual.
- Not found online: Westmijze 1953 itself; Fan 1961; Levine & Daniel 1959 full text; any
  Ampex 300 record-head drawing, lamination thickness, turns or bias current.

The numbers marked [derived] in sections 1 and 2 come from a ~60-line numpy script (the map of
1.3, Newton per field point, max over x on a 3001-point grid from -3 g to 3 g); it is not in the
repo. Rewriting it takes the two formulas in 1.3.
