# Product

<!-- impeccable:product-schema 1 -->

> Inferred, not interviewed. Impeccable's `init` normally interviews the owner. For the 2026-10 console redesign these fields were inferred from the README, the running demo and the owner's brief (light industrial ops console, dense but clean, fluid but restrained motion). Correct anything that is wrong.

## Platform

web

## Users

Fab shift leads, production planners and industrial-engineering reviewers who watch a semiconductor fab replay (SMT2020) and decide how to reschedule a shift after a disruption. They read the console on a desktop monitor at 1280x800 to 1920x1080, often in English, Chinese or Japanese.

## Product Purpose

ResiliMES shows the fab state, simulates disruption scenarios, rebuilds the shift plan and explains the result with AI answers that are checked against simulator evidence. Success is a reviewer who can see what is down, what is at risk and what the new plan changes without reading raw logs.

## Register

Operate. Tool-like and data-dense: restrained colour that carries status meaning, state-only motion, tabular numerals, no decoration.

## Capabilities and Constraints

- Runs offline: no CDNs; fonts and assets are served from `resilimes/demo/static`.
- Three UI languages (en, zh, ja) share i18n keys; layout must survive the longest string.
- API keys and secrets are never shown; the header shows only the model name and data source.
- Status colours (running, down, PM, Q-time risk, hot lot) must stay distinguishable and meet WCAG AA.
