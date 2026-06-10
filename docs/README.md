# CopyRoom Documentation

CopyRoom is a **mode-aware CLI for template-driven project workflows**, built on
[Copier](https://copier.readthedocs.io/). It sits on top of Copier's low-level
copy/update operations and adds: directory-mode awareness, a safe project
lifecycle, an agentic "edit the template from your project" loop, a template
author's workshop (render / golden / update-test / release-check), and
report-only adoption of existing repos.

This documentation is split into three tracks. Start wherever fits you.

## 📖 If you *use* CopyRoom — [User Guide](user/)

| Doc | What it covers |
|-----|----------------|
| [Getting started](user/getting-started.md) | Install, the 60-second tour, your first project. |
| [Concepts & mental model](user/concepts.md) | Modes, markers, the four surfaces, the safety philosophy. |
| [CLI reference](user/cli-reference.md) | Every command, every flag, exit codes, output. |
| [Projects: new & update](user/projects.md) | Creating and updating a generated project. |
| [Editing a template from a project](user/template-editing.md) | The `template-checkout → test → preview` loop. |
| [The workshop](user/workshop.md) | `render`, `golden`, `update-test`, `release-check`. |
| [Adopting / templatizing a repo](user/adoption.md) | `templatize` and `adopt`. |
| [Configuration files](user/configuration.md) | `copyroom.yml`, `copyroom.project.yml`, `.copier-answers.yml`. |
| [Trust & safety model](user/trust-and-safety.md) | What runs, what's gated, what's guaranteed. |

## 🔧 If you *develop* CopyRoom — [Developer Guide](developer/)

| Doc | What it covers |
|-----|----------------|
| [Architecture](developer/architecture.md) | The big picture: packages, the request lifecycle, design rules. |
| [Module reference](developer/module-reference.md) | Every package and module, what it owns. |
| [State machines](developer/state-machines.md) | The guarded-lifecycle pattern every workflow follows. |
| [The `_compat` layer](developer/compat-layer.md) | The subprocess boundary to Copier and git. |
| [Testing](developer/testing.md) | The spec / unit / integration tiers and how to run them. |
| [Contributing](developer/contributing.md) | Dev setup, the gate, conventions, how to add a command. |
| [Decision records](developer/decisions/) | ADRs for choices worth revisiting — e.g. [flat vs. nested CLI](developer/decisions/0001-cli-command-structure.md). |

## 🧩 The engine underneath — [Copier Overview](copier/overview.md)

A self-contained, detailed explanation of [Copier](copier/overview.md): templates,
`copier.yml`, the Jinja suffix, `.copier-answers.yml`, `copier copy`, the
three-way-merge `copier update`, conflicts, versioning, and exactly how each
CopyRoom command maps onto Copier. **Read this if anything about templates,
updates, or merges is unclear** — CopyRoom assumes the Copier model.

---

## The shortest possible mental model

```
A TEMPLATE is a skeleton (copier.yml + *.jinja files), tagged with semver.
A PROJECT is generated from a template; it remembers its template + version
          in .copier-answers.yml, so it can be UPDATED later.
A WORKSHOP is the template author's workbench: it proves templates render,
          match a golden snapshot, and update cleanly before release.

CopyRoom detects which of these you're standing in (the MODE) and only offers
the commands that make sense there. It does this by looking for marker files —
never by guessing.
```

## See it live

The repo ships a scripted, end-to-end demo that drives **every** command against
real templates, projects, and a workshop in a throwaway directory — nothing
mocked:

```bash
devenv shell -- bash demo/walkthrough.sh          # full run
devenv shell -- bash demo/walkthrough.sh --pause  # press Enter between acts
devenv shell -- bash demo/walkthrough.sh --keep   # keep the scratch workspace
```
