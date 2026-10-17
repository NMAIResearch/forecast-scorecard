#!/usr/bin/env python3
"""Recalculate the frozen forecast ledger; no network or provider model runs.
Produced through an AI-assisted workflow (OpenAI GPT-6; Anthropic Opus 5.5) directed and reviewed by the author."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parent
OUTPUTS = ("FORECASTS.csv", "FORECASTS.md", "RESULTS.json")
FIELDS = ("id", "forecaster", "forecast_vintage", "source_publication", "geography", "horizon", "unit", "metric", "scenario", "shape", "value_basis",
          "low", "high", "point", "base_year", "crypto_scope", "coverage", "state", "comparison_family", "superseded_by", "source_id", "locator",
          "qualification", "method_description", "model_reproduction", "maker_assessment")
TEXT_FIELDS = ("id", "forecaster", "forecast_vintage", "source_publication", "geography", "unit", "metric", "scenario", "shape", "value_basis",
               "crypto_scope", "coverage", "state", "source_id", "locator", "qualification", "method_description", "model_reproduction", "maker_assessment")
VERDICTS = ("supported", "partly supported", "not supported", "contradicted", "unassessed")
UNRESOLVED = {"unstated", "data_centres_unspecified", "new_data_centres_unspecified"}
YEARS = range(2000, 2101)
LOWER_BOUND_WORDS = {"exclusive lower bound": "over", "inclusive lower bound": "at least"}
METRIC_NOUNS = {"annual_electricity": "consumption", "data_centre_capacity_demand": "capacity demand", "data_centre_capacity": "capacity",
                "installed_capacity": "installed capacity", "data_centre_power_demand_growth": "power demand growth"}
CANDIDATES = "CANDIDATE_OBSERVATIONS.json"
CANDIDATE_REVIEW = "CANDIDATE_SUPPORT_REVIEW.json"
PRIOR_WORK = "PRIOR_WORK.json"
CANDIDATE_STATUS = ("a candidate enters arithmetic, spans and declared comparisons only with a current supported receipt in "
                    "CANDIDATE_SUPPORT_REVIEW.json")
CANDIDATE_RECEIPT_FIELDS = ("candidate_id", "row_sha256", "candidate_source_list_sha256", "verdict", "reviewer", "review_record_sha256",
                            "locator", "components_short_of_supported", "components_unassessed_as_maker_conduct", "reason")
CANDIDATE_REVIEW_KEY = "candidate_support_review"
RELATIONS = ("same_publication", "earlier_edition", "publisher_only")
UNIT_LABELS = {"TWh": "TWh", "GW": "GW", "percent_growth": "per cent growth"}
HEX64 = re.compile(r"[0-9a-f]{64}")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def row_digest(row):
    """Digest of the claim; the maker's own assessment is excluded so it cannot be bound as review evidence."""
    return digest({k: v for k, v in row.items() if k != "maker_assessment"})


def catalogue_digest(sources):
    """Digest of every source record, so a change to auxiliary evidence also invalidates a receipt."""
    return digest([sources[k] for k in sorted(sources)])


def read_file(root, name):
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("Only flat bundle filenames are permitted")
    path = root / name
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or non-regular bundle file: " + name)
    return path.read_bytes()


