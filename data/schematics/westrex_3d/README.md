# The Westrex 3D stereo disc recorder and the 1960s disc standards: sources

The lathe of docs/PHONO_PLAN.md's "The 1960s record player": a Westrex 3D StereoDisk cutter with
feedback, driven by an RA-1574-D amplifier, on a Scully lathe. The local copies here are
git-ignored; this README is the citation.

## The cutter and its amplifier

- **[DF58]** C. C. Davis and J. G. Frayne, "The Westrex StereoDisk System", *Proc. IRE* 46(10),
  1686-1693, 1958. This is the 3A. Web:
  https://dsu-digital-sound-design.github.io/f-23-history-of-recorded-music/lectures/week-8/control-men/The_Westrex_Stereo_Disk_System.pdf
  (local: `davis_frayne_1958.pdf`).
  - 45/45 geometry, with a drive coil and a feedback coil per channel on one magnesium form.
  - Wire links "relatively stiff ... in a forward direction but with relatively high compliance
    in a lateral direction": each driving system carries "only its components and a negligible
    portion of the other driving system".
  - A tubular cantilever stylus support.
  - "a feedback of approximately 27 db at the resonant frequency ... held up the high-frequency
    response to at least 15 kc"; the natural frequency "about one octave above the geometric
    mean frequency".
  - Worst program peak: 19 cm/s, 0.6 A rms in one 5.6 ohm drive coil, ~2 W.
  - The vertical angle: 23 degrees.
- **[NS64]** C. S. Nelson and J. W. Stafford, "The Westrex 3D StereoDisk System", *JAES* 12(3),
  178-185, July 1964. Web: https://www.collinsaudio.com/Westrex%203D.pdf (local:
  `nelson_stafford_1964.pdf`).
  - Fig. 4: I^2R in the drive coil against velocity (plate clipping 13 dB above 3.5 cm/s).
  - Fig. 5: feedback characteristics.
  - Fig. 6: response without feedback, 0 dB = 7 cm/s.
  - Fig. 7: response with feedback (27 dB for the 3C, 28 dB for the 3D).
  - Fig. 8: the feedback coil's voltage.
  - The 3D's drive coil has twice the 3C's impedance and is ~25% more efficient. 40-55 W can be
    dissipated "in a mass of 0.4 g".
  - The 3D's cutting stylus is a one-piece sapphire.
  - **RA-1574-D**:
    - 75 W at < 1% distortion, 30 Hz - 15 kHz;
    - -15 dBm input for 3.5 cm/s; 600 ohm input;
    - noise at least 80 dB below 75 W;
    - a plug-in constant-velocity card per cutter, +-1 dB 50 Hz - 12 kHz, +-2 dB 12-15 kHz;
    - an RIAA IN / OUT switch.
- **[Bauer 63]** B. B. Bauer, "The vertical tracking angle problem in stereophonic record
  reproduction", *IEEE Trans. Audio* AU-11, 47, 1963, in the March-April 1963 issue. Web:
  https://worldradiohistory.com/Archive-IRE/60s/Audio/IRE-Transactions-On-Audio-1963-03-04.pdf
  (local: `ire_trans_audio_1963_03.pdf`).
  - Lacquer and stylus springback: tan C = tan B - c a, with c a = 0.42. So the Westrex's 23
    degrees cuts at ~0 degrees effective slant.
  - The RIAA committee recommended 15 degrees in 1961.
  - The cutting force is 40 g at 0.004 cm depth.
  - The longitudinal compliance is 0.042e-6 cm/dyn, 60-80% of it the lacquer's.
- **Not found (paywalled):** Gravereaux and White, "Lacquer warp, advance ball, and disc cutter
  dynamics", AES Conv. 52 paper 1090 (1975) / *JAES* 24(3), 182-185 (1976). It is an equivalent
  circuit with values "deduced from experimental data for a Westrex 3DII cutter mounted on a
  Scully lathe", and it would replace the fit below.

**Unpublished in what we have**: the moving mass, Bl, the coil's inductance, the suspension's
stiffness and the feedback coil's sensitivity. The model fits them to NS64's Figs. 6-8 and
Fig. 4 (`scripts/fit_westrex_3d.py`). Each fitted value's source says so.

## Standards

- **NAB Disc Standard, February 1964**. Web:
  https://www.richardhess.com/tape/history/NAB/NAB_Disc_Standard_1964_searchable.pdf (local:
  `nab_disc_standard_1964.pdf`).
  - §3.05, the reproducing curve: t1 75, t2 318, t3 3180 us. Recording is its inverse.
  - Reference levels: 7 cm/s peak at 1 kHz for mono (§3.10); 5.0 cm/s peak per channel in its
    own plane for stereo (§3.15).
  - Footnote 7: program peaks of ~21 cm/s.
  - §2.55, the stereo groove: 90 +- 2 degrees included; top width at least 0.001 in; bottom
    radius at most 0.0002 in.
  - Outer wall = the right channel; in-phase signals cut laterally.
  - Separation at least 26 dB, 100 Hz - 7.5 kHz.
  - Turntable wow and flutter at most 0.04%. Rumble at least 35 dB below 1 cm/s at 100 Hz.
  - HF noise at least 50 dB below 5 cm/s, 500 Hz - 15 kHz.
  - Warp: at most 1/16 in TIR.
- **RIAA Bulletins E1 and E4 (1978)**, the LP's dimensions. Web:
  https://www.bostonaudiosociety.org/pdf/RIAA%20Bulletins%20E1%20&%20E4_1978%20LP%20dimensional%20standards.pdf
  (local: `riaa_e1_e4_1978.pdf`).
  - The 12 in record: outermost groove at most 11.5 in across, innermost at least 4.75 in.
  - Lead-in 16 +- 2 grooves/in; run-out 2-6 grooves/in.
  - Runout 0.016 in TIR.

## The vinyl

- **Barlow, *Wireless World*, April 1964, pp. 160 ff.** Web:
  https://www.worldradiohistory.com/UK/Wireless-World/60s/Wireless-World-1964-04.pdf (local:
  `wireless_world_1964_04.pdf`).
  - Vinyl chloride with ~16% vinyl acetate.
  - E = 300 kg/mm^2 (2.94 GPa); Poisson's ratio 0.35; yield 4.5 kg/mm^2.
  - The dynamic modulus is 4.5-6.5% above the static.

## Lathes, for comparison

Gotham Audio's 1966 catalogue, web:
https://www.worldradiohistory.com/Archive-Catalogs/Miscellaneous-Manufacturers/Gotham-Audio-1966.CV01.pdf:
- the Neumann AM 32b: 90-475 lpi at 33-1/3, wow and flutter under 0.035% rms;
- the preview head half a revolution ahead.
