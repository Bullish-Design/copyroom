# Importable devenv module: exposes the CopyRoom CLI.
#
# Any devenv-managed project can depend on this repo and pull this module in:
#
#   # devenv.yaml
#   inputs:
#     copyroom:
#       url: github:Bullish-Design/copyroom?ref=v0.1.0
#       flake: false
#   imports:
#     - copyroom
#
# That puts the `copyroom` command on PATH. Set `copyroom.enable = false` to
# opt out, or override `copyroom.package` to supply your own build.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.copyroom;
in
{
  options.copyroom = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Whether to add the CopyRoom CLI to the environment.";
    };

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../packages/copyroom-cli.nix { };
      defaultText = lib.literalExpression "pkgs.callPackage ../packages/copyroom-cli.nix { }";
      description = "The CopyRoom CLI package added to the environment.";
    };
  };

  config = lib.mkIf cfg.enable {
    packages = [ cfg.package ];
  };
}
