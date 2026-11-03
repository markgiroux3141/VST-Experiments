# Brüel & Kjær Type 4134 sources (and the 4192)

The mic plan's A2 (docs/MIC_ROOM_PLAN.md): the capsule machinery verified on a small
pressure capsule. The 4134 (1/2 inch, pressure / random incidence, 12.5 mV/Pa, 200 V
external polarization; made from the 1960s to the 1990s, succeeded by the 4192) is the
standard case of condenser-microphone theory (Zuckerwar 1978, Homentcovschi & Miles 2011,
COMSOL's application model). Found 2026-11-03 in a web research pass; values are
transcribed below with where they come from. Cite them in a component file as `bk:`
(B&K documents), `zw:` (Zuckerwar), `hm:` (Homentcovschi & Miles) or `web:`.

No PDF is in the repo. Each downloaded file's URL and sha256 is listed so it can be
fetched again.

## Documents

### B&K product data, "Condenser Microphone Cartridges" (types 4133-4166, ~1980)

B&K Product Data, 19 pages, scanned images only (form "15-144"). It covers types 4133,
4134, 4135, 4136, 4138, 4144, 4145, 4146, 4147, 4148, 4149, 4160, 4161, 4163, 4165, 4166.

- web: https://peel.dk/Bruel&Kjaer/Equipment/Condenser%20Microphone%20Cartridges%20(Product%20datasheets).pdf
  (sha256 `32b489c46337b21a94f73047e386e0aee6bbab2559a642fb5749bdaf0322f737`, 11.2 MB).
  A second copy is under `.../Misc/` (sha256
  `0e7d640cd154d3f228000fc419560e8407f5e10b2908e8458a11189303927c2e`; not compared page
  by page).
- **Page 16 (PDF page 17), "Specifications"**: the table for every type (transcribed
  below). It is printed sideways, so rotate it to read it.
- **Page 6, Fig. 15**: typical frequency responses of the pressure microphones, recorded
  with the electrostatic actuator, 0.01 Hz-200 kHz, in dB re 1 V/Pa. The curve is
  labelled "Types 4134 and 4147", with "4134"'s low-frequency end drawn separately.
- **Page 7, Fig. 19**: a sample calibration chart. It shows a 4145, not a 4134.
- Page 7: each 4134 was delivered with its own pressure (actuator) response and its
  diffuse-field response.
- Pages 2-3: sectional drawings of a 1-inch cartridge only (backplate, insulator,
  vent). They have no dimensions.

### B&K Microphone Handbook, Vol. 1: Theory (BE 1447-12, March 2019)

- web: https://www.bksv.com/media/doc/be1447.pdf (sha256
  `80d71c924c446320700fdd1ff59e699d30601e8c8391eba09adbb599794acd6a`, 9.8 MB, has a
  text layer). An earlier edition is BE 1447-11 (1996).
- Section 2.3 (Measurement Microphone Design, pp. 2-7 to 2-29): the construction and
  the gap, air stiffness, vent, damping, air mass, and **an equivalent circuit with
  values (Fig. 2.13, Table 2.2)**. That example is a generic 50 mV/Pa microphone, not
  the 4134.
- Section 2.4 (pp. 2-35 to 2-37): inherent noise from the acoustic resistances.

### Zuckerwar, "A high-temperature wideband pressure transducer" (NASA CR-149789, 1977)

A. J. Zuckerwar, Old Dominion University, Technical Report PGSTR-PH77-48, final report
on NASA grant NSG 1039, March 1977, 106 pages. **This is the theory that became the 1978
JASA paper, with every equation**, applied to his own prototype capsule (not the 4134).

- web: https://ntrs.nasa.gov/api/citations/19770013461/downloads/19770013461.pdf
  (sha256 `fd15057a84310d5d334cb40e67837b135a73bbb577c5f837b56c4e24a4dd1036`, 3.0 MB,
  the scan has an OCR text layer).
- Section II.B (report pp. 6-19): the coupled membrane and air-film solution (after
  Petritskaya), using a Bessel-shaped trial displacement. It gives the lumped-parameter
  model (eqs. 2-25 to 2-32), the prototype's parameters (Table 3, p. 16), and its
  lumped values (p. 19).
