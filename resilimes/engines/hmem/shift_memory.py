"""Shift memory: the shift lead's escalated decisions as H-MEM records.

* ``remember``: every escalated decision with its counterfactual receipt
  (chosen vs rule default, means over the same sampled futures).
* ``record_override``: a human override with provenance; it marks the twin's
  record of that decision ``wrong`` (trust ledger) and is kept long-term.
* ``recall``: top-5 similar past cases (H-MEM hybrid ranking) for the prompt.
* ``skip_twin`` (sim-only lane): skip the twin when at least
  ``SKIP_MIN_CASES`` close cases of the same kind and family all found
  nothing better than the default. Saves compute; may miss a win.
* ``propose_playbook``: at shift end, playbook rules from repeated receipts.
  Proposals only; a human must ``approve_playbook`` before one becomes a
  long-term record. Nothing is applied automatically.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from resilimes.engines.hmem.engine import HMEM, Memory

SOURCE = "sim_select:twin_receipt"
SKIP_MIN_CASES = 3
SKIP_MIN_SCORE = 0.35  # the H-MEM retrieval threshold
PLAYBOOK_MIN_CASES = 3


def _delta(receipt: dict[str, Any] | None, key: str) -> float | None:
    if not receipt:
        return None
    return round(float(receipt["chosen"][key]) - float(receipt["default"][key]), 2)


def _lever_kinds(entry: dict[str, Any]) -> list[str]:
    chosen = next((p for p in entry.get("plans", []) if p["id"] == entry["chosen"]), None)
    if chosen is None:
        return []
    return sorted({str(lever.get("type")) for lever in chosen.get("levers", [])})


class ShiftMemory:
    def __init__(self, hmem: HMEM | None = None, *, scope: str = "") -> None:
        self.h = hmem or HMEM()
        self.scope = scope  # e.g. "published:seed9" for provenance
        self.by_exception: dict[str, str] = {}
        self.recalls = 0
        self.recalled = 0

    # retrieval ----------------------------------------------------------------
    @staticmethod
    def _query(view: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        tool = next((t["tool"] for t in view.get("tools", []) if t.get("down_until_h")), "")
        text = f"{view['kind']} {view['family']} {tool} {view.get('situation', '')}"
        opts = {
            "domain": view["kind"],
            "entities": [view["family"], view["kind"]] + ([tool] if tool else []),
            "tags": [view["kind"], view["family"]],
        }
        return text, opts

    def recall(self, view: dict[str, Any]) -> list[dict[str, Any]]:
        text, opts = self._query(view)
        result = self.h.query(text, opts)
        self.recalls += 1
        self.recalled += len(result.memories)
        out = []
        for hit in result.memories:
            meta = hit.memory.meta
            out.append(
                {
                    "case": hit.memory.content,
                    "score": round(hit.score, 3),
                    "source": hit.memory.source,
                    "kind": meta.get("kind"),
                    "family": meta.get("family"),
                    "outcome": meta.get("outcome"),
                    "chosen_levers": meta.get("levers"),
                    "delta_wt_min": meta.get("delta_wt_min"),
                    "delta_qviol": meta.get("delta_qviol"),
                    "delta_hot_late": meta.get("delta_hot_late"),
                    "memory_id": hit.memory.id,
                }
            )
        return out

    def skip_twin(self, cases: list[dict[str, Any]]) -> bool:
        close = [c for c in cases if c["score"] >= SKIP_MIN_SCORE and c["source"] == SOURCE]
        if len(close) < SKIP_MIN_CASES:
            return False
        same = {(c["kind"], c["family"]) for c in close}
        return len(same) == 1 and all(c["outcome"] == "default_held" for c in close)

    # writing ------------------------------------------------------------------
    def remember(self, view: dict[str, Any], entry: dict[str, Any]) -> Memory | None:
        receipt = entry.get("receipt")
        if receipt is None:
            return None  # budget / memory skip: no new evidence
        if entry.get("fallback"):
            outcome = "fallback"
        elif entry["chosen"] == entry["default"]:
            outcome = "default_held"
        else:
            outcome = "improved"
        dwt, dq, dh = (_delta(receipt, k) for k in ("wt_min", "qviol", "hot_late"))
        levers = _lever_kinds(entry)
        content = (
            f"{view['kind']} at {view['family']}"
            + (f" ({entry['tool']})" if entry.get("tool") else "")
            + f": {view.get('situation', '')}. Chose {entry['chosen']} "
            + f"[{', '.join(levers) or 'rule default'}]; vs default over "
            + f"{receipt['futures']} futures, {receipt['horizon_h']} h: "
            + f"wt {dwt:+g} min, Q-time {dq:+g}, hot/VIP late {dh:+g} ({outcome})"
        )
        memory = self.h.add(
            content=content,
            source=SOURCE,
            type="factual",
            layer="working",
            confidence=0.7,
            domain=view["kind"],
            tags=[view["kind"], view["family"], outcome],
            entities=[view["family"], view["kind"]]
            + ([entry["tool"]] if entry.get("tool") else []),
            provenance={
                "origin": "simulation",
                "label": "digital-twin receipt (sampled futures, not observed outcome)",
                "refs": {"exception": entry["id"], "scope": self.scope, "t_h": entry["t_h"]},
            },
            meta={
                "kind": view["kind"],
                "family": view["family"],
                "outcome": outcome,
                "levers": levers,
                "chosen": entry["chosen"],
                "delta_wt_min": dwt,
                "delta_qviol": dq,
                "delta_hot_late": dh,
                "receipt": receipt,
            },
        )
        self.by_exception[entry["id"]] = memory.id
        # Trust loop: a recalled case whose outcome this receipt repeats was
        # helpful; one it contradicts was not.
        for case in entry.get("_recalled", []):
            if case.get("source") != SOURCE or self.h.store.get(case["memory_id"]) is None:
                continue
            kind = "helpful" if case.get("outcome") == outcome else "not_helpful"
            self.h.feedback(case["memory_id"], kind)
        return memory

    def record_override(
        self,
        exception_id: str,
        chosen: str,
        *,
        by: str,
        note: str,
        kind: str = "",
        family: str = "",
    ) -> Memory:
        """A human override: kept long-term with provenance; the twin's record of
        the same exception gets ``wrong`` feedback (confidence -0.20, review tag)."""
        twin_id = self.by_exception.get(exception_id)
        memory = self.h.add(
            content=f"Human override at {kind} {family}: chose {chosen}. {note}",
            source="user_correction",
            type="preference",
            layer="long_term",
            confidence=0.9,
            domain=kind or "general",
            tags=[t for t in (kind, family, "override") if t],
            entities=[t for t in (family, kind) if t],
            provenance={
                "origin": "human",
                "label": f"override by {by}",
                "refs": {"exception": exception_id, "at": int(time.time())},
            },
            supersedes=twin_id,
            meta={"kind": kind, "family": family, "outcome": "override", "chosen": chosen},
        )
        if twin_id is not None and self.h.store.get(twin_id) is not None:
            self.h.feedback(twin_id, "wrong", actor=by)
            twin = self.h.store.get(twin_id)
            assert twin is not None
            twin.supersededBy = memory.id
        return memory

    # shift end --------------------------------------------------------------------
    def propose_playbook(self) -> list[dict[str, Any]]:
        """Rules seen often enough in receipts. Proposals only (human approval)."""
        groups: dict[tuple[str, str, str], list[Memory]] = {}
        for m in self.h.store.all():
            if m.source != SOURCE or m.supersededBy:
                continue
            levers = ",".join(m.meta.get("levers") or []) or "rule default"
            key = (m.meta.get("kind", ""), m.meta.get("family", ""), levers)
            groups.setdefault(key, []).append(m)
        totals: dict[tuple[str, str], int] = {}
        for (kind, family, _l), rows in groups.items():
            totals[(kind, family)] = totals.get((kind, family), 0) + len(rows)
        out = []
        for (kind, family, levers), rows in sorted(groups.items()):
            if len(rows) < PLAYBOOK_MIN_CASES or levers == "rule default":
                continue
            dwt = [float(m.meta.get("delta_wt_min") or 0.0) for m in rows]
            dq = [float(m.meta.get("delta_qviol") or 0.0) for m in rows]
            n = totals[(kind, family)]
            text = (
                f"Playbook (proposed): at {kind} on {family}, consider [{levers}]. "
                f"Chosen in {len(rows)} of {n} escalations; twin mean vs default "
                f"wt {sum(dwt) / len(dwt):+.1f} min, Q-time {sum(dq) / len(dq):+.2f}. "
                "Needs shift-lead approval; never applied automatically."
            )
            proposal = self.h.dreaming.propose(
                "playbook",
                text,
                [m.id for m in rows],
                {"kind": kind, "family": family, "levers": levers, "cases": len(rows)},
            )
            out.append({"id": proposal.id, "text": text, "status": proposal.status})
        return out

    def approve_playbook(self, proposal_id: str, *, by: str) -> Memory | None:
        return self.h.dreaming.approve(proposal_id, actor=by)

    # persistence --------------------------------------------------------------------
    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.h.dump(), default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path, *, scope: str = "") -> ShiftMemory:
        memory = cls(scope=scope)
        target = Path(path)
        if target.exists():
            memory.h.load(json.loads(target.read_text(encoding="utf-8")))
        return memory

    def stats(self) -> dict[str, Any]:
        records = self.h.store.all()
        return {
            "records": len(records),
            "receipts": sum(1 for m in records if m.source == SOURCE),
            "overrides": sum(1 for m in records if m.source == "user_correction"),
            "recalls": self.recalls,
            "recalled_cases": self.recalled,
            "ledger": self.h.ledger.stats(),
        }
