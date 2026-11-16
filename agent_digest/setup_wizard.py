from __future__ import annotations

import re
import os
import shutil
import smtplib
import subprocess
import sys
from datetime import date
from getpass import getpass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import requests
from dotenv import dotenv_values, set_key

from .delivery import Mailer
from .digest import Config
from .editorial import Editor
from .sources import http_session, latest_papers, trending

PROVIDERS = {
    "1": ("千问 AI 平台（按量付费）", "https://maas.qianwenaiapi.com/compatible-mode/v1"),
    "2": ("OpenAI", "https://api.openai.com/v1"),
}
MAIL_HOSTS = {
    "qq.com": ("smtp.qq.com", "465"),
    "163.com": ("smtp.163.com", "465"),
    "126.com": ("smtp.126.com", "465"),
    "gmail.com": ("smtp.gmail.com", "587"),
}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def ask(label: str, default: str = "") -> str:
    return input(f"{label}{f' [{default}]' if default else ''}：").strip() or default


def confirm(label: str) -> bool:
    return ask(label + " (y/N)").lower() in {"y", "yes"}


def secret(label: str, saved: str) -> str:
    suffix = "，回车沿用已保存的值" if saved else ""
    return getpass(f"{label}（输入时不显示{suffix}）：").strip() or saved


def model_settings(old: dict[str, str]) -> dict[str, str]:
    print("\n模型服务")
    for index, (label, _) in PROVIDERS.items():
        print(f"  {index}. {label}")
    print("  3. 其他 OpenAI 兼容服务")
    previous_url = old.get("LLM_BASE_URL", "").rstrip("/")
    default = next((key for key, (_, url) in PROVIDERS.items() if url == previous_url), "3" if previous_url else "1")
    choice = ask("选择模型服务", default)
    if choice == "3":
        url = ask("Base URL", previous_url if default == "3" else "")
    elif choice in PROVIDERS:
        _, url = PROVIDERS[choice]
    else:
        raise ValueError("请选择 1、2 或 3。")
    same_provider = previous_url == url.rstrip("/")
    saved_model = old.get("LLM_MODEL", "") if same_provider else ""
    model = ask("输入服务商控制台中的模型 ID", saved_model)
    while not model:
        print("请填写你的账号可用的模型 ID。")
        model = ask("模型 ID")
    key = secret("模型 API 密钥", old.get("LLM_API_KEY", "") if same_provider else "")
    with http_session() as session:
        editor = Editor(session, url, key, model)
        if editor.ask('返回 JSON 对象 {"ok":true}。', {"task": "验证模型连接"}).get("ok") is not True:
            raise ValueError("模型没有通过 JSON 输出检查。")
    print("模型调用成功。")
    return {"LLM_BASE_URL": url, "LLM_MODEL": model, "LLM_API_KEY": key}


def mail_settings(old: dict[str, str]) -> tuple[dict[str, str], Mailer]:
    print("\n发件邮箱")
    sender = ask("发件邮箱地址", old.get("MAIL_FROM", ""))
    host_port = MAIL_HOSTS.get(sender.rsplit("@", 1)[-1].lower())
    if host_port:
        host, port = host_port
        print(f"已识别发信服务器 {host}:{port}")
    else:
        host = ask("SMTP 服务器", old.get("SMTP_HOST", "") if old.get("SMTP_PASSWORD") else "")
        port = ask("SMTP 端口", old.get("SMTP_PORT", "587"))
    same_account = old.get("SMTP_HOST") == host and old.get("MAIL_FROM") == sender
    username = old.get("SMTP_USER", sender) if same_account else sender
    password = secret("邮箱 SMTP 授权码或应用专用密码", old.get("SMTP_PASSWORD", "") if same_account else "")
    if host_port:
        password = "".join(password.split())
    recipient = ask("收件邮箱地址", old.get("MAIL_TO", "") or sender)
    security = "ssl" if port == "465" else "starttls"
    if not host_port:
        security = ask("加密方式（ssl / starttls）", old.get("SMTP_SECURITY", security) if same_account else security)
        username = ask("SMTP 登录账号", username)
    settings = {"SMTP_HOST": host, "SMTP_PORT": port, "SMTP_SECURITY": security,
                "SMTP_USER": username, "SMTP_PASSWORD": password, "MAIL_FROM": sender, "MAIL_TO": recipient}
    mailer = Mailer.from_settings(settings)
    try:
        mailer.check_login()
    except smtplib.SMTPResponseException as exc:
        raise ValueError(f"SMTP 登录失败（{exc.smtp_code}），请检查邮箱地址和授权码。") from None
    except (OSError, ValueError) as exc:
        raise ValueError(f"SMTP 连接失败（{type(exc).__name__}），请检查服务器、端口和网络。") from None
    print("SMTP 登录成功。")
    return settings, mailer


