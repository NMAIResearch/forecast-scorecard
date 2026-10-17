#!/usr/bin/env python3
"""
Rebuild index.html from the version 0.5 records in v0.5/.

build.py writes the page's tables, choices and lists from v0.5/OBSERVATIONS.json, v0.5/CANDIDATE_OBSERVATIONS.json,
v0.5/CANDIDATE_SUPPORT_REVIEW.json, v0.5/SOURCE_CATALOGUE.json and v0.5/RESULTS.json, escaping every value, so the page
renders without its script and no figure on it is typed by hand. A candidate's receipt status is the one v0.5/reproduce.py
computes: a receipt counts only while it binds the candidate's current row and the candidate source list. The page's script
only filters, sorts and opens rows.

    python3 build.py           rewrite the generated parts of index.html
    python3 build.py --check   exit 1 if index.html differs from what the records give

Pure standard library, no dependencies. The page of the v0.2 dataset is kept in v0.2/ with its own build.py.
"""
import html
import importlib.util
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "index.html"
RECORDS = HERE / "v0.5"
BLOCK = re.compile(r"<!--GENERATED:([a-z]+)-->.*?<!--/GENERATED:\1-->", re.DOTALL)
FIELDS = ("id", "forecaster", "forecast_vintage", "source_publication", "geography", "horizon", "unit", "metric",
          "scenario", "shape", "value_basis", "low", "high", "point", "base_year", "crypto_scope", "coverage", "state",
          "superseded_by", "source_id", "locator", "qualification")


def load(records, name):
    return json.loads((records / name).read_text(encoding="utf-8"))


