# CopyRoom development environment.
#
# This is *not* imported by consumers of the repo (they only get the root
# devenv.nix → modules/copyroom.nix). It is pulled in by the root devenv.yaml's
# `imports: - ./dev` so contributors get the full Python toolchain.
{
  pkgs,
  lib,
  config,
  ...
}:

let
  # Pinned release jj, shared with the consumer module. nixpkgs lags behind jj 0.46, which
  # gitman needs.
  jj = import ../nix/jj.nix { inherit pkgs; };

  # One workspace root for every checkout: `<projects>/gitman-workspaces`. In the main
  # checkout, `devenv.root` is `<projects>/copyroom`. In a workspace, it is
  # `<projects>/gitman-workspaces/NAME`. Both resolve to the same directory.
  projectsDir = builtins.dirOf config.devenv.root;
  workspaceRoot =
    if builtins.baseNameOf projectsDir == "gitman-workspaces" then
      projectsDir
    else
      "${projectsDir}/gitman-workspaces";
in
{
  # https://devenv.sh/basics/
  env.GREET = "copyroom";
  env.GITMAN_WORKSPACE_ROOT = workspaceRoot;

  # https://devenv.sh/packages/
  packages = [
    pkgs.git
    jj
    pkgs.uv
    pkgs.secretspec
  ];

  allium.enable = true;

  # https://devenv.sh/languages/
  languages = {
    python = {
      enable = true;
      version = "3.13";
      venv.enable = true;
      uv.enable = true;
    };
  };

  # The editable uv venv already provides the `copyroom` CLI during development,
  # so don't also build and add the packaged one (that's for consumers).
  copyroom.enable = false;

  # https://devenv.sh/scripts/
  scripts.hello.exec = ''
    echo hello from $GREET
  '';

  # devman — the automation plane (CONCEPT.md §5). `base` alone: this repository
  # ships no scheduled work and writes none of its own files. Lives here, in the
  # dev-only layer, so consumers who `imports: - copyroom` never see it.
  # https://devenv.sh/tasks/
  #
  # The two task names the `base` group calls (groups/base/README.md). devenv
  # owns each implementation; Dagu owns the composition (§6). `uv run` rather
  # than bare names: the venv bin is on the interactive shell's PATH but not on
  # the task runner's PATH (STAGE_7_LOG.md, wave 2b). `ruff check src` matches
  # the repo's own `src = ["src"]` scope.
  tasks = {
    "copyroom:lint".exec = "uv run --extra dev ruff check src";
    "copyroom:test".exec = "uv run --extra dev pytest";

    "base:check".after = [ "copyroom:lint" ];
    "base:test".after = [ "copyroom:test" ];
  };

  enterShell = ''
    hello
    git --version
  '';

  # https://devenv.sh/tests/
  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
  '';
}
