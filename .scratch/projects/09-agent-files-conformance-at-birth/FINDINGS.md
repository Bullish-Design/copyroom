# Project 09 — agent-files conformance at birth

**Status:** open · discovered 2026-08-06 while bootstrapping `talkee`
(github.com/cjpais/Handy pydantic client) from `template-py` v0.1.8.

## 1. The issue, observed

A freshly generated repo is **not agent-files conformant out of the box**. The
birth sequence ran `copyroom new <template-py> <target> --answers … --trust`
(rendered + ran the `post_project_create` hooks: `repoman-sync`,
`gitman init --colocate`, `gitman seed`). Immediately after, the repo's own
doctor reports:

```
=== copy (copyroom) ===
…
WARN agent-files — non-conformant — run 'copyroom agent-files check' for details
```

and the check pinpoints the problem:

```
Agent-files check → /home/andrew/Documents/Projects/talkee
  AGENTS.md             : ✓ present
  CLAUDE.md             : ✓ symlink → CLAUDE.md
  copyroom              : ✓ present, current
  copyroom-adopt        : ⚠️  present but stale — run 'copyroom agent-files export'
  copyroom-template-edit: ✓ present, current
```

`copyroom agent-files export` fixes it (all three skills current, check green).
So the failure mode is **known, trivial to repair, and no one runs the repair at
birth** — the scaffold ships a stale artifact and the only fix is a manual
command that isn't in any hook, doc's "next steps", or doctor output (doctor
does say *which* check to run, but not *the fix*).

## 2. Root cause

- Templates ship the canonical skills **as static files**
  (`_copy_without_render: [".agents/skills/**"]` in `copier.yml`), because they
  contain literal `{{ }}` examples and must survive byte-for-byte.
- Those static copies pin the skill content to the **template's** copyroom
  version, not the **installed** copyroom's. template-py v0.1.8's
  `copyroom-adopt` predates the installed copyroom 0.6.1's canonical asset —
  hence "present but stale".
- The birth hooks in `copyroom.project.yml` (`post_project_create`) run
  `repoman-sync` (installs repoman skills + devenv docs) but **nothing
  materializes the copyroom skills**. `copyroom agent-files export` — the only
  operation that guarantees conformance with the *installed* copyroom — is not
  in the template hooks, not in `copyroom new`'s post-render work, and not in
  `copyroom update`'s.

## 3. Impact

- Every fresh consumer repo starts life with a **warn-level doctor red** that
  the scaffolder *caused*; a user following the docs (`repoman doctor` as the
  verify step) has to know the secret extra command.
- The stale-skill window re-opens on every copyroom release bump until a
  template re-ships — meaning even repos that were born conformant drift on
  toolchain upgrades. `copyroom update` converges the *template-shipped* copy,
  not the *canonical* one.
- "Conformance" being a manual post-birth chore invites repos to skip it
  entirely.

## 4. Fix options

| # | Option | Pros | Cons |
|---|--------|------|------|
| A | **`copyroom new` (and `update`) finalize with an agent-files export** when the generated project opts into the convention (rendered `copyroom.project.yml` has a non-default `agent:` section). Idempotent; only touches canonical skills; `overlay` respected (overlaid skills are excluded, never clobbered). | Fixes all templates at once; birth is conformant by construction; applies to both `new` and `update`. | `new`/`update` gain a side effect — must stay strictly idempotent and never touch `AGENTS.md` (blueprint only if absent) or overlaid skills. |
| B | Add `copyroom agent-files export` to `template-*` `post_project_create` hooks. | Zero copyroom code. | Moves the burden into every template; only fixes *new* repos, not the drift-on-upgrade window; stale-vs-installed comparison still happens after the fact. |
| C | Make `agent-files check` auto-repair (`--fix`) and have doctor suggest the exact repair command. | Doctor becomes actionable. | Repair still happens on a later pass, not at birth; two commands to learn. |
| D | A+B+C combined. | Belt and braces. | Most surface area; needless if A lands. |

**Recommendation: A**, with C's doctor text improved as a cheap addition
(doctor already names the check — extend the WARN to name the fix:
`run 'copyroom agent-files export'`). B is unnecessary once A ships, and keeps
the template hooks focused on birth lifecycle (toolchain + VCS) rather than
content materialization.

## 5. Design constraints for option A (guardrails)

- Only run when the rendered project has the convention: `copyroom.project.yml`
  `agent:` present (all fields defaulted — the section exists in template-py's
  rendered file even with `overlay: []`, so gate on `skills_dir`/`instructions`
  being set, or simply on the file declaring `copyroom.version` with an `agent`
  key).
- Must be a no-op when nothing to do (all current, no `agent:` section).
- Must **never** overwrite `AGENTS.md` (only create the blueprint if absent —
  current export semantics), never dereference/replace the `CLAUDE.md` symlink,
  never touch overlaid skills.
- Wire the same finalize into `copyroom update` post-merge so the drift-on-upgrade
  window closes.
- Keep `--trust` semantics orthogonal: this is content materialization inside the
  generated project (like the template itself), not a hook command — it should
  run regardless of `--trust`; only the `post_*` hook commands stay gated.

## 6. Acceptance criteria

1. `copyroom new <template-py> <target> --answers … --trust` → immediately
   `copyroom agent-files check` in `<target>` reports all canonical skills
   `✓ present, current` (no manual export).
2. Same for `copyroom new` **without** `--trust`.
3. `copyroom update` on a repo whose template-shipped skills are stale →
   check green afterwards.
4. Overlaid skills (`agent.overlay`) are untouched by both paths.
5. `repoman doctor` in a freshly generated repo shows no `agent-files` WARN.
6. Export remains idempotent: running `check` after `new` twice is stable.

## 7. Evidence / reference

- Reproduction: `copyroom new /home/andrew/Documents/Projects/template-py /tmp/t … --answers … --trust`, then `copyroom agent-files check` (2026-08-06, copyroom 0.6.1, template-py v0.1.8).
- `copyroom agent-files export|check`: `src/copyroom/agent/`; convention doc `docs/user/agent-files.md`; skills live at `src/copyroom/agent/assets/skills/`.
- Birth hooks live in the generated `copyroom.project.yml` (`commands.post_project_create`) — templates `template-py/template/copyroom.project.yml.jinja`, `template-nix` equivalent.
