import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dotenv import dotenv_values

from agent_digest import setup_wizard as wizard


class SetupWizardTest(unittest.TestCase):
    @patch("agent_digest.setup_wizard.Editor")
    @patch("agent_digest.setup_wizard.Mailer.check_login")
    @patch("agent_digest.setup_wizard.getpass", side_effect=["test-model-key", "test smtp code"])
    @patch("agent_digest.setup_wizard.ask", side_effect=["1", "qwen3.8-flash", "demo@qq.com", "demo@qq.com"])
    def test_qwen_and_qq_defaults_with_private_settings(self, ask, masked, smtp_login, editor):
        editor.return_value.ask.return_value = {"ok": True}
        model = wizard.model_settings({"LLM_BASE_URL": "https://api.openai.com/v1", "LLM_API_KEY": "previous"})
        mail, _ = wizard.mail_settings({})
        self.assertEqual(model["LLM_BASE_URL"], "https://maas.qianwenaiapi.com/compatible-mode/v1")
        self.assertEqual(model["LLM_API_KEY"], "test-model-key")
        self.assertEqual(mail["SMTP_HOST"], "smtp.qq.com")
        self.assertEqual(mail["SMTP_PORT"], "465")
        self.assertEqual(mail["SMTP_PASSWORD"], "testsmtpcode")
        self.assertEqual(mail["SMTP_SECURITY"], "ssl")
        self.assertNotIn("沿用", masked.call_args_list[0].args[0])
        smtp_login.assert_called_once()
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("CUSTOM=keep\nSMTP_PORT=587\n", encoding="utf-8")
            wizard.save_settings(path, model | mail)
            persisted = dotenv_values(path, encoding="utf-8-sig")
            self.assertEqual(persisted["CUSTOM"], "keep")
            self.assertEqual(persisted["SMTP_PORT"], "465")
            self.assertEqual(set(os.listdir(directory)), {".env"})

    @patch("agent_digest.setup_wizard.subprocess.run")
    @patch("agent_digest.setup_wizard.ask", side_effect=["07:20", "09:45", "7"])
    def test_register_uses_requested_times_and_displays_next_runs(self, ask, run):
        wizard.register_schedule()
        args = run.call_args_list[0].args[0]
        self.assertEqual(args[-6:], ["-DailyAt", "07:20", "-WeeklyAt", "09:45", "-WeeklyDay", "Sunday"])
        self.assertIn("NextRunTime", run.call_args_list[1].args[0][-1])
