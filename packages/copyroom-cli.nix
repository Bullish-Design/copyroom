# CopyRoom as a Nix-built Python package.
#
# Two callers use this file:
#   - `flake.nix` passes `pyjutsu` (the guarded publication command) and `runTests = true`.
#   - `modules/copyroom.nix` passes neither. It gets the command without the guard.
#
# CopyRoom runs `jj` and `pyjutsu` as programs. It does not import `pyjutsu`. The package
# wraps `COPYROOM_PYJUTSU` to the pinned `pyjutsu` command and leaves `jj` to the host PATH.
# A second `jj` from this package could differ from the host's `jj` on one repository.
{
  lib,
  buildPythonApplication,
  hatchling,
  pydantic,
  pyyaml,
  templateer,
  tomlkit,
  typer,
  pyjutsu ? null,
  runTests ? false,
  pytestCheckHook,
  pytest-cov,
  hypothesis,
  jujutsu,
  git,
  patch,
}:

let
  pyproject = builtins.fromTOML (builtins.readFile ../pyproject.toml);
in
buildPythonApplication {
  pname = "copyroom";
  version = pyproject.project.version;

  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../pyproject.toml
      ../README.md
      ../src
      ../tests
      # The integration tests read this fixture tree.
      ../.scratch/projects/26-templateer-jj-slice
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
  ] ++ lib.optional (pyjutsu != null) pyjutsu;

  # `pyproject.toml` pins the `pyjutsu` release wheel for uv. The Nix input is the next
  # patch release, which adds only a flake. CopyRoom runs the command, so the pin is relaxed.
  # Without `pyjutsu`, the runtime check skips it. CopyRoom then runs unguarded, as before.
  pythonRelaxDeps = lib.optional (pyjutsu != null) "pyjutsu";
  pythonRemoveDeps = lib.optional (pyjutsu == null) "pyjutsu";

  makeWrapperArgs = lib.optionals (pyjutsu != null) [
    "--set-default"
    "COPYROOM_PYJUTSU"
    "${pyjutsu}/bin/pyjutsu"
  ];

  pythonImportsCheck = [ "copyroom" ];

  # nixpkgs runs the checks in installCheckPhase. pytestCheckHook runs the suite there.
  nativeCheckInputs = lib.optionals runTests [
    pytestCheckHook
    pytest-cov
    hypothesis
    jujutsu
    git
    patch
  ];
  # The suite builds real jj repositories. jj and git want a writable home.
  preInstallCheck = lib.optionalString runTests ''
    export HOME=$TMPDIR
    git config --global user.name test
    git config --global user.email test@example.com
  '';
  postInstallCheck = ''
    export HOME=$TMPDIR
    $out/bin/copyroom --help > /dev/null
  '';

  meta = with lib; {
    description = pyproject.project.description;
    homepage = "https://github.com/Bullish-Design/copyroom";
    license = licenses.mit;
    mainProgram = "copyroom";
    platforms = platforms.all;
  };
}
