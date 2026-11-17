#!/usr/bin/env python3
"""Agentic harness (harness-owned): the egress container's DNS and its log of what it denied (ADR-003).

Runs as root in the egress container once init-firewall.sh has put the rules in force, and keeps running: if it stops,
the container stops and the agent loses its network.

- DNS: it answers on 127.0.0.1:53, where init-firewall.sh redirects every DNS query the agent's processes make. A name
  on the published allowlist (exactly, in any case) is resolved by the container's own resolver, with a query rebuilt
  from the name alone; any other name gets NXDOMAIN and never leaves, and a name whose labels no host name has gets
  FORMERR. So nothing the agent chooses goes out in DNS queries but the listed names themselves.
- The denial log: every outbound packet the rules drop goes to an NFLOG group first (init-firewall.sh), which it reads
  over netlink. Each denied packet and each refused name becomes one JSON line in /run/harness-egress/denials.jsonl, on
  the volume the agent's container mounts read-only; the first line says when the log started. Each judge pass in the
  agent's container records a summary of the log, which the receipt cites.

Standard library only, like the engine. The options exist so the DNS server can run alone, as the tests run it.
"""
import argparse
from datetime import datetime, timezone
import errno
import json
import os
import re
import socket
import socketserver
import struct
import sys
import threading

ALLOWLIST = "/run/harness-egress/allowlist"
LOG = "/run/harness-egress/denials.jsonl"
GROUP = 7   # init-firewall.sh logs to this group
MAX_RECORDS = 20000
FORMERR, NXDOMAIN, SERVFAIL = 1, 3, 2
RECURSION_DESIRED = 0x0100
# What a label of a host name holds (underscore for service names like _dmarc); anything else, a dot inside a label
# included, is no name to resolve.
LABEL = re.compile(rb"^[A-Za-z0-9_-]{1,63}$")
# linux/netlink.h, linux/netfilter/nfnetlink.h, linux/netfilter/nfnetlink_log.h
NETLINK_NETFILTER = 12
NLMSG_ERROR = 2
NLM_F_REQUEST, NLM_F_ACK = 1, 4
NFNL_SUBSYS_ULOG = 4
NFULNL_MSG_PACKET, NFULNL_MSG_CONFIG = 0, 1
NFULA_CFG_CMD, NFULA_CFG_MODE = 1, 2
NFULNL_CFG_CMD_BIND, NFULNL_CFG_CMD_PF_BIND, NFULNL_CFG_CMD_PF_UNBIND = 1, 3, 4
NFULNL_COPY_PACKET = 2
NFULA_PAYLOAD, NFULA_UID = 9, 11
PROTOCOLS = {1: "icmp", 6: "tcp", 17: "udp", 58: "icmpv6"}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DenialLog(object):
    """The append-only log both the DNS server and the packet reader write to. It stops at MAX_RECORDS, saying so."""

    def __init__(self, path):
        self.lock = threading.Lock()
        self.written = 0
        self.file = open(path, "w", encoding="utf-8")
        os.chmod(path, 0o644)
        self.file.write(json.dumps({"started": now(), "log": "what the egress container denied"}) + "\n")
        self.file.flush()

    def add(self, kind, target, uid=None):
        with self.lock:
            if self.written < MAX_RECORDS:
                self.file.write(json.dumps({"at": now(), "kind": kind, "target": target, "uid": uid}) + "\n")
            elif self.written == MAX_RECORDS:
                self.file.write(json.dumps({"at": now(), "truncated": True}) + "\n")
            self.written += 1
            self.file.flush()


# --------------------------------------------------------------------------- DNS

def question(data):
    """(the queried name, lower-case and without the final dot, where the question ends) of a DNS query, or (None,
    None) when it isn't a query for one host name. A query's name has no compression pointers."""
    if len(data) < 12 or data[2] & 0x80 or struct.unpack(">H", data[4:6])[0] != 1:
        return None, None
    labels, at = [], 12
    while at < len(data):
        size = data[at]
        if size == 0:
            end = at + 5
            name = ".".join(labels).lower()
            return (name, end) if labels and end <= len(data) and len(name) <= 253 else (None, None)
        label = data[at + 1:at + 1 + size]
        if not LABEL.match(label):
            return None, None
        labels.append(label.decode("ascii"))
        at += 1 + size
    return None, None


