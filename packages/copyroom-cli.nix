{ lib, python313Packages }:

python313Packages.buildPythonApplication {
  pname = "copyroom";
  version = "0.2.0";

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      ../README.md
      ../src
      ../demo
    ];
  };
  pyproject = true;

  build-system = [
    python313Packages.hatchling
  ];

  dependencies = [
    python313Packages.copier
    python313Packages.pyyaml
    python313Packages.pydantic
  ];

  # nixpkgs ships copier 9.11.x; copyroom's pyproject floors it at 9.15.1 to
  # match the dev (uv) toolchain. The copier features CopyRoom relies on
  # (`_subdirectory`, plain-dir working-tree rendering, `--data-file` /
  # `--vcs-ref`) are stable across copier 9.x, so relax the floor for the Nix
  # build rather than vendoring a newer copier into nixpkgs.
  pythonRelaxDeps = [ "copier" ];

  pythonImportsCheck = [ "copyroom" ];

  meta = with lib; {
    description = "Mode-aware CLI for template-driven project workflows, built on Copier.";
    license = licenses.mit;
    mainProgram = "copyroom";
    platforms = platforms.all;
  };
}
