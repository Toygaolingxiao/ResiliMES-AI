"""H-MEM engine: records, hybrid ranking, feedback, ledger, sleep, conflicts, dreaming.

A local port of the public H-MEM spec (github.com/meterless/meterless,
Apache 2.0). Embeddings are a lightweight hashed bag of words (the spec
allows any embedder; the conformance vectors assert order only where it is
embedding-independent). Times are milliseconds from an injected clock.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TYPES = ("personal", "factual", "preference", "general")
LAYERS = ("short_term", "working", "long_term")
LAYER_WEIGHT = {"long_term": 1.0, "working": 0.8, "short_term": 0.6}
ACTIONS = (
    "create", "read", "update", "delete", "feedback", "promote", "demote", "merge",
    "conflict_detected", "conflict_resolved", "sleep_consolidate", "sleep_archive",
    "sleep_synthesize", "dream_proposed", "dream_approved", "dream_rejected", "restore",
)  # fmt: skip
FEEDBACK = {"helpful": 0.05, "not_helpful": -0.03, "wrong": -0.20}
THRESHOLD = 0.35
TOP_N = 5
DAY_MS = 24 * 3600 * 1000
RECENCY_MS = 14 * DAY_MS
ARCHIVE_AGE_MS = 30 * DAY_MS
ARCHIVE_MAX_ACCESS = 2
CONSOLIDATE_MS = 7 * DAY_MS
SYNTH_COS = 0.82
DREAM_RELATED = 0.35
DREAM_MAX = 8
CONFLICT_GATE = 0.70
ENTITY_CAP = 10
RELATED_CAP = 5
DIM = 256
OPPOSING = (("always", "never"), ("enable", "disable"), ("allow", "forbid"), ("do", "dont"))
_STOP = set(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "and",
        "or",
        "with",
        "by",
        "we",
        "our",
        "it",
        "this",
        "that",
        "when",
        "what",
        "how",
        "do",
        "does",
    ]
)
_TOKEN = re.compile(r"[a-z0-9_.:+-]+")


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    words = tokens(text)
    for gram in words + [f"{a} {b}" for a, b in itertools.pairwise(words)]:
        digest = hashlib.blake2b(gram.encode(), digest_size=4).digest()
        index = int.from_bytes(digest[:2], "big") % DIM
        vec[index] += 1.0 if digest[2] & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return max(0.0, sum(x * y for x, y in zip(a, b, strict=True)))


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


@dataclass
class Memory:
    id: str
    content: str
    source: str
    type: str = "general"
    layer: str = "working"
    confidence: float = 0.7
    timestamp: int = 0
    lastAccessed: int = 0
    accessCount: int = 0
    tags: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    domain: str = "general"
    entities: list[str] = field(default_factory=list)
    relatedTo: list[str] = field(default_factory=list)
    supersedes: str | None = None
    supersededBy: str | None = None
    derivedFrom: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list, repr=False)

    def state(self) -> dict[str, Any]:
        out = {k: copy.deepcopy(v) for k, v in self.__dict__.items() if k != "embedding"}
        return out


@dataclass
class Hit:
    memory: Memory
    score: float
    reason: str


@dataclass
class QueryResult:
    memories: list[Hit]
    strategy: str = "hybrid"


class Ledger:
    """Append-only audit log of the 17 canonical action types."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self.clock = clock
        self.entries: list[dict[str, Any]] = []

    def log(
        self,
        memory_id: str,
        action: str,
        previous: dict[str, Any] | None = None,
        new: dict[str, Any] | None = None,
        actor: str = "system",
        **meta: Any,
    ) -> None:
        if action not in ACTIONS:
            raise ValueError(f"unknown ledger action {action}")
        self.entries.append(
            {
                "memoryId": memory_id,
                "action": action,
                "actor": actor,
                "timestamp": self.clock(),
                "previousState": previous,
                "newState": new,
                "meta": meta,
            }
        )

    def history(self, memory_id: str) -> list[dict[str, Any]]:
        return [entry for entry in self.entries if entry["memoryId"] == memory_id]

    def stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for entry in self.entries:
            out[entry["action"]] = out.get(entry["action"], 0) + 1
        return out


class Store:
    def __init__(self) -> None:
        self.records: dict[str, Memory] = {}

    def get(self, memory_id: str) -> Memory | None:
        return self.records.get(memory_id)

    def all(self) -> list[Memory]:
        return list(self.records.values())


