# Concepts

CopyRoom composes local Templateer sources into jj-managed projects. Each layer
owns a path set and a render history. Updates run in a separate preview
workspace. A reviewed preview can be applied after CopyRoom checks that the
active project has not changed.

See [Local Workflows](local-workflows.md) for the source format, markers,
previews, layers, and workshop flow.
