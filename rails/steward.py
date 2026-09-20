#!/usr/bin/env python3
"""steward rails — the deterministic half of the steward.

The steward is one strong model with memory that watches a second brain for decay
and brings its owner the next thing. Everything that can be computed without
judgement is computed here, in stdlib Python, so the model spends its tokens on
judgement and the guarantees live in code:

  brief          facts for a "what needs you" brief (stale load-bearing pages,
                 orphans, broken links, open connection pages, waiting candidates,
                 open decisions in the research repo, what moved in git, an
                 ordinary-stream sample, recent additions, prior dispositions)
  wake           a bounded wake bundle (identity, last brief, pending verdicts, log)
  dispose        append a keep / act / drop verdict for a brief item (append-only)
  log            append a session event (append-only)
  shield-audit   which pages the shield covers, and how (frontmatter vs body marker)

Shield rule (exact, not substring-over-everything): a marker in the frontmatter
shields the whole page; a marker line in the body shields everything from that
line on. Shielded text never enters a brief, a wake bundle, or a convening.

stdlib only. Run tests:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_CONFIG = {
    "vault": "~/Projects/second-brain",
    "research": "~/Projects/research",
    "wiki_dir": "wiki",
    "surface_state_dir": "surfaces",
    "state_dir": "surfaces/steward",
    "shield_markers": ["do-not-syndicate", "do not syndicate"],
    "stale_days": 60,
    "load_bearing_inbound": 5,
    "decision_window_days": 30,
    "git_window_days": 7,
    "recent_days": 14,
    "ordinary_sample": 2,
    "ordinary_min_age_days": 30,
    "max_items": 5,
    "wake_char_limit": 3000,
    "kete_aronui": "~/claudecode/kete-aronui",
}

LINK_RE = re.compile(r"\[\[([^\]|#\\]+)(?:[#|][^\]]*)?\\?\]\]")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


# ----------------------------------------------------------------------------- config

def load_config(path: str | None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    candidates = []
    if path:
        candidates.append(Path(path))
    if os.environ.get("STEWARD_CONFIG"):
        candidates.append(Path(os.environ["STEWARD_CONFIG"]))
    candidates.append(Path(__file__).resolve().parent.parent / "steward.config.json")
    candidates.append(Path("~/.config/steward/steward.config.json").expanduser())
    for c in candidates:
        if c.exists():
            cfg.update(json.loads(c.read_text(encoding="utf-8")))
            cfg["_config_path"] = str(c)
            break
    for k in ("vault", "research", "kete_aronui"):
        cfg[k] = str(Path(cfg[k]).expanduser())
    return cfg


def state_dir(cfg: dict) -> Path:
    p = Path(cfg["vault"]) / cfg["state_dir"]
    p.mkdir(parents=True, exist_ok=True)
    (p / "briefs").mkdir(exist_ok=True)
    return p


# ----------------------------------------------------------------------------- pages

def parse_frontmatter(text: str) -> tuple[dict, str, str]:
    """Return (frontmatter dict, frontmatter raw text, body)."""
    if not text.startswith("---"):
        return {}, "", text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, "", text
    raw = text[3:end]
    body = text[end + 4:]
    fm: dict = {}
    for line in raw.splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if v.startswith("[") and v.endswith("]"):
            fm[k] = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",") if x.strip()]
        else:
            fm[k] = v.strip('"').strip("'")
    return fm, raw, body


def shield_page(fm: dict, raw_fm: str, body: str, markers: list[str]) -> tuple[str | None, str]:
    """Apply the shield rule. Returns (mode, visible_body). mode: None | 'full' | 'partial'."""
    low_markers = [m.lower() for m in markers]
    fm_text = raw_fm.lower()
    tags = [t.lower() for t in fm.get("tags", [])] if isinstance(fm.get("tags"), list) else []
    if any(m in fm_text for m in low_markers) or any(m in t for t in tags for m in low_markers):
        return "full", ""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        low = line.lower()
        # a marker inside inline code or a link target describes the shield, it does not invoke it
        stripped = re.sub(r"`[^`]*`", "", low)
        stripped = re.sub(r"\[\[[^\]]*\]\]", "", stripped)
        if any(m in stripped for m in low_markers) and not stripped.lstrip().startswith(("- ", "* ", "> ")):
            return "partial", "\n".join(lines[:i])
    return None, body


def parse_date(s: str | None) -> dt.date | None:
    if not s:
        return None
    m = DATE_RE.search(str(s))
    return dt.date.fromisoformat(m.group(1)) if m else None


def load_pages(cfg: dict) -> dict:
    wiki = Path(cfg["vault"]) / cfg["wiki_dir"]
    pages: dict = {}
    for f in sorted(wiki.rglob("*.md")):
        rel = f.relative_to(wiki).with_suffix("").as_posix()
        text = f.read_text(encoding="utf-8", errors="replace")
        fm, raw, body = parse_frontmatter(text)
        mode, visible = shield_page(fm, raw, body, cfg["shield_markers"])
        related = fm.get("related", []) if isinstance(fm.get("related"), list) else []
        links = set(related) | set(LINK_RE.findall(re.sub(r"`[^`\n]*`", "", visible)))
        links.discard(rel)
        pages[rel] = {
            "path": rel,
            "category": rel.split("/")[0] if "/" in rel else "",
            "title": fm.get("title", rel),
            "type": fm.get("type", ""),
            "updated": parse_date(fm.get("updated")),
            "created": parse_date(fm.get("created")),
            "confidence": fm.get("confidence", ""),
            "tags": fm.get("tags", []) if isinstance(fm.get("tags"), list) else [],
            "related": related,
            "links": sorted(links),
            "shield": mode,
            "visible": visible,
            "words": len(visible.split()),
        }
    return pages


def inbound_counts(pages: dict) -> dict:
    inbound = {p: 0 for p in pages}
    for p in pages.values():
        for t in p["links"]:
            if t in inbound:
                inbound[t] += 1
    return inbound


def status_line(page: dict) -> str:
    m = re.search(r"^\*\*Status\.?\*\*\s*(.*)$", page["visible"], flags=re.M)
    return m.group(1).strip() if m else ""


# ----------------------------------------------------------------------------- facts

def git_activity(repo: str, days: int) -> dict | None:
    if not (Path(repo) / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", repo, "log", f"--since={days} days ago", "--pretty=%ad %s", "--date=short"],
            capture_output=True, text=True, timeout=20, check=False,
        ).stdout.strip().splitlines()
    except Exception:  # noqa: BLE001
        return None
    return {"repo": repo, "commits": len(out), "subjects": out[:10]}


def research_decisions(cfg: dict, today: dt.date) -> list[dict]:
    root = Path(cfg["research"])
    if not root.exists():
        return []
    cutoff = (dt.datetime.combine(today, dt.time()) - dt.timedelta(days=cfg["decision_window_days"])).timestamp()
    found = []
    for f in root.rglob("*.md"):
        if any(part in (".git", "node_modules") for part in f.parts):
            continue
        try:
            if f.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        for i, line in enumerate(lines):
            low_h = line.lower()
            if line.startswith("#") and "decision" in low_h:
                settled = ("already" in low_h or "made" in low_h or "relitigate" in low_h) and "open" not in low_h
                if settled:
                    continue
                items = []
                for nxt in lines[i + 1:]:
                    if nxt.startswith("#"):
                        break
                    s = nxt.strip()
                    if re.match(r"^(\d+[.)]|[-*])\s+", s):
                        items.append(re.sub(r"^(\d+[.)]|[-*])\s+", "", s)[:220])
                    if len(items) >= 6:
                        break
                if items:
                    found.append({"file": str(f.relative_to(root)), "heading": line.strip("# ").strip(), "items": items,
                                  "mtime": dt.date.fromtimestamp(f.stat().st_mtime).isoformat()})
    found.sort(key=lambda d: d["mtime"], reverse=True)
    return found[:12]


def prior_dispositions(sd: Path) -> dict:
    tally: dict = {}
    rows = []
    f = sd / "dispositions.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(r)
            tally[r.get("verdict", "?")] = tally.get(r.get("verdict", "?"), 0) + 1
    return {"tally": tally, "rows": rows}


def brief_items_in(brief_md: str) -> list[str]:
    return re.findall(r"^###\s+\d+[.)]?\s*(.*)$", brief_md, flags=re.M)


def pending_verdicts(sd: Path) -> dict | None:
    briefs = sorted((sd / "briefs").glob("*-brief.md"))
    if not briefs:
        return None
    last = briefs[-1]
    date = last.name.split("-brief")[0]
    items = brief_items_in(last.read_text(encoding="utf-8"))
    disp = prior_dispositions(sd)["rows"]
    done = {int(r["item"]) for r in disp if r.get("brief") == date and str(r.get("item", "")).isdigit()}
    pend = [(i + 1, t) for i, t in enumerate(items) if (i + 1) not in done]
    return {"brief": date, "items": items, "pending": pend}


def _registry_drift(cfg: dict, today: dt.date) -> list:
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("concierge", Path(__file__).resolve().parent / "concierge.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod.compute_drift(cfg, today)[:12]
    except Exception:  # noqa: BLE001
        return []


def build_facts(cfg: dict, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    pages = load_pages(cfg)
    inbound = inbound_counts(pages)
    sd = state_dir(cfg)
    stale_cut = today - dt.timedelta(days=cfg["stale_days"])
    recent_cut = today - dt.timedelta(days=cfg["recent_days"])
    ordinary_cut = today - dt.timedelta(days=cfg["ordinary_min_age_days"])

    stale = [
        {"path": p, "title": pg["title"], "updated": pg["updated"].isoformat(), "inbound": inbound[p], "confidence": pg["confidence"]}
        for p, pg in pages.items()
        if pg["updated"] and pg["updated"] < stale_cut and inbound[p] >= cfg["load_bearing_inbound"] and pg["shield"] != "full"
    ]
    stale.sort(key=lambda d: (-d["inbound"], d["updated"]))

    orphans = [
        {"path": p, "title": pg["title"], "updated": pg["updated"].isoformat() if pg["updated"] else None}
        for p, pg in pages.items()
        if inbound[p] == 0 and pg["type"] not in ("overview", "index") and p.split("/")[-1] not in ("index", "log", "overview")
    ]

    broken: dict = {}
    for p, pg in pages.items():
        for t in pg["links"]:
            if t not in pages and not t.startswith(("http", "~", "/")) and t not in ("CLAUDE.md",):
                broken.setdefault(t, []).append(p)
    broken_list = sorted(({"target": t, "from": v[:5], "count": len(v)} for t, v in broken.items()), key=lambda d: -d["count"])[:12]

    open_conn = []
    for p, pg in pages.items():
        if pg["category"] == "themes" or pg["type"] == "connection":
            st = status_line(pg)
            low = st.lower()
            if not st or "actioned" not in low or "not yet" in low or "not resolved" in low or "flagged" in low:
                open_conn.append({"path": p, "title": pg["title"], "status": st[:200]})

    inbox = Path(cfg["vault"]) / cfg["surface_state_dir"] / "_inbox"
    waiting = sorted(f.name for f in inbox.glob("*.md")) if inbox.exists() else []

    recent = [
        {"path": p, "title": pg["title"], "created": pg["created"].isoformat() if pg["created"] else None, "updated": pg["updated"].isoformat() if pg["updated"] else None}
        for p, pg in pages.items()
        if (pg["created"] and pg["created"] >= recent_cut) or (pg["updated"] and pg["updated"] >= today - dt.timedelta(days=7))
    ]
    recent.sort(key=lambda d: (d["updated"] or ""), reverse=True)

    pool = [p for p, pg in pages.items() if pg["confidence"] == "high" and pg["updated"] and pg["updated"] < ordinary_cut and pg["shield"] != "full" and pg["category"] in ("concepts", "projects")]
    rng = random.Random(today.isoformat())
    sample = sorted(rng.sample(pool, min(cfg["ordinary_sample"], len(pool)))) if pool else []
    ordinary = [{"path": p, "title": pages[p]["title"], "updated": pages[p]["updated"].isoformat(), "inbound": inbound[p]} for p in sample]

    shielded = {"full": [p for p, pg in pages.items() if pg["shield"] == "full"], "partial": [p for p, pg in pages.items() if pg["shield"] == "partial"]}

    kete = Path(cfg["kete_aronui"])
    facts = {
        "date": today.isoformat(),
        "vault": cfg["vault"],
        "research": cfg["research"],
        "pages": len(pages),
        "shielded": shielded,
        "stale_load_bearing": stale[:10],
        "orphans": orphans[:15],
        "broken_links": broken_list,
        "open_connections": open_conn,
        "waiting_candidates": waiting,
        "research_decisions": research_decisions(cfg, today),
        "git": {"vault": git_activity(cfg["vault"], cfg["git_window_days"]), "research": git_activity(cfg["research"], cfg["git_window_days"])},
        "recent": recent[:15],
        "ordinary_sample": ordinary,
        "prior": {"dispositions": prior_dispositions(sd)["tally"], "pending": pending_verdicts(sd)},
        "kete_aronui": {"path": str(kete), "present": kete.exists()},
        "registry_drift": _registry_drift(cfg, today),
        "bounds": {"max_items": cfg["max_items"], "read_budget_files": 12, "passes": 1},
    }
    return facts


def facts_markdown(f: dict) -> str:
    out = [f"# Steward facts — {f['date']}", "",
           f"Vault {f['vault']} · {f['pages']} pages · shielded full {len(f['shielded']['full'])}, partial {len(f['shielded']['partial'])}",
           f"Research {f['research']} · kete-aronui present: {f['kete_aronui']['present']}", ""]
    def sec(title, rows, fmt):
        out.append(f"## {title} ({len(rows)})")
        out.extend(fmt(r) for r in rows) if rows else out.append("- none")
        out.append("")
    sec("Stale and load-bearing (old, many inbound links)", f["stale_load_bearing"], lambda r: f"- {r['path']} · updated {r['updated']} · inbound {r['inbound']} · {r['confidence']}")
    sec("Open connection pages", f["open_connections"], lambda r: f"- {r['path']} · {r['status'][:120]}")
    sec("Waiting candidates in _inbox", f["waiting_candidates"], lambda r: f"- {r}")
    out.append(f"## Open decisions in research (files touched in window) ({len(f['research_decisions'])})")
    for d in f["research_decisions"]:
        out.append(f"- {d['file']} · {d['heading']} · {d['mtime']}")
        out.extend(f"    {i+1}. {it}" for i, it in enumerate(d["items"]))
    out.append("")
    g = f["git"]
    out.append("## What moved")
    for k in ("vault", "research"):
        a = g.get(k)
        out.append(f"- {k}: {a['commits']} commits" if a else f"- {k}: not a git repo")
        if a:
            out.extend(f"    - {s}" for s in a["subjects"][:6])
    out.append("")
    sec("Registry drift (concierge)", f.get("registry_drift", []), lambda r: f"- {r['id']} · {r['kind']} · {r['detail']}")
    sec("Recent pages", f["recent"], lambda r: f"- {r['path']} · created {r['created']} · updated {r['updated']}")
    sec("Ordinary-stream sample (re-read; keeps judgement live)", f["ordinary_sample"], lambda r: f"- {r['path']} · updated {r['updated']} · inbound {r['inbound']}")
    sec("Orphans (no inbound links)", f["orphans"], lambda r: f"- {r['path']}")
    sec("Broken wikilinks", f["broken_links"], lambda r: f"- [[{r['target']}]] from {', '.join(r['from'][:3])} ({r['count']})")
    p = f["prior"]
    out.append(f"## Prior dispositions: {p['dispositions'] or 'none yet'}")
    if p["pending"] and p["pending"]["pending"]:
        out.append(f"Pending verdicts from brief {p['pending']['brief']}: " + "; ".join(f"{i}. {t}" for i, t in p["pending"]["pending"]))
    out.append("")
    out.append(f"Bounds: at most {f['bounds']['max_items']} items, read at most {f['bounds']['read_budget_files']} files, one pass, no writes to wiki/.")
    return "\n".join(out)


# ----------------------------------------------------------------------------- state ops

def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_brief(a, cfg):
    facts = build_facts(cfg, dt.date.fromisoformat(a.date) if a.date else None)
    sd = state_dir(cfg)
    if a.save:
        (sd / "briefs" / f"{facts['date']}-facts.json").write_text(json.dumps(facts, indent=2, default=str), encoding="utf-8")
        (sd / "briefs" / f"{facts['date']}-facts.md").write_text(facts_markdown(facts), encoding="utf-8")
    print(json.dumps(facts, indent=2, default=str) if a.json else facts_markdown(facts))


def cmd_dispose(a, cfg):
    if a.verdict not in ("keep", "act", "drop"):
        sys.exit("verdict must be keep | act | drop")
    sd = state_dir(cfg)
    row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "brief": a.brief, "item": a.item, "verdict": a.verdict, "note": a.note or ""}
    append_jsonl(sd / "dispositions.jsonl", row)
    print(json.dumps(row))


def cmd_log(a, cfg):
    sd = state_dir(cfg)
    row = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "event": a.event, "detail": a.detail or "", "machine": os.uname().nodename}
    append_jsonl(sd / "log.jsonl", row)
    print(json.dumps(row))


def cmd_wake(a, cfg):
    sd = state_dir(cfg)
    root = Path(__file__).resolve().parent.parent
    ident = (root / "steward" / "identity.md")
    parts = ["# Steward wake bundle", ""]
    if ident.exists():
        parts += [ident.read_text(encoding="utf-8").strip(), ""]
    pend = pending_verdicts(sd)
    briefs = sorted((sd / "briefs").glob("*-brief*.md"))
    if briefs:
        head = briefs[-1].read_text(encoding="utf-8").splitlines()[:4]
        status = next((l for l in head if "status:" in l), "")
        if status and "disposed" not in status:
            parts.append(f"IN-FLIGHT: {briefs[-1].name} is not disposed ({status.split('status:')[-1].strip()[:60]}). Another steward may be acting on it. Do not act until it is disposed; collect verdicts first or stop.")
    if pend:
        parts.append(f"Last brief: {pend['brief']} · items: " + "; ".join(f"{i+1}. {t}" for i, t in enumerate(pend['items'])))
        if pend["pending"]:
            parts.append("Awaiting Sonny's verdict: " + "; ".join(f"{i}. {t}" for i, t in pend["pending"]))
        else:
            parts.append("All items disposed.")
    else:
        parts.append("No brief yet. This is the first wake.")
    tally = prior_dispositions(sd)["tally"]
    parts.append(f"Dispositions so far: {tally or 'none'}")
    logf = sd / "log.jsonl"
    if logf.exists():
        lines = logf.read_text(encoding="utf-8").splitlines()[-5:]
        parts.append("Recent log:")
        for line in lines:
            try:
                r = json.loads(line)
                parts.append(f"- {r['ts'][:16]} {r['event']}: {r['detail'][:120]}")
            except json.JSONDecodeError:
                pass
    parts.append(f"Handbook: {root / 'steward' / 'handbook.md'}")
    text = "\n".join(parts)
    limit = cfg["wake_char_limit"]
    if len(text) > limit:
        text = text[: limit - 20] + "\n… (wake truncated)"
    print(text)


def cmd_shield_audit(a, cfg):
    pages = load_pages(cfg)
    rows = [(p, pg["shield"]) for p, pg in pages.items() if pg["shield"]]
    print(json.dumps({"full": [p for p, m in rows if m == "full"], "partial": [p for p, m in rows if m == "partial"], "total_pages": len(pages)}, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="steward", description="Deterministic rails for the steward")
    ap.add_argument("--config", help="path to steward.config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief", help="facts for a what-needs-you brief"); b.add_argument("--json", action="store_true"); b.add_argument("--save", action="store_true"); b.add_argument("--date")
    d = sub.add_parser("dispose", help="record keep | act | drop for a brief item"); d.add_argument("--brief", required=True); d.add_argument("--item", required=True, type=int); d.add_argument("--verdict", required=True); d.add_argument("--note")
    l = sub.add_parser("log", help="append a session event"); l.add_argument("--event", required=True); l.add_argument("--detail")
    sub.add_parser("wake", help="bounded wake bundle")
    sub.add_parser("shield-audit", help="which pages the shield covers and how")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    {"brief": cmd_brief, "dispose": cmd_dispose, "log": cmd_log, "wake": cmd_wake, "shield-audit": cmd_shield_audit}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
