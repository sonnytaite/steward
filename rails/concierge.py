#!/usr/bin/env python3
"""concierge rails — the registry of agents, derived from exhaust, curated through the gate.

  crawl     walk the configured roots, emit registry.json (derived facts per agent/repo)
  note      write or update the curated overlay for one agent (stage, going, next, notes)
  console   render console.html (standalone, local) from registry + overlay + research index + vault themes
  where     print "where did I get to" for one agent: derived facts + overlay + latest handover + recent commits
  drift     agents touched since their overlay note, or idle 30+ days with an open next step (feeds the brief)

The registry is derived; the overlay is Sonny's words; the console is a view. Nothing here writes to wiki/.
State lives in <vault>/surfaces/steward/concierge/. stdlib only.
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, re, subprocess, sys, html
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from steward import load_config, parse_frontmatter  # noqa: E402

ARTEFACTS = {
    "CLAUDE.md": "identity", "agents": "agents/", "skills": "skills/", ".claude-plugin": "plugin", "handbook": "handbook",
    "handbooks": "handbooks/", "harness": "harness/", "prompts": "prompts/", "app": "app/", "workbook": "workbook/",
}
CODE_MARKERS = ("pyproject.toml", "package.json", "requirements.txt", "Dockerfile", "docker-compose.yml")
STAGE_RE = re.compile(r"(?im)^\**\s*(status|stage|where this stands|rung)\s*[:.]\**\s*(.+)$")
RUN_RE = re.compile(r"```(?:bash|sh|zsh|shell)?\n((?:.*\n){1,6}?)```")


def git(repo: Path, *args) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=20, check=False).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def first_para(md: str) -> str:
    fm, _, body = parse_frontmatter(md)
    lines = [l.strip() for l in body.splitlines()]
    out = []
    for l in lines:
        if not l or l.startswith("#"):
            if out: break
            continue
        if l.startswith(("---", "|", "```", "!")): continue
        out.append(l.lstrip("> ").strip())
        if len(" ".join(out)) > 400: break
    return " ".join(out)[:500]


def describe_repo(repo: Path, cfg: dict) -> dict | None:
    if not (repo / ".git").exists():
        return None
    files = {p.name for p in repo.iterdir()}
    arts = sorted({v for k, v in ARTEFACTS.items() if k in files or any(f.lower().startswith(k) for f in files)})
    code = any(m in files for m in CODE_MARKERS)
    readme = next((repo / n for n in ("README.md", "readme.md", "CLAUDE.md") if (repo / n).exists()), None)
    md = readme.read_text(encoding="utf-8", errors="replace") if readme else ""
    title = (re.search(r"^# (.+)$", md, flags=re.M) or [None, repo.name])[1] if md else repo.name
    stage = STAGE_RE.search(md)
    runs = [r.strip() for r in RUN_RE.findall(md)[:3]]
    last = git(repo, "log", "-1", "--format=%ad", "--date=short")
    if not last:
        return None
    count = git(repo, "rev-list", "--count", "HEAD")
    recent7 = git(repo, "log", "--since=7 days ago", "--format=%s").splitlines()
    recent30 = git(repo, "log", "--since=30 days ago", "--format=%s").splitlines()
    subjects = git(repo, "log", "-10", "--format=%ad %s", "--date=short").splitlines()
    is_agent = bool(arts) or repo.name in cfg.get("concierge_include", [])
    return {
        "id": repo.name, "path": str(repo), "title": str(title).strip(), "summary": first_para(md), "artefacts": arts, "code": code,
        "declared_stage": stage.group(2).strip()[:160] if stage else "", "how_to_run": runs, "last_commit": last,
        "commits": int(count or 0), "commits_7d": len(recent7), "commits_30d": len(recent30), "recent": subjects, "is_agent": is_agent,
    }


def research_links(cfg: dict, name: str) -> dict:
    root = Path(cfg["research"]); hits, handover = [], None
    for readme in sorted(root.glob("*/README.md")):
        text = readme.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\b" + re.escape(name) + r"\b", text, flags=re.I):
            hits.append(readme.parent.name)
    for proj in hits:
        hs = sorted((root / proj).glob("*handover*.md"))
        if hs and (handover is None or hs[-1].name > handover[1]):
            handover = (proj, hs[-1].name)
    return {"research_projects": hits[:8], "latest_handover": f"{handover[0]}/{handover[1]}" if handover else None}


def wiki_links(cfg: dict, name: str) -> list:
    wiki = Path(cfg["vault"]) / cfg["wiki_dir"]; out = []
    for f in wiki.rglob("*.md"):
        try:
            if re.search(r"\b" + re.escape(name) + r"\b", f.read_text(encoding="utf-8", errors="replace"), flags=re.I):
                out.append(f.relative_to(wiki).with_suffix("").as_posix())
        except OSError:
            pass
    return sorted(out)[:10]


def state(cfg: dict) -> Path:
    p = Path(cfg["vault"]) / cfg["state_dir"] / "concierge"; p.mkdir(parents=True, exist_ok=True); return p


def load_overlay(sd: Path) -> dict:
    f = sd / "overlay.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def cmd_crawl(a, cfg):
    roots = [Path(r).expanduser() for r in cfg.get("concierge_roots", ["~/Projects"])]
    skip = set(cfg.get("concierge_skip", []))
    entries = []
    for root in roots:
        for repo in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in skip):
            d = describe_repo(repo, cfg)
            if d:
                d.update(research_links(cfg, repo.name)); d["wiki_pages"] = wiki_links(cfg, repo.name); entries.append(d)
    # research-side agents: research projects with agents/ or prompts/ dirs
    root = Path(cfg["research"])
    for proj in sorted(root.iterdir()):
        if proj.is_dir() and ((proj / "agents").exists() or (proj / "prompts").exists()) and not (proj / ".git").exists():
            md = (proj / "README.md").read_text(encoding="utf-8", errors="replace") if (proj / "README.md").exists() else ""
            stage = STAGE_RE.search(md)
            last = git(root, "log", "-1", "--format=%ad", "--date=short", "--", str(proj.relative_to(root)))
            entries.append({"id": f"research/{proj.name}", "path": str(proj), "title": (re.search(r"^# (.+)$", md, flags=re.M) or [None, proj.name])[1],
                            "summary": first_para(md), "artefacts": [n for n in ("agents/", "prompts/") if (proj / n.rstrip("/")).exists()], "code": False,
                            "declared_stage": stage.group(2).strip()[:160] if stage else "", "how_to_run": [], "last_commit": last, "commits": 0,
                            "commits_7d": len(git(root, "log", "--since=7 days ago", "--format=%s", "--", str(proj.relative_to(root))).splitlines()),
                            "commits_30d": len(git(root, "log", "--since=30 days ago", "--format=%s", "--", str(proj.relative_to(root))).splitlines()),
                            "recent": git(root, "log", "-6", "--format=%ad %s", "--date=short", "--", str(proj.relative_to(root))).splitlines(),
                            "is_agent": True, "research_projects": [proj.name], "latest_handover": None, "wiki_pages": wiki_links(cfg, proj.name)})
    reg = {"generated": dt.date.today().isoformat(), "entries": entries}
    sd = state(cfg); (sd / "registry.json").write_text(json.dumps(reg, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"registry: {len(entries)} entries ({sum(1 for e in entries if e['is_agent'])} with agent artefacts) -> {sd / 'registry.json'}")


def cmd_note(a, cfg):
    sd = state(cfg); ov = load_overlay(sd); rec = ov.get(a.agent, {})
    for k in ("stage", "going", "next", "notes", "run"):
        v = getattr(a, k, None)
        if v is not None: rec[k] = v
    rec["updated"] = dt.date.today().isoformat(); rec["by"] = a.by or "sonny"
    ov[a.agent] = rec; (sd / "overlay.json").write_text(json.dumps(ov, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({a.agent: rec}, ensure_ascii=False))


def compute_drift(cfg: dict, today: dt.date | None = None) -> list:
    today = today or dt.date.today(); sd = state(cfg)
    f = sd / "registry.json"
    if not f.exists(): return []
    reg = json.loads(f.read_text(encoding="utf-8")); ov = load_overlay(sd); out = []
    for e in reg["entries"]:
        if not e["is_agent"]: continue
        o = ov.get(e["id"], {}); last = dt.date.fromisoformat(e["last_commit"]) if e["last_commit"] else None
        if not o:
            out.append({"id": e["id"], "kind": "no-record", "detail": f"agent artefacts, last commit {e['last_commit']}, no overlay record"})
        elif last and o.get("updated") and last > dt.date.fromisoformat(o["updated"]):
            out.append({"id": e["id"], "kind": "stale-record", "detail": f"code moved {e['last_commit']} after the record ({o['updated']})"})
        elif last and o.get("next") and (today - last).days >= 30:
            out.append({"id": e["id"], "kind": "idle-with-next", "detail": f"idle {(today - last).days} days with next step: {o['next'][:90]}"})
    return out


def cmd_drift(a, cfg):
    print(json.dumps(compute_drift(cfg), indent=1, ensure_ascii=False))


def cmd_where(a, cfg):
    sd = state(cfg); reg = json.loads((sd / "registry.json").read_text(encoding="utf-8")); ov = load_overlay(sd)
    e = next((x for x in reg["entries"] if x["id"] == a.agent or x["id"].endswith("/" + a.agent)), None)
    if not e: sys.exit(f"no registry entry for {a.agent}; run crawl")
    o = ov.get(e["id"], {})
    print(f"# {e['title']}  ({e['id']})\n\n{e['summary']}\n")
    print(f"Last commit {e['last_commit']} · {e['commits']} commits · {e['commits_30d']} in 30 days · artefacts: {', '.join(e['artefacts']) or 'none'}")
    if e["declared_stage"]: print(f"Declared in README: {e['declared_stage']}")
    print(f"\nOverlay (Sonny's words, {o.get('updated', 'never')}): stage={o.get('stage', '?')}\n  going: {o.get('going', '?')}\n  next: {o.get('next', '?')}\n  notes: {o.get('notes', '')}")
    if e.get("how_to_run") or o.get("run"): print("\nHow to run:\n" + (o.get("run") or "\n".join(e["how_to_run"])))
    print("\nResearch: " + ", ".join(e.get("research_projects") or []) + (f"\nLatest handover: {e['latest_handover']}" if e.get("latest_handover") else ""))
    print("Wiki: " + ", ".join(e.get("wiki_pages") or []))
    print("\nRecent commits:\n" + "\n".join("  " + s for s in e["recent"]))
    if e.get("latest_handover"):
        hp = Path(cfg["research"]) / e["latest_handover"]
        txt = hp.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"(?is)(##[^\n]*(next|where|open|decision)[^\n]*\n.*?)(?=\n## |\Z)", txt)
        if m: print("\nFrom the handover:\n" + m.group(1).strip()[:1800])


# ----------------------------------------------------------------------------- console

def research_streams(cfg: dict) -> list:
    idx = Path(cfg["research"]) / "README.md"; out = []
    if not idx.exists(): return out
    for m in re.finditer(r"^### ([^\n]+)\n\*\*Status:\*\* ([^\n]+)\n([^\n]*)", idx.read_text(encoding="utf-8"), flags=re.M):
        name = m.group(1).split(" — ")[0].split(", ")[0].strip(); status = re.sub(r"\[README\]\([^)]*\)", "", m.group(2)).strip(" |·")
        out.append({"name": name, "heading": m.group(1)[:200], "status": status[:200], "gist": re.sub(r"\*\*|\[\[|\]\]", "", m.group(3))[:600]})
    return out


def insights(cfg: dict) -> list:
    root = Path(cfg["research"]); out = []
    for readme in root.glob("*/README.md"):
        text = readme.read_text(encoding="utf-8", errors="replace"); fm_last = re.search(r"\*\*Last active:\*\* (\d{4}-\d{2}-\d{2})", text)
        sec = re.search(r"## Key findings\n(.*?)(?=\n## |\Z)", text, flags=re.S)
        if not sec: continue
        for line in sec.group(1).splitlines():
            b = re.match(r"- \*\*(.+?)\*\*", line)
            if b: out.append({"project": readme.parent.name, "date": fm_last.group(1) if fm_last else "", "insight": b.group(1)[:220]})
    out.sort(key=lambda x: x["date"], reverse=True); return out[:80]


def themes(cfg: dict) -> list:
    tdir = Path(cfg["vault"]) / cfg["wiki_dir"] / "themes"; out = []
    for f in sorted(tdir.glob("*.md")) if tdir.exists() else []:
        fm, _, body = parse_frontmatter(f.read_text(encoding="utf-8")); st = re.search(r"^\*\*Status\.?\*\*\s*(.*)$", body, flags=re.M)
        out.append({"slug": f.stem, "title": fm.get("title", f.stem), "status": st.group(1)[:200] if st else "", "related": fm.get("related", []) if isinstance(fm.get("related"), list) else []})
    return out


def cmd_console(a, cfg):
    sd = state(cfg); reg = json.loads((sd / "registry.json").read_text(encoding="utf-8")); ov = load_overlay(sd)
    data = {"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "registry": reg["entries"], "overlay": ov, "drift": compute_drift(cfg),
            "streams": research_streams(cfg), "insights": insights(cfg), "themes": themes(cfg),
            "moved": {"vault": git(Path(cfg["vault"]), "log", "--since=7 days ago", "--format=%ad %s", "--date=short").splitlines()[:25],
                      "research": git(Path(cfg["research"]), "log", "--since=7 days ago", "--format=%ad %s", "--date=short").splitlines()[:40]},
            "stages": cfg.get("concierge_stages", ["idea", "spec", "prototype", "harness", "sandbox", "pilot", "production", "parked"])}
    tpl = (HERE.parent / "templates" / "console.html").read_text(encoding="utf-8")
    out = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False))
    target = Path(a.out).expanduser() if a.out else sd / "console.html"
    target.write_text(out, encoding="utf-8"); print(f"console -> {target}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="concierge"); ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("crawl"); sub.add_parser("drift")
    n = sub.add_parser("note"); n.add_argument("--agent", required=True); [n.add_argument(f"--{k}") for k in ("stage", "going", "next", "notes", "run", "by")]
    w = sub.add_parser("where"); w.add_argument("agent")
    c = sub.add_parser("console"); c.add_argument("--out")
    a = ap.parse_args(argv); cfg = load_config(a.config)
    {"crawl": cmd_crawl, "note": cmd_note, "where": cmd_where, "console": cmd_console, "drift": cmd_drift}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
