"""Tests for scholaraio.ingest.metadata._api arXiv-specific enrichment behavior."""

from __future__ import annotations

from scholaraio.ingest.metadata._api import enrich_metadata
from scholaraio.ingest.metadata._models import PaperMetadata


def test_enrich_metadata_prefers_arxiv_year_over_s2_year_for_preprint(monkeypatch):
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.get_arxiv_paper",
        lambda arxiv_id: {
            "title": "Direct numerical simulation of out-scale-actuated spanwise wall oscillation in turbulent boundary layers",
            "authors": ["Jizhong Zhang", "Fazle Hussain", "Jie Yao"],
            "year": "2026",
            "abstract": "Official arXiv abstract.",
            "arxiv_id": "2603.25200v1",
            "doi": "",
        },
    )
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_crossref", lambda **kwargs: {})
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_openalex", lambda **kwargs: {})

    def fake_s2(*, doi="", title="", arxiv_id=""):
        assert arxiv_id == "2603.25200"
        return {
            "paperId": "paper-123",
            "title": "Direct numerical simulation of out-scale-actuated spanwise wall oscillation in turbulent boundary layers",
            "year": 2021,
            "citationCount": 0,
            "externalIds": {"ArXiv": "2603.25200"},
            "authors": [{"name": "Jizhong Zhang"}],
            "venue": "",
            "publicationTypes": ["Review"],
            "references": [],
        }

    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_semantic_scholar", fake_s2)

    meta = PaperMetadata(
        title="Direct numerical simulation of out-scale-actuated spanwise wall oscillation in turbulent boundary layers",
        arxiv_id="2603.25200",
    )

    enrich_metadata(meta)

    assert meta.year == 2026
    assert meta.extraction_method == "arxiv_lookup"
    assert meta.abstract == "Official arXiv abstract."


def test_enrich_metadata_normalizes_arxiv_comma_separated_authors(monkeypatch):
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.get_arxiv_paper",
        lambda arxiv_id: {
            "title": "Direct numerical simulation of out-scale-actuated spanwise wall oscillation in turbulent boundary layers",
            "authors": ["Zhang, Jizhong", "Hussain, Fazle", "Yao, Jie"],
            "year": "2026",
            "abstract": "Official arXiv abstract.",
            "arxiv_id": "2603.25200v1",
            "doi": "",
        },
    )
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_crossref", lambda **kwargs: {})
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_openalex", lambda **kwargs: {})
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.query_semantic_scholar",
        lambda **kwargs: {"externalIds": {"ArXiv": "2603.25200"}, "references": []},
    )

    meta = PaperMetadata(title="Test", arxiv_id="2603.25200")

    enrich_metadata(meta)

    assert meta.authors == ["Jizhong Zhang", "Fazle Hussain", "Jie Yao"]
    assert meta.first_author == "Jizhong Zhang"
    assert meta.first_author_lastname == "Zhang"


def test_enrich_metadata_ignores_arxiv_datacite_doi_for_preprint(monkeypatch):
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.get_arxiv_paper",
        lambda arxiv_id: {
            "title": "Direct numerical simulation of out-scale-actuated spanwise wall oscillation in turbulent boundary layers",
            "authors": ["Jizhong Zhang", "Fazle Hussain", "Jie Yao"],
            "year": "2026",
            "abstract": "Official arXiv abstract.",
            "arxiv_id": "2603.25200v1",
            "doi": "10.48550/arXiv.2603.25200",
        },
    )
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_crossref", lambda **kwargs: {})
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.query_openalex",
        lambda **kwargs: {"doi": "https://doi.org/10.48550/arXiv.2603.25200", "id": "https://openalex.org/W1"},
    )
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.query_semantic_scholar",
        lambda **kwargs: {
            "externalIds": {"ArXiv": "2603.25200", "DOI": "10.48550/arXiv.2603.25200"},
            "references": [],
            "paperId": "paper-123",
        },
    )

    meta = PaperMetadata(title="Test", arxiv_id="2603.25200")

    enrich_metadata(meta)

    assert meta.doi == ""
    assert meta.arxiv_id == "2603.25200"
    assert meta.extraction_method == "arxiv_lookup"


def test_enrich_metadata_uses_s2_title_and_authors_when_arxiv_lookup_returns_only_s2(monkeypatch):
    monkeypatch.setattr("scholaraio.ingest.metadata._api.get_arxiv_paper", lambda arxiv_id: {})
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_crossref", lambda **kwargs: {})
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_openalex", lambda **kwargs: {})
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.query_semantic_scholar",
        lambda **kwargs: {
            "title": "Recovered from Semantic Scholar",
            "authors": [{"name": "Alice Example"}, {"name": "Bob Example"}],
            "year": 2024,
            "venue": "arXiv",
            "abstract": "Recovered abstract.",
            "externalIds": {"ArXiv": "2603.25200"},
            "references": [],
            "paperId": "paper-123",
        },
    )

    meta = PaperMetadata(title="Original OCR Title", authors=["Wrong Author"], arxiv_id="2603.25200")

    enrich_metadata(meta)

    assert meta.title == "Recovered from Semantic Scholar"
    assert meta.authors == ["Alice Example", "Bob Example"]
    assert meta.first_author == "Alice Example"
    assert meta.extraction_method == "arxiv_lookup"


