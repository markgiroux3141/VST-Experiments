# beyerdynamic M 160 (CHAINS_PLAN.md WP17)

Supplied by the user (2026-11-10; in the repo since that session):

- `m160_data_en.pdf` (sha256 b91cb6e864525e5252890b5c561a6873553fd1a4e2a115ab1c38800c50e2d69f):
  beyerdynamic's product data, Order # 100.668. Technical specifications: dynamic, pressure
  gradient, 40-18,000 Hz, **hypercardioid**, **rear attenuation at 1 kHz > 25 dB at 110 deg**,
  **open circuit voltage at 1 kHz 1.0 mV/Pa** (-60 dBV), **nominal impedance 200 ohm**, load >=
  1000 ohm, pure aluminium diaphragm, brass case, head 38 mm, shaft 23 mm, 156 mm long. The
  frequency response (+-2.5 dB, 0 dB = 1.0 mV/Pa) at 1 m, 10 cm and 2 cm, an embedded image:
  the 1 m trace digitized (`data/datasheets/beyer_m160_response.csv`, its provenance sidecar).
  The polar pattern (125 Hz-16 kHz, a 3D-looking drawing): not digitized. The wiring diagram:
  the ribbon motor across a transformer's primary, the secondary to pins 2 (ge) and 3 (bl).
- `M160_BA_DE_01.pdf`: the product information (German): "Hypernierencharakteristik mit einer
  Störschallauslöschung von 25 dB bei 110°"; the two red dots mark the ribbons' long axis
  (vertical on a stand).
- `Resolution-M160.pdf`: Resolution magazine's review (May/June 2007): "two aluminium ribbons
  spaced 0.5mm apart", hypercardioid, a pronounced proximity bump.

No construction is published. `RIBBON_M160` (published_points.yaml) models the two ribbons as
one equivalent ribbon on RIBBON_77DX's polydirectional circuit with a fixed slot behind it; its
unknowns are fitted by `scripts/fit_m160.py` (CHAINS_PLAN.md WP17's Notes).
