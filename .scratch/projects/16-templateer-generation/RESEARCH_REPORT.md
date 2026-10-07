# Templateer generation and path ownership spike

Date: 2026-10-07

## Question

Can CopyRoom call Templateer for an explicit generation, freeze its result, replay without a model, and refresh only on request? Does prototype 13 reject a generated file that shares a template path?

## Method

Run [`spike_generation.py`](spike_generation.py) in Templateer's devenv shell. The spike calls the real `TemplateRegistry.generate()` pipeline. A deterministic fake replaces only Pydantic AI's `Agent`. The fake has no network path. The spike copies the real `pyproject-uv` template into a temporary directory.

```bash
cd /home/andrew/Documents/Projects/templateer_v2
SECRETSPEC_REASON='offline generation spike with fake model' \
  devenv shell -- uv run --extra dev python \
  /home/andrew/Documents/Projects/copyroom/.scratch/projects/16-templateer-generation/spike_generation.py
```

The command returned zero and printed four `PASS` lines. [`evidence.json`](evidence.json) records hashes, call counts, and the collision result. Ruff passed after import ordering correction.

## Findings

1. `GenerationResult` supplies `model`, `artifact`, `output_path`, `request`, `warnings`, `attempt`, and `usage`. The fake generation returned a validated model and TOML artifact. The spike also passed that model and artifact to `validate_artifact()`. [Templateer result](../../../../templateer_v2/src/templateer/result.py) and [pipeline](../../../../templateer_v2/src/templateer/pipeline.py) define these fields and validation steps.
2. A saved model re-rendered to identical bytes without another model call. The generation call count stayed at one. An explicit second `generate()` call changed the artifact and raised the call count to two. The first frozen artifact stayed unchanged. [Templateer API](../../../../templateer_v2/src/templateer/api.py) provides the model-free render path.
3. The same model produced different bytes after a renderer edit. The saved artifact stayed unchanged. `GenerationResult` has no template digest or renderer version field. CopyRoom must store a template revision or content digest and a Templateer version beside the frozen model and artifact. For exact replay, CopyRoom should use the frozen artifact. Re-render only when the recorded renderer matches the active renderer.
4. Prototype 13's `overlay_generated()` originally overwrote `pyproject.toml` after `render()` had produced the same path. Neither function rejected this cross-source collision. The follow-up [prototype fix](../13-local-jj-prototype/prototype.py) now rejects exact and file-directory prefix collisions before `new` or `update` changes jj state. Its nine focused tests passed in the [final transcript](../12-jj-render-merge/evidence/2026-10-07/transcript.txt). Production code must apply the same rule when it reuses saved generated paths during an update.

## Limits

The fake model tests orchestration, validation, and replay. It does not test provider quality, costs, credentials, or network failures. Its token counts are synthetic. A real provider can vary its output on refresh, and Templateer does not record the provider's model revision. The spike tests one full-file Templateer output. It does not test region output or multi-file coordination.

Templateer's shell printed unrelated local agent setup warnings. They did not change the command's exit code or the spike result.

## Decision

The explicit generation cycle is feasible with the current Templateer API. A CopyRoom implementation needs a frozen artifact, validated model, output path, and provenance recorded in its own project state. It also needs one owner per output path, with collision checks before `new` and `update`.
