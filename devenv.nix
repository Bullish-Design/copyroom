# CopyRoom as an importable devenv module.
#
# `imports: - copyroom` in another project's devenv.yaml pulls in this file,
# which exposes the `copyroom` CLI via modules/copyroom.nix. Keep this surface
# minimal: development-only tooling lives in ./dev (loaded by this repo's own
# devenv.yaml) so it never leaks into consumers.
{ ... }:

{
  imports = [ ./modules/copyroom.nix ];
}
