# Templateer templatize and golden spike

Date: 2026-10-07

## Question

Can an existing local project become a Templateer-based multi-file template that reproduces the original tree? Can one saved field change two outputs while an original golden scenario remains exact?

## Method

Run [spike.py](spike.py) in Templateer's devenv shell. The script creates a small existing project in a temporary directory. It extracts four UTF-8 files into four Templateer templates. A small local wrapper renders each template with one shared Pydantic input. The wrapper copies one binary file and one relative symlink from a static area. It restores the executable bit from an extraction plan.

```bash
cd /home/andrew/Documents/Projects/templateer_v2
SECRETSPEC_REASON='offline local templatize spike' \
  devenv shell -- uv run --extra dev python \
  /home/andrew/Documents/Projects/copyroom/.scratch/projects/23-templateer-templatize/spike.py
```

The final command returned zero with 13 passing checks. Ruff passed. [evidence.json](evidence.json) records the original manifest, extraction plan, probe manifest, and changed paths. No provider or network call occurs.

## Findings

- Four Templateer `full_file` templates reproduced the text files. The wrapper assembled the multi-file tree. Templateer itself returns one artifact per template and has no project-tree output API.
- The first direct render missed one final newline in every text file. MiniJinja removed one trailing newline. The extraction step added one newline to each template source that ended in a newline. The next render matched every original path and byte.
- The wrapper stored the executable bit for `scripts/hello.sh` in its extraction plan and restored it after render. Templateer's artifact result does not carry file mode.
- The wrapper copied `assets/pixel.bin` as static bytes because Templateer's renderer reads UTF-8 text and returns a string. It copied `docs/current` as a relative symlink because Templateer has no symlink artifact kind. The golden check compared the binary hash and symlink target.
- The extractor changed only the project name sites in `pyproject.toml` and `README.md` to `{{ project_name }}`. Rendering `alpha` still matched the original whole-tree golden. Rendering `beta` changed exactly those two files. The executable, binary, and symlink stayed equal.

## Design consequence

Templatize needs a tree-level wrapper around Templateer. It needs a plan for artifact paths, modes, static binary files, and symlinks. The wrapper can give each text artifact a Templateer schema and renderer, then render them with one saved input model. It must compare the first render with the existing project before it adopts that project. The [jj adoption spike](../17-jj-adopt/RESEARCH_REPORT.md) shows how an exact render can become a T0 ancestor without changing the project's files.

## Limits

This spike handles simple UTF-8 files with LF line endings. It does not establish a policy for arbitrary binary detection, CRLF, encoding marks, special file modes, or external symlink targets. It does not parameterize output paths: Templateer's `output.path` is static metadata. It does not test a model provider. The wrapper called `validate_artifact()` for each text output without a round-trip model check, because some static files do not contain the shared field. A production extractor needs explicit rules for safe interpolation in unstructured text and for generated shell files.
