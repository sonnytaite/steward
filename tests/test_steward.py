"""Tests for rails/steward.py — the guarantees the handbook promises, executable.

  shield        frontmatter marker shields the whole page; a body marker line shields
                everything after it; a marker inside inline code or a link does not
  stale         old + load-bearing pages surface; young or unlinked ones do not
  orphans       pages nobody links to surface
  broken        wikilinks to missing pages surface
  open pages    connection pages whose status is not 'actioned' surface
  decisions     'decision' headings in recently touched research files are extracted
  ordinary      the ordinary-stream sample is deterministic per date
  dispose/log   verdicts and events are append-only rows
  wake          the wake bundle is bounded

stdlib only (unittest). Run: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("steward", HERE.parent / "rails" / "steward.py")
steward = importlib.util.module_from_spec(spec)
spec.loader.exec_module(steward)  # type: ignore[union-attr]

TODAY = dt.date(2026, 9, 20)


def page(title, updated, related=(), body="", tags=("x",), type_="concept", confidence="high", created="2026-04-01"):
    rel = ", ".join(related)
    tg = ", ".join(tags)
    return f"""---
title: "{title}"
type: {type_}
related: [{rel}]
created: {created}
updated: {updated}
confidence: {confidence}
tags: [{tg}]
---

# {title}

