#!/usr/bin/env python3
"""Collect 2024-2025 MARL papers from ICLR, ICML and NeurIPS.

The official conference proceedings supply reproducible accepted-paper indexes.
PDFs are downloaded from proceedings.iclr.cc, proceedings.mlr.press, or
proceedings.neurips.cc; arXiv is only a recorded fallback for a blocked host.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path.home() / "Desktop" / "marl-top3-2024-2025"
YEARS = (2024, 2025)
VENUES = ("ICLR", "ICML", "NeurIPS")
USER_AGENT = "Corpus2Node-MARL-gold-collector/1.0 (research corpus)"

# High precision first, then broad recall. The final manifest keeps the score
# and matched rules so a human can audit every inclusion/exclusion.
DIRECT_PATTERNS = {
    "multi_agent_rl": r"\bmulti[- ]?agent\b.{0,80}\breinforcement\b|\breinforcement\b.{0,80}\bmulti[- ]?agent\b|\bMARL\b",
    "multi_agent_learning": r"\bmulti[- ]?agent\b.{0,50}\b(learning|policy|coordination)\b|\b(learning|policy|coordination)\b.{0,50}\bmulti[- ]?agent\b",
    "markov_game": r"\b(markov|stochastic) games?\b",
    "dec_pomdp": r"\bdec[- ]?pomdp\b|decentralized partially observable",
    "mean_field": r"\bmean[- ]field\b.{0,60}\b(reinforcement|control|game|policy)\b",
    "multi_player_rl": r"\bmulti[- ]?player\b.{0,60}\b(reinforcement|policy|learning)\b",
}
BROAD_PATTERNS = {
    "cooperation": r"\b(cooperat|coordina|collaborat|team)[a-z-]*\b",
    "opponent": r"\b(opponent|adversar|zero[- ]sum|general[- ]sum|equilibri)[a-z-]*\b",
    "communication": r"\b(agent communication|communication learning|emergent communication)\b",
    "credit_assignment": r"\b(credit assignment|value decomposition|counterfactual)\b",
    "agent_population": r"\b(agent population|population of agents|many agents|agent interactions?)\b",
}
RL_CONTEXT = re.compile(
    r"\b(reinforcement learning|policy|policies|reward|value function|q[- ]?learning|actor[- ]?critic|trajectory|rollout)\b",
    re.I,
)
EXCLUDE_PATTERNS = {
    "llm_agents_without_rl": r"\b(large language model|LLM|language agents?)\b",
    "federated_learning": r"\bfederated learning\b",
    "multi_agent_path_only": r"\bmulti[- ]agent path finding\b",
}


def fetch_bytes(url: str, *, attempts: int = 2) -> tuple[bytes, str]:
    completed = subprocess.run(
        [
            "curl", "--compressed", "-L", "--fail", "--silent", "--show-error",
            "--retry", str(max(0, attempts - 1)), "--max-time", "180",
            "-A", USER_AGENT, url,
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode == 0:
        return completed.stdout, "application/octet-stream"
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as response:
                return response.read(), response.headers.get_content_type()
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(5)
    raise AssertionError("unreachable")


def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {key: value or "" for key, value in attrs}


class _ConferenceIndexParser(HTMLParser):
    """Small dependency-free parser for the three accepted-paper indexes."""

    def __init__(self, venue: str, year: int, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.venue = venue
        self.year = year
        self.base_url = base_url
        self.records: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.container_tag = ""
        self.depth = 0
        self.capture = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = _attrs(attrs)
        classes = set(values.get("class", "").split())
        starts = (
            self.venue == "ICML" and tag == "div" and "paper" in classes
        ) or (
            self.venue in {"ICLR", "NeurIPS"} and tag == "li" and "conference" in classes
        ) or (
            self.venue == "ICLR" and tag == "li" and {"entry", "inproceedings"} <= classes
        )
        if starts and self.current is None:
            self.current = {
                "paper_id": values.get("id", ""),
                "title": "",
                "authors": [],
                "venue": self.venue,
                "year": self.year,
                "official_url": "",
                "pdf_url": "",
            }
            self.container_tag = tag
            self.depth = 1
        elif self.current is not None and tag == self.container_tag:
            self.depth += 1
        if self.current is None:
            return
        if self.venue == "ICML":
            if tag == "p" and "title" in classes:
                self.capture = "title"
            elif tag == "span" and "authors" in classes:
                self.capture = "authors_text"
            elif tag == "a":
                href = urllib.parse.urljoin(self.base_url, values.get("href", ""))
                if href.endswith(".pdf") and not self.current["pdf_url"]:
                    self.current["pdf_url"] = href
                elif href.endswith(".html") and not self.current["official_url"]:
                    self.current["official_url"] = href
        elif self.venue in {"ICLR", "NeurIPS"}:
            if tag == "a" and "Abstract" in values.get("href", ""):
                self.current["official_url"] = urllib.parse.urljoin(self.base_url, values["href"])
                if values.get("title") == "paper title":
                    self.capture = "title"
            elif tag == "span" and "paper-authors" in classes:
                self.capture = "authors_text"
        else:
            if tag == "span" and "title" in classes:
                self.capture = "title"
            elif tag == "span" and values.get("itemprop") == "author":
                self.capture = "author"
            elif tag == "a" and "openreview.net/forum" in values.get("href", ""):
                self.current["official_url"] = values["href"]

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if tag in {"p", "span", "a"}:
            self.capture = ""
        if tag == self.container_tag:
            self.depth -= 1
            if self.depth == 0:
                self._finish()

    def handle_data(self, data: str) -> None:
        if self.current is None or not self.capture:
            return
        if self.capture == "author":
            value = " ".join(data.split())
            if value:
                self.current["authors"].append(value)
        else:
            self.current[self.capture] = self.current.get(self.capture, "") + data

    def _finish(self) -> None:
        assert self.current is not None
        record = self.current
        record["title"] = " ".join(record["title"].split()).rstrip(".")
        authors_text = " ".join(record.pop("authors_text", "").split())
        if authors_text and not record["authors"]:
            record["authors"] = [part.strip() for part in re.split(r",|\band\b", authors_text) if part.strip()]
        if self.venue in {"ICLR", "NeurIPS"} and record["official_url"]:
            record["pdf_url"] = (
                record["official_url"]
                .replace("/hash/", "/file/")
                .replace("-Abstract-Conference.html", "-Paper-Conference.pdf")
                .replace("-Abstract-", "-Paper-")
                .replace("Abstract.html", "Paper.pdf")
            )
        if record["title"] and record["official_url"]:
            if not record["paper_id"]:
                record["paper_id"] = hashlib.sha1(record["official_url"].encode()).hexdigest()[:16]
            self.records.append(record)
        self.current = None
        self.container_tag = ""
        self.capture = ""


def conference_records(venue: str, year: int, metadata_dir: Path) -> list[dict[str, Any]]:
    if venue == "ICML":
        volume = {2024: 235, 2025: 267}[year]
        url = f"https://proceedings.mlr.press/v{volume}/"
    elif venue == "NeurIPS":
        url = f"https://proceedings.neurips.cc/paper_files/paper/{year}"
    else:
        url = f"https://proceedings.iclr.cc/paper_files/paper/{year}"
    body, _ = fetch_bytes(url, attempts=3)
    (metadata_dir / f"{venue.lower()}-{year}-accepted.html").write_bytes(body)
    parser = _ConferenceIndexParser(venue, year, url)
    parser.feed(body.decode("utf-8", errors="replace"))
    return parser.records


def score_record(record: dict[str, Any], *, include_abstract: bool = True) -> dict[str, Any]:
    text = record["title"]
    if include_abstract:
        text += " " + record.get("abstract", "")
    matches = []
    score = 0
    for name, pattern in DIRECT_PATTERNS.items():
        if re.search(pattern, text, re.I | re.S):
            matches.append(name)
            score += 8
    broad = []
    for name, pattern in BROAD_PATTERNS.items():
        if re.search(pattern, text, re.I | re.S):
            broad.append(name)
    if broad and RL_CONTEXT.search(text):
        matches.extend(broad)
        score += 3 * len(broad) + 3
    exclusions = [name for name, pattern in EXCLUDE_PATTERNS.items() if re.search(pattern, text, re.I)]
    if exclusions and not any(name in matches for name in DIRECT_PATTERNS):
        score -= 6
    record["relevance_score"] = score
    record["matched_rules"] = matches
    record["exclusion_flags"] = exclusions
    record["scope_tier"] = (
        "core_marl"
        if any(value in matches for value in DIRECT_PATTERNS if value != "multi_agent_learning")
        else "adjacent_manual_review"
    )
    return record


def _worth_enriching(record: dict[str, Any]) -> bool:
    title = record["title"]
    return any(re.search(pattern, title, re.I) for pattern in DIRECT_PATTERNS.values())


def official_metadata(record: dict[str, Any]) -> dict[str, Any]:
    url = record.get("official_url", "")
    if not url:
        return record
    try:
        body, content_type = fetch_bytes(url)
    except Exception as exc:
        record["metadata_error"] = f"{type(exc).__name__}: {exc}"
        return record
    text = body.decode("utf-8", errors="replace") if body.lstrip().startswith(b"<") else ""
    record["abstract"] = _extract_abstract(text)
    record["pdf_url"] = _pdf_url(record, text) or record.get("pdf_url", "")
    return record


def _extract_abstract(text: str) -> str:
    meta_patterns = [
        r'<meta[^>]+name=["\']citation_abstract["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
    ]
    for pattern in meta_patterns:
        match = re.search(pattern, text, re.I | re.S)
        if match:
            return _clean_html(match.group(1))
    for pattern in (
        r'<h2[^>]*>\s*Abstract\s*</h2>\s*<p[^>]*>(.*?)</p>',
        r'<h3[^>]*>\s*Abstract\s*</h3>\s*<p[^>]*>(.*?)</p>',
        r'<div[^>]+id=["\']abstract["\'][^>]*>(.*?)</div>',
        r'"abstract"\s*:\s*\{?\s*"value"\s*:\s*"((?:\\.|[^"\\])*)"',
    ):
        match = re.search(pattern, text, re.I | re.S)
        if match:
            value = match.group(1)
            if "\\" in value:
                try:
                    value = json.loads(f'"{value}"')
                except json.JSONDecodeError:
                    pass
            return _clean_html(value)
    return ""


def _pdf_url(record: dict[str, Any], text: str) -> str:
    url = record.get("official_url", "")
    venue = record["venue"]
    if venue == "ICLR" and "openreview.net" in url:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        note_id = (query.get("id") or [""])[0]
        return f"https://openreview.net/pdf?id={note_id}" if note_id else ""
    citation = re.search(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\'](.*?)["\']', text, re.I)
    if citation:
        return html.unescape(citation.group(1))
    if venue == "ICML" and url.endswith(".html"):
        return url[:-5] + ".pdf"
    if venue == "NeurIPS":
        return url.replace("-Abstract-", "-Paper-").replace("Abstract.html", "Paper.pdf")
    return ""


def _clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def safe_slug(record: dict[str, Any]) -> str:
    text = unicodedata.normalize("NFKD", record["title"]).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:72]
    digest = hashlib.sha1(record["title"].encode()).hexdigest()[:8]
    return f"{record['year']}-{record['venue'].lower()}-{text}-{digest}"


def download_pdf(record: dict[str, Any], target_dir: Path) -> dict[str, Any]:
    url = record.get("pdf_url", "")
    if not url:
        record["download_error"] = "missing official PDF URL"
        return record
    target = target_dir / f"{safe_slug(record)}.pdf"
    if target.exists() and target.stat().st_size > 10_000:
        record["local_pdf"] = str(target)
        record.setdefault("pdf_source", "existing_valid_pdf")
        return record
    try:
        body, content_type = fetch_bytes(url)
        if len(body) <= 10_000 or not body.startswith(b"%PDF"):
            raise ValueError(f"not a valid PDF ({content_type}, {len(body)} bytes)")
        target.write_bytes(body)
        record["local_pdf"] = str(target)
        record["pdf_source"] = "official_conference"
        time.sleep(1)
    except Exception as exc:
        error: Exception = exc
        if record["venue"] == "ICLR":
            fallback = arxiv_pdf_url(record["title"])
            if fallback:
                try:
                    body, content_type = fetch_bytes(fallback)
                    if len(body) <= 10_000 or not body.startswith(b"%PDF"):
                        raise ValueError(f"not a valid PDF ({content_type}, {len(body)} bytes)")
                    target.write_bytes(body)
                    record["local_pdf"] = str(target)
                    record["pdf_source"] = "arxiv_fallback_openreview_blocked"
                    record["fallback_pdf_url"] = fallback
                    time.sleep(3)
                    return record
                except Exception as fallback_exc:
                    error = fallback_exc
        record["download_error"] = f"{type(error).__name__}: {error}"
    return record


def arxiv_pdf_url(title: str) -> str:
    query = urllib.parse.urlencode({"search_query": f'ti:"{title}"', "max_results": 3})
    try:
        body, _ = fetch_bytes(f"https://export.arxiv.org/api/query?{query}")
        root = ET.fromstring(body)
    except Exception:
        return ""
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    wanted = re.sub(r"\W+", "", title).casefold()
    for entry in root.findall("atom:entry", namespace):
        found_title = " ".join((entry.findtext("atom:title", default="", namespaces=namespace)).split())
        found = re.sub(r"\W+", "", found_title).casefold()
        if wanted != found and wanted not in found and found not in wanted:
            continue
        identifier = entry.findtext("atom:id", default="", namespaces=namespace).rsplit("/", 1)[-1]
        identifier = re.sub(r"v\d+$", "", identifier)
        return f"https://arxiv.org/pdf/{identifier}"
    return ""


def _selection_category(record: dict[str, Any]) -> str:
    text = (record["title"] + " " + record.get("abstract", "")).lower()
    rules = (
        ("offline_or_imitation", r"offline|imitation|decision transformer"),
        ("theory_and_games", r"markov game|stochastic game|equilibri|convergence|regret|sample.efficient"),
        ("safety_and_robustness", r"safe|robust|adversar|constrained|attack"),
        ("communication_and_coordination", r"communication|coordination|cooperat"),
        ("benchmark_and_application", r"benchmark|traffic|radiotherapy|climate|crystal|emergency"),
        ("representation_and_scaling", r"representation|scalable|sequence model|graph|role|factor"),
    )
    return next((name for name, pattern in rules if re.search(pattern, text)), "general_marl")


def select_gold_papers(records: list[dict[str, Any]], *, per_group: int = 5) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    preferred_categories = (
        "offline_or_imitation", "theory_and_games", "safety_and_robustness",
        "communication_and_coordination", "benchmark_and_application",
        "representation_and_scaling", "general_marl",
    )
    for venue in VENUES:
        for year in YEARS:
            full_pool = [value for value in records if value["venue"] == venue and value["year"] == year]
            core_pool = [
                value for value in full_pool
                if any(rule != "multi_agent_learning" for rule in value.get("matched_rules", []))
            ]
            pool = core_pool if len(core_pool) >= per_group else full_pool
            for value in pool:
                value["selection_category"] = _selection_category(value)
                title = value["title"]
                value["selection_score"] = value["relevance_score"] + (
                    12 if re.search(DIRECT_PATTERNS["multi_agent_rl"], title, re.I) else 0
                ) + (4 if value.get("abstract") else 0)
            pool.sort(key=lambda value: (-value["selection_score"], value["title"]))
            chosen: list[dict[str, Any]] = []
            for category in preferred_categories:
                match = next((value for value in pool if value["selection_category"] == category and value not in chosen), None)
                if match is not None:
                    chosen.append(match)
                if len(chosen) == per_group:
                    break
            for value in pool:
                if len(chosen) == per_group:
                    break
                if value not in chosen:
                    chosen.append(value)
            for value in chosen:
                value["selection_reason_zh"] = (
                    f"{venue} {year} 分层样本；覆盖 {value['selection_category']}，"
                    "并保留可复核的会议元数据与官方 PDF。"
                )
            selected.extend(chosen)
    return selected


def materialize_selected(root: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    available = [value for value in records if value.get("local_pdf") and Path(value["local_pdf"]).is_file()]
    selected = select_gold_papers(available if len(available) >= 30 else records)
    selected_dir = root / "pdfs" / "selected-corpus-30"
    gold_dir = root / "gold" / "selected-corpus-30-annotations"
    selected_dir.mkdir(parents=True, exist_ok=True)
    gold_dir.mkdir(parents=True, exist_ok=True)
    for record in selected:
        source = Path(record.get("local_pdf", ""))
        if source.exists():
            target = selected_dir / source.name
            if not target.exists():
                shutil.copy2(source, target)
            record["selected_pdf"] = str(target)
        gold = {
            "schema_version": "1.0",
            "paper_id": record["paper_id"],
            "title": record["title"],
            "venue": record["venue"],
            "year": record["year"],
            "pdf_path": record.get("selected_pdf", record.get("local_pdf", "")),
            "review_status": "unreviewed",
            "annotators": [],
            "entities": [],
            "relations": [],
            "claims": [],
            "numeric_results": [],
            "locators": [],
        }
        (gold_dir / f"{safe_slug(record)}.json").write_text(
            json.dumps(gold, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (root / "metadata" / "selected-30.json").write_text(
        json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return selected


def collect(root: Path, *, download: bool, threshold: int) -> list[dict[str, Any]]:
    metadata_dir = root / "metadata"
    pdf_dir = root / "pdfs" / "all-candidates"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)
    all_records = []
    for venue in VENUES:
        for year in YEARS:
            print(f"Indexing {venue} {year}...", flush=True)
            records = conference_records(venue, year, metadata_dir)
            print(f"  accepted index records: {len(records)}", flush=True)
            all_records.extend(records)
    (metadata_dir / "all-accepted-index.json").write_text(
        json.dumps(all_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    title_candidates = [score_record(record, include_abstract=False) for record in all_records if _worth_enriching(record)]
    enriched = []
    for index, record in enumerate(title_candidates, start=1):
        print(f"Metadata {index}/{len(title_candidates)}: {record['title'][:72]}", flush=True)
        enriched.append(score_record(official_metadata(record)))
        time.sleep(0.3)
    candidates = [record for record in enriched if record["relevance_score"] >= threshold]
    candidates.sort(key=lambda item: (-item["relevance_score"], item["year"], item["venue"], item["title"]))
    if download:
        for index, record in enumerate(candidates, start=1):
            print(f"PDF {index}/{len(candidates)}: {record['title'][:72]}", flush=True)
            download_pdf(record, pdf_dir)
    (metadata_dir / "marl-candidates.json").write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    selected = materialize_selected(root, candidates)
    (root / "README.md").write_text(
        "# MARL Top-3 2024-2025 Corpus\n\n"
        "范围：ICLR、ICML、NeurIPS 的 2024 与 2025 完整会议年度。候选集以录用论文官方索引为全集，"
        "通过 MARL、Markov/stochastic game、Dec-POMDP、mean-field 与多智能体学习标题规则形成高召回集合；"
        "`metadata/marl-candidates.json` 保留规则、摘要、scope_tier 和官方链接以供人工复核；"
        "其中 adjacent_manual_review 是为了避免漏检而保留的相邻主题，不冒充确定的 MARL 论文。\n\n"
        f"候选论文：{len(candidates)} 篇；分层选取：{len(selected)} 篇（每个会议-年度 5 篇）。\n\n"
        "`gold/selected-corpus-30-annotations` 当前是待人工双审模板，`review_status=unreviewed`，不能当成正式 gold 指标。"
        "只有改为 `verified` 的标注才会进入正式评测。\n",
        encoding="utf-8",
    )
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--threshold", type=int, default=8)
    args = parser.parse_args()
    candidates = collect(args.root.expanduser(), download=args.download, threshold=args.threshold)
    downloaded = sum(bool(record.get("local_pdf")) for record in candidates)
    print(f"Candidates: {len(candidates)}; downloaded: {downloaded}")
    for venue in VENUES:
        for year in YEARS:
            count = sum(record["venue"] == venue and record["year"] == year for record in candidates)
            print(f"  {venue} {year}: {count}")


if __name__ == "__main__":
    main()
