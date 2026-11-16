from __future__ import annotations

import os
import smtplib
import sqlite3
import ssl
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path


class Rejected(RuntimeError):
    """The server definitely did not accept the message."""


class Uncertain(RuntimeError):
    """The server may have accepted the message."""


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(self.connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS editions (
                kind TEXT NOT NULL, edition TEXT NOT NULL, status TEXT NOT NULL,
                PRIMARY KEY (kind, edition))""")
            db.execute("""CREATE TABLE IF NOT EXISTS edition_papers (
                kind TEXT NOT NULL, edition TEXT NOT NULL, paper_id TEXT NOT NULL,
                PRIMARY KEY (kind, edition, paper_id))""")

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=15)

    def status(self, kind: str, edition: str) -> str | None:
        with closing(self.connect()) as db:
            row = db.execute("SELECT status FROM editions WHERE kind = ? AND edition = ?",
                             (kind, edition)).fetchone()
        return row[0] if row else None

    def sent_papers(self) -> set[str]:
        with closing(self.connect()) as db:
            rows = db.execute("""SELECT paper_id FROM edition_papers
                JOIN editions USING (kind, edition) WHERE status = 'sent'""").fetchall()
        return {row[0] for row in rows}

    def reserve(self, kind: str, edition: str, papers: list[str]) -> bool:
        with closing(self.connect()) as db, db:
            cursor = db.execute("INSERT OR IGNORE INTO editions VALUES (?, ?, 'sending')", (kind, edition))
            if not cursor.rowcount:
                return False
            db.executemany("INSERT INTO edition_papers VALUES (?, ?, ?)",
                           [(kind, edition, paper_id) for paper_id in papers])
        return True

    def resolve(self, kind: str, edition: str, resolution: str) -> bool:
        with closing(self.connect()) as db, db:
            if resolution == "sent":
                cursor = db.execute("UPDATE editions SET status = 'sent' "
                                    "WHERE kind = ? AND edition = ? AND status = 'sending'", (kind, edition))
            else:
                db.execute("BEGIN IMMEDIATE")
                cursor = db.execute("DELETE FROM editions WHERE kind = ? AND edition = ? AND status = 'sending'",
                                    (kind, edition))
                if cursor.rowcount:
                    db.execute("DELETE FROM edition_papers WHERE kind = ? AND edition = ?", (kind, edition))
            return bool(cursor.rowcount)


@dataclass(frozen=True)
class Mailer:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipient: str
    security: str

    @classmethod
    def from_environment(cls) -> Mailer:
        return cls.from_settings(os.environ)

    @classmethod
    def from_settings(cls, settings: Mapping[str, str]) -> Mailer:
        required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM", "MAIL_TO")
        missing = [key for key in required if not settings.get(key)]
        if missing:
            raise ValueError("请配置 " + "、".join(missing))
        port = int(settings.get("SMTP_PORT", "587"))
        security = settings.get("SMTP_SECURITY", "ssl" if port == 465 else "starttls")
        if not 1 <= port <= 65535 or security not in ("ssl", "starttls"):
            raise ValueError("SMTP_PORT 或 SMTP_SECURITY 无效")
        host, username, password, sender, recipient = (settings[key] for key in required)
        for address in (sender, recipient):
            if not address.isascii() or address.count("@") != 1 or any(ch in address for ch in " \r\n,;<>\t"):
                raise ValueError("MAIL_FROM 和 MAIL_TO 各填一个邮箱地址")
        return cls(host, port, username, password, sender, recipient, security)

    def _login(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        smtp = None
        try:
            if self.security == "ssl":
                smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=25, context=context)
            else:
                smtp = smtplib.SMTP(self.host, self.port, timeout=25)
                smtp.ehlo()
                smtp.starttls(context=context)
            smtp.login(self.username, self.password)
            return smtp
        except (OSError, ValueError):
            if smtp is not None:
                smtp.close()
            raise

    def check_login(self) -> None:
        with closing(self._login()):
            pass

    def send(self, subject: str, plain: str, html: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = self.recipient
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=self.sender.rsplit("@", 1)[1])
        message.set_content(plain)
        message.add_alternative(html, subtype="html")
        payload = message.as_bytes(policy=message.policy.clone(linesep="\r\n", cte_type="7bit"))
        smtp = None
        try:
            smtp = self._login()
            sender_code, _ = smtp.mail(self.sender)
            recipient_code, _ = smtp.rcpt(self.recipient) if sender_code == 250 else (sender_code, b"")
            if recipient_code not in (250, 251, 252):
                raise Rejected(f"SMTP 未接受地址（{recipient_code}）")
        except (OSError, ValueError) as exc:
            if smtp is not None:
                smtp.close()
            raise Rejected(f"SMTP 尚未提交邮件（{type(exc).__name__}）") from None
        except Rejected:
            if smtp is not None:
                smtp.close()
            raise
        try:
            code, _ = smtp.data(payload)
            if code != 250:
                raise Rejected(f"SMTP 拒绝接收正文（{code}）")
        except smtplib.SMTPDataError as exc:
            raise Rejected(f"SMTP 拒绝接收正文（{exc.smtp_code}）") from None
        except OSError as exc:
            raise Uncertain(f"SMTP 正文提交结果未确认（{type(exc).__name__}）") from None
        finally:
            smtp.close()
