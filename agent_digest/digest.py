from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

import requests
import yaml

from .editorial import Editor, PaperCopy
from .sources import GITHUB, Paper, Project, latest_papers, trending

LOG = logging.getLogger(__name__)
PROJECT_LIMIT = 5


@dataclass(frozen=True)
class Config:
    papers: int = 2
    hf_lookback_days: int = 3
    model: str = ""

    @classmethod
    def load(cls, path: Path) -> Config:
        if not path.exists() and path == Path("config.yml"):
            return cls()
        values = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        legacy = {"daily_projects", "weekly_projects", "languages", "project_candidates_per_language",
                  "owner_names", "project_names"}
        if not isinstance(values, dict) or set(values) - set(cls.__dataclass_fields__) - legacy:
            raise ValueError("请检查 config.yml 中的字段")
        config = cls(**{key: value for key, value in values.items() if key not in legacy})
        for key, minimum, maximum in (("papers", 1, 10), ("hf_lookback_days", 0, 14)):
            value = getattr(config, key)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{key} 须为 {minimum}–{maximum} 的整数")
        if not isinstance(config.model, str):
            raise ValueError("model 须为字符串")
        return config


@dataclass
class Digest:
    kind: str
    edition: str
    fetched_at: datetime
    papers: list[PaperCopy]
    projects: list[Project]
    notes: list[str]
    sources: list[tuple[str, str]]

    @property
    def subject(self) -> str:
        title = "Agent 早报" if self.kind == "daily" else "Agent GitHub 周报"
        return f"{title} · {self.edition}"


def translate(editor_fn, *args):
    for attempt in range(2):
        try:
            return editor_fn(*args)
        except ValueError as exc:
            LOG.warning("内容生成失败（第 %d 次）%s", attempt + 1, exc)
    return None


def select_papers(editor: Editor, papers: list[Paper], limit: int) -> list[PaperCopy]:
    scores = editor.relevance([
        {"id": paper.id, "title": paper.title, "evidence": paper.abstract[:4500]} for paper in papers
    ])
    ranked = sorted(papers, key=lambda paper: -scores[paper.id])
    selected = []
    for paper in ranked:
        if scores[paper.id] < 2 or len(selected) >= limit:
            break
        copy = translate(editor.paper, paper)
        if copy is not None:
            selected.append(copy)
    return selected


def build_digest(session: requests.Session, editor: Editor, config: Config, *, kind: str,
                 edition: str, edition_day: date, now: datetime, seen: set[str]) -> Digest:
    digest = Digest(kind, edition, now, [], [], [], [])
    if kind == "daily":
        try:
            ranking_day, papers = latest_papers(session, edition_day, config.hf_lookback_days)
        except (requests.RequestException, ValueError) as exc:
            LOG.warning("HF 抓取失败 %s", type(exc).__name__)
            digest.notes.append("Hugging Face 论文榜抓取失败。")
        else:
            digest.sources.append((f"HF 论文榜 · {ranking_day}" if papers else "HF 论文榜 · 未找到榜单条目",
                                   f"https://huggingface.co/papers/date/{ranking_day}"))
            digest.papers = select_papers(editor, [paper for paper in papers if paper.id not in seen], config.papers)
            if len(digest.papers) < config.papers:
                digest.notes.append(f"论文栏目收录 {len(digest.papers)} / {config.papers} 篇，符合筛选且可交付的条目不足。")

    period = "daily" if kind == "daily" else "weekly"
    window = "日榜" if kind == "daily" else "周榜"
    try:
        entries = trending(session, "python", period)
    except (requests.RequestException, ValueError) as exc:
        LOG.warning("GitHub Python %s 抓取失败 %s", window, type(exc).__name__)
        digest.notes.append(f"GitHub Python {window}抓取失败。")
    else:
        digest.sources.append((f"GitHub Python {window}", f"{GITHUB}/trending/python?since={period}"))
        projects = entries[:PROJECT_LIMIT]
        translations = translate(editor.project_descriptions, projects) or {}
        digest.projects = [replace(project, description=translations.get(project.name, project.description))
                           for project in projects]
    if not digest.sources:
        raise ValueError("本期数据源全部抓取失败，未生成邮件")
    return digest
