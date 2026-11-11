#!/usr/bin/env python3
"""Agentic harness (harness-owned): the egress container's log of what it denied (ADR-003).

Runs as root in the egress container once init-firewall.sh has put the rules in force. Every outbound packet the
rules drop goes to an NFLOG group first (init-firewall.sh); this reads that group over netlink and appends one JSON line
per denied packet to /run/harness-egress/denials.jsonl, on the volume the agent's container mounts read-only. The first
line says when the log started. Each judge pass in the agent's container records a summary of the log, which the
receipt cites. Standard library only, like the engine.
"""
from datetime import datetime, timezone
import errno
import json
import os
import socket
import struct
import sys

LOG = "/run/harness-egress/denials.jsonl"
GROUP = 7   # init-firewall.sh logs to this group
MAX_RECORDS = 20000
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


def message(kind, family, attributes, seq):
    body = struct.pack("=BBH", family, 0, socket.htons(GROUP if family == socket.AF_UNSPEC else 0))
    for code, payload in attributes:
        size = 4 + len(payload)
        body += struct.pack("=HH", size, code) + payload + b"\0" * (-size % 4)
    return struct.pack("=IHHII", 16 + len(body), (NFNL_SUBSYS_ULOG << 8) | kind, NLM_F_REQUEST | NLM_F_ACK, seq, 0) + body


def configure(sock, family, attributes, seq):
    sock.send(message(NFULNL_MSG_CONFIG, family, attributes, seq))
    reply = sock.recv(65536)
    if len(reply) >= 20 and struct.unpack_from("=H", reply, 4)[0] == NLMSG_ERROR:
        error = struct.unpack_from("=i", reply, 16)[0]
        if error:
            raise OSError(-error, os.strerror(-error))


def listen():
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


def denial(packet, uid):
    """The record of a denied packet: where it was going, and the uid of the process that sent it."""
    version = packet[0] >> 4 if packet else 0
    if version == 4 and len(packet) >= 20:
        header, protocol, address = (packet[0] & 0x0f) * 4, packet[9], socket.inet_ntop(socket.AF_INET, packet[16:20])
    elif version == 6 and len(packet) >= 40:
        header, protocol, address = 40, packet[6], "[%s]" % socket.inet_ntop(socket.AF_INET6, packet[24:40])
    else:
        return None
    name = PROTOCOLS.get(protocol, str(protocol))
    if protocol in (6, 17) and len(packet) >= header + 4:
        target = "%s:%d/%s" % (address, struct.unpack_from(">H", packet, header + 2)[0], name)
    else:
        target = "%s/%s" % (address, name)
    return {"at": now(), "kind": "connect", "target": target, "uid": uid}


def records(data):
    at = 0
    while at + 16 <= len(data):
        size, kind = struct.unpack_from("=IH", data, at)
        if size < 16:
            break
        if kind == (NFNL_SUBSYS_ULOG << 8) | NFULNL_MSG_PACKET:
            found = attributes(data[at + 20:at + size])
            uid = struct.unpack(">I", found[NFULA_UID])[0] if len(found.get(NFULA_UID, b"")) == 4 else None
            record = denial(found.get(NFULA_PAYLOAD, b""), uid)
            if record:
                yield record
        at += (size + 3) & ~3


def main():
    sock = listen()
    written = 0
    with open(LOG, "w", encoding="utf-8") as log:
        log.write(json.dumps({"started": now(), "log": "packets the egress container denied"}) + "\n")
        log.flush()
        os.chmod(LOG, 0o644)
        while True:
            try:
                data = sock.recv(1 << 16)
            except OSError as exc:
                if exc.errno == errno.ENOBUFS:   # a burst overflowed the socket; the next packets still arrive
                    continue
                raise
            for record in records(data):
                if written == MAX_RECORDS:
                    log.write(json.dumps({"at": now(), "truncated": True}) + "\n")
                if written < MAX_RECORDS:
                    log.write(json.dumps(record) + "\n")
                written += 1
            log.flush()


if __name__ == "__main__":
    sys.exit(main())
