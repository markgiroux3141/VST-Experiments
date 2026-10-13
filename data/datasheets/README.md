# Digitized datasheet curves

Every CSV here is covered by a provenance sidecar. That's one
`<source>.provenance.yaml` per source document, listing each CSV taken from it
(e.g. `ge_6386.provenance.yaml` covers `ge_6386_plate.csv`, `ge_6386_transfer.csv`
and `ge_6386_cascode_gm.csv`). A curve without provenance must not be used for fitting.

- `sources/`: local copies of the datasheet PDFs (hashes in the sidecars).
- `published_points.yaml`: tabulated values transcribed from the sheets
  (operating points, capacitances, ratings), each with its source.

## CSV format

One row per point, SI units, with a header row. Use one column per swept
variable, e.g. `vg_v,vp_v,ip_a`.

## Provenance sidecar

```yaml
device: "6386"
curve: plate characteristics          # what the figure shows
document: "RCA 6386 data sheet"       # title as printed
publisher: RCA
date: TBD                             # as printed on the sheet
figure: TBD                           # page / figure number
scan_source: TBD                      # where the scan came from (URL or archive)
digitized_with: TBD                   # tool and version, e.g. WebPlotDigitizer 4.x
digitized_by: TBD
digitized_on: TBD
axis_calibration: TBD                 # reference points used
estimated_error: TBD                  # e.g. "±2% of full scale on Ip"
notes: ""
```
