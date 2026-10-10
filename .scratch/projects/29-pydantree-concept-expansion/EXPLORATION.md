# Concept expansion: Pydantree in CopyRoom

Date: 2026-10-10
Status: exploration; no runtime change

## Recommendation

Investigate Pydantree as an optional syntax analysis tool for CopyRoom.
Start with precise parameter selection in `templatize`. Keep ordinary render,
preview, apply, and layer convergence on Templateer and jj.

The [local Templateer and jj evaluation](../25-templateer-jj-evaluation/RESEARCH_REPORT.md)
found no role for Pydantree in the project lifecycle. That result still holds.
It did not test syntax analysis of rendered files or source extraction.
This document explores those additional functions.

## What Pydantree provides

Pydantree parses source text with Tree-sitter. Its light `pydantree-sitter`
package maps grammar nodes into schema-backed Pydantic models. A caller can
find typed nodes and receive source spans. Its optional pattern module uses
ast-grep to find structures. A rewrite returns byte-range edits and new text;
the caller writes files if it accepts the result. The separate
`pydantree-sitter-grammar` package builds custom grammar bundles.

These packages operate on syntax inside a file. CopyRoom's composer owns the
project tree, output paths, modes, links, and source snapshots. Templateer
renders artifacts. jj owns render history, previews, and merges. Pydantree
does not supply those functions.

