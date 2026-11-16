from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger(__name__)
HF = "https://huggingface.co"
GITHUB = "https://github.com"
REPO_HREF = re.compile(r"/[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+\Z")
PAPER_ID = re.compile(r"(?:[a-z][a-z.\-]+/)?\d{4}\.\d{4,5}(?:v\d+)?\Z", re.I)


def http_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "agent-digest/0.1 (personal RSS-style email digest)"
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods={"GET"}, respect_retry_after_header=False)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    response = session.get(url, timeout=(6, 20), **kwargs)
    response.raise_for_status()
    return response


def public_url(value: str, hosts: set[str] | None = None) -> str:
    try:
        parsed = urlparse(value)
        if (parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not any(ch.isspace() for ch in value) and parsed.port in (None, 443)
                and (hosts is None or parsed.hostname in hosts)):
            return value
    except ValueError:
        pass
    return ""


def hf_get(session: requests.Session, path: str, **kwargs) -> requests.Response:
    proxy = os.getenv("HF_PROXY_URL")
    if proxy:
        kwargs["proxies"] = {"https": proxy}
    return get(session, f"{HF}/{path}", **kwargs)


@dataclass(frozen=True)
class Paper:
    id: str
    title: str
    abstract: str
    published: str
    ranking_date: date
    url: str


@dataclass(frozen=True)
class Project:
    name: str
    rank: int
    language: str
    description: str
    stars: int | None
    forks: int | None
    gained: int | None
    avatars: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def url(self) -> str:
        return f"{GITHUB}/{self.name}"


def latest_papers(session: requests.Session, edition: date, lookback: int) -> tuple[date, list[Paper]]:
    for offset in range(lookback + 1):
        day = edition - timedelta(days=offset)
        rows = hf_get(session, "api/daily_papers", params={"date": day.isoformat()}).json()
        if not isinstance(rows, list):
            raise ValueError("HF Daily Papers 返回格式变化")
        if not rows:
            continue
        papers = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("paper"), dict):
                continue
            paper = row["paper"]
            identifier = paper.get("id")
            if not isinstance(identifier, str) or not PAPER_ID.fullmatch(identifier):
                continue
            canonical_id = re.sub(r"v\d+$", "", identifier)
            if canonical_id in seen:
                continue
            title = row.get("title") or paper.get("title") or ""
            abstract = row.get("summary") or paper.get("summary") or ""
            if not abstract:
                try:
                    abstract = hf_get(session, f"api/papers/{identifier}").json().get("summary", "")
                except (requests.RequestException, ValueError):
                    LOG.warning("无法获取论文摘要 %s", identifier)
            if title.strip() and abstract.strip():
                papers.append(Paper(canonical_id, title.strip(), abstract.strip(),
                                    (paper.get("publishedAt") or "")[:10], day, f"{HF}/papers/{identifier}"))
                seen.add(canonical_id)
        if not papers:
            raise ValueError("HF 榜单存在，但未解析出任何论文")
        return day, papers
    return edition, []


def _number(node) -> int | None:
    if node is None:
        return None
    match = re.search(r"\d[\d,]*", node.get_text(" ", strip=True))
    return int(match[0].replace(",", "")) if match else None


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def parse_trending(html: str, language: str) -> list[Project]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("article.Box-row")
    if not rows:
        if re.search(r"no trending repositories|don.t see anything in here", soup.get_text(" ", strip=True), re.I):
            return []
        raise ValueError("GitHub Trending 未发现榜单条目，可能是页面结构变化或访问受限")
    projects = []
    for rank, row in enumerate(rows, 1):
        link = row.select_one("h2 a[href], h1 a[href]")
        href = link.get("href", "") if link else ""
        if not REPO_HREF.fullmatch(href):
            raise ValueError("GitHub Trending 未能解析仓库链接")
        avatars = []
        for img in row.select('a[data-hovercard-type="user"] img, img.avatar'):
            url = public_url(img.get("src", ""), {"avatars.githubusercontent.com"})
            pair = (img.get("alt", "").strip(), url)
            if url and pair not in avatars:
                avatars.append(pair)
        projects.append(Project(
            href[1:], rank, _text(row.select_one('[itemprop="programmingLanguage"]')) or language,
            _text(row.select_one("p")),
            _number(row.select_one(f'a[href="{href}/stargazers"]')),
            _number(row.select_one(f'a[href="{href}/forks"]')),
            _number(row.select_one("span.float-sm-right")), tuple(avatars),
        ))
    return projects


def trending(session: requests.Session, language: str, period: str) -> list[Project]:
    response = get(session, f"{GITHUB}/trending/{language}", params={"since": period})
    return parse_trending(response.text, language)
