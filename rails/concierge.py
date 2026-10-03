#!/usr/bin/env python3
"""concierge rails — the registry of agents, derived from exhaust, curated through the gate.

  crawl     walk the configured roots, emit registry.json (derived facts per agent/repo)
  note      write or update the curated overlay for one agent (stage, going, next, notes)
  art       write or update the overlay's record for one artefact (category, title, blurb, why, data), keyed by ~/ path
  console   render console.html (standalone, local) from registry + overlay + research index + vault themes,
            with the Dashboards section (overlay "_dashboards", last touched from git at generation time)
            and the Research, Articles and Visualisations sections (registry "artefacts", overlay "_artefacts"),
            and the Handovers section (registry "handovers": every handover brief under ~/Projects, newest first)
  where     print "where did I get to" for one agent: derived facts + overlay + latest handover + recent commits
  drift     agents touched since their overlay note, or idle 30+ days with an open next step (feeds the brief)

The registry is derived; the overlay is Sonny's words; the console is a view. Nothing here writes to wiki/.
State lives in <vault>/surfaces/steward/concierge/. stdlib only.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, os, re, subprocess, sys, html
from urllib.parse import quote
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
        "last_ts": int(git(repo, "log", "-1", "--format=%ct") or 0), "last_hash": git(repo, "log", "-1", "--format=%h"),
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


def agent_overlay(ov: dict) -> dict:
    """Overlay records keyed by agent id; keys starting with _ hold curated lists (for example _dashboards)."""
    return {k: v for k, v in ov.items() if not k.startswith("_")}


def dashboards(ov: dict) -> list:
    """The curated list of local dashboards, dev servers and services, with last touched derived from git now."""
    out = []
    for d in ov.get("_dashboards", []):
        d = dict(d); repo = Path(d["repo"]).expanduser() if d.get("repo") else None
        line = git(repo, "log", "-1", "--format=%ad|%h|%ct|%s", "--date=short") if repo and (repo / ".git").exists() else ""
        date, sha, ts, subject = (line.split("|", 3) + ["", "", "", ""])[:4]
        d.update(last_touched=date, last_hash=sha, last_subject=subject[:160], last_ts=int(ts or 0))
        if d.get("url", "").startswith("file://~"): d["url"] = "file://" + str(Path("~").expanduser()) + d["url"][len("file://~"):]
        out.append(d)
    return out


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", str(s)).strip("-").lower()


def dash_anchor(d: dict) -> str:
    """Stable in-page id for a dashboard, service or dev server card: its kind and name."""
    return f'{ {"service": "s", "dev": "v"}.get(d.get("kind"), "d") }-{slug(d["name"])}'


def art_anchor(i: dict) -> str:
    """Stable in-page id for an artefact card: a short hash of its path under ~/Projects, so it survives regeneration."""
    return i.get("anchor") or "a-" + hashlib.sha1(i["rel"].encode()).hexdigest()[:10]


def agent_anchor(agent_id: str) -> str:
    return "g-" + slug(agent_id)  # the template's agent cards carry the same id


CMD_LINE = re.compile(r"^(cd|source|\.|python3?|uv|uvx|pip|npm|npx|pnpm|yarn|node|make|docker|bash|sh|claude|git|ollama|\.venv/|\./|~/|/)\S*(\s|$)")  # a shell command, not prose
RECENT_LABEL = {"dashboard": "Dashboard", "service": "Service", "dev": "Dev server", "visualisations": "Visualisation", "articles": "Article",
                "research": "Research", "unfiled": "Unfiled", "agent": "Agent", "handover": "Handover"}


def recent_items(dash: list, art: dict, entries: list, ov: dict, handovers: list | None = None) -> list:
    """Everything with a last-touched time, newest first by commit time (file time where there is no commit); ties keep title order."""
    out = []
    for i in handovers or []:
        out.append({"kind": "handover", "title": i["title"], "anchor": i["anchor"], "direct": "file://" + quote(i["path"]), "date": i["last_touched"],
                    "hash": i.get("last_hash", ""), "subject": i.get("last_subject", ""), "ts": i.get("last_ts", 0), "project": i["project"],
                    "blurb": i.get("where", ""), "cmd": ""})
    for d in dash:
        cmd = f"cd {d['start_cwd']} && {d['start_cmd']}" if d.get("start_cwd") and d["start_cwd"] != "~" else d.get("start_cmd", "")
        out.append({"kind": d.get("kind", "dashboard"), "title": d["name"], "anchor": dash_anchor(d), "direct": d["url"], "date": d.get("last_touched", ""),
                    "hash": d.get("last_hash", ""), "subject": d.get("last_subject", ""), "ts": d.get("last_ts", 0),
                    "project": Path(d["repo"]).expanduser().name if d.get("repo") else "", "blurb": d.get("what", ""), "cmd": cmd})
    for i in art["items"]:
        out.append({"kind": i["category"], "title": i["title"], "anchor": art_anchor(i), "direct": "file://" + quote(i["path"]), "date": i["last_touched"],
                    "hash": i.get("last_hash", ""), "subject": i.get("last_subject", ""), "ts": i.get("last_ts", 0), "project": i["project"],
                    "blurb": i.get("blurb", ""), "cmd": ""})
    for x in entries:
        if not x.get("is_agent"): continue
        o = ov.get(x["id"], {}); lines = (o.get("run") or "").splitlines() + [l for r in x.get("how_to_run") or [] for l in r.splitlines()]
        run = next((l.strip() for l in lines if CMD_LINE.match(l.strip())), "")
        out.append({"kind": "agent", "title": x["title"] if len(x["title"]) <= 60 else x["id"], "anchor": agent_anchor(x["id"]), "agent": x["id"],
                    "direct": "file://" + quote(x["path"]), "date": x.get("last_commit", ""), "hash": x.get("last_hash", ""), "subject": "",
                    "ts": x.get("last_ts", 0), "project": x["id"], "blurb": o.get("next") or x.get("summary", ""), "cmd": run})
    return sorted((r for r in out if r["ts"]), key=lambda r: (-r["ts"], r["title"].lower()))


def render_recent(items: list, now: dt.datetime | None = None) -> str:
    """The Recent index: one line per item, the title an in-page link to its full card, a direct link beside it.
    Eight rows, then a native fold with up to sixteen from the last fourteen days."""
    if not items: return ""
    e = lambda s: html.escape(str(s or ""), quote=True)
    now = now or dt.datetime.now(); cutoff = (now - dt.timedelta(days=14)).timestamp()
    top = items[:8]; more = [r for r in items[8:16] if r["ts"] >= cutoff]
    shown = top + more

    def line(r):
        agent = f' data-agent="{e(r["agent"])}"' if r.get("agent") else ""
        href = "#agents" if r.get("agent") else "#" + r["anchor"]  # agent cards are drawn by script; without it the link lands on Agents
        hsh = f' <code title="{e(r["subject"])}">{e(r["hash"])}</code>' if r.get("hash") else ' <span class="muted">file date</span>'
        cmd = (f'<span class="rcmd"><code>{e(r["cmd"])}</code><button class="copy rcopy" type="button" title="copy the start command">copy</button></span>' if r.get("cmd") else "")
        return (f'<li class="rrow"><span class="tag rk rk-{e(r["kind"])}">{e(RECENT_LABEL.get(r["kind"], r["kind"]))}</span>'
                f'<a class="rtitle" href="{e(href)}" data-target="{e(r["anchor"])}"{agent} title="{e(r["blurb"][:200])}">{e(r["title"])}</a>'
                f'<a class="rdirect" href="{e(r["direct"])}" target="_blank" rel="noopener" title="open {e(r["direct"])}" aria-label="open directly">&#8599;</a>'
                f'<span class="rmeta">{e(r["date"])}{hsh} · {e(r["project"])}</span>{cmd}</li>')

    rng = f'{dt.date.fromtimestamp(shown[-1]["ts"]).isoformat()} to {dt.date.fromtimestamp(shown[0]["ts"]).isoformat()}'
    h = major_open("recent", f'Recent, most recently touched first <span class="muted rrange">({e(rng)})</span>', "")
    h += ('<p class="lead">Last week\'s work to pick up: every dashboard, visualisation, article, research page, unfiled page, handover and agent, ordered by its last commit '
          '(file date where there is none). The title jumps to its card below; the arrow opens it directly.</p>')
    h += f'<ul class="recent">{"".join(line(r) for r in top)}</ul>'
    if more: h += f'<details class="more rmore"><summary>show 16 <span class="muted">({len(more)} more from the last fourteen days)</span></summary><ul class="recent">{"".join(line(r) for r in more)}</ul></details>'
    return h + "</details>"


def major_open(sid: str, name: str, n, extra: str = "", h2cls: str = "") -> str:
    """Open tag of one major section: a native <details> (works with scripts blocked), open by default, the heading and its
    count as the summary line, styled like the Dev servers fold. The template's script remembers open or closed per browser."""
    cnt = f' <span class="muted acount" data-total="{n}">({n})</span>' if n != "" else ""
    return f'<details class="major{extra}" id="{sid}" open><summary><h2{f" class={h2cls}" if h2cls else ""}>{name}{cnt}</h2></summary>'


