import smtplib
import unittest
from datetime import date, datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from agent_digest.__main__ import edition_for
from agent_digest.delivery import Mailer, Rejected, State, Uncertain
from agent_digest.digest import Config, build_digest
from agent_digest.editorial import Editor, verified_translation
from agent_digest.render import render
from agent_digest.sources import Paper, Project, parse_trending


class EditorialTest(unittest.TestCase):
    def test_keeps_structure_and_rejects_changed_facts(self):
        original = "A [paper](https://example.org/) with 1,024 steps."
        good = "这篇[论文](https://example.org/)包含 1024 步。"
        self.assertEqual(verified_translation(original, good), good)
        for changed in (good.replace("1024", "2048"), good.replace("example", "example2"), good + "\n\n第二段。"):
            with self.assertRaises(ValueError):
                verified_translation(original, changed)


class CollectionTest(unittest.TestCase):
    def test_trending_metadata(self):
        html = '''<article class="Box-row"><h2><a href="/a/replay">a/replay</a></h2>
        <p>Debug agents</p><span itemprop="programmingLanguage">TypeScript</span>
        <a href="/a/replay/stargazers">5,509</a><a href="/a/replay/forks">20</a>
        <span class="float-sm-right">128 stars today</span>
        <img class="avatar" alt="@a" src="https://avatars.githubusercontent.com/u/1"></article>'''
        [project] = parse_trending(html, "typescript")
        self.assertEqual((project.rank, project.name, project.language, project.stars, project.forks,
                          project.gained, project.avatars[0][0]), (1, "a/replay", "TypeScript", 5509, 20, 128, "@a"))
        with self.assertRaises(ValueError):
            parse_trending("<html>rate limited</html>", "python")

    @patch("agent_digest.digest.trending")
    @patch("agent_digest.digest.latest_papers")
    def test_daily_and_weekly_render(self, hf, trending):
        day = date(2026, 11, 16)
        hf.return_value = (day, [Paper(f"2611.1234{i}", f"Agent paper {i}", "First part.\n\nSecond part.",
                                    str(day), day, f"https://huggingface.co/papers/2611.1234{i}") for i in range(3)])
        trending.side_effect = lambda _, language, period: [
            Project(f"owner/{language}-tool-{index}", index, language, "Record browser tool calls.", 700,
                    10, index, (("@owner", "https://avatars.githubusercontent.com/u/1"),))
            for index in range(1, 8)]
        editor = Editor(MagicMock(), "https://example.org/v1", "test", "test")

        def respond(_instruction, data):
            if isinstance(data, list) and data and "evidence" in data[0]:
                return {"scores": {item["id"]: 3 for item in data}}
            if "paragraphs" in data:
                return {"title": data["title"].replace("Agent paper", "智能体论文"), "paragraphs": ["第一段。", "第二段。"]}
            if "abstract" in data:
                return {"guide": "智能体如何使用工具？\n\n这项研究讨论工具调用。"}
            return {name: "记录浏览器工具调用。" for name in data}

        with patch.object(editor, "ask", side_effect=respond):
            for kind, period, expected in [("daily", "daily", (2, 5)), ("weekly", "weekly", (0, 5))]:
                edition, edition_day = edition_for(kind, day, None)
                report = build_digest(MagicMock(), editor, Config(), kind=kind, edition=edition, edition_day=edition_day,
                                      now=datetime(2026, 11, 16, tzinfo=timezone.utc), seen={"2611.12340"})
                self.assertEqual((len(report.papers), len(report.projects)), expected)
                self.assertEqual([project.rank for project in report.projects], [1, 2, 3, 4, 5])
                self.assertEqual(trending.call_args.args[1:], ("python", period))
                plain, html = render(report)
                self.assertNotIn("README", plain)
                self.assertNotIn("项目导读", html)
                self.assertIn("记录浏览器工具调用。", html)
                self.assertIn("星标", html)
                self.assertIn('alt="@owner"', html)
                if kind == "daily":
                    self.assertIn("第一段。</p>\n\n<p>第二段。", html)
                    self.assertIn("导读\n智能体如何使用工具？这项研究讨论工具调用。", plain)
                else:
                    self.assertNotIn("Hugging Face 论文", plain)


class DeliveryTest(unittest.TestCase):
    def test_state_reservation_survives_reopen_and_weekly_is_independent(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "state.db"
            state = State(path)
            self.assertTrue(state.reserve("daily", "2026-11-16", ["2611.12345"]))
            loaded = State(path)
            self.assertFalse(loaded.reserve("daily", "2026-11-16", []))
            self.assertEqual(loaded.sent_papers(), set())
            self.assertTrue(loaded.resolve("daily", "2026-11-16", "retry"))
            self.assertTrue(loaded.reserve("daily", "2026-11-16", ["2611.12346"]))
            self.assertTrue(loaded.resolve("daily", "2026-11-16", "sent"))
            self.assertEqual(state.sent_papers(), {"2611.12346"})
            self.assertFalse(state.reserve("daily", "2026-11-16", []))
            self.assertTrue(state.reserve("weekly", "2026-W47", []))

    @patch("agent_digest.delivery.smtplib.SMTP")
    def test_multipart_and_classifies_smtp_outcome(self, smtp_factory):
        smtp = smtp_factory.return_value
        smtp.mail.return_value = (250, b"OK")
        smtp.rcpt.return_value = (250, b"OK")
        smtp.data.return_value = (250, b"OK")
        mailer = Mailer("smtp.example.org", 587, "test", "secret", "a@example.org", "b@example.org", "starttls")
        mailer.send("Agent 早报", "纯文本", "<p>HTML 正文</p>")
        parsed = BytesParser(policy=policy.default).parsebytes(smtp.data.call_args.args[0])
        self.assertEqual(parsed["Subject"], "Agent 早报")
        self.assertIn("纯文本", parsed.get_body(preferencelist=("plain",)).get_content())
        self.assertIn("HTML 正文", parsed.get_body(preferencelist=("html",)).get_content())
        smtp.data.side_effect = smtplib.SMTPServerDisconnected()
        with self.assertRaises(Uncertain):
            mailer.send("test", "text", "<p>test</p>")
        smtp.data.side_effect = smtplib.SMTPDataError(554, b"rejected")
        with self.assertRaises(Rejected):
            mailer.send("test", "text", "<p>test</p>")


if __name__ == "__main__":
    unittest.main()
