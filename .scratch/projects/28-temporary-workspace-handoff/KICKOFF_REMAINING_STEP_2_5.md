# Kickoff: finish CopyRoom Step 2.5

Use this prompt from `/home/andrew/Documents/Projects/copyroom`.

## Task and decisions

Finish the remaining Step 2.5 work for CopyRoom. Fix the confirmed publication
race and the test cleanup guard. Update the tests, user documentation, and
recorded evidence to match the final behavior. Do not implement Steps 3, 4, or
5 in this session.

The user made two design decisions on 2026-10-08:

1. CopyRoom may depend on pyjutsu for guarded publication.
2. Design D-A alone is insufficient as the final publication design. Keep it as
   an explicit fallback after correcting its false-success defect. The default
   guarded path belongs to Steps 3 to 5.

Step 2.5 has a narrower obligation. It must never return success or discard
recovery state when a foreign writer changed the project during publication.
The jj command may move `@` before CopyRoom detects this race. Record that
limit clearly. Do not claim that Step 2.5 can reject before `@` moves.

## Start here

1. Read `AGENTS.md`, `.agents/skills/copyroom/SKILL.md`,
   `.agents/skills/gitman/SKILL.md`, and `.agents/skills/writing/SKILL.md`.
   Follow any linked instructions that apply.
2. Run every command inside the devenv shell. Route **all version-control
   actions** through gitman. Never run raw `git` or `jj` in this repository.
   A disposable test project may invoke the pinned jj executable.
3. Run `devenv shell -- gitman status` first. Check the current lane, remote
   relation, changed paths, and lockfiles. Preserve relevant active work.
   Start a new gitman lane stacked on the published Step 2.5 H lane, or use
   its current descendant if it is suitable. Do not silently work from `main`:
   the Step 2.5 E to H changes are published lanes, not trunk commits.
4. Read the full handoff record before editing:
   - `.scratch/projects/28-temporary-workspace-handoff/KICKOFF_PROMPT.md`
   - `.scratch/projects/28-temporary-workspace-handoff/HANDOFF_DESIGN_2026-10-08.md`,
     especially §§3, 6, 9, 14, and 16
   - `.scratch/projects/28-temporary-workspace-handoff/IMPLEMENTATION_GUIDE.md`,
     especially Phases E to H and the Step 3 boundary
   - All other files in that project directory that bear on publication,
     recovery, the crash matrix, or the prototype
5. Verify current code and evidence. The paths and line numbers below identify
   the 2026-10-08 state; they can move.

The published lanes reported before this prompt were E
`d8f4a7feddb2e554373dc8b513b5f3956e8b95bd`, F
`7f4f3059bb4a07ab9a7163cf4a183e4ba067a215`, G
`e9019ffbead380eba4d59f82ebf30126326aeebd`, and H
`0015235342bfe2371014d1d44a10e86484decb4d`. Verify these with
gitman. Do not treat old gate logs as proof of the current tree.

## Confirmed defects to resolve

### 1. False success after an interleaved writer

`src/copyroom/local/workflow.py` checks active state before publication, then
calls `jj new <prepared-head>` for update and layer add. Its later
`_verify_published` check proves that `@` has the prepared parent, tree, marker,
and render. It does not prove that publication started from the checked active
operation or that a competing working-copy commit was not displaced.

`tests/integration/test_local_templateer_jj.py` has two competing-writer tests
near lines 828 to 891. Both inject a foreign `jj commit` just before `jj new`.
Both currently accept successful CopyRoom completion. They assert that the
foreign commit object remains readable, but do not assert that the writer's
work remains on the active line or that recovery state remains. This is the
critical gap. The existing `_check_operation_parent` helper near line 347 is
not called; verify what it actually proves before using it.

Implement the smallest correct Step 2.5 repair for **both** update and layer
add. A race that cannot be proved safe must return a nonzero finding, retain
the journal and preview or equivalent recovery evidence, and explain the next
safe action. Do not run `jj op restore` or silently discard a foreign commit.
Do not make recovery convert a known or ambiguous interleave into success.
Check the operation graph, active commit, and stored prepublication state as
needed. If old journals lack a new field, handle them conservatively. Preserve
the established `0` ok, `1` finding, `2` infrastructure/configuration, and
`3` usage exit-code contract.

First add deterministic regression tests that fail on the present code. Put a
real jj writer at the last boundary before `jj new`. Assert the exact foreign
bytes and commit are reachable, the active lineage or recovery state is
correct, the command returns the required nonzero status, and a later
`status`/`recover` does not report false success. Cover update and layer add.
Also test a command error or crash after publication if the new recovery rule
needs that distinction. Tests must assert outcomes, not only command counts or
file existence.

### 2. Ineffective temporary layer cleanup guard

`tests/integration/test_local_templateer_jj.py` has a cleanup guard near lines
65 to 72. It compares `.jj/repo.resolve()` to the project repository. In a jj
workspace, `.jj/repo` is a text file that contains the repository path.
Resolving the pointer file does not read it. The guard can miss leaked
`copyroom-layer-*` directories. Fix the parser or use the production parser in
`workflow.py` near line 1360. Ensure the guard identifies only temporary
directories owned by the current test. Add one focused check that fails if a
known owned directory is leaked. Do not delete unrelated user directories.

## Recheck the surrounding contract

Review the existing Step 2.5 implementation while making the repairs. Keep
publication verification fatal for marker/tree mismatches. Keep published
state and a useful report when cleanup fails. Preserve conflict detection,
orphan render detection, duplicate render-head detection, NUL-safe tracked
paths, JSON write durability, and explicit working-copy snapshot warnings.
Keep no-change behavior and update-test conflict behavior stable. Check that
docs state the recovery states, report fields, exit codes, colocation rule,
tracked-tree limits, and power-loss limit accurately. Correct a specific gap
that you find; do not expand this into Steps 3 to 5.

The slow matrix lives in `tests/crash/test_publication_crash_matrix.py`.
Inspect its crash points and assertions. Its 26 cases and concurrent-writer
barriers do not by themselves prove the immediate prepublication success path.
Add a case only when it asserts a distinct relevant outcome. Use the evidence
under `.scratch/projects/28-temporary-workspace-handoff/evidence/step-2.5/`
as historical evidence, not as a new test result.

## Gates and completion

Run the focused regressions first. Then run and record fresh results for:

```bash
devenv shell -- uv run pytest -q
devenv shell -- uv run pytest -q -m slow
devenv shell -- uv run ruff check src/ tests/
devenv shell -- bash demo/walkthrough.sh
```

Save concise command results in a new dated Step 2.5 evidence directory.
Record the exact lane/head, test counts, and any known limits. If a gate fails,
fix the cause and rerun that gate. Review gitman status before describing the
change. Include all relevant active changes, apart from clear local artifacts
or secrets. Describe and publish the completed lane with gitman; use no author
attribution line. Report the published lane, results, remaining limits, and
whether Step 3 may now start. Stop before implementing Steps 3 to 5.
