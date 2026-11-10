# Shure SM7 / SM7B (CHAINS_PLAN.md WP15)

## Sources

- `us_pro_SM7B_specsheet.pdf`: Shure's SM7B product specification (2009), web:
  http://recordinghacks.com/pdf/shure/us_pro_SM7B_specsheet.pdf (linked from
  https://recordinghacks.com/microphones/Shure/SM7B): dynamic, cardioid, 50-20,000 Hz, 150 ohm,
  open circuit -59.0 dB (1.12 mV) re 1 V/Pa at 1 kHz; bass roll-off and mid-range emphasis
  switches. Its response chart (flat, bass roll-off, presence) and polar charts (250 / 500 /
  1000 Hz; 2500 / 8300 Hz) are vector paths: `scripts/digitize_shure_sm7.py` ->
  `data/datasheets/shure_sm7_response.csv` (frame +20 / -20 dB, 5 dB rules, log frequency on
  the 50 / 100 / 1000 / 10000 Hz rules); the polar points are read on a render
  (`scripts/fit_sm7.py`'s POLAR).
- No construction of the cartridge is published: R_SM7 starts from the MD 421's network form and
  is fitted (CHAINS_PLAN.md WP15's Notes).
