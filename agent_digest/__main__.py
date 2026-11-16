from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
import yaml
from dotenv import load_dotenv

from .delivery import Mailer, Rejected, State, Uncertain
from .digest import Config, build_digest
from .editorial import Editor
from .render import render
from .sources import http_session

LOG = logging.getLogger(__name__)


def edition_for(kind: str, today: date, override: str | None) -> tuple[str, date]:
    if kind == "daily":
        value = date.fromisoformat(override) if override else today
        return value.isoformat(), value
    if override:
        match = re.fullmatch(r"(\d{4})-W(\d{2})", override)
        if not match:
            raise ValueError("周报期号须为 YYYY-Www，例如 2026-W47")
        value = date.fromisocalendar(int(match[1]), int(match[2]), 1)
    else:
        value = today
    year, week, _ = value.isocalendar()
    return f"{year}-W{week:02d}", value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="个人 Agent 早报与 GitHub 周报")
    parser.add_argument("kind", choices=("daily", "weekly"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只生成本地预览（默认）")
    mode.add_argument("--send", action="store_true", help="提交邮件")
    mode.add_argument("--resolve", choices=("sent", "retry"), help="手动确认未决发送的结果")
    parser.add_argument("--edition", help="指定期号；日刊 YYYY-MM-DD，周刊 YYYY-Www")
    parser.add_argument("--timezone", help="IANA 时区，缺省使用电脑本地时区")
    parser.add_argument("--config", type=Path, default=Path("config.yml"))
    parser.add_argument("--state", type=Path, default=Path(".digest/state.sqlite3"))
    parser.add_argument("--output", type=Path, default=Path("preview"))
    parser.add_argument("--log", type=Path, help="追加运行日志到文件")
    args = parser.parse_args()
    if args.resolve and not args.edition:
        parser.error("--resolve 需要明确指定 --edition")
    return args


def run(args: argparse.Namespace) -> None:
    now = datetime.now(ZoneInfo(args.timezone)) if args.timezone else datetime.now().astimezone()
    edition, day = edition_for(args.kind, now.date(), args.edition)
    state = State(args.state)
    if args.resolve:
        if not state.resolve(args.kind, edition, args.resolve):
            raise ValueError("指定期号没有待确认的发送记录")
        LOG.info("已更新 %s %s 的发送状态", args.kind, edition)
        return

    if args.send and state.status(args.kind, edition) == "sent":
        LOG.info("%s %s 已发出，跳过", args.kind, edition)
        return
    if args.send and state.status(args.kind, edition) == "sending":
        raise Uncertain("本期发送状态未确认，请核对收件箱后用 --resolve 处理")

    mailer = Mailer.from_environment() if args.send else None
    config = Config.load(args.config)
    with http_session() as session:
        editor = Editor(session, os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
                        os.getenv("LLM_API_KEY", ""), os.getenv("LLM_MODEL") or config.model)
        digest = build_digest(session, editor, config, kind=args.kind, edition=edition, edition_day=day,
                              now=now, seen=state.sent_papers())
    plain, html = render(digest)
    if mailer is None:
        args.output.mkdir(parents=True, exist_ok=True)
        base = args.output / f"{args.kind}-{edition}"
        base.with_suffix(".html").write_text(html, encoding="utf-8")
        base.with_suffix(".txt").write_text(plain, encoding="utf-8")
        LOG.info("预览已保存 %s.html 与 .txt", base)
        return

    if not state.reserve(args.kind, edition, [entry.paper.id for entry in digest.papers]):
        if state.status(args.kind, edition) == "sent":
            LOG.info("本期已由另一个任务发出")
            return
        raise Uncertain("另一进程占用本期发信记录")
    try:
        mailer.send(digest.subject, plain, html)
    except Rejected:
        state.resolve(args.kind, edition, "retry")
        raise
    state.resolve(args.kind, edition, "sent")
    LOG.info("SMTP 已接收 %s，含 %d 篇论文和 %d 个项目", digest.subject, len(digest.papers), len(digest.projects))


def main() -> int:
    args = parse_args()
    load_dotenv(Path(".env"), encoding="utf-8-sig")
    handlers: list[logging.Handler] = [logging.StreamHandler()] if sys.stderr is not None else []
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    try:
        run(args)
    except (ValueError, OSError, ZoneInfoNotFoundError, requests.RequestException, yaml.YAMLError,
            Rejected, Uncertain) as exc:
        LOG.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
