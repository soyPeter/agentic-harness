"""Fail-closed, append-only write attempts shared by a repository's worktrees."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time


class IndeterminateWrite(Exception):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Journal:
    def __init__(self, path):
        self.path = Path(path)

    def transaction(self, action):
        try:
            return self._transaction(action)
        except (OSError, ValueError) as exc:
            raise IndeterminateWrite("write journal unavailable; park without writing: %s" % exc)

    def _transaction(self, action):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                rows = []
                if self.path.exists():
                    with self.path.open(encoding="utf-8") as handle:
                        for line in handle:
                            row = json.loads(line)
                            if not isinstance(row, dict) or not row.get("key") or row.get("state") not in (
                                    "attempted", "observed", "retry-authorized"):
                                raise ValueError("invalid write journal record")
                            rows.append(row)
                return action(rows)
            except (OSError, ValueError) as exc:
                raise IndeterminateWrite("write journal unavailable; park without writing: %s" % exc)

    def append(self, row):
        row = dict(row, at=time.time())
        created = not self.path.exists()
        with self.path.open("a+", encoding="utf-8") as handle:
            handle.seek(0, os.SEEK_END)
            offset = handle.tell()
            try:
                if created:
                    for directory in (self.path.parent, self.path.parent.parent):
                        descriptor = os.open(str(directory), os.O_RDONLY)
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            except OSError:
                # An unconfirmed result must not hide the pending attempt on the next read.
                handle.seek(offset)
                handle.truncate()
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
                raise

    @staticmethod
    def latest(rows):
        return {row["key"]: row for row in rows}

    def pending(self):
        return self.transaction(lambda rows: [row for row in self.latest(rows).values()
                                               if row["state"] == "attempted"])

    def begin(self, task, operation, target, intent, repeatable=False):
        """Records an attempt before the write. A write already observed returns its row instead, unless it is
        repeatable: then it is recorded again under the same key."""
        key = digest([task, operation, target, intent])
        def start(rows):
            latest = self.latest(rows)
            pending = [r["key"] for r in latest.values() if r["state"] == "attempted"]
            if pending:
                raise IndeterminateWrite("indeterminate_write: reconcile or park pending attempt(s) %s; no retry"
                                         % ", ".join(pending))
            previous = latest.get(key)
            if previous and previous["state"] == "observed" and not repeatable:
                return key, previous
            self.append(dict(key=key, state="attempted", task=task, operation=operation,
                             target=target, intent=intent))
            return key, None
        return self.transaction(start)

    def observe(self, key, result):
        def finish(rows):
            previous = self.latest(rows).get(key)
            if not previous or previous["state"] != "attempted":
                raise IndeterminateWrite("no pending attempt %s" % key)
            self.append(dict(previous, state="observed", result=result))
        self.transaction(finish)

    def resolve(self, key, evidence, retry=False):
        def finish(rows):
            previous = self.latest(rows).get(key)
            if not previous or previous["state"] != "attempted":
                raise IndeterminateWrite("no pending attempt %s" % key)
            self.append(dict(previous, state="retry-authorized" if retry else "observed",
                             evidence=digest(evidence), result=None))
        self.transaction(finish)

    def execute(self, task, operation, target, intent, call):
        key, previous = self.begin(task, operation, target, intent)
        if previous:
            return previous.get("result")
        # Even an error response may follow a committed write; only a known success clears the attempt.
        result = call()
        self.observe(key, result)
        return result
