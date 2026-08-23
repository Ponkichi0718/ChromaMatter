# ChromaMatter repository instructions

These instructions apply to the entire repository.

## Session start

1. Read this `AGENTS.md` completely.
2. Read `HANDOFF.md` completely.
3. Read `CURRENT_STATE.json` and treat pending/failed gates as authoritative.
4. Run `git status --short --branch` before editing. Preserve unrelated or
   user-owned changes; do not discard or overwrite them.

## Branch and publication safety

- Do not commit directly to `main`. Work on a feature branch and use a pull
  request for review.
- Do not commit private models, customer/user models, binaries, executables,
  archives, build output, `dist`, virtual environments, caches, validation
  output, credentials, tokens, personal paths, personal email addresses, or
  other identifying information.
- Do not change public version `0.8beta` unless the project owner explicitly
  requests that version change.
- Do not publish or mark a Windows binary release eligible while
  `CURRENT_STATE.json` or `HANDOFF.md` records an unresolved binary compliance,
  corresponding-source, build, test, archive, privacy, or checksum gate.
- Do not reuse old build or archive evidence after source, packaging, license,
  icon, or documentation bytes change.

## Functional safety contracts

- Do not weaken topology, watertightness, winding, positive-volume,
  self-intersection policy, or 3MF fail-closed validation merely to make an
  export succeed.
- Preserve the existing safe GLB seam-weld and export-time solidification
  boundaries. True holes, ambiguous seams, non-manifold geometry, and invalid
  3MF must continue to fail with an actionable message.
- Preserve manual palette assignment/display separation and the pending-apply
  export guard. Do not allow preview colors and exported colors to diverge
  silently.
- Keep private validation assets read-only and outside the repository. Do not
  record their filenames, hashes, absolute paths, or identifying content in
  public files.

## Change and validation discipline

- Make the smallest behavior-preserving change that completes the task.
- Add or update focused regression tests for changed contracts.
- Before claiming completion, run the focused tests, `git diff --check`, and
  any proportional build/runtime checks recorded in `HANDOFF.md`.
- A source-only test is not evidence for a packaged executable. A preflight
  build is not evidence for a later rebuild.
- Treat license/compliance automation as a conservative engineering gate, not
  as legal advice. Keep ChromaMatter application code
  `GPL-3.0-or-later`; keep TetGen and every third-party component under its own
  stated license.

## Session end

1. Update `HANDOFF.md` with the exact objective, completed work, current state,
   next task, changed files, tests, prohibited actions, and local-only files.
2. Do not include private model names or personal information in the handoff.
3. Show or record `git diff --stat`, `git diff --check`, and
   `git status --short --branch`.
4. Do not commit or push unless the project owner explicitly authorizes those
   actions for that session.