def unique_keys(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate JSON key")
    return dict(pairs)


def read_json(root, name):
    return json.loads(read_file(root, name), object_pairs_hook=unique_keys,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Non-finite JSON: " + x)))


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid numeric value: " + name)
    return value


def year(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value not in YEARS:
        raise ValueError("Invalid year: " + name)
    return value


def check_row(row, source_map):
    if not isinstance(row, dict):
        raise ValueError("Forecast records must be objects")
    if set(row) != set(FIELDS):
        raise ValueError("Observation fields must match the declared schema: " + str(row.get("id")))
    for key in TEXT_FIELDS:
        if not isinstance(row[key], str) or not row[key].strip():
            raise ValueError("Missing text field: " + key)
    for key in ("comparison_family", "superseded_by"):
        if not isinstance(row[key], str):
            raise ValueError("Text field required: " + key)
    if row["source_id"] not in source_map:
        raise ValueError("Unknown source: " + row["source_id"])
    if row["unit"] not in {"TWh", "GW", "percent_growth"}:
        raise ValueError("Unsupported unit")
    if row["shape"] not in {"point", "scenario_range", "upper_bound", "lower_bound"}:
        raise ValueError("Unsupported estimate shape")
    if row["value_basis"] not in {"table_value", "text_value", "chart_value"}:
        raise ValueError("Unsupported value basis")
    if row["state"] not in {"retained_historical", "refreshed", "added"}:
        raise ValueError("Unsupported record state")
    if row["maker_assessment"] not in VERDICTS:
        raise ValueError("Unknown maker assessment")
    if row["model_reproduction"] != "not_attempted":
        raise ValueError("This bundle contains no provider-model reproduction evidence")
    horizon = year(row["horizon"], "horizon")
    if row["shape"] == "upper_bound":
        if row["low"] is not None or row["point"] is not None:
            raise ValueError("An upper-bound record carries only its stated upper value")
        lo = hi = number(row["high"], "high")
    elif row["shape"] == "lower_bound":
        if row["high"] is not None or row["point"] is not None:
            raise ValueError("A lower-bound record carries only its stated lower value")
        lo = hi = number(row["low"], "low")
    else:
        lo, hi = number(row["low"], "low"), number(row["high"], "high")
    if lo > hi or (row["unit"] != "percent_growth" and lo < 0):
        raise ValueError("Invalid forecast interval")
    if row["point"] is not None:
        point = number(row["point"], "point")
        if not lo <= point <= hi:
            raise ValueError("Point lies outside its stated interval")
    if row["shape"] == "point" and not (lo == hi == row["point"]):
        raise ValueError("Point record requires equal low/high/point values")
    if row["unit"] == "percent_growth":
        if lo <= -100 or row["base_year"] is None or year(row["base_year"], "base_year") >= horizon:
            raise ValueError("Growth records require a base year before the horizon and growth above minus 100")
    elif row["base_year"] is not None:
        raise ValueError("An absolute quantity cannot carry a growth base year")


def load(root=ROOT):
    data = read_json(root, "OBSERVATIONS.json")
    catalogue = read_json(root, "SOURCE_CATALOGUE.json")
    review = read_json(root, "SUPPORT_REVIEW.json")
    if not all(isinstance(x, dict) for x in (data, catalogue, review)):
        raise ValueError("Input roots must be objects")
    records, sources, receipts = data.get("records"), catalogue.get("sources"), review.get("reviews")
    if not isinstance(records, list) or not records or not isinstance(sources, list) or not sources or not isinstance(receipts, list):
        raise ValueError("Non-empty records and sources and a review list are required")
    source_map = {}
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("id"), str):
            raise ValueError("Malformed source")
        if source["id"] in source_map:
            raise ValueError("Duplicate source ID")
        if not isinstance(source.get("url"), str) or not source["url"].startswith("https://"):
            raise ValueError("A source requires its HTTPS reference")
        source_map[source["id"]] = source
    by_id = {}
    for row in records:
        check_row(row, source_map)
        if row["id"] in by_id:
            raise ValueError("Duplicate observation ID: " + row["id"])
        by_id[row["id"]] = row
    for row in records:
        later = row["superseded_by"]
        if later:
            new = by_id.get(later)
            if new is None or later == row["id"]:
                raise ValueError("superseded_by must name another observation: " + row["id"])
            same = ("forecaster", "comparison_family", "geography", "horizon", "unit", "metric", "base_year")
            if not row["comparison_family"] or any(row[k] != new[k] for k in same):
                raise ValueError("superseded_by must name a later observation of the same series and quantity: " + row["id"])
    for row in records:
        seen, rid = set(), row["id"]
        while rid:
            if rid in seen:
                raise ValueError("superseded_by links form a cycle: " + row["id"])
            seen.add(rid)
            rid = by_id[rid]["superseded_by"]
    for item in receipts:
        if not isinstance(item, dict) or item.get("verdict") not in VERDICTS:
            raise ValueError("Malformed support review receipt")
        for key in ("observation_id", "row_sha256", "catalogue_sha256", "reviewer", "review_record_sha256", "locator"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError("Support review receipt lacks: " + key)
    candidate_ids = None
    for pair in data.get("comparisons", []):
        if not isinstance(pair, dict) or not all(isinstance(pair.get(k), str) and pair[k] for k in ("id", "interpretation")):
            raise ValueError("Comparison requires id and interpretation")
        for key in ("old", "new"):
            if pair.get(key) in by_id:
                continue
            if candidate_ids is None:
                candidate_ids = declared_candidate_ids(root)
            if pair.get(key) not in candidate_ids:
                raise ValueError("Comparison references an unknown observation")
    return data, source_map, receipts


def declared_candidate_ids(root):
    """Candidate IDs that a declared comparison may name; load_candidates validates the candidate file in full."""
    doc = read_json(root, CANDIDATES)
    records = doc.get("records") if isinstance(doc, dict) else None
    if not isinstance(records, list):
        raise ValueError("Candidate file needs records")
    return {r["id"] for r in records if isinstance(r, dict) and isinstance(r.get("id"), str)}


def text_fields(item, keys, what):
    for key in keys:
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise ValueError(what + " lacks: " + key)


def source_records(items, prefix, what):
    """Source records for the candidate and prior-work files: unique IDs, an HTTPS reference, an access date and the original's SHA-256."""
    found = {}
    if not isinstance(items, list) or not items:
        raise ValueError(what + " needs a non-empty source list")
    for source in items:
        if not isinstance(source, dict) or not re.fullmatch(prefix + r"\d{2}", str(source.get("id"))) or source["id"] in found:
            raise ValueError("Malformed or duplicate source in " + what)
        if (not str(source.get("url", "")).startswith("https://") or not HEX64.fullmatch(str(source.get("original_sha256", "")))
                or not ISO_DATE.fullmatch(str(source.get("access_date", "")))):
            raise ValueError("A source requires an HTTPS reference, an access date and the SHA-256 of its retained original: " + source["id"])
        found[source["id"]] = source
    return found


def load_candidates(root, data):
    """Candidate observations: same row schema as the ledger, their own sources, and a route into arithmetic only through a current
    supported receipt in the candidate receipt file, whose per-candidate status is attached under CANDIDATE_REVIEW_KEY."""
    doc = read_json(root, CANDIDATES)
    if not isinstance(doc, dict) or doc.get("status") != CANDIDATE_STATUS:
        raise ValueError("Candidate file must declare that candidates enter no arithmetic, span or comparison without a current supported receipt")
    if CANDIDATE_REVIEW_KEY in doc:
        raise ValueError("Candidate file cannot carry its own support review: " + CANDIDATE_REVIEW_KEY)
    for key in ("selection_rule", "search_record", "sources", "records", "horizon_basis", "auxiliary_sources", "known_unregistered"):
        if key not in doc:
            raise ValueError("Candidate file lacks: " + key)
    sources = source_records(doc["sources"], "N", "the candidate file")
    if not isinstance(doc["records"], list) or not doc["records"]:
        raise ValueError("Candidate file needs records")
    ledger_ids, seen = {r["id"] for r in data["records"]}, set()
    for row in doc["records"]:
        check_row(row, sources)
        if not re.fullmatch(r"C\d{2}", row["id"]) or row["id"] in seen or row["id"] in ledger_ids:
            raise ValueError("Candidate IDs must be unique, use the C prefix and differ from ledger IDs: " + str(row["id"]))
        if row["superseded_by"] or row["comparison_family"] or row["state"] != "added":
            raise ValueError("A candidate carries no supersession or comparison family until it is admitted: " + row["id"])
        seen.add(row["id"])
    for cid, ids in doc["auxiliary_sources"].items():
        if cid not in seen or not isinstance(ids, list) or not set(ids) <= set(sources):
            raise ValueError("Auxiliary sources must name a candidate and its listed sources: " + str(cid))
    for cid, basis in doc["horizon_basis"].items():
        if cid not in seen or not isinstance(basis, str) or not basis.strip():
            raise ValueError("A horizon basis must name a candidate and state the basis: " + str(cid))
    known = set()
    for item in doc["known_unregistered"]:
        if not isinstance(item, dict) or not re.fullmatch(r"NK\d{2}", str(item.get("id"))) or item["id"] in known or item.get("source_id") not in sources:
            raise ValueError("Malformed candidate known value: " + str(item.get("id") if isinstance(item, dict) else item))
        text_fields(item, ("forecaster", "locator", "description"), "Candidate known value " + item["id"])
        known.add(item["id"])
    doc[CANDIDATE_REVIEW_KEY] = candidate_review_status(doc, load_candidate_review(root, doc))
    return doc


def candidate_source_list_digest(candidates):
    """Digest of every candidate source record, computed as catalogue_digest computes the ledger's, so that a change to any candidate
    source, including auxiliary evidence, makes every candidate receipt stale."""
    return catalogue_digest({s["id"]: s for s in candidates["sources"]})


def load_candidate_review(root, candidates):
    """Candidate receipts: each binds one listed candidate; a malformed file or receipt, or a receipt naming an unknown candidate, fails."""
    doc = read_json(root, CANDIDATE_REVIEW)
    if not isinstance(doc, dict) or not isinstance(doc.get("reviews"), list) or not isinstance(doc.get("historical_reviews"), list):
        raise ValueError("Malformed candidate support review file: reviews and historical_reviews lists are required")
    known = {r["id"] for r in candidates["records"]}
    for item in doc["reviews"]:
        if not isinstance(item, dict) or set(item) != set(CANDIDATE_RECEIPT_FIELDS) or item["verdict"] not in VERDICTS:
            raise ValueError("Malformed candidate support review receipt")
        if not all(isinstance(item[k], str) and HEX64.fullmatch(item[k]) for k in ("row_sha256", "candidate_source_list_sha256", "review_record_sha256")):
            raise ValueError("Malformed candidate support review receipt: digests must be SHA-256 hex")
        text_fields(item, ("candidate_id", "reviewer", "locator", "reason"), "Candidate support review receipt")
        for key in ("components_short_of_supported", "components_unassessed_as_maker_conduct"):
            if not isinstance(item[key], list) or not all(isinstance(c, str) and c.strip() for c in item[key]):
                raise ValueError("Malformed candidate support review receipt: " + key)
        if item["verdict"] == "supported" and item["components_short_of_supported"]:
            raise ValueError("A supported candidate receipt cannot list components short of support: " + item["candidate_id"])
        if item["candidate_id"] not in known:
            raise ValueError("Candidate support review receipt names an unknown candidate: " + item["candidate_id"])
    return doc["reviews"]


def candidate_review_status(candidates, receipts):
    """Each candidate's support status and the reason; a receipt counts only if it binds the current row and the candidate source list."""
    status, evidence = {}, candidate_source_list_digest(candidates)
    for row in candidates["records"]:
        mine = [r for r in receipts if r["candidate_id"] == row["id"]]
        current = [r for r in mine if r["row_sha256"] == row_digest(row) and r["candidate_source_list_sha256"] == evidence]
        if len(current) > 1:
            raise ValueError("More than one current candidate receipt: " + row["id"])
        if current:
            status[row["id"]] = {"status": current[0]["verdict"], "reason": current[0]["reason"],
                                 "components_short_of_supported": current[0]["components_short_of_supported"]}
        elif mine:
            status[row["id"]] = {"status": "review stale", "reason": "no receipt binds the current candidate row and candidate source list",
                                 "components_short_of_supported": []}
        else:
            status[row["id"]] = {"status": "unreviewed", "reason": "no receipt in " + CANDIDATE_REVIEW, "components_short_of_supported": []}
    return status


def admitted_candidates(candidates):
    """Candidate rows whose current receipt is supported, in identifier order; None or no receipt admits nothing."""
    if candidates is None:
        return []
    review = candidates[CANDIDATE_REVIEW_KEY]
    return sorted((r for r in candidates["records"] if review[r["id"]]["status"] == "supported"), key=lambda r: r["id"])


def load_prior_work(root, data):
    """Earlier-work sources and the 4E comparison; every registered observation is allocated to one relation exactly once."""
    doc = read_json(root, PRIOR_WORK)
    if not isinstance(doc, dict):
        raise ValueError("Prior-work file must be an object")
    source_records(doc.get("sources"), "P", "the prior-work file")
    ledger = {r["id"]: r for r in data["records"]}
    rows, allocated = doc.get("four_e_comparison"), []
    if not isinstance(rows, list) or not rows:
        raise ValueError("Prior-work file needs a 4E comparison")
    for row in rows:
        text_fields(row, ("publisher", "four_e_entries", "four_e_record", "four_e_scenario", "four_e_base_year", "four_e_crypto", "four_e_quality",
                          "four_e_locator", "difference"), "A 4E comparison row")
        if not row["four_e_locator"].startswith("P01"):
            raise ValueError("A 4E comparison row must locate its evidence in P01: " + row["publisher"])
        listed = []
        for key in RELATIONS:
            if not isinstance(row.get(key), list) or not all(isinstance(i, str) for i in row[key]):
                raise ValueError("A 4E comparison row needs the list " + key + ": " + row["publisher"])
            listed += row[key]
        if not isinstance(row.get("ledger_shown"), list) or not row["ledger_shown"] or not set(row["ledger_shown"]) <= set(listed):
            raise ValueError("Ledger observations shown must be among the row's allocated observations: " + row["publisher"])
        allocated += listed
        for chk in row.get("checks", []):
            value = ledger[chk["observation"]][chk["field"]] if chk.get("observation") in ledger else None
            agrees = (value == chk.get("four_e_value") if chk.get("relation") == "equal" else
                      value is not None and (value < chk["four_e_low"] or value > chk["four_e_high"]) if chk.get("relation") == "outside" else False)
            if not agrees:
                raise ValueError("PRIOR_WORK.json check fails: " + row["publisher"] + " " + str(chk.get("observation")))
    if sorted(allocated) != sorted(ledger) or len(allocated) != len(set(allocated)):
        raise ValueError("The 4E comparison must allocate every registered observation exactly once")
    parameters = doc.get("four_e_parameters")
    if not isinstance(parameters, list) or not parameters:
        raise ValueError("Prior-work file needs the 4E parameter mapping")
    for item in parameters:
        text_fields(item, ("parameter", "four_e_values", "four_e_locator", "ledger", "relation"), "A 4E parameter row")
    quality = doc.get("four_e_quality_filter")
    if not isinstance(quality, dict):
        raise ValueError("Prior-work file needs the 4E quality-filter record")
    for tier in ("low", "higher"):
        part = quality.get(tier)
        if not isinstance(part, dict) or not all(isinstance(part.get(k), int) and not isinstance(part.get(k), bool) and part[k] > 0
                                                 for k in ("publications", "scenarios_and_cases", "minimum", "maximum")) or part["minimum"] >= part["maximum"]:
            raise ValueError("Malformed 4E quality-filter tier: " + tier)
    labels, summary = quality.get("figure_es1_estimates_by_higher_class"), quality.get("executive_summary_scenarios_and_cases_higher")
    if (not isinstance(labels, list) or not labels or not all(isinstance(x, int) and not isinstance(x, bool) and x > 0 for x in labels)
            or not isinstance(summary, int) or isinstance(summary, bool) or summary <= 0):
        raise ValueError("Malformed 4E quality-filter counts")
    for key in ("year", "geography", "unit"):
        if key not in quality:
            raise ValueError("4E quality-filter record lacks: " + key)
    return doc


def review_status(data, sources, receipts):
    """Return each observation's support status; a receipt counts only if it binds the current row and the complete source catalogue."""
    status, evidence = {}, catalogue_digest(sources)
    for row in data["records"]:
        current = [r for r in receipts if r["observation_id"] == row["id"] and r["row_sha256"] == row_digest(row)
                   and r["catalogue_sha256"] == evidence]
        if len(current) > 1:
            raise ValueError("More than one current review receipt: " + row["id"])
        if current:
            status[row["id"]] = current[0]["verdict"]
        elif any(r["observation_id"] == row["id"] for r in receipts):
            status[row["id"]] = "review stale"
        else:
            status[row["id"]] = "unreviewed"
    return status


def compare(old, new, status):
    reasons = []
    for key in ("geography", "horizon", "unit", "metric", "base_year", "crypto_scope", "coverage", "value_basis"):
        if old.get(key) != new.get(key):
            reasons.append("different " + key)
    if "upper_bound" in (old["shape"], new["shape"]):
        reasons.append("an upper-end statement is not a point estimate")
    if "lower_bound" in (old["shape"], new["shape"]):
        reasons.append("an open lower bound is not a point estimate")
    for row in (old, new):
        if status.get(row["id"]) != "supported":
            reasons.append(f"{row['id']} support review: {status.get(row['id'], 'unreviewed')}")
    same_series = (old["forecaster"] == new["forecaster"] and old["comparison_family"] and old["comparison_family"] == new["comparison_family"])
    if old["scenario"] != new["scenario"] and "unstated" not in (old["scenario"], new["scenario"]):
        reasons.append("different scenario")
    if not same_series:
        if "unstated" in (old["scenario"], new["scenario"]):
            reasons.append("scenario is unresolved")
        for key in ("crypto_scope", "coverage"):
            if old[key] in UNRESOLVED or new[key] in UNRESOLVED:
                reasons.append("scope is unresolved: " + key)
    if reasons:
        return {"status": "not_comparable", "old": old["id"], "new": new["id"], "reasons": reasons}
    if old["shape"] != "point" or new["shape"] != "point":
        return {"status": "no_direction_assigned", "old": old["id"], "new": new["id"], "reason": "A point and a scenario range do not define a common central estimate"}
    a, b = old["point"], new["point"]
    result = {"status": "conditional_arithmetic", "old": old["id"], "new": new["id"], "n_observations": 2,
              "qualifications": [old["qualification"], new["qualification"]], "support_review": [status[old["id"]], status[new["id"]]]}
    if old["unit"] == "percent_growth":
        a, b = 1 + a / 100, 1 + b / 100
        result["basis"] = "Implied forecast-level index; assumes an unchanged physical baseline estimate"
        result["growth_rate_difference_percentage_points"] = new["point"] - old["point"]
    else:
        result["basis"] = "Difference between stated forecast points; not realised growth or forecast accuracy"
    result.update(old_value=a, new_value=b, difference=b-a, numerator=b-a, denominator=a)
    result["relative_change_percent"] = None if a == 0 else (b-a) / a * 100
    return result


def stated_bounds(members):
    """Stated-bound span computed as the recorded-value spans compute it: open lower bounds are listed, never used as extrema."""
    bounded = [m for m in members if m["shape"] != "lower_bound"]
    low = min((m["low"] for m in bounded if m["low"] is not None), default=None)
    high = max((m["high"] for m in bounded), default=None)
    return {"observation_ids": [m["id"] for m in members], "n_observations": len(members), "n_publishers": len({m["forecaster"] for m in members}),
            "minimum_stated_bound": low, "maximum_stated_bound": high, "span_width": None if low is None or high is None else high - low,
            "open_lower_bounds": [{"id": m["id"], "lower_bound": m["low"]} for m in members if m["shape"] == "lower_bound"]}


def like_for_like(rows, status, spans):
    """Set each like-for-like group beside wider sets for the same metric, unit and target year, all restricted to supported observations."""
    by_id = {r["id"]: r for r in rows}
    forecasts = [r for r in rows if r["metric"] != "historical_model_estimate"]
    supported = [r for r in forecasts if status[r["id"]] == "supported"]
    comparison = []
    for span in spans:
        members = [by_id[i] for i in span["observation_ids"]]
        key = (members[0]["metric"], members[0]["unit"], members[0]["horizon"])
        same = [r for r in supported if (r["metric"], r["unit"], r["horizon"]) == key]
        geography = [r for r in same if r["geography"] == members[0]["geography"]]
        inside, near = set(span["observation_ids"]), {r["id"] for r in geography}
        comparison.append({
            "group": span["group"],
            "like_for_like": dict(stated_bounds(members), crypto_scopes=sorted({m["crypto_scope"] for m in members})),
            "same_geography_any_vintage_or_base_year": dict(stated_bounds(geography), added_observations=[r["id"] for r in geography if r["id"] not in inside]),
            "same_metric_unit_and_year": dict(stated_bounds(same), added_observations=[r["id"] for r in same if r["id"] not in near],
                                              geographies=sorted({r["geography"] for r in same}),
                                              base_years=sorted({r["base_year"] for r in same}, key=lambda y: (y is not None, y or 0)),
                                              superseded=[r["id"] for r in same if r["superseded_by"]],
                                              crypto_scopes=sorted({r["crypto_scope"] for r in same})),
            "excluded_short_of_supported": sorted(r["id"] for r in forecasts if (r["metric"], r["unit"], r["horizon"]) == key and status[r["id"]] != "supported")})
    multi = [c for c in comparison if c["like_for_like"]["n_observations"] > 1]
    return {"rule": ("Spans of stated bounds among observations with a current supported receipt. A like-for-like group shares geography, metric, unit, "
                     "target year and base year and holds one vintage per publisher series; the same-geography set drops the base-year and vintage "
                     "conditions; the same-metric set keeps only metric, unit and target year. Observations short of a supported receipt are excluded "
                     "from every set and listed. Open lower bounds are listed, not used as extrema. Not a probability interval, consensus estimate or "
                     "convergence test."),
            "groups": len(comparison), "groups_with_more_than_one_observation": len(multi),
            "groups_mixing_cryptocurrency_scopes": [c["group"] for c in multi if len(c["like_for_like"]["crypto_scopes"]) > 1],
            "comparison": comparison}


def results(data, sources, receipts, candidates=None):
    """Recalculate the declared outputs. A candidate enters spans, the like-for-like sets and declared comparisons on the ledger's terms
    only with a current supported receipt; without the candidate records (candidates=None) no candidate is admitted."""
    ledger = data["records"]
    status = review_status(data, sources, receipts)
    admitted = admitted_candidates(candidates)
    rows = ledger + admitted
    by_id = {r["id"]: r for r in ledger}
    statuses = dict(status)
    if candidates is not None:
        by_id.update({r["id"]: r for r in candidates["records"]})
        statuses.update({i: s["status"] for i, s in candidates[CANDIDATE_REVIEW_KEY].items()})
    for pair in data["comparisons"]:
        for key in ("old", "new"):
            if pair[key] not in by_id:
                raise ValueError("A declared comparison names a candidate; the candidate records are required: " + pair[key])
    groups, superseded = {}, []
    for row in rows:
        if statuses[row["id"]] != "supported" or row["metric"] == "historical_model_estimate":
            continue
        if row["superseded_by"]:
            superseded.append({"id": row["id"], "superseded_by": row["superseded_by"], "forecaster": row["forecaster"]})
            continue
        key = " / ".join(str(row[k]) for k in ("geography", "metric", "unit", "horizon", "base_year"))
        groups.setdefault(key, []).append(row)
    spans = []
    for key, members in sorted(groups.items()):
        bounded = [m for m in members if m["shape"] != "lower_bound"]
        spans.append({"group": key, "observation_ids": [m["id"] for m in members], "n_observations": len(members), "n_publishers": len({m["forecaster"] for m in members}),
                      "minimum_stated_bound": min((m["low"] for m in bounded if m["low"] is not None), default=None), "maximum_stated_bound": max((m["high"] for m in bounded), default=None),
                      "open_lower_bounds": [{"id": m["id"], "lower_bound": m["low"]} for m in members if m["shape"] == "lower_bound"],
                      "interpretation": ("Recorded-value span only; the minimum and maximum stated bounds exclude open lower bounds, which are listed in open_lower_bounds; "
                                         "observation and publisher counts include all group members; superseded same-publisher vintages are listed separately; "
                                         "boundaries, scenarios and shapes are not normalised"),
                      "shapes": sorted({m["shape"] for m in members}), "crypto_scopes": sorted({m["crypto_scope"] for m in members}),
                      "publication_vintages": sorted({m["source_publication"] for m in members})})
    counts = {s: sum(v == s for v in status.values()) for s in sorted(set(status.values()))}
    return {"version": data["version"], "as_of": data["as_of"], "observation_count": len(ledger),
            "source_count_used": len({r["source_id"] for r in ledger}), "provider_models_reconstructed": 0,
            "maker_assessment": {s: sum(r["maker_assessment"] == s for r in ledger) for s in sorted({r["maker_assessment"] for r in ledger})},
            "support_review": {"counts": counts, "by_observation": status, "receipts": len(receipts),
                               "rule": "Arithmetic and spans use only observations whose current row and source digests carry a supported receipt"},
            "candidate_admission": {"rule": ("A candidate in CANDIDATE_OBSERVATIONS.json enters spans, the like-for-like comparison and declared "
                                             "comparisons, as a registered observation does, only when CANDIDATE_SUPPORT_REVIEW.json holds a supported "
                                             "receipt bound to its current row and to the candidate source list; admitted lists the candidates that do"),
                                    "admitted": [r["id"] for r in admitted]},
            "comparisons": [dict(id=p["id"], interpretation=p["interpretation"], **compare(by_id[p["old"]], by_id[p["new"]], statuses)) for p in data["comparisons"]],
            "recorded_value_spans": spans, "like_for_like_comparison": like_for_like(rows, statuses, spans), "superseded_observations": superseded,
            "unresolved": data["unresolved"], "known_unregistered": data["known_unregistered"], "scope_limits": data["scope_limits"]}


def value_text(row):
    if row["shape"] == "upper_bound":
        return f"up to {row['high']:g}"
    if row["shape"] == "lower_bound":
        return f"lower bound {row['low']:g}"
    if row["shape"] == "scenario_range":
        tail = "" if row["point"] is None else f"; reference {row['point']:g}"
        return f"{row['low']:g} to {row['high']:g}{tail}"
    return f"{row['point']:g}"


def paper_statements(data):
    """Sentences PAPER.md must carry verbatim, generated from the ledger so that a stated threshold cannot drift from its record."""
    statements = {}
    for row in data["records"]:
        if row["shape"] != "lower_bound":
            continue
        words = [w for phrase, w in LOWER_BOUND_WORDS.items() if phrase in row["qualification"]]
        if len(words) != 1 or row["metric"] not in METRIC_NOUNS:
            raise ValueError("A lower bound needs one stated inclusivity and a named metric: " + row["id"])
        statements[row["id"]] = (f"{row['forecaster']} states its {row['horizon']} {METRIC_NOUNS[row['metric']]} only as {words[0]} {row['low']:,g} {row['unit']}; "
                                 f"the ledger records that as an open lower bound ({row['id']}), which enters no comparison and is listed separately in value spans "
                                 "rather than treated as a maximum.")
    return statements


def fmt(value):
    """A number as the paper prints it: thousands separated by commas, no exponent."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value:,}" if isinstance(value, int) else f"{value:,.10g}"


def listing(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def stated_value(row):
    """A registered or candidate value in the paper's words; an open lower bound uses the inclusivity its qualification states."""
    if row["shape"] == "upper_bound":
        return f"up to {fmt(row['high'])}"
    if row["shape"] == "lower_bound":
        words = [w for phrase, w in LOWER_BOUND_WORDS.items() if phrase in row["qualification"]]
        if len(words) != 1:
            raise ValueError("A lower bound needs one stated inclusivity and a named metric: " + row["id"])
        return f"{words[0]} {fmt(row['low'])}"
    if row["shape"] == "scenario_range":
        tail = "" if row["point"] is None else f" (reference {fmt(row['point'])})"
        return f"{fmt(row['low'])} to {fmt(row['high'])}{tail}"
    return fmt(row["point"])


def ledger_text(row):
    base = "" if row["base_year"] is None else f" versus {row['base_year']}"
    scenario = "scenario not stated" if row["scenario"] == "unstated" else row["scenario"]
    return (f"{row['id']}: {stated_value(row)} {UNIT_LABELS[row['unit']]}{base}, {row['geography']}, {row['horizon']}, {scenario}; "
            f"{CRYPTO_LABELS[row['crypto_scope']]}")


def bounds_text(span):
    low, high = span["minimum_stated_bound"], span["maximum_stated_bound"]
    if low is None and high is None:
        text = "no finite bound"
    elif low is None:
        text = f"up to {fmt(high)}"
    else:
        text = fmt(low) if low == high else f"{fmt(low)} to {fmt(high)}"
    opens = "; ".join(f"open lower bound {fmt(o['lower_bound'])} ({o['id']})" for o in span["open_lower_bounds"])
    return f"{span['n_observations']} ({span['n_publishers']}); {text}" + (f"; {opens}" if opens else "")


def group_label(row):
    base = "" if row["base_year"] is None else f"; base year {row['base_year']}"
    return f"{row['geography']}; {METRIC_NOUNS[row['metric']]}; {UNIT_LABELS[row['unit']]}; {row['horizon']}{base}"


def group_phrase(row):
    base = "" if row["base_year"] is None else f" on a {row['base_year']} base"
    return f"the {row['geography']} {METRIC_NOUNS[row['metric']]} group for {row['horizon']}{base}"


def like_for_like_blocks(result, by_id):
    comparison = result["like_for_like_comparison"]
    lines = ["| Like-for-like group | Like-for-like: N (publishers); stated bounds | Same geography, any vintage or base year | "
             "Same metric, unit and year, any geography | Excluded, short of a supported receipt |", "| --- | --- | --- | --- | --- |"]
    for item in comparison["comparison"]:
        first = by_id[item["like_for_like"]["observation_ids"][0]]
        cells = [group_label(first), bounds_text(item["like_for_like"])]
        for key in ("same_geography_any_vintage_or_base_year", "same_metric_unit_and_year"):
            added = item[key]["added_observations"]
            cells.append(bounds_text(item[key]) + (f"; adds {', '.join(added)}" if added else ""))
        cells.append(", ".join(item["excluded_short_of_supported"]) or "none")
        lines.append("| " + " | ".join(cells) + " |")
    multi = [c for c in comparison["comparison"] if c["like_for_like"]["n_observations"] > 1]
    summary = [f"Only {len(multi)} of the {comparison['groups']} like-for-like groups hold more than one observation."]
    for item in multi:
        first, own = by_id[item["like_for_like"]["observation_ids"][0]], item["like_for_like"]
        sentence = f"{group_phrase(first)[0].upper()}{group_phrase(first)[1:]} holds {own['n_observations']} observations from {own['n_publishers']} publishers"
        if len(own["crypto_scopes"]) > 1:
            sentence += (" and is not fully like for like, because it mixes cryptocurrency scopes ("
                         + listing([CRYPTO_LABELS[s].replace("cryptocurrency ", "") for s in own["crypto_scopes"]]) + ")")
        summary.append(sentence + ".")

    def bounds(span):
        return span["minimum_stated_bound"], span["maximum_stated_bound"]

    narrower = [c for c in multi if c["like_for_like"]["span_width"] is not None and c["same_metric_unit_and_year"]["span_width"] is not None
                and c["like_for_like"]["span_width"] < c["same_metric_unit_and_year"]["span_width"]]
    geographic = [c for c in narrower if bounds(c["like_for_like"]) == bounds(c["same_geography_any_vintage_or_base_year"])]
    if multi and len(narrower) == len(multi) == len(geographic):
        reading = (f"In each of the {len(multi)} groups that hold more than one observation, the like-for-like span is narrower than the span across all "
                   "geographies for the same metric and year and equal to the span within the same geography, so the narrowing comes from separating "
                   "geographies; adding other editions or base years within a geography leaves these spans unchanged.")
    else:
        parts = []
        for c in multi:
            first = by_id[c["like_for_like"]["observation_ids"][0]]
            state = ("narrower than across all geographies" if c in narrower else "not narrower than across all geographies")
            if c in narrower:
                state += ", and equal to the same-geography span" if c in geographic else ", and narrower than the same-geography span"
            parts.append(f"for {group_phrase(first)} the like-for-like span is {state}")
        reading = ("Among the groups that hold more than one observation, " + "; ".join(parts) + ".") if parts else "No group holds more than one observation."
    return {"like-for-like table": "\n".join(lines), "like-for-like summary": " ".join(summary), "like-for-like reading": reading}


def four_e_blocks(prior, data):
    by_id = {r["id"]: r for r in data["records"]}
    rows, q = prior["four_e_comparison"], prior["four_e_quality_filter"]
    same = [i for r in rows for i in r["same_publication"]]
    earlier = [i for r in rows for i in r["earlier_edition"]]
    other = [i for r in rows for i in r["publisher_only"]]

    def verb(ids):
        return "comes" if len(ids) == 1 else "come"

    overlap = (f"Of the ledger's {len(by_id)} registered observations, {len(same)} ({listing(same)}) {verb(same)} from a publication that the 4E review "
               f"catalogues, {len(earlier)} ({listing(earlier)}) {verb(earlier)} from later editions of report series whose earlier editions it catalogues, "
               f"and {len(other)} {verb(other)} from publications it does not catalogue, although it catalogues other publications from all {len(rows)} "
               "registered publishers.")
    labels = {"same_publication": "same publication", "earlier_edition": "earlier edition of the same series",
              "publisher_only": "other publications of the publisher only"}
    table = ["| Publisher | 4E entries and relation to the ledger | What the 4E review records | What the ledger records |", "| --- | --- | --- | --- |"]
    for row in rows:
        relation = "; ".join(f"{labels[k]}: {', '.join(row[k])}" for k in RELATIONS if row[k])
        four_e = (f"{row['four_e_record']}. Scenario: {row['four_e_scenario']}. Base year: {row['four_e_base_year']}. "
                  f"Cryptocurrency: {row['four_e_crypto']}. Quality: {row['four_e_quality']}. ({row['four_e_locator']})")
        table.append("| " + " | ".join([row["publisher"], f"{row['four_e_entries']}; {relation}", four_e,
                                          "; ".join(ledger_text(by_id[i]) for i in row["ledger_shown"])]) + " |")
    differences = "\n".join(f"- {row['publisher']}: {row['difference']}" for row in rows)
    parameters = ["| 4E catalogue parameter | 4E values | Ledger fields | Relation |", "| --- | --- | --- | --- |"]
    parameters += [f"| {p['parameter']} | {p['four_e_values']} ({p['four_e_locator']}) | {p['ledger']} | {p['relation']} |" for p in prior["four_e_parameters"]]
    low, high = q["low"], q["higher"]
    quality = (f"The 4E review reports that studies it rated {low['rating']} ({low['publications']} publications) gave {q['geography'].lower()} estimates "
               f"for {q['year']} of {fmt(low['minimum'])} to {fmt(low['maximum'])} {q['unit']} across {low['scenarios_and_cases']} scenarios and cases, "
               f"and that studies it rated {high['rating']} ({high['publications']} publications) gave {fmt(high['minimum'])} to "
               f"{fmt(high['maximum'])} {q['unit']} across {high['scenarios_and_cases']} scenarios and cases. Its executive summary gives "
               f"{q['executive_summary_scenarios_and_cases_higher']} for the second count, and the per-class labels of its Figure ES.1 sum to "
               f"{sum(q['figure_es1_estimates_by_higher_class'])}.")
    references = "\n".join(f"- {s['id']}. {s['citation']} {s['url']}" for s in prior["sources"])
    return {"4E overlap": overlap, "4E comparison table": "\n".join(table), "4E differences": differences,
            "4E parameter table": "\n".join(parameters), "4E quality filter": quality, "earlier-work references": references}


def candidate_blocks(candidates):
    sources = {s["id"]: s for s in candidates["sources"]}
    lines = ["| ID | Publisher, publication date | Stated figure | Geography and target | Quantity, scenario and boundary | Source |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in candidates["records"]:
        target = candidates["horizon_basis"].get(row["id"], str(row["horizon"]))
        scenario = "scenario not stated" if row["scenario"] == "unstated" else row["scenario"]
        lines.append("| " + " | ".join([row["id"], f"{row['forecaster']}, {row['source_publication']}", f"{stated_value(row)} {UNIT_LABELS[row['unit']]}",
                                          f"{row['geography']}, {target}", f"{METRIC_NOUNS[row['metric']]}; {scenario}; {boundary_text(row)}",
                                          f"[{row['source_id']}]({sources[row['source_id']]['url']})"]) + " |")
    return {"candidate table": "\n".join(lines), "candidate status": candidate_status_text(candidates)}


def candidate_status_text(candidates):
    """Each candidate's receipt status in the paper's words: which candidates enter arithmetic and why the others do not."""
    review, groups = candidates[CANDIDATE_REVIEW_KEY], {}
    for row in candidates["records"]:
        groups.setdefault(review[row["id"]]["status"], []).append(row["id"])

    def noun(ids):
        return ("Candidate " if len(ids) == 1 else "Candidates ") + listing(ids)

    def verb(ids, one, many):
        return one if len(ids) == 1 else many

    sentences = []
    if "supported" in groups:
        ids = groups["supported"]
        sentences.append(f"{noun(ids)} {verb(ids, 'has', 'have')} a current supported claim-support receipt and "
                         f"{verb(ids, 'enters', 'enter')} arithmetic, spans and declared comparisons as registered observations do.")
    if "unreviewed" in groups:
        ids = groups["unreviewed"]
        sentences.append(f"{noun(ids)} {verb(ids, 'awaits an independent claim-support receipt', 'await independent claim-support receipts')} "
                         f"and {verb(ids, 'enters', 'enter')} no arithmetic, span or comparison.")
    if "review stale" in groups:
        ids = groups["review stale"]
        sentences.append(f"{noun(ids)} {verb(ids, 'has', 'have')} only receipts that no longer bind {verb(ids, 'its', 'their')} current record and "
                         f"source list, and {verb(ids, 'enters', 'enter')} no arithmetic, span or comparison.")
    for verdict in VERDICTS[1:]:
        for cid in groups.get(verdict, []):
            short = review[cid]["components_short_of_supported"]
            detail = f", short of supported in {listing(short)}," if short else ""
            sentences.append(f"Candidate {cid} is rated {verdict}{detail} and enters no arithmetic, span or comparison.")
    return " ".join(sentences)


def paper_blocks(data, sources, receipts, candidates, prior):
    """Text blocks PAPER.md must carry verbatim, generated from the bundle's records so that no table or count can drift from them."""
    result = results(data, sources, receipts, candidates)
    by_id = {r["id"]: r for r in data["records"] + candidates["records"]}
    return {**like_for_like_blocks(result, by_id), **four_e_blocks(prior, data), **candidate_blocks(candidates)}


CRYPTO_LABELS = {"included": "cryptocurrency included", "excluded": "cryptocurrency excluded",
                 "excluded_inferred": "cryptocurrency excluded by inference", "unstated": "cryptocurrency not stated"}
COVERAGE_LABELS = {"total_facility_IT_plus_overhead": "total facility, IT plus overhead", "it_load": "IT load only",
                   "servers_storage_network_infrastructure": "servers, storage and network infrastructure",
                   "small_large_data_centres_and_crypto": "small and large data centres and cryptocurrency",
                   "data_centres_unspecified": "facility boundary not fully stated",
                   "new_data_centres_unspecified": "new data centres only, facility boundary not fully stated"}


def boundary_text(row):
    """Readable cryptocurrency and facility boundary for the Markdown view, failing closed on a value without a label."""
    if row["crypto_scope"] not in CRYPTO_LABELS or row["coverage"] not in COVERAGE_LABELS:
        raise ValueError("No readable boundary label for " + row["id"])
    return f"{CRYPTO_LABELS[row['crypto_scope']]}; {COVERAGE_LABELS[row['coverage']]}"


DISCLOSURE = "## AI assistance, conflicts and limitations\n\nThe research design, method, sourcing decisions and analytical judgements are the author's. OpenAI GPT-6 and Anthropic Opus 5.5 and Fable 5.1 assisted with data retrieval, calculation, literature search and drafting, so this text was artificially generated and was reviewed by the author before publication. The assisting models are not always neutral parties to the subject matter: OpenAI, whose GPT-6 model also reviewed the claim support for the candidate observations, Anthropic, and Google, whose Gemini 3.8 Flash High model reviewed the claim support for the registered observations and the hand-written sentences of the paper, all take part in the AI industry whose data-centre electricity demand these forecasts describe.\n\nGuarantee: every measured claim is traced to the primary document recorded in SOURCE_CATALOGUE.json, PRIOR_WORK.json or CANDIDATE_OBSERVATIONS.json as described in the paper's Verification note, and reproduce.py regenerates every table from OBSERVATIONS.json, SOURCE_CATALOGUE.json, SUPPORT_REVIEW.json, CANDIDATE_SUPPORT_REVIEW.json, PRIOR_WORK.json and CANDIDATE_OBSERVATIONS.json. Modelled or estimated inputs are identified as such in each observation's value basis and qualification in OBSERVATIONS.json, CANDIDATE_OBSERVATIONS.json and FORECASTS.md, rather than presented as measurements. A reader can check this without trusting either party.\n\nWhat the author cannot guarantee: a language model's output can be wrong in ways that survive review. In prose the error is locally plausible and consistent in tone with what surrounds it; in code it simply runs, and a wrong constant or a mis-set filter still returns a clean number. Several methods have been deployed to mitigate this, including explicit instructions, internal red-teaming and cross-lab blindspot checks, but the author does not claim the review is exhaustive. Corrections are logged against the DOI when surfaced.\n\nNo warranty is offered beyond the terms of the CC BY 4.0 licence. Independent analysis and open-science documentation only, not investment advice."


def outputs(data, sources, receipts, candidates=None):
    status = review_status(data, sources, receipts)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(FIELDS) + ["support_review"], lineterminator="\n")
    writer.writeheader()
    writer.writerows(dict(row, support_review=status[row["id"]]) for row in data["records"])
    text = ["# Forecast observations", "", "Purpose: inspect the frozen descriptive ledger.", "", "This work was produced through an AI-assisted workflow directed and reviewed by the author.", "",
            "Values describe publisher estimates. Coverage and vintage differ; this table supplies no consensus or accuracy ranking.", "",
            "| ID | Publisher and vintage | Quantity | Geography and target | Boundary | Source and qualification | Support review |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in data["records"]:
        base = "" if row["base_year"] is None else f" versus {row['base_year']}"
        source = sources[row["source_id"]]
        quantity = f"{value_text(row)} {row['unit']}{base}; {row['value_basis'].replace('_', ' ')}"
        if row["unit"] == "percent_growth":
            change = value_text(row)
            quantity += f"; normalised change {change} / baseline 100; N=1 forecast observation"
        later = f" Superseded by {row['superseded_by']}." if row["superseded_by"] else ""
        cells = [row["id"], f"{row['forecaster']}, {row['forecast_vintage']}", quantity,
                 f"{row['geography']}, {row['horizon']}; {row['metric']}; {row['scenario']}", boundary_text(row),
                 f"[{row['source_id']}]({source['url']}), {row['locator']}. {row['qualification']}{later}", status[row["id"]]]
        text.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    text += ["", "## Unresolved records", ""]
    text += [f"- {item['id']}, {item['forecaster']}: unverified. {item['reason']}" for item in data["unresolved"]]
    text += ["", "## Known unregistered source values", ""]
    text += [f"- {item['id']}, {item['forecaster']} ({item['source_id']}, {item['locator']}): {item['description']}" for item in data["known_unregistered"]]
    text += ["", "## Verification scope", "", "Support review status comes from digest-bound receipts in SUPPORT_REVIEW.json. The maker's assessment is recorded separately and never enables arithmetic. No provider model was reconstructed.", ""]
    text += [DISCLOSURE, ""]
    return {"FORECASTS.csv": stream.getvalue().encode(), "FORECASTS.md": "\n".join(text).encode(),
            "RESULTS.json": encoded(results(data, sources, receipts, candidates))}


def write_outputs(target, generated):
    target.mkdir()
    try:
        for name, payload in generated.items():
            with (target / name).open("xb") as handle:
                handle.write(payload)
    except BaseException:
        shutil.rmtree(target)
        raise


def check(root, data, sources, receipts):
    """Read-only package check. The declared file set is confirmed before the candidate files are read, because generated outputs
    depend on candidate receipts; generated bytes are compared before the manifest hashes."""
    manifest = read_json(root, "REPRODUCTION.json")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Manifest has no files")
    required = {"OBSERVATIONS.json", "SOURCE_CATALOGUE.json", "SUPPORT_REVIEW.json", "LEGACY.csv", "reproduce.py", "test_reproduce.py", "reuse_example.py", "README.md", "PAPER.md", "PAPER.pdf",
                CANDIDATES, CANDIDATE_REVIEW, PRIOR_WORK, *OUTPUTS}
    if set(files) != required:
        raise ValueError("Manifest must identify the exact declared package files")
    if {p.name for p in root.iterdir()} != required | {"REPRODUCTION.json"}:
        raise ValueError("Package contains unexpected or missing entries")
    candidates = load_candidates(root, data)
    for name, expected in outputs(data, sources, receipts, candidates).items():
        if read_file(root, name) != expected:
            raise ValueError("Generated output differs: " + name)
    for name, expected in files.items():
        if hashlib.sha256(read_file(root, name)).hexdigest() != expected:
            raise ValueError("Package hash differs: " + name)
    paper = read_file(root, "PAPER.md").decode("utf-8")
    for rid, sentence in paper_statements(data).items():
        if sentence not in paper:
            raise ValueError("PAPER.md disagrees with the ledger: " + rid)
    prior = load_prior_work(root, data)
    for name, block in paper_blocks(data, sources, receipts, candidates, prior).items():
        if block not in paper:
            raise ValueError("PAPER.md disagrees with the generated " + name)
    return {"status": "pass", "checked": ["input structure", "declared arithmetic", "support review digest binding", "generated output bytes", "listed package hashes", "generated paper statements for open lower bounds",
                                          "candidate and prior-work records", "candidate receipt digest binding", "generated paper tables and statements"],
            "not_assessed": ["source truth", "forecaster model reconstruction", "scientific validity", "reviewer identity", "PDF layout"],
            "authenticity_limit": "The supplied manifest detects disagreement; coordinated file-and-manifest edits are not authenticated"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--output-dir", type=Path)
    group.add_argument("--explain")
    group.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"))
    group.add_argument("--paper-blocks", action="store_true", help="print the text blocks PAPER.md must carry verbatim")
    args = parser.parse_args()
    try:
        data, sources, receipts = load()
        by_id = {r["id"]: r for r in data["records"]}
        if args.paper_blocks:
            result = paper_blocks(data, sources, receipts, load_candidates(ROOT, data), load_prior_work(ROOT, data))
        elif args.explain:
            candidates = load_candidates(ROOT, data)
            listed = {r["id"]: r for r in candidates["records"]}
            if args.explain in listed:
                row, review = listed[args.explain], candidates[CANDIDATE_REVIEW_KEY][args.explain]
                cand_sources = {s["id"]: s for s in candidates["sources"]}
                result = {"candidate": row, "source": cand_sources[row["source_id"]], "row_sha256": row_digest(row),
                          "candidate_source_list_sha256": candidate_source_list_digest(candidates), "status": CANDIDATE_STATUS,
                          "support_review": review["status"], "support_review_reason": review["reason"],
                          "components_short_of_supported": review["components_short_of_supported"]}
            elif args.explain not in by_id:
                raise ValueError("Unknown observation ID")
            else:
                row = by_id[args.explain]
                result = {"observation": row, "source": sources[row["source_id"]], "row_sha256": row_digest(row),
                          "support_review": review_status(data, sources, receipts)[row["id"]], "scope_limits": data["scope_limits"]}
        elif args.compare:
            candidates = load_candidates(ROOT, data)
            pool = dict(by_id, **{r["id"]: r for r in admitted_candidates(candidates)})
            for i in args.compare:
                if i not in pool:
                    review = candidates[CANDIDATE_REVIEW_KEY].get(i)
                    raise ValueError("Unknown comparison ID" if review is None else
                                     f"Unknown comparison ID: {i} is a candidate without a current supported receipt ({review['status']})")
            status = dict(review_status(data, sources, receipts), **{i: "supported" for i in pool if i not in by_id})
            result = compare(pool[args.compare[0]], pool[args.compare[1]], status)
        elif args.output_dir:
            target = args.output_dir.resolve()
            if target == ROOT or target.is_relative_to(ROOT) or args.output_dir.is_symlink() or target.exists():
                raise ValueError("Output directory must be new and outside the bundle")
            generated = outputs(data, sources, receipts, load_candidates(ROOT, data))
            write_outputs(target, generated)
            result = {"status": "generated", "files": list(generated), "package_integrity": "not_checked", "source_truth": "not_assessed"}
        else:
            result = check(ROOT, data, sources, receipts)
        sys.stdout.buffer.write(encoded(result))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        sys.stderr.buffer.write(encoded({"status": "failed", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