{body}
"""


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.vault = root / "vault"
        wiki = self.vault / "wiki"
        for d in ("concepts", "projects", "themes"):
            (wiki / d).mkdir(parents=True)
        # hub: old, linked by five pages -> stale and load-bearing
        (wiki / "concepts" / "hub.md").write_text(page("Hub", "2026-04-01"))
        for i in range(5):
            (wiki / "projects" / f"p{i}.md").write_text(page(f"P{i}", "2026-09-15", related=["concepts/hub"], body="see [[concepts/hub]] and [[concepts/missing-page]]" if i == 0 else "", type_="project"))
        # orphan
        (wiki / "concepts" / "orphan.md").write_text(page("Orphan", "2026-09-01"))
        # body marker: links after the marker must not count
        (wiki / "concepts" / "partial.md").write_text(page("Partial", "2026-09-01", body="public part links [[concepts/orphan-not]].\n\n**Do-not-syndicate. Private.**\n\nsecret part links [[concepts/hub]] and [[concepts/orphan]]"))
        # inline-code mention must not shield
        (wiki / "concepts" / "describes.md").write_text(page("Describes", "2026-09-01", body="the `do-not-syndicate` shield is a rail"))
        # frontmatter tag shield
        (wiki / "concepts" / "sealed.md").write_text(page("Sealed", "2026-09-01", tags=("private", "do-not-syndicate"), body="links [[concepts/hub]]"))
        # open connection page
        (wiki / "themes" / "t1.md").write_text(page("T1", "2026-09-20", type_="connection", body="**Status.** Noted 2026-09-20. Not yet actioned in x."))
        (wiki / "themes" / "t2.md").write_text(page("T2", "2026-09-20", type_="connection", body="**Status.** Actioned 2026-09-21."))
        # research repo with a decision heading
        self.research = root / "research"
        (self.research / "proj").mkdir(parents=True)
        (self.research / "proj" / "README.md").write_text("# Proj\n\n## Decisions for Sonny\n\n1. Do A or B?\n2. Ship now?\n\n## Decisions already made (do not relitigate)\n\n1. settled\n\n## Other\n\n- not a decision\n")
        (wiki / "projects" / "esc.md").write_text(page("Esc", "2026-09-15", body="escaped link [[concepts/hub\\]] here", type_="project"))
        self.cfg = dict(steward.DEFAULT_CONFIG)
        self.cfg.update({"vault": str(self.vault), "research": str(self.research), "kete_aronui": str(root / "nope")})

    def tearDown(self):
        self.tmp.cleanup()

    def facts(self):
        return steward.build_facts(self.cfg, TODAY)


class ShieldTests(Fixture):
    def test_frontmatter_marker_shields_whole_page(self):
        pages = steward.load_pages(self.cfg)
        self.assertEqual(pages["concepts/sealed"]["shield"], "full")
        self.assertEqual(pages["concepts/sealed"]["visible"], "")
        self.assertNotIn("concepts/hub", pages["concepts/sealed"]["links"])

    def test_body_marker_truncates_from_that_line(self):
        pages = steward.load_pages(self.cfg)
        pg = pages["concepts/partial"]
        self.assertEqual(pg["shield"], "partial")
        self.assertIn("public part", pg["visible"])
        self.assertNotIn("secret part", pg["visible"])
        self.assertNotIn("concepts/orphan", pg["links"])

    def test_inline_code_mention_does_not_shield(self):
        pages = steward.load_pages(self.cfg)
        self.assertIsNone(pages["concepts/describes"]["shield"])

    def test_shielded_text_never_in_facts_markdown(self):
        md = steward.facts_markdown(self.facts())
        self.assertNotIn("secret part", md)


class FactsTests(Fixture):
    def test_stale_load_bearing(self):
        f = self.facts()
        self.assertEqual([r["path"] for r in f["stale_load_bearing"]], ["concepts/hub"])
        self.assertGreaterEqual(f["stale_load_bearing"][0]["inbound"], 5)

    def test_orphan(self):
        paths = {r["path"] for r in self.facts()["orphans"]}
        self.assertIn("concepts/orphan", paths)
        self.assertNotIn("concepts/hub", paths)

    def test_broken_link(self):
        targets = {r["target"] for r in self.facts()["broken_links"]}
        self.assertIn("concepts/missing-page", targets)

    def test_open_connection_pages(self):
        paths = {r["path"] for r in self.facts()["open_connections"]}
        self.assertIn("themes/t1", paths)
        self.assertNotIn("themes/t2", paths)

    def test_research_decisions_extracted(self):
        d = self.facts()["research_decisions"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["items"], ["Do A or B?", "Ship now?"])

    def test_ordinary_sample_deterministic(self):
        a = self.facts()["ordinary_sample"]
        b = steward.build_facts(self.cfg, TODAY)["ordinary_sample"]
        self.assertEqual(a, b)
        self.assertLessEqual(len(a), self.cfg["ordinary_sample"])
        self.assertNotIn("concepts/sealed", [r["path"] for r in a])

    def test_escaped_wikilink_is_not_broken(self):
        f = self.facts()
        self.assertNotIn("concepts/hub\\", {r["target"] for r in f["broken_links"]})
        self.assertIn("concepts/hub", steward.load_pages(self.cfg)["projects/esc"]["links"])

    def test_link_inside_inline_code_is_not_a_link(self):
        (self.vault / "wiki" / "concepts" / "code.md").write_text(page("Code", "2026-09-15", body="prose about `[[wiki-links]]` syntax"))
        self.assertNotIn("wiki-links", {r["target"] for r in self.facts()["broken_links"]})

    def test_settled_decisions_skipped(self):
        heads = [d["heading"] for d in self.facts()["research_decisions"]]
        self.assertEqual(heads, ["Decisions for Sonny"])

    def test_bounds_present(self):
        self.assertEqual(self.facts()["bounds"]["max_items"], 5)


class StateTests(Fixture):
    def run_cli(self, *argv):
        buf = io.StringIO()
        cfgp = self.vault / "steward.config.json"
        cfgp.write_text(json.dumps(self.cfg))
        with redirect_stdout(buf):
            steward.main(["--config", str(cfgp), *argv])
        return buf.getvalue()

    def test_dispose_appends_rows(self):
        self.run_cli("dispose", "--brief", "2026-09-20", "--item", "1", "--verdict", "keep", "--note", "fine")
        self.run_cli("dispose", "--brief", "2026-09-20", "--item", "2", "--verdict", "drop")
        rows = (self.vault / "surfaces" / "steward" / "dispositions.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 2)
        self.assertEqual(json.loads(rows[0])["verdict"], "keep")

    def test_dispose_rejects_bad_verdict(self):
        with self.assertRaises(SystemExit):
            self.run_cli("dispose", "--brief", "2026-09-20", "--item", "1", "--verdict", "maybe")

    def test_log_appends(self):
        self.run_cli("log", "--event", "brief", "--detail", "first")
        rows = (self.vault / "surfaces" / "steward" / "log.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(rows[0])["event"], "brief")

    def test_wake_is_bounded_and_reports_pending(self):
        sd = self.vault / "surfaces" / "steward" / "briefs"
        sd.mkdir(parents=True)
        (sd / "2026-09-20-brief.md").write_text("# brief\n\n### 1. First thing\n\n### 2. Second thing\n")
        self.run_cli("dispose", "--brief", "2026-09-20", "--item", "1", "--verdict", "act")
        out = self.run_cli("wake")
        self.assertIn("2. Second thing", out)
        self.assertNotIn("1. First thing\n", out.split("Awaiting")[-1])
        self.cfg["wake_char_limit"] = 400
        out = self.run_cli("wake")
        self.assertLessEqual(len(out), 402)
        self.assertIn("wake truncated", out)

    def test_wake_flags_in_flight_brief(self):
        sd = self.vault / "surfaces" / "steward" / "briefs"; sd.mkdir(parents=True)
        (sd / "2026-09-21-brief.md").write_text("# What needs you\n\n> steward brief · 2 items · status: awaiting-disposition\n\n### 1. A\n\n### 2. B\n")
        out = self.run_cli("wake")
        self.assertIn("IN-FLIGHT", out)
        (sd / "2026-09-21-brief.md").write_text("# What needs you\n\n> steward brief · 2 items · status: disposed (2 act)\n\n### 1. A\n\n### 2. B\n")
        self.assertNotIn("IN-FLIGHT", self.run_cli("wake"))

    def test_brief_save_writes_facts_files(self):
        self.run_cli("brief", "--save", "--date", "2026-09-20")
        b = self.vault / "surfaces" / "steward" / "briefs"
        self.assertTrue((b / "2026-09-20-facts.json").exists())
        self.assertTrue((b / "2026-09-20-facts.md").exists())


class ConciergeTests(Fixture):
    def _mod(self):
        spec = importlib.util.spec_from_file_location("concierge", HERE.parent / "rails" / "concierge.py")
        m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

    def test_note_then_drift(self):
        m = self._mod(); sd = self.vault / "surfaces" / "steward" / "concierge"; sd.mkdir(parents=True)
        (sd / "registry.json").write_text(json.dumps({"entries": [
            {"id": "a", "is_agent": True, "last_commit": "2026-09-15"},
            {"id": "b", "is_agent": True, "last_commit": "2026-07-01"},
            {"id": "c", "is_agent": False, "last_commit": "2026-09-15"}]}))
        (sd / "overlay.json").write_text(json.dumps({"a": {"updated": "2026-09-01", "next": "x"}, "b": {"updated": "2026-09-10", "next": "ship"}}))
        d = {x["id"]: x["kind"] for x in m.compute_drift(self.cfg, TODAY)}
        self.assertEqual(d, {"a": "stale-record", "b": "idle-with-next"})

    def test_dashboards_curated_list_renders_static(self):
        m = self._mod()
        ov = {"a": {"stage": "harness"}, "_dashboards": [
            {"kind": "dashboard", "name": "Thing <x>", "url": "http://127.0.0.1:9", "repo": str(self.vault / "nope"), "start_cwd": "~/p", "start_cmd": "run it"},
            {"kind": "dev", "name": "dev1", "url": "http://localhost:3000", "start_cwd": "~/d", "start_cmd": "npm run dev"}]}
        self.assertEqual(list(m.agent_overlay(ov)), ["a"])
        d = m.dashboards(ov)
        self.assertEqual(d[0]["last_touched"], "")
        h = m.render_dashboards(d)
        self.assertIn("Thing &lt;x&gt;", h); self.assertIn("cd ~/p &amp;&amp; run it", h); self.assertIn('data-probe="1"', h); self.assertIn("Dev servers", h)
        self.assertEqual(m.render_dashboards([]), "")

    def test_artefact_rules_first_match_wins(self):
        m = self._mod(); f = {"title": "", "chartlib": "", "canvas": False, "svg": False}
        c = lambda rel, facts=f, md={}: m.classify(rel, facts, md, "research/", "second-brain/articles/")[0]
        self.assertEqual(c("research/x/atlas-map.html"), "research")  # path beats the visualisation words
        self.assertEqual(c("second-brain/articles/brief.html"), "articles")
        self.assertEqual(c("second-brain/zara-pack/README.html"), "articles")
        self.assertEqual(c("repo/notes.html", f, {"type": "brief"}), "articles")
        self.assertEqual(c("repo/views/board.html"), "visualisations")
        self.assertEqual(c("repo/dashboard_run_1.html"), "visualisations")
        self.assertEqual(c("repo/page.html", dict(f, svg=True)), "visualisations")
        self.assertEqual(c("repo/page.html", dict(f, chartlib="chart.js")), "visualisations")
        self.assertEqual(c("repo/mockup.html"), "unfiled")

    def test_artefact_exclusions(self):
        m = self._mod()
        for rel in ("second-brain/surfaces/steward/concierge/console.html", "steward/templates/console.html", "org-atlas/static/index.html",
                    "estate-console/static/index.html", "research/a/map_template.html", "x/thought piece v1 backup.html", "pia-plus/ui/index.html"):
            self.assertTrue(m.excluded(rel), rel)
        for rel in ("research/a/readme.html", "worx-ai-triage/views/board.html", "research/b/sources.html"):
            self.assertEqual(m.excluded(rel), "", rel)
        self.assertIn("node_modules", m.ART_PRUNE_DIRS); self.assertIn("dify-src", m.ART_PRUNE_DIRS)

    def test_artefacts_crawl_overlay_and_static_render(self):
        m = self._mod(); home = Path(tempfile.mkdtemp()); self.cfg["concierge_artefact_base"] = str(home)
        research = home / "research"; vault = home / "second-brain"
        (research / "proj").mkdir(parents=True); (vault / "articles").mkdir(parents=True); (home / "app" / "views").mkdir(parents=True)
        self.cfg["research"] = str(research); self.cfg["vault"] = str(vault)
        (research / "proj" / "README.md").write_text("# Proj\n\n**Status:** Active (kickoff)\n")
        (research / "proj" / "readme.html").write_text("<html><title>Proj</title><p>A research page that says what it is in one line.</p></html>")
        (research / "proj" / "map_template.html").write_text("<html><title>T</title></html>")
        (vault / "articles" / "idea.html").write_text("<html><title>Idea</title></html>")
        (vault / "articles" / "idea.md").write_text("---\ntitle: The Idea\ntype: article\ncreated: 2026-06-21\ndek: One line.\n---\n# The Idea\n")
        (vault / "articles" / "published").mkdir(); (vault / "articles" / "published" / "idea.pdf").write_bytes(b"%PDF-1.4 /Title (The Idea)")
        (home / "app" / "views" / "board.html").write_text("<html><title>Build board</title><svg></svg></html>")
        (home / "app" / "loose.html").write_text("<html><title>Loose</title></html>")
        (home / "app" / "frag.html").write_text("<div>partial</div>")
        for d in (research, vault, home / "app"): subprocess.run(["git", "init", "-q", str(d)], check=True)
        subprocess.run(["git", "-C", str(research), "add", "."], check=True)
        subprocess.run(["git", "-C", str(research), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"], check=True)
        art = m.crawl_artefacts(self.cfg, [str(home / "app")])
        cats = {Path(i["rel"]).name: i["category"] for i in art["items"]}
        self.assertEqual(cats, {"readme.html": "research", "idea.html": "articles", "board.html": "visualisations", "loose.html": "unfiled"})
        idea = next(i for i in art["items"] if i["rel"].endswith("idea.html"))
        self.assertEqual((idea["title"], idea["date"], idea["blurb"]), ("The Idea", "2026-06-21", "One line."))
        self.assertTrue(idea["pdf"].endswith("published/idea.pdf"))
        rd = next(i for i in art["items"] if i["rel"].endswith("readme.html"))
        self.assertTrue(rd["committed"] and rd["last_hash"])  # git index read (the marker survives splitlines)
        self.assertEqual(art["research_projects"]["proj"]["status"], "Active (kickoff)")
        self.assertEqual({Path(x["path"]).name: x["reason"] for x in art["excluded"]}, {"map_template.html": "template file", "frag.html": "HTML fragment (no html, body or title)"})
        home_s = str(Path("~").expanduser()); key = next(i["path"] for i in art["items"] if i["rel"].endswith("loose.html")); key = "~" + key[len(home_s):] if key.startswith(home_s) else key
        v = m.artefacts_view(art, {"_artefacts": {key: {"category": "visualisations", "why": "because <I said>", "by": "sonny"}}})
        loose = next(i for i in v["items"] if i["rel"].endswith("loose.html"))
        self.assertEqual((loose["category"], loose["rule"]), ("visualisations", "overlay"))
        h = m.render_artefacts(v)
        for sid in ('id="research"', 'id="articles"', 'id="visualisations"', 'id="unfiled"'): self.assertIn(sid, h)
        self.assertIn("because &lt;I said&gt;", h); self.assertIn('hidden>', h)  # filter boxes stay hidden without scripts
        self.assertIn(">PDF</a>", h); self.assertIn("Unfiled</b> <span class=\"muted acount\" data-total=\"0\">(0)", h)

    def test_brief_facts_carry_drift(self):
        self.test_note_then_drift()
        self.assertIn("registry_drift", steward.build_facts(self.cfg, TODAY))


if __name__ == "__main__":
    unittest.main()
