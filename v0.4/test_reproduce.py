#!/usr/bin/env python3
"""Test arithmetic, review binding, source boundaries and safe output handling on disposable copies.
Produced through an AI-assisted workflow (OpenAI GPT-6; Anthropic Opus 5.5) directed and reviewed by the author."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("forecast_reproducer", ROOT / "reproduce.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReproductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="forecast-test-")
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "bundle"
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns("__pycache__"))
        self.data, self.sources, self.receipts = module.load(self.root)
        self.rows = {r["id"]: r for r in self.data["records"]}
        self.supported = {i: "supported" for i in self.rows}

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(self.root / "reproduce.py"), *args], capture_output=True, text=True)

    def alter(self, change):
        change(self.data)
        (self.root / "OBSERVATIONS.json").write_bytes(module.encoded(self.data))

    def receipt(self, rid, verdict="supported"):
        row = self.rows[rid]
        return {"observation_id": rid, "row_sha256": module.row_digest(row), "catalogue_sha256": module.catalogue_digest(self.sources),
                "verdict": verdict, "reviewer": "test fixture", "review_record_sha256": "0" * 64, "locator": "fixture"}

    def refresh(self, candidates=True):
        """Regenerate outputs and manifest hashes in the disposable copy, so that only a paper disagreement can remain. Outputs
        include admitted candidates, as reproduce.py --check computes them; candidates=False serves a fixture whose candidate
        file or ledger IDs the reproducer is expected to refuse, so that outputs cannot be computed with candidates."""
        data, sources, receipts = module.load(self.root)
        admitted = module.load_candidates(self.root, data) if candidates else None
        for name, payload in module.outputs(data, sources, receipts, admitted).items():
            (self.root / name).write_bytes(payload)
        path = self.root / "REPRODUCTION.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"] = {n: hashlib.sha256((self.root / n).read_bytes()).hexdigest() for n in manifest["files"]}
        path.write_bytes(module.encoded(manifest))

    def compare(self, old, new, status=None):
        return module.compare(self.rows[old], self.rows[new], self.supported if status is None else status)

    def test_check_is_read_only(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        result = self.cli("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})
        self.assertIn("scientific validity", json.loads(result.stdout)["not_assessed"])

    def test_bnef_arithmetic_has_the_actual_denominator(self):
        result = self.compare("O13", "O14")
        self.assertEqual((result["numerator"], result["denominator"], result["n_observations"]), (88, 106, 2))
        self.assertAlmostEqual(result["relative_change_percent"], 83.0188679245283)

    def test_growth_revision_uses_the_source_named_prior(self):
        result = self.compare("O19", "O11")
        self.assertEqual(result["growth_rate_difference_percentage_points"], 45)
        self.assertAlmostEqual(result["denominator"], 2.75)
        self.assertAlmostEqual(result["relative_change_percent"], 16.363636363636363)

    def test_upper_end_statement_is_not_a_point(self):
        result = self.compare("O10", "O11")
        self.assertEqual(result["status"], "not_comparable")
        self.assertIn("an upper-end statement is not a point estimate", result["reasons"])

    def test_open_lower_bound_is_not_a_point(self):
        result = self.compare("O17", "O27")
        self.assertEqual(result["status"], "not_comparable")
        self.assertIn("an open lower bound is not a point estimate", result["reasons"])

    def test_lower_bound_record_carries_only_its_lower_value(self):
        for field, value in (("high", 1300), ("point", 1250)):
            row = dict(self.rows["O27"], **{field: value})
            with self.assertRaisesRegex(ValueError, "lower-bound record"):
                module.check_row(row, self.sources)
        with self.assertRaises(ValueError):
            module.check_row(dict(self.rows["O27"], low=-1), self.sources)

    def test_open_lower_bound_is_listed_not_used_as_span_maximum(self):
        receipts = [self.receipt(i) for i in self.rows]
        result = module.results(self.data, self.sources, receipts)
        span = next(s for s in result["recorded_value_spans"] if "O27" in s["observation_ids"])
        self.assertEqual(span["open_lower_bounds"], [{"id": "O27", "lower_bound": 1200}])
        bounded = [self.rows[i]["high"] for i in span["observation_ids"] if self.rows[i]["shape"] != "lower_bound"]
        self.assertEqual(span["maximum_stated_bound"], max(bounded))
        self.assertTrue(all(not s["open_lower_bounds"] for s in result["recorded_value_spans"] if "O27" not in s["observation_ids"]))
        self.assertIn("exclude open lower bounds", span["interpretation"])

    def test_growth_lower_bound_generates_all_outputs(self):
        self.alter(lambda d: next(r for r in d["records"] if r["id"] == "O11").update(shape="lower_bound", low=175, high=None, point=None))
        self.assertEqual(self.cli("--explain", "O11").returncode, 0)
        out = self.parent / "lower-growth"
        result = self.cli("--output-dir", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(module.OUTPUTS))
        table = (out / "FORECASTS.md").read_text(encoding="utf-8")
        self.assertIn(f"lower bound 175 percent_growth versus {self.rows['O11']['base_year']}", table)
        self.assertIn("normalised change lower bound 175 / baseline 100", table)
        self.assertIn("lower_bound", (out / "FORECASTS.csv").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((out / "RESULTS.json").read_text(encoding="utf-8"))["observation_count"], len(self.rows))

    def test_markdown_rows_state_cryptocurrency_and_facility_boundary(self):
        table = module.outputs(self.data, self.sources, self.receipts)["FORECASTS.md"].decode("utf-8")
        rows = {line.split(" | ")[0].lstrip("| ").strip(): line for line in table.splitlines() if line.startswith("| O")}
        self.assertIn("| Boundary |", table)
        self.assertIn("cryptocurrency excluded; ", rows["O05"])
        self.assertIn("cryptocurrency included; small and large data centres and cryptocurrency", rows["O07"])
        self.assertIn("cryptocurrency excluded by inference; facility boundary not fully stated", rows["O08"])
        self.assertIn("cryptocurrency not stated; total facility, IT plus overhead", rows["O01"])
        self.assertIn("cryptocurrency not stated; facility boundary not fully stated", rows["O10"])
        self.assertEqual(len(rows), len(self.rows))
        self.alter(lambda d: next(r for r in d["records"] if r["id"] == "O05").update(crypto_scope="partial"))
        with self.assertRaisesRegex(ValueError, "No readable boundary label for O05"):
            module.outputs(*module.load(self.root))

    def test_check_rejects_a_manifest_listed_file_changed_without_its_hash(self):
        self.assertEqual(self.cli("--check").returncode, 0)
        readme = self.root / "README.md"
        readme.write_bytes(readme.read_bytes() + b"\nAltered after packaging.\n")
        result = self.cli("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Package hash differs: README.md", result.stderr)

    def test_generated_table_carries_the_house_disclosure(self):
        table = module.outputs(self.data, self.sources, self.receipts)["FORECASTS.md"].decode("utf-8")
        self.assertIn("This work was produced through an AI-assisted workflow directed and reviewed by the author.", table.split("|")[0])
        self.assertIn("## AI assistance, conflicts and limitations", table)
        self.assertIn(module.DISCLOSURE, table)

    def test_paper_lower_bound_sentence_tracks_the_ledger(self):
        statements = module.paper_statements(self.data)
        self.assertEqual(list(statements), ["O27"])
        self.assertIn(statements["O27"], (self.root / "PAPER.md").read_text(encoding="utf-8"))
        self.refresh()
        self.assertEqual(self.cli("--check").returncode, 0)
        self.alter(lambda d: next(r for r in d["records"] if r["id"] == "O27").update(low=1300))
        self.refresh()
        self.assertIn("PAPER.md disagrees with the ledger: O27", self.cli("--check").stderr)

    def test_lower_bound_needs_a_stated_inclusivity(self):
        qualification = self.rows["O27"]["qualification"].replace("an exclusive lower bound", "a lower bound")
        self.alter(lambda d: next(r for r in d["records"] if r["id"] == "O27").update(qualification=qualification))
        self.refresh()
        self.assertIn("needs one stated inclusivity", self.cli("--check").stderr)

    def test_same_base_goldman_revision_is_upward(self):
        result = self.compare("O20", "O12")
        self.assertEqual(result["status"], "conditional_arithmetic")
        self.assertAlmostEqual(result["relative_change_percent"], 24.423963133640566)

    def test_iea_tabulated_pair_is_a_one_unit_fall(self):
        result = self.compare("O01", "O03")
        self.assertEqual((result["difference"], result["denominator"]), (-1, 946))
        self.assertEqual(self.compare("O02", "O18")["difference"], 0)

    def test_changed_base_year_is_not_a_downward_revision(self):
        result = self.compare("O11", "O12")
        self.assertEqual(result["status"], "not_comparable")
        self.assertIn("different base_year", result["reasons"])
        self.assertNotIn("relative_change_percent", result)

    def test_unit_and_metric_boundaries_are_refused(self):
        self.assertIn("different unit", self.compare("O03", "O09")["reasons"])
        self.assertIn("different unit", self.compare("O03", "O10")["reasons"])
        old, new = copy.deepcopy(self.rows["O13"]), copy.deepcopy(self.rows["O14"])
        new["unit"] = "TWh"
        self.assertIn("different unit", module.compare(old, new, self.supported)["reasons"])
        new = copy.deepcopy(self.rows["O14"]); new["metric"] = "annual_electricity"
        self.assertIn("different metric", module.compare(old, new, self.supported)["reasons"])

    def test_cross_publisher_unknown_scope_is_refused(self):
        self.assertEqual(self.compare("O18", "O16")["status"], "not_comparable")
        old, new = copy.deepcopy(self.rows["O16"]), copy.deepcopy(self.rows["O16"])
        new.update(id="X01", forecaster="Other publisher", comparison_family="")
        reasons = module.compare(old, new, dict(self.supported, X01="supported"))["reasons"]
        self.assertEqual(reasons, ["scope is unresolved: crypto_scope", "scope is unresolved: coverage"])
        old["scenario"] = new["scenario"] = "unstated"
        self.assertIn("scenario is unresolved", module.compare(old, new, dict(self.supported, X01="supported"))["reasons"])

    def test_crypto_scope_and_quantity_boundaries_are_not_normalised(self):
        self.assertEqual(self.compare("O05", "O07")["status"], "not_comparable")
        self.assertEqual(self.compare("O14", "O15")["status"], "not_comparable")

    def test_same_publisher_does_not_override_an_explicit_scope_or_scenario_change(self):
        old, new = copy.deepcopy(self.rows["O13"]), copy.deepcopy(self.rows["O14"])
        old["crypto_scope"], new["crypto_scope"] = "included", "excluded"
        self.assertEqual(module.compare(old, new, self.supported)["status"], "not_comparable")
        old, new = copy.deepcopy(self.rows["O01"]), copy.deepcopy(self.rows["O03"])
        new["scenario"] = "Lift-Off Case"
        self.assertIn("different scenario", module.compare(old, new, self.supported)["reasons"])

    def test_value_basis_mismatch_is_refused(self):
        old, new = copy.deepcopy(self.rows["O01"]), copy.deepcopy(self.rows["O03"])
        new["value_basis"] = "text_value"
        self.assertIn("different value_basis", module.compare(old, new, self.supported)["reasons"])

    def test_point_inside_range_is_not_flat(self):
        old = copy.deepcopy(self.rows["O05"])
        new = copy.deepcopy(old)
        new.update(shape="point", low=649, high=649, point=649)
        self.assertEqual(module.compare(old, new, self.supported)["status"], "no_direction_assigned")

    def test_unreviewed_partly_supported_or_stale_rows_block_arithmetic(self):
        for verdict in ("unreviewed", "partly supported", "review stale"):
            with self.subTest(verdict=verdict):
                status = dict(self.supported, O13=verdict)
                self.assertIn("O13 support review: " + verdict, self.compare("O13", "O14", status)["reasons"])

    def test_receipt_binds_row_and_source_digests(self):
        receipts = [self.receipt(i) for i in self.rows]
        self.assertEqual(set(module.review_status(self.data, self.sources, receipts).values()), {"supported"})
        edited = copy.deepcopy(self.data)
        next(r for r in edited["records"] if r["id"] == "O14")["qualification"] += " Edited."
        self.assertEqual(module.review_status(edited, self.sources, receipts)["O14"], "review stale")
        sources = copy.deepcopy(self.sources); sources["S11"]["locator"] += " edited"
        self.assertEqual(module.review_status(self.data, sources, receipts)["O14"], "review stale")
        auxiliary = copy.deepcopy(self.sources); auxiliary["S09"]["original_sha256"] = "0" * 64
        status = module.review_status(self.data, auxiliary, receipts)
        self.assertEqual((status["O11"], status["O19"]), ("review stale", "review stale"))
        self.assertIn("O19 support review: review stale", module.compare(self.rows["O19"], self.rows["O11"], status)["reasons"])
        maker = copy.deepcopy(self.data)
        next(r for r in maker["records"] if r["id"] == "O14")["maker_assessment"] = "contradicted"
        self.assertEqual(module.review_status(maker, self.sources, receipts)["O14"], "supported")

    def test_spans_use_only_current_supported_rows_and_one_vintage_per_series(self):
        receipts = [self.receipt(i, "partly supported" if i == "O16" else "supported") for i in self.rows]
        result = module.results(self.data, self.sources, receipts)
        members = [i for span in result["recorded_value_spans"] for i in span["observation_ids"]]
        self.assertNotIn("O16", members)
        self.assertNotIn("O06", members)
        self.assertTrue({"O01", "O02", "O10", "O13", "O19", "O20"}.isdisjoint(members))
        self.assertEqual({s["id"] for s in result["superseded_observations"]}, {"O01", "O02", "O10", "O13", "O19", "O20"})
        for span in result["recorded_value_spans"]:
            families = [self.rows[i]["comparison_family"] for i in span["observation_ids"] if self.rows[i]["comparison_family"]]
            self.assertEqual(len(families), len(set(families)), span["group"])
            self.assertEqual(len({self.rows[i]["base_year"] for i in span["observation_ids"]}), 1)

    def test_without_receipts_no_arithmetic_or_span_is_produced(self):
        result = module.results(self.data, self.sources, [])
        self.assertEqual(result["recorded_value_spans"], [])
        self.assertTrue(all(c["status"] == "not_comparable" for c in result["comparisons"]))

    def test_duplicate_ids_fail(self):
        self.alter(lambda d: d["records"].append(copy.deepcopy(d["records"][0])))
        self.assertNotEqual(self.cli("--check").returncode, 0)

    def test_duplicate_json_keys_fail(self):
        text = (self.root / "OBSERVATIONS.json").read_text(encoding="utf-8")
        (self.root / "OBSERVATIONS.json").write_text(text.replace('"id": "O01",', '"id": "O01", "id": "O99",', 1), encoding="utf-8")
        self.assertIn("Duplicate JSON key", self.cli("--check").stderr)

    def test_missing_source_fails(self):
        self.alter(lambda d: d["records"][0].update(source_id="missing"))
        self.assertIn("Unknown source", self.cli("--check").stderr)

    def test_nonfinite_and_boolean_values_fail(self):
        for value in (True, float("inf"), float("nan")):
            with self.subTest(value=value):
                d = copy.deepcopy(self.data); d["records"][0]["point"] = value
                (self.root / "OBSERVATIONS.json").write_text(json.dumps(d))
                self.assertNotEqual(self.cli("--check").returncode, 0)

    def test_invalid_quantities_fail(self):
        cases = [("O05", dict(low=900, high=100), "Invalid forecast interval"),
                 ("O05", dict(point=900), "outside its stated interval"),
                 ("O03", dict(unit="MW"), "Unsupported unit"),
                 ("O11", dict(base_year=None), "base year before the horizon"),
                 ("O11", dict(base_year=2030), "base year before the horizon"),
                 ("O03", dict(base_year=2023), "cannot carry a growth base year"),
                 ("O03", dict(horizon=1999), "Invalid year"),
                 ("O03", dict(qualification=" "), "Missing text field: qualification"),
                 ("O03", dict(value_basis="guess"), "Unsupported value basis"),
                 ("O10", dict(low=100), "carries only its stated upper value"),
                 ("O10", dict(point=165), "carries only its stated upper value")]
        for rid, change, message in cases:
            with self.subTest(rid=rid, change=change):
                d = copy.deepcopy(self.data)
                next(r for r in d["records"] if r["id"] == rid).update(change)
                (self.root / "OBSERVATIONS.json").write_bytes(module.encoded(d))
                self.assertIn(message, self.cli("--check").stderr)

    def test_superseded_link_must_stay_in_series(self):
        self.alter(lambda d: next(r for r in d["records"] if r["id"] == "O01").update(superseded_by="O18"))
        self.assertIn("same series and quantity", self.cli("--check").stderr)

    def test_supersession_cycles_fail_and_chains_pass(self):
        cycles = [{"O03": "O01"}, {"O10": "O19", "O11": "O10"}]
        for links in cycles:
            with self.subTest(links=links):
                d = copy.deepcopy(self.data)
                for r in d["records"]:
                    r["superseded_by"] = links.get(r["id"], r["superseded_by"])
                (self.root / "OBSERVATIONS.json").write_bytes(module.encoded(d))
                self.assertIn("form a cycle", self.cli("--check").stderr)
        d = copy.deepcopy(self.data)
        next(r for r in d["records"] if r["id"] == "O10")["superseded_by"] = "O19"
        (self.root / "OBSERVATIONS.json").write_bytes(module.encoded(d))
        loaded = module.load(self.root)[0]
        self.assertEqual(next(r for r in loaded["records"] if r["id"] == "O10")["superseded_by"], "O19")

    def test_rows_cannot_claim_unearned_review_fields(self):
        self.alter(lambda d: d["records"][0].update(independent_review="accepted"))
        self.assertIn("declared schema", self.cli("--check").stderr)

    def test_duplicate_current_receipts_fail_but_stale_history_is_ignored(self):
        current = self.receipt("O14")
        other = dict(current, verdict="partly supported")
        for receipts in ([current, dict(current)], [current, other], [other, current]):
            with self.subTest(verdicts=[r["verdict"] for r in receipts]):
                with self.assertRaisesRegex(ValueError, "More than one current review receipt: O14"):
                    module.review_status(self.data, self.sources, receipts)
        stale = dict(current, row_sha256="0" * 64, verdict="partly supported")
        for receipts in ([stale, current], [current, stale]):
            self.assertEqual(module.review_status(self.data, self.sources, receipts)["O14"], "supported")

    def test_malformed_receipt_fails(self):
        p = self.root / "SUPPORT_REVIEW.json"; d = json.loads(p.read_text())
        d["reviews"].append(dict(self.receipt("O01"), verdict="accepted")); p.write_bytes(module.encoded(d))
        self.assertIn("Malformed support review receipt", self.cli("--check").stderr)

    def test_corrupt_generated_output_fails(self):
        (self.root / "FORECASTS.csv").write_text("changed\n")
        self.assertIn("Generated output differs", self.cli("--check").stderr)

    def test_manifest_omission_fails(self):
        p = self.root / "REPRODUCTION.json"; d = json.loads(p.read_text())
        d["files"].pop("PAPER.md"); p.write_bytes(module.encoded(d))
        self.assertIn("exact declared package", self.cli("--check").stderr)

    def test_missing_or_symlink_input_fails(self):
        for name in ("OBSERVATIONS.json", "SUPPORT_REVIEW.json"):
            with self.subTest(name=name):
                p = self.root / name; backup = self.parent / (name + ".bak")
                p.rename(backup); p.symlink_to(backup)
                self.assertIn("non-regular", self.cli("--check").stderr)
                p.unlink(); backup.rename(p)

    def test_unlisted_private_file_cannot_pass_package_check(self):
        (self.root / "private-notes.txt").write_text("disposable fixture")
        self.assertIn("unexpected or missing entries", self.cli("--check").stderr)

    def test_existing_internal_and_symlink_outputs_are_refused(self):
        link = self.parent / "link-out"
        os.symlink(self.parent / "absent-target", link)
        for target in (self.root, self.root / "inside", self.parent, link):
            with self.subTest(target=target):
                self.assertIn("new and outside", self.cli("--output-dir", str(target)).stderr)
        self.assertFalse((self.root / "inside").exists())
        self.assertFalse((self.parent / "absent-target").exists())

    def test_failed_generation_leaves_no_partial_directory(self):
        target = self.parent / "partial"
        with self.assertRaises(TypeError):
            module.write_outputs(target, {"FORECASTS.csv": b"ok\n", "RESULTS.json": "not bytes"})
        self.assertFalse(target.exists())

    def test_generation_and_explanation_preserve_qualifications(self):
        out = self.parent / "generated"
        result = self.cli("--output-dir", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["source_truth"], "not_assessed")
        result = self.cli("--explain", "O12"); data = json.loads(result.stdout)
        self.assertEqual(data["observation"]["base_year"], 2025)
        self.assertEqual(data["observation"]["forecast_vintage"], "2026-08-12 (statement recorded)")
        self.assertEqual(data["support_review"], "supported")
        self.assertIn("not a decline", data["source"]["coverage_limit"])
        self.assertIn("transcript", data["observation"]["qualification"])
        result = self.cli("--explain", "O11")
        self.assertEqual(json.loads(result.stdout)["support_review"], "partly supported")
        result = self.cli("--explain", "O21")
        self.assertEqual(json.loads(result.stdout)["support_review"], "supported")

    def test_unknown_id_and_argument_fail(self):
        self.assertNotEqual(self.cli("--explain", "missing").returncode, 0)
        self.assertEqual(self.cli("--not-an-option").returncode, 2)

    def read_bundle_json(self, name):
        return json.loads((self.root / name).read_text(encoding="utf-8"))

    def write_bundle_json(self, name, doc):
        (self.root / name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def test_like_for_like_comparison_sets_counts_and_exclusions(self):
        result = module.results(self.data, self.sources, self.receipts)["like_for_like_comparison"]
        groups = {c["group"]: c for c in result["comparison"]}
        self.assertEqual((result["groups"], result["groups_with_more_than_one_observation"]), (11, 3))
        self.assertEqual(result["groups_mixing_cryptocurrency_scopes"], ["US / annual_electricity / TWh / 2030 / None"])
        us = groups["US / annual_electricity / TWh / 2030 / None"]
        own = us["like_for_like"]
        self.assertEqual((own["n_observations"], own["n_publishers"], own["minimum_stated_bound"], own["maximum_stated_bound"]), (5, 5, 380, 843))
        self.assertEqual(us["same_geography_any_vintage_or_base_year"]["added_observations"], ["O02"])
        wide = us["same_metric_unit_and_year"]
        self.assertEqual(sorted(wide["added_observations"]), ["O01", "O03", "O17", "O27"])
        self.assertEqual((wide["n_observations"], wide["n_publishers"], wide["minimum_stated_bound"], wide["maximum_stated_bound"]), (10, 7, 380, 1065))
        growth = groups["Global / data_centre_power_demand_growth / percent_growth / 2030 / 2025"]
        self.assertEqual(growth["like_for_like"]["observation_ids"], ["O12"])
        self.assertEqual(sorted(growth["same_geography_any_vintage_or_base_year"]["added_observations"]), ["O10", "O20"])
        self.assertEqual(growth["excluded_short_of_supported"], ["O11", "O19"])
        self.assertEqual(groups["US / installed_capacity / GW / 2035 / None"]["excluded_short_of_supported"], ["O13"])

    def test_like_for_like_sets_exclude_and_list_short_of_supported_rows(self):
        receipts = [self.receipt(i, "partly supported" if i == "O16" else "supported") for i in self.rows]
        result = module.results(self.data, self.sources, receipts)["like_for_like_comparison"]
        us = next(c for c in result["comparison"] if c["group"] == "US / annual_electricity / TWh / 2030 / None")
        for key in ("like_for_like", "same_geography_any_vintage_or_base_year", "same_metric_unit_and_year"):
            self.assertNotIn("O16", us[key]["observation_ids"])
        self.assertEqual(us["excluded_short_of_supported"], ["O16"])
        self.assertEqual(module.results(self.data, self.sources, [])["like_for_like_comparison"]["comparison"], [])

    def test_open_lower_bound_is_listed_not_an_extremum_in_wider_sets(self):
        result = module.results(self.data, self.sources, self.receipts)["like_for_like_comparison"]
        seen = 0
        for item in result["comparison"]:
            for key in ("like_for_like", "same_geography_any_vintage_or_base_year", "same_metric_unit_and_year"):
                span = item[key]
                if "O27" in span["observation_ids"]:
                    seen += 1
                    self.assertEqual(span["open_lower_bounds"], [{"id": "O27", "lower_bound": 1200}])
                    self.assertLess(span["maximum_stated_bound"], 1200)
        self.assertGreaterEqual(seen, 3)

    def test_paper_carries_every_generated_block(self):
        data, sources, receipts = module.load(self.root)
        blocks = module.paper_blocks(data, sources, receipts, module.load_candidates(self.root, data), module.load_prior_work(self.root, data))
        self.assertEqual(sorted(blocks), sorted(["like-for-like table", "like-for-like summary", "like-for-like reading", "4E overlap", "4E comparison table",
                                                 "4E differences", "4E parameter table", "4E quality filter", "earlier-work references",
                                                 "candidate table", "candidate status"]))
        paper = (self.root / "PAPER.md").read_text(encoding="utf-8")
        for name, block in blocks.items():
            self.assertIn(block, paper, name)
        printed = json.loads(self.cli("--paper-blocks").stdout)
        self.assertEqual(printed, blocks)

    def test_check_rejects_a_paper_table_that_drifts_from_the_ledger(self):
        self.assertEqual(self.cli("--check").returncode, 0)
        self.alter(lambda d: next(r for r in d["records"] if r["id"] == "O05").update(high=900))
        self.refresh()
        self.assertIn("PAPER.md disagrees with the generated like-for-like table", self.cli("--check").stderr)

    def test_check_rejects_a_comparison_record_changed_without_the_paper(self):
        prior = self.read_bundle_json("PRIOR_WORK.json")
        prior["four_e_comparison"][0]["four_e_record"] += " Edited."
        self.write_bundle_json("PRIOR_WORK.json", prior)
        self.refresh()
        self.assertIn("PAPER.md disagrees with the generated 4E comparison table", self.cli("--check").stderr)

    def test_candidates_enter_no_arithmetic_span_or_comparison(self):
        self.write_candidate_review([])  # the no-receipt boundary, on an explicit fixture
        candidates = module.load_candidates(self.root, self.data)
        fixture = [dict(self.receipt("O09"), observation_id=r["id"], row_sha256=module.row_digest(r)) for r in candidates["records"]]
        text = json.dumps(module.results(self.data, self.sources, self.receipts + fixture))
        for row in candidates["records"]:
            self.assertNotIn('"' + row["id"] + '"', text)
        self.assertIn("Unknown comparison ID", self.cli("--compare", "C01", "O09").stderr)
        explained = json.loads(self.cli("--explain", "C01").stdout)
        self.assertEqual((explained["status"], explained["candidate"]["id"]), (module.CANDIDATE_STATUS, "C01"))

    def test_candidate_file_is_validated(self):
        cases = [(lambda d: d["records"][0].update(id="O09"), "Candidate IDs must be unique"),
                 (lambda d: d["records"][1].update(id="C01"), "Candidate IDs must be unique"),
                 (lambda d: d["sources"][0].update(url="http://example.org"), "HTTPS reference"),
                 (lambda d: d["sources"][0].update(original_sha256="0"), "HTTPS reference"),
                 (lambda d: d.update(status="awaiting review"), "enter no arithmetic"),
                 (lambda d: d["records"][0].update(superseded_by="C02"), "no supersession"),
                 (lambda d: d["records"][0].update(source_id="S01"), "Unknown source"),
                 (lambda d: d["known_unregistered"][0].update(source_id="S01"), "Malformed candidate known value"),
                 (lambda d: d["auxiliary_sources"].update(C01=["N99"]), "Auxiliary sources")]
        original = self.read_bundle_json("CANDIDATE_OBSERVATIONS.json")
        for change, message in cases:
            with self.subTest(message=message):
                doc = copy.deepcopy(original)
                change(doc)
                self.write_bundle_json("CANDIDATE_OBSERVATIONS.json", doc)
                self.refresh(candidates=False)
                self.assertIn(message, self.cli("--check").stderr)

    def test_candidate_ids_cannot_collide_with_a_ledger_id(self):
        self.alter(lambda d: next(r for r in d["records"] if r["id"] == "O26").update(id="C01"))
        self.refresh(candidates=False)
        self.assertIn("differ from ledger IDs: C01", self.cli("--check").stderr)

    def test_prior_work_file_is_validated(self):
        cases = [(lambda d: d["four_e_comparison"][3]["publisher_only"].remove("O09"), "allocate every registered observation exactly once"),
                 (lambda d: d["four_e_comparison"][0]["publisher_only"].append("O08"), "allocate every registered observation exactly once"),
                 (lambda d: d["four_e_comparison"][3]["checks"][0].update(four_e_value=600), "PRIOR_WORK.json check fails"),
                 (lambda d: d["four_e_comparison"][7]["checks"][0].update(four_e_high=1100), "PRIOR_WORK.json check fails"),
                 (lambda d: d["sources"][0].update(url="ftp://example.org"), "HTTPS reference"),
                 (lambda d: d["four_e_quality_filter"]["higher"].update(minimum=600), "Malformed 4E quality-filter tier"),
                 (lambda d: d["four_e_comparison"][1].update(four_e_locator="page 20"), "locate its evidence in P01"),
                 (lambda d: d["four_e_comparison"][2].update(ledger_shown=["O08"]), "Ledger observations shown"),
                 (lambda d: d["four_e_comparison"][4].pop("four_e_base_year"), "lacks: four_e_base_year")]
        original = self.read_bundle_json("PRIOR_WORK.json")
        for change, message in cases:
            with self.subTest(message=message):
                doc = copy.deepcopy(original)
                change(doc)
                self.write_bundle_json("PRIOR_WORK.json", doc)
                self.refresh()
                self.assertIn(message, self.cli("--check").stderr)

    def test_check_requires_the_candidate_and_prior_work_files(self):
        for name in ("CANDIDATE_OBSERVATIONS.json", "PRIOR_WORK.json"):
            with self.subTest(name=name):
                path, backup = self.root / name, self.parent / (name + ".bak")
                path.rename(backup)
                self.assertIn("unexpected or missing entries", self.cli("--check").stderr)
                backup.rename(path)

    CAPACITY_2030 = "Global / data_centre_capacity_demand / GW / 2030 / None"

    def candidate_doc(self):
        return self.read_bundle_json("CANDIDATE_OBSERVATIONS.json")

    def candidate_receipt(self, cid, verdict="supported", components=()):
        doc = self.candidate_doc()
        row = next(r for r in doc["records"] if r["id"] == cid)
        return {"candidate_id": cid, "row_sha256": module.row_digest(row),
                "candidate_source_list_sha256": module.catalogue_digest({s["id"]: s for s in doc["sources"]}),
                "verdict": verdict, "reviewer": "test fixture", "review_record_sha256": "0" * 64, "locator": "fixture",
                "components_short_of_supported": list(components), "components_unassessed_as_maker_conduct": [], "reason": "fixture"}

    def write_candidate_review(self, reviews):
        doc = self.read_bundle_json("CANDIDATE_SUPPORT_REVIEW.json")
        doc["reviews"] = reviews
        self.write_bundle_json("CANDIDATE_SUPPORT_REVIEW.json", doc)

    def loaded(self):
        data, sources, receipts = module.load(self.root)
        return data, sources, receipts, module.load_candidates(self.root, data)

    def candidate_results(self):
        return module.results(*self.loaded())

    def span_members(self, result, group):
        return next((s["observation_ids"] for s in result["recorded_value_spans"] if s["group"] == group), None)

    def unused_candidate_ids(self, count):
        """Candidate-style IDs absent from the candidate file and the ledger, so that a fixture never collides with a real candidate.
        The helper draws from C01 to C99 (the validator's pattern, C and two digits, also admits C00, which the helper leaves out);
        when fewer than count of them are free, the test fails here with that reason rather than reusing an ID or failing later on
        a short list."""
        taken = {r["id"] for r in self.candidate_doc()["records"]} | set(self.rows)
        free = [cid for cid in (f"C{n:02d}" for n in range(99, 0, -1)) if cid not in taken]
        if len(free) < count:
            self.fail(f"Free candidate IDs of C01 to C99: {len(free)}; this fixture needs {count}")
        return free[:count]

    @staticmethod
    def awaiting_sentence(ids):
        """The paper's sentence for candidates without a receipt, in candidate-file order, assembled here rather than by the
        reproducer's own text helpers."""
        names = ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]
        if len(ids) == 1:
            return f"Candidate {names} awaits an independent claim-support receipt and enters no arithmetic, span or comparison."
        return f"Candidates {names} await independent claim-support receipts and enter no arithmetic, span or comparison."

    def current_blocks(self):
        data, sources, receipts, candidates = self.loaded()
        return module.paper_blocks(data, sources, receipts, candidates, module.load_prior_work(self.root, data))

    def refresh_manifest(self):
        path = self.root / "REPRODUCTION.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"] = {n: hashlib.sha256((self.root / n).read_bytes()).hexdigest() for n in manifest["files"]}
        path.write_bytes(module.encoded(manifest))

    def refresh_with_candidates(self, paper_from=None):
        """Regenerate outputs with candidate admission and refresh the manifest; given the blocks from before a change, also replace
        each changed generated block in PAPER.md, so that only the change under test can remain."""
        data, sources, receipts, candidates = self.loaded()
        for name, payload in module.outputs(data, sources, receipts, candidates).items():
            (self.root / name).write_bytes(payload)
        if paper_from is not None:
            blocks, path = self.current_blocks(), self.root / "PAPER.md"
            paper = path.read_text(encoding="utf-8")
            for name, old in paper_from.items():
                if blocks[name] != old:
                    self.assertEqual(paper.count(old), 1, name)
                    paper = paper.replace(old, blocks[name])
            path.write_text(paper, encoding="utf-8")
        self.refresh_manifest()

    def test_bundle_receipts_bind_and_admit_every_candidate(self):
        """The shipped receipt file holds one current supported receipt per candidate, and RESULTS.json is computed with them."""
        data, sources, receipts, candidates = self.loaded()
        ids = sorted(r["id"] for r in candidates["records"])
        rows = {r["id"]: r for r in candidates["records"]}
        source_list = module.candidate_source_list_digest(candidates)
        shipped = self.read_bundle_json("CANDIDATE_SUPPORT_REVIEW.json")["reviews"]
        self.assertEqual(sorted(r["candidate_id"] for r in shipped), ids)
        for receipt in shipped:
            self.assertEqual((receipt["row_sha256"], receipt["candidate_source_list_sha256"]),
                             (module.row_digest(rows[receipt["candidate_id"]]), source_list))
        review = candidates[module.CANDIDATE_REVIEW_KEY]
        self.assertEqual({i: s["status"] for i, s in review.items()}, {i: "supported" for i in ids})
        with_candidates = module.results(data, sources, receipts, candidates)
        self.assertEqual(with_candidates["candidate_admission"]["admitted"], ids)
        self.assertNotEqual(with_candidates, module.results(data, sources, receipts))
        self.assertEqual(json.loads((self.root / "RESULTS.json").read_text(encoding="utf-8")), with_candidates)
        explained = json.loads(self.cli("--explain", ids[0]).stdout)
        self.assertEqual((explained["support_review"], explained["candidate_source_list_sha256"]), ("supported", source_list))

    def test_candidate_file_without_receipts_admits_no_candidate(self):
        """The no-receipt boundary on an explicit fixture: with the receipt file emptied, every candidate is unreviewed and the
        results equal those computed without candidates; once the outputs and the paper are regenerated, the package check
        passes, the stored RESULTS.json equals the results without candidates and the paper lists every candidate as awaiting
        a receipt."""
        blocks = self.current_blocks()
        self.write_candidate_review([])
        data, sources, receipts, candidates = self.loaded()
        review = candidates[module.CANDIDATE_REVIEW_KEY]
        self.assertEqual({i: s["status"] for i, s in review.items()}, {r["id"]: "unreviewed" for r in candidates["records"]})
        with_candidates = module.results(data, sources, receipts, candidates)
        self.assertEqual(with_candidates, module.results(data, sources, receipts))
        self.assertEqual(with_candidates["candidate_admission"]["admitted"], [])
        explained = json.loads(self.cli("--explain", "C02").stdout)
        self.assertEqual((explained["support_review"], explained["support_review_reason"]), ("unreviewed", "no receipt in CANDIDATE_SUPPORT_REVIEW.json"))
        self.assertEqual(explained["candidate_source_list_sha256"], module.candidate_source_list_digest(candidates))
        self.refresh_with_candidates(paper_from=blocks)
        result = self.cli("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read_bundle_json("RESULTS.json"), module.results(data, sources, receipts))
        self.assertIn(self.awaiting_sentence([r["id"] for r in candidates["records"]]), (self.root / "PAPER.md").read_text(encoding="utf-8"))

    def test_shipped_receipt_goes_stale_when_its_candidate_row_changes(self):
        """A shipped receipt binds the row it reviewed: an edit to that row withdraws the candidate from arithmetic, and the package
        check fails until the outputs and the paper are regenerated."""
        blocks = self.current_blocks()
        doc = self.candidate_doc()
        next(r for r in doc["records"] if r["id"] == "C02")["qualification"] += " Edited after review."
        self.write_bundle_json("CANDIDATE_OBSERVATIONS.json", doc)
        self.refresh_manifest()
        data, sources, receipts, candidates = self.loaded()
        self.assertEqual(candidates[module.CANDIDATE_REVIEW_KEY]["C02"]["status"], "review stale")
        self.assertNotIn("C02", module.results(data, sources, receipts, candidates)["candidate_admission"]["admitted"])
        self.assertIn("Generated output differs: RESULTS.json", self.cli("--check").stderr)
        self.refresh_with_candidates()
        self.assertIn("PAPER.md disagrees with the generated like-for-like table", self.cli("--check").stderr)
        self.refresh_with_candidates(paper_from=blocks)
        result = self.cli("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Candidate C02 has only receipts that no longer bind its current record and source list",
                      (self.root / "PAPER.md").read_text(encoding="utf-8"))

    def test_supported_candidate_receipt_admits_the_candidate_to_its_group(self):
        self.write_candidate_review([])  # start from no receipt, on an explicit fixture
        before = self.candidate_results()
        self.write_candidate_review([self.candidate_receipt("C01")])
        after = self.candidate_results()
        self.assertEqual(self.span_members(before, self.CAPACITY_2030), ["O09", "O21", "O24"])
        self.assertEqual(self.span_members(after, self.CAPACITY_2030), ["O09", "O21", "O24", "C01"])
        span = next(s for s in after["recorded_value_spans"] if s["group"] == self.CAPACITY_2030)
        self.assertEqual((span["n_observations"], span["n_publishers"], span["minimum_stated_bound"], span["maximum_stated_bound"]), (4, 3, 220, 490.7))
        group = next(c for c in after["like_for_like_comparison"]["comparison"] if c["group"] == self.CAPACITY_2030)
        self.assertIn("C01", group["like_for_like"]["observation_ids"])
        self.assertIn("C01", group["same_metric_unit_and_year"]["observation_ids"])
        self.assertEqual(after["candidate_admission"]["admitted"], ["C01"])
        for key in ("support_review", "comparisons", "observation_count", "superseded_observations"):
            self.assertEqual(after[key], before[key], key)
        explained = json.loads(self.cli("--explain", "C01").stdout)
        self.assertEqual((explained["support_review"], explained["status"]), ("supported", module.CANDIDATE_STATUS))
        compared = self.cli("--compare", "O24", "C01")
        self.assertEqual(compared.returncode, 0, compared.stderr)
        reasons = json.loads(compared.stdout)["reasons"]
        self.assertFalse([r for r in reasons if "support review" in r])
        self.assertIn("scenario is unresolved", reasons)

    def test_admitted_candidate_reaches_the_package_only_through_regenerated_outputs_and_paper(self):
        blocks = self.current_blocks()
        self.assertEqual(self.cli("--check").returncode, 0)
        self.write_candidate_review([self.candidate_receipt("C01")])
        self.refresh_manifest()
        self.assertIn("Generated output differs: RESULTS.json", self.cli("--check").stderr)
        self.refresh_with_candidates()
        self.assertIn("PAPER.md disagrees with the generated like-for-like table", self.cli("--check").stderr)
        self.refresh_with_candidates(paper_from=blocks)
        result = self.cli("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        paper = (self.root / "PAPER.md").read_text(encoding="utf-8")
        self.assertIn("Candidate C01 has a current supported claim-support receipt and enters arithmetic, spans and declared comparisons", paper)
        self.assertIn(self.awaiting_sentence([r["id"] for r in self.candidate_doc()["records"] if r["id"] != "C01"]), paper)

    def test_stale_candidate_row_digest_admits_nothing(self):
        receipt = self.candidate_receipt("C01")
        doc = self.candidate_doc()
        next(r for r in doc["records"] if r["id"] == "C01")["qualification"] += " Edited after review."
        self.write_bundle_json("CANDIDATE_OBSERVATIONS.json", doc)
        self.write_candidate_review([receipt])
        data, sources, receipts, candidates = self.loaded()
        self.assertEqual(candidates[module.CANDIDATE_REVIEW_KEY]["C01"]["status"], "review stale")
        result = module.results(data, sources, receipts, candidates)
        self.assertEqual(result["candidate_admission"]["admitted"], [])
        self.assertEqual(self.span_members(result, self.CAPACITY_2030), ["O09", "O21", "O24"])
        self.assertIn("Candidate C01 has only receipts that no longer bind its current record and source list",
                      module.candidate_status_text(candidates))
        self.assertIn("C01 is a candidate without a current supported receipt (review stale)", self.cli("--compare", "C01", "O24").stderr)

    def test_stale_candidate_source_list_digest_admits_nothing(self):
        receipt = self.candidate_receipt("C01")
        doc = self.candidate_doc()
        next(s for s in doc["sources"] if s["id"] == "N04")["coverage_limit"] += " Edited after review."
        self.write_bundle_json("CANDIDATE_OBSERVATIONS.json", doc)
        self.write_candidate_review([receipt])
        data, sources, receipts, candidates = self.loaded()
        self.assertEqual(module.row_digest(next(r for r in candidates["records"] if r["id"] == "C01")), receipt["row_sha256"])
        self.assertEqual(candidates[module.CANDIDATE_REVIEW_KEY]["C01"]["status"], "review stale")
        self.assertEqual(module.results(data, sources, receipts, candidates)["candidate_admission"]["admitted"], [])

    def test_candidate_verdict_short_of_supported_admits_nothing(self):
        for verdict in ("partly supported", "not supported", "contradicted", "unassessed"):
            with self.subTest(verdict=verdict):
                self.write_candidate_review([self.candidate_receipt("C01", verdict, [] if verdict == "unassessed" else ["geography"])])
                data, sources, receipts, candidates = self.loaded()
                self.assertEqual(candidates[module.CANDIDATE_REVIEW_KEY]["C01"]["status"], verdict)
                result = module.results(data, sources, receipts, candidates)
                self.assertEqual(result["candidate_admission"]["admitted"], [])
                self.assertNotIn('"C01"', json.dumps(result["recorded_value_spans"]) + json.dumps(result["like_for_like_comparison"]))
                self.assertIn(f"Candidate C01 is rated {verdict}", module.candidate_status_text(candidates))
                self.assertIn(f"C01 is a candidate without a current supported receipt ({verdict})", self.cli("--compare", "C01", "O24").stderr)
        self.write_candidate_review([self.candidate_receipt("C01", "partly supported", ["geography"])])
        self.assertIn("Candidate C01 is rated partly supported, short of supported in geography, and enters no arithmetic, span or comparison.",
                      module.candidate_status_text(self.loaded()[3]))

    def test_fixture_candidate_ids_fail_explicitly_when_too_few_are_free(self):
        doc = self.candidate_doc()
        taken = {r["id"] for r in doc["records"]}
        doc["records"] += [dict(copy.deepcopy(doc["records"][0]), id=f"C{n:02d}") for n in range(1, 100) if f"C{n:02d}" not in taken]
        self.write_bundle_json("CANDIDATE_OBSERVATIONS.json", doc)
        with self.assertRaisesRegex(AssertionError, "Free candidate IDs of C01 to C99: 0; this fixture needs 1"):
            self.unused_candidate_ids(1)
        doc["records"] = [r for r in doc["records"] if r["id"] != "C42"]
        self.write_bundle_json("CANDIDATE_OBSERVATIONS.json", doc)
        self.assertEqual(self.unused_candidate_ids(1), ["C42"])
        with self.assertRaisesRegex(AssertionError, "Free candidate IDs of C01 to C99: 1; this fixture needs 2"):
            self.unused_candidate_ids(2)

    def test_candidate_receipt_naming_an_unknown_candidate_fails(self):
        unknown = self.unused_candidate_ids(1)[0]
        self.write_candidate_review([dict(self.candidate_receipt("C01"), candidate_id=unknown)])
        with self.assertRaisesRegex(ValueError, "names an unknown candidate: " + unknown):
            module.load_candidates(self.root, self.data)
        self.refresh_manifest()
        self.assertIn("names an unknown candidate: " + unknown, self.cli("--check").stderr)

    def test_duplicate_current_candidate_receipts_fail_but_stale_history_is_ignored(self):
        current = self.candidate_receipt("C01")
        other = dict(current, verdict="partly supported", components_short_of_supported=["geography"])
        for reviews in ([current, dict(current)], [current, other], [other, current]):
            with self.subTest(verdicts=[r["verdict"] for r in reviews]):
                self.write_candidate_review(reviews)
                with self.assertRaisesRegex(ValueError, "More than one current candidate receipt: C01"):
                    module.load_candidates(self.root, self.data)
        self.refresh_manifest()
        self.assertIn("More than one current candidate receipt: C01", self.cli("--check").stderr)
        stale = dict(current, row_sha256="0" * 64, verdict="partly supported", components_short_of_supported=["geography"])
        for reviews in ([stale, current], [current, stale]):
            self.write_candidate_review(reviews)
            self.assertEqual(self.loaded()[3][module.CANDIDATE_REVIEW_KEY]["C01"]["status"], "supported")

    def test_malformed_candidate_receipt_file_fails(self):
        good = self.candidate_receipt("C01")
        cases = [(lambda d: d.pop("reviews"), "Malformed candidate support review file"),
                 (lambda d: d.update(reviews={}), "Malformed candidate support review file"),
                 (lambda d: d.pop("historical_reviews"), "Malformed candidate support review file"),
                 (lambda d: d.update(reviews=["C01"]), "Malformed candidate support review receipt"),
                 (lambda d: d.update(reviews=[dict(good, verdict="accepted")]), "Malformed candidate support review receipt"),
                 (lambda d: d.update(reviews=[{k: v for k, v in good.items() if k != "locator"}]), "Malformed candidate support review receipt"),
                 (lambda d: d.update(reviews=[dict(good, admitted=True)]), "Malformed candidate support review receipt"),
                 (lambda d: d.update(reviews=[dict(good, row_sha256="0")]), "digests must be SHA-256 hex"),
                 (lambda d: d.update(reviews=[dict(good, reason=" ")]), "lacks: reason"),
                 (lambda d: d.update(reviews=[dict(good, components_short_of_supported="geography")]), "components_short_of_supported"),
                 (lambda d: d.update(reviews=[dict(good, components_short_of_supported=["geography"])]), "cannot list components short of support")]
        original = self.read_bundle_json("CANDIDATE_SUPPORT_REVIEW.json")
        for change, message in cases:
            with self.subTest(message=message):
                doc = copy.deepcopy(original)
                change(doc)
                self.write_bundle_json("CANDIDATE_SUPPORT_REVIEW.json", doc)
                with self.assertRaisesRegex(ValueError, message):
                    module.load_candidates(self.root, self.data)
        self.write_bundle_json("CANDIDATE_SUPPORT_REVIEW.json", [])
        self.refresh_manifest()
        self.assertIn("Malformed candidate support review file", self.cli("--check").stderr)
        (self.root / "CANDIDATE_SUPPORT_REVIEW.json").write_text('{"reviews": [], "reviews": [], "historical_reviews": []}\n', encoding="utf-8")
        self.refresh_manifest()
        self.assertIn("Duplicate JSON key", self.cli("--check").stderr)

    def test_check_requires_the_candidate_receipt_file(self):
        path, backup = self.root / "CANDIDATE_SUPPORT_REVIEW.json", self.parent / "CANDIDATE_SUPPORT_REVIEW.json.bak"
        path.rename(backup)
        self.assertIn("unexpected or missing entries", self.cli("--check").stderr)
        backup.rename(path)
        manifest = json.loads((self.root / "REPRODUCTION.json").read_text(encoding="utf-8"))
        manifest["files"].pop("CANDIDATE_SUPPORT_REVIEW.json")
        (self.root / "REPRODUCTION.json").write_bytes(module.encoded(manifest))
        self.assertIn("exact declared package", self.cli("--check").stderr)

    def test_declared_comparison_naming_a_candidate_follows_the_ledger_rules(self):
        fixture, unknown = self.unused_candidate_ids(2)
        doc = self.candidate_doc()
        doc["records"].append(dict(copy.deepcopy(self.rows["O04"]), id=fixture, forecaster="Fixture publisher", source_id="N01", state="added",
                                   comparison_family="", superseded_by="", low=500, high=500, point=500))
        self.write_bundle_json("CANDIDATE_OBSERVATIONS.json", doc)
        self.alter(lambda d: d["comparisons"].append({"id": "R90", "old": "O04", "new": fixture, "interpretation": "Fixture comparison with a candidate."}))
        data, sources, receipts, candidates = self.loaded()
        refused = next(c for c in module.results(data, sources, receipts, candidates)["comparisons"] if c["id"] == "R90")
        self.assertEqual(refused["status"], "not_comparable")
        self.assertIn(fixture + " support review: unreviewed", refused["reasons"])
        with self.assertRaisesRegex(ValueError, "the candidate records are required: " + fixture):
            module.results(data, sources, receipts)
        self.write_candidate_review([self.candidate_receipt(fixture)])
        computed = next(c for c in self.candidate_results()["comparisons"] if c["id"] == "R90")
        self.assertEqual((computed["status"], computed["numerator"], computed["denominator"], computed["n_observations"]),
                         ("conditional_arithmetic", 36, 464, 2))
        self.alter(lambda d: d["comparisons"][-1].update(new=unknown))
        with self.assertRaisesRegex(ValueError, "Comparison references an unknown observation"):
            module.load(self.root)


if __name__ == "__main__":
    unittest.main()