def render_dashboards(items: list) -> str:
    """Static HTML for the Dashboards section, so it renders even when scripts are blocked; the script adds live status."""
    e = lambda s: html.escape(str(s or ""), quote=True)

    def cmd(d):
        return f"cd {d['start_cwd']} && {d['start_cmd']}" if d.get("start_cwd") and d["start_cwd"] != "~" else d.get("start_cmd", "")

    def status(d):
        if d["url"].startswith("file://"): return '<span class="dstate"><span class="dot file"></span><span class="dlabel">static file</span></span>'
        return '<span class="dstate" data-probe="1"><span class="dot"></span><span class="dlabel">not checked</span></span>'

    def touched(d):
        if not d.get("last_touched"): return '<span class="muted">no git history</span>'
        return f'{e(d["last_touched"])} <code title="{e(d["last_subject"])}">{e(d["last_hash"])}</code>'

    def dcard(d):
        hnz = '<span class="tag warn">Health NZ work</span>' if d.get("scope") == "hnz" else ""
        setup = f'<div class="meta">first time: <code>{e(d["setup"])}</code></div>' if d.get("setup") else ""
        note = f'<div class="meta">{e(d["note"])}</div>' if d.get("note") else ""
        repo = f' · <code>{e(d["repo"])}</code>' if d.get("repo") else ""
        nxt = f'<p><b>Next:</b> {e(d["next"])}</p>' if d.get("next") else '<p class="muted">Next: not recorded</p>'
        return (f'<div class="card dash" id="{e(dash_anchor(d))}" data-url="{e(d["url"])}"><div class="dhead"><h3>{e(d["name"])}</h3>{status(d)}</div>'
                f'<div class="meta"><a href="{e(d["url"])}" target="_blank" rel="noopener">{e(d["url"])}</a> {hnz}</div>'
                f'<div class="cmdrow"><pre class="cmd">{e(cmd(d))}</pre><button class="copy" type="button" title="copy the start command">copy</button></div>{setup}'
                f'<p>{e(d.get("what"))} {e(d.get("why"))}</p>{nxt}{note}'
                f'<div class="meta">last touched {touched(d)}{repo}</div></div>')

    def row(d):
        hnz = ' <span class="tag warn">Health NZ work</span>' if d.get("scope") == "hnz" else ""
        return (f'<tr id="{e(dash_anchor(d))}"><td><b>{e(d["name"])}</b>{hnz}</td><td><a href="{e(d["url"])}" target="_blank" rel="noopener">{e(d["url"])}</a></td>'
                f'<td><code>{e(cmd(d))}</code></td><td>{e(d.get("what"))}</td><td class="muted">{touched(d)}</td></tr>')

    dash = [d for d in items if d.get("kind", "dashboard") == "dashboard"]
    dev = [d for d in items if d.get("kind") == "dev"]
    svc = [d for d in items if d.get("kind") == "service"]
    if not items: return ""
    h = (major_open("dashboards", "Dashboards", len(dash)) + '<div class="dtop">'
         '<button class="checknow" id="checknow" type="button">check now</button><span class="gen" id="checked">live status needs scripts; the links and commands work without them</span></div>'
         '<p class="lead">Every local dashboard you have built, with the command to start it if it is down. Status is checked from this page every 60 seconds: '
         '<span class="dot up"></span> up, <span class="dot down"></span> down, <span class="dot"></span> checking.</p>'
         f'<div class="grid dgrid">{"".join(dcard(d) for d in dash)}</div>')
    if dev:
        h += (f'<details class="devs"><summary>Dev servers <span class="muted">({len(dev)}), Next.js apps that all default to port 3000, so only one runs at a time; no live status</span></summary>'
              f'<table><tr><th>Repo</th><th>URL</th><th>Start</th><th>What</th><th>Last touched</th></tr>{"".join(row(d) for d in dev)}</table></details>')
    h += "</details>"
    if svc:
        h += major_open("services", "Services", len(svc)) + f'<div class="grid dgrid">{"".join(dcard(d) for d in svc)}</div></details>'
    return h


