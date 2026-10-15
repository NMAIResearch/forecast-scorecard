# AI Energy-Demand Forecast Scorecard

Data, code and paper for *The AI Energy-Demand Forecast Scorecard: what data-centre electricity forecasts measure and what can be checked*, by NM AI Research (ORCID
[0009-0003-4213-7769](https://orcid.org/0009-0003-4213-7769)). Licence: CC BY 4.0.

This work was produced through an AI-assisted workflow directed and reviewed by the author.

- **Version 0.4** is in [`v0.4/`](v0.4/). Its 17 files are byte-identical to the Zenodo record
  [10.5281/zenodo.23384001](https://doi.org/10.5281/zenodo.23384001).
- **All versions:** [10.5281/zenodo.20572928](https://doi.org/10.5281/zenodo.20572928) resolves to the latest version.
- **Interactive page:** https://nmairesearch.github.io/forecast-scorecard/ shows the earlier v0.2 dataset; see below.

## Version 0.4

Forecasts of data-centre electricity demand from different publishers measure different quantities, draw different boundaries and date from different editions. Each registered figure is tied to a retained publication and an independent claim-support receipt, with dates, edition, target and base years, unit, quantity, scenario and coverage kept as separate fields. A revision is computed only where one publisher states both figures for the same quantity and both carry supported receipts, and every declined comparison is listed.

Start with `v0.4/PAPER.md` or `v0.4/PAPER.pdf`, and `v0.4/FORECASTS.md`. To check the package, run in your terminal from
the `v0.4` folder:

```sh
python3 -B reproduce.py --check
```

The check needs Python 3.11 or newer and uses only the standard library, with no network access. `v0.4/README.md` lists
the other commands, the role of every file and what the check does not verify. This repository's `.gitattributes` turns
off line-ending conversion, because the check compares exact bytes.

## Guardrails

The paper makes no demand forecast, accuracy ranking or capacity-uplift estimate.

## What it does: the interactive page (v0.2 data)

`index.html`, `build.py` and `forecast_scorecard_data.csv` make up the interactive page at
https://nmairesearch.github.io/forecast-scorecard/. It shows the 11 forecasts of the v0.2 dataset (Zenodo version
[10.5281/zenodo.20708978](https://doi.org/10.5281/zenodo.20708978), 15 June 2026) and has not been rebuilt for version 0.4. Its "verified" and "confirmed"
labels belong to that dataset; they are not version 0.4's claim-support verdicts. `build.py` regenerates `index.html` by
embedding the CSV, using only the Python standard library.

## Disclosure: AI assistance, conflicts and limitations

The statement for version 0.4 is in `v0.4/README.md` and at the end of the paper. Independent analysis and open-science documentation only, not investment advice.
