{
  lib,
  buildPythonApplication,
  hatchling,
  pydantic,
  pyyaml,
  templateer,
  tomlkit,
  typer,
}:

buildPythonApplication {
  pname = "copyroom";
  version = "0.7.7";

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      ../README.md
      ../src
    ];
  };
  pyproject = true;

  build-system = [
    hatchling
  ];

  dependencies = [
    pyyaml
    pydantic
    templateer
    tomlkit
    typer
  ];

  pythonRelaxDeps = [ "pydantic-ai-slim" ];

  pythonImportsCheck = [ "copyroom" ];

  meta = with lib; {
    description = "Mode-aware CLI for local Templateer and jj project workflows.";
    license = licenses.mit;
    mainProgram = "copyroom";
    platforms = platforms.all;
  };
}
