import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "set_openrouter_key.sh"
VALID_KEY = "sk-or-v1-" + "a" * 64


@unittest.skipUnless(shutil.which("sh"), "POSIX sh is required")
class SetOpenRouterKeyTests(unittest.TestCase):
    def run_script(self, env_file, key, *arguments):
        return subprocess.run(
            ["sh", str(SCRIPT), "--env-file", str(env_file), "--no-verify", "--no-restart", *arguments],
            input=key,
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )

    def test_replaces_existing_key_and_preserves_other_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "runtime.env"
            env_file.write_text(
                "LLM_PROVIDER=openrouter\n"
                "OPENROUTER_API_KEY=expired-key\n"
                "OPENROUTER_MODEL=openrouter/free\n"
                "# keep this comment\n",
                encoding="utf-8",
            )

            result = self.run_script(env_file, VALID_KEY + "\n")

            self.assertEqual(result.returncode, 0, result.stderr)
            text = env_file.read_text(encoding="utf-8")
            self.assertIn("OPENROUTER_API_KEY=" + VALID_KEY, text)
            self.assertNotIn("expired-key", text)
            self.assertIn("LLM_PROVIDER=openrouter", text)
            self.assertIn("OPENROUTER_MODEL=openrouter/free", text)
            self.assertIn("# keep this comment", text)
            self.assertNotIn(VALID_KEY, result.stdout + result.stderr)

    def test_appends_key_when_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "runtime.env"
            env_file.write_text("LLM_PROVIDER=openrouter\n", encoding="utf-8")

            result = self.run_script(env_file, VALID_KEY + "\r\n")

            self.assertEqual(result.returncode, 0, result.stderr)
            lines = env_file.read_text(encoding="utf-8").splitlines()
            self.assertIn("OPENROUTER_API_KEY=" + VALID_KEY, lines)
            self.assertEqual(sum(line.startswith("OPENROUTER_API_KEY=") for line in lines), 1)

    def test_rejects_invalid_key_without_modifying_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "runtime.env"
            original = "LLM_PROVIDER=openrouter\nOPENROUTER_API_KEY=old\n"
            env_file.write_text(original, encoding="utf-8")

            for invalid in ("", "not-a-key", "sk-or-v1-abc def", "sk-or-v1-short"):
                with self.subTest(key=invalid):
                    result = self.run_script(env_file, invalid)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(env_file.read_text(encoding="utf-8"), original)

    def test_missing_env_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "missing.env"

            result = self.run_script(env_file, VALID_KEY)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("环境文件不存在", result.stderr)
            self.assertFalse(env_file.exists())

    def test_key_file_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / "runtime.env"
            env_file.write_text("OPENROUTER_API_KEY=old\n", encoding="utf-8")
            key_file = Path(temporary) / "new-key"
            key_file.write_text(VALID_KEY + "\n", encoding="utf-8")

            result = subprocess.run(
                ["sh", str(SCRIPT), "--env-file", str(env_file), "--key-file", str(key_file),
                 "--no-verify", "--no-restart"],
                text=True,
                capture_output=True,
                cwd=ROOT,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("OPENROUTER_API_KEY=" + VALID_KEY, env_file.read_text(encoding="utf-8"))
            self.assertNotIn(VALID_KEY, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
