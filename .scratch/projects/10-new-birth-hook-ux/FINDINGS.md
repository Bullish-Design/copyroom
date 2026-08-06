# Project 10 — `copyroom new` birth-hook UX: trust-gate visibility + workflow-accurate next steps

**Status:** open · discovered 2026-08-06 while bootstrapping `talkee` from
`template-py` v0.1.8.

## 1. The issue, observed

Two adjacent rough edges in `copyroom new`'s post-render output, hit during the
same bootstrap:

**(a) The trust gate is invisible until you know it exists.** The family's
canonical birth ceremony lives in the template's `post_project_create` hooks
(`repoman-sync` → `gitman init --colocate` → `gitman seed`). Running
`copyroom new <template> <target> --answers …` **without** `--trust` renders the
repo but silently skips those hooks — nothing on stdout says the template
declared hooks, that they were skipped, or how to run them. The `--trust`
concept is documented in `docs/user/trust-and-safety.md`, but `new`'s output
doesn't surface it at the point of decision.

**(b) The printed next-steps contradict the workflow.** With hooks skipped, the
tail of `copyroom new` reads:

```
Project created in /home/andrew/Documents/Projects/talkee
  Next: cd /home/andrew/Documents/Projects/talkee
  Next: git init && git add . && git commit -m "Initial generation"
  Next: copyroom inspect
```

`git init && git add . && git commit` is generic Copier advice. The family's
actual VCS birth is **gitman** (`gitman init --colocate --trunk main` +
`gitman seed`), and the post-birth verify step is `repoman doctor`. A user who
follows the printed advice ends up with a plain-git repo outside the lane
model — no `.jj`, no `gitman.toml`, no trunk discipline — and the discrepancy is
invisible until gitman/repoman later complain. This is exactly the state that
caused the initial confusion during the `talkee` bootstrap.

## 2. Root cause

`new`'s next-steps are a static, generic tail (copier-flavoured git advice)
printed after render. `copyroom new` **already reads** `copyroom.project.yml`
after rendering (for project metadata / mode detection) but does not consult
`commands.post_project_create` / `post_template_update` when composing output —
so it neither reports that hooks exist nor tells the truth about how to finish
the birth.

## 3. Impact

- Users (human or agent) can end up with a repo that skipped its declared birth
  lifecycle and a VCS shape the family tooling doesn't manage — then hit
  confusing secondary failures (gitman `no repo`, repoman doctor reds).
- The trust decision is made blindly: you can't consent to running hooks you
  weren't told exist.
- `--trust`'s safety story is good, but the UX around it is a trap for the
  exact scenario the family's templates depend on (hook-bearing templates are
  the norm, not the exception).

## 4. Fix options

| # | Option | Pros | Cons |
|---|--------|------|------|
| A | **Surface hooks in `new`'s output.** After render, read the generated `copyroom.project.yml`; if `commands.post_project_create` is non-empty: print them when `--trust` ran, and when it didn't print a clear "N hooks declared but skipped — re-run with `--trust` (or run them manually)" block. | Zero new commands; fixes the consent gap at the point of decision; cheap. | Re-running `new` into an existing dir is awkward; user still needs the full manual sequence if they refuse `--trust`. |
| B | **Workflow-accurate next-steps.** Replace the generic git advice with the family ceremony (gitman init/seed via the declared `post_project_create`, `repoman doctor` to verify) — print it *when hooks are skipped*. | Output finally teaches the right path. | Doc-only if not paired with A. |
| C | **`copyroom project hooks run`** (new command) — execute the rendered project's `post_project_create` / `post_template_update` on demand (still trust-gated). | Gives a legitimate "finish the birth later" path; makes A's advice executable rather than hand-typed. | New command surface; must re-derive the render-time env (`devenv shell`), mirror `--trust` gating. |
| D | A+B+C. | Complete. | Most surface area. |

**Recommendation: A+B now, C as the follow-up** if A's "re-run with `--trust`"
advice proves insufficient. A and B are small, output-only changes with tests;
C is a real feature and deserves its own planning pass.

## 5. Design constraints

- Read `copyroom.project.yml` from the **rendered** target (post-render), not
  the template — hooks are template-author data and must be shown verbatim as
  declared.
- Trust gate unchanged: hooks never auto-run without `--trust`; A/B only change
  *reporting*.
- Keep `--json` output structured (family contract: plain, parseable lines).
- Next-steps must not hardcode "gitman" — render the *declared* hook commands
  (they are the ceremony); only the fallback advice (no hooks declared) can
  stay generic.

## 6. Acceptance criteria

1. `copyroom new <hook-bearing-template> <target> --answers …` (no `--trust`):
   stdout lists the declared `post_project_create` hooks, states they were
   skipped, and prints workflow-accurate next steps (exact commands to finish
   birth + verify).
2. Same with `--trust`: stdout shows the hooks ran (as today) and next steps
   reflect a born repo (`copyroom inspect`, `repoman doctor`).
3. Template with no hooks: output unchanged from today (generic advice OK).
4. `--json` remains machine-parseable in both modes.
5. Existing `new`/`update` tests stay green; new tests cover all three
   template shapes above.

## 7. Evidence / reference

- Reproduction: `copyroom new /home/andrew/Documents/Projects/template-py /tmp/t … --answers …` (no `--trust`), 2026-08-06, copyroom 0.6.1 — observe the "Next:" block above and the absence of any hooks note.
- Hook declarations: `copyroom.project.yml` `commands.post_project_create` (rendered from `template-py/template/copyroom.project.yml.jinja`).
- Trust model doc: `docs/user/trust-and-safety.md`; `new` CLI reference: `docs/user/cli-reference.md`; implementation: `src/copyroom/project/`.
