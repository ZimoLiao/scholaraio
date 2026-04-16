"""API query functions (Crossref, Semantic Scholar, OpenAlex) and metadata enrichment."""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote, urlencode

import requests

from scholaraio.sources.arxiv import get_arxiv_paper, normalize_arxiv_ref

from ._extract import _extract_lastname
from ._models import (
    CR_BASE,
    OA_BASE,
    RELAXED_THRESHOLD,
    S2_BASE,
    S2_FIELDS,
    SESSION,
    TIMEOUT,
    TITLE_MATCH_THRESHOLD,
    PaperMetadata,
)

_log = logging.getLogger(__name__)


# ============================================================================
#  API Query Functions
# ============================================================================


def query_semantic_scholar(doi: str = "", title: str = "", arxiv_id: str = "") -> dict:
    """查询 Semantic Scholar API。

    Args:
        doi: DOI 标识符（优先使用）。
        arxiv_id: arXiv 标识符（如 ``2401.12345``，DOI 为空时使用）。
        title: 论文标题（DOI 和 arXiv ID 均为空时用于搜索）。

    Returns:
        API 返回的论文数据字典，未找到时返回空字典。
    """
    if doi:
        paper_id = quote(f"DOI:{doi}", safe="")
        url = f"{S2_BASE}/{paper_id}?fields={S2_FIELDS}"
    elif arxiv_id:
        paper_id = quote(f"arXiv:{arxiv_id}", safe="")
        url = f"{S2_BASE}/{paper_id}?fields={S2_FIELDS}"
    elif title:
        params = {"query": title, "limit": "3", "fields": S2_FIELDS}
        url = f"{S2_BASE}/search?{urlencode(params)}"
    else:
        return {}

    try:
        resp = SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 5))
            _log.warning("[S2] Rate limited, waiting %ds", wait)
            time.sleep(min(wait, 30))
            resp = SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()

        # Search endpoint returns list — pick best match
        if "data" in data:
            for item in data.get("data", []):
                if title and _fuzzy_title_match(title, item.get("title", "")) >= TITLE_MATCH_THRESHOLD:
                    return item
            return {}
        return data
    except (requests.RequestException, ValueError, KeyError) as e:
        _log.warning("[S2] %s", e)
        return {}


def _oa_api_key() -> str:
    try:
        from scholaraio.config import load_config

        return load_config().openalex.api_key or ""
    except Exception:
        return ""


def query_openalex(doi: str = "", title: str = "") -> dict:
    """查询 OpenAlex API。

    Args:
        doi: DOI 标识符（优先使用）。
        title: 论文标题（DOI 为空时用于搜索）。

    Returns:
        API 返回的论文数据字典，未找到时返回空字典。
    """
    if doi:
        url = f"{OA_BASE}/doi:{doi}"
    elif title:
        keywords = _title_keywords(title, max_words=8)
        params = {
            "filter": f"title.search:{keywords}",
            "per_page": "3",
            "select": "id,doi,title,publication_year,cited_by_count,authorships,primary_location,type,abstract_inverted_index",
        }
        url = f"{OA_BASE}?{urlencode(params)}"
    else:
        return {}

    api_key = _oa_api_key()
    if api_key:
        url = f"{url}&api_key={api_key}" if "?" in url else f"{url}?api_key={api_key}"

    try:
        resp = SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()

        # Search endpoint returns list
        if "results" in data:
            for item in data.get("results", []):
                if title and _fuzzy_title_match(title, item.get("title", "")) >= TITLE_MATCH_THRESHOLD:
                    return item
            return {}
        return data
    except (requests.RequestException, ValueError, KeyError) as e:
        _log.warning("[OA] %s", e)
        return {}


def query_crossref(doi: str = "", title: str = "") -> dict:
    """查询 Crossref API（DOI 权威注册中心）。

    Crossref 提供最规范的期刊名、作者列表和论文类型分类。

    Args:
        doi: DOI 标识符（优先使用）。
        title: 论文标题（DOI 为空时用于搜索）。

    Returns:
        API 返回的论文数据字典，未找到时返回空字典。
    """
    if doi:
        url = f"{CR_BASE}/{doi}"
    elif title:
        keywords = _title_keywords(title, max_words=8)
        params = {
            "query.title": keywords,
            "rows": "3",
            "select": "DOI,title,author,container-title,published-print,"
            "published-online,type,is-referenced-by-count,abstract",
        }
        url = f"{CR_BASE}?{urlencode(params)}"
    else:
        return {}

    try:
        resp = SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()

        # DOI lookup returns {"message": {...}}
        if doi:
            return data.get("message", {})

        # Title search returns {"message": {"items": [...]}}
        items = data.get("message", {}).get("items", [])
        for item in items:
            cr_titles = item.get("title", [])
            cr_title = cr_titles[0] if cr_titles else ""
            if title and _fuzzy_title_match(title, cr_title) >= TITLE_MATCH_THRESHOLD:
                return item
        return {}
    except (requests.RequestException, ValueError, KeyError) as e:
        _log.warning("[CR] %s", e)
        return {}


