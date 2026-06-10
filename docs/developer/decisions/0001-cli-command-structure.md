# ADR 0001 — CLI command structure: flat verbs vs. noun-grouped subcommands

- **Status:** Accepted — **flat** for v0.x. Revisit at the 1.0 CLI-stability milestone.
- **Date:** 2026-06-10
- **Deciders:** CopyRoom maintainers
- **Applies to:** the entire `copyroom` command surface (`src/copyroom/cli.py`,
  `src/copyroom/session/`).

This record exists so the decision can be **revisited deliberately** rather than
drifted into. If you are adding the Nth command and wondering whether to group it,
read this first.

---

## Context

CopyRoom's CLI is, today, a **flat list of verbs**:

```
copyroom new        copyroom update       copyroom template-checkout
copyroom render     copyroom golden       copyroom template-test
copyroom test       copyroom release-check copyroom template-preview
copyroom update-test copyroom registry    copyroom templatize  copyroom adopt
```

Three facts make "flat" the path of least resistance and "grouped" a larger change
than it first appears:

1. **argparse is flat.** `cli.py:_build_parser` registers one subparser per
   command. Grouping (`copyroom project inspect`) means **nested subparsers** or a
   hand-rolled two-level router.
2. **The session spec is flat.** `.scratch/specs/copyroom-session.allium` defines
   the legal command sets as flat string sets, e.g.
   `command in {"inspect","new","update","status"}` and
   `{"registry","render","test","golden","release-check","update-test"}`. Grouping
   would require respecing these.
3. **The dispatcher keys off flat strings.** `session/model.py`
   (`WORKSHOP_COMMANDS` / `PROJECT_COMMANDS` / `BOOTSTRAP_COMMANDS`) and
   `session/dispatcher.py` (`COMMAND_MODE_MAP`) map a single command token → mode.
   Two-level commands would change the dispatch key shape.

The tension: the **concept doc**
(`.scratch/projects/01-concepting/COPYROOM_CONCEPT_FINAL.md`) narrates a
noun-grouped surface (`project new`, `project inspect`, `template update`,
`template status`, `release check <id>`), while the **implementation and the
session spec** went flat. The two `inspect`/`status` commands being added in
v0.3.0 forced the question.

---

## Options

### Option A — Flat verbs *(chosen)*

`copyroom inspect`, `copyroom status`, `copyroom registry`, …

**Pros**
- **Consistency.** Every command shipped to date is a flat verb. Flat keeps the
  whole surface uniform with zero exceptions.
- **Spec-faithful.** Matches the session spec's flat command sets exactly — no
  `.allium` churn, no dispatcher reshaping.
- **Minimal machinery.** One `add_parser` per command; the existing
  `COMMAND_MODE_MAP`/`COMMAND_FN` dicts work unchanged.
- **Non-breaking.** Adds commands without touching existing ones.
- **Fast to ship** and easy to test (the dispatch model is already proven).

**Cons**
- The namespace grows crowded as commands accumulate (already ~14).
- Generic words (`status`, `test`) carry less context without a noun in front.
- No built-in grouping in `--help` beyond the manually maintained prose groups in
  `COPYROOM_DESCRIPTION`.

**Implications**
- Discoverability leans on the hand-grouped help text and the docs, not on the
  parser structure.
- Mode gating stays a flat `command → mode` lookup.

**Opportunities**
- Cheap to add `project`/`template` **aliases** later (a thin shim that maps
  `project inspect` → the flat `inspect` handler) without splitting the surface —
  a non-breaking on-ramp toward grouping if it's ever wanted.

### Option B — Noun-grouped subcommands

`copyroom project new`, `copyroom project inspect`, `copyroom template update`,
`copyroom template status`, `copyroom workshop render`, …

**Pros**
- Scales to many commands; the noun supplies context.
- Reads like the concept doc; groups map cleanly onto the four surfaces.
- `--help` naturally nests (group help, then command help).

**Cons**
- **Inconsistent unless you regroup *everything*.** Grouping two new commands
  while `new`/`update`/`render` stay flat is the worst of both worlds. Doing it
  properly is a **breaking redesign** of a v0.x CLI (every documented invocation,
  the demo, every test, every skill changes).
- **Spec churn.** The session command sets and the dispatcher key shape both
  change; the spec tests follow.
- **More parser machinery** (nested subparsers or a router) and a richer error
  story ("unknown group" vs "unknown command in group").
- The noun↔mode mapping is non-trivial: `template-checkout`/`-test`/`-preview` are
  *project*-mode commands that act *on* the template — is that `project template
  checkout`? `template checkout`? Grouping forces naming decisions the flat
  surface dodges.

**Implications**
- A migration would want a deprecation window (old flat names aliased + warning)
  to avoid breaking users and the devenv-module/agent-skill consumers.

**Opportunities**
- A clean 1.0 surface; room for genuinely large command counts (workshop ops,
  agent commands, policy commands the concept doc anticipates).

---

## Decision

**Adopt flat verbs for all of v0.x.** Grouping is a 1.0 CLI-stability decision, not
a per-feature one. Shipping `inspect`/`status` (and any new command) flat keeps the
surface uniform, the spec untouched, and the change non-breaking.

`status` and `inspect` overlap, so their scopes are fixed to stay distinct:
- **`inspect`** — the full, `--json`-friendly project report.
- **`status`** — a terse human "where am I" (mode, template + ref, worktree
  cleanliness, and "update available" via the latest-ref resolver).

---

## Consequences

- New commands are added as flat verbs and registered in `WORKSHOP_COMMANDS` /
  `PROJECT_COMMANDS` / `BOOTSTRAP_COMMANDS` accordingly.
- `--help` grouping remains a documentation/`COPYROOM_DESCRIPTION` concern.
- The session spec stays the source of truth for the legal flat command sets.
- We accept gradual namespace crowding as the price of consistency until 1.0.

---

## When to revisit

Reopen this ADR when **any** of these is true:

- The flat namespace exceeds ~20 commands, or two commands collide on a natural
  name.
- We commit to the concept doc's larger surface (workshop ops, `agent *`,
  `context *`, `policy *`) — that volume justifies grouping.
- User/agent feedback shows the flat list is hard to navigate.
- We're cutting **1.0** and want a stable, intentional command grammar (the right
  moment to absorb a breaking redesign).

### Migration path (if we go grouped later)

1. **Spec first:** restructure the command sets in `copyroom-session.allium` and
   decide the noun↔mode↔command grammar (resolve the `template-*` placement).
2. **Parser:** move to nested subparsers (or a small two-level router in
   `_build_parser`); make the dispatch key a `(group, command)` pair or a
   normalized `"group command"` string.
3. **Back-compat:** keep every existing flat name as a **deprecated alias** that
   maps to the new grouped handler and prints a one-line deprecation notice. Hold
   the window for at least one minor release.
4. **Consumers:** update the demo (`demo/walkthrough.sh`), the agent skills
   (`.agents/skills/copyroom-*`), the docs (`docs/user/cli-reference.md` et al.),
   and the spec tests together.
5. **Remove aliases** only at the next major bump.

The cheap intermediate step — **adding grouped aliases without removing flat
names** — is available at any time and is non-breaking; prefer it over a hard
cutover if the motivation is discoverability rather than a clean 1.0 grammar.

## See also

- [Architecture](../architecture.md) — the request lifecycle and dispatch.
- [Module reference](../module-reference.md) — `cli.py` and `session/`.
- `.scratch/specs/copyroom-session.allium` — the flat command sets.
