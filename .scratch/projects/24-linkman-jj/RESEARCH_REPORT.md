# Research report — Linkman with local jj projects

Date: 2026-10-07 UTC

## Target and method

Test Linkman as the owner of a shared file in two local jj projects. Test
central edits, jj history, a moved source, and a template update. Run the
[executable spike](spike.py) from spike 12's devenv shell:

```sh
cd .scratch/projects/12-jj-render-merge
devenv shell -- python3 ../24-linkman-jj/spike.py
```

The script calls Linkman 0.1.0 through the Linkman repo's devenv shell. It
calls jj 0.45.1 through spike 12's devenv shell. All test projects and shared
files live under this spike's ignored `.devenv/state/run` directory. The
[results](evidence/2026-10-07-results.txt) and
[command transcript](evidence/2026-10-07-transcript.txt) record the run.
All 35 checks passed.

## Findings

Linkman applied `ruff.toml` symlinks in both projects. Each link pointed to
one central `style.toml`. jj committed each symlink as mode `120000` with
the target path as its content. When the central file changed, both projects
read the new bytes. Neither project's jj `@` commit changed. A project commit
therefore records the link path, not the central file's content or revision.

Moving the central file broke both links. Linkman's `check --json` still
reported `clean: true`, because each raw symlink target still matched its
declaration. `linkman apply` then did nothing and left both links broken.
Changing each declaration to the new target and applying Linkman repaired
both links. A system that needs target health must check target existence
separately. This is observed Linkman behavior, also visible in its
[`classify_status` code](/home/andrew/Documents/Projects/linkman/src/linkman/planning.py).

The local render prototype created project A from a template that omitted
`ruff.toml`. After Linkman applied the link and jj committed it, a template
update changed `README.md` and kept the link and its target content. This
proves that the two owners can coexist when their path sets are disjoint.
The current prototype changes the active workspace during update; the
separate workspace spike addresses that operational risk.

A second template generated a regular `ruff.toml`. Linkman refused to
replace it and preserved its bytes. This supports one owner per path as an
enforced rule. A template must omit each Linkman link path.

## Design consequence and limits

Linkman can manage shared files that change in one central location. The
project's jj history does not record central content changes. Record the
central source revision when reproducibility matters. An absolute symlink
target also depends on that machine path. This spike moved the source file,
but did not relocate the projects or clone them to another machine.

The test used one shared text file and one generated template path. It did
not test directories, relative links, concurrent changes, or Linkman's
migration command. The broken-link result is specific to Linkman 0.1.0.
