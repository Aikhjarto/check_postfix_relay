"""Tests of the bash completion in completions/check_postfix_relay."""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from tests.test_check_postfix_relay import FAKE_POSTCONF, FAKE_POSTMAP

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLUGIN = os.path.join(ROOT, "check_postfix_relay")
COMPLETION = os.path.join(ROOT, "completions", "check_postfix_relay")

CONFIG = {
    "params": {"sender_dependent_relayhost_maps": "lmdb:/etc/postfix/relay_by_sender, lmdb:/etc/postfix/more"},
    "tables": {
        "lmdb:/etc/postfix/relay_by_sender": {"user@example.net": "[smtp.example.net]:587",
                                               "other@example.org": "[mail.example.org]:587"},
        "lmdb:/etc/postfix/more": {"third@example.com": "[smtp.example.com]:465"},
    },
}


def help_words():
    """The option strings --help lists.

    Before Python 3.13 argparse repeats the metavar after every option string,
    since then only after the last. An option line starts with the invocation,
    followed by the description after two or more spaces or on the next line.
    """
    output = subprocess.run([sys.executable, PLUGIN, "--help"], stdout=subprocess.PIPE,
                            universal_newlines=True, check=True).stdout
    words = set()
    for line in output.split("\n"):
        match = re.match(r"  (-\S.*?)(?:\s{2,}|$)", line)
        if match:
            words.update(re.findall(r"(?:^|, )(-{1,2}[^\s,=\[{]+)", match.group(1)))
    return words


@unittest.skipUnless(shutil.which("bash"), "bash is not installed")
class CompletionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.bin = os.path.join(directory.name, "bin")
        os.mkdir(self.bin)
        for name, script in (("postconf", FAKE_POSTCONF), ("postmap", FAKE_POSTMAP)):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(script)
            os.chmod(path, stat.S_IRWXU)
        self.config = os.path.join(directory.name, "postfix.json")
        with open(self.config, "w") as f:
            json.dump(CONFIG, f)

    def complete(self, *words):
        """The candidates bash offers for the last of words, which may be empty."""
        words = ("check_postfix_relay",) + words
        script = 'source "$1"; shift; COMP_WORDS=("$@"); COMP_CWORD=$(($# - 1)); ' \
                 '_check_postfix_relay; printf "%s\\n" "${COMPREPLY[@]}"'
        env = dict(os.environ, FAKE_POSTFIX=self.config, PATH=self.bin + os.pathsep + os.environ["PATH"])
        result = subprocess.run(["bash", "-c", script, "bash", COMPLETION] + list(words),
                                stdout=subprocess.PIPE, universal_newlines=True, check=True, env=env)
        return [line for line in result.stdout.split("\n") if line]

    def test_syntax(self):
        subprocess.run(["bash", "-n", COMPLETION], check=True)

    def test_offers_exactly_the_options_of_help(self):
        self.assertEqual(set(self.complete("")), help_words())

    def test_option_prefix(self):
        self.assertEqual(self.complete("--v"), ["--version"])

    def test_skip_offers_the_senders_of_all_maps(self):
        self.assertEqual(sorted(self.complete("-x", "")),
                         ["other@example.org", "third@example.com", "user@example.net"])

    def test_skip_prefix(self):
        self.assertEqual(self.complete("-x", "oth"), ["other@example.org"])

    def test_skip_leaves_out_senders_already_skipped(self):
        self.assertEqual(sorted(self.complete("-x", "user@example.net", "-x", "")),
                         ["other@example.org", "third@example.com"])

    def test_no_candidates_after_options_with_values(self):
        for option in ("-r", "-w", "-c", "-t"):
            with self.subTest(option=option):
                self.assertEqual(self.complete(option, ""), [])

    def test_without_postfix(self):
        env_path = os.environ["PATH"]
        os.remove(os.path.join(self.bin, "postconf"))
        if shutil.which("postconf", path=env_path + os.pathsep + "/usr/sbin:/sbin"):
            self.skipTest("postconf is installed")
        self.assertEqual(self.complete("-x", ""), [])


if __name__ == "__main__":
    unittest.main()
