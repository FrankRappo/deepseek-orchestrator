import os
from pathlib import Path
import subprocess
import tempfile
import unittest


WRAPPER = Path(__file__).resolve().parents[1] / "bin" / "deepseek"


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = self.root / "codex"
        self.fake.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"$1\" == --version ]]; then echo 'codex-cli 0.155.1'; exit 0; fi\n"
            "printf '%s\\n' \"$@\" > \"$ARGS_FILE\"\n"
            "printf '%s\\n' \"$CODEX_HOME\" > \"$HOME_FILE\"\n"
            "printf '%s\\n' \"$DEEPSEEK_API_KEY\" > \"$KEY_CAPTURE_FILE\"\n"
            "cat > \"$PROMPT_CAPTURE_FILE\"\n",
            encoding="utf-8",
        )
        self.fake.chmod(0o755)
        self.key_file = self.root / "key.txt"
        self.key_file.write_text("sk-test-only\n", encoding="utf-8")
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("Check this task.\n", encoding="utf-8")
        self.env = dict(os.environ)
        self.env.pop("DEEPSEEK_API_KEY", None)
        self.env.update(
            DEEPSEEK_CODEX_BIN=str(self.fake),
            DEEPSEEK_KEY_FILE=str(self.key_file),
            ARGS_FILE=str(self.root / "args"),
            HOME_FILE=str(self.root / "home"),
            KEY_CAPTURE_FILE=str(self.root / "key-capture"),
            PROMPT_CAPTURE_FILE=str(self.root / "prompt-capture"),
        )

    def call_exec(self, *extra):
        return subprocess.run(
            [str(WRAPPER), "exec", "--project", str(self.root),
             "--prompt-file", str(self.prompt), "--output-last-message",
             str(self.root / "last.txt"), *extra],
            env=self.env, text=True, capture_output=True, check=False,
        )

    def call_interactive(self, *extra):
        return subprocess.run(
            [str(WRAPPER), *extra, "--project", str(self.root)],
            env=self.env, text=True, capture_output=True, check=False,
        )

    def test_safe_mode_uses_deepseek_config_and_project(self):
        result = self.call_exec()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.root / "args").read_text().splitlines()
        self.assertLess(args.index("--ask-for-approval"), args.index("exec"))
        self.assertIn("workspace-write", args)
        self.assertIn("on-request", args)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", args)
        self.assertIn("deepseek-v4-pro", args)
        self.assertIn("--json", args)
        self.assertEqual((self.root / "prompt-capture").read_text(), "Check this task.\n")
        self.assertEqual((self.root / "key-capture").read_text(), "sk-test-only\n")
        self.assertEqual((self.root / "home").read_text().strip(),
                         str(WRAPPER.parent.parent / ".codex"))
        self.assertIn("model_catalog_json=", "\n".join(args))

    def test_interactive_starts_codex_tui_with_safe_permissions(self):
        result = self.call_interactive("--model", "deepseek-flash")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.root / "args").read_text().splitlines()
        self.assertIn("-C", args)
        self.assertIn(str(self.root), args)
        self.assertIn("deepseek-flash", args)
        self.assertIn("workspace-write", args)
        self.assertIn("on-request", args)
        self.assertNotIn("exec", args)
        self.assertNotIn("resume", args)

    def test_resume_last_uses_isolated_home_and_project(self):
        result = self.call_interactive("resume", "--last")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.root / "args").read_text().splitlines()
        self.assertEqual(args[-2:], ["resume", "--last"])
        self.assertIn(str(self.root), args)
        self.assertEqual((self.root / "home").read_text().strip(),
                         str(WRAPPER.parent.parent / ".codex"))

    def test_resume_rejects_conflicting_session_selection(self):
        result = self.call_interactive("resume", "--last", "--session", "123")
        self.assertEqual(result.returncode, 2)
        self.assertIn("either --last or --session", result.stderr)
        self.assertFalse((self.root / "args").exists())

    def test_dangerous_is_explicit(self):
        result = self.call_exec("--dangerous", "--model", "deepseek-flash")
        self.assertEqual(result.returncode, 0, result.stderr)
        args = (self.root / "args").read_text().splitlines()
        self.assertLess(args.index("--dangerously-bypass-approvals-and-sandbox"), args.index("exec"))
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", args)
        self.assertNotIn("workspace-write", args)
        self.assertIn("deepseek-flash", args)

    def test_invalid_key_does_not_reach_codex(self):
        self.key_file.write_text("invalid\n", encoding="utf-8")
        result = self.call_exec()
        self.assertEqual(result.returncode, 2)
        self.assertIn("format is invalid", result.stderr)
        self.assertFalse((self.root / "args").exists())


if __name__ == "__main__":
    unittest.main()
