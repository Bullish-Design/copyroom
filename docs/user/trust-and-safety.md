# Trust and safety

CopyRoom uses local source directories. Review a source before you render it.
Templateer validators run before CopyRoom writes output. Path checks reject
traversal, reserved paths (including `.agents` and `.claude`), and collisions
between layers.

Preview changes stay in a separate jj workspace. Resolve conflicts there.
CopyRoom refuses to apply a stale preview and applies the reviewed tree without
a second render.

CopyRoom publishes through the pyjutsu guard. It refuses to publish in a colocated
child workspace when the guard is too old to keep that workspace's Git HEAD. See
[Colocated child workspaces](local-workflows.md#colocated-child-workspaces).

See [Local Workflows](local-workflows.md#create-and-update) for the preview and
conflict process. Legacy answer markers require explicit migration; see the
[migration note](../copier/overview.md).
