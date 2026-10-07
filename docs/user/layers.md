# Layers

A layer is one local source and its owned output paths. The base layer comes
from `copyroom new`. Add another layer with `copyroom layer add`. Each layer has
an independent jj render history.

CopyRoom rejects exact, prefix, case-folded, and project-owned path collisions.
Use `copyroom update --layer NAME` to preview one layer at a time.

See [Local Workflows](local-workflows.md#layers) for commands and examples.