class Sleep:
    def __init__(self, hmem: HMEM) -> None:
        self.h = hmem
        self.backups: dict[str, dict[str, Memory]] = {}

    def _protected(self, memory: Memory) -> bool:
        records = self.h.store.all()
        referenced = any(
            memory.id in (m.derivedFrom + m.relatedTo) or m.supersedes == memory.id
            for m in records
            if m.id != memory.id
        )
        hub = len(memory.relatedTo) >= RELATED_CAP
        return bool(memory.derivedFrom) or memory.supersedes is not None or referenced or hub

    def preview(self) -> dict[str, Any]:
        """Read-only: what execute() would do."""
        now = self.h.clock()
        records = self.h.store.all()
        archive = [
            m.id
            for m in records
            if now - m.timestamp >= ARCHIVE_AGE_MS
            and m.accessCount <= ARCHIVE_MAX_ACCESS
            and not self._protected(m)
        ]
        consolidate = [
            m.id
            for m in records
            if m.layer == "short_term" and now - m.lastAccessed >= CONSOLIDATE_MS
        ]
        groups: list[list[str]] = []
        seen: set[str] = set(archive)
        for a in records:
            if a.id in seen or a.derivedFrom:
                continue
            group = [a.id]
            for b in records:
                if (
                    b.id != a.id
                    and b.id not in seen
                    and not b.derivedFrom
                    and cosine(a.embedding, b.embedding) >= SYNTH_COS
                ):
                    group.append(b.id)
            if len(group) > 1:
                groups.append(group)
                seen.update(group)
        return {"toConsolidate": consolidate, "toArchive": archive, "toSynthesize": groups}

    def execute(self, preview: dict[str, Any]) -> dict[str, Any]:
        h = self.h
        backup_id = f"bk-{len(self.backups) + 1}-{h.clock()}"
        self.backups[backup_id] = copy.deepcopy(h.store.records)
        log: list[str] = []
        for memory_id in preview.get("toConsolidate", []):
            m = h.store.get(memory_id)
            if m is not None:
                before = m.state()
                m.layer = "long_term"
                h.ledger.log(m.id, "sleep_consolidate", before, m.state())
                log.append(f"consolidate {m.id}")
        for memory_id in preview.get("toArchive", []):
            m = h.store.get(memory_id)
            if m is not None and not self._protected(m):
                h.ledger.log(m.id, "sleep_archive", m.state(), None)
                del h.store.records[m.id]
                log.append(f"archive {m.id}")
        for group in preview.get("toSynthesize", []):
            members = [h.store.get(i) for i in group]
            alive = [m for m in members if m is not None]
            if len(alive) < 2:
                continue
            merged = h.add(
                content=max(alive, key=lambda m: len(m.content)).content,
                source="sleep",
                type=alive[0].type,
                layer="long_term",
                confidence=max(m.confidence for m in alive),
                tags=sorted({t for m in alive for t in m.tags}),
                entities=sorted({e for m in alive for e in m.entities})[:ENTITY_CAP],
                derivedFrom=[m.id for m in alive],
            )
            h.ledger.log(merged.id, "sleep_synthesize", None, merged.state())
            for m in alive:
                h.ledger.log(m.id, "merge", m.state(), None, into=merged.id)
                del h.store.records[m.id]
            log.append(f"synthesize {merged.id}")
        return {"backupId": backup_id, "log": log, "counts": {"actions": len(log)}}

    def restore(self, backup_id: str) -> None:
        self.h.store.records = copy.deepcopy(self.backups[backup_id])
        self.h.ledger.log("*", "restore", None, None, backupId=backup_id)


class Conflicts:
    def __init__(self, hmem: HMEM) -> None:
        self.h = hmem
        self.queue: list[dict[str, Any]] = []

    def scan(self) -> list[dict[str, Any]]:
        found = []
        records = self.h.store.all()
        for a, b in itertools.combinations(records, 2):
            if a.supersedes == b.id or b.supersedes == a.id:
                continue
            ta, tb = set(tokens(a.content)), set(tokens(b.content))
            for x, y in OPPOSING:
                if (x in ta and y in tb) or (y in ta and x in tb):
                    rest = _jaccard(ta - {x, y}, tb - {x, y})
                    if rest >= 0.5:
                        conf = 0.5 + 0.3 * rest + (0.1 if set(a.entities) & set(b.entities) else 0)
                        conf += 0.1 if a.domain == b.domain else 0.0
                        found.append({"a": a.id, "b": b.id, "kind": f"{x}/{y}", "confidence": conf})
                        self.h.ledger.log(a.id, "conflict_detected", other=b.id)
                        break
        return found

    def autoResolve(self, conflict: dict[str, Any]) -> str:
        h = self.h
        a, b = h.store.get(conflict["a"]), h.store.get(conflict["b"])
        if a is None or b is None:
            return "queued"

        def strength(m: Memory) -> float:
            source = 0.3 if m.source == "user_correction" else 0.0
            return m.confidence + source + 0.01 * min(m.accessCount, 10)

        sa, sb = strength(a), strength(b)
        decision = _clamp01(0.5 + abs(sa - sb))
        if decision < CONFLICT_GATE:
            self.queue.append(conflict)
            return "queued"
        winner, loser = (a, b) if sa >= sb else (b, a)
        before = loser.state()
        loser.supersededBy = winner.id
        h.ledger.log(loser.id, "conflict_resolved", before, loser.state(), winner=winner.id)
        return "resolved"


