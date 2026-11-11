"""The sandbox's DNS (follow-up 1 of the harness's ADR-003): the egress container answers every DNS query the agent
makes, and resolves only the names on the published allowlist.

  query                                         answer                      denial log
  a listed name, in any case, with or without  the upstream resolver's     nothing
  the final dot, over UDP or TCP
  any other name (a subdomain of a listed one,  NXDOMAIN, with the query's  {"kind": "dns", "target": <name>}
  a name that contains a listed one)            id and question
  a query that isn't one, or a name with a      FORMERR                     {"kind": "dns", "target": "(malformed)"}
  label no host name has (a dot, a control
  byte, a space)

What reaches the upstream resolver for a listed name is rebuilt from the name alone: the question in lower case, with a
fresh id, recursion desired and no other section, so nothing else the agent put in its query (an EDNS option, other
records, its id or flags) leaves. The agent gets its own id and question back.

These checks run .devcontainer/harness-agent/egress.py on the host through its command line, as the DNS server alone
(--no-packets: the packet log needs Linux and CAP_NET_ADMIN), in front of a stand-in upstream resolver that answers
every query with one address. tests/test-sandbox-egress.py checks the whole egress container (HARNESS_E2E=1). The
property check needs hypothesis.
"""
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

from hypothesis_profiles import examples

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None


EGRESS = Path(__file__).resolve().parents[1] / "payload/owned/.devcontainer/harness-agent/egress.py"
ALLOWLIST = ("api.anthropic.com", "github.com", "objects.githubusercontent.com")
ANSWER = bytes([192, 0, 2, 7])
NOERROR, FORMERR, NXDOMAIN = 0, 1, 3


def query(name, ident=0x1234, qtype=1):
    labels = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.rstrip(".").split(".") if part)
    return struct.pack(">HHHHHH", ident, 0x0100, 1, 0, 0, 0) + labels + b"\0" + struct.pack(">HH", qtype, 1)


def answered(query_bytes):
    """The stand-in upstream's answer: the query with one A record."""
    ident, = struct.unpack(">H", query_bytes[:2])
    record = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + ANSWER
    return struct.pack(">HHHHHH", ident, 0x8180, 1, 1, 0, 0) + query_bytes[12:] + record


class Upstream:
    """A resolver on 127.0.0.1 that answers every query, over UDP and TCP, and counts them."""

    def __init__(self):
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.port = self.udp.getsockname()[1]
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp.bind(("127.0.0.1", self.port))
        self.tcp.listen(8)
        self.asked = 0
        self.received = []
        for serve in (self.serve_udp, self.serve_tcp):
            threading.Thread(target=serve, daemon=True).start()

    def serve_udp(self):
        while True:
            try:
                data, peer = self.udp.recvfrom(4096)
            except OSError:
                return
            self.asked += 1
            self.received.append(data)
            self.udp.sendto(answered(data), peer)

    def serve_tcp(self):
        while True:
            try:
                connection, _ = self.tcp.accept()
            except OSError:
                return
            with connection:
                size, = struct.unpack(">H", read_exactly(connection, 2))
                self.asked += 1
                data = read_exactly(connection, size)
                self.received.append(data)
                reply = answered(data)
                connection.sendall(struct.pack(">H", len(reply)) + reply)

    def close(self):
        self.udp.close()
        self.tcp.close()


def read_exactly(connection, size):
    data = b""
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("closed after %d of %d bytes" % (len(data), size))
        data += chunk
    return data


