---
name: Grotto query optimization validation
description: Real-world feedback on the project's staged performance approach.
---

Prefer measured, staged, behavior-preserving database-read reductions over broad rewrites of Dashboard logic.

**Why:** The user confirmed in real-world use that both sets of low-risk query reductions left the app functioning correctly and felt somewhat faster. That feedback supports the staged approach, not any untested subsequent optimization.

**How to apply:** For future performance work, compare results and query counts before and after; keep sensitive placement, attendance, points, and make-up calculations authoritative unless a separately scoped change justifies altering them.