# ----------------------------------------------------------------------------- artefacts
# Research, Articles and Visualisations: the rendered pages (HTML, and PDF beside them) Sonny has had made and can open.
# Scope: the known set (every repo the crawl registers, the overlay's agents and the _dashboards repos) plus the whole
# research repo and the vault's share folder. The concierge_skip rules still apply, so Health NZ and private trees
# (healthX, healthx-commons, vault-personal, og-docs, ...) are never read.
#
# Rules, first match wins (classify): under the research repo -> research; under the vault's share folder (surface
# share_dir), a briefs/digests/packs path or a *-pack folder, or a sibling .md whose front matter type is brief, article,
# digest or pack -> articles; a title or file name with a visualisation word, or a page with <svg>, <canvas> or a chart
# library script tag -> visualisations; anything else -> unfiled (shown, folded, never dropped). The overlay's
# "_artefacts" (keyed by ~/ path) then overrides category, title, blurb, why and data in Sonny's words.
#
# Exclusions: generated artefacts of tools, vendored or downloaded material, templates and fragments. Every excluded
# file or pruned folder is recorded in the registry with its reason, so the exclusion list is auditable.
ART_PRUNE_DIRS = {  # folder names never walked
    "node_modules": "dependencies", ".venv": "virtualenv", "venv": "virtualenv", "site-packages": "dependencies",
    ".git": "git internals", "dist": "build output", "build": "build output", ".next": "build output", "out": "build output",
    "vendor": "vendored library", "__pycache__": "cache", ".pytest_cache": "cache", "coverage": "test coverage output",
    "fixtures": "test fixtures", "tests": "test fixtures", "test": "test fixtures", "dify-src": "vendored third-party source (Dify)",
    "raw": "downloaded source material", ".obsidian": "editor config", "_exemplars": "copyrighted reference scans",
    "_style": "house style files", "source-project-for-review-only": "vendored copy of another repo",
}
ART_QUIET = {"dependencies", "virtualenv", "git internals", "cache", "editor config"}  # pruned without listing each folder
ART_EXCLUDE = [  # (regex on the path relative to ~/Projects, reason); first match wins
    (r"^second-brain/surfaces/steward/concierge/console\.html$", "the concierge's own console"),
    (r"^steward/templates/", "concierge template"),
    (r"^org-atlas/(static|images?|snapshots?)/", "org-atlas app shell and images, served by atlas serve"),
    (r"^estate-console/static/", "estate console app shell, served by console.py"),
    (r"^[^/]+/(static|web|ui|public|app|src)/index\.html$", "app shell, needs its server (see Dashboards)"),
    (r"^whakapapa-kete/sources/published/", "published source texts the kete ingests, not made for Sonny"),
    (r"/data/(derived|raw)/", "data folder: downloads and generated fragments"),
    (r"(?i)(^|/)[^/]*template[^/]*\.(html?|pdf)$", "template file"),
    (r"(?i)(^|/)[^/]*[ ._-](backup|bak|old|copy)(\.[^/.]+)?\.html?$", "backup copy of another page"),
    (r"^cisra/CIS_Controls_Guide[^/]*\.pdf$", "third-party reference document (CIS Controls guide)"),
    (r"^drptool/nist\.sp\.[^/]*\.pdf$", "third-party reference document (NIST SP 800-184)"),
]
VIS_WORDS = re.compile(r"(?i)\b(atlas|dashboards?|maps?|charts?|workforce|scoreboards?|heat ?maps?|graphs?|visuali[sz](?:ation|er)s?|fleet view|radar|board)\b")
CHART_LIB = re.compile(r"(?is)<script[^>]+src=[\"'][^\"']*(chart(?:\.umd)?(?:\.min)?\.js|chart\.js|/d3(?:@|\.v\d|\.min|\.js)|echarts|plotly|vega|leaflet|mapbox|highcharts|apexcharts|cytoscape|vis-network|mermaid)")
ART_TYPES = {"brief", "article", "digest", "pack", "vision-artefact"}
DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", s or ""))).strip()


def html_facts(f: Path) -> dict:
    """Derived from the page itself: title (<title>, else first <h1>), blurb (meta description, else first paragraph),
    visual markers and any stated data source line."""
    try:
        t = f.read_text(encoding="utf-8", errors="replace")[:2_000_000]
    except OSError:
        return {"title": "", "blurb": "", "svg": False, "canvas": False, "chartlib": "", "fragment": True, "data": ""}
    title = _strip((re.search(r"(?is)<title[^>]*>(.*?)</title>", t) or [None, ""])[1])
    h1 = _strip((re.search(r"(?is)<h1[^>]*>(.*?)</h1>", t) or [None, ""])[1])
    desc = re.search(r"(?is)<meta[^>]+name=[\"']description[\"'][^>]*content=[\"']([^\"']+)", t)
    body = re.sub(r"(?is)<(script|style|svg|nav|header)[^>]*>.*?</\1>", " ", t)
    prose = lambda p: len(p) > 40 and sum(c.isalpha() or c.isspace() for c in p) / len(p) > 0.85 and p.count("→") < 3
    para = next((p for p in (_strip(m) for m in re.findall(r"(?is)<p[^>]*>(.*?)</p>", body)) if prose(p)), "")
    lib = CHART_LIB.search(t)
    # a labelled source only: an element whose text opens "Data:", "Data source(s):" or "Source(s):" (never a data: URI or prose)
    data = re.search(r"(?i)>\s*(?:<(?:b|strong|em|span|dt|th)[^>]*>\s*)?(?:data sources?|data|sources?)\s*(?:[:：]\s*</(?:b|strong|em|span|dt|th)>|</(?:b|strong|em|span|dt|th)>\s*[:：]|[:：])\s*(?:</?d[dt][^>]*>\s*)*([^<]{12,240})<", body)
    return {"title": title or h1, "blurb": _strip(desc.group(1)) if desc else para[:280], "svg": bool(re.search(r"(?i)<svg[\s>]", t)),
            "canvas": bool(re.search(r"(?i)<canvas[\s>]", t)), "chartlib": lib.group(1) if lib else "",
            "fragment": not re.search(r"(?i)<(html|body|title)[\s>]", t), "data": _strip(data.group(1)).strip(" :") if data else ""}


def pdf_title(f: Path) -> str:
    """The PDF's own /Title from its info dictionary, when it is plain text and not a tool's placeholder; else ''."""
    try:
        with open(f, "rb") as fh:
            head = fh.read(200_000); fh.seek(max(0, f.stat().st_size - 200_000)); tail = fh.read()
    except OSError:
        return ""
    m = re.search(rb"/Title\s*\(((?:[^()\\]|\\.){3,200})\)", tail) or re.search(rb"/Title\s*\(((?:[^()\\]|\\.){3,200})\)", head)
    t = m.group(1).decode("latin-1").replace("\\(", "(").replace("\\)", ")").strip() if m else ""
    return "" if not t or t.startswith("\xfe\xff") or re.search(r"(?i)^(untitled|microsoft word|document\d*)", t) else t


def git_index(repo: Path) -> dict:
    """One pass over a repo's history: relative path -> (date, short hash, subject, unix time) of the last commit that touched it."""
    out, cur = {}, None
    mark = "@@concierge@@"  # a text marker: str.splitlines() treats control separators such as \x1e as line breaks
    for line in git(repo, "log", f"--format={mark}%ad|%h|%ct|%s", "--date=short", "--name-only", "--no-renames").splitlines():
        if line.startswith(mark):
            dte, sha, ts, subj = (line[len(mark):].split("|", 3) + ["", "", "", ""])[:4]; cur = (dte, sha, subj, int(ts or 0)); continue
        if line and cur and line not in out: out[line] = cur
    return out


