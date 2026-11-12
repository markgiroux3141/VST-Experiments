# Tape particles: a literature study for a particle-level bench

2026-11-12, overnight research (no code changed). The question: is a detailed particle
simulation (thermally activated, interacting Stoner-Wohlfarth macrospins, kinetic Monte
Carlo; not LLG) worth building as a "virtual bench" that calibrates the cheap Preisach
model of Scotch 111 (TAPE_PLAN.md, "The model", TM2 steps 6-7)? It is worth it only if,
built from physical particle parameters and fitted to static data (Sound Talk Nos. 20,
22), it predicts the dynamic bias curves of No. 21 without being fitted to them.

Conventions: SI first, cgs in brackets where the literature is cgs (1 Oe = 79.58 A/m;
1 emu/cm^3 = 1 kA/m; 4 pi M [G] = 4 pi x M [kA/m]; 1 erg/cm^3 = 0.1 J/m^3). kT at 293 K = 4.04e-21 J = 0.0253 eV.

Source tags: **[read]** = the number was read in the source in this session (page or
table given); **[abstract]** = only the abstract or an index record was available;
**[memory]** = recalled, not checked in this session; `provisional: model knowledge
(...)` = no source found, a range from physics or general knowledge; **[derived]** =
computed here from the cited inputs (formula given). Nothing below was fitted.

Status of this file: complete (section 1 written first for the other sessions; sections
2-5 added after). Section 5 is the verdict.

---

## 1. Parameter table: 1950s acicular gamma-Fe2O3 audio tape

### 1.1 What is known about Scotch 111 itself

| Quantity | Value | Source |
|---|---|---|
| Coercivity Hc | 270 Oe (21.5 kA/m) | Eilers, "3M Audio Open Reel Tapes, in Customary Units", AES Historical Committee 2011, p.1 row 111 [read] (`data/datasheets/tape/aes_3m_audio_open_reel_products.pdf`) |
| Retentivity Br | 900 G (90 mT), i.e. Mr = 71.6 kA/m | same [read] |
| Remanent flux | 0.64 lines per 1/4" (~1.0 uWb/m) | same [read] |
| Coating thickness | 0.5 mil (12.7 um) on 1.42 mil acetate | same [read] |
| Oxide | acicular gamma-Fe2O3 ("red oxide"); 3M's first acicular-oxide tape was #111 (1948) | Eilers table lists 111A as 1948; that the particles were acicular gamma: provisional: model knowledge (industry history; not found in a primary 3M source this session) |
| Major loop measurement | 60 Hz B-H meter, 1000 Oe peak; "essentially saturated in this field"; B = J + H plotted | Sound Talk No. 22 (Mar. 1953) p.1 [read] |
| Remanence curve | 60 Hz meter, remanence after unsaturated symmetric loops; samples +-10% | Sound Talk No. 20 p.1 [read] (digitized: `data/datasheets/scotch_111_remanence.csv`) |
| No. 21 test condition | audio current "about 20 db below that required to give a 1% distorted signal"; Ampex 300, 15 ips, 70 kc bias, 0.002" record gap, NARTB EQ | Sound Talk No. 21 (Feb. 1953) p.1 [read]. **No. 21 is a small-signal measurement: its bias curves are the anhysteretic (bias) susceptibility against bias amplitude, not a large-signal transfer.** |
| Squareness Mr/Ms | not printed for #111 | No. 22's loops are drawn without labels per type on p.2 and in B (not J); a squareness can't be read cleanly. TAPE_PLAN.md TM1 already dropped this check. |
| Particle size, SFD, packing, orientation | not printed by 3M in the bulletins archived | (all bulletins in `data/datasheets/tape/` read this session) |