The light package needs a grammar and its matching `node-types.json` schema
for each language. It checks schema vocabulary when it binds the grammar.
The schema and parser must still have recorded provenance. The root
`pydantree` project is a uv workspace envelope; its installable products
have the two names above. The [PyPI distribution named `pydantree`](https://pypi.org/project/pydantree/)
belongs to another project. Use the member package names when testing a
dependency.

Sources: [Pydantree architecture](https://github.com/Bullish-Design/pydantree/blob/c0ccabc730616e4e2ce4bfed1b59db3b5a4618ee/docs/architecture.md),
[user guide](https://github.com/Bullish-Design/pydantree/blob/c0ccabc730616e4e2ce4bfed1b59db3b5a4618ee/docs/user-guide.md),
[light package metadata](https://github.com/Bullish-Design/pydantree/blob/c0ccabc730616e4e2ce4bfed1b59db3b5a4618ee/src/pydantree_sitter/pyproject.toml),
and [Tree-sitter's parsing model](https://tree-sitter.github.io/tree-sitter/).

## Candidate CopyRoom functions

| Function | Current CopyRoom behavior | Proposed use | Priority |
| --- | --- | --- | --- |
| Precise `templatize` parameters | Selected text files replace every occurrence of the project directory name. | Find candidate syntax nodes, show exact spans, and replace only approved values. | First spike |
| Adoption and update reports | Adoption reports paths, hashes, and modes. A preview gives a file tree for review. | Extract named facts from the old and proposed files, then report changes to functions or configuration bindings. | Second |
| Workshop structure checks | Goldens compare exact paths, bytes, modes, and links. | Add optional rules that require a generated entry point or configuration binding. | Second |
| Agent context reports | The current local workflow does not index source constructs. | Report selected symbols and bindings with file and line locations for an agent. | Later |

The first three functions have a direct workflow owner. Agent context needs
a separate user need and report contract before implementation.

### First use: parameter selection in `templatize`

[`templatize`](../../../src/copyroom/local/manage.py) currently calls
`template_text.replace(project.name, "{{ project_name }}")` for each selected
file. A matching name in a comment, unrelated string, or identifier also
changes. The command proves that the default answer reproduces the original
tree. It does not probe a changed answer.

A syntax analysis step could list candidate Python string literals and Nix
bindings with file, line, byte span, and value. The user would select the
intended sites. CopyRoom would create the Templateer source from those
spans. It would then render the original answer and a changed answer.
The original must match the project exactly. The changed answer must alter
only the selected outputs and pass each relevant language check.

Pydantree should locate spans before CopyRoom inserts `{{ project_name }}`.
The intermediate Jinja template may not parse as Python or Nix. CopyRoom
must validate rendered output, not the template text, as source code.

Pydantree's Python example already finds typed functions and assignments.
Its Nix example finds bindings and list expressions. These examples support
a small two-language spike. They do not prove general language coverage.
See the [Python example](https://github.com/Bullish-Design/pydantree/blob/c0ccabc730616e4e2ce4bfed1b59db3b5a4618ee/examples/wheel-extract/extract.py)
and [Nix example](https://github.com/Bullish-Design/pydantree/blob/c0ccabc730616e4e2ce4bfed1b59db3b5a4618ee/examples/devenv-extract/extract.py).

### Later use: reports and workshop checks

CopyRoom could parse both sides of a reviewed preview and compare selected
facts. A report could say that a Python function signature changed or that a
Nix binding gained a package. Pydantree supplies nodes and spans. CopyRoom
would implement the comparison and decide which changes matter.

A workshop rule could check a generated output for a required structure.
For example, it could require a Python entry point or a Nix import.
Exact goldens would remain the source of truth for bytes. A structural rule
would express an additional invariant that survives harmless formatting
changes. A rule violation would be a finding; a missing configured parser
would be a configuration error.

These functions should analyze saved rendered bytes in a preview or scenario.
They should not rerender during apply or change the reviewed tree.

## Integration boundary

Keep syntax analysis behind an explicit command option or workshop rule.
Pass UTF-8 source bytes into a language adapter. Return a plain report with
the source digest, parser identity, schema digest, node kind, and byte span.
Return proposed edits as data. Apply edits only through CopyRoom's existing
reviewed workflow.

The first adapter can use `pydantree-sitter` and a pinned Python grammar.
A Nix adapter needs its own grammar wheel or bundle and vendored schema.
Add the optional `pattern` extra only if typed traversal cannot express the
chosen query. The heavy grammar-authoring package has no current CopyRoom
use; Templateer source files and CopyRoom markers already use established
formats.

Record parser and schema provenance when a report affects a decision.
If a configured policy must pass, treat missing parser assets as exit `2`
and a policy violation as exit `1`. Keep the existing exit `3` for invalid
command use. A read-only optional summary can report `skipped` for an
unsupported language without changing project state.

## Limits and costs

- Pydantree parses text. It does not analyze binary files, symlinks, file
  ownership, or jj conflicts.
- Tree-sitter can recover from invalid syntax. Pydantree's rewrite path has
  language-parser checks for Python and JSON. Other languages need a tested
  validator or a stated weaker result.
- Typed extraction needs a matching grammar and schema per language.
  Distribution, provenance, and version pins add maintenance work.
- Pattern search adds `ast-grep-py`. Its language support and grammar
  agreement need tests for each adapter.
- Syntax spans do not supply a three-way semantic merge. Keep jj's merge and
  conflict workflow in control.
- Native grammar bundles are executable code. Load only trusted, pinned
  parsers. Do not load a source project's arbitrary bundle during a normal
  update.

See Pydantree's [syntax checks](https://github.com/Bullish-Design/pydantree/blob/c0ccabc730616e4e2ce4bfed1b59db3b5a4618ee/src/pydantree_sitter/syntax.py)
and [pattern rewrite contract](https://github.com/Bullish-Design/pydantree/blob/c0ccabc730616e4e2ce4bfed1b59db3b5a4618ee/src/pydantree_sitter/pattern.py#L685).

## Evidence reviewed on 2026-10-10

- The Pydantree checkout is at `c0ccabc730616e4e2ce4bfed1b59db3b5a4618ee`.
  Its root metadata and two member packages report version `0.4.0`.
- Ten focused pattern rewrite and wheel example tests passed. The Python
  extraction example matched its saved transcript and ground truth.
- A direct `devenv shell` in the Pydantree checkout failed during Nix
  evaluation: `dotenv.resolved` had no value. The focused checks ran with
  that checkout's existing Python environment from inside CopyRoom's devenv
  shell. A fresh consumer build remains unverified.
- CopyRoom and Pydantree had clean working copies after the review. No
  source, configuration, or runtime dependency changed.

The passing checks ran from the CopyRoom root with these commands:

```bash
devenv shell -- bash -lc 'cd ../pydantree && .devenv/state/venv/bin/python -m pytest -q tests/test_pattern_rewrite.py tests/test_wheel_example.py'
devenv shell -- bash -lc 'cd ../pydantree && .devenv/state/venv/bin/python examples/wheel-extract/extract.py'
```

## Proposed spike and decision gate

Create one disposable CopyRoom project with a Python source file and a Nix
configuration file. Include intentional name matches in a target value, a
comment, and an unrelated value. Use Pydantree to report candidate spans.
Select one site in each file and build a Templateer source from those sites.

The spike passes when:

1. The default answer renders the original tree byte for byte.
2. A changed answer modifies only selected sites and passes Python and Nix
   validation.
3. An ambiguous or missing site causes a finding before a source is written.
4. The report records parser and schema identities and exact byte spans.
5. The new syntax option reports unsupported files without a silent
   replacement. The existing explicit `templatize` command keeps its behavior.
6. Normal `new`, `update`, and `apply` still run without Pydantree.

After the spike, decide whether the value of targeted parameters justifies
the package and grammar maintenance cost. Then assess semantic preview
reports and workshop rules separately. Do not add Pydantree to CopyRoom's
required runtime dependencies before that decision.
