# AI Energy-Demand Forecast Scorecard

Data, code and paper for *The AI Energy-Demand Forecast Scorecard: what data-centre electricity forecasts measure and what can be checked*, by NM AI Research (ORCID
[0009-0003-4213-7769](https://orcid.org/0009-0003-4213-7769)). Licence: CC BY 4.0.

This work was produced through an AI-assisted workflow directed and reviewed by the author.

- **Version 0.5** is in [`v0.5/`](v0.5/). Its 17 files are byte-identical to the Zenodo record
  [10.5281/zenodo.23434495](https://doi.org/10.5281/zenodo.23434495).
- **Version 0.4** is in [`v0.4/`](v0.4/). Its 17 files are byte-identical to the Zenodo record
  [10.5281/zenodo.23384001](https://doi.org/10.5281/zenodo.23384001).
- **All versions:** [10.5281/zenodo.20572928](https://doi.org/10.5281/zenodo.20572928) resolves to the latest version.
- **Interactive page:** https://nmairesearch.github.io/forecast-scorecard/ shows the version 0.5 records; see below.

## Version 0.5

Forecasts of data-centre electricity demand from different publishers measure different quantities, draw different boundaries and date from different editions. Each registered figure is tied to a retained publication and an independent claim-support receipt, with dates, edition, target and base years, unit, quantity, scenario and coverage kept as separate fields. Candidate figures reach beyond the ledger's Global and US figures, to the Australian National Electricity Market, Europe and China as the IEA defines them, France, Denmark, Italy, Great Britain, Norway, Germany, Finland, Sweden, Belgium, Poland, Switzerland and the European Union. A revision is computed only where one publisher states both figures for the same quantity and both carry supported receipts, and every declined comparison is listed. The paper makes no demand forecast, accuracy ranking or capacity-uplift estimate.

Start with `v0.5/PAPER.md` or `v0.5/PAPER.pdf`, and `v0.5/FORECASTS.md`. To check the package, run in your terminal from
the `v0.5` folder:

```sh
python3 -B reproduce.py --check
```

The check needs Python 3.11 or newer and uses only the standard library, with no network access. `v0.5/README.md` lists
the other commands, the role of every file and what the check does not verify. This repository's `.gitattributes` turns
off line-ending conversion, because the check compares exact bytes.

## Guardrails

The paper makes no demand forecast, accuracy ranking or capacity-uplift estimate.

## What it does: the interactive page

`index.html` and `build.py` make up the interactive page at https://nmairesearch.github.io/forecast-scorecard/. It shows
each registered observation and candidate of version 0.5 with its receipt status and source, and the like-for-like
groups with their recorded spans. `build.py` writes the page's tables from the files in `v0.5/`, using only the Python
standard library. To check the page against those files, run in your terminal from the repository root:

```sh
python3 -B -m unittest test_page -v
```

### What it does: the interactive page (v0.2 data)

The page of the v0.2 dataset (Zenodo version [10.5281/zenodo.20708978](https://doi.org/10.5281/zenodo.20708978), 15 June
2026) is kept in `v0.2/`, with its own `build.py` over `forecast_scorecard_data.csv`. Its "verified" and "confirmed"
labels belong to that dataset; they are not the claim-support verdicts of later versions.

## Disclosure: AI assistance, conflicts and limitations

The statement for version 0.5 is in `v0.5/README.md` and at the end of the paper. Independent analysis and open-science documentation only, not investment advice.