class Resolver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory(prefix="egress dns ")
        cls.addClassCleanup(temp.cleanup)
        work = Path(temp.name)
        cls.log = work / "denials.jsonl"
        (work / "allowlist").write_text("".join(name + "\n" for name in ALLOWLIST))
        cls.upstream = Upstream()
        cls.addClassCleanup(cls.upstream.close)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        cls.port = probe.getsockname()[1]
        probe.close()
        cls.server = subprocess.Popen(
            [sys.executable, "-B", str(EGRESS), "--no-packets", "--listen", "127.0.0.1:%d" % cls.port,
             "--upstream", "127.0.0.1:%d" % cls.upstream.port, "--allowlist", str(work / "allowlist"),
             "--log", str(cls.log)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        cls.addClassCleanup(cls.server.kill)
        ready = cls.server.stdout.readline()
        assert "answering DNS" in ready, ready + cls.server.stdout.read()

    def ask(self, data, tcp=False):
        """(rcode, the addresses answered, the reply's id and question) for a query sent to the egress resolver."""
        if tcp:
            with socket.create_connection(("127.0.0.1", self.port), timeout=5) as connection:
                connection.sendall(struct.pack(">H", len(data)) + data)
                size, = struct.unpack(">H", read_exactly(connection, 2))
                reply = read_exactly(connection, size)
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(5)
                client.sendto(data, ("127.0.0.1", self.port))
                reply, _ = client.recvfrom(4096)
        rcode = struct.unpack(">H", reply[2:4])[0] & 0x000f
        answers = struct.unpack(">H", reply[6:8])[0]
        return rcode, [ANSWER] * answers if answers else [], reply[:2], reply[12:]

    def denied(self):
        return [record.get("target") for record in map(json.loads, self.log.read_text().splitlines())
                if record.get("kind") == "dns"]

    TABLE = (
        ("api.anthropic.com",            NOERROR),
        ("API.Anthropic.COM",            NOERROR),
        ("github.com.",                  NOERROR),
        ("objects.githubusercontent.com", NOERROR),
        ("example.com",                  NXDOMAIN),
        ("exfil.github.com",             NXDOMAIN),
        ("github.com.evil.example",      NXDOMAIN),
        ("anthropic.com",                NXDOMAIN),
    )

    def test_only_listed_names_resolve_over_udp_and_tcp(self):
        for name, rcode in self.TABLE:
            for tcp in (False, True):
                with self.subTest(name=name, tcp=tcp):
                    answer = self.ask(query(name), tcp=tcp)

                    self.assertEqual(answer[:2], (rcode, [ANSWER] if rcode == NOERROR else []))

    def test_a_refused_name_gets_nxdomain_for_its_own_query_and_is_logged(self):
        data = query("leak-123.example", ident=0xbeef, qtype=16)

        rcode, addresses, ident, question = self.ask(data)

        self.assertEqual((rcode, addresses, ident, question), (NXDOMAIN, [], b"\xbe\xef", data[12:]))
        self.assertIn("leak-123.example", self.denied())

    def test_a_refused_name_never_reaches_the_upstream_resolver(self):
        before = self.upstream.asked

        self.ask(query("never-asked.example"))

        self.assertEqual(self.upstream.asked, before)

    def test_a_query_that_is_not_one_gets_formerr(self):
        rcode, addresses, ident, _ = self.ask(b"\x00\x07garbage")

        self.assertEqual((rcode, addresses, ident), (FORMERR, [], b"\x00\x07"))
        self.assertIn("(malformed)", self.denied())

    def test_a_name_whose_labels_no_host_name_has_is_never_forwarded_or_logged_as_is(self):
        dotted = struct.pack(">HHHHHH", 7, 0x0100, 1, 0, 0, 0) + b"\x0dapi.anthropic\x03com\x00" + struct.pack(">HH", 1, 1)
        names = {"a dot inside a label (api.anthropic + com)": dotted,
                 "a newline": query("leak\nAPPROVED.example"), "a space": query("a b.example"),
                 "a control byte": query("x\x01y.example")}
        for case, data in names.items():
            with self.subTest(case=case):
                before = self.upstream.asked

                rcode, addresses, _, _ = self.ask(data)

                self.assertEqual((rcode, addresses), (FORMERR, []))
                self.assertEqual(self.upstream.asked, before)
        self.assertFalse([name for name in self.denied() if "\n" in name or " " in name or "\x01" in name])

    def test_only_the_question_rebuilt_from_the_listed_name_reaches_the_upstream_resolver(self):
        for tcp in (False, True):
            with self.subTest(tcp=tcp):
                opt = b"\x00" + struct.pack(">HHIH", 41, 4096, 0, 8) + struct.pack(">HH", 65001, 4) + b"leak"
                asked = (struct.pack(">HHHHHH", 0x4242, 0x0130, 1, 0, 0, 1) + query("Api.Anthropic.COM")[12:] + opt)

                rcode, addresses, ident, question = self.ask(asked, tcp=tcp)
                sent = self.upstream.received[-1]

                self.assertEqual((rcode, addresses, ident), (NOERROR, [ANSWER], b"\x42\x42"))
                self.assertEqual(question[:len(query("Api.Anthropic.COM")) - 12], query("Api.Anthropic.COM")[12:])
                self.assertEqual(sent[2:], struct.pack(">HHHHH", 0x0100, 1, 0, 0, 0) + query("api.anthropic.com")[12:])
                self.assertNotEqual(sent[:2], b"\x42\x42")

    def test_the_log_starts_with_when_it_started(self):
        self.assertIn("started", json.loads(self.log.read_text().splitlines()[0]))

    if given is not None:
        label = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=12)

        @settings(max_examples=examples(60), deadline=None)
        @given(name=st.one_of(st.sampled_from(ALLOWLIST), st.lists(label, min_size=1, max_size=4).map(".".join)),
               upper=st.booleans(), dot=st.booleans(), tcp=st.booleans())
        def test_a_name_resolves_exactly_when_it_is_listed(self, name, upper, dot, tcp):
            asked = (name.upper() if upper else name) + ("." if dot else "")

            rcode, addresses, _, _ = self.ask(query(asked), tcp=tcp)

            self.assertEqual(rcode == NOERROR and addresses == [ANSWER], name in ALLOWLIST, asked)


if __name__ == "__main__":
    unittest.main()
