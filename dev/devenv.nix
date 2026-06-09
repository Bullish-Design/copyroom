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
