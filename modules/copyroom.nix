# Importable devenv module: exposes CopyRoom, Templateer, and jj.
#
# Any devenv-managed project can depend on this repo and pull this module in:
#
#   # devenv.yaml
#   inputs:
#     copyroom:
#       url: github:Bullish-Design/copyroom?ref=v0.7.7
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
  minijinja = pkgs.python313Packages.callPackage ../packages/minijinja.nix { };
  templateer = pkgs.python313Packages.callPackage ../packages/templateer.nix { inherit minijinja; };
  copyroomPackage = pkgs.python313Packages.callPackage ../packages/copyroom-cli.nix { inherit templateer; };
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
      default = copyroomPackage;
      defaultText = lib.literalExpression "pkgs.python313Packages.callPackage ../packages/copyroom-cli.nix { templateer = ...; }";
      description = "The CopyRoom CLI package added to the environment.";
    };
  };

  config = lib.mkIf cfg.enable {
    packages = [ cfg.package pkgs.jujutsu ];
  };
}
