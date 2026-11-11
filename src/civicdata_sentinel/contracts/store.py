"""Separate append-only review journal with hash chaining and serialized writers."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from .evidence import utcnow
from .models import Proposal

APPLICATION_ID = 0x43535052


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Journal:
    def __init__(self, con):
        self.con = con

    def list(self):
        return [row[0] for row in self.con.execute("SELECT DISTINCT proposal_id FROM journal ORDER BY proposal_id")]

    def load(self, pid):
        parent, state = "", None
        for payload, stored_parent, stored_hash in self.con.execute(
            "SELECT payload,parent,hash FROM journal WHERE proposal_id=? ORDER BY id", (pid,)
        ):
            value = json.loads(payload)
            if stored_parent != parent or digest({"parent": parent, "payload": value}) != stored_hash:
                raise ValueError("Proposal journal integrity check failed")
            parent, state = stored_hash, value
        if state is None:
            raise ValueError("Unknown proposal ID")
        Proposal.model_validate(state["proposal"])
        return state

    def append(self, state, event, *, actor, reason):
        if not actor.strip() or not reason.strip():
            raise ValueError("Actor and reason are required")
        state = {**state, "event": event, "actor": actor, "reason": reason, "at": utcnow()}
        pid = state["id"]
        row = self.con.execute(
            "SELECT hash FROM journal WHERE proposal_id=? ORDER BY id DESC LIMIT 1", (pid,)
        ).fetchone()
        parent = row[0] if row else ""
        hashed = digest({"parent": parent, "payload": state})
        self.con.execute(
            "INSERT INTO journal(proposal_id,payload,parent,hash) VALUES(?,?,?,?)",
            (pid, canonical(state), parent, hashed),
        )
        return state

    def create(self, proposal):
        return self.append(
            {
                "id": uuid4().hex,
                "revision": 1,
                "proposal": proposal.model_dump(),
                "verification": None,
                "decisions": {},
            },
            "generated",
            actor="proposal-engine",
            reason="Generated draft only; no rules approved",
        )

    def edit(self, pid, rules, *, actor, reason):
        state = self.load(pid)
        candidate = {**state["proposal"], "rules": rules}
        proposal = Proposal.model_validate(candidate)
        return self.append(
            {
                **state,
                "revision": state["revision"] + 1,
                "proposal": proposal.model_dump(),
                "verification": None,
                "decisions": {},
            },
            "edited",
            actor=actor,
            reason=reason,
        )


@contextmanager
def workspace(path="state/proposals.sqlite"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + ".lock", timeout=15):
        con = sqlite3.connect(path)
        try:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            app = con.execute("PRAGMA application_id").fetchone()[0]
            if (names and names != {"journal"}) or app not in {0, APPLICATION_ID}:
                raise ValueError("This is not a proposal workspace; monitoring databases must never be used here")
            if names and app != APPLICATION_ID:
                raise ValueError("Unrecognized proposal workspace")
            con.execute(f"PRAGMA application_id={APPLICATION_ID}")
            con.execute(
                "CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY, proposal_id TEXT NOT NULL, "
                "payload TEXT NOT NULL, parent TEXT NOT NULL, hash TEXT NOT NULL)"
            )
            con.commit()
            con.execute("BEGIN IMMEDIATE")
            yield Journal(con)
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()