@dataclass
class Proposal:
    id: str
    kind: str  # insight | invariant | domain | playbook
    content: str
    derivedFrom: list[str]
    meta: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"


class Dreaming:
    def __init__(self, hmem: HMEM) -> None:
        self.h = hmem
        self.proposals: dict[str, Proposal] = {}

    def propose(
        self, kind: str, content: str, derived: list[str], meta: dict[str, Any] | None = None
    ) -> Proposal:
        proposal = Proposal(f"dp-{len(self.proposals) + 1}", kind, content, derived, meta or {})
        self.proposals[proposal.id] = proposal
        self.h.ledger.log(proposal.id, "dream_proposed", None, None, kind=kind)
        return proposal

    def _related(self, a: Memory, b: Memory) -> float:
        tags = _jaccard(set(a.tags), set(b.tags))
        entities = _jaccard(set(a.entities), set(b.entities))
        domain = 1.0 if a.domain == b.domain else 0.0
        kind = 1.0 if a.type == b.type else 0.0
        return (
            0.4 * cosine(a.embedding, b.embedding)
            + 0.15 * tags
            + 0.15 * domain
            + 0.15 * kind
            + 0.15 * entities
        )

    def dream(self) -> list[Proposal]:
        """Proposals for review; nothing is materialized."""
        records = [m for m in self.h.store.all() if m.supersededBy is None]
        out: list[Proposal] = []
        used: set[str] = set()
        for a in records:
            if a.id in used:
                continue
            cluster = [a] + [
                b
                for b in records
                if b.id != a.id and b.id not in used and self._related(a, b) >= DREAM_RELATED
            ]
            if len(cluster) < 2:
                continue
            used.update(m.id for m in cluster)
            kind = "invariant" if a.type in ("preference", "personal") else "insight"
            if sum(1 for p in out if p.kind == kind) >= DREAM_MAX:
                continue
            content = "; ".join(m.content for m in cluster)
            out.append(self.propose(kind, content, [m.id for m in cluster]))
        return out

    def approve(self, proposal_id: str, actor: str = "human") -> Memory | None:
        proposal = self.proposals.get(proposal_id)
        if proposal is None or proposal.status != "pending":
            return None
        proposal.status = "approved"
        created = self.h.add(
            content=proposal.content,
            source="dreaming",
            type="preference" if proposal.kind in ("invariant", "playbook") else "factual",
            layer="long_term",
            confidence=0.8,
            derivedFrom=list(proposal.derivedFrom),
            tags=[proposal.kind],
            meta=dict(proposal.meta),
            provenance={"origin": "dream_approved", "label": f"approved by {actor}"},
        )
        self.h.ledger.log(created.id, "dream_approved", None, created.state(), actor=actor)
        return created

    def reject(self, proposal_id: str, actor: str = "human") -> None:
        proposal = self.proposals.get(proposal_id)
        if proposal is not None and proposal.status == "pending":
            proposal.status = "rejected"
            self.h.ledger.log(proposal_id, "dream_rejected", None, None, actor=actor)


