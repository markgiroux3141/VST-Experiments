# Victor Orthophonic Victrola: sources

The acoustic gramophone matched by electrical analogy at Bell Labs (docs/PHONO_PLAN.md G2's
anchor). PDFs here are git-ignored.

- `maxfield_harrison.pdf`: J. P. Maxfield and H. C. Harrison, "Methods of High Quality
  Recording and Reproducing of Music and Speech Based on Telephone Research", Bell Telephone
  Laboratories, 1926 (Trans. AIEE; reprinted J. Audio Eng. Soc. 26(5), 1978, pp. 327-342).
  Found via web: https://charm-os.kdl.kcl.ac.uk/history/p20_4_1_3.html (fetched by the user,
  2026-11-18).

Used for: Fig. 20 digitized as `data/datasheets/maxfield_harrison_1926_fig20.csv` (provenance
`maxfield_harrison_1926.provenance.yaml`, with the PDF's sha256), the check of the Victor
model (`tests/test_gramophone.py`), and the Orthophonic's design figures (pp. 25-30, listed in
the provenance's notes and docs/PHONO_PLAN.md "Status (2026-11-18)").