**[derived] The coating's packing x squareness.** Mr = p S Ms_p, with p the packing
fraction, S the squareness and Ms_p the particle's magnetization. With Mr = 71.6 kA/m
(Eilers) and Ms_p = 360-389 kA/m (below): **p S = 0.18-0.20**. An unoriented 3D ensemble
of SW particles has S = 0.5; a 2D in-plane random one 0.64; so p = 0.28-0.40 for S =
0.5-0.7. The project's provisional p = 0.35 (SCOTCH111@3) implies S = 0.53-0.57, i.e. a
nearly unoriented coating, consistent with the fitted kappa = 1.5 (a weak in-plane
orientation; SCOTCH111@3's `orientation`).

### 1.2 The material: bulk gamma-Fe2O3 (maghemite)

| Quantity | Value | Source |
|---|---|---|
| Density | 4.86 g/cm^3 | Draine & Hensley, arXiv:1205.7021 (2012), Table 1 [read] |
| Ms, low temperature | 4 pi Ms = 4890 G -> Ms = 389 kA/m | same, Table 1 and Sec. 2.3, citing Dutta et al. 2004 [read]; they note it is ~70% of the ideal (10/3) muB per formula unit (7100 G) |
| Ms, room temperature | 3.8 x 10^5 A/m | arXiv:2404.07769 (2024), Table 1, citing Dunlop & Ozdemir [abstract-level: read in a search snippet of the table, not the PDF] |
| Ms per mass, recording particles | 56-74 A m^2/kg (= emu/g) measured, reduced from ideal | Springer abstract, doi:10.1007/BF00203200 [abstract]. 74 emu/g x 4.86 g/cm^3 = 360 kA/m [derived] |
| Ms range to use | **360-389 kA/m**; 74 emu/g at RT is the figure usually quoted for tape oxide | the two rows above; "74 emu/g" for tape-grade particles [memory] (Mee & Daniel, Magnetic Recording Technology, particle table) |
| K1 (cubic), RT | -4.6 x 10^4 erg/cm^3 = **-4.6 kJ/m^3**; easy axes <111> | Draine & Hensley Sec. 2.3 citing Buschow 1995 [read]; also arXiv:2404.07769 Table 1 (-4.6e3 J/m^3) [snippet]. They call maghemite's K1 "uncertain"; Valstyn et al. 1962 found -2.5e5 erg/cm^3 in powders [read, same section] |
| Exchange stiffness A | 1 x 10^-11 J/m | arXiv:2404.07769 Table 1, citing Dunlop & Ozdemir [snippet] |
| Exchange length l_ex = sqrt(2A / (mu0 Ms^2)) | 11 nm (Ms 360 kA/m) | [derived] |
| Curie temperature | ~870 K (stability limit: converts to alpha-Fe2O3 near 670 K) | Draine & Hensley Sec. 2.3 [read]; 673 K transition from the ACS Appl. Nano Mater. 2020 search snippet [abstract] |

### 1.3 The particle

| Quantity | Value | Source |
|---|---|---|
| Shape | acicular (needles grown from goethite, alpha-FeOOH, dehydrated, reduced to Fe3O4, reoxidized to gamma) | general tape patents, e.g. US 3047428 [abstract]; provisional: model knowledge for #111's process |
| Length | 0.4-1.0 um for 1950s audio oxide (later oxide 0.3-0.5 um) | patents: "acicular gamma ferric oxide ... length less than about 1.5 microns" (Kodak), "below one micron" (search snippets) [abstract]; a 1980s particle: 0.46-0.5 um, axis ratio 8-11, 365-370 Oe (US 4693931; snippets) [abstract]. For 1948-1953 oxide: provisional: model knowledge (0.5-1 um, the earliest acicular oxides were larger than later ones) |
| **Period electron micrograph** | gamma-Fe2O3 tape particles "about 0.5 x 0.1 u" (um), ~10^10 particles per second past the head at 0.76 m/s | Westmijze, "The fundamentals of magnetic recording", lecture of 17 June 1955, Tijdschrift NRG 21 (1956), pp. 12-13 and Fig. 10 [read] (web: https://soundandscience.net/wp-content/uploads/2023/03/1126_NAG_Publicatie_No_56a_Westmijze_The_fundamentals_of_magnetic_recorder_1956.pdf). Philips / European tape of 1955, not #111, but the same oxide generation: **the best period number found** |
| Hc against mean particle length (TDK acicular gamma-Fe2O3, 1970) | 280 Oe at 0.17 um, peak ~350 Oe at 0.34 um, 300 Oe at 0.5 um, ~265 Oe at 0.8 um | Tochihara, Imaoka & Namikawa, IEEE Trans. Magn. 6, 808 (1970), Fig. as redrawn in Manly, "Thinking about print-through in analog tape", Audio, Sept. 1977, Fig. 8A [read off the figure, +-5 Oe] (web: https://gammaelectronics.xyz/audio_09-1977_print-through.html). #111's 270 Oe sits on the long-particle side of this curve, consistent with 0.5-0.8 um particles (an inference, not a measurement of #111) |
| Aspect ratio (length / width) | 5:1 to 10:1 (Westmijze's micrograph: ~5:1) | prior-art range "between 5 and 10 to 1" in a gamma-Fe2O3 patent [abstract]; the 1967 JAP study used 5:1 tape particles [abstract] |
| Width | 0.06-0.15 um | [derived] from length / aspect ratio |
| Volume | ~1-5 x 10^-21 m^3 | [derived]; the project's own noise fit (Sound Talk No. 34) gives 1.62 x 10^-21 m^3 (~0.4 x 0.07 um), SCOTCH111@3 `noise` |
| Length and volume distributions | lognormal, sigma_ln(length) ~0.3-0.5, sigma_ln(V) ~0.6-1.0 | provisional: model knowledge (electron-micrograph statistics of goethite-route oxides; no period histogram found this session) |
| Crystallites | a particle is polycrystalline (pores and grain boundaries from the dehydration); Hc falls with crystallite size; crystallites interact across non-magnetic boundaries | "Influence of Crystallite Size on the Magnetic Properties of Acicular gamma-Fe2O3 Particles", J. Appl. Phys. 39, 1261 (1968) [abstract] |

### 1.4 Anisotropy, switching and the incoherence reduction

| Quantity | Value | Source |
|---|---|---|
| Shape anisotropy field Hk = dN Ms (prolate spheroid) | aspect 5: dN = 0.416 -> 150-162 kA/m (1880-2040 Oe); aspect 8: dN = 0.457 -> 165-178 kA/m (2070-2240 Oe); needle limit Ms/2 = 180-195 kA/m | [derived] (spheroid demagnetizing factors, Ms 360-389 kA/m) |
| Crystalline anisotropy field, cubic K1 < 0: Hk = 4|K1| / (3 mu0 Ms) | ~13 kA/m (~170 Oe) | [derived] from K1 = -4.6 kJ/m^3, Ms 360 kA/m |
| Shape vs crystalline share of measured Hc | shape ~67% of the room-temperature Hc for 5:1 acicular gamma-Fe2O3; the shape term nearly independent of diameter, fitting the chain-of-spheres model | "On the Coercivity of gamma-Fe2O3 Particles", J. Appl. Phys. 38 (1967) [abstract]; authors Eagle & Mallinson [memory, not checked] |
| Ideal SW (coherent) switching field, field along the axis | = Hk, ~1900-2200 Oe for aspect 5-8 | [derived] |
| Ideal SW random-ensemble coercivity | 0.479 Hk ~ 900-1060 Oe | [derived] (Stoner-Wohlfarth 1948's random-ensemble factor 0.479 [memory]) |
| Measured tape Hc | 250-370 Oe (#111: 270) | Eilers [read]; patents [abstract] |
| **Incoherence reduction** | measured / ideal SW ~ **0.13-0.2 of Hk** (0.25-0.4 of the random-ensemble coherent Hc) | [derived] from the rows above. Mechanisms in the literature: fanning in a chain of spheres (Jacobs & Bean, Phys. Rev. 100, 1060 (1955) [abstract]: proposed because elongated particles switched well below the coherent-rotation value), curling (Frei, Shtrikman & Treves 1957 [memory]), polycrystallinity and pores (1968 JAP [abstract]), packing interaction (below) |
| Curling nucleation field (infinite cylinder, field on axis), H_n = Ms (1.08 l_ex^2 / R^2 - N_par) | width 50 nm, aspect 5: 56 kA/m (710 Oe); width 70 nm, aspect 5-8: 19-29 kA/m (240-360 Oe); width 100 nm: ~0-9 kA/m | [derived] (Aharoni's curling formula, q = 1.08 [memory]; A, Ms above). Curling puts measured-size particles at the measured Hc, but it is steep in width (R^-2) and A is uncertain: treat it as plausibility, not a prediction |
| Coherent-to-curling crossover radius R_c = l_ex sqrt(1.08 / dN) | ~17 nm (width ~35 nm) | [derived]: 1950s particles (60-150 nm wide) are deep in the incoherent regime |
| Switching-field distribution (SFD) of the ensemble | lognormal sigma_ln ~0.28-0.33 (the project's static fit to No. 20 + Hc) | SCOTCH111@1-3 fits [read: config/components/scotch111/3.yaml: sigma_ln 0.283, median 20.0 kA/m] |
| SFD (Delta H / Hc from dM/dH FWHM) of period oxide tapes | 0.3-0.6 | provisional: model knowledge (gamma-oxide audio tapes; later "high output" oxides were narrower; Scotch 250 advertised "particles more uniform in size and needle shape", R-e/p Dec. 1974 [read in the archived PDF's README extract]) |
| Interaction field spread sigma_Hi (Preisach) | 46-64 Oe (3.7-5.1 kA/m) | project fit, SCOTCH111@1 and @3 [read] |

### 1.5 Coating

| Quantity | Value | Source |
|---|---|---|
| Packing fraction p | 0.28-0.40 (p S = 0.18-0.20, see 1.1) | [derived]; the Knowles packing model was compared with tapes for 0 <= p <= 0.4 (IEEE Trans. Magn. 1985 [abstract]); SCOTCH111@3 uses 0.35 (provisional) |
| Orientation | #111 (1948) predates deliberate magnetic orientation in coating; weakly in-plane by the coating's flow | provisional: model knowledge (orientation magnets in coating lines are a 1950s-60s development; not dated from a primary source this session). The project's No. 21 fit gives kappa ~1.5 (in-plane axial von Mises) |
| Squareness S | 0.5-0.6 (nearly unoriented) | [derived] from p S and p; random-3D SW = 0.5 [memory, standard SW result] |

### 1.6 Thermal activation

| Quantity | Value | Source |
|---|---|---|
| Barrier law | E(H) = K V (1 - H / H0)^m, m = 2 for aligned SW, ~1.36-1.5 for random axes (see the note below the table) | Sharrock, J. Appl. Phys. 76, 6413 (1994) "Time dependence of switching fields in magnetic recording media" [abstract]; the project's `tape_switching_study.py` docstring uses Hc(t) = H0 [1 - (ln(f0 t / ln2) / (KV/kT))^n], n = 1/2 aligned, 0.735 random |
| Time-dependent coercivity in tape oxides | exists and grows as the switching unit shrinks; short-time ("writing") coercivity > long-time ("storage") coercivity | Sharrock & McKinney, IEEE Trans. Magn. 17, 3020 (1981), doi:10.1109/TMAG.1981.1061755 [abstract] |
| KV/kT of gamma-Fe2O3 tape particles (from Hc vs sweep rate / viscosity) | **not found as a number for period audio oxide this session.** Brackets: physical volume with coherent K = mu0 Ms Hk / 2 -> ~2000 (project's study); a modern nanoscale gamma-Fe2O3 tape ~100 (ACS Appl. Nano Mater. 2020, KuV/kT ~100 from time-dependent coercivity [abstract]); a 0.4 um acicular oxide with an activation volume ~1/10-1/30 of the particle: provisional: model knowledge, **KV/kT ~ 60-400** (the range the project's study bracketed with 60 / 150 / 400) | as stated |
| Switching volume vs particle volume | the Sharrock barrier model gives switching volumes "in good agreement" with particle volumes for acicular oxide, acicular metal and barium ferrite (with an adjusted energy expression) | Sharrock 1994 [abstract] |
| Print-through and time dependence | print-through correlates well with the time-dependence parameter (S_v or dHc / d ln(rate)) across iron oxide tapes with and without cobalt | Flanders & Sharrock, J. Appl. Phys. 62, 2918 (1987) [abstract] |
| Viscosity peak | magnetic viscosity effects peak at fields near Hc and scale with print-through | Flanders, IEEE Trans. Magn. 22, 145 (1986), doi:10.1109/TMAG.1986.1064301 [abstract] |
| Print-through activation energy (from its temperature dependence) | ~0.05 eV for the smallest acicular gamma-Fe2O3 particles, ~0.15 eV for the others; print grows as the axial length shrinks and with contact time | Tochihara, Imaoka & Namikawa (TDK), IEEE Trans. Magn. 6, 808 (1970) [abstract]. These are field-reduced barriers of the population that prints, not KV |
| Superparamagnetic threshold | KV/kT ~ 25 for remanence over ~100 s | widely used criterion (US 6307817 [abstract]); a particle with E/kT ~25-40 in the stray field prints |
| Attempt frequency f0 | 10^9-10^10 Hz (10^9 the usual choice for oxide particles) | provisional: model knowledge (Sharrock's papers use 10^9 Hz [memory]); the result depends on it only through ln(f0 t) |
| ln(f0 t) at the time scales that matter (f0 = 10^9) | 60 Hz loop (~3 ms per half cycle): ~15-16; a bias half-period at 70 kHz (~7 us): ~9 (the project used a 0.1 rad window near the peak: 5.8); a week on the shelf: ~34 | [derived] |

Note on the exponent: for the energy barrier E = KV (1 - H/H0)^m, aligned SW gives m = 2
and Sharrock's Hc(t) exponent is n = 1/m = 1/2; random orientations give m ~1.36-1.5
(n ~0.67-0.735). The project's study uses n.

### 1.7 What follows for a particle bench (short)

- The ideal SW numbers are ~5x too hard. A bench of SW macrospins would need either an
  "effective particle" (a reduced Hk fitted to No. 22's Hc, i.e. a fit, not a prediction)
  or a chain-of-spheres / curling sub-model (whose answer swings by 2-3x with the width
  and A). **The bench can't predict Hc from the particle; it must be fitted to the static
  data first**, which is the plan anyway.
- The thermal parameter that matters (the activation volume, KV/kT) is the least known
  number in the table: no period measurement found. The project's study already ran the
  plausible range (60-2000) and found <= 0.4 dB on No. 21.

---

## 2. AC-bias recording with interacting particles

### 2.1 What shapes a bias curve (the literature's mechanisms)

All sources agree on one picture: a particle's state freezes where the decaying bias
amplitude it sees falls below its switching field, and it keeps the signal field present
at that moment. The bias curve's shape then comes from where that freezing contour lies.

| Mechanism | What it does to No. 21's curves | Source |
|---|---|---|
| Freezing at the contour "bias amplitude = Hc"; the signal field there is recorded through an anhysteretic susceptibility tensor (longitudinal and vertical fields) | the rise: the contour reaches deeper into the coating as bias grows; the long-wavelength fall: past full depth, the contour moves away from the gap where signal and bias fall together, so the recorded signal field ~ Hc x (I_signal / I_bias) | Bertram, "Long wavelength AC bias recording theory", IEEE Trans. Magn. 10, 1039 (1974) [abstract: "excellent quantitative agreement" with measured sensitivity, the shape of sensitivity vs bias "correlates well"; no demagnetization and **no switching-field spread** in that model]; McKnight, "Biasing magnetic tape in recording", Electronics World, Aug. 1967, p.34 and Fig. 1C [read: with the DC and AC fields decreasing together, "increasing the a.c. up to a certain point has the same effect as before but beyond this point the magnetization decreases"] |
| A spread of switching fields and the coating's depth spread the freezing over an area: the signal is averaged over the time a particle crosses it | the short-wavelength loss and its growth with bias; "the greater the spread in the coercive force and the thicker the tape, the larger this area" | Westmijze 1956 (lecture), pp. 4-5 [read]; the same in Westmijze, Philips Res. Rep. 8 (1953) [memory, the report itself not found online] |
| The recording point moves downstream with bias | the recorded signal's phase shifts almost linearly with bias level; hence HF falls with bias | Hinrichs, "On the theories of AC bias used in magnetic tape recording", IEEE Trans. Audio AU-11, 78 (1963), p.81 and Fig. 6 [read] (web: https://worldradiohistory.com/Archive-IRE/60s/Audio/IRE-Transactions-On-Audio-1963-05-06.pdf), citing Daniel, Proc. IEE 100 III, 168 (1953) |
| Short wavelengths peak at lower bias | "the current for maximum sensitivity is the same over a wide range of low frequencies ... as frequency increases ... the maximum sensitivity occurs at lower and lower currents" | McKnight 1967 p.35, Fig. 1E [read] |
| The output depends on the bias peaks only, not the bias waveform; the bias itself is not recorded | sine, square and triangle bias with equal peaks gave the same output | Hinrichs 1963 pp.79-80 [read]. Supports a rate-independent (extrema-only) model like the project's |
| Interparticle interactions set the anhysteretic susceptibility | "strength and sign of interparticle interactions largely determine the anhysteretic susceptibility of strongly interacting systems"; varying them by temperature changed it by up to 50% | Spratt, Fearon, Bissell, Lyberatos, Chantrell & Wohlfarth, IEEE Trans. Magn. 24, 1895 (1988) [abstract] |
| Relevance of the bias-curve slope to AC bias in general | "the initial anhysteretic susceptibility of tapes is central to high-frequency bias sensitivity" | review on fine-particle interactions in recording (scilit record 585bfe31...) [abstract] |

The project's step 7 already contains Bertram's two mechanisms (vector fields, the head's
image for the over-bias fall) plus demagnetization; the 1 kHz over-bias fall it gets with
the image (-3.2 to -3.6 dB at 8 mA) is the size of Bertram's 1 / I_bias law: the measured
peak at ~5.5-6 mA and 8 mA give 20 log(5.5..6 / 8) = -2.5 to -3.3 dB [derived], against -3.3 measured. **The residual
misfit is the rise (too steep) and the 15k-1k spread (too small), i.e. the freezing
happens over too narrow a range of bias amplitude.** In this picture the width of the rise
is the width, in bias amplitude, of the population that freezes: the switching-field
distribution as it acts under a decaying AC field, convolved with the depth profile of
the head field.

Two numbers frame it [derived]:
- The Ampex 300's 51 um record gap barely changes the deep-gap field over the coating: the
  Karlqvist field on the gap's centre line falls as atan(g / 2y), so between the coating's
  front (y ~0.5 um) and back (y ~13 um) it falls by atan(25.4/13.2) / atan(25.4/0.5) = 0.70,
  i.e. 3 dB. Depth alone gives a rise ~3 dB wide in bias.
- The fitted lognormal SFD (sigma_ln 0.28) spans its 10-90% range over a factor
  exp(2 x 1.28 x 0.28) = 2.05 in field, 6.2 dB.
- Measured, 1 kHz rises from -20.4 dB to the peak over roughly 2 -> 6 mA, 9.5 dB of bias.
  A rise that wide needs either a wider effective switching distribution under AC than
  the 60 Hz remanence curve shows, or a head field that isn't proportional to current.

### 2.2 Does a Preisach model fitted to DC data predict AC processes? (the bench's question)

| Finding | Source |
|---|---|
| A Preisach model identified on particulate media "agreed well with DC remanence measurements but fit AC measurements less well" | Stancu et al., J. Magn. Magn. Mater. 193 (1999), "Interactions characterisation in particulate magnetic recording media. Experiments and Preisach model" (VHS gamma-Fe2O3 tape: AC demagnetization, anhysteretic remanence) [abstract via search snippets; full text not reached] |
| AC-biased, DC-biased and partial-anhysteresis processes on an SVHS tape modelled with the generalized moving Preisach model, parameters identified from major loop, IRM, DCD, first magnetization and the integral generalized Delta-M curve | Bissell, Ardeleanu, Postolache, Cerchez & Stancu, IEEE Trans. Magn. 37, 1624 (2001) [abstract] |
| Commercial gamma-Fe2O3 and Co-gamma-Fe2O3 tapes violate the congruency of minor loops: the **moving** model fits, the product model doesn't | Vajda & Della Torre, "Measurements of output-dependent Preisach functions", IEEE Trans. Magn. 27, 4757 (1991), doi:10.1109/20.278938 [abstract] |
| The mean-field (moving) term is usually **positive** in acicular particle systems ("a disruption of the good geometry by agglomeration and poor dispersion"), negative in well-dispersed MP (-330 Oe) and positive in BaFe (+460 Oe) | Cerchez, Stoleriu & Stancu, J. Optoelectron. Adv. Mater. 5, 351 (2003), pp. 352-353, Table 1 [read] (web: https://old.joam.inoe.ro/arhiva/pdf5_1/Cerchez.pdf). No gamma-Fe2O3 value in that table |
| A Monte Carlo of chain-of-sphere particles with circulating interaction-field sets reproduces "the principal features" of anhysteresis in tapes | Knowles, "Anhysteresis in tapes: a Monte Carlo treatment", IEEE Trans. Magn. 23, 201 (1987) [abstract]; Knowles' packing model gave Hc(p) for 0 <= p <= 0.4 (1985) [abstract] |
| A computer simulation of bias recording explains the linearization of the remanence curve and the maximum output level against media parameters, checked against experiment (Bayer AG; a second paper on 10 kHz saturation output in cassettes "in quantitative agreement") | Eiling, IEEE Trans. Magn. 24, 2235 (1988), doi:10.1109/20.3433 [abstract]; Eiling 1990 [abstract] |
| Interaction parameter values for gamma-Fe2O3 tape (a moving alpha or a mean field in Oe) | **not found as a number in this search**; Cerchez's table has BaFe and MP only. Provisional: model knowledge, a positive mean field of order 0.1-0.3 of the coercivity for an agglomerated acicular coating (i.e. ~30-80 Oe for #111), sign and size to be fitted |

Where this leaves the plan:
- The literature directly supports the worry: a Preisach model identified on DC
  remanence data (like No. 20) is known to predict AC processes less well in particulate
  tape. So a mismatch on No. 21 is expected from the model class, not only from the
  heads. Whether a particle model fixes it isn't settled by anything found here.
- Prior particle simulations of anhysteresis exist (Knowles 1987, Spratt / Chantrell's
  group 1988, the Iasi group's LLG ensembles), but **a particle-level simulation of
  moving-head AC-bias recording that reproduces measured bias curves was not found in this
  search** (Eiling 1988 may be the closest; its method isn't in its abstract).
- Does a mean field widen bias curves? In a moving model the anhysteretic susceptibility
  becomes chi0 / (1 - alpha chi0) (positive alpha raises it and steepens the transfer);
  it acts on the transfer curve, not on which particles freeze at which bias amplitude.
  It should therefore move the 3% THD knee more than the bias curves' width. This is an
  argument from the model's structure [derived], not a published result.
- What could widen them: an interaction field that changes during each bias cycle (the
  neighbours flip with the bias: a "dynamic" interaction, which a static Preisach
  interaction field per hysteron can't represent; the Iasi group's models add a dynamic
  interaction term and a "thermal variable variance", Borcia, Spinu & Stancu, JOAM 4, 307
  (2002) [read: Neel relaxation times with an attempt frequency "about 10^9 s^-1"]), or
  correlated reversal of agglomerates (Cerchez's positive mean field). These are the
  mechanisms a dipolar-interacting particle bench would add, and the only ones on this
  list it could test.

### 2.3 Thermal effects on recording

Covered by the project's own study (scripts/tape_switching_study.py, TAPE_PLAN.md item 3):
<= 0.4 dB over the plausible barrier range. Nothing found in the literature contradicts
it: Sharrock & McKinney (1981) and Sharrock (1994) describe the rate effect as large only
for small switching units, and the period oxide's particles are large (Section 1.6).

---

## 3. Print-through

### 3.1 The physics

- Mechanism: the field of a recorded layer reaches the neighbouring turns at a few Oe,
  far below Hc, and over time switches the particles whose barrier is near kT ln(f0 t):
  "in magnetic domains where the local coercive force is small, the direction of
  magnetization is changed under the combined action of the small disturbing field, and
  the thermal agitation" (Westmijze 1956, pp. 14-15 [read]). Manly (Audio 1977 [read])
  gives the same picture with Bean & Livingston's 25 kT transition zone and a lognormal
  volume distribution whose low tail does the printing.
- The stray field: mu0 H = (pi d B0 / lambda) e^{-2 pi Delta / lambda} at distance Delta
  from a layer of thickness d and induction B0; maximum at lambda = 2 pi Delta; for
  Delta = 55 um and B0 = 80 G, ~5 Oe (Westmijze 1956, p.14 [read]). A tape of 250 Oe Hc
  prints in it, growing "logarithmically with time" (his Fig. 11 [read]: printed flux
  linear in log t from 10 s to ~2 x 10^4 s, ~0.36 to ~1.35 x 10^-12 Wb, i.e. M(t) ~ S
  ln(t / t0) with t0 ~ 1 s [derived, read off the figure]).
- Particle size: print rises steeply as the mean particle length falls below the length
  of peak Hc: -49.5 dB at 0.8 um, -47.5 at 0.4, -46.5 at 0.3, -38 dB at 0.17 um
  (Tochihara et al. 1970, as redrawn in Manly 1977 Fig. 8B [read off the figure, +-0.5 dB]);
  activation energies from the temperature dependence: ~0.05 eV for the smallest
  particles, ~0.15 eV for the others (Tochihara 1970 [abstract]).
- Correlation with magnetic viscosity: print-through tracks the time-dependence parameter
  (Flanders & Sharrock, J. Appl. Phys. 62, 2918 (1987) [abstract]) and the viscosity near Hc
  (Flanders, IEEE Trans. Magn. 22, 145 (1986) [abstract]). Stafford, "A print-through
  constant for magnetic particles", IEEE Trans. Magn. (1976) [abstract]: print at the
  optimum wavelength = a constant + 10 log(retentivity x coating thickness / base
  thickness).
- Standard treatments named in the brief: Neel's relaxation (1949) [memory]; Tochihara
  1970 [abstract]; a Bertram print-through theory **was not found** (Bertram's book chapter
  on thermal effects wasn't reachable); Daniel & Axon, "Accidental printing in magnetic
  recording", BBC Quarterly 5, 241-256 (1950), and Westmijze, "Studies on magnetic
  recording VI: change in the recording with time", Philips Res. Rep. 8, 354-366 (1953),
  are the primary period studies (cited by Manly; not found online).

### 3.2 The numbers in Sound Talk Nos. 10 and 38 (read in full this session)

Both bulletins are qualitative: **neither has a measured curve, a table, or a figure with
data** (No. 10 has no figures; No. 38's Figs. 1-3 are wind diagrams). What they state:

| Statement | Bulletin, page |
|---|---|
| "The effect is non-linear; i.e. transfer is like recording with no bias. The transfer level will decrease perhaps 2 db. for each 1 db. decrease in recording level." | No. 10, p.1, col. 1 |
| Grows with storage time "over a period which may vary from several days to several months"; "cannot usually be detected except after considerable time" | No. 10, p.1 |
| Temperature coefficient "approximately 1 db. per 10 deg F" (1.8 dB per 10 K), "not the same for all tapes and all times of storage" | No. 10, p.1, col. 2 |
| Stray AC or DC fields "can act to increase the transfer by a few or even 30 or 40 db"; "fields of only a few oersteds" noticeably increase it, while "several hundred oersteds" are needed for measurable erasure, "one or two thousand" for complete erasure | No. 10, p.1, col. 2 |
| Frequency: "middle frequencies most important"; long wavelengths weak (weaker field for the same magnetization) and short wavelengths weak (the base's spacing loss); a thicker base helps "mainly in the higher frequencies" | No. 10, pp.1-2 |
| Normally "well below the noise level" | No. 10, p.2 |
| The next **outer** layer (oxide-in wind) prints more than the inner: the field passes the base only, against base plus oxide | No. 38 (Ray Smith, 15 Aug. 1960), p.1 |
| Stored tails-out (on the take-up reel) the stronger print plays as **post-print** (masked by the signal); stored on the supply reel, as pre-print | No. 38, pp.1-2, Figs. 2-3 |
| "Measured a few minutes after removal from intimate contact ... the printed signal will show a drop of 6 db or more from the level measured seconds after removal" | No. 38, p.2 ("Removal") |

### 3.3 Numbers from the period data that 3M didn't print

From Manly, Audio Sept. 1977, which redraws the 1947-1953 studies (Lippert 1947, Daniel &
Axon 1950, Westmijze 1953, Johnson); the author warns that the 1950-vintage numbers "may be
somewhat exaggerated" for 1977 tape and are "indicative" [all read off the figures]:

| Quantity | Value | Figure |
|---|---|---|
| Print vs storage time, constant temperature | a straight line in dB against log t: **-56.5 dB at 10 s, -52 dB at 5 min, -40 dB at 1 week: 3.45 dB per decade of time** | Fig. 1 (Lippert, Daniel & Axon, Westmijze) |
| Decay after separation | an immediate ~2 dB drop, then 6 dB in ~3 min for a 5-minute print; a 1-week print needs nearly a week to drop 6 dB (on the figure ~-46.5 dB at 10^6 s, ~-52 dB at 10^7 s, ~-54.5 dB at 1 year); "the final decay rate is roughly the negative of the earlier rate of increase" | Fig. 1, text |
| Temperature | at 1000 s: -50 / -45 / -40 / -35 dB at 100 / 150 / 200 / 250 deg F: **5 dB per 50 deg F** (1.8 dB per 10 K); this tape's time slope ~8 dB per decade (100 deg F: -58 dB at 100 s, -42 dB at 10^4 s) | Fig. 2 (Daniel & Axon, Westmijze, Johnson) |
| Heat-induced print | persists after cooling, more stable than room-temperature print | text |
| Wavelength | peak at **lambda = 2 pi d** (d the overall tape thickness); "1.5 mil" tape (1.9 mil overall, the #111 class) peaks at ~-40.5 dB near 0.012 in (0.3 mm); long wavelengths fall ~20 dB per decade of wavelength toward -51 dB at 0.1 in | Fig. 3 (Daniel & Axon), Table I |
| Level law | "print-through is dB-linear", the printed level a fixed number of dB below the master **at any master level** | text, p.1 |
| Pre vs post | pre-print exceeds post-print by up to 12 dB (Daniel 1961, Rhodes 1961); with equal horizontal and vertical printing, post-print nearly vanishes and pre-print rises ~6 dB | text |
| External AC field (5 min storage, 2 min rotated in the field) | -60 dB at 0, ~-58 at 5 Oe rms, -55 at 10, -52.5 at 15, -50 dB at 20 Oe rms | Fig. 6 (Daniel & Axon) |
| Winding tension | higher tension prints more short-term; after overnight, no difference | text (Daniel & Axon) |
| Typical well-stored modern (1977) tape | -55 to -60 dB; Westmijze 1956: "most modern tapes ... not exceeding 55 dB" | text; Westmijze p.15 [read] |
| Industry test | 4 h at 150 deg F, cooled, measured at the peak wavelength | text |

Checks [derived]:
- **The level law.** 3M No. 10 (2 dB per dB) and Manly (1 dB per dB) disagree. The
  wavelength data side with Manly: a print linear in the stray field peaks where k e^{-k d}
  peaks, at lambda = 2 pi d, and falls 20 dB per decade at long wavelengths, as Fig. 3
  shows; a square-law print would peak at lambda = pi d and fall 40 dB per decade. 3M's
  "like recording with no bias" may describe their 1950 tapes or overloaded material; the
  minimal model should take 1:1 and keep 2:1 as a variant.
- **Time and temperature are one Neel-Arrhenius law.** The printing population has barriers
  E* = kT ln(f0 t). Raising T by dT at fixed t equals multiplying t by (f0 t)^(dT/T): at
  ln(f0 t) = 30 (f0 10^9 Hz, t ~ 3 h) and T = 300 K, +10 K is 0.43 decades of time, i.e.
  0.43 x 3.45 = **1.5 dB per 10 K predicted against 1.8 measured** (3M No. 10 and Manly
  Fig. 2 agree on 1.8). The rest is consistent with Ms and K falling with temperature.
  Fig. 2's own tape (8 dB per decade) would predict ~3.4 dB per 10 K against its 1.8: a
  factor-2 miss for that composite, which Manly calls indicative only.
- **Delay and wavelength on #111 at 15 ips.** Overall thickness 48.8 um (Eilers), so the
  print peaks at lambda = 307 um: **1.24 kHz at 15 ips, 620 Hz at 7.5 ips**. Through the base
  only (36.1 um, the outer layer per No. 38) lambda = 227 um, 1.68 kHz at 15 ips. A layer's
  delay is its circumference over the speed: 2 pi r / v = 0.94 s at r = 57 mm (a 10.5 in
  NAB hub) to ~2.2 s at r = 133 mm, at 15 ips [derived; the reel radii provisional: model
  knowledge].

### 3.4 What a minimal print-through model needs

All linear, applied once per stored reel (a "condition dial": storage time, temperature,
wind direction, tails-out or not, time since rewind); no particle simulation:
1. The recorded tape's magnetization (the project already has it per cell).
2. The vector stray field of layer n at layers n +- 1 (both Hx and Hy, the closed-form
   e^{-k Delta} transfer; the base and oxide spacings of No. 38 for outer / inner).
3. A print susceptibility chi_p(t, T) per field component (longitudinal and
   perpendicular differ for an in-plane oriented coating; their ratio sets the pre / post
   asymmetry, up to 12 dB in the data). Its time law: 3.45 dB per decade (Manly Fig. 1);
   its temperature law through E* = kT ln(f0 t) (or 1.8 dB per 10 K directly); its level
   at one point: -52 dB at 5 min, -40 dB after a week at room temperature at the peak
   wavelength, for 1950-vintage tape (Manly Fig. 1; the same order as Westmijze's "not
   exceeding 55 dB" for 1955 tapes).
4. Decay after separation (rewind): the mirror of the growth (Manly Fig. 1; 3M No. 38's
   6 dB within minutes for a fresh print).
5. Optionally, stray AC fields: +10 dB at 20 Oe rms (Manly Fig. 6).
6. The reel geometry for the delays (layer by layer, the radius growing by the tape's
   thickness per turn), and the wind (oxide-in, "A" wind, for the 351).

Inside the project's framework, item 3 can come from the same Preisach ensemble if each
hysteron carries an energy barrier (a Preisach-Neel model, Borcia et al. 2002): the
printing population is the low-barrier tail, and the 3.45 dB per decade fixes its
slope [derived: amplitude ~ t^0.17, i.e. the cumulative barrier density rises as
e^{0.17 E / kT} near E ~ 25-35 kT]. That is the one place where a barrier distribution per
hysteron earns its keep; it costs nothing at run time (one integral per storage condition).

---

## 4. Modulation noise from particle clustering and packing

| Finding | Source |
|---|---|
| Demagnetized-tape noise estimated from the particle count (0.5 x 0.1 um, ~10^10 particles/s at 0.76 m/s) 80 dB below saturation, ~70 dB below the maximum signal, in a 10 kHz band (the order measured on demagnetized tape); magnetized tape is much noisier: "modulation noise" from fluctuations of sensitivity ("an irregular distribution of the magnetic particles, or ... thickness-variations of the coating"); a ~1% fluctuation in the number of magnetized particles gives modulation noise 40 dB below the signal, "the figure measured in practice"; partly masked by the signal; DC or bias recorded by accident makes it unmasked | Westmijze 1956, pp. 12-13 [read; the percentage is garbled in the scan, 1% is what -40 dB implies] |
| A general theory of the read-voltage spectrum from particulate media, DC and modulation noise for clustered media; ~10 dB discrepancy at short wavelengths on Fe2O3 tape, attributed to interactions | Thurlings, IEEE Trans. Magn. 16 (1980) and a 1979 companion [abstract] |
| AC and DC noise spectra of MP tape fitted by a clustering model: mean cluster length 2-4 particles; at long wavelengths both exceed independent-particle estimates, at short wavelengths fall below | Luo & Bertram (2001) [abstract] |
| Thick particulate tapes: demagnetized noise **lower** than saturation noise (a trough, from flux closure in clusters, centred above the remanent coercivity); thin coatings behave like thin films (noise peak at the coercivity); an LLG ensemble of 8000 particles reproduced the change with thickness | Stoleriu, Bissell, Mercer, Ardeleanu & Stancu, JOAM 4, 289 (2002), pp. 289-291 [read] (web: https://old.joam.inoe.ro/arhiva/pdf4_2/Stoleriu.pdf) |
| Particulate noise theory rests on Poisson statistics, valid only for point particles; correlations and clustering added in a simplified model | Bertram, Theory of Magnetic Recording (1994), "Medium noise mechanisms, part 2: particulate noise" (Cambridge chapter page) [abstract] |

Level dependence the models predict:
- **Packing fluctuations** (Poisson count, plus a correlated packing field): the noise
  power is proportional to the recorded magnetization squared, so the
  signal-to-modulation-noise ratio is constant with level and the noise rides as
  sidebands under the signal (Westmijze's -40 dB). This is in the project already
  (SCOTCH111@3 `noise`: packing_sigma fitted to No. 34's DC spectrum).
- **Magnetization-state noise** (each particle's binomial up / down state): largest
  when the state is mixed. For AC-biased audio recording the recorded M is a small
  fraction of Mr, so this term is nearly the bulk-erased noise, independent of level.
- **Clustering** (correlated packing and flux closure) lowers the erased noise below the
  Poisson value in thick coatings and adds a long-wavelength excess; the total is then
  not "erased noise + c M^2" exactly. For a 12.7 um coating of ~0.5 um particles this is
  the thick-media regime of Stoleriu 2002.
- For AC-biased recording the measured DC-noise spectrum (No. 34's 3% level) already
  pins the modulation term the project uses; a particle bench would mainly explain its
  spectrum's shape (cluster length), not add an audible new effect.

---

## 5. Verdict

**What a particle bench would plausibly change, in order of audibility:**

1. **The tape's saturation knee** (the 3% vs 1% THD spacing: the model's anhysteretic
   gives +4.9 dB, #111's own Sound Talk No. 1 ~4.1-4.5 dB). Interactions set the
   anhysteretic susceptibility and its shape (Spratt et al. 1988), and that is what
   "driving the tape" sounds like. A dipolar particle ensemble is the natural way to get
   it from physics. Audible: yes, in every driven print. But a one-parameter mean field
   (a moving Preisach alpha) in the existing self-consistent demagnetization loop can
   carry it at near-zero cost, fitted to No. 1's h3 curves, with No. 21 held out.
2. **No. 21's bias-curve width** (the rise and the 15k-1k spread). The literature says a
   DC-identified Preisach model fits AC processes worse (Stancu 1999), so the model class
   itself is suspect, and a bench with dynamic interactions could show whether static
   interaction fields are the reason. But the bench can't predict No. 21 from first
   principles: the ideal SW particle is ~5x too hard (Section 1.4), so the bench must be
   fitted to Nos. 20 / 22 through an effective switching-field distribution, and No. 21
   also depends on the record head's field against current and depth, which is
   provisional (TAPE_PLAN.md item 4: the heads lead for two other misses). A failed
   prediction couldn't be blamed on the particles alone. Audibility after alignment:
   small (the alignment sets bias and the record EQ trim absorbs the 15 kHz level); what
   remains is how HF level and HF saturation move with bias (No. 14's 4 dB miss at 7 kHz),
   heard on hot cymbals.
3. **Modulation noise and its spectrum.** Already in the model at the measured level;
   clustering changes the spectral shape and the erased noise by a few dB. Masked by the
   signal; low priority.
4. **Print-through.** Clearly audible (pre-echo at -40 to -55 dB before a loud entry, the
   classic tape artifact), and the period data give its laws well (Section 3.3). **It
   doesn't need the bench.** A linear model with a time- and temperature-dependent
   susceptibility, or a barrier distribution per hysteron, reproduces every published
   trend. It is the cheapest big audible win on this list.

**Cheaper terms that could carry the result:**
- **A mean-field (moving Preisach) interaction**, H_eff = H + alpha M, alpha > 0 for an
  agglomerated acicular coating (Cerchez 2003; sign and size fitted). It is a local term
  in the same fixed point as the project's demagnetization, so it costs ~nothing.
  Expected effect: the anhysteretic's shape and the saturation knee; little on bias-curve
  width (an argument from the model, untested).
- **A dynamic interaction variance**: the interaction field's spread grows with the
  bias amplitude (neighbours flipping during each bias cycle), i.e. sigma_Hi as a function
  of the cell's last bias peak. One table per cell, ~zero cost. This is the term most
  likely to widen the bias curves in bias, and the one thing worth asking a small bench
  (a few thousand interacting particles in a slab under a decaying AC field, no head,
  no transport: a partial-ARM experiment) before building anything bigger.
- **An energy barrier per hysteron** (Preisach-Neel): needed for print-through and the
  shelf decay, not for recording (<= 0.4 dB, the project's study).

**Recommendation.** Don't build the full kinetic Monte Carlo of the moving tape first.
Build (a) print-through from Section 3.4 (laws from the period data, no new physics risk),
and (b) a small static-head partial-ARM bench of dipolar-interacting effective particles
(fitted to No. 20 / 22) whose only question is: does a static Preisach with fitted sigma_Hi
reproduce the bench's partial-ARM curve (susceptibility against AC amplitude), and if not,
does a bias-dependent sigma_Hi or a mean field? If the bench's curve is wider than the
static Preisach's by the ~3 dB of bias No. 21 needs, the cheap term goes into the medium
and No. 21 is the held-out test; if not, the misfit is the heads', and the particle route
is closed at small cost.

---

## Sources (what was actually opened this session)

- 3M Sound Talk Nos. 10, 20, 21, 22, 38: `data/datasheets/tape/` (read in full).
- Eilers, AES Historical Committee table (via the project's extract in
  `data/datasheets/tape/README.md` and `published_points.yaml`).
- Draine & Hensley, arXiv:1205.7021 (2012), Table 1 and Sec. 2.3 (maghemite properties).
- Westmijze, "The fundamentals of magnetic recording" (1955 lecture, NRG 1956):
  https://soundandscience.net/wp-content/uploads/2023/03/1126_NAG_Publicatie_No_56a_Westmijze_The_fundamentals_of_magnetic_recorder_1956.pdf
- Manly, "Thinking about print-through in analog tape", Audio, Sept. 1977, with its
  figures: https://gammaelectronics.xyz/audio_09-1977_print-through.html
- McKnight, "Biasing magnetic tape in recording", Electronics World, Aug. 1967:
  https://mrltapes.com/pages/technical-papers (mcknight_biasing.pdf)
- Hinrichs (1963) and Bayer (1963), IEEE Trans. Audio AU-11:
  https://worldradiohistory.com/Archive-IRE/60s/Audio/IRE-Transactions-On-Audio-1963-05-06.pdf
- Cerchez, Stoleriu & Stancu, JOAM 5, 351 (2003): https://old.joam.inoe.ro/arhiva/pdf5_1/Cerchez.pdf
- Stoleriu et al., JOAM 4, 289 (2002): https://old.joam.inoe.ro/arhiva/pdf4_2/Stoleriu.pdf
- Borcia, Spinu & Stancu, JOAM 4, 307 (2002): https://old.joam.inoe.ro/arhiva/pdf4_2/Borcia.pdf
- Abstracts / index records only (IEEE via manuscript.isc.ac, scilit, ADS): Bertram 1974;
  Eiling 1988; Knowles 1987; Spratt et al. 1988; Vajda & Della Torre 1991; Bissell et al.
  2001; Stancu et al. 1999; Sharrock & McKinney 1981; Sharrock 1990, 1994; Flanders 1986;
  Flanders & Sharrock 1987; Tochihara et al. 1970; Stafford 1976; Thurlings 1979-80; Luo &
  Bertram 2001; the 1967 and 1968 JAP gamma-Fe2O3 coercivity papers; Jacobs & Bean 1955.
- Not found online: Westmijze's Philips Research Reports 8 (1953); Daniel & Axon, BBC
  Quarterly (1950); Bertram's and Mee & Daniel's book chapters; any gamma-Fe2O3 audio-tape
  KV/kT or moving-parameter value.