def reply(data, end, rcode):
    """An answer with no records to the query in data, with rcode; the question is kept when there is one."""
    flags = 0x8080 | (struct.unpack(">H", data[2:4])[0] & 0x7900 if len(data) >= 4 else 0) | rcode
    asked = data[12:end] if end else b""
    return data[:2].ljust(2, b"\0") + struct.pack(">HHHHH", flags, 1 if asked else 0, 0, 0, 0) + asked


class Resolver(object):
    def __init__(self, allowed, upstream, log=None):
        self.allowed, self.upstream, self.log = allowed, upstream, log

    def answer(self, data, tcp):
        name, end = question(data)
        if name is None:
            self.log.add("dns", "(malformed)")
            return reply(data, None, FORMERR)
        if name not in self.allowed:
            self.log.add("dns", name)
            return reply(data, end, NXDOMAIN)
        asked = data[12:end]
        # The name in lower case and its type and class: the labels' length bytes are below 64, so lower() leaves them.
        canonical = asked[:-4].lower() + asked[-4:]
        ident = os.urandom(2)
        try:
            answer = self.ask_upstream(ident + struct.pack(">HHHHH", RECURSION_DESIRED, 1, 0, 0, 0) + canonical, tcp)
        except (OSError, ValueError):
            return reply(data, end, SERVFAIL)
        if answer[:2] != ident or answer[12:end].lower() != canonical.lower():
            return reply(data, end, SERVFAIL)
        return data[:2] + answer[2:12] + asked + answer[end:]

    def ask_upstream(self, query, tcp):
        if tcp:
            with socket.create_connection(self.upstream, timeout=5) as connection:
                connection.sendall(struct.pack(">H", len(query)) + query)
                size, = struct.unpack(">H", read_exactly(connection, 2))
                return read_exactly(connection, size)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(5)
            client.sendto(query, self.upstream)
            while True:
                answer, _ = client.recvfrom(65535)
                if answer[:2] == query[:2]:
                    return answer


def read_exactly(connection, size):
    data = b""
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ValueError("the connection closed early")
        data += chunk
    return data


