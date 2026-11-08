# Hammond Novachord: circuit research notes (2026-11-07)

Web research for docs/NOVACHORD_PLAN.md (NV0). Every value carries its source. "inferred"
marks my own arithmetic or reading, not printed data.

## Sources

- **[SM2] Hammond Instrument Co., "The Hammond Novachord: A Manual for the Service
  Technician", Second Edition** (scan restored by Mike Buffington / Forgotten Futures, thanks
  to Tom Rhea and EMEAPP).
  web: https://archive.org/details/hammond-novachord-a-manual-for-the-service-technician-second-edition-white-version
  Local copies: `novachord_service_manual_2nd_ed_white.pdf` (32 MB, 47 pages, image-only),
  `novachord_service_manual_2nd_ed_white_djvu.txt` (archive.org's OCR; the figure values in
  it are garbled, so they were read from the page images). PDF page numbers below are of
  this file.
- **[SM-orig] Another scan, "Original Hammond Novachord Service Manual"**, circa 1938.
  web: https://archive.org/details/originalhammondnovachordservicemanual
  Local: `novachord_service_manual_original.pdf`, `..._djvu.txt`. Not yet compared with SM2
  (it may be the first edition).
- Figure crops read for these notes (from SM2): `fig16_divider_crop.png`,
  `fig16_control_crop.png`, `fig19_playing_key_crop.png`, `attack_switch_table_crop.png`,
  `fig15_oscillator_crop.png`, `fig20_control_box_crop.png`.
- **[P682] US 2,126,682**, L. Hammond, "Electrical musical instrument", Serial No. 199,614,
  filed 1938-04-02, granted 1938-08-09: the divider ("non-linear amplifier") and the keying.
  web: https://patents.google.com/patent/US2126682A/en
  PDF: https://patentimages.storage.googleapis.com/68/bd/02/ea35d68ccc6fe8/US2126682.pdf
- **[P464] US 2,126,464**, L. Hammond, Serial No. 199,613, same dates: a related instrument
  whose lower notes are gas-tube relaxation oscillators locked to vacuum-tube masters, with a
  control tube and key circuit. Not the production Novachord's generator.
  web: https://patents.google.com/patent/US2126464A/en
- **US 2,254,284** (J. M. Hanert, filed 1939-05-18, granted 1941-09-02) is **the Solovox**
  (type-53 master, six type-885 gas-tube dividers, 2A5 output), not the Novachord.
  web: https://patents.google.com/patent/US2254284A/en. Its reed vibrato switches an
  inductance (L4 in series with / shunting L3) at "in the order of 7 c.p.s.".
- **[OT]** oldtech.com, transcribing the owner's text: https://oldtech.com/synth/HammondNovaC1.html
- **[DS]** Phil Cirocco's restoration: https://discretesynthesizers.com/nova/intro.htm
  (sub-pages generator.htm, control.htm, power.htm not fetched yet).
- **[LMNC]** Lookmumnocomputer forum recreation (256byteram):
  https://lookmumnocomputer.discourse.group/t/diy-hammond-novachord/5353

## 1. The divider (SM2 Fig. 16, PDF p. 37; Fig. 18, p. 39; text pp. 6-7)

**Topology.** A 6W7-G pentode, non-oscillating, self-biased just below cutoff; it fires on
alternate input pulses. Not a monostable or a blocking oscillator: "The type of frequency
divider used in the Novachord does not oscillate, but the circuit constants are so chosen
that the divider tube responds only to alternate cycles of the input frequency" (SM2 p. 6).
"Each frequency divider is a non-linear amplifier" (SM2 p. 5). [P682]: "no oscillators are
employed. Each tube operates as a non-linear amplifier."

**Netlist read off Fig. 16 ("Divider circuit, except lowest octave"):**

