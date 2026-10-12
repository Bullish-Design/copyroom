# Importable devenv module: exposes CopyRoom, Templateer, and the pinned jj 0.46.0.
#
# Any devenv-managed project can depend on this repo and pull this module in:
#
#   # devenv.yaml
#   inputs:
#     copyroom:
#       url: github:Bullish-Design/copyroom?ref=v0.8.2
#       flake: false
#   imports:
#     - copyroom
#
# That puts the `copyroom` command and jj 0.46.0 on PATH. Set `copyroom.enable = false` to
# opt out, or override `copyroom.package` to supply your own build. Set
# `copyroom.jj.package = null` when the project already supplies its own jj 0.46 or later.
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

    jj.package = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = import ../nix/jj.nix { inherit pkgs; };
      defaultText = lib.literalExpression "import ../nix/jj.nix { inherit pkgs; }";
      description = ''
        The jj package added to the environment. The default is the pinned jj 0.46.0 release.
        Set this to null when the project supplies its own jj, so the shell holds only one.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    packages = [ cfg.package ] ++ lib.optional (cfg.jj.package != null) cfg.jj.package;
  };
}
