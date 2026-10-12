# Projects

Create a project from a local Templateer source with `copyroom new`. CopyRoom
stores validated answers and a render head in the project. The source goes to a
private Git ref, not into the tree.

Use `copyroom update` to create an isolated preview. Review the files, then
apply that preview. CopyRoom refuses to apply it if the active project changed
after preview creation.

See [Local Workflows](local-workflows.md#create-and-update) and the
[CLI Reference](cli-reference.md) for command details.
