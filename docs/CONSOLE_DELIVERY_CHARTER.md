# Console delivery charter — mid-version hardening project

Status: founded 2026-11-21. Owner: Toygaolingxiao (merge authority).
Driver: Muse (delinjiang123), increments as PRs.
Tracking: GitHub milestone "Console delivery hardening" + the epic
issue that links this charter.

## Why

A full hands-on UI audit of the running console (2026-11-21; every
page, every control, three languages, two viewport widths) returned a
verdict of **not delivery-ready**: 5 high, 12 medium, 4 low findings.
Individually they are small; together they say the console's pages are
not yet held to one standard — numbers without denominators, states
without explanations, copy that truncates mid-sentence, a main flow
(report generation) that can hang invisibly. This project bundles the
findings into one mid-version effort with a single acceptance gate,
instead of dribbling them out as unrelated issues.

A second event makes workline 0 urgent: PR #107 was merged on
2026-11-21 with a branch-side merge that had silently reverted main
content (PRs #106, #108, #111 and a 25-test file). Restoring that
content is this project's first increment.

## Design principle (owner-directed, 2026-11-21)

Provenance is **compact, checkable, on demand** — not pervasive.
The demo's habit of printing source/disclaimer-style explanation on
every surface is an artifact of the simulation context; real use
would clutter and break layouts. Key numbers carry a minimal
denominator/timing note; full provenance lives in details/hover.
No disclaimer-style long sentences. Audits and increments must not
treat "source labels everywhere" as a goal.

## Scope

In scope: the console frontend (all tabs), /timeline, /report,
/import, and the presentation layer behind them (explain payloads as
rendered). Out of scope: the scheduler core, simulation semantics,
and any change to existing contract semantics (additive fields
only). Contract-first, one PR-sized increment at a time, six-section
PR bodies, per the standing engineering standards.

## Worklines

0. **Restore main.** Rebuild the merge PR #107 should have produced:
   #106 stats labels and tests, #108 claim/v1 extraction, #111 H1/H2
   fix, the deleted extraction test file — while keeping #107's own
   data-source increment intact. (First increment; in flight.)
1. **Main-flow usability.** /report generation becomes asynchronous
   with progress, an estimate, cancel and timeout; the report form
   layout is repaired. (Audit H1, M8.)
2. **Number correctness and denominators.** Duration carry bug
   ("1h 60m" for a 2-hour bar); the two on-time rates get their
   denominators and time points; AI-evidence counts reconciled;
   watch-list heading matches its rows; equipment badge definitions
   stated; bare "—" and skipped-step entries get reasons.
   (Audit H2, H4, M5, M6, M7, M9.)
3. **Input and feedback.** Visible seed validation with the valid
   range; empty states that say why and what to do next; invalid
   lots never enter "recently viewed". (Audit H3, M4, M12.)
4. **Copy and layout system.** Provenance copy converged to the
   principle above; scenario text expandable to full; all strings
   keyed for i18n and re-rendered on language switch; banner
   truncation fixed; the "1.0.0" element's role split. The owner's
   in-flight refresh-button relocation (PR #113) belongs to this
   line's landscape and is not duplicated here.
   (Audit H5, M2, M10, M11.)
5. **Import and information architecture.** /import gains format
   documentation, required columns, a sample, and a result view;
   "back" means the same thing everywhere; the equipment list is
   virtualized or collapsible; keyboard focus is visible and the
   Gantt is keyboard-operable; no state conveyed by colour alone.
   (Audit M3, L1–L4.)

## Acceptance gate

The version is done when a re-audit of the running instance against
the 2026-11-21 checklist shows: zero high findings, every medium
either fixed or explicitly waived in the epic issue, and the full
test suite green at no less than the restored test count. Findings
are re-checked on the live pages, not from code.

## Relation to the standing queue

The dev queue's timeline-honesty candidate (M7) and the other
candidates continue independently; this project owns the audit
findings. Anything that turns out to need a contract-semantics
change stops and becomes a proposal, per the standing mandate.
