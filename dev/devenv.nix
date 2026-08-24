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

{
  # https://devenv.sh/basics/
  env.GREET = "copyroom";

  # https://devenv.sh/packages/
  packages = [
    pkgs.git
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
  devman = {
    enable = true;
    project = "copyroom";
    groups = [ "base" ];
  };

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