def test_enrich_metadata_normalizes_versioned_arxiv_id_before_arxiv_and_s2_lookup(monkeypatch):
    seen: dict[str, str] = {}

    def fake_get_arxiv_paper(arxiv_id: str):
        seen["arxiv"] = arxiv_id
        return {
            "title": "Normalized arXiv lookup",
            "authors": ["Alice Example"],
            "year": "1999",
            "abstract": "Official arXiv abstract.",
            "arxiv_id": arxiv_id,
            "doi": "",
        }

    def fake_s2(*, doi="", title="", arxiv_id=""):
        seen["s2"] = arxiv_id
        return {"externalIds": {"ArXiv": arxiv_id}, "references": [], "paperId": "paper-123"}

    monkeypatch.setattr("scholaraio.ingest.metadata._api.get_arxiv_paper", fake_get_arxiv_paper)
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_crossref", lambda **kwargs: {})
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_openalex", lambda **kwargs: {})
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_semantic_scholar", fake_s2)

    meta = PaperMetadata(title="Original OCR Title", arxiv_id="hep-th/9901001v3")

    enrich_metadata(meta)

    assert seen == {"arxiv": "hep-th/9901001", "s2": "hep-th/9901001"}
    assert meta.arxiv_id == "hep-th/9901001"
    assert meta.extraction_method == "arxiv_lookup"


def test_enrich_metadata_records_arxiv_as_api_source_when_only_arxiv_lookup_succeeds(monkeypatch):
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.get_arxiv_paper",
        lambda arxiv_id: {
            "title": "Official arXiv only result",
            "authors": ["Alice Example"],
            "year": "1999",
            "abstract": "Official arXiv abstract.",
            "arxiv_id": arxiv_id,
            "doi": "",
        },
    )
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_crossref", lambda **kwargs: {})
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_openalex", lambda **kwargs: {})
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_semantic_scholar", lambda **kwargs: {})

    meta = PaperMetadata(title="Original OCR Title", arxiv_id="hep-th/9901001v3")

    enrich_metadata(meta)

    assert meta.api_sources == ["arxiv"]
    assert meta.extraction_method == "arxiv_lookup"


def test_enrich_metadata_falls_back_to_crossref_reference_dois_when_s2_references_missing(monkeypatch):
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.query_crossref",
        lambda **kwargs: (
            {
                "DOI": "10.1234/example",
                "title": ["Particle-laden channel flow"],
                "container-title": ["Journal of Fluid Mechanics"],
                "author": [{"given": "Alice", "family": "Example"}],
                "published-print": {"date-parts": [[2024]]},
                "reference": [
                    {"DOI": "10.1017/jfm.1"},
                    {"DOI": "10.1017/jfm.2"},
                    {"unstructured": "No DOI here"},
                    {"doi": "10.1017/JFM.1"},
                ],
            }
        ),
    )
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.query_semantic_scholar",
        lambda **kwargs: {
            "paperId": "paper-123",
            "title": "Particle-laden channel flow",
            "externalIds": {"DOI": "10.1234/example"},
            "references": [{"externalIds": {}}],
        },
    )
    monkeypatch.setattr("scholaraio.ingest.metadata._api.query_openalex", lambda **kwargs: {})

    meta = PaperMetadata(title="Particle-laden channel flow", doi="10.1234/example")

    enrich_metadata(meta)

    assert meta.references == ["10.1017/jfm.1", "10.1017/jfm.2"]


def test_enrich_metadata_rejects_title_search_hit_when_author_and_year_both_conflict(monkeypatch):
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.query_crossref",
        lambda **kwargs: (
            {
                "DOI": "10.1002/9781118527221.ch2",
                "title": ["Structure of Turbulent Boundary Layers"],
                "author": [{"given": "Ronald J.", "family": "Adrian"}],
                "published-print": {"date-parts": [[2013]]},
                "container-title": ["Coherent Flow Structures at Earth's Surface"],
                "type": "other",
                "is-referenced-by-count": 5,
                "abstract": "Wrong candidate abstract.",
            }
            if kwargs.get("title")
            else {}
        ),
    )
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.query_openalex",
        lambda **kwargs: (
            {
                "doi": "https://doi.org/10.1002/9781118527221.ch2",
                "title": "Structure of Turbulent Boundary Layers",
                "publication_year": 2013,
                "authorships": [{"author": {"display_name": "Ronald J. Adrian"}}],
            }
            if kwargs.get("title")
            else {}
        ),
    )
    monkeypatch.setattr(
        "scholaraio.ingest.metadata._api.query_semantic_scholar",
        lambda **kwargs: {},
    )

    meta = PaperMetadata(
        title="The structure of turbulent boundary layers",
        authors=["S. J. Kline", "W. C. Reynolds"],
        first_author="S. J. Kline",
        first_author_lastname="Kline",
        year=1967,
    )

    enrich_metadata(meta)

    assert meta.doi == ""
    assert meta.first_author_lastname == "Kline"
    assert meta.year == 1967
    assert meta.extraction_method == "local_only"
