# Adoption and templatize

Use `copyroom adopt` to compare a local source with an existing project. The
report is read-only. Add `--write` to record the source snapshot and jj render
history after you review the report.

Use `copyroom templatize` to extract a local Templateer source from an existing
project. The command checks that the extracted source renders the original
files, modes, binary data, and safe relative symlinks.

See [Local Workflows](local-workflows.md#adopt-and-templatize) for examples.
