# samples/

Sounds for the app's sampler, sorted from the user's sample library. Only this README is
committed: the audio is the user's (commercial packs), like `data/clips/`.

```sh
uv run python scripts/import_samples.py --root "D:/Music stuff/Reason/SAMPLE LIBRARY"   # rebuilds samples/drums/
uv run python scripts/import_samples.py --root DIR --dry-run [--list CATEGORY|none]    # what would go where
```

`drums/<category>/<pack>_<name>.wav` holds the drums and percussion: kick, snare, rim, clap, snap,
hihat_closed / _open / _pedal, hihat (state not named), crash, ride, cymbal (china, splash, other),
tom, hand_drum (conga, bongo, timbale, tabla, ...), shaker, tambourine, cowbell, metal_perc (agogo,
triangle, bells), wood_perc (clave, woodblock, guiro, ...), mallet, orchestral (timpani, concert bass
drum), perc (named "percussion" only), perc_fx (Neptunes-style knocks, clanks, clicks), roll and
loop.

The category comes from the file's name, or a pack's code (MACHINES' `K-` / `S-` / `H-` ...,
Neptunian's `N1K`, the Ambience Kit's GM codes), or the Dre / Timb / Inter / Vinyl banks' layout
(`DRE1-1AB 001`-`012` kicks, `013`-`022` snares). Numbered hits with nothing to go by are
guessed from their sound and go to `drums/unlabeled/<guess>/`. The guess is a 7-nearest-neighbour
vote trained on the named hits, 85% right on those (leave-one-out).

Every file is a PCM WAV at its source's rate and channels (16-bit, or 24-bit for 24-bit
sources), equal to the source sample for sample. Identical sounds are kept once.
`drums/index.json` lists each file's category, how it was decided, pack, rate, channels,
duration, the PCM's SHA-256 and every source it came from.
