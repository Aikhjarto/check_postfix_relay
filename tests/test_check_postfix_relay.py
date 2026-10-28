"""Tests for check_postfix_relay, with fake postconf/postmap and a fake SMTP relay."""
import base64
import importlib.machinery
import importlib.util
import json
import os
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(os.path.dirname(HERE), "check_postfix_relay")

loader = importlib.machinery.SourceFileLoader("check_postfix_relay", PLUGIN)
spec = importlib.util.spec_from_loader("check_postfix_relay", loader)
plugin = importlib.util.module_from_spec(spec)
loader.exec_module(plugin)

# postconf -h NAME: the value from $FAKE_POSTFIX's "params"
FAKE_POSTCONF = """#!/usr/bin/python3
import json, os, sys
config = json.load(open(os.environ["FAKE_POSTFIX"]))
print(config["params"].get(sys.argv[-1], ""))
"""

# postmap -q KEY TABLE / postmap -s TABLE: from $FAKE_POSTFIX's "tables"
FAKE_POSTMAP = """#!/usr/bin/python3
import json, os, sys
config = json.load(open(os.environ["FAKE_POSTFIX"]))
if sys.argv[1] == "-q":
    value = config["tables"].get(sys.argv[3], {}).get(sys.argv[2])
    if value is None:
        sys.exit(1)
    print(value)
elif sys.argv[1] == "-s":
    for key, value in config["tables"].get(sys.argv[2], {}).items():
        print("%s\\t%s" % (key, value))
"""


