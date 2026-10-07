# Trust and safety

CopyRoom uses local source directories. Review a source before you render it.
Templateer validators run before CopyRoom writes output. Path checks reject
traversal, reserved paths, and collisions between layers.

Preview changes stay in a separate jj workspace. Resolve conflicts there.
CopyRoom refuses to apply a stale preview and applies the reviewed tree without
a second render.

See [Local Workflows](local-workflows.md#create-and-update) for the preview and
conflict process. Legacy answer markers require explicit migration; see the
[migration note](../copier/overview.md).