def save_settings(path: Path, settings: dict[str, str]) -> None:
    with TemporaryDirectory(prefix=".setup-", dir=path.parent) as folder:
        staged = Path(folder) / path.name
        if path.exists():
            shutil.copyfile(path, staged)
        else:
            shutil.copyfile(path.with_name(".env.example"), staged)
        for name, value in settings.items():
            set_key(staged, name, value, quote_mode="always", encoding="utf-8-sig")
        staged.replace(path)


def check_sources(path: Path, old: dict[str, str]) -> None:
    proxy = os.getenv("HF_PROXY_URL") or old.get("HF_PROXY_URL")
    config = Config.load(Path("config.yml"))
    with http_session() as session:
        try:
            _, papers = latest_papers(session, date.today(), config.hf_lookback_days, proxy=proxy)
        except (requests.ConnectionError, requests.Timeout):
            print("Hugging Face 连接失败。如果你的网络需要代理，请填写本机 HTTP(S) 代理地址。")
            proxy = ask("代理地址，留空结束配置")
            parsed = urlsplit(proxy)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("Hugging Face 未连通。配置已保存，修复网络后可以重新运行向导。") from None
            try:
                _, papers = latest_papers(session, date.today(), config.hf_lookback_days, proxy=proxy)
            except (requests.RequestException, ValueError) as exc:
                raise ValueError(f"Hugging Face 代理测试失败（{type(exc).__name__}），请检查代理和网络。") from None
            if papers:
                save_settings(path, {"HF_PROXY_URL": proxy})
        except (requests.RequestException, ValueError) as exc:
            raise ValueError(f"Hugging Face 论文榜检查失败（{type(exc).__name__}）。") from None
        if not papers:
            raise ValueError("最近几天没有可读取的 Hugging Face 论文榜，请稍后再试。")
        print(f"Hugging Face 论文榜可用，读到 {len(papers)} 篇论文。")
        for period, label in (("daily", "日榜"), ("weekly", "周榜")):
            try:
                projects = trending(session, "python", period)
            except (requests.RequestException, ValueError) as exc:
                raise ValueError(f"GitHub Python {label}检查失败（{type(exc).__name__}）。") from None
            print(f"GitHub Python {label}可用，读到 {len(projects)} 个项目。")


def register_schedule() -> None:
    daily = ask("每天发送时间（HH:MM）", "08:10")
    weekly = ask("每周发送时间（HH:MM）", "08:30")
    weekday = ask("每周星期几（1=周一，7=周日）", "1")
    if not all(re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", t) for t in (daily, weekly)):
        raise ValueError("发送时间请使用 24 小时制 HH:MM。配置已保存，可重新运行向导。")
    if weekday not in "1234567" or len(weekday) != 1:
        raise ValueError("星期请填写 1 到 7。配置已保存，可重新运行向导。")
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    "install-schedule.ps1", "-Python", sys.executable, "-DailyAt", daily,
                    "-WeeklyAt", weekly, "-WeeklyDay", WEEKDAYS[int(weekday) - 1]], check=True)


def main() -> int:
    if not sys.stdin.isatty():
        print("请在可交互的终端运行配置向导。")
        return 1
    print("Trend Inbox 配置向导")
    path = Path(".env")
    try:
        old = {key: value for key, value in dotenv_values(path, encoding="utf-8-sig").items()
               if value is not None} if path.exists() else {}
        model = model_settings(old)
        mail, mailer = mail_settings(old)
        save_settings(path, model | mail)
        print("本机配置已保存。")
        check_sources(path, old)
        if not confirm(f"向 {mailer.recipient} 发送一封连接测试邮件？"):
            return 0
        body = "Trend Inbox 已连通发件邮箱。这封测试信不会占用今天的早报期号。"
        mailer.send("Trend Inbox · 发信测试", body, f"<p>{body}</p>")
        print("发件服务器已接收测试邮件。请在收件箱查看。")
        if sys.platform == "win32":
            if confirm("收到测试邮件后，是否现在设置本地定时任务？"):
                register_schedule()
        else:
            print("收到测试邮件后，按 README 的 macOS / Linux 定时步骤添加任务。")
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError, EOFError, KeyboardInterrupt) as exc:
        print(f"安装向导停止：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
