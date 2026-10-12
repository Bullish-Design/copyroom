Draft comment for issue #3. Not posted.

---

**Root cause.** Copier 9.19 resolves each destination path before it applies
excludes (`copier/_main.py:827-841`). `.agents` itself passes, because Copier
resolves only the parent of a symlink. The next entry, `.agents/devenv`, is a
plain path. `resolve()` follows the link to devman's central store, which is
outside the destination root. Copier then raises `ForbiddenPathError` at line
839. The exclude check is at line 840, so `--exclude '.agents/**'` cannot help.
`_skip_if_exists` is checked later still.

**Reproduced on 0.7.7.** A clean clone of poddantic `origin/main`
(`_commit: v0.5.0`) with `.agents` as a symlink gives
`ForbiddenPathError: ".agents/devenv" is forbidden`, then
`Update failed at state: failed`, exit 1, and a clean tree. Without the link,
the update runs and records 7 conflicts: `.gitignore`, `AGENTS.md`,
`README.md`, `copyroom.project.yml`, `devenv.nix`, `devenv.yaml`, and
`pyproject.toml`.

**Trigger.** template-py v0.7.0 ships `template/.agents/devenv/**`. devman
owns `.agents` and links it into each project.

**On 0.8.x.** The engine is jj, not Copier. A source that renders `.agents/**`
into a symlinked `.agents` is refused at preflight with exit 1 or 2. CopyRoom
writes nothing through the link. A source without `.agents/**` updates cleanly
with the link in place.

**Decision.** We will not fix this in a 0.7.x release. The fix has two parts:

1. Templates stop shipping `.agents/**`.
2. The fleet migrates to 0.8.x. That work is tracked in #4.

Investigation report: `.scratch/projects/30-fleet-convergence-investigation/REPORT.md`.