class HMEM:
    """The conformance surface: add, query, feedback, store, ledger, sleep, dreaming, conflicts."""

    def __init__(self, clock: Callable[[], int] | None = None, **opts: Any) -> None:
        if clock is None and "clock" in opts:
            clock = opts["clock"]
        import time

        self.clock: Callable[[], int] = clock or (lambda: int(time.time() * 1000))
        self.store = Store()
        self.ledger = Ledger(self.clock)
        self.sleep = Sleep(self)
        self.conflicts = Conflicts(self)
        self.dreaming = Dreaming(self)
        self._seq = 0

    def add(self, content: str = "", source: str = "", **fields: Any) -> Memory:
        if not isinstance(source, str) or not source.strip():
            raise ValueError("a memory needs a source")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("a memory needs content")
        now = self.clock()
        self._seq += 1
        clean = {k: v for k, v in fields.items() if v is not None}
        clean.setdefault("provenance", {"origin": "direct", "label": source})
        clean["provenance"] = {"learnedAt": now, **clean["provenance"]}
        memory = Memory(
            id=f"mem-{self._seq}", content=content, source=source, timestamp=now,
            lastAccessed=now, **clean,
        )  # fmt: skip
        if memory.type not in TYPES or memory.layer not in LAYERS:
            raise ValueError("bad type or layer")
        memory.confidence = _clamp01(float(memory.confidence))
        memory.entities = memory.entities[:ENTITY_CAP]
        memory.relatedTo = memory.relatedTo[:RELATED_CAP]
        memory.embedding = embed(content)
        self.store.records[memory.id] = memory
        self.ledger.log(memory.id, "create", None, memory.state())
        return memory

    def score(
        self,
        memory: Memory,
        query: str,
        qvec: list[float],
        qtokens: list[str],
        tags: set[str],
        domain: str | None,
        entities: set[str],
    ) -> float:
        semantic = cosine(qvec, memory.embedding)
        keyword = _jaccard(set(qtokens[:8]), set(tokens(memory.content)))
        tag = _jaccard(tags, set(memory.tags)) if tags else 0.0
        dom = 1.0 if domain is not None and domain == memory.domain else 0.0
        ent = _jaccard(entities, set(memory.entities)) if entities else 0.0
        layer = LAYER_WEIGHT[memory.layer]
        age = max(0, self.clock() - memory.lastAccessed)
        recency = math.exp(-age / RECENCY_MS)
        superseded = 1.0 if memory.supersededBy else 0.0
        raw = (
            0.35 * semantic + 0.20 * keyword + 0.10 * tag + 0.10 * dom
            + 0.15 * ent + 0.05 * layer + 0.05 * recency - 0.20 * superseded
        )  # fmt: skip
        return _clamp01(raw) * memory.confidence

    def query(self, query: str, opts: dict[str, Any] | None = None, **kw: Any) -> QueryResult:
        opts = {**(opts or {}), **kw}
        threshold = float(opts.get("threshold", THRESHOLD))
        top_n = int(opts.get("topN", TOP_N))
        tags = set(opts.get("tags") or [])
        entities = set(opts.get("entities") or [])
        domain = opts.get("domain")
        where: Callable[[Memory], bool] = opts.get("where") or (lambda _m: True)
        qvec, qtokens = embed(query), tokens(query)
        hits = [
            Hit(m, self.score(m, query, qvec, qtokens, tags, domain, entities), "hybrid")
            for m in self.store.all()
            if where(m)
        ]
        hits = [hit for hit in hits if hit.score >= threshold]
        hits.sort(key=lambda hit: (-hit.score, hit.memory.id))
        hits = hits[:top_n]
        now = self.clock()
        for hit in hits:
            hit.memory.lastAccessed = now
            self.ledger.log(hit.memory.id, "read", score=round(hit.score, 4))
        return QueryResult(hits)

    def feedback(self, memory_id: str, kind: str, actor: str = "system") -> Memory:
        memory = self.store.records[memory_id]
        if kind not in FEEDBACK:
            raise ValueError(f"feedback kind {kind}")
        before = memory.state()
        memory.confidence = round(_clamp01(memory.confidence + FEEDBACK[kind]), 10)
        if kind == "helpful":
            memory.accessCount += 1
        if kind == "wrong" and "review" not in memory.tags:
            memory.tags.append("review")
        self.ledger.log(memory.id, "feedback", before, memory.state(), actor=actor, kind=kind)
        return memory

    # persistence ------------------------------------------------------------
    def dump(self) -> dict[str, Any]:
        return {
            "seq": self._seq,
            "records": [m.state() for m in self.store.all()],
            "ledger": self.ledger.entries,
            "proposals": [p.__dict__ for p in self.dreaming.proposals.values()],
        }

    def load(self, data: dict[str, Any]) -> None:
        self._seq = int(data.get("seq", 0))
        for row in data.get("records", []):
            memory = Memory(**row)
            memory.embedding = embed(memory.content)
            self.store.records[memory.id] = memory
        self.ledger.entries = list(data.get("ledger", []))
        for row in data.get("proposals", []):
            self.dreaming.proposals[row["id"]] = Proposal(**row)