def md_facts(md: Path) -> dict:
    """A sibling .md for an article: front matter title, type, date and dek; else the first ### line or paragraph."""
    if not md.exists(): return {}
    text = md.read_text(encoding="utf-8", errors="replace"); fm, _, body = parse_frontmatter(text)
    dek = fm.get("dek") or (re.search(r"(?m)^### (.+)$", body) or [None, ""])[1] or first_para(text)
    date = next((str(fm[k]) for k in ("date", "created", "written") if fm.get(k)), "")
    return {"title": str(fm.get("title") or (re.search(r"(?m)^# (.+)$", body) or [None, ""])[1]).strip(), "type": str(fm.get("type", "")).lower(),
            "date": DATE_IN_NAME.search(date).group(1) if DATE_IN_NAME.search(date) else "", "blurb": re.sub(r"\*\*|\*|\[\[|\]\]", "", str(dek)).strip()[:300]}


def classify(rel: str, facts: dict, md: dict, research_prefix: str, share_prefix: str) -> tuple[str, str]:
    """The rules, first match wins. Returns (category, the rule that fired)."""
    parts = rel.split("/")
    if research_prefix and rel.startswith(research_prefix): return "research", "under the research repo"
    if share_prefix and rel.startswith(share_prefix): return "articles", "under the surface share folder"
    if any(p in ("briefs", "digests", "packs") or p.endswith("-pack") for p in parts[:-1]): return "articles", "briefs, digests or packs path"
    if md.get("type") in ART_TYPES: return "articles", f"front matter type {md['type']}"
    name = re.sub(r"[_\-.]+", " ", Path(rel).stem)
    if VIS_WORDS.search(name) or VIS_WORDS.search(facts.get("title", "")): return "visualisations", "visualisation word in title or file name"
    if facts.get("chartlib"): return "visualisations", f"chart library ({facts['chartlib']})"
    if facts.get("canvas"): return "visualisations", "contains <canvas>"
    if facts.get("svg"): return "visualisations", "contains <svg>"
    return "unfiled", "no rule matched"


def excluded(rel: str) -> str:
    return next((why for rx, why in ART_EXCLUDE if re.search(rx, rel)), "")