def reproducer(records):
    """The records' own reproduce.py, loaded as a module, for its candidate receipt rule."""
    spec = importlib.util.spec_from_file_location("reproduce_v0_5", records / "reproduce.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def figures(records):
    """One row per registered observation and per candidate, in record order, with its receipt status and source."""
    observations = load(records, "OBSERVATIONS.json")
    candidates = load(records, "CANDIDATE_OBSERVATIONS.json")
    results = load(records, "RESULTS.json")
    catalogue = load(records, "SOURCE_CATALOGUE.json")
    receipts = load(records, "CANDIDATE_SUPPORT_REVIEW.json")["reviews"]
    sources = {s["id"]: (s["title"], s["url"]) for s in catalogue["sources"]}
    sources.update({s["id"]: (s["title"], s["url"]) for s in candidates["sources"]})
    registered = results["support_review"]["by_observation"]
    candidate_status = reproducer(records).candidate_review_status(candidates, receipts)
    basis = candidates.get("horizon_basis", {})
    rows = []
    for kind, records_of_kind in (("registered", observations["records"]), ("candidate", candidates["records"])):
        for record in records_of_kind:
            row = {field: record.get(field) for field in FIELDS}
            title, url = sources[record["source_id"]]
            status = registered[record["id"]] if kind == "registered" else candidate_status[record["id"]]["status"]
            row.update(kind=kind, source_title=title, source_url=url, receipt=status,
                       admitted=(status == "supported") if kind == "candidate" else None,
                       horizon_basis=basis.get(record["id"]) if kind == "candidate" else None)
            rows.append(row)
    return rows


def e(value):
    return "" if value is None else html.escape(str(value), quote=True)


def words(value):
    return e(None if value is None else str(value).replace("_", " "))


def number(value):
    """A number as the records write it; "none" where a bound is absent."""
    return "none" if value is None else json.dumps(value)


def link(url, text):
    if isinstance(url, str) and url.startswith("https://"):
        return f'<a href="{e(url)}" target="_blank" rel="noopener">{e(text)}</a>'
    return e(text)


def unit_text(row):
    return f"% growth relative to {e(row['base_year'])}" if row["unit"] == "percent_growth" else e(row["unit"])


def value_html(row):
    unit = f' <span class="unit">{unit_text(row)}</span>'
    if row["shape"] == "point":
        return f'<span class="val">{e(number(row["point"]))}</span>{unit}'
    if row["shape"] == "scenario_range":
        reference = (f' <span class="unit">(reference point {e(number(row["point"]))})</span>'
                     if row["point"] is not None else "")
        return f'<span class="val">{e(number(row["low"]))} to {e(number(row["high"]))}</span>{unit}{reference}'
    if row["shape"] == "upper_bound":
        return f'upper bound <span class="val">{e(number(row["high"]))}</span>{unit}'
    if row["shape"] == "lower_bound":
        return f'lower bound <span class="val">{e(number(row["low"]))}</span>{unit}'
    return words(row["shape"])


def flag(status):
    status = status or "no current receipt"
    kind = "ok" if status == "supported" else ("part" if status == "partly supported" else "none")
    return f'<span class="flag {kind}">{e(status)}</span>'


def details(items):
    return "<dl>" + "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in items if value) + "</dl>"


def figure_rows(rows):
    out = []
    for r in rows:
        key = e(r["id"])
        attributes = {"kind": r["kind"], "geo": r["geography"], "metric": r["metric"], "year": r["horizon"],
                      "receipt": r["receipt"] or "", "search": " ".join(str(r[k] or "") for k in ("forecaster", "scenario", "id")).lower(),
                      "sort-id": r["id"], "sort-forecaster": r["forecaster"], "sort-geography": r["geography"],
                      "sort-year": r["horizon"], "sort-metric": r["metric"], "sort-receipt": r["receipt"] or ""}
        data = " ".join(f'data-{k}="{e(v)}"' for k, v in attributes.items())
        superseded = f' <span class="note">superseded by {e(r["superseded_by"])}</span>' if r["superseded_by"] else ""
        year_note = f' <span class="note">{e(r["horizon_basis"])}</span>' if r["horizon_basis"] else ""
        admission = (f' <span class="note">{"admitted" if r["admitted"] else "not admitted"}</span>'
                     if r["kind"] == "candidate" else "")
        out.append(
            f'<tr class="row" id="row-{key}" data-id="{key}" data-more="more-{key}" {data}>'
            f'<td><button type="button" class="more-btn" aria-expanded="false" aria-controls="more-{key}" '
            f'aria-label="Details for {key}">{key}</button></td>'
            f'<td><span class="fc">{e(r["forecaster"])}</span>{superseded}</td>'
            f'<td>{e(r["geography"])}</td><td>{e(r["horizon"])}{year_note}</td>'
            f'<td class="num">{value_html(r)}</td><td>{words(r["metric"])}</td><td>{e(r["scenario"])}</td>'
            f'<td>{words(r["coverage"])}</td><td>{words(r["crypto_scope"])}</td><td>{flag(r["receipt"])}{admission}</td></tr>')
        out.append(
            f'<tr class="more" id="more-{key}" hidden><td colspan="10">' + details([
                ("Vintage", e(r["forecast_vintage"])), ("Source publication", e(r["source_publication"])),
                ("Source", link(r["source_url"], r["source_title"]) + f' <span class="id">{e(r["source_id"])}</span>'),
                ("Locator", e(r["locator"])), ("Qualification", e(r["qualification"])),
                ("Value basis", words(r["value_basis"])), ("Base year", e(r["base_year"])), ("State", words(r["state"])),
                ("Superseded by", e(r["superseded_by"]))]) + "</td></tr>")
    return "\n".join(out)


def set_text(s, unit):
    if not s:
        return ""
    parts = [f"{e(s['n_observations'])} observations from {e(s['n_publishers'])} publishers",
             f"stated bounds {e(number(s['minimum_stated_bound']))} to {e(number(s['maximum_stated_bound']))} {e(unit)} "
             f"(width {e(number(s['span_width']))})"]
    if s.get("observation_ids"):
        parts.append(e(", ".join(s["observation_ids"])))
    if s.get("open_lower_bounds"):
        parts.append("open lower bounds: " + ", ".join(
            f"{e(o['id'])} lower bound {e(number(o['lower_bound']))} {e(unit)}" for o in s["open_lower_bounds"]))
    if s.get("geographies"):
        parts.append(f"{e(len(s['geographies']))} geographies")
    return "; ".join(parts)


def group_rows(groups, rows):
    basis = {r["id"]: r["horizon_basis"] for r in rows if r["horizon_basis"]}
    out = []
    for i, g in enumerate(groups, 1):
        geography, metric, unit, year = (g["group"].split(" / ") + ["", "", "", ""])[:4]
        s = g["like_for_like"]
        wider = (("Same geography, any vintage or base year", g.get("same_geography_any_vintage_or_base_year")),
                 ("Same metric, unit and target year", g.get("same_metric_unit_and_year")))
        members = []
        for part in (s,) + tuple(w for _, w in wider):
            for oid in (part or {}).get("observation_ids", []):
                if oid in basis and oid not in members:
                    members.append(oid)
        excluded = ", ".join(str(x.get("id", x)) if isinstance(x, dict) else str(x) for x in g.get("excluded_short_of_supported", []))
        key = f"g{i}"
        out.append(
            f'<tr class="row" id="row-{key}" data-id="{key}" data-more="more-{key}" data-geo="{e(geography)}" '
            f'data-metric="{e(metric)}" data-year="{e(year)}">'
            f'<td><button type="button" class="more-btn" aria-expanded="false" aria-controls="more-{key}">'
            f'{words(g["group"])}</button></td>'
            f'<td class="num">{e(s["n_observations"])}</td><td class="num">{e(s["n_publishers"])}</td>'
            f'<td class="num">{e(number(s["minimum_stated_bound"]))}</td><td class="num">{e(number(s["maximum_stated_bound"]))}</td>'
            f'<td class="num">{e(number(s["span_width"]))}</td><td>{words(", ".join(s.get("crypto_scopes", [])))}</td>'
            f'<td>{e(excluded)}</td></tr>')
        items = [("Like for like", set_text(s, unit))] + [(name, set_text(w, unit)) for name, w in wider]
        items.append(("Target year basis", "; ".join(f"{e(oid)}: {e(basis[oid])}" for oid in members)))
        out.append(f'<tr class="more" id="more-{key}" hidden><td colspan="8">' + details(items) + "</td></tr>")
    return "\n".join(out)


def options(values):
    return "".join(f'<option value="{e(v)}">{words(v)}</option>' for v in values)


def generate(records):
    """The generated parts of the page, by block name."""
    rows = figures(records)
    observations = load(records, "OBSERVATIONS.json")
    results = load(records, "RESULTS.json")
    comparison = results["like_for_like_comparison"]
    ordered = lambda values: sorted(set(values), key=lambda v: (len(str(v)), str(v)) if isinstance(v, int) else str(v))
    registered = sum(r["kind"] == "registered" for r in rows)
    return {
        "version": e(observations["version"]), "asof": e(observations["as_of"]),
        "geography": options(ordered(r["geography"] for r in rows)),
        "metric": options(ordered(r["metric"] for r in rows)),
        "year": options(ordered(r["horizon"] for r in rows)),
        "figures": figure_rows(rows), "groups": group_rows(comparison["comparison"], rows),
        "shown": e(len(rows)), "total": e(len(rows)), "registered": e(registered), "candidates": e(len(rows) - registered),
        "supported": e(sum(r["receipt"] == "supported" for r in rows)),
        "groupsmore": e(comparison["groups_with_more_than_one_observation"]), "groupstotal": e(len(comparison["comparison"])),
        "groupsmixed": words("; ".join(comparison["groups_mixing_cryptocurrency_scopes"])),
        "grouprule": e(comparison["rule"]),
        "supportrule": e(results["support_review"]["rule"]), "admissionrule": e(results["candidate_admission"]["rule"]),
        "definitions": "".join(f"<dt>{words(k)}</dt><dd>{e(v)}</dd>" for k, v in sorted(observations["field_definitions"].items())),
        "limits": "".join(f"<li>{e(item)}</li>" for item in results["scope_limits"]),
    }


def render(page, blocks):
    found = BLOCK.findall(page)
    if sorted(found) != sorted(blocks) or len(found) != len(set(found)):
        raise ValueError("index.html must hold each GENERATED block exactly once: " + ", ".join(sorted(set(blocks) ^ set(found))))
    return BLOCK.sub(lambda m: f"<!--GENERATED:{m.group(1)}-->{blocks[m.group(1)]}<!--/GENERATED:{m.group(1)}-->", page)


def main(argv):
    if not HTML.exists() or not RECORDS.is_dir():
        print("error: run this from the folder with index.html and v0.5/")
        return 1
    page = HTML.read_text(encoding="utf-8")
    built = render(page, generate(RECORDS))
    if "--check" in argv:
        same = built == page
        print("index.html matches the v0.5 records" if same else "index.html differs from what the v0.5 records give")
        return 0 if same else 1
    HTML.write_text(built, encoding="utf-8")
    print("index.html rebuilt from the v0.5 records")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
