from __future__ import annotations

from html import escape
from urllib.parse import urljoin

from .digest import Digest
from .editorial import MARKDOWN
from .sources import public_url


def link(label: str, url: str) -> str:
    href = public_url(url)
    return f'<a href="{escape(href)}">{escape(label)}</a>' if href else escape(label)


def image(url: str, label: str, width: int | None = None) -> str:
    if not public_url(url):
        return ""
    sizing = f' width="{width}" height="{width}"' if width else ' width="560"'
    return (f'<img src="{escape(url)}" alt="{escape(label)}"{sizing} '
            'style="max-width:100%;height:auto;border:0">')


def markdown(text: str, base_url: str) -> str:
    tokens = MARKDOWN.parse(text)
    for token in tokens:
        for child in token.children or ():
            if child.type == "link_open":
                href = urljoin(base_url, child.attrGet("href") or "")
                child.attrSet("href", public_url(href) or base_url)
    return MARKDOWN.renderer.render(tokens, MARKDOWN.options, {})


def render(digest: Digest) -> tuple[str, str]:
    timestamp = digest.fetched_at.strftime("%Y-%m-%d %H:%M %z")
    plain = [digest.subject, f"抓取时间 {timestamp}"]
    html = [f"<h1>{escape(digest.subject)}</h1>", f"<p>抓取时间 {escape(timestamp)}</p>"]
    if digest.sources:
        plain.append("\n".join(f"{label} {url}" for label, url in digest.sources))
        html.append("<ul>" + "".join(f"<li>{link(label, url)}</li>" for label, url in digest.sources) + "</ul>")
    if digest.notes:
        plain.extend(digest.notes)
        html.append("<ul>" + "".join(f"<li>{escape(note)}</li>" for note in digest.notes) + "</ul>")

    if digest.kind == "daily":
        plain.append("Hugging Face 论文")
        html.append("<h2>Hugging Face 论文</h2>")
        if not digest.papers:
            plain.append("本期暂无论文条目。")
            html.append("<p>本期暂无论文条目。</p>")
    for item in digest.papers:
        paper = item.paper
        metadata = f"HF 榜单 {paper.ranking_date}" + (f" · 发布 {paper.published}" if paper.published else "")
        arxiv = f"https://arxiv.org/abs/{paper.id}"
        plain.extend([f"{item.title}\n{paper.title}\n{metadata}", f"导读\n{item.guide}",
                      "摘要译文\n" + "\n\n".join(item.abstract), f"HF 论文页 {paper.url}\n论文原文 {arxiv}"])
        html.extend([f"<h3>{link(item.title, paper.url)}</h3>", f"<p>{escape(paper.title)}<br>{escape(metadata)}</p>",
                     f"<h4>导读</h4><p>{escape(item.guide)}</p>", "<h4>摘要译文</h4>",
                     *(markdown(part, paper.url) for part in item.abstract),
                     f"<p>{link('HF 论文页', paper.url)} · {link('论文原文', arxiv)}</p>"])

    plain.append("GitHub Trending 项目")
    html.append("<h2>GitHub Trending 项目</h2>")
    if not digest.projects:
        plain.append("本期暂无项目条目。")
        html.append("<p>本期暂无项目条目。</p>")
    for project in digest.projects:
        period = "今日" if digest.kind == "daily" else "本周"
        numbers = (("总星标", project.stars), ("Fork 数", project.forks), (f"{period}新增星标", project.gained))
        metadata = " · ".join([f"{project.language} · 第 {project.rank} 名"]
                              + [f"{label} {value:,}" for label, value in numbers if value is not None])
        plain.append(f"{project.name}\n{project.url}")
        html.append(f"<h3>{link(project.name, project.url)}</h3>")
        if project.description:
            plain.append(project.description)
            html.append(f"<p>{escape(project.description)}</p>")
        plain.append(metadata)
        html.append(f"<p>{escape(metadata)}</p>")
        if project.avatars:
            avatars = " ".join(image(src, name or "贡献者头像", 24) for name, src in project.avatars)
            html.append(f"<p>贡献者 {avatars}</p>")
            names = [name for name, _ in project.avatars if name]
            if names:
                plain.append("贡献者 " + "、".join(names))

    page = ('<!doctype html><html lang="zh-Hans"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(digest.subject)}</title></head>'
            '<body style="margin:0;background:#fff;color:#17212d">'
            '<div style="max-width:640px;margin:0 auto;padding:20px;'
            'font:16px/1.65 Arial, Microsoft YaHei, sans-serif;overflow-wrap:anywhere">'
            + "\n".join(html) + "</div></body></html>")
    return "\n\n".join(plain) + "\n", page
