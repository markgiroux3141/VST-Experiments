# Fairchild 670 schematic crops

Crops of drawing A-96039, "670 Dual Limiter Schematic", from the Fairchild 670
instruction manual (Fairchild Recording Equipment Corp., dated Dec 1959).

- Source: http://thehistoryofrecording.com/Manuals/Fairchild/Fairchild_670_stereo_limiting_amplifier_instructions_Schematics.pdf
- sha256 of the downloaded PDF: `0ede9ed8d1294ada7b3e05a6f8ef89e7487a7530a2c7a36481c5c297bac7c535`
  (24 MB, scanned images, not committed)
- Rendered at 300 dpi and cropped on 2026-10-13. Values were read by eye.

| File | Shows |
|---|---|
| `audio_path.png` | AT101, T101, the four-triode 6386 banks, R103-R105 cathode network, C101/C102, T102, R107/R108/R111 |
| `sidechain_1.png` | T102 secondaries, R145-R150 pads, T103, R113-R119 threshold networks, 12AX7 (V105), 12BH7A (V106) |
| `sidechain_2.png` | 6973 pair (V107/V108), T104 with feedback winding, CR101-104 bridge, S102 time constant network, R142 ZERO |
| `psu_1.png`, `psu_2.png` | Rectifier, L301, C304-C306, EL34/6084/5651 regulator, bias supply |
| `notes.png` | Drawing notes, control list (AT101 input gain, R105 balance, R115 AC threshold, R117 DC threshold, R142 zero) |

`config/circuits/fairchild_670.yaml` cites these values as `sch:` (printed on the
drawing) or `sch-interp:` (wiring read off the scan, where it isn't certain).

Open questions from the scan:

- Where the 12BH7 grid leaks and cathode resistors return. They are modeled to
  ground, which leaves the 12BH7 plates at about 44 V.
- The return rail for the 6973 grid leaks. Modeled as a bounded genome parameter.
- How the dual-gang BALANCE pot's two wipers connect. Modeled as one pot with
  its wiper on the cathode return.
- C114, the trimmer between the grid lines, has no printed value and is omitted.
