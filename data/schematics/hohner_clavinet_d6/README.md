# Hohner Clavinet D6: sources

What the model (docs/CLAVINET_PLAN.md; `config/clavinet/d6.yaml`, `config/circuits/clavinet_d6.yaml`)
is built from, gathered 2026-11-06. Every value in the config files cites one of these, or is
marked `provisional`.

## Measurements of a D6 (the anchor)

- **[G13]** L. Gabrielli, V. Välimäki, H. Penttinen, S. Squartini, S. Bilbao, "A digital
  waveguide-based approach for Clavinet modeling and synthesis", *EURASIP J. Adv. Signal
  Process.* 2013:103, doi:10.1186/1687-6180-2013-103. Open access (CC-BY 2.0); the provisional
  PDF: https://www.ness.music.ed.ac.uk/wp-content/uploads/2013/06/Gabrielli.pdf.
  - The D6 (2): 60 keys F1-E6, the first 23 strings wound; the tangent traps the string on the
    anvil for the note's duration; the yarn on the pin side.
  - The tone (2.3): T60 of low and mid notes 20 s or more; the 2nd partial always >3 dB above
    the 1st.
  - Release (2.3.1): the pitch drops 3 semitones for the whole keyboard; Fig. 5 (release at
    0.5 s, the partials gone ~0.1 s later).
  - Inharmonicity: Table 1 (B for F1, A#1, D3, D#3, F#5, E6) and Fig. 6 (B over the keyboard:
    flat ~9e-5 above 150 Hz).
  - Decay: Fig. 7 (A2 partials, piano and mezzoforte, with beating), Fig. 8 (E4 partials' T60).
  - Beating: 0.5-2 Hz, up to 15 dB, only up to E4.
  - Pickups: impedance Fig. 9 (~10.2-10.9 kOhm); flux against string distance Fig. 10.
  - The amp (2.1, 2.3.6, 3.4): two-stage BJT, the tone switches as four filter cells (Table 3:
    SOFT 30 kOhm / 0.1 uF, MEDIUM 10 kOhm / 15 nF, TREBLE 2 H / 4.7 nF, BRILLIANT 0.6 H);
    their SPICE responses (Fig. 11); without the switches nearly flat (-3 dB shelf at 130 Hz,
    +3 dB at 4 kHz); THD 1% at 1 kHz for 400 mV in (the pickups' largest in normal polyphonic
    playing), 3.6% on fortissimo chord peaks.
  - The knock (3.5): mostly below 1.2 kHz.
  - Key velocity (3.2): 1-4 m/s.
- **[R12]** L. Remaggi, L. Gabrielli, R. C. D. de Paiva, V. Välimäki, S. Squartini, "A pickup
  model for the Clavinet", DAFx-12, York 2012,
  https://dafx.de/paper-archive/2012/papers/dafx12_submission_62.pdf.
  - Six bars of ten strings (each bar 0.5 cm wide; 3.7 cm long on the centre pickup, 3.3 cm
    on the bridge).
  - Positions: the centre pickup 18.5 cm (lowest string) to 6.5 cm (highest) from the string
    termination; the bridge pickup a constant 4 cm, tilted ~30 deg in plan.
  - Fig. 4: the Vizimag geometry (37 mm magnets 7 mm high, 3 mm apart). Fig. 5: flux against
    displacement (centre / edge strings); vertical motion 25-30 dB above horizontal.
  - Table 1: the pickup switches.
  - An example string: 67.8 cm at 161 Hz.

**Two disagreements** between the papers, settled for now as the config says:
- [G13] 2.1 writes "10 metal bar coils ... six strings each"; [R12]'s dimensioned figure has six
  bars of ten. The figure is followed.
- [R12] puts the centre pickup above the strings and the bridge pickup below; [G13] the other
  way round. The journal paper is followed.

## Strings

- Plain strings keys 24-60 one gauge, different lengths: Clavinet.com message board,
  https://www.tapatalk.com/groups/clavinetdotcommessageboard39332/clavinet-strings-question-t514.html.
- The original plain gauge .008 in (replacements .009): https://ep-forum.com/smf/index.php?topic=9669.0.
- Wound types by key (1-8, 9-14, 15-23; plain 24-60): a NOS D6 / E7 string listing,
  https://www.ebay.com/itm/316149692228.
- Wound gauges .032 / .028 / .022 in: Vintage Vibe's replacement set,
  https://www.vintagevibe.com/products/clavinet-strings.
- Not found: per-key lengths (derived from [G13]'s B, `varimu/clavinet/spec.py`), tensions,
  wrap material.

## The electronics

- The D6's front-end transistor, a **BC 413C** (and the caps on the preamp board: .01 uF film,
  4.7 nF between the two inductors, .22 uF output, .015 uF, 100 uF / 16 V, 6.8 uF / 20 V
  tantalum): Clavinet.com, "Upgrading the D6 Preamp" (Jim Williams),
  https://clavinet.com/d6upgrade.php.
- E7 / D6 preamp notes (BC550C in the preamp, an 8.2 V zener and BC238 regulator added on the
  E7 for adapters, a 100 uF filter, an 8.2 pF cap, a battery at ~8.8 V under load, an input
  transformer on the E7's "rot" side): GroupDIY, https://groupdiy.com/threads/clavinet-e7.38507.
- The Clavinet C's preamp: AC151 germanium PNP, positive ground, 9 V:
  https://chicagoelectricpiano.com/clavinet/hohner-clavinet-schematic-tone-controls/ and
  GroupDIY https://groupdiy.com/threads/clavinet-c-audio-issues.81284.
- **In hand: Hohner's E7 schematic**, `clavinete7.jpg` ("Schaltbild Hohner-Clavinet E 7,
  St.-Nr. 801 111"; found by the user 2026-11-06). Two pickups of six coils, the two
  ganged pickup rockers, an input transformer (Beyer TR 145, BV 35 569, 1:15) into a 10 nF
  and a BC550C with 1 MOhm || 8.2 pF collector-to-base feedback and a 12 kOhm load (emitter
  grounded); 0.22 uF into the tone chain (30k || 0.1u, 10k || 15n, 2 H || 4.7n, 0.6 H, each
  rocker shorting its cell: the chain [G13] Table 3 gives, and the topology inferred from
  its Fig. 11); 30 kOhm and 10 nF into a second BC550C (620k / 100k divider, 10 kOhm load,
  2.2 kOhm + 1 kOhm || 6.8 uF emitter), 0.22 uF to a 100 kOhm log volume and the jack; the
  rail a BC238 follower on an 8.2 V zener (1.8 kOhm), 100 uF. The chokes: Siemens pot cores
  14 x 8, N30, AL 4200 (B65541-K0000-R030), 2 H = 700 turns of 0.09 mm CuL, 0.6 H = 400
  turns of 0.1 mm CuL (the drawing's 0.5 H symbol disagrees with its own table).
- **Still not in hand: the D6's own schematic** (the E7's above is used: the same tone cells,
  [G13] Table 3). [G13] cites it as clavinet.com's "Clavinet D6
  amplifier schematic" (http://www.gti.net/junebug/clavinet/Clavinet%5FD6%5Fschematic.pdf,
  dead). Copies: Chicago Electric Piano's translated D6 / E7 wiring
  (https://chicagoelectricpiano.com/hohner/clavinet-schematic-wiring/, an image), Vintage
  Vibe's preamp kit instructions (https://www.vintagevibe.com/products/clavinet-preamp-rebuild-kit,
  "Instructions" tab), the GroupDIY threads' attachments (login): the user found the first
  two pages gone (2026-11-06). The amp in `config/circuits/clavinet_d6.yaml` was a
  provisional two-stage design until the E7's schematic was read (2026-11-06).

## Other

- The harp's layout (strings diagonal under the keys): Wikipedia, https://en.wikipedia.org/wiki/Clavinet.
- Physical models for comparison (not used as data): Bilbao & Rath, "Time domain emulation of the
  Clavinet", AES 128th Convention, London 2010; Gabrielli, Välimäki, Bilbao, "Real-time
  emulation of the Clavinet", ICMC 2011.
