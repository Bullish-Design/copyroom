# Copier Migration Note

This page records the former CopyRoom backend. It is not current guidance.

Older projects may have `.copier-answers.yml` or
`.copier-answers.<layer>.yml` markers. CopyRoom does not rewrite these files or
pretend that a Copier source is a local Templateer source. To move a project,
extract a local source with `copyroom templatize`, review it with an exact tree
check, then run `copyroom adopt --answers FILE --write`.

Current source, preview, conflict, and adoption behavior is in
[Local Workflows](../user/local-workflows.md).
