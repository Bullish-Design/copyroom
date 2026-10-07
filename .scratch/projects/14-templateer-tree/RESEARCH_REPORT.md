# Templateer project tree spike — 2026-10-07

## Question and result

Can a local wrapper compose Templateer artifacts into a project tree from one saved model? **Yes, for the tested fixtures.** Five Templateer `full_file` templates rendered one JSON model into TOML, Markdown, Python, and YAML files. The wrapper checked each artifact before it wrote the tree. Three fresh Python processes produced the same bytes and file modes with different environment values.

Templateer renders one artifact per call. The tree, output path expansion, collision check, file mode, and common schema check belong to the wrapper. This spike does not change Templateer.

## Fixed inputs and environment

- Templateer source: `/home/andrew/Documents/Projects/templateer_v2`. The source file hashes are in [templateer-source-sha256.txt](evidence/2026-10-07/templateer-source-sha256.txt). This spike did not query version control in that repo.
- Python 3.13.14; Templateer 0.4.1; Pydantic 2.13.4; MiniJinja 2.22.0; pytest 9.1.1; Ruff 0.16.1. See [versions.txt](evidence/2026-10-07/versions.txt).
- Inputs: [answers.json](answers.json), [manifest.json](manifest.json), and five Templateer fixtures in [fixtures](fixtures).
- The commands ran from the Templateer repo in its devenv shell. `SECRETSPEC_REASON` satisfies that repo's shell policy. The spike made no model request.

## Exact run commands

From `/home/andrew/Documents/Projects/templateer_v2`:

```bash
SECRETSPEC_REASON='Run local Templateer render spike without model calls' MYPI_AGENT_ROOT=.agents/pi devenv shell -- uv run pytest -q -o addopts='' -p no:cov /home/andrew/Documents/Projects/copyroom/.scratch/projects/14-templateer-tree/test_spike.py
SECRETSPEC_REASON='Run local Templateer render spike without model calls' MYPI_AGENT_ROOT=.agents/pi devenv shell -- uv run ruff check /home/andrew/Documents/Projects/copyroom/.scratch/projects/14-templateer-tree/spike.py /home/andrew/Documents/Projects/copyroom/.scratch/projects/14-templateer-tree/test_spike.py
SECRETSPEC_REASON='Run local Templateer render spike without model calls' MYPI_AGENT_ROOT=.agents/pi devenv shell -- uv run python /home/andrew/Documents/Projects/copyroom/.scratch/projects/14-templateer-tree/spike.py --out /tmp/templateer-tree-final-20261007-2
```

The final test run passed **19 tests**. Ruff passed. See [pytest-final.txt](evidence/2026-10-07/pytest-final.txt), [ruff-final.txt](evidence/2026-10-07/ruff-final.txt), and [render.txt](evidence/2026-10-07/render.txt). Devenv printed an unrelated mypi-agent key setup warning. The requested commands returned zero.

The tree fingerprint was `805143964ac33e73e0c905dd1c37e98c25e0e3e8207a650d3be56dcdc4343960`. The tree contained `README.md`, `config/project.yml`, `pyproject.toml`, `scripts/about.py`, and `src/cedar_lab/__init__.py`. The script mode was `0755`; each other file mode was `0644`.

## Evidence by concern

| Concern | Executable result |
| --- | --- |
| One saved typed model | The wrapper gave the same JSON object to all five `TemplateRegistry.render_from_model()` calls. Each call validated it against a Pydantic schema. The wrapper also required identical JSON schemas across artifacts. |
| Multiple languages | Templateer rendered TOML, Markdown, Python, and YAML. `validate_artifact()` accepted each artifact. |
| Structured data escaping | A description with quotes and a newline stayed a string in TOML and YAML. It did not add an `INJECTED` key. Python parser validation passed. |
| Validators | Templateer's TOML parser rejected invalid TOML. A declared command validator rejected a README without a heading. |
| Paths | The wrapper rejected absolute paths, parent paths, empty segments, reserved VCS segments, backslashes, and path separators in a model value. |
| Ownership | Two artifacts targeting the same path failed. A file and directory prefix collision failed. |
| Modes | The wrapper applied the manifest's executable list and rejected a list entry with no artifact. |
| Byte stability | Three fresh processes used `PYTHONHASHSEED` values `1`, `2147483647`, and `random`; `TZ` values `UTC`, `Pacific/Honolulu`, and `Asia/Tokyo`; `LC_ALL` values `C` and `C.UTF-8`; and different `SOURCE_DATE_EPOCH` values. Every output byte and mode matched. |
| Changed schema | Adding required `license: str` rejected the saved model. Adding `license: str = "MIT"` and using it in the renderer accepted the saved model but changed output bytes. The multi-artifact wrapper rejected a schema mismatch between artifacts. |

## API and design findings

Templateer [validates the model and renders one artifact](/home/andrew/Documents/Projects/templateer_v2/src/templateer/api.py:213). Its [artifact validator](/home/andrew/Documents/Projects/templateer_v2/src/templateer/api.py:249) runs output checks. The [renderer](/home/andrew/Documents/Projects/templateer_v2/src/templateer/renderer.py:20) uses the validated model data and strict undefined behavior. Template metadata has [one output path](/home/andrew/Documents/Projects/templateer_v2/src/templateer/models.py:104). Templateer does not expand that path against the model or create a project tree.

The wrapper in [spike.py](spike.py) proves that composition needs little code. It also shows where the production contract must live: path resolution, one owner per path, schema identity across artifacts, executable modes, and validation before writing.

A saved model alone does not pin output bytes. A schema default or renderer edit can change a later render with unchanged answers. The jj render commit must preserve old bytes as the merge base. A template revision or content digest must identify the source used for each new render. The wrapper should report schema changes before update. This is an inference from the changed-default test.

## Limits

- The fixtures use local, trusted Python schemas. Templateer loads schema Python code, and a declared command validator runs a local command. This spike did not sandbox either one.
- The byte check covers these fixtures and ambient values. It does not prove every possible schema or validator is deterministic.
- The wrapper is an experiment. It does not handle concurrent writers, existing tree symlinks, or destination recovery after an interrupted copy.
- Markdown has no built-in parser. The fixture uses a command validator for its heading rule.
- The spike did not run Templateer's authoring injection audit, model generation, adoption, workshop flow, or jj update path. Other spikes cover or must cover those concerns.

## Run history

The first Ruff run found one import order error in the test file. I fixed that import order and reran Ruff. The final Ruff run passed. The first pytest run also passed, but it inherited unrelated coverage settings and printed coverage warnings. The final run disabled that coverage plugin for this isolated test file and passed all 19 tests.