class Relay(socketserver.StreamRequestHandler):
    """A minimal SMTP server: EHLO, AUTH PLAIN, MAIL, RCPT, RSET, QUIT; no STARTTLS."""

    def reply(self, line):
        self.wfile.write((line + "\r\n").encode())

    def handle(self):
        self.reply("220 fake ESMTP")
        while True:
            line = self.rfile.readline().decode().strip()
            if not line:
                return
            verb = line.split()[0].upper()
            self.server.log.append(verb)
            if verb in ("EHLO", "HELO"):
                self.reply("250-fake")
                self.reply("250 AUTH PLAIN")
            elif verb == "AUTH":
                _, user, password = base64.b64decode(line.split()[2]).decode().split("\0")
                if self.server.logins.get(user) == password:
                    self.reply("235 2.7.0 Authentication successful")
                else:
                    self.reply("535 5.7.8 Error: authentication failed")
            elif verb == "MAIL":
                self.reply("250 2.1.0 Ok")
            elif verb == "RCPT":
                if "nobody@" in line:
                    self.reply("550 5.1.1 User unknown")
                else:
                    self.reply("250 2.1.5 Ok")
            elif verb == "RSET":
                self.reply("250 2.0.0 Ok")
            elif verb == "QUIT":
                self.reply("221 2.0.0 Bye")
                return
            else:
                self.reply("502 5.5.2 Error: command not recognized")


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class PluginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.relay = Server(("127.0.0.1", 0), Relay)
        cls.relay.logins = {"system@example.org": "secret-1", "user@example.net": "secret-2"}
        cls.relay.log = []
        threading.Thread(target=cls.relay.serve_forever, daemon=True).start()
        cls.address = "[127.0.0.1]:%d" % cls.relay.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.relay.shutdown()
        cls.relay.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for name, text in (("postconf", FAKE_POSTCONF), ("postmap", FAKE_POSTMAP)):
            path = os.path.join(self.tmp.name, name)
            with open(path, "w") as handle:
                handle.write(text)
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        self.relay.log.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, params=None, tables=None):
        """A Postfix configuration with SASL, the fake relay as relayhost and one sender relay."""
        conf = {
            "params": {
                "relayhost": self.address,
                "smtp_tls_security_level": "may",
                "smtp_sasl_auth_enable": "yes",
                "smtp_sender_dependent_authentication": "yes",
                "smtp_sasl_password_maps": "lmdb:/etc/postfix/sasl_passwd",
                "sender_dependent_relayhost_maps": "lmdb:/etc/postfix/relayhostmap",
                "sender_canonical_maps": "regexp:/etc/postfix/sender_canonical",
                "myhostname": "relay.example.org",
            },
            "tables": {
                "lmdb:/etc/postfix/sasl_passwd": {
                    self.address: "system@example.org:secret-1",
                    "user@example.net": "user@example.net:secret-2",
                },
                "lmdb:/etc/postfix/relayhostmap": {"user@example.net": self.address},
            },
        }
        conf["params"].update(params or {})
        for table, entries in (tables or {}).items():
            conf["tables"][table] = entries
        return conf

    def run_plugin(self, conf, *args):
        path = os.path.join(self.tmp.name, "postfix.json")
        with open(path, "w") as handle:
            json.dump(conf, handle)
        env = dict(os.environ, FAKE_POSTFIX=path, PATH=self.tmp.name + os.pathsep + os.environ["PATH"])
        return subprocess.run([sys.executable, PLUGIN] + list(args), capture_output=True, text=True, env=env)

    def test_all_logins_ok(self):
        result = self.run_plugin(self.config())
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(result.stdout.startswith("OK - 2 relay login(s) ok | 'relayhost'="))
        self.assertIn("OK relayhost: 127.0.0.1:", result.stdout)
        self.assertIn("login as system@example.org ok", result.stdout)
        self.assertIn("login as user@example.net ok", result.stdout)
        self.assertNotIn("secret", result.stdout + result.stderr)

    def test_rejected_login_is_critical(self):
        conf = self.config(tables={"lmdb:/etc/postfix/sasl_passwd": {
            self.address: "system@example.org:secret-1",
            "user@example.net": "user@example.net:wrong",
        }})
        result = self.run_plugin(conf)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertTrue(result.stdout.startswith("CRITICAL - user@example.net: 127.0.0.1:"))
        self.assertIn("rejects the login of user@example.net: 535", result.stdout)
        self.assertIn("OK relayhost:", result.stdout)
        self.assertNotIn("wrong", result.stdout)

    def test_skip_sender(self):
        result = self.run_plugin(self.config(), "-x", "user@example.net")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(result.stdout.startswith("OK - 1 relay login(s) ok"))
        self.assertNotIn("user@example.net", result.stdout)

    def test_same_relay_and_login_tested_once(self):
        # without sender dependent authentication the sender's relay uses the relayhost's login
        result = self.run_plugin(self.config({"smtp_sender_dependent_authentication": "no"}))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(result.stdout.startswith("OK - 1 relay login(s) ok"))
        self.assertEqual(self.relay.log.count("AUTH"), 1)

    def test_missing_credentials_unknown(self):
        conf = self.config(tables={"lmdb:/etc/postfix/sasl_passwd": {self.address: "system@example.org:secret-1"}},
                           params={"smtp_sender_dependent_authentication": "yes"})
        conf["tables"]["lmdb:/etc/postfix/relayhostmap"] = {"user@example.net": "[127.0.0.2]:2525"}
        result = self.run_plugin(conf)
        self.assertEqual(result.returncode, 3, result.stdout)
        self.assertIn("no credentials for [127.0.0.2]:2525", result.stdout)

    def test_recipient_test(self):
        result = self.run_plugin(self.config(), "-r", "root@example.org")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("user@example.net -> root@example.org accepted", result.stdout)
        self.assertIn("RSET", self.relay.log)
        result = self.run_plugin(self.config(), "-r", "nobody@example.org")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("RCPT TO:<nobody@example.org> rejected: 550", result.stdout)

    def test_unreachable_relay_critical(self):
        conf = self.config({"relayhost": "[127.0.0.1]:1"})
        conf["tables"]["lmdb:/etc/postfix/sasl_passwd"]["[127.0.0.1]:1"] = "system@example.org:secret-1"
        result = self.run_plugin(conf, "-x", "user@example.net")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertTrue(result.stdout.startswith("CRITICAL - relayhost: 127.0.0.1:1:"))

    def test_no_relayhost(self):
        conf = self.config({"relayhost": "", "sender_dependent_relayhost_maps": ""})
        result = self.run_plugin(conf)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, "OK - no relayhost configured, Postfix delivers directly\n")

    def test_usage_error_is_unknown(self):
        result = self.run_plugin(self.config(), "--no-such-option")
        self.assertEqual(result.returncode, 3)
        self.assertTrue(result.stdout.startswith("UNKNOWN - check_postfix_relay: unrecognized arguments"))

    def test_version(self):
        result = self.run_plugin(self.config(), "--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "check_postfix_relay %s\n" % plugin.VERSION)


class ParseRelayTest(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(plugin.parse_relay("[mail.example.org]:587"), ("mail.example.org", 587))
        self.assertEqual(plugin.parse_relay("[mail.example.org]"), ("mail.example.org", 25))
        self.assertEqual(plugin.parse_relay("mail.example.org:465"), ("mail.example.org", 465))
        self.assertEqual(plugin.parse_relay("mail.example.org"), ("mail.example.org", 25))
        self.assertEqual(plugin.parse_relay("smtp:[mail.example.org]:587"), ("mail.example.org", 587))
        self.assertEqual(plugin.parse_relay("[a.example.org]:587, [b.example.org]:587"), ("a.example.org", 587))


if __name__ == "__main__":
    unittest.main()