| Part | Connection | Value (SM2 Fig. 16) |
|---|---|---|
| RN3 | input (oscillator or preceding divider's CN1) -> grid | 1 MEG |
| RN4 | grid -> ground | 2 MEG |
| RN13 | grid -> ground, parallel to RN4 (the "adjustment resistor", in clips) | 1.2 to 3.5 MEG |
| CN2 | grid -> cathode | .0005 to .009 (uF) |
| CN3 | cathode -> ground | .005 to .08 |
| RN6 | cathode -> -192 V | 1 MEG |
| RN1 | cathode -> control-tube grid network (via CN5) | 1 MEG |
| RN5 | plate -> +270 V | 500,000 |
| CN4 | plate -> ground | .001 to .02 |
| CN1 | plate -> next divider's RN3 | .001 to .02 |
| G2 + G3 | screen and suppressor tied together -> +70 V (read off the drawing) | |

Values are ranges because "the actual value may vary from note to note or octave to octave"
(SM2 p. 5). Lowest octave (Fig. 18): same RN3 1 MEG, RN4 2 MEG, RN13 1.2-3.5 MEG, RN6 1 MEG,
-192 V / +70 V, **CN3 .009 to .018**; its cathode feeds the control tube; no next stage.

**Operating point (SM2 p. 7):** "The steady-state plate current of the tube, about .2
milliampere, causes a drop across the 1 megohm bias resistor RN 6 of 198 volts. This opposes
the -192 volt fixed bias supply and leaves a net bias of about 6 volts on the tube."
Inferred: plate DC about 270 - 0.2 mA x 500 k = 170 V.

**How it divides (SM2 p. 7, with its Fig. 4):** the input "is a sharp-pointed wave and
suddenly makes the grid go positive". Plate current raises the cathode, which "acts through
CN2 to make the grid more positive, so that the grid remains positive even after the input
wave has passed ... it operates until the cathode and plate potentials are so nearly alike
that plate current can no longer flow" and CN3 is charged. Then "the grid potential ... goes
down at a rate determined by leakage from ground through RN4 and RN13 into CN2 and CN3 in
series. The cathode potential ... goes down at a rate determined by the leakage from -192
volts through RN6 into CN3. The time constants of these two circuits are so adjusted that G
floats down faster than K." The second input cycle cannot trip it; the third does.
Failure modes (SM2 pp. 7-8): cathode too fast / grid too slow -> no division ("plays an
octave high"); the reverse -> divides by four, not three ("a divider of this type does not
readily divide by three"); the change is gradual, so "plays an octave low" means "an audible
sub-octave component". Adjustment: RN13 1.7-2.5 MEG centres a divider, 1.2-3.5 MEG in
extremes; no / high RN13 -> octave low, low RN13 -> octave high (SM2 pp. 20-21). Aging:
"the capacity of the condensers tends to increase", "Resistors tend to increase" (SM2 p.
19-20). Vibrato near the edge makes a divider "click loudly or 'warble'" (SM2 p. 21).

**Waveforms.** The plate output is a sawtooth: "of a characteristic saw-tooth shape except
that the steep side of the wave will not approach the vertical"; output amplitude "will be
substantially the same, independent of the amplitude of the input ... changed in the ratio of
about 2:1 without any appreciable change" [P682]. The control tube takes the **cathode**
wave, the next divider the **plate** wave, which keeps sub-octaves out of the control tube's
signal [P682]. SM2 p. 20 Fig. 5 shows a proper divider output; the "harmonic indicated at
'A' should be as small as possible".

**Patent variant [P682]** (an 85-note A=440 design, pentode "SJ I" in the OCR, probably 6J7
(inferred)): Co (cathode-ground) .09 mfd, Cb (grid-cathode) .011 mfd, grid leak 400,000 ohm,
input series resistor 1,000,000 ohm, cathode resistor 500,000 ohm to -100 V, B+ +300 V,
suppressor +45 V, cutoff "about 6 volts", average cathode current .212 mA. Values for note 25
(110 Hz). Also a transformer-coupled variant (Fig. 8).

## 2. The top-octave oscillator (SM2 Figs. 14 / 15, PDF pp. 35-36; text pp. 5-6)

- 12 oscillators, one 6C8-G each, "at the frequencies of the highest octave of the
  instrument (F to E inclusive)" (SM2 p. 5).
- **Frequencies:** SM2 Fig. 12 (PDF p. 33) labels note A's chain: oscillator 1760 cy.,
  dividers 880, 440, 220, 110, 55 cy. So the oscillators span F6 to E7 (inferred, A440 equal
  temperament: F6 1396.91 Hz ... E7 2637.02 Hz).
- **Below serial 1699 (Fig. 14):** "The tuning coil has a movable core section actuated by a
  thumb nut ... shunted by two condensers, CN 11 and CN 12, one for rough tuning and one for
  fine tuning. This is a high Q tuned circuit requiring little feedback voltage". "Triode 1
  drives triode 2 through a voltage dividing network and also provides a signal through RN 19
  to the highest octave control tube. The output of triode 2 is connected through feedback
  resistor RN 14 to the grid of triode 1 and also provides a signal to the first divider
  tube." Values in Fig. 14: RN19 1 MEG; CN11 selected at factory; CN31 .005 to .012; CN32
  .01 to .02; CN33 .003 to .007; RN14 100,000 (OCR) ; "+270 V".
- **Serial 1700 and above (Fig. 15):** "Triode 1 of the 6C8-G tube is part of a conventional
  oscillator circuit including tuning coil and condensers CN 11 and CN 12 as tuning constants.
  Triode 2 operates as an amplifier connected in such a manner as to increase the apparent
  capacity of condenser CN 17 as the gain of the tube is increased" (a Miller reactance
  stage, inferred term). Values read off Fig. 15: tapped tuning coil; CN11 factory-selected;
  CN12 .01 to .02; CN13 .08 to .14; CN10 .001; RN18 20,000; CN17 .00005 to .0001; RN17
  60,000 and RN22 50,000 (plate network to +270 V); RN16 3 MEG; RN14 2 MEG (also "to grid #2
  of adjacent oscillator"); CN16 .025; RN15 10,000; RN40 50,000; RN35 250,000; RN36 10,000;
  RN39 250,000; CN31 .005 to .012; CN1 .01 to .02 (to first divider); RN19 1 MEG (to control
  tube grid); -192 V bias; vibrato reed coil LN6. The full wiring of triode 2's grid
  network was not traced; read the page image before modelling.
- Tuning: CN11 "is selected at the factory for each individual instrument and has no
  standard value"; tune within 1.5 turns of the knob (SM2 pp. 21-22).

## 3. Keying, control tube and envelope (SM2 Figs. 16, 17, 19; text pp. 6, 8-9, 16-17)

**Control tube (Fig. 16, "except highest octave"):** 6W7-G. Grid fed from the divider
cathode through RN1 1 MEG and CN5 .0005 to .02. Grid to ground: RN2 150,000 to 350,000, CN29
.0005 to .002, and CN30 .0005 to .005 switched in by the BRIGHT-MELLOW switch. Screen +34 V
(drawing; SM2 p. 17 text: "proper screen potential, about 25 volts"). Suppressor grounded.
Cathode: CN15 .03 to .19 to ground, RN7 1.5 to 5 MEG to the key circuit. Plates of four
adjacent control tubes in common to the control box. Plate DC "varies from about 200 volts on
the lower notes to 150 volts on the higher" (SM2 p. 17).
**Top octave (Fig. 17):** grid from the oscillator, RN2 200,000, RN8 50,000 switched by
BRIGHT-MELLOW (instead of a capacitor), CN15 .05 to .06, RN7 1 MEG, screen +34 V.
How it shapes: the grid bias lets "plate current ... flow only during the positive peak
portion of the input signal wave", giving "a series of steep peaks" rich in harmonics
[P682]; the mellow capacitor makes the peak less sharp [P682, SM2 p. 6].

**Playing key circuit (Fig. 19, PDF p. 40), read off the drawing:**
- Three springs per key. Spring 3 rests on bus "A"; key down, it leaves A and touches
  stationary spring 2. Spring 1 rests on the "Cut-off" bus; key down, it lifts off. The
  sustaining cam holds spring 1 off for every key (SM2 p. 8).
- Spring 2 = the keying lead to RN7 (the control tube's cathode resistor), with CN7 .25 to
  the cut-off return, and RN10 "180M TO 450M" from spring 1 (read as 180-450 kilohm, inferred:
  "M" is the old thousand, the spares kit lists 180,000-450,000 ohm resistors, and the text
  says the note "will decay rapidly as CN7 discharges through RN10", which 180 megohm with
  .25 uF could not).
- Spring 3 -> RN12 30,000 to 75,000 -> node X; node X -> RN11 1 to 5 MEG -> bus "C"; node X ->
  CN8 .25 -> the cut-off return.
- The cut-off divider (SM2 Fig. 19): ground - RN38 500 to 700 - six RN37 100 ohm - RN33 2800
  (1300 in some) - +34 V (+17 V in some). Taps: notes 45-72 yellow, 13-44 orange, 5-12 red,
  1-4 brown, "the 'Cut-off' bus-bar is in four sections, each at a different cut-off
  potential" (SM2 p. 8). Inferred tap voltages (600 ohm RN38, +34 V): 6.8 / 7.65 / 8.5 /
  9.35 V (yellow to brown), all positive, so the cathode sits above its grounded grid.
- SM2 p. 8: "Before the key is depressed, condenser CN8 is charged to a potential determined
  by 'A' and 'C' ... When spring 3 is moved from the bus-bar to spring 2, this voltage charges
  CN7. Current then passes from this condenser over the keying lead to the cathode of the
  control tube, and the note sounds. When the key is released the note will decay rapidly as
  CN7 discharges through RN10, unless the sustaining pedal is depressed. This pedal opens
  contact 1 on all keys and makes the decay slower since CN7 can then discharge only through
  the control tube." "The initial potential of CN8 is determined largely by the voltage 'A'
  since RN12 is much smaller than RN11."
- "The potential of 'A' determines the initial intensity of the note ... and that of 'C'
  determines its final intensity with the key held down" (SM2 p. 8). The attack switch "varies
  the potential of bus-bar 'A' between ground and -260 volts".
- **Attack switch, DC volts (SM2 p. 16, PDF p. 18), A / C:** 1: 268 / 9; 2: -235 / -24; 3:
  -180 / -40; 4: -125 / -125; 5: -40 / -180; 6: -24 / -235; 7: 9 / -268. "These voltages may
  vary from 10 to 15 per cent." (Position 1's A is printed without a sign; -268 inferred from
  p. 15: "-270 volts ... when the attack control is at 'fast'".) Position 1 = Fast, 7 = Slow.
  [DS]: "Setting 1 is for percussive type envelopes", "Setting 4, without the release
  function is an organ envelope", "Setting 7 would be great for string simulation"; "The
  times are not variable, but the levels are."
- Inferred time constants (my arithmetic on the printed values, not data): release RN10 x
  CN7 = 45-113 ms; fast transfer RN12 x (CN7 in series with CN8, 0.125 uF) = 3.8-9.4 ms;
  slow approach to C, RN11 x CN8 = 0.25-1.25 s (CN7 also in the path); sustained decay
  through RN7 1.5-5 MEG and the tube, at least 0.4-1.25 s.
- Patent version [P682]: three adjustable buses Ba, Bb (safe cutoff), Bc. Piano: Ba about
  200 V (sign lost in the OCR), Bc ground; organ: Ba and Bc about -100 V; slow string: Ba
  ground, Bc about -200 V. [P464], note No. 25: "C1 and Ca, .3 mfd; R1 and R11, 4 megohms; R12
  and R13, 6000 ohms", R8 10,000, Rm 600,000, Re 20 megohms; "A at minus 450 volts, B, C and
  F at ground, D and E at plus 6 volts"; control tube "a pentode having sharp grid cutoff",
  screen 25 V, plate about 200 V, cut off at cathode +6 V.
- [LMNC] recreation (a guide, not the original): 6J6 per note, envelope C4 / C5; "Slow ... A
  is at 0V and C is at -100V", Fast the reverse; "The Cutoff voltage is about 20V".
- Sustain: "removing cut-off bias from the control tubes"; the bass pedal covers "the lower
  36 notes", the other two the whole keyboard (SM2 p. 4).

## 4. Output networks, BRIGHT / MELLOW, tone controls (SM2 Fig. 20, PDF p. 41; pp. 9-10)

- Per group of four control tubes (18 groups, inferred 72 / 4): plate load RN23 55,000 to
  100,000 to +270 V ("from filter in pre-amplifier"), then RN24 500,000 in series with CN18
  .00015 to .005 to a common bus; the bus has RN26 250,000 to ground and goes through .14 uF
  and RN27 30,000 to the resonators. "If four consecutive notes fail to sound, the trouble is
  probably in the common plate lead ... or in the output network" (SM2 p. 17). This series RC
  per group may be what [DS] calls the band-pass filters (inferred). [DS] says the mellow
  setting "reduces the bandwidth of each band pass filter"; SM2 says mellow adds capacitors in
  the control tube grid circuits (CN30), lower 18 notes excluded.
- Balancer: "connects fixed resistors across resistors RN23 for the lower half of the
  keyboard" (SM2 p. 10). Values not printed.
- Resonator stack (series string, each element shunted by its switched resistor control):
  BRILLIANT (LN2), 3RD RESONATOR LN3 || CN21 .008, 2ND LN4 || CN22 .023, 1ST LN5 || CN23
  .065, DEEP (CN20, RN48 1 MEG), FULL (RN34 30,000; RN61 15,000 with a switch operated by
  BRIGHT-MELLOW, omitted below serial 1700). **Inductances LN2-LN5 are not printed**, so the
  resonator frequencies are unknown. "Each resonator is tuned to a different audio frequency
  and is controlled by a variable resistance across it" and the variable resistors "are
  actually switches with fixed resistors"; FULL "may also be used to vary the sharpness of
  tuning of the resonators" (SM2 p. 9).
- To the preamp: RN54 7 MEG with CN39 .000015; VOLUME control taps RN56 50 MEG / CN41 .00005,
  RN55 25 MEG / CN40 .0001.

## 5. Vibrato (SM2 pp. 5-6, Figs. 14 / 15)

- "There are six reeds vibrating at different rates, each producing the vibrato effect for
  two oscillators" (SM2 p. 6); reeds "magnetically driven"; "three contacts on each reed ...
  The middle contact is for driving the reed ... The contacts should make in the middle of
  the reed's motion" (SM2 p. 22); drive coils at 50 V (SM2 p. 11).
- Below 1700: the reed contact switches a capacitor across part of the tuning coil. "The
  small vibrato switch ... connects condenser CN 33 across a portion of the oscillator tuning
  coil, thus lowering the oscillator frequency, each time the reed contact closes." Normal
  vibrato switches CN32 in and removes CN31: "The reed contacts ... are closed one half of the
  time; therefore, CN 32 is twice the value of CN 31." CN31 .005-.012, CN32 .01-.02, CN33
  .003-.007 (Fig. 14).
- 1700 and above: the reed changes triode 2's grid bias, so its gain and the Miller
  capacitance of CN17 (.00005-.0001); "Resistor RN 40 and condenser CN 16 act as a filter to
  prevent the vibrato reed from making the change in gain in triode 2 too abrupt" (RN40
  50,000, CN16 .025: tau 1.25 ms, inferred).
- Rate: "the periodicity being preferably in the order of seven per second" [P682]. No
  source found for the depth in cents.

## 6. Preamp, power amp, supply (SM2 pp. 10-11, Figs. 21-24)

- Preamp (Fig. 21): **a 6J7-G and a 6J5-G** (SM2 p. 10; the plan's "2 x 6J7" needs
  checking). "This condenser [expression] is variable and is arranged in a degenerative
  feed-back circuit so that a reduction in its capacity increases the volume". Fixed bias
  from the -192 V supply. Hum bucking: power-amp output fed into the 6J5-G cathode. 50,000
  ohm grid stopper on the 6J7-G. "The output transformer has a 500 ohm push-pull output."
  Unused speaker post "grounded through a 12 ohm resistor". Volume-adjust condenser
  .0234 (OCR of Fig. 21, unverified).
- Power amp (Fig. 22): "a standard Hammond Organ amplifier using two type 56 input tubes and
  four 2A3 tubes in push-pull parallel". Two 12" dynamic (field-coil) speakers; Fig. 22 shows
  fields of 250 ohms and 5,000 ohms (OCR; which speaker has which not checked).
- Supply (Fig. 23, text p. 11): filtered by tubes instead of condensers. "Rectifier tube A
  supplies 270 volts", ripple cancelled by tubes B, C, D; "Tubes E, F and G operate similarly
  for the 70 volt tap"; "Rectifier tube J supplies 260 volts for keying. Tube I furnishes 192
  volts bias for the dividers and the preamplifier, while tube H supplies 50 volts to the
  vibrato driving coils." Fig. 24 terminal card: +270, +70, +34, +17, ground, -192 (-200 in
  earlier models), -50, -260 / -270 keying. Rectifiers 5V4G and 5Y3-G appear (SM2 p. 18 and
  Fig. 23). Tolerance: 10% each, 15% if all move together (SM2 p. 15).