def dns_servers(resolver, address):
    class Udp(socketserver.BaseRequestHandler):
        def handle(self):
            data, sock = self.request
            sock.sendto(resolver.answer(data, tcp=False), self.client_address)

    class Tcp(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.settimeout(10)
            try:
                while True:
                    size, = struct.unpack(">H", read_exactly(self.request, 2))
                    answer = resolver.answer(read_exactly(self.request, size), tcp=True)
                    self.request.sendall(struct.pack(">H", len(answer)) + answer)
            except (OSError, ValueError):
                pass

    socketserver.ThreadingUDPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    servers = (socketserver.ThreadingUDPServer(address, Udp), socketserver.ThreadingTCPServer(address, Tcp))
    for server in servers:
        server.daemon_threads = True
    return servers


def resolv_conf_upstream():
    """The resolver the container itself was given (Docker's, 127.0.0.11 on a Compose network)."""
    try:
        lines = open("/etc/resolv.conf", encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    servers = [line.split()[1] for line in lines if line.split()[:1] == ["nameserver"] and len(line.split()) > 1]
    return next((server for server in servers if server not in ("127.0.0.1", "::1")), "127.0.0.11")


# --------------------------------------------------------------------------- denied packets

def message(kind, family, attributes, seq):
    body = struct.pack("=BBH", family, 0, socket.htons(GROUP if family == socket.AF_UNSPEC else 0))
    for code, payload in attributes:
        size = 4 + len(payload)
        body += struct.pack("=HH", size, code) + payload + b"\0" * (-size % 4)
    header = struct.pack("=IHHII", 16 + len(body), (NFNL_SUBSYS_ULOG << 8) | kind, NLM_F_REQUEST | NLM_F_ACK, seq, 0)
    return header + body


def configure(sock, family, attributes, seq):
    sock.send(message(NFULNL_MSG_CONFIG, family, attributes, seq))
    answer = sock.recv(65536)
    if len(answer) >= 20 and struct.unpack_from("=H", answer, 4)[0] == NLMSG_ERROR:
        error = struct.unpack_from("=i", answer, 16)[0]
        if error:
            raise OSError(-error, os.strerror(-error))


def nflog_socket():
    sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_NETFILTER)
    sock.bind((0, 0))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
    for seq, family in enumerate((socket.AF_INET, socket.AF_INET6), 1):
        # Kernels before 3.17 need the family bound to nfnetlink_log; later ones ignore both commands.
        for command in (NFULNL_CFG_CMD_PF_UNBIND, NFULNL_CFG_CMD_PF_BIND):
            try:
                configure(sock, family, [(NFULA_CFG_CMD, bytes([command]))], seq)
            except OSError:
                pass
    configure(sock, socket.AF_UNSPEC, [(NFULA_CFG_CMD, bytes([NFULNL_CFG_CMD_BIND]))], 10)
    configure(sock, socket.AF_UNSPEC, [(NFULA_CFG_MODE, struct.pack(">IBB", 96, NFULNL_COPY_PACKET, 0))], 11)
    return sock


def attributes(data):
    found, at = {}, 0
    while at + 4 <= len(data):
        size, code = struct.unpack_from("=HH", data, at)
        if size < 4:
            break
        found[code & 0x3fff] = data[at + 4:at + size]
        at += (size + 3) & ~3
    return found


def destination(packet):
    """Where a denied packet was going: address:port/protocol, or address/protocol without ports."""
    version = packet[0] >> 4 if packet else 0
    if version == 4 and len(packet) >= 20:
        header, protocol, address = (packet[0] & 0x0f) * 4, packet[9], socket.inet_ntop(socket.AF_INET, packet[16:20])
    elif version == 6 and len(packet) >= 40:
        header, protocol, address = 40, packet[6], "[%s]" % socket.inet_ntop(socket.AF_INET6, packet[24:40])
    else:
        return None
    name = PROTOCOLS.get(protocol, str(protocol))
    if protocol in (6, 17) and len(packet) >= header + 4:
        return "%s:%d/%s" % (address, struct.unpack_from(">H", packet, header + 2)[0], name)
    return "%s/%s" % (address, name)


def log_packets(sock, log):
    while True:
        try:
            data = sock.recv(1 << 16)
        except OSError as exc:
            if exc.errno == errno.ENOBUFS:   # a burst overflowed the socket; the next packets still arrive
                continue
            raise
        at = 0
        while at + 16 <= len(data):
            size, kind = struct.unpack_from("=IH", data, at)
            if size < 16:
                break
            if kind == (NFNL_SUBSYS_ULOG << 8) | NFULNL_MSG_PACKET:
                found = attributes(data[at + 20:at + size])
                target = destination(found.get(NFULA_PAYLOAD, b""))
                if target:
                    uid = found.get(NFULA_UID, b"")
                    log.add("connect", target, struct.unpack(">I", uid)[0] if len(uid) == 4 else None)
            at += (size + 3) & ~3


def address(text, default_port):
    host, _, port = text.rpartition(":")
    return (host, int(port)) if host else (text, default_port)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--listen", default="127.0.0.1:53")
    parser.add_argument("--upstream", default=None, help="default: the nameserver in /etc/resolv.conf")
    parser.add_argument("--allowlist", default=ALLOWLIST)
    parser.add_argument("--log", default=LOG)
    parser.add_argument("--no-packets", action="store_true", help="leave out the denied-packet log (needs Linux)")
    args = parser.parse_args(argv)
    with open(args.allowlist, encoding="utf-8") as listed:
        allowed = {line.strip().lower().rstrip(".") for line in listed if line.strip()}
    upstream = address(args.upstream or resolv_conf_upstream(), 53)
    packets = None if args.no_packets else nflog_socket()
    resolver = Resolver(allowed, upstream)
    servers = dns_servers(resolver, address(args.listen, 53))
    # The health check waits for the log, so everything is listening before it exists.
    resolver.log = log = DenialLog(args.log)
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    print("egress: answering DNS for %d allowlisted names on %s" % (len(allowed), args.listen), flush=True)
    if packets is None:
        threading.Event().wait()
    log_packets(packets, log)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
