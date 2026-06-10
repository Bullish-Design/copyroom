# Adopting & Templatizing an Existing Repo

CopyRoom can bring an **existing, hand-written repo** — one that predates CopyRoom
and has no markers — under template management. There are two commands and two
paths. Both are **bootstrap commands**: they run in an unmanaged repo, bypass
mode detection, and resolve their own context. There is an agent skill,
`copyroom-adopt`, that runs the whole arc.

---

## Choosing a path

```
unmanaged repo R
├── you already HAVE a template T  → ADOPT(T)                       (one step)
└── you have NO template           → TEMPLATIZE(R) → converge → finalize → ADOPT
```

- **You name a template** → skip straight to [Adopt](#adopt).
- **No template yet** → extract one from the repo first
  ([Templatize](#templatize) → [Converge](#converge) → [Finalize](#finalize)),
  then adopt it. Because the extracted template reproduces the repo, that final
  adoption is near-zero-drift.

The template is **named or extracted, never guessed**. CopyRoom will not
fuzzy-match a registry to pick a template for you.

---

## Templatize

Extract a self-contained template repo from the current repo.

```bash
copyroom templatize [--into PATH] [--name NAME] [--id ID]
```

This scaffolds a sibling directory (default `../<repo>-template`) that is, at
once:

- a **Copier template** — `copier.yml` (with `_subdirectory: template` and one
  `project_name` question) plus `template/`, a **verbatim** copy of your repo;
- the **workshop** that exercises it — `copyroom.yml`, `registry/`,
  `scenarios/<id>/default.yml` and `probe.yml`, and `golden/<id>/default/` (a
  snapshot of the repo).

### The verbatim-then-parameterize trick

Copier only renders files ending in `.jinja`. A `template/` copied **verbatim**
(no `.jinja` suffixes) therefore reproduces your repo **exactly** under the
default answers. So `copyroom golden <id> default` reports **no diffs from the
very first render** — you start from a faithful baseline and introduce parameters
*without ever breaking the match*.

The scaffold is left a **plain (non-git) directory** on purpose: Copier renders a
plain directory's working tree directly, so each edit you make shows up
immediately in the golden loop.

```bash
cd my-legacy-app
copyroom templatize --into ../my-legacy-app-template --name my-legacy-app
```

---

## Converge

Work **inside the new template repo**. Introduce template variables one at a time,
keeping the golden match green.

1. **Decide what should be a variable** (the project name, the author, etc.).
   Confirm the inferred answers before committing to them.
2. **Parameterize one file:** rename it to add a `.jinja` suffix and replace the
   literal value with `{{ project_name }}` (or another question you add to
   `copier.yml`):

   ```bash
   cd ../my-legacy-app-template
   git mv template/README.md template/README.md.jinja   # or rm + recreate
   # edit template/README.md.jinja: replace "my-legacy-app" with {{ project_name }}
   ```

   Because the default answer equals the repo name, rendering yields the literal
   again — the golden match holds.
3. **Re-converge:**

   ```bash
   copyroom golden my-legacy-app default     # → ✅ no diffs when faithful
   ```

   Repeat until clean. **`--refresh` is not the goal here** — the repo is the
   ground truth; keep editing `template/` until it matches, don't move the goal
   posts.
4. **Sanity-check over-parameterization** with the `probe` scenario. It renders
   with a deliberately distinct name (`copyroom-probe-xyz`) and has **no golden**
   — it's a review render, not pass/fail:

   ```bash
   copyroom render my-legacy-app probe
   # inspect generated/my-legacy-app/probe/ — a value substituted too broadly
   # shows up as obviously-wrong output here.
   ```

---

## Finalize

Once the golden loop is clean, turn the template into a real, tagged git repo:

```bash
cd ../my-legacy-app-template
git init -q && git add -A && git commit -qm "template v0.1.0" && git tag v0.1.0
```

A tagged git repo is exactly what `adopt` needs (it renders a *ref*).

---

## Adopt

Link the original repo to a template and report drift. **Report-only** — the only
file it can write into the repo is `.copier-answers.yml`, and only with `--write`.

```bash
copyroom adopt <template> [--ref REF] --answers FILE [--write] [--force]
```

Run it from the **repo being adopted**:

1. **Author the answers file yourself.** Read the template's `copier.yml` and
   write the `--answers` file that reproduces the repo. For an extracted template
   that's just `project_name: <repo name>`; pass `--ref v0.1.0`.
2. **Run report-only first** (no `--write`) to see the drift:

   ```bash
   cd my-legacy-app
   cat > answers.yml <<'YAML'
   project_name: my-legacy-app
   YAML
   copyroom adopt ../my-legacy-app-template --ref v0.1.0 --answers answers.yml
   ```

   The drift report has three parts:
   - **Template adds** — files the template produces that the repo lacks.
   - **Differs** — files in both with divergent content.
   - **Repo-only** — files the repo has that the template doesn't (its
     legitimately-extra content).

   A reviewable unified diff is written under `.copyroom/adopt/<timestamp>.patch`.

3. **When the answers look right, record the link:**

   ```bash
   copyroom adopt ../my-legacy-app-template --ref v0.1.0 --answers answers.yml --write
   ```

   This copies the rendered `.copier-answers.yml` into the repo. After that,
   CopyRoom detects the repo as a **project** and it can receive
   `copyroom update`.

```bash
git status            # the only addition is .copier-answers.yml (+ .copyroom/ scratch)
```

---

## Important rules

- **Drift is information, not a problem to auto-fix.** A repo can legitimately
  diverge from its template. `adopt` reports drift; it never rewrites your source
  files. There is no `--reconcile` in v1.
- **`adopt` refuses an already-managed repo** (one with `.copier-answers.yml`)
  unless you pass `--force` — re-adopting would silently retarget the project.
- **The template source must be a git repository** so a ref can be rendered. The
  finalize step provides exactly that; a user-named local template must already be
  a git repo.
- **`templatize` excludes scratch/VCS dirs** from both the verbatim copy and the
  golden snapshot: `.git`, `.copyroom`, `generated`, `__pycache__`,
  `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.venv`, `node_modules`.

## See also

- [The workshop](workshop.md) — `templatize` scaffolds one; here's how to drive it.
- [Copier overview](../copier/overview.md#24-_subdirectory--separating-template-source-from-template-repo) — why `_subdirectory: template` and the `.jinja` rule make this work.
- The `copyroom-adopt` agent skill (`.agents/skills/copyroom-adopt/`).
