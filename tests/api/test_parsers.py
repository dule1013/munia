from app.modules.jobs.service import canonicalize_url
from app.modules.migration.parsers import markdown_table, pipeline_rows, report_number, score_value


def test_url_normalization_removes_tracking_and_fragment():
    assert canonicalize_url("HTTPS://Jobs.Example.com/role/?utm_source=x&team=eng#apply") == "https://jobs.example.com/role?team=eng"


def test_pipeline_parser_preserves_candidate_metadata():
    rows = pipeline_rows("- [ ] https://jobs.example.com/1 | Acme | Director | Spain | source: greenhouse | eligibility: eligible | reason: multi-team scope")
    assert len(rows) == 1
    assert rows[0].location == "Spain"
    assert rows[0].labels == {"source": "greenhouse", "eligibility": "eligible", "reason": "multi-team scope"}


def test_tracker_parser_and_identifiers():
    rows = markdown_table("| # | Company | Role | Score | Report |\n|---|---|---|---|---|\n| 2 | Acme | Director | 4.6/5 | [3](../reports/003-acme.md) |")
    assert rows[0]["company"] == "Acme"
    assert score_value(rows[0]["score"]) == 4.6
    assert report_number(rows[0]["report"]) == 3
