"""
notify.py — 论文推送摘要
=========================

每个 notification task 是一个 workspace，包含 notify.json 配置。
运行时从 OpenAlex 或本地库获取新论文，语义评分后推送到指定频道（Apprise URL）。

状态持久化到 data/index.db：
  - notify_seen   — 全局已见 DOI（去重）
  - notify_digests — 历史摘要记录

用法：
    scholaraio notify init <ws-name> --query "..." [--schedule "0 8 * * 1"] [--channel URL]
    scholaraio notify run  <ws-name> [--dry-run]
    scholaraio notify list
    scholaraio notify install <ws-name>
    scholaraio notify history <ws-name>
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


# ============================================================================
#  DB state helpers
# ============================================================================


def _ensure_notify_tables(db_path: Path) -> None:
    """Create notify_seen and notify_digests tables if not exists."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notify_seen (
                doi       TEXT PRIMARY KEY,
                first_seen_at TEXT NOT NULL,
                workspace TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notify_digests (
                id          TEXT PRIMARY KEY,
                workspace   TEXT,
                generated_at TEXT,
                sent_at     TEXT,
                channel     TEXT,
                n_papers    INTEGER,
                digest_path TEXT
            )
            """
        )
        conn.commit()


def _filter_seen(papers: list[dict], db_path: Path, workspace: str) -> list[dict]:
    """Remove papers whose DOI is already in notify_seen."""
    _ensure_notify_tables(db_path)

    dois = [p["doi"] for p in papers if p.get("doi")]
    if not dois:
        return papers

    placeholders = ",".join("?" * len(dois))
    with sqlite3.connect(db_path) as conn:
        seen = {
            row[0]
            for row in conn.execute(
                f"SELECT doi FROM notify_seen WHERE doi IN ({placeholders})", dois
            ).fetchall()
        }

    return [p for p in papers if p.get("doi") not in seen]


def _mark_seen(papers: list[dict], db_path: Path, workspace: str) -> None:
    """Mark papers as seen in notify_seen table."""
    if not papers:
        return
    _ensure_notify_tables(db_path)

    now = datetime.now(timezone.utc).isoformat()
    rows = [(p["doi"], now, workspace) for p in papers if p.get("doi")]
    if rows:
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO notify_seen (doi, first_seen_at, workspace) VALUES (?, ?, ?)",
                rows,
            )
            conn.commit()


def _record_digest(
    db_path: Path,
    workspace: str,
    n_papers: int,
    digest_path: Path,
    channels: list[str],
    sent: bool,
) -> None:
    """Record a digest run in notify_digests table."""
    _ensure_notify_tables(db_path)

    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO notify_digests
            (id, workspace, generated_at, sent_at, channel, n_papers, digest_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(_uuid.uuid4()),
                workspace,
                now,
                now if sent else None,
                ",".join(channels),
                n_papers,
                str(digest_path),
            ),
        )
        conn.commit()


def get_digest_history(db_path: Path, workspace: str, limit: int = 10) -> list[dict]:
    """Return recent digest records for a workspace.

    Args:
        db_path: index.db 路径。
        workspace: 工作区名称。
        limit: 返回条数上限。

    Returns:
        摘要记录列表（newest first）。
    """
    _ensure_notify_tables(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, workspace, generated_at, sent_at, channel, n_papers, digest_path
            FROM notify_digests
            WHERE workspace = ?
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            (workspace, limit),
        ).fetchall()

    return [dict(r) for r in rows]


# ============================================================================
#  notify.json helpers
# ============================================================================


def _load_notify_config(ws_dir: Path) -> dict:
    notify_json = ws_dir / "notify.json"
    if not notify_json.exists():
        raise FileNotFoundError(f"notify.json 不存在: {ws_dir}")
    return json.loads(notify_json.read_text(encoding="utf-8"))


def _save_notify_config(ws_dir: Path, config: dict) -> None:
    notify_json = ws_dir / "notify.json"
    tmp = notify_json.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(notify_json)


# ============================================================================
#  Public API: init
# ============================================================================


def init_notify(
    ws_dir: Path,
    *,
    query: str,
    schedule: str = "0 8 * * 1",
    channels: list[str] | None = None,
    sources: list[str] | None = None,
    relevance_threshold: float = 0.65,
    max_papers: int = 10,
) -> dict:
    """创建或更新工作区的 notify.json 配置。

    Args:
        ws_dir: 工作区目录路径。
        query: 感兴趣的研究描述，用于语义相关性评分。
        schedule: Cron 表达式（5 字段），默认每周一上午 8 点。
        channels: Apprise URL 列表（Telegram/邮件/Slack 等）。
        sources: 论文来源列表，支持 ``"openalex"`` 和 ``"library"``。
        relevance_threshold: 最低相关性分数（0-1），低于此值的论文不纳入摘要。
        max_papers: 每次摘要最多收录论文数。

    Returns:
        最终 notify.json 内容字典。
    """
    ws_dir.mkdir(parents=True, exist_ok=True)

    notify_json = ws_dir / "notify.json"
    config: dict = {}
    if notify_json.exists():
        config = json.loads(notify_json.read_text(encoding="utf-8"))

    config.update(
        {
            "interest_query": query,
            "sources": sources or ["openalex"],
            "schedule": schedule,
            "relevance_threshold": relevance_threshold,
            "max_papers": max_papers,
            "channels": channels or [],
            "digest_format": "markdown",
        }
    )
    if "last_run" not in config:
        config["last_run"] = None

    _save_notify_config(ws_dir, config)
    return config


# ============================================================================
#  Paper fetching
# ============================================================================


def _fetch_openalex_recent(
    query: str,
    *,
    since_date: str | None = None,
    max_results: int = 50,
) -> list[dict]:
    """Fetch recent papers from OpenAlex matching a keyword query.

    Args:
        query: 关键词/语义查询字符串。
        since_date: 只拉取此日期之后发表的论文（YYYY-MM-DD）。
        max_results: 最多返回条数（上限 200）。

    Returns:
        论文字典列表，含 doi/title/authors/year/abstract/cited_by_count/venue。
    """
    import requests

    filters = ["type:article"]
    if since_date:
        filters.append(f"from_publication_date:{since_date}")

    params: dict = {
        "search": query,
        "filter": ",".join(filters),
        "sort": "publication_date:desc",
        "per-page": min(max_results, 100),
        "select": (
            "id,title,authorships,publication_year,publication_date,"
            "doi,abstract_inverted_index,cited_by_count,primary_location"
        ),
    }

    try:
        resp = requests.get(
            "https://api.openalex.org/works",
            params=params,
            headers={"User-Agent": "ScholarAIO/1.0 (mailto:notify@scholaraio.dev)"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        _log.error("OpenAlex 请求失败: %s", e)
        return []

    results: list[dict] = []
    for work in data.get("results", []):
        doi = work.get("doi") or ""
        if doi:
            doi = doi.removeprefix("https://doi.org/")

        # Decode abstract from OpenAlex inverted index format
        abstract = ""
        inv_idx = work.get("abstract_inverted_index")
        if inv_idx:
            try:
                word_positions = [
                    (pos, word) for word, positions in inv_idx.items() for pos in positions
                ]
                abstract = " ".join(w for _, w in sorted(word_positions))
            except Exception:
                pass

        authors = []
        for a in (work.get("authorships") or [])[:5]:
            name = ((a.get("author") or {}).get("display_name") or "").strip()
            if name:
                authors.append(name)

        venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name", "")

        results.append(
            {
                "doi": doi,
                "title": work.get("title") or "",
                "authors": authors,
                "year": work.get("publication_year"),
                "date": work.get("publication_date") or "",
                "abstract": abstract,
                "cited_by_count": work.get("cited_by_count") or 0,
                "venue": venue,
                "openalex_id": work.get("id") or "",
            }
        )

    return results


def _fetch_library_new(db_path: Path, *, since_date: str | None = None) -> list[dict]:
    """Fetch papers recently added to the main library.

    Args:
        db_path: index.db 路径。
        since_date: 只返回此日期之后入库的论文（YYYY-MM-DD）。

    Returns:
        简略论文字典列表（id/dir_name/doi）。
    """
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            if since_date:
                rows = conn.execute(
                    "SELECT id, dir_name, doi FROM papers_registry WHERE indexed_at >= ?",
                    (since_date,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, dir_name, doi FROM papers_registry ORDER BY rowid DESC LIMIT 50"
                ).fetchall()
        return [{"id": r["id"], "dir_name": r["dir_name"], "doi": r["doi"] or ""} for r in rows]
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        _log.debug("library fetch 失败: %s", e)
        return []


# ============================================================================
#  Relevance scoring
# ============================================================================


def _score_papers(papers: list[dict], query: str, cfg) -> list[dict]:
    """Score papers by semantic similarity to query string.

    Uses the same embedding model as vectors.py. Falls back to uniform 0.5
    scores if embeddings are unavailable.

    Args:
        papers: 论文字典列表，需含 title/abstract 字段。
        query: 相关性查询字符串。
        cfg: ScholarAIO Config 对象。

    Returns:
        papers 列表（每项追加 ``relevance_score`` 字段），按分数降序排列。
    """
    if not papers:
        return []

    texts = [f"{p.get('title', '')} {(p.get('abstract') or '')[:500]}" for p in papers]

    try:
        import numpy as np

        from scholaraio.vectors import _embed_batch

        all_texts = [query] + texts
        embeddings = _embed_batch(all_texts, cfg)
        query_emb = np.array(embeddings[0], dtype=np.float32)
        paper_embs = np.array(embeddings[1:], dtype=np.float32)

        # Cosine similarity
        query_norm = query_emb / (np.linalg.norm(query_emb) + 1e-8)
        norms = np.linalg.norm(paper_embs, axis=1, keepdims=True) + 1e-8
        paper_norms = paper_embs / norms
        scores = paper_norms @ query_norm

        scored = [{**p, "relevance_score": float(s)} for p, s in zip(papers, scores)]
    except ImportError:
        _log.warning("语义评分不可用（缺少 embed 依赖），使用默认分数 0.5")
        scored = [{**p, "relevance_score": 0.5} for p in papers]

    return sorted(scored, key=lambda p: p.get("relevance_score", 0), reverse=True)


# ============================================================================
#  Digest rendering
# ============================================================================


def _render_digest(
    papers: list[dict],
    query: str,
    workspace: str,
    date_str: str,
) -> str:
    """Render digest as Markdown.

    Args:
        papers: 已过滤、已评分、已排序的论文列表。
        query: 兴趣查询字符串（显示在摘要头部）。
        workspace: 工作区名称。
        date_str: 日期字符串（YYYY-MM-DD）。

    Returns:
        Markdown 格式的摘要字符串。
    """
    lines = [
        f"# 论文推送 — {workspace} | {date_str}",
        "",
        f"主题：{query}",
        "",
        f"本期新增 **{len(papers)}** 篇",
        "",
        "---",
        "",
    ]

    for i, p in enumerate(papers, 1):
        title = p.get("title") or "（无标题）"
        authors = p.get("authors") or []
        first_author = authors[0] if authors else "?"
        if len(authors) > 1:
            first_author += " et al."
        year = p.get("year") or "?"
        venue = p.get("venue") or ""
        doi = p.get("doi") or ""
        score = p.get("relevance_score", 0.0)
        cited = p.get("cited_by_count") or 0
        abstract = p.get("abstract") or ""
        abstract_preview = abstract[:200] + "..." if len(abstract) > 200 else abstract

        # Map score to star rating: ≥0.85→⭐⭐⭐, ≥0.75→⭐⭐, else ⭐
        stars = "⭐⭐⭐" if score >= 0.85 else ("⭐⭐" if score >= 0.75 else "⭐")

        meta_parts = [first_author]
        if venue:
            meta_parts.append(venue)
        if year:
            meta_parts.append(str(year))
        meta_line = " · ".join(meta_parts)

        lines.append(f"**[{i}] {title}** {stars} {score:.2f}")
        lines.append(meta_line)
        if doi:
            lines.append(f"DOI: https://doi.org/{doi}")
        if cited:
            lines.append(f"引用量: {cited}")
        if abstract_preview:
            lines.append("")
            lines.append(f"> {abstract_preview}")
        lines.append("")

    return "\n".join(lines)


# ============================================================================
#  Delivery via Apprise
# ============================================================================


def _send_digest(digest_text: str, channels: list[str], title: str) -> list[str]:
    """Send digest via Apprise to all configured channels.

    Args:
        digest_text: 摘要 Markdown 正文。
        channels: Apprise URL 列表。
        title: 推送标题。

    Returns:
        推送失败的 channel URL 列表（成功时为空列表）。
    """
    if not channels:
        return []

    try:
        import apprise
    except ImportError:
        _log.warning("apprise 未安装，跳过推送。安装方法: pip install apprise")
        return channels

    a = apprise.Apprise()
    for url in channels:
        a.add(url)

    success = a.notify(title=title, body=digest_text)
    if not success:
        _log.error("Apprise 推送失败，请检查 channel URL 配置")
        return channels
    return []


# ============================================================================
#  Public API: run
# ============================================================================


def run_notify(ws_dir: Path, cfg, *, dry_run: bool = False) -> dict:
    """执行一次通知摘要。

    从配置的来源（OpenAlex / 本地库）获取论文，去重、评分后生成摘要并推送。

    Args:
        ws_dir: 工作区目录路径（需含 notify.json）。
        cfg: ScholarAIO Config 对象。
        dry_run: 为 True 时只生成 draft.md，不推送也不更新 last_run。

    Returns:
        执行结果字典：

        - ``n_fetched``: 从来源拉取的原始论文数
        - ``n_new``: 去重、过滤后纳入摘要的论文数
        - ``n_sent``: 成功推送的论文数（dry_run 时为 0）
        - ``digest_path``: 生成的摘要文件路径
        - ``dry_run``: 是否为 dry-run 模式
        - ``failed_channels``: 推送失败的 channel 列表
    """
    notify_cfg = _load_notify_config(ws_dir)
    query = notify_cfg.get("interest_query") or ""
    sources = notify_cfg.get("sources") or ["openalex"]
    channels = notify_cfg.get("channels") or []
    threshold = float(notify_cfg.get("relevance_threshold") or 0.65)
    max_papers = int(notify_cfg.get("max_papers") or 10)
    last_run = notify_cfg.get("last_run")

    ws_name = ws_dir.name
    db_path = cfg.index_db

    # --- Fetch from all sources ---
    all_papers: list[dict] = []
    for source in sources:
        if source == "openalex":
            fetched = _fetch_openalex_recent(query, since_date=last_run, max_results=max_papers * 4)
            all_papers.extend(fetched)
            _log.info("OpenAlex: 获取 %d 篇", len(fetched))
        elif source == "library":
            fetched = _fetch_library_new(db_path, since_date=last_run)
            all_papers.extend(fetched)
            _log.info("本地库: 获取 %d 篇", len(fetched))
        else:
            _log.warning("未知来源类型: %s", source)

    n_fetched = len(all_papers)

    # --- In-batch DOI dedup ---
    seen_dois: set[str] = set()
    deduped: list[dict] = []
    for p in all_papers:
        doi = p.get("doi") or ""
        if doi:
            if doi in seen_dois:
                continue
            seen_dois.add(doi)
        deduped.append(p)

    # --- Cross-session dedup (notify_seen table) ---
    new_papers = _filter_seen(deduped, db_path, ws_name)

    # --- Relevance scoring ---
    if query:
        scored = _score_papers(new_papers, query, cfg)
    else:
        scored = new_papers

    # --- Threshold filter + top-N ---
    filtered = [p for p in scored if p.get("relevance_score", 0.5) >= threshold]
    top_papers = filtered[:max_papers]
    n_new = len(top_papers)

    # --- Generate digest ---
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest_text = _render_digest(top_papers, query, ws_name, date_str)

    digests_dir = ws_dir / "digests"
    digests_dir.mkdir(exist_ok=True)
    digest_path = digests_dir / f"{date_str}.md"
    draft_path = ws_dir / "draft.md"

    digest_path.write_text(digest_text, encoding="utf-8")
    draft_path.write_text(digest_text, encoding="utf-8")
    _log.info("Digest 已写入: %s (%d 篇)", digest_path, n_new)

    failed_channels: list[str] = []
    n_sent = 0

    if not dry_run:
        if top_papers and channels:
            title = f"📬 {ws_name} 论文推送 {date_str}"
            failed_channels = _send_digest(digest_text, channels, title)
            n_sent = n_new if not failed_channels else 0

        # Mark seen and persist state
        _mark_seen(top_papers, db_path, ws_name)
        notify_cfg["last_run"] = date_str
        _save_notify_config(ws_dir, notify_cfg)

        # Record in DB
        _record_digest(
            db_path,
            ws_name,
            n_new,
            digest_path,
            channels,
            sent=n_sent > 0,
        )

    return {
        "n_fetched": n_fetched,
        "n_new": n_new,
        "n_sent": n_sent,
        "digest_path": str(digest_path),
        "dry_run": dry_run,
        "failed_channels": failed_channels,
    }


# ============================================================================
#  Public API: list
# ============================================================================


def list_notify_tasks(ws_root: Path) -> list[dict]:
    """列出所有含 notify.json 的工作区任务。

    Args:
        ws_root: workspace/ 根目录。

    Returns:
        任务信息字典列表（name/query/schedule/channels/last_run）。
    """
    if not ws_root.is_dir():
        return []
    tasks = []
    for d in sorted(ws_root.iterdir()):
        if d.is_dir() and (d / "notify.json").exists():
            try:
                nc = json.loads((d / "notify.json").read_text(encoding="utf-8"))
            except Exception:
                continue
            tasks.append(
                {
                    "name": d.name,
                    "query": nc.get("interest_query") or "",
                    "schedule": nc.get("schedule") or "",
                    "channels": nc.get("channels") or [],
                    "last_run": nc.get("last_run"),
                }
            )
    return tasks


# ============================================================================
#  Public API: systemd timer
# ============================================================================


def _cron_to_systemd_calendar(cron: str) -> str:
    """Convert a 5-field cron expression to systemd OnCalendar format."""
    parts = cron.strip().split()
    if len(parts) != 5:
        return "weekly"

    minute, hour, dom, month, dow = parts
    day_map = {
        "0": "Sun", "7": "Sun",
        "1": "Mon", "2": "Tue", "3": "Wed",
        "4": "Thu", "5": "Fri", "6": "Sat",
    }

    if dom == "*" and month == "*":
        h = hour.zfill(2)
        m = minute.zfill(2)
        if dow in day_map:
            return f"{day_map[dow]} *-*-* {h}:{m}:00"
        if dow == "*":
            return f"*-*-* {h}:{m}:00"

    return "weekly"  # fallback for complex expressions


def generate_systemd_units(ws_dir: Path, cfg_path: Path) -> tuple[str, str]:
    """Generate systemd .service and .timer unit file content.

    Args:
        ws_dir: 工作区目录路径（需含 notify.json）。
        cfg_path: config.yaml 路径，写入 Environment= 行。

    Returns:
        ``(service_content, timer_content)`` 字符串二元组。
    """
    ws_name = ws_dir.name
    notify_cfg = _load_notify_config(ws_dir)
    calendar = _cron_to_systemd_calendar(notify_cfg.get("schedule") or "0 8 * * 1")

    service_name = f"scholaraio-notify-{ws_name}"

    service = f"""\