def human_size(n: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB": return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def research_project_facts(root: Path, name: str, gi: dict) -> dict:
    readme = root / name / "README.md"; md = readme.read_text(encoding="utf-8", errors="replace") if readme.exists() else ""
    fm, _, _ = parse_frontmatter(md) if md else ({}, "", "")
    st = STAGE_RE.search(md); status = str(fm.get("status") or (st.group(2) if st else "")).strip()
    dates = [v for k, v in gi.items() if k.startswith(name + "/")]
    last = max(dates, key=lambda d: d[3]) if dates else ("", "", "", 0)
    return {"name": name, "title": (re.search(r"(?m)^# (.+)$", md) or [None, name])[1].strip(), "status": re.sub(r"\*\*", "", status)[:200],
            "last_touched": last[0], "last_hash": last[1], "last_subject": last[2][:160], "path": str(root / name)}


def crawl_artefacts(cfg: dict, repos: list) -> dict:
    """Walk the known set and return {items, excluded, research_projects}. Derived only; the overlay is applied at console time."""
    home = Path(cfg.get("concierge_artefact_base", "~/Projects")).expanduser().resolve()  # resolved, like the roots, so symlinks cannot skew prefixes
    research = Path(cfg["research"]).resolve(); vault = Path(cfg["vault"]).resolve(); skip = set(cfg.get("concierge_skip", []))
    scfg = vault / "surface.config.json"
    share_dir = json.loads(scfg.read_text(encoding="utf-8")).get("share_dir", "share") if scfg.exists() else "share"
    rel_of = lambda p: os.path.relpath(p, home)
    research_prefix = rel_of(research) + "/"; share_prefix = rel_of(vault / share_dir) + "/"
    # the known set: registered repos + overlay agents + dashboard repos, plus research and the vault (which crawl skips as repos)
    roots = {Path(r).resolve() for r in repos} | {research.resolve(), vault.resolve()}
    ov = load_overlay(state(cfg))
    for k in agent_overlay(ov):
        if (home / k).is_dir(): roots.add((home / k).resolve())
    for d in ov.get("_dashboards", []):
        if d.get("repo") and Path(d["repo"]).expanduser().is_dir(): roots.add(Path(d["repo"]).expanduser().resolve())
    roots = sorted(r for r in roots if r.name not in skip or r in (research.resolve(), vault.resolve()))
    dash_files = {str(Path(d["url"][len("file://"):]).expanduser()) for d in ov.get("_dashboards", []) if d.get("url", "").startswith("file://")}
    dash_files |= {str(Path(d["repo"]).expanduser() / "index.html") for d in ov.get("_dashboards", []) if d.get("repo") and d.get("url", "").startswith("http")}
    hnz = {Path(d["repo"]).expanduser().resolve().name for d in ov.get("_dashboards", []) if d.get("scope") == "hnz" and d.get("repo")}
    items, excl, pruned = [], [], {}
    for root in roots:
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            keep = []
            for dn in dirnames:
                why = ART_PRUNE_DIRS.get(dn)
                if not why: keep.append(dn); continue
                if why in ART_QUIET: continue
                n = sum(1 for _, _, fs in os.walk(Path(dirpath) / dn) for f in fs if f.lower().endswith((".html", ".htm", ".pdf")))
                if n: pruned[(rel_of(Path(dirpath) / dn), why)] = n
            dirnames[:] = sorted(keep)
            files += [Path(dirpath) / f for f in filenames if f.lower().endswith((".html", ".htm", ".pdf"))]
        if not files: continue
        gi = git_index(root); pdfs = {}
        for f in files:
            if f.suffix.lower() != ".pdf": continue
            parent = f.parent.parent if f.parent.name == "published" else f.parent
            pdfs[(parent, f.stem)] = f
        paired = set()
        for f in sorted(files):
            rel = rel_of(f); why = excluded(rel) or ("already in Dashboards" if str(f) in dash_files else "")
            if f.suffix.lower() == ".pdf": continue
            facts = html_facts(f)
            if not why and facts["fragment"]: why = "HTML fragment (no html, body or title)"
            if why: excl.append({"path": rel, "reason": why}); continue
            pdf = pdfs.get((f.parent, f.stem)); paired.add(pdf) if pdf else None
            items.append(_artefact(f, rel, facts, pdf, root, gi, research, research_prefix, share_prefix, hnz, home))
        for pdf in sorted(set(pdfs.values()) - paired):
            rel = rel_of(pdf); why = excluded(rel)
            if why: excl.append({"path": rel, "reason": why}); continue
            items.append(_artefact(pdf, rel, {"title": pdf_title(pdf), "blurb": "", "fragment": False}, None, root, gi, research, research_prefix, share_prefix, hnz, home))
    rgi = git_index(research)
    projects = {i["group"] for i in items if i["category"] == "research" and i.get("group")}
    rp = {n: research_project_facts(research, n, rgi) for n in sorted(projects)}
    folded = {}  # more than three files excluded for one reason in one folder -> one row for the folder
    for x in excl: folded.setdefault((str(Path(x["path"]).parent), x["reason"]), []).append(x)
    excl = [x for (d, w), xs in folded.items() for x in xs if len(xs) <= 3] + [{"path": d + "/", "reason": w, "files": len(xs)} for (d, w), xs in folded.items() if len(xs) > 3]
    excl = sorted(excl, key=lambda x: x["path"]) + [{"path": p + "/", "reason": w, "files": n} for (p, w), n in sorted(pruned.items())]
    return {"items": items, "excluded": excl, "research_projects": rp}


def _artefact(f, rel, facts, pdf, root, gi, research, research_prefix, share_prefix, hnz, home) -> dict:
    md = md_facts(f.with_suffix(".md"))
    if not md and f.name.lower() == "readme.html": md = {"blurb": first_para((f.parent / "README.md").read_text(encoding="utf-8", errors="replace"))[:300]} if (f.parent / "README.md").exists() else {}
    cat, rule = classify(rel, facts, md, research_prefix, share_prefix)
    vis = classify(rel, facts, md, "", "")[1] if cat == "research" and classify(rel, facts, md, "", "")[0] == "visualisations" else ""
    in_repo = os.path.relpath(f, root); g = gi.get(in_repo)
    if g: date, sha, subj, committed, ts = g[0], g[1], g[2][:160], True, g[3]
    else: date, sha, subj, committed, ts = dt.date.fromtimestamp(f.stat().st_mtime).isoformat(), "", "", False, int(f.stat().st_mtime)
    if rel.startswith(research_prefix):
        group = in_repo.split("/", 1)[0] if "/" in in_repo else ""; project, ppath = f"research/{group}", str(research / group)
    else:
        group, project, ppath = "", root.name, str(root)
    if cat == "articles":
        parts = in_repo.split("/")
        group = "packs" if any(p == "packs" or p.endswith("-pack") for p in parts[:-1]) else ("digests" if "digests" in parts or "digest" in f.stem else "briefs")
    data = facts.get("data", "")
    if cat == "visualisations" and not data:
        for readme in (f.parent / "README.md", Path(ppath) / "README.md"):
            if readme.exists():
                hit = next((l for l in readme.read_text(encoding="utf-8", errors="replace").splitlines() if f.name in l and re.search(r"(?i)data|source|from", l)), "")
                if hit: data = "README: " + re.sub(r"[*`]|\[([^\]]+)\]\([^)]*\)", r"\1", hit).strip(" -")[:240]; break
    return {"path": str(f), "rel": rel, "ext": f.suffix.lower().lstrip("."), "title": md.get("title") or facts.get("title") or f.stem.replace("-", " "),
            "blurb": md.get("blurb") or facts.get("blurb", ""), "date": md.get("date") or (DATE_IN_NAME.search(f.name).group(1) if DATE_IN_NAME.search(f.name) else ""),
            "category": cat, "rule": rule, "group": group, "project": project, "project_path": ppath, "pdf": str(pdf) if pdf else "",
            "data": data, "last_touched": date, "last_hash": sha, "last_ts": ts, "anchor": "a-" + hashlib.sha1(rel.encode()).hexdigest()[:10], "last_subject": subj, "committed": committed, "size": f.stat().st_size,
            "scope": "hnz" if root.name in hnz else "", "looks_visual": vis}


def artefacts_view(reg_art: dict, ov: dict) -> dict:
    """Apply the overlay's _artefacts (keyed by ~/ path) over the derived list: category, title, blurb, why, data."""
    home = str(Path("~").expanduser()); cur = ov.get("_artefacts", {})
    items = []
    for i in reg_art.get("items", []):
        i = dict(i); o = cur.get("~" + i["path"][len(home):] if i["path"].startswith(home) else i["path"], {})
        for k in ("category", "title", "blurb", "why", "data"):
            if o.get(k): i[k] = o[k]
        if o.get("category"): i["rule"] = "overlay"
        if o: i["overlay_by"] = o.get("by", ""); i["overlay_updated"] = o.get("updated", "")
        items.append(i)
    return {"items": items, "research_projects": reg_art.get("research_projects", {}), "excluded": reg_art.get("excluded", [])}


def render_artefacts(view: dict) -> str:
    """Static HTML for Research, Articles, Visualisations and Unfiled, so the lists render with scripts blocked;
    the script only adds the per-section filter."""
    e = lambda s: html.escape(str(s or ""), quote=True); uri = lambda p: "file://" + quote(str(p))
    items = view["items"]; rp = view["research_projects"]
    by = {c: [i for i in items if i["category"] == c] for c in ("research", "articles", "visualisations", "unfiled")}

    def touched(i):
        if i.get("last_hash"): return f'{e(i["last_touched"])} <code title="{e(i["last_subject"])}">{e(i["last_hash"])}</code>'
        return f'{e(i["last_touched"])} <span class="muted">(file date, not in git)</span>'

    def src(i):
        return f'<a href="{e(uri(i["project_path"]))}">{e(i["project"])}</a>'

    def links(i):
        a = f'<a class="atitle" href="{e(uri(i["path"]))}" target="_blank" rel="noopener">{e(i["title"])}</a>'
        kinds = [f'<a class="kind" href="{e(uri(i["path"]))}" target="_blank" rel="noopener">{e(i["ext"].upper())}</a>']
        if i.get("pdf"): kinds.append(f'<a class="kind" href="{e(uri(i["pdf"]))}" target="_blank" rel="noopener">PDF</a>')
        return a, " ".join(kinds)

    def tags(i):
        t = '<span class="tag warn">Health NZ work</span>' if i.get("scope") == "hnz" else ""
        if i.get("looks_visual") and i["category"] == "research": t += f'<span class="tag" title="passes the visualisation test: {e(i["looks_visual"])}">visual</span>'
        return t + (f'<span class="tag ok" title="overlay record {e(i.get("overlay_updated"))} by {e(i.get("overlay_by"))}">overlay</span>' if "overlay_by" in i else "")

    def row(i, show_src=True):
        a, k = links(i)
        why = f'<div class="why"><b>Why:</b> {e(i["why"])}</div>' if i.get("why") else ""
        blurb = f'<div class="ablurb">{e(i["blurb"][:260])}</div>' if i.get("blurb") else ""
        return (f'<li class="aitem" id="{e(art_anchor(i))}"><div class="aline">{a} <span class="kinds">{k}</span>{tags(i)}</div>{blurb}{why}'
                f'<div class="meta">{(src(i) + " · ") if show_src else ""}<code>{e(Path(i["rel"]).name)}</code> · last touched {touched(i)} · {e(human_size(i["size"]))}</div></li>')

    def card(i, chip=False):
        a, k = links(i)
        pc = f'<a class="tag pc" href="{e(uri(i["project_path"]))}">{e(i["project"].replace("research/", ""))}</a>' if chip else ""
        none = "What it shows: not stated on the page." if i["category"] == "visualisations" else "No summary on the page (a PDF carries only its title)." if i["ext"] == "pdf" else "No summary on the page."
        what = f'<p>{e(i["blurb"][:300])}</p>' if i.get("blurb") else f'<p class="muted">{none}</p>'
        data = f'<div class="meta"><b>Data:</b> {e(i["data"])}</div>' if i.get("data") else '<div class="meta"><b>Data:</b> not stated on the page or in a nearby README</div>'
        why = f'<div class="why"><b>Why:</b> {e(i["why"])}</div>' if i.get("why") else ""
        date = f' · dated {e(i["date"])}' if i.get("date") else ""
        return (f'<div class="card art aitem" id="{e(art_anchor(i))}">{pc}<h3>{a}</h3><div class="meta"><span class="kinds">{k}</span>{tags(i)}{date}</div>{what}{why}{data if i["category"] == "visualisations" else ""}'
                f'<div class="meta">{src(i)} · last touched {touched(i)} · {e(human_size(i["size"]))}</div></div>')

    def head(cid, name, n, lead):
        return (major_open(cid, name, n, " arts") + f'<div class="dtop"><input class="afilter" type="search" placeholder="filter {name.lower()}…" '
                f'aria-label="filter {name.lower()}" hidden></div><p class="lead">{lead}</p>')

    h = ""
    # Research, grouped by project, newest first; long lists fold after eight
    groups = {}
    for i in by["research"]: groups.setdefault(i["group"] or "(research root)", []).append(i)
    order = sorted(groups, key=lambda g: max(x["last_touched"] for x in groups[g]), reverse=True)
    h += head("research", "Research", len(by["research"]), f'Every rendered page in the research repo, {len(groups)} projects, most recently touched first; each project shows four pages and folds the rest. The status line is the project README\'s own.')
    for g in order:
        lst = sorted(sorted(groups[g], key=lambda x: (x["last_touched"], x["rel"]), reverse=True), key=lambda x: not x["rel"].lower().endswith("readme.html"))
        p = rp.get(g, {}); status = f'<span class="astatus" title="{e(p["status"])}">{e(p["status"])}</span>' if p.get("status") else '<span class="muted">status not recorded</span>'
        pt = f'last touched {e(p["last_touched"])} <code title="{e(p.get("last_subject"))}">{e(p.get("last_hash"))}</code>' if p.get("last_touched") else ""
        rows = "".join(row(i, False) for i in lst[:4]); more = lst[4:]
        fold = f'<details class="more"><summary>{len(more)} more pages</summary><ul class="alist">{"".join(row(i, False) for i in more)}</ul></details>' if more else ""
        h += (f'<div class="agroup"><div class="ghead"><a class="gname" href="{e(uri(p.get("path") or lst[0]["project_path"]))}">{e(g)}</a> <span class="muted">({len(lst)})</span> {status}'
              f'<span class="meta"> {pt}</span></div><ul class="alist">{rows}</ul>{fold}</div>')
    h += "</details>"; research_html, h = h, ""
    # Articles: briefs, digests, packs
    arts = by["articles"]
    h += head("articles", "Articles", len(arts), "HBR-style briefs, digests and packs from the surface plugin (the vault's <code>articles/</code> and pack folders), HTML and PDF side by side. Title, date and summary come from each article's front matter where it has one.")
    for g, label in (("briefs", "Briefs and one-pagers"), ("digests", "Digests"), ("packs", "Packs")):
        lst = sorted((i for i in arts if i["group"] == g), key=lambda x: (x.get("date") or x["last_touched"]), reverse=True)
        if lst: h += f'<div class="agroup"><div class="ghead"><b>{label}</b> <span class="muted">({len(lst)})</span></div><div class="grid agrid">{"".join(card(i) for i in lst)}</div></div>'
    h += "</details>"; articles_html, h = h, ""
    vis = sorted(by["visualisations"], key=lambda x: x["last_touched"], reverse=True)
    h += head("visualisations", "Visualisations", len(vis), f"Standalone views you open to see rather than read, ordered by source project; click a project to filter ({len({i['project'] for i in vis})} projects). What it shows and the data behind it are quoted from the page or a README beside it; where neither says, it says so.")
    vgroups = {}  # ordered by source project (most recently touched project first), a project chip on each card, chips above filter
    for i in vis: vgroups.setdefault(i["project"], []).append(i)
    chips = "".join(f'<button type="button" class="pchip" data-q="{e(g)}">{e(g.replace("research/", ""))} <span class="muted">{len(lst)}</span></button>' for g, lst in vgroups.items())
    h += f'<div class="pchips" aria-label="filter by project">{chips}</div>'
    h += f'<div class="grid agrid">{"".join(card(i, chip=True) for lst in vgroups.values() for i in lst)}</div>'
    h += "</details>"
    h += articles_html + research_html  # smallest first, so Research's length never buries the other two
    un = sorted(by["unfiled"], key=lambda x: x["last_touched"], reverse=True)
    ex = view.get("excluded", [])
    reasons = {}
    for x in ex: reasons[x["reason"]] = reasons.get(x["reason"], 0) + x.get("files", 1)
    exrows = "".join(f'<tr><td><code>{e(x["path"])}</code></td><td>{x.get("files", 1)}</td><td>{e(x["reason"])}</td></tr>' for x in ex)
    h += (major_open("unfiled", "Unfiled", len(un), " arts") + f'<p class="lead">Pages the rules could not place, folded so nothing is dropped silently; '
          f'file one by giving it a category in the overlay\'s <code>_artefacts</code>. Every exclusion is listed below with its reason.</p>'
          f'<details class="devs"><summary>Unfiled pages <span class="muted">({len(un)})</span></summary>'
          f'<input class="afilter" type="search" placeholder="filter unfiled…" aria-label="filter unfiled" hidden><ul class="alist">{"".join(row(i) for i in un)}</ul></details>'
          f'<details class="devs"><summary><b>Excluded</b> <span class="muted">({sum(reasons.values())} files, by the documented exclusion list)</span></summary>'
          f'<p class="meta">{e("; ".join(f"{r}: {n}" for r, n in sorted(reasons.items(), key=lambda kv: -kv[1])))}. The list is ART_PRUNE_DIRS and ART_EXCLUDE in <code>rails/concierge.py</code>; '
          f'dependency, virtualenv, cache and git folders are skipped without listing.</p><table><tr><th>Path</th><th>Files</th><th>Why</th></tr>'
          f'{exrows}</table></details></details>')
    return h


# ----------------------------------------------------------------------------- handovers
# Session handover briefs: every Markdown file under ~/Projects whose name contains "handover" (case blind), plus any
# README or other .md whose first heading contains "handover". Scope: every top-level folder except concierge_skip
# (the research repo and the vault are walked, as for artefacts), so employer-hidden repos stay hidden. Pruned: the
# artefact prune list plus Terraform state, agent worktrees, .claude folders (skills, not handovers) and scratchpads;
# the artefact exclusion list (ART_EXCLUDE) still applies. Dated by the file's last commit; by file time where the
# file is untracked or has uncommitted edits.
HO_PRUNE = set(ART_PRUNE_DIRS) | {".terraform", ".claude", "worktrees", "scratchpad", "target", ".mypy_cache", ".ruff_cache"}
HO_NAME = re.compile(r"(?i)handover")
QUIET_DAYS = 14


def _md_head(text: str) -> tuple[str, str]:
    """(title, where we are): the first heading, and the first plain line after it (front matter status wins)."""
    fm, _, body = parse_frontmatter(text)
    lines = body.splitlines(); title, start = "", 0
    for n, l in enumerate(lines):
        m = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", l.strip())
        if m: title, start = m.group(1).strip(), n + 1; break
    status = str(fm.get("status") or "").strip() if isinstance(fm, dict) else ""
    where, fence, para = "", False, []
    for l in lines[start:]:
        s = l.strip()
        if para and (not s or s.startswith(("#", "|", "```", "- ", "* ", "<!--"))): break  # a hard-wrapped line joins its paragraph
        if s.startswith("```"): fence = not fence; continue
        if fence or not s or s.startswith(("#", "|", "---", "***", "<!--", "!")): continue
        para.append(s.lstrip("> ").strip() if para else s)
        if len(" ".join(para)) > 400: break
    where = " ".join(para)
    clean = lambda s: re.sub(r"\s+", " ", re.sub(r"\*\*|__|`|\[\[|\]\]|\[([^\]]+)\]\([^)]*\)", r"\1", s.lstrip("> ").strip())).strip()
    return clean(title), clean(status or where)


def _git_root(p: Path) -> Path | None:
    for d in (p.parent, *p.parent.parents):
        if (d / ".git").exists(): return d
    return None


def crawl_handovers(cfg: dict) -> list:
    """Walk ~/Projects for handover briefs. Derived only; the console flags quiet ones at render time."""
    home = Path(cfg.get("concierge_artefact_base", "~/Projects")).expanduser().resolve()
    research = Path(cfg["research"]).expanduser().resolve(); vault = Path(cfg["vault"]).expanduser().resolve(); skip = set(cfg.get("concierge_skip", []))
    keep = {research, vault}
    roots = sorted(p for p in home.iterdir() if p.is_dir() and not p.name.startswith(".") and (p.name not in skip or p.resolve() in keep))
    out = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in HO_PRUNE)
            for fn in filenames:
                if not fn.lower().endswith(".md"): continue
                f = Path(dirpath) / fn; rel = os.path.relpath(f, home)
                if excluded(rel): continue
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")[:20000] if HO_NAME.search(fn) else f.read_text(encoding="utf-8", errors="replace")[:4000]
                except OSError:
                    continue
                title, where = _md_head(text)
                if not HO_NAME.search(fn) and not HO_NAME.search(title): continue
                if HO_NAME.search(fn) and not text.strip(): continue
                out.append(_handover(f, rel, title, where, root, research))
    return sorted(out, key=lambda h: (-h["last_ts"], h["title"].lower()))