# ============================================================================
#  Helpers
# ============================================================================


def _fuzzy_title_match(a: str, b: str) -> float:
    """Dice coefficient on word sets (case-insensitive, stripped punctuation).

    Dice = 2*|A∩B| / (|A|+|B|).  More forgiving than Jaccard for
    different-length strings (e.g. subtitle included in only one source).
    """

    def words(s: str) -> set[str]:
        return set(re.sub(r"[^\w\s]", "", s.lower()).split())

    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return 2 * len(wa & wb) / (len(wa) + len(wb))


def _title_keywords(title: str, max_words: int = 8) -> str:
    """Extract significant keywords from title for API search."""
    stop = {"a", "an", "the", "of", "in", "on", "for", "and", "by", "to", "with", "its", "their"}
    words = re.sub(r"[^\w\s-]", "", title).replace("-", " ").split()
    significant = [w for w in words if w.lower() not in stop]
    return " ".join(significant[:max_words])


def _dedupe_dois(dois: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for doi in dois:
        normalized = str(doi or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(lowered)
    return deduped


def _reference_dois_from_s2(s2_data: dict) -> list[str]:
    ref_dois: list[str] = []
    for ref in s2_data.get("references") or []:
        ext_ids = ref.get("externalIds") or {}
        doi = ext_ids.get("DOI")
        if doi:
            ref_dois.append(doi)
    return _dedupe_dois(ref_dois)


def _reference_dois_from_crossref(cr_data: dict) -> list[str]:
    ref_dois: list[str] = []
    for ref in cr_data.get("reference") or []:
        if not isinstance(ref, dict):
            continue
        doi = ref.get("DOI") or ref.get("doi")
        if doi:
            ref_dois.append(str(doi))
    return _dedupe_dois(ref_dois)


def _collect_reference_dois(cr_data: dict, s2_data: dict) -> list[str]:
    s2_dois = _reference_dois_from_s2(s2_data)
    if s2_dois:
        return s2_dois
    return _reference_dois_from_crossref(cr_data)


def _is_arxiv_datacite_doi(doi: str) -> bool:
    """Return True if *doi* is arXiv's own DataCite DOI, not a publisher DOI."""
    normalized = (doi or "").strip().lower()
    return normalized.startswith("10.48550/arxiv.")


def _candidate_first_author_lastname(cr_data: dict, s2_data: dict, oa_data: dict) -> str:
    """Return the candidate first-author lastname from API search results."""
    if cr_data.get("author"):
        first = cr_data["author"][0]
        family = (first.get("family", "") or "").strip()
        if family:
            return family
        given_joined = f"{first.get('given', '')} {first.get('family', '')}".strip()
        if given_joined:
            return _extract_lastname(given_joined)
    if s2_data.get("authors"):
        name = (s2_data["authors"][0].get("name", "") or "").strip()
        if name:
            return _extract_lastname(name)
    if oa_data.get("authorships"):
        name = ((oa_data["authorships"][0].get("author", {}) or {}).get("display_name", "") or "").strip()
        if name:
            return _extract_lastname(name)
    return ""


def _candidate_year(cr_data: dict, s2_data: dict, oa_data: dict) -> int | None:
    """Return the candidate publication year from API search results."""
    for date_key in ("published-print", "published-online"):
        parts = (cr_data.get(date_key, {}) or {}).get("date-parts", [[]])
        if parts and parts[0] and parts[0][0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                break
    if s2_data.get("year"):
        try:
            return int(s2_data["year"])
        except (TypeError, ValueError):
            pass
    if oa_data.get("publication_year"):
        try:
            return int(oa_data["publication_year"])
        except (TypeError, ValueError):
            pass
    return None


def _search_result_consistent_with_local(meta: PaperMetadata, cr_data: dict, s2_data: dict, oa_data: dict) -> bool:
    """Reject title-search hits when both author and year clearly conflict.

    For title-driven enrichment we tolerate missing local fields, but when local extraction
    already has both a first-author lastname and a year, an API hit should not replace the
    paper with a different author *and* a far-away year.
    """
    local_last = (meta.first_author_lastname or "").strip().lower()
    candidate_last = _candidate_first_author_lastname(cr_data, s2_data, oa_data).strip().lower()
    local_year = meta.year
    candidate_year = _candidate_year(cr_data, s2_data, oa_data)

    author_conflict = bool(local_last and candidate_last and local_last != candidate_last)
    year_conflict = bool(local_year and candidate_year and abs(int(local_year) - int(candidate_year)) > 2)
    return not (author_conflict and year_conflict)


# ============================================================================
#  Relaxed Queries (Tier 3)
# ============================================================================


def _query_crossref_relaxed(title: str) -> dict:
    """Crossref title search with relaxed matching."""
    keywords = _title_keywords(title, max_words=8)
    params = {
        "query.title": keywords,
        "rows": "5",
        "select": "DOI,title,author,container-title,published-print,"
        "published-online,type,is-referenced-by-count,abstract",
    }
    url = f"{CR_BASE}?{urlencode(params)}"
    try:
        resp = SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code != 200:
            return {}
        items = resp.json().get("message", {}).get("items", [])
        for item in items:
            cr_title = (item.get("title") or [""])[0]
            if _fuzzy_title_match(title, cr_title) >= RELAXED_THRESHOLD:
                return item
        return {}
    except (requests.RequestException, ValueError) as e:
        _log.warning("[CR-relaxed] %s", e)
        return {}


def _query_oa_relaxed(title: str) -> dict:
    """OpenAlex title search with relaxed matching."""
    keywords = _title_keywords(title, max_words=8)
    params = {
        "filter": f"title.search:{keywords}",
        "per_page": "5",
        "select": "id,doi,title,publication_year,cited_by_count,authorships,primary_location,type,abstract_inverted_index",
    }
    url = f"{OA_BASE}?{urlencode(params)}"
    try:
        resp = SESSION.get(url, timeout=TIMEOUT)
        if resp.status_code != 200:
            return {}
        for item in resp.json().get("results", []):
            if _fuzzy_title_match(title, item.get("title", "")) >= RELAXED_THRESHOLD:
                return item
        return {}
    except (requests.RequestException, ValueError) as e:
        _log.warning("[OA-relaxed] %s", e)
        return {}


# ============================================================================
#  Enrichment
# ============================================================================


def _reconstruct_oa_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract text from OpenAlex inverted index format.

    Format: {"word": [pos0, pos1, ...], ...} → ordered sentence.
    """
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


def _apply_arxiv_metadata(meta: PaperMetadata, arxiv_data: dict) -> None:
    """Apply authoritative arXiv metadata without letting enrichers overwrite it."""
    if not arxiv_data:
        return
    if arxiv_data.get("title"):
        meta.title = arxiv_data["title"]
    if arxiv_data.get("authors"):
        authors = []
        for author in arxiv_data["authors"]:
            author = (author or "").strip()
            if "," in author:
                last, first = [part.strip() for part in author.split(",", 1)]
                author = f"{first} {last}".strip()
            authors.append(author)
        meta.authors = authors
        meta.first_author = meta.authors[0]
        meta.first_author_lastname = _extract_lastname(meta.first_author)
    if arxiv_data.get("year"):
        try:
            meta.year = int(arxiv_data["year"])
        except (TypeError, ValueError):
            pass
    if arxiv_data.get("abstract"):
        meta.abstract = arxiv_data["abstract"]
    if arxiv_data.get("doi") and not meta.doi and not _is_arxiv_datacite_doi(arxiv_data["doi"]):
        meta.doi = arxiv_data["doi"]
    official_arxiv_id = normalize_arxiv_ref(arxiv_data.get("arxiv_id", ""))
    if official_arxiv_id:
        meta.arxiv_id = official_arxiv_id


def enrich_metadata(meta: PaperMetadata) -> PaperMetadata:
    """通过 API 查询补全和覆盖元数据。

    查询策略（多层降级）:
      1. **Tier 1** — DOI 直查（三个 API 并行，无限流）
      2. **Tier 2** — Crossref + OA 标题搜索（严格匹配 ≥0.85）
      3. **Tier 3** — Crossref + OA 放宽搜索（匹配 ≥0.65）
      4. **Tier 4** — S2 标题搜索（最后手段，可能被限流）
      5. **Tier 5** — 本地数据（无 API 结果可用）

    合并优先级: Crossref > Semantic Scholar > OpenAlex > 正则提取。

    Args:
        meta: 已提取的元数据（至少需要 ``title`` 或 ``doi``）。

    Returns:
        同一个 :class:`PaperMetadata` 实例，字段已被 API 数据覆盖/补全。
    """
    cr_data: dict = {}
    s2_data: dict = {}
    oa_data: dict = {}
    arxiv_data: dict = {}
    arxiv_metadata_applied = False

    if meta.arxiv_id:
        normalized_arxiv_id = normalize_arxiv_ref(meta.arxiv_id)
        if normalized_arxiv_id:
            meta.arxiv_id = normalized_arxiv_id

    if meta.arxiv_id and _is_arxiv_datacite_doi(meta.doi):
        meta.doi = ""

    # ---- Tier 1: DOI lookup (all three, DOI queries are not rate-limited) ----
    if meta.doi:
        cr_data = query_crossref(doi=meta.doi)
        s2_data = query_semantic_scholar(doi=meta.doi)
        oa_data = query_openalex(doi=meta.doi)
        if cr_data or s2_data or oa_data:
            # Guard: verify API-returned title matches local title (prevent DOI hallucination)
            api_title = (
                (cr_data.get("title", [None]) or [None])[0]
                if cr_data
                else (s2_data.get("title") if s2_data else (oa_data.get("title") if oa_data else None))
            )
            title_score = _fuzzy_title_match(meta.title, api_title) if (meta.title and api_title) else 1.0
            if title_score < RELAXED_THRESHOLD:
                _log.debug("DOI title mismatch (score=%.2f), discarding DOI", title_score)
                meta.doi = ""
                cr_data, s2_data, oa_data = {}, {}, {}
            else:
                meta.extraction_method = "doi_lookup"

    # ---- Tier 1.5: arXiv ID lookup (official metadata + S2 enrichment) ----
    if not cr_data and not s2_data and not oa_data and meta.arxiv_id:
        _log.debug("Trying arXiv ID lookup: %s", meta.arxiv_id)
        arxiv_data = get_arxiv_paper(meta.arxiv_id)
        s2_data = query_semantic_scholar(arxiv_id=meta.arxiv_id)
        if arxiv_data or s2_data:
            arxiv_metadata_applied = bool(arxiv_data)
            _apply_arxiv_metadata(meta, arxiv_data)
            ext_ids = s2_data.get("externalIds") or {}
            if ext_ids.get("DOI") and not meta.doi and not _is_arxiv_datacite_doi(ext_ids["DOI"]):
                meta.doi = ext_ids["DOI"]
                _log.debug("arXiv → DOI resolved: %s", meta.doi)
            if meta.doi:
                cr_data = query_crossref(doi=meta.doi)
                oa_data = query_openalex(doi=meta.doi)
            meta.extraction_method = "arxiv_lookup"

    # ---- Tier 2: Title search via Crossref + OA (no rate limit) ----
    if not cr_data and not s2_data and not oa_data and meta.title:
        _log.debug("No DOI match, trying title search")
        cr_data = query_crossref(title=meta.title)
        oa_data = query_openalex(title=meta.title)

        # If Crossref found a DOI, use it for S2 + OA DOI lookup
        found_doi = ""
        if cr_data and cr_data.get("DOI"):
            found_doi = cr_data["DOI"]
        elif oa_data and oa_data.get("doi"):
            found_doi = oa_data["doi"].replace("https://doi.org/", "")

        if found_doi:
            if not s2_data:
                s2_data = query_semantic_scholar(doi=found_doi)
            if not oa_data:
                oa_data = query_openalex(doi=found_doi)

        if cr_data or s2_data or oa_data:
            if not _search_result_consistent_with_local(meta, cr_data, s2_data, oa_data):
                _log.debug("title search mismatch: discarding candidate due to author/year conflict")
                cr_data, s2_data, oa_data = {}, {}, {}
            else:
                meta.extraction_method = "title_search"

    # ---- Tier 3: Relaxed title search (Crossref + OA, lower threshold) ----
    if not cr_data and not s2_data and not oa_data and meta.title:
        _log.debug("Strict match failed, trying relaxed search")
        cr_data = _query_crossref_relaxed(meta.title)
        oa_data = _query_oa_relaxed(meta.title)

        # Again, use found DOI for S2
        found_doi = ""
        if cr_data and cr_data.get("DOI"):
            found_doi = cr_data["DOI"]
        elif oa_data and oa_data.get("doi"):
            found_doi = oa_data["doi"].replace("https://doi.org/", "")
        if found_doi and not s2_data:
            s2_data = query_semantic_scholar(doi=found_doi)

        if cr_data or s2_data or oa_data:
            if not _search_result_consistent_with_local(meta, cr_data, s2_data, oa_data):
                _log.debug("relaxed title search mismatch: discarding candidate due to author/year conflict")
                cr_data, s2_data, oa_data = {}, {}, {}
            else:
                meta.extraction_method = "title_search_relaxed"

    # ---- Tier 4: S2 title search (last resort, may be rate-limited) ----
    if not cr_data and not s2_data and not oa_data and meta.title:
        _log.debug("Trying S2 title search (last resort)")
        s2_data = query_semantic_scholar(title=meta.title)
        if s2_data:
            if not _search_result_consistent_with_local(meta, {}, s2_data, {}):
                _log.debug("S2 title search mismatch: discarding candidate due to author/year conflict")
                s2_data = {}
            else:
                meta.extraction_method = "title_search_s2"

    # ---- Tier 5: local_only ----
    if arxiv_metadata_applied and "arxiv" not in meta.api_sources:
        meta.api_sources.append("arxiv")

    if not cr_data and not s2_data and not oa_data and not arxiv_metadata_applied:
        meta.extraction_method = meta.extraction_method or "local_only"
        return meta

    # ---- Merge strategy: API data OVERRIDES md-extracted data ----
    # Priority for authors/title/year/journal: Crossref > S2 > OA > md fallback
    # For DOI/IDs/citations: always collect from all sources

    # ---- 1. Crossref (highest quality for journal/authors/type) ----
    if cr_data:
        meta.api_sources.append("crossref")
        meta.citation_count_crossref = cr_data.get("is-referenced-by-count")
        if cr_data.get("DOI"):
            meta.doi = cr_data["DOI"]
        meta.crossref_doi = cr_data.get("DOI", "")
        # Year: prefer published-print, fallback published-online
        for date_key in ("published-print", "published-online"):
            parts = cr_data.get(date_key, {}).get("date-parts", [[]])
            if parts and parts[0] and parts[0][0]:
                meta.year = parts[0][0]
                break
        # Title — Crossref is authoritative, override md-extracted title
        cr_titles = cr_data.get("title", [])
        if cr_titles and cr_titles[0]:
            meta.title = cr_titles[0]
        # Journal (Crossref has standardized container-title)
        ct = cr_data.get("container-title", [])
        if ct:
            meta.journal = ct[0]
        # Authors — Crossref is the most authoritative (has structured given/family)
        if cr_data.get("author"):
            meta.authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in cr_data["author"]]
            meta.first_author = meta.authors[0]
            # Use Crossref's structured family name directly (handles double
            # surnames like García-Villalba, Ouyang, etc. that _extract_lastname misses)
            first_a = cr_data["author"][0]
            meta.first_author_lastname = first_a.get("family", "") or _extract_lastname(meta.first_author)
        # Paper type
        if cr_data.get("type"):
            meta.paper_type = cr_data["type"]
        # Bibliographic details
        if cr_data.get("volume"):
            meta.volume = cr_data["volume"]
        if cr_data.get("issue"):
            meta.issue = cr_data["issue"]
        if cr_data.get("page"):
            meta.pages = cr_data["page"]
        elif cr_data.get("article-number"):
            meta.pages = cr_data["article-number"]
        if cr_data.get("publisher"):
            meta.publisher = cr_data["publisher"]
        if cr_data.get("ISSN"):
            issns = cr_data["ISSN"]
            if isinstance(issns, list) and issns:
                meta.issn = issns[0]
            elif isinstance(issns, str):
                meta.issn = issns

    # ---- 2. Semantic Scholar (best abstract, good authors) ----
    if s2_data:
        meta.api_sources.append("semantic_scholar")
        meta.citation_count_s2 = s2_data.get("citationCount")
        meta.s2_paper_id = s2_data.get("paperId", "")
        ext_ids = s2_data.get("externalIds") or {}
        if not meta.doi and ext_ids.get("DOI") and not _is_arxiv_datacite_doi(ext_ids["DOI"]):
            meta.doi = ext_ids["DOI"]
        if not meta.arxiv_id and ext_ids.get("ArXiv"):
            meta.arxiv_id = ext_ids["ArXiv"]
        # Title: override only if Crossref didn't provide one
        if not cr_data and not arxiv_metadata_applied and s2_data.get("title"):
            meta.title = s2_data["title"]
        if not meta.year and s2_data.get("year"):
            meta.year = s2_data["year"]
        if not meta.journal and s2_data.get("venue"):
            meta.journal = s2_data["venue"]
        # Authors: override only if Crossref didn't provide them
        if not cr_data and not arxiv_metadata_applied and s2_data.get("authors"):
            meta.authors = [a.get("name", "") for a in s2_data["authors"]]
            if meta.authors:
                meta.first_author = meta.authors[0]
                meta.first_author_lastname = _extract_lastname(meta.first_author)
        # Paper type
        if not meta.paper_type and s2_data.get("publicationTypes"):
            meta.paper_type = s2_data["publicationTypes"][0]
        # Abstract — S2 gives clean plain text (preferred)
        if s2_data.get("abstract") and not (arxiv_metadata_applied and arxiv_data.get("abstract")):
            meta.abstract = s2_data["abstract"]
    # ---- 3. Crossref abstract (strip HTML/JATS tags, collapse whitespace) ----
    if cr_data and not meta.abstract and cr_data.get("abstract"):
        raw = cr_data["abstract"]
        raw = re.sub(r"<[^>]+>", "", raw)  # strip HTML/JATS tags
        raw = re.sub(r"[\n\t\r]+", " ", raw)  # collapse newlines/tabs
        raw = re.sub(r"\s{2,}", " ", raw)  # collapse multiple spaces
        meta.abstract = raw.strip()

    ref_dois = _collect_reference_dois(cr_data, s2_data)
    if ref_dois:
        meta.references = ref_dois

    # ---- 4. OpenAlex (fallback for everything) ----
    if oa_data:
        meta.api_sources.append("openalex")
        meta.citation_count_openalex = oa_data.get("cited_by_count")
        meta.openalex_id = oa_data.get("id", "")
        if not meta.doi and oa_data.get("doi"):
            oa_doi = oa_data["doi"].replace("https://doi.org/", "")
            if not _is_arxiv_datacite_doi(oa_doi):
                meta.doi = oa_doi
        # Title: override only if neither Crossref nor S2 provided one
        if not cr_data and not s2_data and oa_data.get("title"):
            meta.title = oa_data["title"]
        if not meta.year and oa_data.get("publication_year"):
            meta.year = oa_data["publication_year"]
        # Authors: override only if neither Crossref nor S2 provided them
        if not cr_data and not s2_data and oa_data.get("authorships"):
            meta.authors = [a.get("author", {}).get("display_name", "") for a in oa_data["authorships"]]
            if meta.authors:
                meta.first_author = meta.authors[0]
                meta.first_author_lastname = _extract_lastname(meta.first_author)
        # Journal from primary_location
        if not meta.journal:
            loc = oa_data.get("primary_location", {}) or {}
            source = loc.get("source", {}) or {}
            meta.journal = source.get("display_name", "")
        # Paper type
        if not meta.paper_type and oa_data.get("type"):
            meta.paper_type = oa_data["type"]
        # Bibliographic details from OA (fallback)
        biblio = oa_data.get("biblio", {}) or {}
        if not meta.volume and biblio.get("volume"):
            meta.volume = biblio["volume"]
        if not meta.issue and biblio.get("issue"):
            meta.issue = biblio["issue"]
        if not meta.pages:
            fp, lp = biblio.get("first_page", ""), biblio.get("last_page", "")
            if fp:
                meta.pages = f"{fp}-{lp}" if lp and lp != fp else fp
        if not meta.publisher:
            loc = oa_data.get("primary_location", {}) or {}
            source = loc.get("source", {}) or {}
            if source.get("host_organization_name"):
                meta.publisher = source["host_organization_name"]
        if not meta.issn:
            loc = oa_data.get("primary_location", {}) or {}
            source = loc.get("source", {}) or {}
            issns = source.get("issn", [])
            if issns:
                meta.issn = issns[0]
        # Abstract from OA inverted index (last resort)
        if not meta.abstract and oa_data.get("abstract_inverted_index"):
            meta.abstract = _reconstruct_oa_abstract(oa_data["abstract_inverted_index"])

    return meta
