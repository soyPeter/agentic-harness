#!/usr/bin/env python3
"""Stands in for Linear's GraphQL API in the self-test: serves issues from fixture files and records mutations.

  fake-linear.py <fixture dir> <port file> <calls file>

Answers 401 unless the Authorization header is "lin_test_key", as Linear does for a wrong key.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer  # HTTPServer resolves its host name on start, which can hang on macOS

FIXTURES, PORT_FILE, CALLS = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def answer(self, code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.headers.get("Authorization") != "lin_test_key":
            return self.answer(401, {"errors": [{"message": "Authentication required"}]})
        query, variables = request.get("query", ""), request.get("variables") or {}
        with CALLS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"query": query.split("(")[0].strip(), "variables": variables}) + "\n")
        if "commentCreate" in query:
            return self.answer(200, {"data": {"commentCreate": {"success": True, "comment": {
                "id": "c1", "url": "https://linear.app/triple/issue/x#comment-c1"}}}})
        if "issueUpdate" in query:
            return self.answer(200, {"data": {"issueUpdate": {"success": True, "issue": {
                "identifier": variables.get("id"), "state": {"name": "In Review", "type": "started"}}}}})
        fixture = FIXTURES / ("%s.json" % variables.get("id"))
        if fixture.is_file():
            return self.answer(200, json.loads(fixture.read_text(encoding="utf-8")))
        return self.answer(200, {"data": {"issue": None}})


server = TCPServer(("127.0.0.1", 0), Handler)
PORT_FILE.write_text(str(server.server_address[1]))
server.serve_forever()