[Unit]
Description=ScholarAIO notification digest: {ws_name}
After=network-online.target

[Service]
Type=oneshot
ExecStart=scholaraio notify run {ws_name}
Environment=SCHOLARAIO_CONFIG={cfg_path}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

    timer = f"""\
[Unit]
Description=ScholarAIO notification timer: {ws_name}
Requires={service_name}.service

[Timer]
OnCalendar={calendar}
Persistent=true

[Install]
WantedBy=timers.target
"""

    return service, timer


def install_systemd(ws_dir: Path, cfg_path: Path) -> tuple[Path, Path]:
    """Generate and install systemd user timer for a notify task.

    Args:
        ws_dir: 工作区目录路径（需含 notify.json）。
        cfg_path: config.yaml 路径。

    Returns:
        ``(service_path, timer_path)`` 已写入文件路径二元组。

    Raises:
        RuntimeError: systemctl 调用失败（会记录 warning，不中断流程）。
    """
    import subprocess

    ws_name = ws_dir.name
    service_content, timer_content = generate_systemd_units(ws_dir, cfg_path)
    service_name = f"scholaraio-notify-{ws_name}"

    systemd_user_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_user_dir.mkdir(parents=True, exist_ok=True)

    service_path = systemd_user_dir / f"{service_name}.service"
    timer_path = systemd_user_dir / f"{service_name}.timer"

    service_path.write_text(service_content, encoding="utf-8")
    timer_path.write_text(timer_content, encoding="utf-8")
    _log.info("已写入 systemd 文件: %s, %s", service_path, timer_path)

    # Enable and start the timer
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", f"{service_name}.timer"],
            check=True,
            capture_output=True,
        )
        _log.info("systemd timer 已启动: %s.timer", service_name)
    except FileNotFoundError:
        _log.warning("systemctl 不可用（非 systemd 环境），请手动设置定时任务")
    except Exception as e:
        _log.warning("systemctl 调用失败: %s", e)

    return service_path, timer_path
