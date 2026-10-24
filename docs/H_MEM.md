# H-MEM shift memory

`resilimes/engines/hmem/` is a **local Python port of the public H-MEM spec**
(Meterless, Apache License 2.0, github.com/meterless/meterless:
`AGENTS.md`, `README.md`, conformance vectors). It is **not meterlessd**: no
daemon and no network. Embeddings are a hashed bag of words (256-d, unigrams +
bigrams), not a neural model. Off by default: only the `sim_hmem` and
`sim_llm_hmem` study arms (or an explicit `SimShiftLead(memory=...)`) use it.

## Engine (`engine.py`), spec parameters

- Record: content, source (required), type, layer (short_term / working /
  long_term), confidence, tags, entities, domain, provenance, `derivedFrom`,
  `supersedes` / `supersededBy`, `relatedTo` (≤ 5), access stats.
- Retrieval: `0.35 semantic + 0.20 keyword (Jaccard, top-8) + 0.10 tag +
  0.10 domain + 0.15 entity + 0.05 layer + 0.05 recency (14 d) − 0.20 superseded`,
  × confidence; threshold 0.35; top 5.
- Feedback: helpful +0.05, not_helpful −0.03, wrong −0.20 and a `review` tag.
- Trust ledger: every change is an entry with actor, previous and new state
  (17 actions, as in the spec).
- Sleep: preview (no mutation) → execute (with backup id) → restore. Archives
  records ≥ 30 days old with ≤ 2 accesses and no references; derived records
  are protected.
- Conflicts: opposing pairs are surfaced; auto-resolve only above the 0.70
  gate, the loser marked `supersededBy`; otherwise queued for a human.
- Dreaming: proposals only; nothing materializes before approval, which
  creates a long_term record with `derivedFrom` lineage.

Conformance: `tests/test_hmem_engine.py` runs every case in the vendored
`vectors.json` the way the spec's `runner.ts` does (13/13 pass).

## Shift memory (`shift_memory.py`)

- **Remember**: each escalated decision with its counterfactual receipt
  (chosen vs rule default over the same sampled futures). Provenance says
  "digital-twin receipt (sampled futures, not observed outcome)".
- **Human override** (`record_override`): kept long_term with provenance
  (who, when, why), confidence 0.9; the twin's record of that decision gets
  `wrong` feedback and is superseded.
- **Recall**: top-5 similar cases (kind, family, tool, situation) go into both
  LLM prompts (`sim_llm_hmem`). In the LLM-free `sim_hmem` arm, memory may skip
  the twin when ≥ 3 close cases of the same kind and family all found nothing
  better than the default (saves compute; may miss a win — measured below).
- **Trust loop**: a recalled case is marked helpful / not_helpful by whether
  the new receipt repeats its outcome.
- **Playbook** (`propose_playbook`, shift end): a rule is proposed when the same
  lever set was chosen in ≥ 3 escalations of one kind and family, with the twin
  means. **Proposals only**; `approve_playbook` (a human) materializes one.
  Nothing is applied automatically.

## Evaluation (with vs without memory)

Memory is warm-started on dev seeds 1–3 (book `published`), saved to
`memory_<arm>.json`, and every held-out run (seeds 9–13) loads that same file
without writing back, so held-out runs are independent.

_Running on the box; filled in when the run finishes._

The live comparison (`sim_llm` vs `sim_llm_hmem`, Nemotron) runs on the PC
with `python scripts\run_live_eval.py` (see [AI_SIM_SELECT.md](AI_SIM_SELECT.md)).
