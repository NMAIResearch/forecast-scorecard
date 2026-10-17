"""
Checks that index.html displays the version 0.5 records exactly: every figure row and group row is read back from the
rendered page and compared, cell by cell, with the records through this file's own formatting. Also checks escaping,
receipt status, the page's own text and the v0.2 page. Run from the repository root:

    python3 -B -m unittest test_page -v

Pure standard library.
"""
import contextlib
import io
import json
import re
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import build

RECORDS = build.RECORDS
V02_PAGE = build.HERE / "v0.2" / "index.html"
V02_CSV = build.HERE / "forecast_scorecard_data.csv"
DASHES = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")


def load(name, records=RECORDS):
    return json.loads((records / name).read_text(encoding="utf-8"))


def num(value):
    return "none" if value is None else json.dumps(value)


def spaced(text):
    return " ".join(str(text).split())


class Page(HTMLParser):
    """Rows of the two tables, each with its attributes, the text of each cell and its buttons (attributes and text); the
    elements and links of the page."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.rows, self.links, self.tags = [], [], []
        self._table, self._row, self._cell, self._button = None, None, None, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, self._table))
        if tag == "table":
            self._table = a.get("id")
        elif tag == "tr" and self._table:
            self._row = {"table": self._table, "attrs": a, "cells": [], "buttons": []}
        elif tag == "td" and self._row is not None:
            self._cell = []
        elif tag == "button" and self._row is not None:
            self._row["buttons"].append(a)
            self._button = []
        if tag == "a":
            self.links.append(a.get("href", ""))

    def handle_endtag(self, tag):
        if tag == "button" and self._button is not None:
            self._row["buttons"][-1]["text"] = spaced("".join(self._button))
            self._button = None
        if tag == "td" and self._cell is not None:
            self._row["cells"].append(spaced("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._table = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._button is not None:
            self._button.append(data)

    def table(self, name, kind="row"):
        return [r for r in self.rows if r["table"] == name and r["attrs"].get("class") == kind]


def expected_value(r):
    unit = f"% growth relative to {r['base_year']}" if r["unit"] == "percent_growth" else r["unit"]
    if r["shape"] == "point":
        return f"{num(r['point'])} {unit}"
    if r["shape"] == "scenario_range":
        reference = f" (reference point {num(r['point'])})" if r["point"] is not None else ""
        return f"{num(r['low'])} to {num(r['high'])} {unit}{reference}"
    if r["shape"] == "upper_bound":
        return f"upper bound {num(r['high'])} {unit}"
    return f"lower bound {num(r['low'])} {unit}"


def records_in_order(records=RECORDS):
    return ([("registered", r) for r in load("OBSERVATIONS.json", records)["records"]] +
            [("candidate", r) for r in load("CANDIDATE_OBSERVATIONS.json", records)["records"]])


def rendered(records):
    """The page as build.py would write it for the given records."""
    return Page(build.render(build.HTML.read_text(encoding="utf-8"), build.generate(records)))


def copy_of_records(folder):
    target = Path(folder) / "v0.5"
    shutil.copytree(RECORDS, target)
    return target


class PageShowsTheRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = build.HTML.read_text(encoding="utf-8")
        cls.page = Page(cls.text)
        cls.figures = cls.page.table("figures")
        cls.groups = cls.page.table("groups")

    def test_the_page_is_current(self):
        self.assertEqual(build.render(self.text, build.generate(RECORDS)), self.text)

    def test_every_observation_once_in_record_order(self):
        self.assertEqual([r["attrs"]["data-id"] for r in self.figures], [r["id"] for _, r in records_in_order()])

    def test_each_row_displays_its_record(self):
        basis = load("CANDIDATE_OBSERVATIONS.json").get("horizon_basis", {})
        for (kind, r), row in zip(records_in_order(), self.figures):
            cells, rid = row["cells"], r["id"]
            self.assertEqual(cells[0], rid)
            self.assertTrue(cells[1].startswith(r["forecaster"]), rid)
            self.assertEqual(cells[2], r["geography"], rid)
            year = spaced(f"{r['horizon']} {basis.get(rid, '')}") if kind == "candidate" else str(r["horizon"])
            self.assertEqual(cells[3], year, rid)
            self.assertEqual(cells[4], expected_value(r), rid)
            self.assertEqual(cells[5], r["metric"].replace("_", " "), rid)
            self.assertEqual(cells[6], r["scenario"], rid)
            self.assertEqual(cells[7], r["coverage"].replace("_", " "), rid)
            self.assertEqual(cells[8], r["crypto_scope"].replace("_", " "), rid)
            self.assertEqual(row["attrs"]["data-kind"], kind, rid)
            if r.get("superseded_by"):
                self.assertIn(f"superseded by {r['superseded_by']}", cells[1], rid)

    def test_receipts_and_admission(self):
        results = load("RESULTS.json")
        admitted = set(results["candidate_admission"]["admitted"])
        for (kind, r), row in zip(records_in_order(), self.figures):
            if kind == "registered":
                expected = results["support_review"]["by_observation"][r["id"]]
                self.assertEqual(row["cells"][9], expected, r["id"])
            else:
                expected = "supported" if r["id"] in admitted else row["attrs"]["data-receipt"]
                self.assertNotEqual(expected, "", r["id"])
                self.assertEqual(row["cells"][9], f"{expected} {'admitted' if r['id'] in admitted else 'not admitted'}", r["id"])
            self.assertEqual(row["attrs"]["data-receipt"], expected, r["id"])

    def test_details_show_source_locator_and_qualification(self):
        catalogue = {s["id"]: s for s in load("SOURCE_CATALOGUE.json")["sources"]}
        catalogue.update({s["id"]: s for s in load("CANDIDATE_OBSERVATIONS.json")["sources"]})
        more = {r["attrs"]["id"]: r for r in self.page.table("figures", "more")}
        for (_, r), row in zip(records_in_order(), self.figures):
            detail = more[row["attrs"]["data-more"]]["cells"][0]
            source = catalogue[r["source_id"]]
            for text in (source["title"], r["locator"], r["qualification"], r["source_id"]):
                self.assertIn(spaced(text), detail, r["id"])
            self.assertIn(source["url"], self.page.links, r["id"])

    def test_every_row_opens_from_a_button(self):
        ids = {r["attrs"]["id"] for r in self.page.rows if r["attrs"].get("class") == "more"}
        for row in self.figures + self.groups:
            buttons = [b for b in row["buttons"] if b.get("class") == "more-btn"]
            self.assertEqual(len(buttons), 1, row["attrs"]["id"])
            self.assertEqual(buttons[0].get("aria-expanded"), "false")
            self.assertIn(buttons[0].get("aria-controls"), ids)

    def test_button_names_include_their_visible_text(self):
        for row in self.figures + self.groups:
            for button in row["buttons"]:
                self.assertTrue(button["text"], row["attrs"]["id"])
                name = spaced(button.get("aria-label", button["text"]))
                self.assertIn(button["text"].lower(), name.lower(), row["attrs"]["id"])

    def test_hidden_parts_stay_hidden_at_every_width(self):
        style = self.text.split("<style>")[1].split("</style>")[0]
        rule = re.search(r"\[hidden\]\s*\{\s*display\s*:\s*none\s*!important\s*;?\s*\}", style)
        self.assertIsNotNone(rule, "the stylesheet has no [hidden]{display:none!important} rule")

    def test_tables_scroll_inside_their_own_box(self):
        for name in ("figures", "groups"):
            box = re.search(r'<div class="scroll">\s*<table id="' + name + '"', self.text)
            self.assertIsNotNone(box, f"the {name} table is not inside a scroll box")
        style = self.text.split("<style>")[1].split("</style>")[0]
        self.assertIsNone(re.search(r"(^|[\s,{}])table\s*\{[^}]*display", style), "a rule sets the display of tables")
        unconditional = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", style)
        rule = re.search(r"(^|[\s,}])\.scroll\s*\{[^}]*overflow-x\s*:\s*auto", unconditional)
        self.assertIsNotNone(rule, "the scroll box does not scroll sideways at every width")
        # No later or narrower rule may turn that off: every rule naming .scroll, inside a media query or not, and every
        # !important overflow declaration keeps sideways scrolling (the first value of overflow is its x value).
        for selector, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", style):
            names_box = re.search(r"\.scroll(?![\w-])", selector)
            if names_box:
                self.assertNotRegex(declarations, r"(?<![\w-])display\s*:", f"{selector.strip()} sets display")
            for prop, value in re.findall(r"(?<![\w-])(overflow(?:-x)?)\s*:\s*([^;]+)", declarations):
                if names_box or "!important" in value:
                    sideways = value.replace("!important", " ").split()[0]
                    self.assertIn(sideways, ("auto", "scroll"), f"{selector.strip()} sets {prop}: {value.strip()}")

    def test_groups_display_the_results(self):
        comparison = load("RESULTS.json")["like_for_like_comparison"]["comparison"]
        self.assertEqual(len(self.groups), len(comparison))
        more = {r["attrs"]["id"]: r for r in self.page.table("groups", "more")}
        for g, row in zip(comparison, self.groups):
            s, cells = g["like_for_like"], row["cells"]
            self.assertEqual(cells[0], g["group"].replace("_", " "))
            self.assertEqual(cells[1:6], [num(s["n_observations"]), num(s["n_publishers"]), num(s["minimum_stated_bound"]),
                                          num(s["maximum_stated_bound"]), num(s["span_width"])], g["group"])
            unit = g["group"].split(" / ")[2]
            detail = more[row["attrs"]["data-more"]]["cells"][0]
            for part in (s, g.get("same_geography_any_vintage_or_base_year"), g.get("same_metric_unit_and_year")):
                for bound in (part or {}).get("open_lower_bounds", []):
                    self.assertIn(f"{bound['id']} lower bound {num(bound['lower_bound'])} {unit}", detail, g["group"])

    def test_group_details_carry_the_horizon_basis(self):
        basis = load("CANDIDATE_OBSERVATIONS.json").get("horizon_basis", {})
        comparison = load("RESULTS.json")["like_for_like_comparison"]["comparison"]
        more = {r["attrs"]["id"]: r for r in self.page.table("groups", "more")}
        checked = 0
        for g, row in zip(comparison, self.groups):
            ids = set()
            for part in (g["like_for_like"], g.get("same_geography_any_vintage_or_base_year"), g.get("same_metric_unit_and_year")):
                ids.update((part or {}).get("observation_ids", []))
            for oid in sorted(ids & set(basis)):
                self.assertIn(f"{oid}: {basis[oid]}", more[row["attrs"]["data-more"]]["cells"][0], g["group"])
                checked += 1
        self.assertGreater(checked, 0)

    def test_quoted_text_occurs_in_the_paper(self):
        paper = (RECORDS / "PAPER.md").read_text(encoding="utf-8")
        quoted = re.findall(r'data-src="PAPER\.md">([^<]+)<', self.text)
        self.assertGreaterEqual(len(quoted), 4)
        for text in quoted:
            self.assertIn(text, paper)

    def test_dashes_only_in_publication_titles(self):
        titles = [s["title"] for s in load("SOURCE_CATALOGUE.json")["sources"] + load("CANDIDATE_OBSERVATIONS.json")["sources"]]
        text = self.text
        for title in titles:
            text = text.replace(build.e(title), "")
        self.assertIsNone(DASHES.search(text))

    def test_links_are_https_or_relative(self):
        for target in self.page.links:
            self.assertTrue(target.startswith("https://") or not re.match(r"^[a-z]+:", target), target)

    def test_the_script_inserts_no_record_text(self):
        script = self.text.split("<script>")[2]
        self.assertNotIn("innerHTML", script)


class PageFollowsChangedRecords(unittest.TestCase):
    def test_a_stale_candidate_receipt_is_not_shown_as_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            records = copy_of_records(folder)
            doc = load("CANDIDATE_OBSERVATIONS.json", records)
            doc["records"][0]["qualification"] += " Changed after review."
            (records / "CANDIDATE_OBSERVATIONS.json").write_text(json.dumps(doc), encoding="utf-8")
            page = rendered(records)
            row = [r for r in page.table("figures") if r["attrs"]["data-id"] == doc["records"][0]["id"]][0]
            self.assertNotEqual(row["attrs"]["data-receipt"], "supported")
            self.assertFalse(row["cells"][9].startswith("supported"))
            self.assertIn("not admitted", row["cells"][9])

    def test_a_candidate_without_a_receipt_is_not_shown_as_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            records = copy_of_records(folder)
            reviews = load("CANDIDATE_SUPPORT_REVIEW.json", records)
            dropped = reviews["reviews"].pop(0)["candidate_id"]
            (records / "CANDIDATE_SUPPORT_REVIEW.json").write_text(json.dumps(reviews), encoding="utf-8")
            row = [r for r in rendered(records).table("figures") if r["attrs"]["data-id"] == dropped][0]
            self.assertNotEqual(row["attrs"]["data-receipt"], "supported")
            self.assertIn("not admitted", row["cells"][9])

    def test_markup_in_the_records_is_shown_as_text(self):
        with tempfile.TemporaryDirectory() as folder:
            records = copy_of_records(folder)
            doc = load("OBSERVATIONS.json", records)
            doc["records"][0]["qualification"] = "<img src=x onerror=alert(1)>"
            doc["records"][0]["scenario"] = "</td><script>alert(1)</script>"
            (records / "OBSERVATIONS.json").write_text(json.dumps(doc), encoding="utf-8")
            page = rendered(records)
            self.assertNotIn(("img", "figures"), page.tags)
            self.assertNotIn(("script", "figures"), page.tags)
            row = page.table("figures")[0]
            self.assertEqual(row["cells"][6], "</td><script>alert(1)</script>")

    def test_a_wrong_figure_is_caught(self):
        text = build.HTML.read_text(encoding="utf-8")
        first = load("OBSERVATIONS.json")["records"][0]
        shown = f'<span class="val">{num(first["point"])}</span>'
        self.assertIn(shown, text)
        changed = text.replace(shown, f'<span class="val">{num(first["point"] + 1)}</span>', 1)
        with tempfile.TemporaryDirectory() as folder:
            page = Path(folder) / "index.html"
            original = build.HTML
            try:
                page.write_text(changed, encoding="utf-8")
                build.HTML = page
                with contextlib.redirect_stdout(io.StringIO()) as printed:
                    self.assertEqual(build.main(["--check"]), 1)
                self.assertIn("differs", printed.getvalue())
                self.assertNotEqual(Page(changed).table("figures")[0]["cells"][4], expected_value(first))
            finally:
                build.HTML = original


class V02PageKeepsItsData(unittest.TestCase):
    def test_embedded_csv_equals_the_v02_csv(self):
        html_text = V02_PAGE.read_text(encoding="utf-8")
        found = re.findall(r"const CSV = `(.*?)`;", html_text, re.DOTALL)
        self.assertEqual(found, [V02_CSV.read_text(encoding="utf-8").strip()])

    def test_marked_historical(self):
        self.assertIn("<b>Historical view.</b>", V02_PAGE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