- Appendix A (pp. 63-64): **the acoustic impedances of a hole, a slot and the back
  chamber** (formulas below).
- Eq. 2-33 gives the gap from the capacitance, and eq. 2-34 the tension from the
  in-vacuo resonance.
- The other NASA reports on the same project (NTRS 19760005249, 19760011323) only use
  a 4134 as the reference microphone. They don't add any parameters.

### Zuckerwar, "Theoretical response of condenser microphones" (JASA 1978)

J. Acoust. Soc. Am. 64(5), 1278-1285 (1978), doi:10.1121/1.382112. **We don't have it**:
it is paywalled, and NTRS 19790041577 has no download. Its abstract (NTRS) says the
theory agrees excellently with measured data for the B&K 4134 and 4146. Its 4134
parameter table is reproduced by Homentcovschi & Miles (below), who say the membrane,
geometry and air parameters "are those given by Zuckerwar". The same author's
"Principles of operation of condenser microphones" (AIP Handbook of Condenser
Microphones, Wong & Embleton eds., 1995, ch. 3, pp. 37-69) is also not online.

### Homentcovschi & Miles, "An analytical-numerical method for determining the mechanical response of a condenser microphone" (JASA 2011)

J. Acoust. Soc. Am. 130(6), 3698 (2011). Open access:
web: https://pmc.ncbi.nlm.nih.gov/articles/PMC3257755/ (read as HTML, no hash).

- The section on the B&K 4134 gives **Zuckerwar's 4134 parameters** (table below).
- Fig. 1(a) is a photograph: "Top view of the B&K 4134 microphone after removing the
  diaphragm" (six holes in six sectors).
- Fig. 3 plots the mechanical sensitivity (amplitude and phase), computed against the
  measurements in Zuckerwar's paper. The text says the numerical result is "overdamped
  as compared with the measured values". No numbers are tabulated.
- The thermal-noise section gives its own result and the published values to compare
  against (below).

### COMSOL Application Library, "The Brüel & Kjær 4134 Condenser Microphone" (ID 12375)

A full FEM model of the capsule: thermoviscous acoustics, electrostatics, a pretensioned
membrane, a moving mesh, 1/12 sector symmetry. It is compared with measurements on a real
4134 (valid from 200 Hz up) and computes the mechanical-thermal noise.

- web: https://doc.comsol.com/6.4/doc/com.comsol.help.models.aco.bk_4134_microphone/bk_4134_microphone.html
  (the documentation, read as HTML).
- web: https://doc.comsol.com/6.4/doc/com.comsol.help.models.aco.bk_4134_microphone/models.aco.bk_4134_microphone.pdf
  (sha256 `516f7c6aeb309755e8886ddff697c31854accccbf890bcdce8f840015ce55c01`). This is
  only a 6-page preview; the HTML has the rest.
- web: https://www.comsol.de/model/download/1334381/bk_4134_microphone_parameters.txt
  (sha256 `afa30358266be7542010c2d9c5960590b0df46eb52109da3f3a39931fb64806e`, 664 B):
  the model's parameter list.
- The geometry (backplate holes, slot) is in the .mph file only. It needs a COMSOL
  login and wasn't fetched.

### B&K Product Data, Type 4192 (BP 2213-11, 2008-06)

- web: https://www.bksv.com/media/doc/bp2213.pdf (sha256
  `2c0893fe578ed4ac83bd491c66ad004f3bb21c686423c9682bc14f2c2d0e1cf8`, 2 pages, text
  layer).
- Fig. 1, the typical pressure-field response from 1 Hz to 100 kHz, is a **vector**
  curve. It can be digitized from its paths, as `scripts/digitize_jensen_p12r.py` does.

### Others read, little or nothing used

- W. J. Wang et al. 2004 (J. Micromech. Microeng. 14, 403) via a DTIP 2008 paper,
  web: https://arxiv.org/pdf/0805.0856 (sha256
  `ad30a260cde256b4313ac65d5cfe5250daa5500b73d6d6df04d4f1ffad1d474e`): the Škvor gap
  and hole-resistance formulas for MEMS (eqs. 7-8). The text layer garbles them.