def _handover(f: Path, rel: str, title: str, where: str, root: Path, research: Path) -> dict:
    repo = _git_root(f); line = git(repo, "log", "-1", "--format=%ad|%h|%ct|%s", "--date=short", "--", str(f)) if repo else ""
    dirty = bool(git(repo, "status", "--porcelain", "--", str(f))) if repo and line else False
    if line and not dirty:
        date, sha, ts, subj = (line.split("|", 3) + ["", "", "", ""])[:4]; ts = int(ts or 0)
    else:
        ts = int(f.stat().st_mtime); date, sha, subj = dt.date.fromtimestamp(ts).isoformat(), "", ""
    try:
        under_research = f.resolve().is_relative_to(research)
    except AttributeError:  # Python < 3.9
        under_research = str(f.resolve()).startswith(str(research) + os.sep)
    if under_research:
        sub = os.path.relpath(f.resolve(), research).split(os.sep)
        project, ppath = ("research/" + sub[0], research / sub[0]) if len(sub) > 1 else ("research", research)
    else:
        project, ppath = root.name, root
    twin = f.with_suffix(".html")
    return {"path": str(f), "rel": rel, "title": title or f.stem.replace("-", " "), "where": where[:400], "project": project, "project_path": str(ppath),
            "in_project": os.path.relpath(f, ppath), "html": str(twin) if twin.exists() else "", "last_touched": date, "last_hash": sha,
            "last_subject": subj[:160], "last_ts": ts, "committed": bool(sha), "dirty": dirty,
            "anchor": "h-" + hashlib.sha1(rel.encode()).hexdigest()[:10]}


