# CopyRoom is a host tool in nix-meta's developer toolbelt. The developer
# profile installs its CLI from Vendomat's shared toolchain and puts it on PATH.
# Projects do not need a CopyRoom input or this module to run `copyroom`.
#
# Central overlays import RepoMan's manager module when a repository needs it:
#
#   imports = [ /run/current-system/sw/share/repoman/module/devenv.nix ];
#
# This module is not installed at a central CopyRoom path. Keep project tasks,
# packages, and test settings in tracked project files. This module remains for
# CopyRoom's own shell and other explicit standalone environments. Its options
# apply only where a project deliberately imports it.
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