- J. Cillo (Shure), COMSOL Conference Boston 2024, "Application for Simulating
  Acoustic Response of Condenser Microphone Cartridges",
  web: https://ws-bos.comsol.com/paper/download/1443342/cillo-comsol-conference-2024-boston-final.pdf
  (sha256 `d47d52411a908cdde74ddcb74bd914dbf0f1e257919370155581f999fe49b702`): a
  parametrized cartridge template built from COMSOL's 4134 model. It has no 4134
  values.

## The 4134: physical parameters

The sources' symbols, in SI units. "zw/hm" means Zuckerwar's 1978 value as reproduced by
Homentcovschi & Miles 2011; we haven't seen the original table.

| Quantity | Value | Source | Confidence |
|---|---|---|---|
| Diaphragm radius a | 4.45 mm | zw/hm | good (the theory's value) |
| Diaphragm radius (FEM) | 4.5 mm | COMSOL `Rmic` | good |
| Diaphragm thickness | 5 um | zw/hm; COMSOL `tm` | good |
| Diaphragm surface density sigma | 0.0445 kg/m^2 | zw/hm; COMSOL `rhoms` | good |
| Diaphragm material | nickel (8900 kg/m^3 implied by 0.0445 / 5 um; COMSOL's table prints 890, a typo; its .txt derives rho = rhoms / tm) | COMSOL documentation | good |
| Diaphragm E, nu (COMSOL) | 2.21e11 Pa, 0.4 | COMSOL parameters | as modelled |
| Tension T | 3162 N/m | zw/hm | good (Zuckerwar fits T to the measured resonance, eq. 2-34) |
| Tension (COMSOL) | 3160 N/m | COMSOL `Tm0` | good |
| In-vacuo resonance | not printed. Arithmetic from a, T, sigma: f = 2.405 / (2 pi a) sqrt(T / sigma) = **22.9 kHz** | derived | - |
| Gap h (mean membrane to backplate) | 20.77 um | zw/hm | good |
| Gap (COMSOL) | "around 19 um" | COMSOL documentation | good |
| Gap, typical B&K | 20 um +- 0.8 um ("typically") | BE 1447 p. 2-8 | generic |
| Backplate radius | 3.61 mm (circular) | zw/hm | good |
| Backplate holes | 6, radius 0.51 mm, centres 2.03 mm from the axis, depth 0.84 mm (= backplate thickness at the holes) | zw/hm | good |
| Peripheral slot | "the length of the peripheral slit is 0.3 mm" (width? depth? not said) | hm | **ambiguous**; the slot's other dimensions are missing |
| Back chamber volume V | 1.264e-7 m^3 (126 mm^3) | zw/hm | good |
| Microphone (modelled) height | 3.35 mm | COMSOL `Hmic` | as modelled |
| Cartridge height | 11 mm without grid, 12.7 mm with | B&K data p. 16 | good |
| Cartridge diameter | 12.7 mm without grid, 13.2 mm with; thread 12.7 mm-60 NS2 | B&K data p. 16 | good |
| Air (Zuckerwar) | rho 1.2 kg/m^3; mu 1.89e-5 Pa s; isothermal c 290 m/s | hm (his prototype report used 1.21, 1.86e-5, 287.35) | good |
| Pressure equalization vent | **not found** for the 4134 (dimensions or resistance). B&K: "typically 0.1 s" time constant, lower limiting frequency 1-2 Hz for general-purpose types | BE 1447 pp. 2-17, 2-19 | generic |
| Polarization voltage | 200 V | B&K data p. 16; COMSOL `Vpol` | good |
| Capacitance (polarized, 250 Hz) | 18 pF (one cell for 4133 / 4134 / 4147 / 4149) | B&K data p. 16 | good (individually calibrated) |
| COMSOL charge | Q0 3.145e-10 C per 1/12 sector at 200 V (arithmetic: 3.774e-9 C total, 18.9 pF) | COMSOL parameters | as modelled |
| Stray capacitance | **not found** for the 4134 | - | - |
| Open-circuit sensitivity, 250 Hz | 12.5 mV/Pa, -38 dB re 1 V/Pa | B&K data p. 16 | good (nominal; each unit calibrated) |
| Resonance (90 deg phase) | 23 kHz (one cell for 4133 / 4134 / 4147 / 4149) | B&K data p. 16 | good |
| Equivalent air volume (1 atm) | 10 mm^3 (4133 / 4134 / 4147 / 4149) | B&K data p. 16 | good |
| Response flat within +-2 dB | 3.9 Hz-20 kHz (pressure / random incidence) | B&K data p. 16 | good |
| Thermal noise | 18 dB(A) | B&K data p. 16 | good |
| Distortion | 3% above 160 dB SPL | B&K data p. 16 | good |
| Static pressure | -0.7 dB/atm | B&K data p. 16 | good |
| Temperature coefficient | -0.01 dB/degC (-50 to +60 degC) | B&K data p. 16 | good |

## Published responses and noise to verify against

**Pressure (actuator) response, B&K data Fig. 15, typical.** Read by eye from a 300 dpi
render; digitize it before using these as targets.

- -38 dB re 1 V/Pa (12.5 mV/Pa), flat from ~20 Hz to ~8 kHz.
- A broad rise to about +1 dB (~14 mV/Pa) around 15-18 kHz, back through 12.5 mV/Pa
  near 22 kHz.
- About 8 mV/Pa (-4 dB) near 30 kHz, ~5 mV/Pa (-8 dB) near 40 kHz, ~2.2 mV/Pa (-15 dB)
  at 50 kHz, where the curve ends.
- Low end (the "4134" branch): ~-41 dB (-3 dB) at the curve's start, about 2.9 Hz;
  ~-39.5 dB at 6 Hz; ~-38.5 dB at 10 Hz. It doesn't say whether the vent was exposed.
- So the capsule is close to critically damped (B&K uses Q ~1 for pressure
  microphones, BE 1447 p. 2-22). Fig. 15 is an actuator response: the electrostatic
  force drives the diaphragm with no radiation load. A pressure response differs from
  it slightly at high frequencies.

**Type 4192 (the 4134's successor, BP 2213 Fig. 1).** Typical pressure-field response
with the protection grid, vent exposed. Flat 0 dB from ~10 Hz to ~10 kHz; about -5 dB at
1 Hz; a slight rise of ~+0.3 dB around 10-15 kHz; about -0.5 dB at 20 kHz. Specified
+-1 dB from 5 Hz to 7 kHz and +-2 dB from 3.15 Hz to 20 kHz.

**Zuckerwar 1978.** Computed vs measured response for the 4134 and 4146 (as cited by
hm Fig. 3). No numbers are available until the paper is obtained.

**COMSOL.** The model's level is printed as 20 log10(|V/p_in|) + L0, with L0 = 39.5 dB
called "the normalization sensitivity, here the level at 250 Hz". If that normalizes the
model to 0 dB at 250 Hz (our reading, not stated), the FEM's absolute sensitivity is
about -39.5 dB re 1 V/Pa, i.e. ~10.6 mV/Pa against the nominal 12.5. The documentation
gives no deviations from its measured curves in numbers.

**Thermal (mechanical) noise of the 4134:**

| Value | Source |
|---|---|
| 18 dB(A) | B&K data p. 16 (data sheet) |
| 19.7 dB(A) | Zuckerwar (1978), as quoted by hm |
| 18.9 dB(A) | Tarnow, JASA 82, 379 (1987), as quoted by hm |
| 18.3 dB(A) | Tan & Miao, JASA 126, 2301 (2009), the modified Škvor / Starr approach, as quoted by hm |
| 18.0 dB(A) | Wong, AIP Handbook ch. 19 (1995), as quoted by hm |
| 17.9 dB(A); 1.39e-6 Pa/sqrt(Hz); R_acs ~1.2e8 N s/m^5 | hm (their FEM), 10 Hz-20 kHz |
| 18.7 dB(A) | COMSOL (FEM, Johnson noise of Re(Z_a)) |
| 4192: 19 dB(A), 21.3 dB(Lin) | BP 2213 |

hm's spectral density checks with p = sqrt(4 k T R) at R = 1.2e8 N s/m^5 and 293 K:
1.39e-6 Pa/sqrt(Hz).

## Lumped-element formulas (with sources)

The notation is acoustic impedance (Pa per m^3/s). S = pi a^2 is the diaphragm area.

**Zuckerwar 1977 (NASA CR-149789), checked against the scanned pages:**

- Eq. 2-27: the diaphragm-plus-film acoustic impedance below the first resonance is
  Z_M = i w (4/3) sigma / S + 8 pi T / (i w S^2) + 8 pi T / (i w S^2) (D1 + D2 + D3 + D4).
  - D1 is the air film's compliance: D1 ~ rho0 c^2 a^2 / (8 T h), with c the isothermal
    sound speed.
  - D2 is the flow through the openings.
  - D3 and D4 correct D1 and D2 for the membrane's curvature.
  - The D's (eqs. 2-30a-d) are sums over the air modes and openings. Their T_m, Gamma_m
    and s_s are defined in eqs. 2-11 and 2-13.
- **Membrane mass M = (4/3) sigma / (pi a^2)**, and **membrane compliance
  C_M = (pi a^2)^2 / (8 pi T)** (= pi a^4 / (8 T)) (eq. 2-28).
- **Air compliance C_A = S^2 / (8 pi T Re{D})**, and **damping R = 8 pi T Im{D} /
  (w S^2)** (eqs. 2-31a, b). The closed-film limit is C_A' = pi a^2 h / (rho0 c^2), and
  the openings make C_A >> C_A'.
- **Q = (1/R) sqrt(M (C_M + C_A) / (C_M C_A))** (eq. 2-32).
- The lumped model is valid below ~2 kHz for his prototype. Above that, the Q still
  indicates the peak height. Values are taken at 1 kHz.
- **Hole k** (radius r, depth l): Z = 8 rho0 nu l / (pi r^4) + i w (4/3) rho0 l /
  (pi r^2), i.e. Poiseuille resistance 8 mu l / (pi r^4) and mass 4 rho0 l /
  (3 pi r^2) (eq. A-4).
- **Slot** (length w, width t, depth l): Z = 12 rho0 nu l / (t^3 w) + i w (6/5)
  rho0 l / (t w) (eq. A-5).
- **Back chamber**: Z_C = rho0 c^2 / (i w V), shared by all openings. The openings
  couple through it: Z_ij = Z_i delta_ij + Z_C (eq. A-2c).
- **Gap from capacitance**: h = a_BP^2 / (36e9 C), i.e. eps0 pi a_BP^2 / C (eq. 2-33).
  **Tension from the in-vacuo resonance**: T = 6.825 a^2 f_R1^2 sigma (eq. 2-34; the
  scan writes rho_M t for sigma).

His prototype (not the 4134, Table 3 and p. 19) as a check of the machinery:

- a 4.7625 mm, t 5.588 um, rho_M 7900 kg/m^3, sigma 4.4145e-2 kg/m^2, rho0 1.21 kg/m^3,
  mu 1.86e-5, c_T 287.35 m/s.
- Backplate radius 4.572 mm; 4 holes at 2.6924 mm, radius 0.3969 mm, depth 0.6604 mm;
  a slot at 4.667 mm, 95.25 um wide, 0.6604 mm deep; back chamber 1.4878e-7 m^3.
- Gap and tension adjustable (microphone 1: h 37.2 um, T 2893 N/m, 15.6 pF;
  microphone 2: 43.0 um, 4487 N/m, 13.6 pF; Table 7).
- At 1 kHz: M 826 kg/m^4, C_M 6.82e-14 m^5/N, C_A 1.60e-12 m^5/N, R 1.32e7 N s/m^5,
  Q 8.52.
- He fitted the measured actuator responses to the theory at 10 Hz (shape only, not
  absolute level).

**Homentcovschi & Miles 2011 (the same lumped forms, extracted from FEM):**

- M_M = 4 sigma / (3 pi a^2), C_M = (pi a^2)^2 / (8 pi T).
- R_A(w) = (1/w) Im(1/J(w)), and C_A(w) = [Re(1/J) + 4 sigma w^2 / (3 pi a^2) -
  8 pi T / (pi a^2)^2]^-1, where J is the volume displacement per unit pressure.
- The noise is F = sqrt(4 k T0 R_A), with R_acs = R_A / S^2.

**B&K Microphone Handbook (BE 1447), Fig. 2.13 / Table 2.2.** The circuit is in the
impedance analogy. It is a generic 50 mV/Pa 1/2-inch-class microphone, resonance
10 kHz, Q = 1; not the 4134.

| Element | Value |
|---|---|
| Cd, diaphragm compliance | 0.314e-12 m^5/N |
| Ld, diaphragm mass | 600 kg/m^4 |
| Ls, mass of the slit behind the diaphragm | 296 kg/m^4 |
| Rs, resistance of the slit behind the diaphragm | 56.2e6 N s/m^5 |
| Cc, internal cavity | 2.83e-12 m^5/N |
| Rv, vent | 36e9 N s/m^5 (Rv Cc = 0.10 s) |
| C1 / C2 / C3, coupling | 5.66e-12 / -5.66e-12 / 5.66e-12 (m^5/N or F) |
| Ce, blocked electrical capacitance | 17 pF |

- The vent connects terminal 3 to 1 (exposed) or to 2 (unexposed).
- Simplified (Fig. 2.14, Table 2.3): Cds = Cd Cc / (Cd + Cc) = 2.83e-13, Lds = Ld + Ls
  = 896, Rds = Rs = 56.2e6.
- A cavity's compliance is Ca = V / (gamma Ps), and the equivalent volume is
  Ve = gamma Ps / (i w Zds).
- Noise: p_n = sqrt(4 k T Ra df). Only the diaphragm's damping resistance matters: the
  vent's noise is below the preamplifier's (p. 2-37).
- The handbook's rules of thumb:
  - the cavity's air stiffness is typically 10% of the total;
  - the slit's air mass is 10-50% of the moving mass;
  - Q = 1 for pressure microphones, 0.316 for free-field ones;
  - the vent time constant is ~0.1 s;
  - stress up to 600 N/mm^2 in the diaphragm foil.

**Škvor's squeeze-film resistance** (J. Škvor, Acustica 19, 1967/68; quoted in Scheeper
et al., Sens. Actuators A 44, 1994; in Wang et al. 2004; and in arXiv 0805.0856 eq. 7, all
garbled in the text layer). The standard form is:

- R_gap = 12 mu / (n pi h^3) * (A/2 - A^2/8 - ln(A)/4 - 3/8), with n the holes per unit
  area and A the open-area fraction. This is a specific resistance in Pa s/m: divide by
  the backplate area for the acoustic one.
- Each hole: 8 mu l / (pi r^4).

It assumes a uniform periodic hole array (not the 4134's six large holes and slot). The
bracket matches the source. **Check the normalization (12 vs 3/2 per cell) against
Škvor's paper or Scheeper's review before using it.** For the 4134, Zuckerwar's
solution, or an FEM-calibrated R (hm's ~1.2e8 N s/m^5), is the better target.

## Arithmetic cross-checks (from the values above; nothing simulated)

- **Membrane:** M = 4 sigma / (3 pi a^2) = 954 kg/m^4; C_M = pi a^4 / (8 T) =
  4.87e-14 m^5/N. Lumped resonance 1 / (2 pi sqrt(M C_M)) = 23.3 kHz, and the exact
  first membrane mode is 22.9 kHz. The air film's mass lowers it and its stiffness
  raises it. The spec's 23 kHz (90 deg) is consistent.
- **Back chamber:** V / (gamma P0) = 8.90e-13 m^5/N (adiabatic), V / P0 = 1.25e-12
  (isothermal). That is 5-7% of the stiffness; B&K quotes "typically 10%". The data
  sheet's -0.7 dB/atm also suggests ~8%.
- **Film:** the closed-film compliance pi a^2 h / P0 = 1.28e-14 m^5/N, stiffer than
  the membrane. It is relieved only by the holes and slot.
- **Capacitance:** eps0 pi (3.61 mm)^2 / 20.77 um = 17.4 pF gross. That matches
  Zuckerwar's eq. 2-33 at C = 17.4 pF, so his gap probably came from a capacitance
  measurement. Without the six holes' area it is 15.4 pF. The spec's 18 pF includes
  stray capacitance, which isn't separated anywhere.
- **Equivalent volume:** the membrane alone is C_M gamma P0 = 6.9 mm^3 (isothermal
  4.9) against the data sheet's 10 mm^3 (4192: 8.8). **That's a mismatch of ~1.5x;
  open.**
- **Sensitivity**, at low frequency with constant charge, a parabolic membrane, and the
  chamber in series. Mean displacement over the backplate is 9.96e-10 m/Pa, so
  e = 200 V x 9.96e-10 / 20.77e-6 = 9.6 mV/Pa (-40.4 dB re 1 V/Pa). This is an upper
  bound: it ignores the film's stiffness and the stray capacitance.
- The nominal is 12.5 mV/Pa. **So Zuckerwar's parameter set (as reproduced) is ~2.3 dB
  short of the nominal sensitivity.** COMSOL's L0 = 39.5 dB, if read as above, shows
  the same shortfall (~-1.5 dB). Zuckerwar compared response shapes, not absolute
  levels (his 1977 data were scaled to the theory at 10 Hz).
- Possible causes: the tension, the effective radius (a larger clamped radius would
  also fix the equivalent volume), the gap at polarization (the electrostatic pull
  closes it slightly; its negative stiffness is ~3% at 200 V), or the electrode area.
  **A2 should match the shape against the data and treat the absolute level as a
  calibration** (or a bounded genome value), not a pass / fail.

## The 4192 (successor, better current documentation, less geometry)

From BP 2213-11:

- IEC 61094-4 WS2P; external polarization 200 V.
- 12.5 mV/Pa (-38 dB +- 1.5 dB re 1 V/Pa) at 250 Hz.
- Response: +-1 dB 5 Hz-7 kHz, +-2 dB 3.15 Hz-20 kHz. Lower limiting frequency 1-2 Hz;
  side vented.
- Diaphragm resonance 23 kHz (90 deg).
- Capacitance 18 pF at 250 Hz; equivalent air volume 8.8 mm^3 (250 Hz).
- Thermal noise 19 dB(A), 21.3 dB(Lin). Upper limit of the dynamic range above
  162 dB SPL (3%).
- Static-pressure coefficient -0.005 dB/kPa; temperature coefficient -0.0045 dB/K.
- Press-fitted stainless-steel diaphragm.
- Sizes: 12.7 mm without the grid, 13.2 mm with it; heights 12.6 / 13.5 mm.

No internal geometry (gap, tension, holes, cavity) is published for the 4192. The 4190
(free-field, 50 mV/Pa) wasn't researched. The handbook's generic 50 mV/Pa circuit is the
closest data for that class.

## Missing

- Zuckerwar 1978's own table: it would confirm the reproduced values. The slot's
  dimensions (width, depth, radius) and the hole layout's angular positions (60 deg by
  symmetry) are also missing, as are his computed and measured curves.
- The 4134's vent: dimensions, resistance or time constant.
- The 4134's stray (passive) capacitance.
- COMSOL's .mph geometry: it needs a login.
- A digitized 4134 pressure response with numbers: the B&K Fig. 15 and the 4192
  Fig. 1 curves need digitizing.
- A 4134 calibration chart (individual units' charts, e.g. on auction sites, would give
  real curves; none found).
- The noise spectrum's shape: only A-weighted totals and hm's flat 1.39e-6 Pa/sqrt(Hz)
  are available. B&K Handbook Fig. 2.22 shows 1/3-octave noise spectra for the 1/2-inch
  12.5 mV/Pa class.
