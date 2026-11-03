# The K 47 (Braunmühl-Weber) capsule: theory, geometry, diffraction

Research notes for MIC_ROOM_PLAN.md A3, option (a) (2026-11-03). The problem was that
`K47@1` (`varimu/devices/capsule.py` `dual_lumped`, `parts.capsule_dual`) can't reproduce
Neumann's curves. Two things go wrong:

- **Low end:** the cardioid's null fills (0 dB front to back at 100 Hz; Neumann shows
  11.7 dB).
- **High end:** without diffraction both entries see the free field, so the omni sum
  notches near 15 kHz.

This file collects what the literature says. Each source is listed with what it gives and
how far to trust it. The proposals at the end are tied to those sources.

Labels used below:
- **"my arithmetic"** marks numbers I worked out from a source's formulas. They are not
  data.
- **"model knowledge"** marks textbook statements I did not check against a source in
  this session.

Downloaded files are in `C:\Users\Ria\AppData\Local\Temp\claude\k47_pdfs\` (scratch; not
committed). They were read with PyMuPDF; nothing in them was executed.

## Summary

1. **The network family is right. The parameters are in the wrong regime.**
   - Torio & Segota (Shure, AES 2000) model the dual-diaphragm capsule as
     `C_d – C_a – R_a – C_a – C_d`. Our `capsule_dual` reduces to the same network when
     `r_through` is small and the film sits between the gap and the holes.
   - Their exact result (below, eqs. 5-9) is two first-order filters that share one corner,
     `f_o = 1 / (π R_a (C_a + C_d))`:
     - a high-pass term with cardioid directivity;
     - a low-pass term that is omnidirectional in the far field.
   - So **every dual-diaphragm capsule becomes omni below `f_o` in the far field.** Torio &
     Segota measured this on their own capsule and on two other makers' microphones.
   - With `K47@1`'s values, `f_o ≈ 750 Hz` and k ≈ 0.71 (my arithmetic). That predicts
     0.2 dB front to back at 100 Hz, which is exactly our failure.
2. **The diaphragm should be tuned low.** Every source on the tuning puts its resonance in
   the middle of the band, about 1 kHz:
   - von Braunmühl & Weber's patent: "the damped natural frequency of the membrane is
     arranged to lie in the middle range of frequencies";
   - Austrian Audio on the CK12: membrane 800-1500 Hz;
   - a capsule maker on the M 7 and CK12 (forum): ~800 Hz;
   - an M 7 replica: 950 Hz, "quite similar to the tuning of the original M7";
   - Bock (capsule maker): "a relatively low resonant freq".

   That means a tension of a few tens of N/m. `K47@1` has 1500 N/m, and `fit_k47.py`
   bounds it to 300-5000 N/m. Those are measurement-microphone tensions: the membrane alone
   resonates at 13 kHz. With `C_d` ≫ `C_a` (a soft diaphragm on a stiff air cushion),
   `f_o` falls to ~10-50 Hz and the cardioid holds down to the bass.
3. **The mechanism, from the patent.** The two diaphragms have two motions:
   - "with compression of the enclosed volume of air": the pressure mode, controlled by the
     stiffness of the enclosed air;
   - "a parallel displacement of both membranes, the enclosed volume of air being carried
     along": the gradient mode, controlled by friction in the gap.

   The cardioid condition is that the two displacements are equal. In Torio & Segota's
   terms: `c R_a C_a ≈ d`, and the sensitivity is set by `C_a`, the air volume behind each
   diaphragm (gap plus blind holes).
   - Blind holes add compliance to the pressure mode.
   - Through-holes plus the gap film set the friction of the gradient mode.
   - In Braunmühl's design "the air-gap ... defined the resistance for both the pressure
     and [the gradient] component" (Austrian Audio). The CK12 later split them with a slit.
4. **Diffraction is the high-end fix, and the literature treats it as the design.**
   Boré & Peus: "the growing pressure build-up already starts compensating below the
   transition frequency f_t for the gradual decrease in the diaphragm driving force caused
   by the pressure gradient". Above that, the capsule is a pressure / interference
   transducer (Boré & Peus 5.3).
   - Proposed now: entries computed from the exact rigid-sphere series. They are
     closed-form, have the right low-frequency gradient limit and double the front
     pressure. Both entries are averaged over the diaphragm with its mode shape.
   - Proposed later: a body-of-revolution BEM of the real capsule and basket.
5. **K 47 / M 7 geometry.** There is still no primary source. Forum and maker figures
   agree with each other and fit the theory's sensitivity: M 7 about 5.7 mm thick;
   through-holes 0.8 mm × 5.65 mm; about 153 holes in all; blind holes about 1.1 mm,
   2.5-4 mm deep. See "K 47 / M 7 geometry".

## 1. Sources

### 1.1 von Braunmühl & Weber, US 2,179,361 (the principle's patent)

- H. J. von Braunmühl, W. Weber, "Condenser microphone", US 2,179,361. Priority DE
  4 April 1935, filed 30 March 1936, granted 7 Nov 1939.
- Web: https://patentimages.storage.googleapis.com/dd/eb/53/667df19b808297/US2179361.pdf
  (685,690 bytes, sha256 `4d4913b82564d1a7d9248e36bfeb18c02df22b18b7fe5f0de811b20a839f3e93`,
  the same file as in README.md). OCR text read from the PDF.
- The German counterpart's number (DE 705 827 per Mix; the brief's "DE 645 916?") is
  **not verified**. The 1935 paper "Kapazitive Richtmikrophone" (Hochfrequenztechnik und
  Elektroakustik 46) was not found online.
- Confidence: **high** (primary). The physics is qualitative: there are no values.

What it gives (printed page / column):

- p. 2 col. 1, the single-diaphragm gradient capsule: "the difference in sound pressures
  ... has a rising frequency characteristic up to that frequency at which the half wave
  length corresponds to the difference in path between the front and rear sides".
  - The film's force rises with frequency, "so that the membrane executes oscillations of
    the same amplitude": friction control.
  - "a completely horizontal frequency curve ... would only be obtained if the friction
    control widely exceeds the mass control and the elastic control ... Since this is not
    technically desirable on grounds of sensitivity ... there is obtained ... a highly
    damped resonance curve (Figure 2) ... The damped natural frequency of the membrane is
    arranged to lie in the middle range of frequencies by a proper selection of its mass
    and its elasticity."
- p. 2 col. 2, the fixes at the band edges:
  - for high frequencies "a flat air cavity in front of the membrane brings about an
    increase in the driving force" (a resonator ahead of the diaphragm);
  - for low frequencies, closed air cavities coupled to the space between membrane and
    electrode (cavity L via tube K, Fig. 3).
  - Diameter: "about 3 cms", limited by the wavelength at 10 kHz.
- p. 3 col. 1, **the dual-diaphragm cardioid (Fig. 4)**: the plate b with bores a extending
  through it, and two membranes c, d "having similar mechanical properties"; only c is
  electrically operative.
  - "Such a system of two membranes executes two principal movements. On the one hand the
    sound pressure causes a movement with respect to one another of the two membranes with
    compression of the enclosed volume of air. On the other hand there occurs, owing to the
    difference in the sound pressures acting on the two sides a parallel displacement of
    both membranes, the enclosed volume of air being carried along with them."
  - For rear incidence the two displacements of c cancel (Fig. 7), which gives the
    cardioid (Fig. 8).
  - "The condition for a decreasing or vanishing sensitivity for sounds from rearward
    directions is the equality of the membrane displacements under the influence of the
    sound pressure and under the influence of the sound pressure difference." The
    difference is set "simply by the diameter of the microphone".
  - "For the production of a straight line frequency curve the movement of the membrane
    must be principally determined by friction."
- p. 3 col. 2:
  - The electrode "possesses ... besides the bores a extending through it a number of
    shorter bores e not extending through it. Their number, size and arrangement influences
    the membrane displacement".
  - The friction-controlled co-phase motion reduces the sensitivity. The low-frequency fall
    "due to the elastic properties" is compensated by increasing the pressure difference at
    low frequencies: a gauze ring f around the capsule (Figs. 9-10) that "acts for the low
    frequencies as if the diameter of the microphone had been increased".
  - Omni = both membranes conducting, in parallel. Directional = one unconnected.
- Claim 1: the gap is "small compared with the diameter and spacing of said perforations
  and recesses and of a value which would render the frictional air damping on said
  diaphragm high as compared with its mass- and elasticity damping".

### 1.2 Torio & Segota, "Unique Directional Properties of Dual-Diaphragm Microphones"

- G. Torio, J. Segota (Shure), AES 109th Convention, Los Angeles, Sept. 2000, preprint 5179
  (per README.md).
- The full paper is on Shure's site, web:
  https://content-files.shure.com/Pubs/dual-diaphragm-microphone-properties/pdf_ea_dual_diaphragm_mics.pdf
  (559,046 bytes, sha256 `dc1228007d7a3dfc0273aa47a7f8408f7fb498354f810a584a4a81bfe2c0e235`,
  28 pages).
- **The key source.** Confidence: **high** for the model and its measured trends (peer
  conference, measured). The equations were transcribed from the rendered pages.
- Their reference [2] is the single-diaphragm basis: G. Torio, "Understanding the Transfer
  Function of Condenser Microphones in Response to Different Sound Sources", AES 105th
  Convention, San Francisco, 1998. Its section 3.2 argues the diaphragm is stiffness
  controlled. **Not found online.**

The single-diaphragm network (p. 3, Fig. 3): `P_f – C_d – node(C_a to ground) – R_a – P_b`.
- (1) `e_o/P_f = K_AE [s R_a C_a (1 + d cosθ/(c R_a C_a)) + (d/r) cosθ] / [s R_a (C_d + C_a) + 1]`
- (2) `f_o,SD = 1/(2π R_a (C_a + C_d))`
- (3) `K_HP,SD = C_a/(C_a + C_d) · (1 + d cosθ/(c R_a C_a))`
- (4) `K_LP,SD = (d/r) cosθ`

**The dual-diaphragm network (p. 5, Fig. 6):**
`P_f – C_d – node(C_a to ground) – R_a – node(C_a to ground) – C_d – P_b`.
- "the diaphragms are stiffness controlled in the frequency range of interest so they are
  modeled simply as an acoustic compliance C_d. C_a and R_a represent the compliances and
  resistance of the acoustic phase shift network."
- The output is the front diaphragm's displacement: `e_o = K_AE U / s`.
- (5) `e_o/P_f = K_AE · C_a C_d/(C_a + C_d) · [ s R_a (C_a + C_d)/2 · (1 + d cosθ / (c R_a (C_a + C_a²/C_d))) + (1 + (C_d/(2 C_a)) (d/r) cosθ) ] / [ s R_a (C_d + C_a)/2 + 1 ]`
- (6) `f_o,DD = 1/(π R_a (C_a + C_d))` (twice the single-diaphragm corner)
- (7) `K_HP,DD = 1 + d cosθ / (c R_a (C_a + C_a²/C_d))`. The cardioid condition is
  `c R_a C_a (1 + C_a/C_d) = d`.
- (8) `K_LP,DD = 1 + (d/r) (C_d/(2 C_a)) cosθ`. It is omnidirectional in the far field
  (r → ∞) and figure-8-leaning close up.
- (9) The low-pass term is cardioid at `r = d C_d / (2 C_a)`.
- (A10), the drive: `P_b = P_f [1 − (s d/c) cosθ − (d/r) cosθ]`, first order, no
  diffraction.
- (A9) as printed contains an undefined `C_t`; (5) is the usable result.

Their example values (p. 6), and what they compute from them:
- d = 3.2 cm (1.25 in capsule);
- C_d = 1.64e-10 m^5/N;
- R_a = 200e5 = 2.0e7 Pa s/m^3;
- C_a = 5.3e-12 m^5/N;
- they quote f_o = 53 Hz (single) and 106 Hz (dual).

My arithmetic gives 47 / 94 Hz from (2) / (6) with these values, so one value is
presumably rounded (12% off in both).
- Note C_d / C_a = 31: the diaphragm is ~30× more compliant than the cavity behind it.
- My arithmetic from (5) for a far-field plane wave:
  - k = 0.85 (slightly hypercardioid);
  - front / back 6.8 dB at 100 Hz, 20.4 dB at 1 kHz;
  - the on-axis response steps down ~5.4 dB (from 1 + k to 1) below f_o.

Findings, quoted:
- p. 7: at 8 ft "the dual-diaphragm model is leaning toward omnidirectional at 100 Hz".
- p. 13: "In the far field the dual-diaphragm capsules display a response that is
  approaching omnidirectional in the low frequency range ... Closer to the source the
  dual-diaphragm capsules display a near perfect cardioid in the low frequency range"
  (their capsule and two other makers', Figs. 17-25).
- p. 24: the rear diaphragm "acts as a compliance at low frequencies ..., and as such its
  impedance gets larger as frequency is lowered, partially blocking low frequency sound
  waves from reaching the back of the diaphragm ... the dual-diaphragm capsule acts less as
  a pressure-gradient responding device and more like a pressure responding device".
- Omni (sum of the two cardioids) is flat at all distances (Fig. 28). Figure-8 (the
  difference) has proximity bass.
- Measurement distance matters at low frequencies. **Neumann's 1958 polars don't state
  theirs.** By (9), a K 47-like capsule's low-frequency pattern is cardioid near
  `d C_d / (2 C_a)`, which ranges from tens of cm to metres.

### 1.3 Boré & Peus, "Microphones: Methods of Operation and Type Examples" (Neumann, 1999)

- Web: https://assets.sennheiser.com/download/assets/docu0002_BoreBuch_E-1999.PDF/5574009cdc0211f0887916ac7ce906bd
  (942,111 bytes, sha256 `751c758d8a546329db83848a883dfb50757f36d81a64aee60386098e97ba1385`).
- Neumann's own book, qualitative. Confidence: **high** as Neumann's account of how their
  capsules work; **no values** for the K 47.
- Printed page numbers below; the PDF page is one less.

What it gives:
- p. 13, Fig. 3: the gradient's response for points 25 mm apart, with the transition
  frequency f_t where λ/2 equals the path; "between 4 and 10 kHz, depending on the size".
- p. 20, 3.3: "sound arriving perpendicularly to the diaphragm exerts, depending on the
  shape of the microphone, **up to 10 dB more force on the diaphragm** as the result of
  pressure build-up. With sound from the side or rear bending and shading effects appear."
- p. 21, 3.3.2 (pressure-gradient microphones): "This depends on the microphone diameter,
  the transition frequency and the delay as the sound travels around the microphone to the
  rear face of the diaphragm being closely correlated. Properly dimensioned, **the growing
  pressure build-up already starts compensating below the transition frequency f_t for the
  gradual decrease in the diaphragm driving force caused by the pressure gradient**; above
  the transition frequency, the microphone gains a single- or double-sided directional
  characteristic similar to that of a cardioid or figure-8 as the result of interference
  and shadowing effects."
- p. 32, 5:
  - diaphragms 1-10 µm, gaps 5-50 µm;
  - "the restoring force and damping of the diaphragm are primarily determined by the air
    cushion behind it, and can be adjusted ... by a suitable choice of diaphragm spacing
    and by holes drilled in the backplate (but not through it)".
  - 5.1: pressure capsules are high-tuned, with blind holes to soften the air cushion.
- p. 33, 5.2: gradient capsules have through-holes. The diaphragm "should have only a
  (frequency-independent) frictional constraint ... the diaphragm resonance ... is placed
  at the middle of the frequency range ... The resonance is then damped to such an extent
  by air friction in the gap between diaphragm and backplate and also in the backplate
  itself that it is no longer recognizable as such."
- p. 33, 5.3 (cardioid condenser microphones): "**In some microphones, one portion of the
  backplate is provided with through holes, another portion with blind holes. The capsules
  thus function partially as a pressure gradient transducer and partially as a pressure
  transducer, the end product being a cardioid characteristic.**"
  - In other designs the backplate is an acoustic low-pass ("holes, slots and pockets ...
    friction resistances and ... acoustic inductances and capacitances"). Above f_t "sound
    impinges on the diaphragm only from the front, and the microphone capsule takes on the
    character of a pressure or interference transducer".
  - p. 34: the first kind "enjoy a popularity ... possibly because their pressure
    transducer portions ... handle transients with greater precision".
- p. 37, 5.5.1 (Figs. 19-20): pattern selection by the second half's polarization; the
  centre position gives cardioid.

### 1.4 Peus, "Modern Acoustic and Electronic Design of Studio Condenser Microphones" (AES 116th, 2004)

- Preprint 6131, web:
  https://assets.sennheiser.com/download/assets/lect0045_Peus_AES-2004_Modern-acoustic-and-electronic-design.PDF/a847da68dc0d11f0a0b34a591c6843d5
  (660,295 bytes, sha256 `4f53480c749a6ce1bec3865a5baaf98cb9747b130d1cf499067371db2a1ad5c9`).
- A scan; read from rendered pages. Confidence: **high** (Neumann's head of development).

What it gives:
- p. 2: the CMV 3's M 1-2 pressure capsule, 50 mm: "For sounds directly originated in
  front of the microphone ... the capsule sensitivity increased by **more than 12 dB at
  high frequencies due to pressure build-up**." This is a diffraction anchor for a 50 mm
  flat-faced body.
- p. 2, Fig. 3 (M 7, cardioid and omni): "The sensitivity of the cardioid polar pattern
  was very balanced, with a flat presence boost of 3 to 4 dB. **In the omni setting, the
  sensitivity at high frequencies increased to +6 dB.**" The omni setting is the sum of
  both halves, so this is the build-up seen with no gradient cancellation. It is the
  opposite of our notch.
- pp. 4-5: in a large-diaphragm capsule "only around **40 % of the vibrating mass** is
  comprised of the diaphragm itself, whereas approximately 60 % consists of the mass of the
  air which is moved by the diaphragm".
  - U 87 (K 67, ~1960): 34 mm, "diaphragms ... positioned at 8 mm from one another".
  - A 2003 capsule: 33 mm, 6 mm apart, with less enclosed air mass and a faster transient.

### 1.5 Austrian Audio (Christoph Frank), "The CK12 Capsule Demystified"

- Web: https://austrian.audio/the-ck12-capsule-demystified/ (no date on the page).
- A maker's engineer on a sibling capsule (AKG CK12, Braunmühl-derived). Confidence:
  **medium-high** for the CK12; it is not the K 47.

What it gives:
- "In Braunmühl's Version, the air-gap between membrane and electrode ... defined the
  resistance for both the pressure and cardioid component of the system".
- "The CK12 separated those two by using a slit ... between the two capsule halves for
  control of the gradient component so it can be adjusted independently."
- The slit's distance ring is "around 50µm", often customized per microphone. The
  membrane-to-electrode ring is "30-50µm", which also provides "an air suspension for the
  membrane movement".
- The membrane "has a resonance frequency of 800-1500Hz", varying over production.
- Rear rejection is "around 20dB", tuned by hand.

### 1.6 Makers' and restorers' figures (forum level)

- **dale116dot7** (GroupDIY, 25 Jan 2005,
  https://groupdiy.com/threads/m7-capsule-in-g7.5110/): "the original M7 and the original
  CK12 were tuned with diaphragm resonance frequencies of 800 Hz ... Current manufacturing
  practice appears to tune a bit higher - maybe 1200 Hz." He says this comes from reading
  patents.
- **The 10000cows.com M 7 replica** (http://www.10000cows.com/SomeMicPhotos.htm, the
  builder's own page; fetched HTML 9,991 bytes, sha256
  `378c02bdfadd930f598a8d00e7c28ecb43efcd033ba7df632f97176d5b122940`):
  - 6 µm Mylar "tensioned to a resonance of about 950 Hz, which is quite similar to the
    tuning of the original M7"; "A mass of 120 grams should result in a diaphragm resonant
    frequency of about 950 Hz";
  - working blind-hole depth 4 mm; "this one was 2.5mm ... devoid of any high-end";
  - "Diaphragm tuning is not as critical on the Neumann capsule design as it is on the
    Siemens/AKG capsule";
  - an original M 7 with a dried-out, cracked PVC diaphragm.
  - Probably the same builder as dale116dot7 (not verified).
- **dale116dot7** (GroupDIY, 7 Mar 2007, https://groupdiy.com/threads/building-capsules.21329/,
  post 15): M 7 phase shift from "the dimensions of the through holes (which are 5,65mm
  long and 0,8 mm in diameter)".
- **GroupDIY "DIY capsule"** (https://groupdiy.com/threads/diy-capsule.2527/, 2004):
  - Marik measured an M 7: 29.85 mm without the middle rim, gold area 25.41 mm, thickness
    5.73 mm;
  - dale116dot7: 152-153 holes per capsule, through-holes "1/32"" (0.79 mm), blind holes
    a #57-58 drill (≈ 1.07-1.09 mm), a guessed stop depth of 0.155" (3.9 mm), and a
    single-backplate KK47 / M 7 thickness of "maybe 6.5 mm".
- **David Bock**, Tape Op #46 (README.md): a 1" membrane, metallized to 0.9", "a
  relatively low resonant freq".
- **Science Museum Group** M 7 (README.md): "153 precisely hand-drilled ... holes, some of
  which went through to the opposite side".
- **audioimprov.com K 67 take-apart**
  (https://www.audioimprov.com/AudioImprov/Mics/Entries/2013/2/19_K67_Capsule_Take-apart.html):
  rows of 6, 8, 10, 12, 12, 12, 12, 12, 12, 10, 8, 6 (110 holes), "every other hole ...
  half go through with a smaller drill, and half are blind". This is the K 67, not the
  K 47.

Confidence for all of 1.6: **low-medium**. They are consistent with each other and with
1.1-1.5, but they are second-hand.

### 1.7 Diffraction sources

- **Rigid sphere, exact series.**
  - R. O. Duda, W. L. Martens, "Range dependence of the response of a spherical head
    model", J. Acoust. Soc. Am. 104(5), 3048-3058 (1998): the surface pressure on a rigid
    sphere for a plane wave and for a point source at range r, with a stable recursive
    evaluation.
  - Textbook: P. M. Morse, K. U. Ingard, Theoretical Acoustics (1968), the sphere
    scattering section; B. Rafaely, Fundamentals of Spherical Array Processing (Springer,
    2015), the rigid-sphere mode strength.
  - Citations from model knowledge; the papers weren't downloaded. The planar formula below
    is derived and checked at n = 0, 1.
- **Rigid disk, low-frequency limit.** H. Lamb, Hydrodynamics (6th ed., 1932), the disk
  moving broadside: velocity potential ±(2U/π)√(a² − r²) on its faces, added mass 8ρa³/3.
  Model knowledge. The added mass checks against the standard 8ρa³/3.
- **Rigid disk / plates / cylinders / cube, measured and exact.**
  - G. G. Muller, R. Black, T. E. Dunn, "The Diffraction Produced by Cylindrical and
    Cubical Obstacles and by Circular and Square Plates", J. Acoust. Soc. Am. 10(1), 6-13
    (1938): the pressure on the front face vs dimension / λ at 0°, 30°, 60°. A secondary
    source (https://gammaelectronics.xyz/sb_1980-01_diff.html) prints the year as 1948; the
    volume dates it 1938.
  - F. M. Wiener, "Sound Diffraction by Rigid Spheres and Circular Cylinders", J. Acoust.
    Soc. Am. 19, 444 (1947): the sphere and cylinder surface pressure, theory vs
    experiment.
  - F. M. Wiener, "The Diffraction of Sound by Rigid Disks and Rigid Square Plates",
    J. Acoust. Soc. Am. 21 (1949), with an erratum in 22(1) (1950): the surface pressure vs
    angle of incidence. The illuminated side agrees with an approximate theory, and the
    exact zero-thickness disk at normal incidence agrees with experiment for 1 ≤ ka ≤ 5.
  - R. D. Spence, "The Diffraction of Sound by Circular Disks and Apertures", J. Acoust.
    Soc. Am. 20(4), 380-386 (1948), doi:10.1121/1.1906389: the exact theory in oblate
    spheroidal coordinates.
  - None of these four were downloaded (JASA paywall; the sonicfield.org abstract pages are
    gone or unreachable). The details come from abstracts quoted in search results.
    Confidence: **medium** on the citations, **none** on numbers I haven't seen.
- Boré & Peus (up to 10 dB build-up) and Peus (the 50 mm M 1-2, >12 dB; the M 7 omni,
  +6 dB at the top): above.

### 1.8 Named but not obtained

None of these was found online in this pass. They're worth getting:
- Torio 1998 (AES 105th; the single-diaphragm basis).
- H. F. Olson, Acoustical Engineering (1957): the impedance-analogy networks for gradient
  and cardioid microphones.
- M. Rossi, Acoustics and Electroacoustics (Artech, 1988).
- B. B. Bauer's papers on phase-shift cardioids.
- J. R. Sank, "Microphones", J. Audio Eng. Soc. 33 (1985).
- M. Schneider, "Pop Measurements, Low Frequency Response and Microphone Construction",
  AES 104th (1998).
- Esteves et al., JASA 2017 (a general lumped model; README.md).
- Zuckerwar 1978 and Škvor 1967/68 (film resistance; README.md).
- M. R. Stinson, "The propagation of plane sound waves in narrow and wide circular tubes
  ...", J. Acoust. Soc. Am. 89(2), 550-558 (1991): the isothermal / adiabatic transition in
  holes.

No thesis with a K 47 / K 67 / CK12 lumped model *with values* turned up. Torio & Segota's
example is the closest published set.

## 2. The theory, consolidated

**Two modes.** The two diaphragms are equal, so the motion splits into two modes (the
patent's two "principal movements"; Torio & Segota's two filter terms):

- **The pressure (symmetric) mode.** The diaphragms move toward each other and compress the
  enclosed air. One diaphragm's volume displacement is `p · C_d C_a / (C_d + C_a)`. That is
  `≈ p C_a` when `C_d` ≫ `C_a`: the diaphragm is controlled by the stiffness of the air
  cushion (Boré & Peus: "air suspension" (Austrian Audio), "restoring force ... primarily
  determined by the air cushion"). It is flat from the static leak up to the resonance of
  the diaphragm's mass on `C_a`.
- **The gradient (antisymmetric) mode.** Both diaphragms translate together and push air
  from one side to the other through the gap films and through-holes, resistance `R_a`. The
  drive is `Δp = jω (d/c) p cosθ`. When friction controls (`R_a/2` ≫ `1/(ω C_d)` and
  ≫ `ω M`), the displacement is `Δp/(jω R_a) = (d/(c R_a)) p cosθ`, which is flat. The
  patent requires friction control here.
- **Below the corner `1/(π R_a C_d)`, the diaphragm's own stiffness takes over the
  gradient mode.** Its displacement then falls 6 dB/octave, and the pressure mode is left:
  omni at low frequencies. This is Torio & Segota's `f_o` and the patent's "fall ... due
  to the elastic properties" (compensated in the patent by the gauze ring).
- **The cardioid** needs the two displacements equal: `C_a ≈ d/(c R_a)` (Torio & Segota
  (7)).

The control regime per band (my synthesis of the patent, Boré & Peus, and Torio & Segota):

| band | pressure mode | gradient mode | pattern (one side) |
|---|---|---|---|
| below the leak (≪ 1 Hz) | vented | vented | none |
| leak .. `f_o = 1/(π R_a (C_a + C_d))` | air stiffness (`C_a`) | diaphragm stiffness (`C_d`), falls with ω | toward omni |
| `f_o` .. ~5-10 kHz | air stiffness | **friction** (`R_a`) | cardioid |
| above ~5-10 kHz | mass + air stiffness resonance, film-damped; diffraction build-up | blocked (`ωM` ≫ `R_a`) or film low-pass | pressure / interference transducer |

**What controls the diaphragm.** It is not one regime but a pair of them, and the
diaphragm's own stiffness must be small next to both the air cushion (`C_d` ≫ `C_a`) and
the friction (`1/(ω C_d)` ≪ `R_a` above `f_o`).
- Our "stiffness-controlled" `K47@1` has `C_d` ≈ 9 `C_a` and `R_a C_d` = 0.4 ms. The
  diaphragm stiffness controls the gradient mode up to ~750 Hz, hence omni there.
- Our "resistance-controlled" attempt raised `R_a` without softening the diaphragm. That
  shrinks the gradient mode by `1/R_a` while `C_a` stays as it was, so either the balance
  or the sensitivity is lost.

**The holes and the film.**
- **Blind holes (and grooves, pockets)** add compliance to `C_a`. That raises the
  pressure-mode sensitivity and lowers `R_a` for the cardioid.
  - 10000cows: 2.5 mm deep holes gave a capsule "devoid of any high-end" vs 4 mm. By this
    theory, less `C_a` means a stiffer cushion and a weaker pressure mode, so the balance
    shifts. My reading, not the builder's.
  - Holes of r ≈ 0.4-0.55 mm are wider than the thermal boundary layer above a few hundred
    Hz (δ_t = √(2κ/ω) ≈ 85 µm at 1 kHz; model knowledge, Stinson 1991). Their air is
    closer to **adiabatic** (`V/(γ P0)`) than isothermal in most of the band, and the gap
    film (h ≈ 50 µm) is isothermal.
- **Through-holes plus the gap film** form `R_a`. In Braunmühl's design the film dominates
  ("the air-gap ... defined the resistance for both components", Austrian Audio; the
  patent's claim 1: the gap is small next to the hole spacing, so friction is high).
  - The M 7's through-holes (0.8 mm × 5.65 mm, forum) have a Poiseuille resistance of only
    ~10^5 Pa s/m^3 per ~30 holes (my arithmetic). So `R_a` is the lateral flow in the film
    toward the through-holes.
  - The CK12 adds a slit in series so that `R_a` can be set apart from the film.
- **The film into the blind holes** is short (the holes are ~1.7 mm apart). Its resistance
  (Škvor's cell formula with ~60 blind holes per side and B ≈ 0.25: ~10^6 Pa s/m^3, my
  arithmetic) puts the blind holes' corner near 100 kHz. To audio the blind holes and the
  gap are one node, which is Torio & Segota's `C_a` at each end of `R_a`.
- **Distributed effects.** The film plus blind holes is a 2-D RC diffusion medium drained
  at the through-holes. One lumped `R_a` holds while the diffusion time across a
  through-hole's cell is short against the period. With ~30-40 through-holes this is
  ~10 µs (corner ~10 kHz, my arithmetic), so near the top of the band one more RC rung
  would matter. Boré & Peus describe the backplate as an "acoustic low-pass network".

## 3. K 47 / M 7 geometry found

There is still no drawing or primary measurement. The best estimates, with sources:

| quantity | value | source | confidence |
|---|---|---|---|
| outer diameter | M 7 32 mm, K 47 33 mm; M 7 29.85 mm without the middle rim | GroupDIY (README.md, 1.6) | low-medium |
| metallized diameter | 25.41 mm (Marik, measured) / 0.9" = 22.9 mm (Bock) | 1.6 | medium |
| capsule (backplate) thickness | 5.73 mm (M 7, measured); "maybe 6.5 mm" (guess) | 1.6 | medium |
| through-holes | Ø 0.8 mm (1/32"), 5.65 mm long | dale116dot7 2004 / 2007 | low-medium |
| blind holes | Ø ≈ 1.07-1.09 mm (#57-58 drill), depth ~3.9 mm guessed; replica 4 mm works, 2.5 mm loses the top | dale116dot7; 10000cows | low |
| hole count | 153 in all ("some ... through"); 152-153 | Science Museum; dale116dot7 | medium (count), none (split) |
| diaphragm | M 7: PVC 9-11 µm; K 47 / K 49: polyester ~6 µm | README.md; 10000cows | medium |
| diaphragm resonance | ~800 Hz (original M 7, CK12); ~950 Hz (M 7 replica, "similar to the original"); 800-1500 Hz (CK12) | dale116dot7; 10000cows; Austrian Audio | medium (consistent; a mid-band tuning is primary in the patent) |
| capacitance per half | 78-83 pF | 1959 drawing (README.md) | high |
| polarization | 63 V on the backplate | 1959 drawing | high |
| vibrating mass | ~40% diaphragm, ~60% co-moving air (large-diaphragm capsules) | Peus 2004 | high (generic) |
| diaphragm spacing | K 67 8 mm (34 mm capsule); a 2003 capsule 6 mm (33 mm) | Peus 2004 | high (not the K 47) |

My arithmetic from these numbers. They are consistency checks, not data:
- **Gap.** `C0 = ε0 π b² / h` with C0 ≈ 75-80 pF (less ~3 pF stray) and b = 11.4-12.7 mm
  gives h ≈ 45-58 µm, within Boré & Peus's 5-50 µm.
- **Tension.**
  - A 6 µm polyester membrane (ρs = 8.3e-3 kg/m²) at a = 12.5 mm whose first mode in vacuo
    is 1-2 kHz has T ≈ 7-30 N/m.
  - If the 800-950 Hz was measured in air on the bare ring (air loading ~3× the film's
    mass), the in-vacuo frequency is ~2× higher and T ≈ 30-40 N/m.
  - Either way it is **tens of N/m, not thousands**.
  - Stability at 63 V: the electrostatic negative stiffness in our first-mode model is
    ~1.8e5 · E0² ≈ 7e8 Pa/m³ for h = 48 µm. Against `1/C_d` = `8T/(π a⁴)` that is 0.34 of
    the restoring stiffness at T = 20 N/m and 0.85 at 8 N/m. So **T ≳ 12 N/m** for a
    margin, and the polarization softening is a real part of `C_d`. This may be what
    actually sets the factory tension.
- **Blind-hole volume.** The forum's M 7 numbers (153 holes; say ~33 through and ~60 blind
  per side; Ø 1.08 mm × 3.9 mm) give ≈ 0.21 cm³ per side. That is `C_a` ≈ 1.5e-12
  (adiabatic) to 2.1e-12 (isothermal) m^5/N per side, plus the gap's 0.02 cm³.
- **Sensitivity check.**
  - The U 47's 2.5-2.8 mV/µbar (25-28 mV/Pa) cardioid output, divided by the amplifier's
    +9.7 dB (our circuit), is ~8-9 mV/Pa at the capsule.
  - The displacement needed (`2 C_a` on axis × E0 κ/(π a² h) ≈ 3e9 V/m³) gives
    `C_a` ≈ 1.4-1.7e-12 m^5/N per side.
  - **The forum geometry and Neumann's sensitivity agree to within the uncertainty.**
    `K47@1`'s `C_a` (7.4e-13) is about half of this.
- **R_a.** The cardioid then needs `R_a = d/(c C_a)` ≈ 4-7e7 Pa s/m^3 for d = 20-32 mm.
  - Škvor's film formula with only the ~33 through-holes as drains at h = 48 µm gives
    ~0.9e7 per side (~2e7 total), Torio & Segota's value.
  - Matching would need h ≈ 35 µm or the blind holes not acting as drains. **R_a is the
    parameter to fit**, bounded about 1e7-1e8.
- **f_o** with C_d = 5e-10 (T ≈ 20 N/m), C_a = 1.6e-12, R_a = 5e7: ≈ 13 Hz. Neumann's
  11.7 dB at 100 Hz needs f_o ≲ 54 Hz with k ≈ 1 in the far field (my arithmetic from
  (5)). So **the low tension alone fixes the low end.**

## 4. Diffraction by the capsule body

How others treat it:
- Boré & Peus (3.3.2) and the patent (the HF "flat air cavity in front of the membrane")
  treat the pressure build-up and the rear shadow as **part of the design**. They
  compensate the gradient's fall above f_t, and above it the capsule works as a pressure /
  interference transducer.
- Torio & Segota limit their model to below ~1 kHz (pure delay plus 1/r, eq. A10).
- Measurement-microphone practice treats it as a per-angle "free-field correction" of the
  blocked pressure (model knowledge).
- So the network's two inputs should be the **blocked pressures** on the two diaphragms'
  faces: the incident field plus the field scattered by the rigid capsule and basket.
  - Each should be averaged with the diaphragm's mode shape (the work-conjugate of its
    volume velocity): `p_entry = ∫ p w dA / ∫ w dA`, with `w = 1 − r²/a²`, the shape
    `displacement_per_volume` already assumes.
  - The radiation mass stays in the network (`m_diaphragm`), as now.

Closed forms:

- **Rigid sphere, plane wave.** In the project's e^{+jωt} convention, with γ the angle
  between the surface point and the direction toward the source:

  `p(a, γ) / p0 = (1/(ka)²) Σ_{n≥0} j^{n−1} (2n+1) P_n(cos γ) / h_n^{(2)′}(ka)`

  - Derived from the standard expansion and the Wronskian
    `j_n y_n′ − j_n′ y_n = 1/x²`. Checked at n = 0 (gives 1) and n = 1 (gives
    `(3/2) j ka cos γ`).
  - The equivalent form is Duda & Martens 1998. Their range-dependent version handles a
    point source at r, which Neumann's polars may need (Torio & Segota: the low-frequency
    pattern depends on r).
  - Low-frequency limit: `1 + (3/2) j ka cos γ`. So the two poles' **effective path is
    3a**, the 3/2 being the sphere's flow concentration.
  - The pole facing the source tends to +6 dB.
  - The rear pole has the bright spot. Averaging over the diaphragm's cap tames it.
  - Truncate at n ≈ ka + 10 or so.
- **Rigid thin disk, low-frequency limit.** The potential flow past a disk broadside
  (Lamb) gives a pressure difference between the faces at radius r of
  `Δp(r) = jk p0 (4/π) √(a² − r²) cosθ` (my derivation from Lamb's potential, checked
  against the added mass).
  - The effective path is **4a/π at the centre**, and `16a/(5π)` ≈ 1.02a weighted by the
    parabolic mode over the whole face.
  - A thick capsule adds roughly its thickness (heuristic). This is the low-frequency `d`
    that the cardioid condition uses.
  - The disk's high-frequency face pressure has a coherent edge ring, so it peaks near
    ka ≈ π (~10-11 kHz for a = 15-16.5 mm). The peak is up to the ~10 dB that Boré & Peus
    quote for flat faces (Wiener 1949 has the measured curves vs angle; Spence 1948 the
    exact normal-incidence theory). A sphere peaks less (6 dB, smoothly).
- Why the omni notch goes away:
  - At high frequencies each half is a pressure transducer of its own face (Boré & Peus
    5.3), and the omni output sums the two.
  - With free-field entries `p_f + p_r = 2 cos(ωd/2c)`, which notches at c/(2d).
  - With blocked pressures the front face builds up toward +6 to +10 dB and the rear is
    shadowed, so the sum doesn't cancel and rises at the top. That matches Peus's M 7 omni
    "+6 dB at high frequencies".

## 5. What this means for our network

### 5.1 `dual_lumped` (numbers from geometry): re-parameterize, no new topology

`capsule_dual`'s topology already contains Torio & Segota's Fig. 6:

`L_m – C_d – gap(C_g) – R_f – holes(R_b → C_b) – R_t + L_t – holes – R_f – gap – C_d – L_m`

It reduces to Fig. 6 with `C_a = C_g + C_b` and `R_a = 2 R_f + R_t` when `R_f, R_b` are
small and `R_t` carries the resistance. Today it is the other way round: `R_f` is
3e7 per side and `R_t` 5.5e4. So:

1. **Reassign the resistances (Austrian Audio; Torio & Segota; the patent's claim 1).**
   - `r_film` becomes the film into the blind holes: Škvor's cell formula with the *blind*
     holes as drains. It is small (~1e6) and keeps some pressure-mode damping at the top.
   - `r_through` becomes the gradient path: twice the film resistance toward the
     through-holes (Škvor with the *through* holes as drains, or a fitted
     `gradient_resistance_pa_s_m3`), plus the holes' Poiseuille resistance, plus an
     optional `slit_resistance_pa_s_m3` (the CK12 family; 0 for the K 47).
   - `m_through` stays. The same nodes and elements mean no IR change, only values.
2. **Make the diaphragm low-tuned (the patent; Austrian Audio; the forum tunings).**
   - Tension bounds about 8-60 N/m: in-vacuo membrane resonance ~1-3 kHz for 6 µm
     polyester, and the fitted target is the ~1 kHz "damped natural frequency".
   - Keep the electrostatic negative stiffness, and reject (load error) a geometry whose
     softening exceeds ~0.7 of the restoring stiffness at the circuit's polarization.
   - Report `f_o = 1/(π R_a (C_a + C_d))` and `k = d/(c R_a C_a (1 + C_a/C_d))` in the
     component file next to `membrane_resonance_hz` (Torio & Segota (6), (7)). They show
     at fit time whether a geometry can be cardioid at 100 Hz.
3. **Blind-hole compliance adiabatic, not isothermal (model knowledge; Stinson 1991).**
   - For hole radii ≳ 0.3 mm use `V/(γ P0)`. Or, better, a thermal-relaxation pair: the
     adiabatic C in parallel with `R_th` in series with `(C_iso − C_ad)`, `R_th` from the
     hole's thermal time `r²/(5.8 κ)` or so.
   - Keep the gap film isothermal.
   - The pair adds one node per side, so it is optional.
4. **Bounds that follow from the geometry (section 3).**
   - backplate thickness 5.0-6.5 mm (through-hole length = thickness);
   - through-holes Ø 0.7-0.9 mm, count 20-60;
   - blind holes Ø 0.9-1.3 mm, 30-80 per side, depth 1.5-4.5 mm (≤ thickness − 0.5 mm);
   - total count ≈ 153 as a soft constraint;
   - h from C0 = 78-83 pF (less stray), so not free;
   - `d` 15-35 mm, or from the body (5.3).

   Then **fit to Neumann's curves with the sensitivity as a target**: 2.5-2.8 mV/µbar
   cardioid and 1.4-1.7 omni at the output. The omni / cardioid ratio, 0.5-0.6, is itself
   a check: two ideal back-to-back cardioids averaged give exactly half on axis.
5. **Optional, only if the top octave demands it (Boré & Peus's "low-pass network").**
   Split `r_through`'s film part into a two-rung RC ladder, with the blind compliance
   shared between the rungs. This is a topology change in both builders, so make it only
   with a measured reason.

`capsule_dual` itself needs no change for the K 47. The CK12's slit is a series resistance
already covered by `r_through`.

### 5.2 `fit_k47.py` (not edited here)

Its bounds exclude the regime the sources describe:
- tension: 300-5000 → ~8-60 N/m;
- film resistance: the gradient path (1e7-1e8) and the blind film (~1e5-1e7) need separate
  bounds;
- `path_m`: 4-30 mm is fine once diffraction supplies the high end, but tie it to the body
  (5.3).

Neumann's polars should be computed at a stated distance, or the plane-wave assumption
should be flagged: Torio & Segota's (8)-(9) make the low-frequency pattern of a
dual-diaphragm capsule depend on r.

### 5.3 `varimu/mics/free_field.py`: a diffraction model

Replace "both entries see the free field" with blocked pressures in three stages:

1. **Now: the rigid-sphere entries (closed form, cheap, exact for its shape).**
   - `sphere_entries(f, theta, radius_m, cap_half_angle_rad, r_m=inf)` gives the front
     and rear entry factors. Use the series above (Duda & Martens for finite r), averaged
     over the two polar caps with the parabolic weight. Use Gauss-Legendre in cos γ over
     the cap, and the azimuth average analytically: P_n of the angle to the source
     averages to `P_n(cos θ) P_n(cos γ)` by the addition theorem.
   - Choose the radius so that the cap-weighted low-frequency path equals the body's `d`
     (≈ 3a for small caps), and the cap so that its area matches the diaphragm's.
   - It gives the gradient's low-frequency limit exactly, the saturation of the gradient,
     the front build-up (+6 dB) and the rear shadow at every angle, all reciprocal and
     causal.
   - `entry_pressures` applies the two complex factors in the frequency domain, as `_delay`
     does now. Precompute per angle for prints.
   - Tests:
     - the LF limit (`1 + (3/2) jka cos γ`);
     - the front pole → 2 at ka ≫ 1;
     - the plane-wave free-field check `ka → 0`;
     - the new entries reduce to the old delay model at low frequency.
2. **Next: the low-frequency `d` of the real body by potential flow.** An axisymmetric
   Laplace boundary solve of the capsule plus head basket gives the exact
   low-frequency path, the quantity the cardioid condition and `R_a` hinge on (Lamb's
   disk: 1.02a mode-weighted for a thin disk). It is cheap on the CPU and replaces a
   fitted `path_m`.
3. **Later (the plan's fidelity item, now a prerequisite): a body-of-revolution BEM** of
   the capsule (a short cylinder with a rim) plus basket.
   - Helmholtz, azimuthal orders solved separately, which is exact for any angle. Use the
     GPU per the plan, with the sphere as its verification case (its analytic series).
   - Check against Wiener 1949's measured disk curves and Muller, Black & Dunn's
     front-face data.
   - Tabulate `H_f(f, θ)`, `H_r(f, θ)` as the component's diffraction data.
   - This adds the flat face's edge-ring peak (up to ~10 dB near ka ≈ π, Boré & Peus) that
     the sphere lacks.

Validation targets, sourced:
- Boré & Peus: up to 10 dB build-up on axis.
- Peus: the M 7 omni +6 dB at high frequencies; the M 7 cardioid "flat presence boost of 3
  to 4 dB".
- Peus: the 50 mm M 1-2 build-up of >12 dB, as a sanity check of the BEM on a bigger
  face.
- Neumann's 1952 / 1958 responses.

### 5.4 Open points

- **The through / blind split of the 153 holes, and the gap.** No source. These are the
  two most sensitive unknowns (`R_a` goes as 1/h³ and with the drain count). A K 47 / K 49
  drawing from Neumann's service, or one measured capsule, would settle them.
- **Whether Neumann's 1958 polars were measured in the far field.** Not stated. It decides
  whether 11.7 dB at 100 Hz is a far-field target.
- **The M 7's "middle rim".** It may be the patent's low-frequency path extension (the
  gauze ring's job). Speculative; a body BEM would show its effect on `d`.
- **Torio & Segota's example values reproduce their stated corners only to 12%.** The
  formulas are self-consistent; one printed value is presumably rounded.
