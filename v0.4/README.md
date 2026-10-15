# Forecast Scorecard working bundle

Purpose: inspect and recalculate the frozen forecast ledger with its source, review and comparison limits.

This work was produced through an AI-assisted workflow directed and reviewed by the author.

Version: 0.4. Every registered observation carries a current independent claim-support receipt in SUPPORT_REVIEW.json; RESULTS.json gives the counts by verdict. The candidate observations added in this version, in CANDIDATE_OBSERVATIONS.json, carry current supported receipts in CANDIDATE_SUPPORT_REVIEW.json; a candidate enters arithmetic only with a current supported receipt. Only observations with a supported receipt enter arithmetic or spans. Earlier versions remain available from [AI Energy-Demand Forecast Scorecard](https://doi.org/10.5281/zenodo.20572928).

Start with PAPER.md and FORECASTS.md. This bundle uses Python's standard library, with no network access, credentials, GPU or model calls. Python 3.11 or newer is required. No runtime verification receipt is included in this bundle.

Run in your terminal from the extracted folder:

```sh
python3 -B reproduce.py --check
```

The check is read-only. It validates inputs, including the candidate and prior-work records, recalculates declared outputs, binds review receipts to the current observation records and source catalogue, and candidate receipts to the current candidate records and candidate source list, checks that the paper carries verbatim every table, count and statement generated from the records, including the lower-bound statement, and compares output bytes and package hashes. A matching manifest does not authenticate the creator or withstand coordinated replacement of files and manifest. It does not verify source truth, rebuild the providers' models or accept the paper's scientific claims.

Arithmetic and recorded-value spans use only observations with a current supported receipt in SUPPORT_REVIEW.json. A candidate in CANDIDATE_OBSERVATIONS.json enters them, and declared comparisons, only with a current supported receipt in CANDIDATE_SUPPORT_REVIEW.json, which names the digests of the candidate row and of the candidate source list; without one it confers nothing, and reproduce.py --explain with its ID reports its status. A receipt names the digests of the observation and of the complete source catalogue. Changing a claim field or bound evidence makes its receipt stale; the status becomes review stale and arithmetic is refused. The maker_assessment field is excluded from the claim digest. The maker's own assessment is recorded in each row and never enables arithmetic. A comparison involving an observation without a current supported receipt returns not_comparable with the review status as one of its reasons.

To inspect a forecast together with its source, digest and review status, run in your terminal:

```sh
python3 -B reproduce.py --explain O12
```

To examine the different-base-year comparison, run in your terminal:

```sh
python3 -B reproduce.py --compare O11 O12
```

The returned not_comparable state is an intended result. A changed percentage denominator is not a forecast decline. Other checks refuse different units, metrics, value bases (a tabulated value against a rounded text figure), upper-bound and open lower-bound statements, explicit scenario or coverage differences and unresolved cross-publisher scope. The field definitions in OBSERVATIONS.json explain the shape, value basis, coverage and superseded_by fields. Comparisons within a publisher-linked series remain conditional on the recorded interpretation and source qualifications.

To print the generated tables and statements that the paper must carry, run in your terminal:

```sh
python3 -B reproduce.py --paper-blocks
```

Run the worked example in your terminal:

```sh
python3 -B reuse_example.py
```

Run the tests in your terminal:

```sh
python3 -B test_reproduce.py -v
```

Tests work on disposable copies and use fixture receipts to exercise the arithmetic paths. They include invalid inputs, stale receipts and deliberate output corruption. They do not run forecasters' models or modify the bundle. Running Python without -B can write a bytecode cache into the folder, after which the package check refuses the unexpected entry.

To generate the declared outputs in a new directory outside this bundle, run in your terminal:

```sh
python3 -B reproduce.py --output-dir ../forecast-regenerated
```

An existing directory, an output location inside the bundle or a symlink destination is refused, and a failed write removes the partly written directory. Generation does not check package integrity. Editing a value does not update its source evidence or confer acceptance: review its period, scope, qualifications and source support together. Machine arithmetic retains its calculation precision; that precision is not uncertainty precision for an approximate source forecast.

## Contents

| File | Role |
| --- | --- |
| OBSERVATIONS.json | Authoritative proposed ledger, field definitions, qualifications, unresolved records, known unregistered values and comparison pairs |
| SOURCE_CATALOGUE.json | Public references, source locators and inspection limits |
| SUPPORT_REVIEW.json | Independent support verdicts bound to observation and source digests |
| CANDIDATE_OBSERVATIONS.json | Candidate observations added in this version, their sources, the selection rule, known unregistered values and the search record |
| CANDIDATE_SUPPORT_REVIEW.json | Independent support verdicts for the candidates, bound to candidate row and candidate source-list digests; only a supported receipt admits a candidate to arithmetic |
| PRIOR_WORK.json | Earlier-work sources and the comparison with the IEA 4E review's catalogue |
| LEGACY.csv | Byte-preserved historical dataset; earlier verified labels are not current acceptance |
| reproduce.py | Input checks, review binding, bounded arithmetic, explanation and read-only package checks |
| test_reproduce.py | Positive and negative regression checks on disposable copies |
| reuse_example.py | A review-gated revision and a refused baseline comparison |
| FORECASTS.csv and FORECASTS.md | Generated views of the authoritative ledger |
| RESULTS.json | Review status, calculations, denominators, recorded-value spans, the like-for-like comparison, admitted candidates and unresolved records |
| PAPER.md | Interpretation and full coverage limits |
| REPRODUCTION.json | File checksums and entrypoints; does not hash itself |

The catalogue excludes private file paths, internal review logs and raw third-party documents. Provider statements are attributed observations. Source matching, calculation reproduction, independent acceptance and author release are separate states. REPRODUCTION.json records independent acceptance of the package as pending, and each SOURCE_CATALOGUE.json entry marks its independent review as pending.

NM AI Research material: CC BY 4.0. Third-party sources retain their own rights.

## Verification

Each registered value is traced to the source and locator recorded in SOURCE_CATALOGUE.json and OBSERVATIONS.json, and its independent claim-support receipt is in SUPPORT_REVIEW.json. Candidate values are traced to the sources recorded in CANDIDATE_OBSERVATIONS.json, with any independent receipt in CANDIDATE_SUPPORT_REVIEW.json, and values attributed to the IEA 4E review to PRIOR_WORK.json, which carries no receipts. `python3 -B reproduce.py --check` verifies the package; the paper's Verification note describes the checks and their limits.

## AI assistance, conflicts and limitations

The research design, method, sourcing decisions and analytical judgements are the author's. OpenAI GPT-6 and Anthropic Opus 5.5 and Fable 5.1 assisted with data retrieval, calculation, literature search and drafting, so this text was artificially generated and was reviewed by the author before publication. The assisting models are not always neutral parties to the subject matter: OpenAI, whose GPT-6 model also reviewed the claim support for the candidate observations, Anthropic, and Google, whose Gemini 3.8 Flash High model reviewed the claim support for the registered observations and the hand-written sentences of the paper, all take part in the AI industry whose data-centre electricity demand these forecasts describe.

Guarantee: every measured claim is traced to the primary document recorded in SOURCE_CATALOGUE.json, PRIOR_WORK.json or CANDIDATE_OBSERVATIONS.json as described in the paper's Verification note, and reproduce.py regenerates every table from OBSERVATIONS.json, SOURCE_CATALOGUE.json, SUPPORT_REVIEW.json, CANDIDATE_SUPPORT_REVIEW.json, PRIOR_WORK.json and CANDIDATE_OBSERVATIONS.json. Modelled or estimated inputs are identified as such in each observation's value basis and qualification in OBSERVATIONS.json, CANDIDATE_OBSERVATIONS.json and FORECASTS.md, rather than presented as measurements. A reader can check this without trusting either party.

What the author cannot guarantee: a language model's output can be wrong in ways that survive review. In prose the error is locally plausible and consistent in tone with what surrounds it; in code it simply runs, and a wrong constant or a mis-set filter still returns a clean number. Several methods have been deployed to mitigate this, including explicit instructions, internal red-teaming and cross-lab blindspot checks, but the author does not claim the review is exhaustive. Corrections are logged against the DOI when surfaced.

No warranty is offered beyond the terms of the CC BY 4.0 licence. Independent analysis and open-science documentation only, not investment advice.
