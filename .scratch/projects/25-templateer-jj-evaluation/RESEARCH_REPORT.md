# Local Templateer and jj concept evaluation

Date: 2026-10-07

## Decision

The tested design can cover CopyRoom's local project lifecycle without Copier.
Templateer renders and validates individual text artifacts. A small tree
composer owns paths, modes, static files, symlinks, and one saved input model.
Plain jj stores each rendered tree in a commit line and merges updates into a
project. Separate jj workspaces support candidate renders and previews.
Linkman can own shared symlinks when its paths are outside the rendered tree.
Pydantree has no role in the tested design.

This is a feasibility result from disposable local repositories. The spike
scripts are not a production CLI. The [integrated pilot](../20-templateer-jj-pilot/RESEARCH_REPORT.md)
joined actual Templateer renders with jj preview and apply; the other spikes
tested the remaining lifecycle edges.

## Evidence by capability

| Capability | Result | Evidence |
| --- | --- | --- |
| Multi-file `new` | Five Templateer artifacts used one saved Pydantic model and produced stable bytes and modes in three processes. The composer rejects unsafe and duplicate paths. | [Tree render](../14-templateer-tree/RESEARCH_REPORT.md), [integrated pilot](../20-templateer-jj-pilot/RESEARCH_REPORT.md) |
| Local `update` | T0→T1→T2 gives the expected merge bases. Project edits survive clean merges; jj records conflicts. A separate workspace previews the result without changing the active checkout. | [Render graph](../12-jj-render-merge/RESEARCH_REPORT.md), [workspace](../15-jj-workspace/RESEARCH_REPORT.md), [integrated pilot](../20-templateer-jj-pilot/RESEARCH_REPORT.md) |
| Layers and generated files | Each effective output path needs one owner. Exact and file-directory prefix collisions can be rejected before `new`, layer add, update, or refresh. A conditional seed omission must remain in project state. | [Overlapping layers](../12-jj-render-merge/SPIKE.md), [ownership preflight](../21-path-ownership/RESEARCH_REPORT.md), [prototype fix](../13-local-jj-prototype/test_prototype.py) |
| Explicit LLM generation | Templateer returned a validated model and artifact through its real pipeline with an offline fake Agent. A saved model rerendered without another model call. Refresh made a new artifact only when requested. The old artifact stayed frozen. | [Generation cycle](../16-templateer-generation/RESEARCH_REPORT.md) |
| `adopt` and `templatize` | An existing project's bytes can stay unchanged while a T0 render becomes an ancestor. A local extractor reproduced a sample tree, including an executable file, static binary, and relative symlink; one saved field changed two selected outputs. | [Adoption](../17-jj-adopt/RESEARCH_REPORT.md), [templatize](../23-templateer-templatize/RESEARCH_REPORT.md) |
| Template workshop | A candidate template workspace rendered against a full-tree golden scenario. A separate project workspace showed the update, while both active checkouts stayed unchanged until explicit apply. | [Workshop](../18-jj-template-workshop/RESEARCH_REPORT.md) |
| Shared files | Linkman updated two project symlinks from one central file. jj preserved a Linkman-owned link through a template update when the template omitted that path. | [Linkman and jj](../24-linkman-jj/RESEARCH_REPORT.md) |

## Required design rules

1. **Store rendered bytes in jj.** T0 is the real merge base; T1 is its child.
   Identify the current render head with a stable per-layer marker or ref.
   The graph gives the merge base after the tool finds that head. Old bytes do
   not need to be regenerated to perform the merge.
2. **Record source identity separately.** A local path locates a template but
   does not identify immutable bytes. Record a source commit or content digest,
   Templateer version, manifest digest, validated answers, and any frozen
   generated artifact. A source digest proves identity but does not retrieve a
   missing source; a snapshot or reachable commit is needed for replay.
3. **Preflight ownership.** Compare the effective rendered path sets, including
   generated files and Linkman paths, before touching the active project.
   Reject exact and file-directory prefix collisions. Keep intentional seed
   omissions in project state. Path transfer needs an explicit action.
4. **Preview in a separate workspace.** Compare with `jj diff --from <project>
   --to <preview>`; a plain diff on a merge commit can appear empty. Apply
   only after checks and an explicit command. Record the operation ID before
   apply for controlled rollback. Resolve conflicts through jj's conflict
   state.
5. **Treat generation as an event.** Save the validated model and exact
   artifact after a provider call. Reuse that artifact until an explicit
   refresh. A renderer or schema change can alter a rerender even when saved
   answers are unchanged, so report the source change.

The earlier idea that `devenv.lock` pins local templates was **wrong** in the
tested setup. In devenv 2.4.0, a local [`path:` input](../19-devenv-local-input/RESEARCH_REPORT.md)
stored a path without a revision. A local [`git+file://` input](../22-devenv-git-file/RESEARCH_REPORT.md)
stored the branch name and URL without a revision or content hash; it followed
the new branch tip after evaluation refresh while its lock stayed unchanged.
Use devenv to supply the toolchain and tests. Record template source identity
in the project protocol.

The initial byte-stability test is useful for avoiding noisy updates. Strict
determinism is not a precondition for jj's merge algebra because T0 is stored
as an immutable render commit. A nondeterministic rerender can still produce
spurious changes and conflicts. Freeze generated output and control ordinary
renderer inputs.

## Work remaining before replacing CopyRoom

- Build one maintained CLI and tree composer from the pilots. Give it stable
  project markers, source lookup, immutable source identity, exit codes, and
  preflight checks. Do not run the disposable prototype in a managed repo.
- Define source relocation and retrieval. An absolute local path failed after
  both source and project moved; an explicit source override recovered it.
  A digest alone cannot restore unavailable source bytes.
- Define file policy for CRLF, non-UTF-8 text, binary files, symlinks, modes,
  case-insensitive path collisions, and special files. The templatize test
  covered only simple LF text, one binary, and one relative symlink.
- Define concurrent change and crash recovery rules for jj workspaces. The
  workspace spike recovered controlled failures; it did not kill a process
  during a write or change the active repo from another process.
- Test a real model provider when provider reliability, credentials, cost,
  and quality become acceptance criteria. The current generation test used
  the real Templateer pipeline with a fake Agent and no network request.
- Decide how to check Linkman target health and source revision. Linkman's
  `check` reported a broken symlink as clean when its raw target still matched
  the declaration. A jj commit stores the symlink target, not central content.

These are implementation and operating rules. None of the completed local
spikes found a need to keep Copier for the requested local-file workflow.
