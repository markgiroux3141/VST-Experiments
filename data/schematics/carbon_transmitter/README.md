# The carbon transmitter (CHAINS_PLAN.md WP31)

## Sources (found 2026-11-11; the extract is git-ignored: URL and sha256 here)

- W. C. Jones, "Instruments for the New Telephone Sets", Bell System Technical Journal 17 (July
  1938), pp. 338-357: the Western Electric F1 handset transmitter unit (the 302 set's) and its
  receiver. From worldradiohistory.com's BSTJ archive: the issue
  https://www.worldradiohistory.com/Archive-Bell-System-Technical-Journal/30s/Bell-1938c.o.pdf
  (sha256 444e5412ee3c31d75399d841a4e4c4207bc18e4e0c3232f8b509712b3d736022; the article is its PDF
  pp. 13-33); the article's pages extracted as `bstj17_1938_jones_instruments.pdf` (sha256
  85c226d016995c9ab8503c6eb0f11ba3af06499babf547227cd053ab1e6815d7).

What it gives (read 2026-11-11):
- p. 342-345: the "direct action" carbon element (electrodes proportioned so the current paths'
  pressure and length keep the resistance and modulation constant with position), the resilient
  silk closure, machine filling; Fig. 4 the positional characteristics; Fig. 5 the resistances.
- p. 347-349: **the equivalent circuit (Fig. 6)**: the diaphragm as three masses (the central
  m0 with the movable electrode, the ribbed intermediate m1, the outer m4) coupled by stiffnesses
  s3 / s2 with internal resistances r6 / r2; the paper "books" at the edge (s4, r4); the
  equalizing hole (m3, r3: its effect below 300 cycles); the controlling stiffness s3, the cavity
  between the diaphragm and the frame; the grid's holes (m0, r0), the cavity s0, the moisture
  membrane (m1, r1), the cavity s1 to the diaphragm; the carbon's impedance a function of
  amplitude and frequency. No element values are printed.
- **Fig. 6: the pressure response (measured, aged two years' equivalent; and computed from the
  circuit) and the field response (new and earlier units, an artificial voice): rising around
  2000 cycles** (deliberately: closer to direct speech with the new receiver).
- **Fig. 7: the sum and difference components (1500 + 1700 cycles) against the pressure (4-100
  bars), new and earlier units: the new unit's both >= 10 dB under the fundamental** (the
  difference component a property of the carbon itself, not of the input-output curve).

## Plan (not built)

The kind exists: `varimu/devices/carbon.py` (`CARBON_BUTTON@1`, the Victorian synth's: pins a, b,
force, ref; G(F) = G_open + G0 (F/F0)^n). The F1: the Fig. 6 network as an acoustic / mechanical
lumped circuit driving the force pin (masses and stiffnesses fitted to Fig. 6's pressure response,
one figure per unknown), the carbon's G0 / n fitted to the unit's resistance and to Fig. 7's
intermodulation; fed as in a telephone loop (the central office's 48 V battery through its feed
coils, provisional until a 302 set's circuit is sourced) into the clean preamp.