def render_handovers(items: list, now: dt.datetime | None = None) -> str:
    """The Handovers section: one line per brief, newest first, with where it stands and links to the .md and its .html twin.
    Briefs untouched for fourteen days carry a quiet tag."""
    e = lambda s: html.escape(str(s or ""), quote=True); uri = lambda p: "file://" + quote(str(p))
    now = now or dt.datetime.now(); cutoff = (now - dt.timedelta(days=QUIET_DAYS)).timestamp()
    quiet = sum(1 for i in items if i["last_ts"] < cutoff)

    def row(i):
        kinds = f'<a class="kind" href="{e(uri(i["path"]))}" target="_blank" rel="noopener">MD</a>'
        if i.get("html"): kinds += f' <a class="kind" href="{e(uri(i["html"]))}" target="_blank" rel="noopener">HTML</a>'
        tag = f'<span class="tag warn" title="not touched for {QUIET_DAYS} days or more">quiet</span>' if i["last_ts"] < cutoff else ""
        if i.get("last_hash"): when = f'{e(i["last_touched"])} <code title="{e(i["last_subject"])}">{e(i["last_hash"])}</code>'
        else: when = f'{e(i["last_touched"])} <span class="muted">({"file date, uncommitted edits" if i.get("dirty") else "file date, not in git"})</span>'
        w = i.get("where") or ""; w = w if len(w) <= 260 else w[:260].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        where = f'<div class="ablurb">{e(w)}</div>' if w else '<div class="ablurb muted">Where it stands: not stated.</div>'
        return (f'<li class="aitem" id="{e(i["anchor"])}"><div class="aline"><a class="atitle" href="{e(uri(i["path"]))}" target="_blank" rel="noopener">{e(i["title"])}</a> '
                f'<span class="kinds">{kinds}</span>{tag}</div>{where}'
                f'<div class="meta"><a href="{e(uri(i["project_path"]))}">{e(i["project"])}</a> · <code>{e(i["in_project"])}</code> · last updated {when}</div></li>')

    h = (major_open("handovers", "Handovers", len(items), " arts") + '<div class="dtop"><input class="afilter" type="search" placeholder="filter handovers…" '
         'aria-label="filter handovers" hidden></div>'
         f'<p class="lead">Every session handover brief across the projects, newest first by last commit (file date where uncommitted). '
         f'The line under each title is where it stands, from its front matter status or its first line. {quiet} quiet for {QUIET_DAYS} days or more.</p>')
    if not items: return h + '<p class="muted">No handovers found.</p></details>'
    return h + f'<ul class="alist">{"".join(row(i) for i in items)}</ul></details>'


