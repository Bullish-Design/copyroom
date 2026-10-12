# Configuration

Project answers use JSON and must match the shared Pydantic schema in the local
Templateer source. The source manifest lists Templateer artifacts, static
files, executable paths, and safe relative symlinks. No output path may start
with `.agents` or `.claude`, because devman owns them.

A source can be pinned to a Git ref. See
[Versioned sources](local-workflows.md#versioned-sources).

A project tracks one CopyRoom file: `.copyroom-local.json`. The preview,
journal, and lock files under `.copyroom-local/` are local and untracked. CopyRoom
keeps no source copy in the tree. It records each source in the private Git ref
`refs/copyroom/sources/<digest>`. See
[The private source store](local-workflows.md#the-private-source-store).

See [Local Workflows](local-workflows.md#source-format) for the manifest format
and [CLI Reference](cli-reference.md) for command options.
