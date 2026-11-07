# Sennheiser MD 421 (CHAINS_PLAN.md WP14)

- Sennheiser's MD 421-II Product Specification V1.1 (PNG of page 2 here; curves in
  `data/datasheets/sennheiser_md421_*.csv`, `scripts/digitize_md421.py`): pressure-gradient
  dynamic cardioid, 30-17,000 Hz, **2 mV/Pa +-2.5 dB**, **250 ohm** (earlier sheets: 200 ohm,
  and 2 mV/Pa +-3 dB), 215 x 46 x 49 mm, ~385 g; five-position bass roll-off switch ("M"
  music = flat; the other four dip to roughly -5 / -9 / -12 / -20 dB at 50 Hz); "internal bass
  tubes" (the rear path), acoustic parts in an inner chassis, glass-composite housing,
  hardened stainless-steel basket. Response (dBV for 1 Pa): flat -54 dBV 100 Hz-1 kHz, a
  +7 dB presence rise 3-8 kHz, a steep fall above ~14 kHz. Polars at 125-16000 Hz: -3.5 dB
  at 90 deg at 125 Hz, -7.7 dB at 500-2000 Hz, ~-25 dB at 150-180 deg 1 kHz.
- Not found: the cartridge's construction (diaphragm size, the bass tubes' dimensions,
  the switch's network values). The cartridge is fitted to the curves (the D112's method:
  `scripts/fit_d112.py`), the switch a provisional passive network on the output fitted to
  the four dips. A teardown or Sennheiser's patent for the MD 421 (US 3,??? , 1960s) would
  bound the construction: not looked up yet.