def artefact_jump(view: dict, handovers: int | None = None) -> str:
    c = lambda k: sum(1 for i in view["items"] if i["category"] == k)
    ho = f'<a href="#handovers">Handovers ({handovers})</a>' if handovers is not None else ""
    return (f'<nav class="jump" aria-label="sections"><a href="#recent">Recent</a>{ho}<a href="#dashboards">Dashboards</a><a href="#services">Services</a><a href="#visualisations">Visualisations ({c("visualisations")})</a>'
            f'<a href="#articles">Articles ({c("articles")})</a><a href="#research">Research ({c("research")})</a>'
            f'<a href="#unfiled">Unfiled ({c("unfiled")})</a><a href="#agents">Agents</a></nav>')


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
            lts = int(git(root, "log", "-1", "--format=%ct", "--", str(proj.relative_to(root))) or 0); lh = git(root, "log", "-1", "--format=%h", "--", str(proj.relative_to(root)))
            entries.append({"id": f"research/{proj.name}", "path": str(proj), "title": (re.search(r"^# (.+)$", md, flags=re.M) or [None, proj.name])[1],
                            "summary": first_para(md), "artefacts": [n for n in ("agents/", "prompts/") if (proj / n.rstrip("/")).exists()], "code": False,
                            "declared_stage": stage.group(2).strip()[:160] if stage else "", "how_to_run": [], "last_commit": last, "last_ts": lts, "last_hash": lh, "commits": 0,
                            "commits_7d": len(git(root, "log", "--since=7 days ago", "--format=%s", "--", str(proj.relative_to(root))).splitlines()),
                            "commits_30d": len(git(root, "log", "--since=30 days ago", "--format=%s", "--", str(proj.relative_to(root))).splitlines()),
                            "recent": git(root, "log", "-6", "--format=%ad %s", "--date=short", "--", str(proj.relative_to(root))).splitlines(),
                            "is_agent": True, "research_projects": [proj.name], "latest_handover": None, "wiki_pages": wiki_links(cfg, proj.name)})
    art = crawl_artefacts(cfg, [e["path"] for e in entries if not e["id"].startswith("research/")])
    ho = crawl_handovers(cfg)
    reg = {"generated": dt.date.today().isoformat(), "entries": entries, "artefacts": art, "handovers": ho}
    sd = state(cfg); (sd / "registry.json").write_text(json.dumps(reg, indent=1, ensure_ascii=False), encoding="utf-8")
    cats = {c: sum(1 for i in art["items"] if i["category"] == c) for c in ("research", "articles", "visualisations", "unfiled")}
    print(f"registry: {len(entries)} entries ({sum(1 for e in entries if e['is_agent'])} with agent artefacts) -> {sd / 'registry.json'}")
    print("artefacts: " + ", ".join(f"{k} {v}" for k, v in cats.items()) + f"; excluded {len(art['excluded'])}")
    print(f"handovers: {len(ho)} across {len({h['project'] for h in ho})} projects")


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


def cmd_art(a, cfg):
    """Write or update one overlay _artefacts record (category, title, blurb, why, data), keyed by ~/ path."""
    sd = state(cfg); ov = load_overlay(sd); home = str(Path("~").expanduser())
    p = str(Path(a.path).expanduser().resolve()); key = "~" + p[len(home):] if p.startswith(home) else p
    if a.category and a.category not in ("research", "articles", "visualisations", "unfiled"): sys.exit(f"unknown category {a.category}")
    arts = ov.setdefault("_artefacts", {}); rec = arts.get(key, {})
    for k in ("category", "title", "blurb", "why", "data"):
        v = getattr(a, k, None)
        if v is not None: rec[k] = v
    rec["updated"] = dt.date.today().isoformat(); rec["by"] = a.by or "sonny"
    arts[key] = rec; (sd / "overlay.json").write_text(json.dumps(ov, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: rec}, ensure_ascii=False))


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
    for d in (x for x in dashboards(load_overlay(sd)) if Path(x.get("repo", "")).expanduser().name == e["id"]):
        print(f"Dashboard: {d['name']} {d['url']}  (start: cd {d['start_cwd']} && {d['start_cmd']})")
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
    sd = state(cfg); reg = json.loads((sd / "registry.json").read_text(encoding="utf-8")); full = load_overlay(sd); ov = agent_overlay(full)
    dash = dashboards(full); art = artefacts_view(reg.get("artefacts", {}), full)
    ho = reg["handovers"] if "handovers" in reg else crawl_handovers(cfg)  # a registry from before handovers: derive them now
    data = {"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "registry": reg["entries"], "overlay": ov, "drift": compute_drift(cfg), "dashboards": dash,
            "streams": research_streams(cfg), "insights": insights(cfg), "themes": themes(cfg),
            "moved": {"vault": git(Path(cfg["vault"]), "log", "--since=7 days ago", "--format=%ad %s", "--date=short").splitlines()[:25],
                      "research": git(Path(cfg["research"]), "log", "--since=7 days ago", "--format=%ad %s", "--date=short").splitlines()[:40]},
            "stages": cfg.get("concierge_stages", ["idea", "spec", "prototype", "harness", "sandbox", "pilot", "production", "parked"])}
    tpl = (HERE.parent / "templates" / "console.html").read_text(encoding="utf-8")
    out = tpl.replace("<!--__JUMP__-->", artefact_jump(art, len(ho))).replace("<!--__HANDOVERS__-->", render_handovers(ho)).replace("<!--__DASHBOARDS__-->", render_dashboards(dash)).replace("<!--__RECENT__-->", render_recent(recent_items(dash, art, reg["entries"], ov, ho))).replace("<!--__ARTEFACTS__-->", render_artefacts(art)).replace("<!--__AGENTS__-->", major_open("agents", "Agents", f"{sum(1 for x in reg['entries'] if x['is_agent'])} of {len(reg['entries'])} repos", h2cls="break")).replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    target = Path(a.out).expanduser() if a.out else sd / "console.html"
    target.write_text(out, encoding="utf-8"); print(f"console -> {target}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="concierge"); ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("crawl"); sub.add_parser("drift")
    n = sub.add_parser("note"); n.add_argument("--agent", required=True); [n.add_argument(f"--{k}") for k in ("stage", "going", "next", "notes", "run", "by")]
    w = sub.add_parser("where"); w.add_argument("agent")
    c = sub.add_parser("console"); c.add_argument("--out")
    r = sub.add_parser("art"); r.add_argument("--path", required=True); [r.add_argument(f"--{k}") for k in ("category", "title", "blurb", "why", "data", "by")]
    a = ap.parse_args(argv); cfg = load_config(a.config)
    {"crawl": cmd_crawl, "note": cmd_note, "art": cmd_art, "where": cmd_where, "console": cmd_console, "drift": cmd_drift}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
