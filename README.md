# AI Energy-Demand Forecast Scorecard — interactive

An interactive front-end to *The AI Energy-Demand Forecast Scorecard*: a reproducible audit of **how the field forecasts data-centre electricity demand** — scored on dispersion, the forecasters' own revisions, and transparency. It is a scorecard of forecaster *behaviour*, not a forecast.

**Live tool:** https://nmiltonresearch.github.io/forecast-scorecard/
**Canonical record (frozen, citable):** [DOI 10.5281/zenodo.20572928](https://doi.org/10.5281/zenodo.20572928)
**Author:** N. Milton · ORCID [0009-0003-4213-7769](https://orcid.org/0009-0003-4213-7769) · Licence CC BY 4.0

## What it does

Two views, switched at the top:

- **Forecasts.** All 11 forecasts in their *published* units, scopes and horizons. **Dispersion** is computed only within a comparable slice (same scope, metric, unit, horizon) — narrow Scope + Unit to compare like with like. Leave them on "All" and the banner reports how many *incompatible formats* the field is using (the heterogeneity finding). Self-revisions are shown where a forecaster changed its own number; all logged revisions point up.
- **Transparency funnel.** Three nested tiers computed from the table: **verified** (confirmable against any credible source) ⊃ **confirmable at the primary source** (author-published) ⊃ **reproducible** (model rebuildable from public method + data). The gap between verified and reproducible is the headline: most figures can be quoted, few can be rebuilt.

The page embeds `forecast_scorecard_data.csv` verbatim, so it never goes stale and is not "live" — the canonical, citable version is the Zenodo DOI above.

## Files

- `index.html` — the interactive tool, self-contained (no dependencies, no server needed).
- `forecast_scorecard_data.csv` — the frozen forecast dataset.
- `build.py` — regenerates `index.html` by embedding the CSV (pure standard library). Edit the CSV, run `python3 build.py`, commit.

The full reproduce script (`forecast_scorecard_reproduce.py`) and write-up live in the [Zenodo record](https://doi.org/10.5281/zenodo.20572928).

## Guardrails

This scores how the field forecasts; it is **not** a forecast and takes no view on which number is right. "Opaque" means the model is proprietary / not reproducible, not that the figure is wrong. Units and scopes are not interchangeable: TWh, GW and % are different things; US is not Global; 2030 is not 2035.

## Disclosure

No third party reviewed, funded, or directed this work. The author holds no position that depends on any of these forecasts being right.

## Licence

Creative Commons Attribution 4.0 International (CC BY 4.0).