- [DS] measured on a restored unit: "The positive rail is at 300v DC. The negative rail is at
  -300v DC."

## 7. Keyboard

- 72 keys, F to E: twelve oscillators F to E at the top octave plus five dividers each (SM2
  p. 5). With A = 1760 Hz at the top (Fig. 12), the range is F1 (43.65 Hz) to E7 (2637.0 Hz)
  (inferred, A440 equal temperament). Key numbering in SM2: notes 1-72, note 1 presumably the
  lowest (the brown cut-off tap serves notes 1-4).

## Not found / open

- Inductances of the tuning coils and of LN2-LN5 (so the resonator frequencies).
- The vibrato depth in cents and each reed's rate.
- Per-note values within the printed ranges (CN2, CN3, CN4, CN1, RN7, CN15, RN23, CN18):
  the manual's condenser pan chart (pp. 24-25) lists stock values, not per-note picks.
- Not yet read: discretesynthesizers.com sub-pages (generator.htm, control.htm, power.htm);
  SM-orig compared with SM2; the full trace of Fig. 15's triode-2 network.

## Walled / needs the user

- None needed for the above. The GroupDIY thread from the plan
  (https://groupdiy.com/threads/looking-for-hammond-novachord-service-manual.40260) is moot now
  that the manual is on archive.org.
