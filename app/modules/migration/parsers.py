import csv
import re
from dataclasses import dataclass
from io import StringIO

URL_RE = re.compile(r"https?://[^\s|)>]+")


@dataclass(frozen=True)
class ShortlistRow:
    url: str
    bucket: str
    company: str
    title: str
    location: str
    posted: str
    source: str
    eligibility: str
    reason: str


@dataclass(frozen=True)
class LegacyPipelineRow:
    url: str
    company: str
    title: str
    location: str
    done: bool
    labels: dict[str, str]


def markdown_table(content: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in content.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    headers = [part.strip().casefold() for part in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        values = [part.strip() for part in line.strip("|").split("|")]
        if len(values) != len(headers):
            continue
        rows.append(dict(zip(headers, values, strict=True)))
    return rows


def shortlist_rows(content: str) -> tuple[dict[str, ShortlistRow], bool]:
    result: dict[str, ShortlistRow] = {}
    bucket: str | None = None
    recognized = False
    current_company = ""
    current_title = ""
    fields: dict[str, str] = {}

    def commit() -> None:
        url = fields.get("direct application url") or fields.get("url")
        if bucket and current_company and url:
            result[url] = ShortlistRow(url, bucket, current_company, current_title, fields.get("location", ""), fields.get("posted", ""), fields.get("source", ""), fields.get("eligibility", "Uncertain"), fields.get("why it may fit") or fields.get("fit", ""))

    for line in content.splitlines():
        section = re.match(r"^##\s+(.+)$", line)
        if section:
            commit()
            current_company = ""
            current_title = ""
            fields = {}
            heading = section.group(1)
            if re.search(r"worth evaluating|worth a look|pass", heading, re.I):
                bucket = "worth"
                recognized = True
            elif re.search(r"uncertain|marginal|maybe", heading, re.I):
                bucket = "uncertain"
                recognized = True
            else:
                bucket = None
            continue
        item = re.match(r"^###\s+(.+?)\s+[—-]\s+(.+)$", line)
        if item:
            commit()
            current_company, current_title = item.group(1).strip(), item.group(2).strip()
            fields = {}
            continue
        field = re.match(r"^[-*]\s+([^:]+):\s*(.+)$", line)
        if field and current_company:
            fields[field.group(1).strip().casefold()] = field.group(2).strip()
            continue
        compact = re.match(r"^(.*),\s*(https?://[^,\s]+),\s*([^,]+),\s*(.+)$", line) if bucket and not current_company else None
        if compact:
            prefix = [part.strip() for part in re.split(r",\s*", compact.group(1)) if part.strip()]
            if len(prefix) >= 5:
                company = prefix.pop(0)
                source = prefix.pop()
                posted = prefix.pop()
                location = prefix.pop()
                url = compact.group(2)
                result[url] = ShortlistRow(url, bucket, company, ", ".join(prefix), location, posted, source, compact.group(3).strip(), compact.group(4).strip())
    commit()
    return result, recognized


def pipeline_rows(content: str) -> list[LegacyPipelineRow]:
    rows: list[LegacyPipelineRow] = []
    for line in content.splitlines():
        match = re.match(r"^\s*-\s*\[([ xX])\]\s*(.+)$", line)
        if not match:
            continue
        values = [value.strip() for value in match.group(2).split("|")]
        if len(values) < 3 or not values[0].startswith(("http://", "https://")):
            continue
        positional = values[:3]
        labels: dict[str, str] = {}
        location = ""
        for value in values[3:]:
            label = re.match(r"^([a-z][a-z_-]*):\s*(.*)$", value, re.I)
            if label:
                labels[label.group(1).casefold()] = label.group(2).strip()
            elif not location:
                location = value
        rows.append(LegacyPipelineRow(positional[0], positional[1], positional[2], location, match.group(1).casefold() == "x", labels))
    return rows


def tsv_rows(content: str) -> list[dict[str, str]]:
    if not content.strip():
        return []
    return list(csv.DictReader(StringIO(content), delimiter="\t"))


def pdf_index_rows(content: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in content.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        values = line.split("\t")
        if len(values) < 3 or not values[0].strip().isdigit():
            continue
        rows.append({"report": values[0].strip(), "pdf": values[1].strip(), "html": values[2].strip(), "format": values[3].strip() if len(values) > 3 else "a4", "date": values[4].strip() if len(values) > 4 else ""})
    return rows


def first_url(*values: str) -> str | None:
    for value in values:
        match = URL_RE.search(value or "")
        if match:
            return match.group(0)
    return None


def score_value(value: str) -> float | None:
    match = re.search(r"([0-5](?:\.\d+)?)", value or "")
    return float(match.group(1)) if match else None


def report_number(value: str) -> int | None:
    match = re.search(r"(?:reports/)?0*(\d+)-", value or "") or re.fullmatch(r"0*(\d+)", (value or "").strip())
    return int(match.group(1)) if match else None
