{
  lib,
  fetchFromGitHub,
  buildPythonApplication,
  hatchling,
  click,
  minijinja,
  openai,
  pydantic,
  pydantic-ai-slim,
  pyyaml,
}:

buildPythonApplication {
  pname = "templateer";
  version = "0.5.0";

  src = fetchFromGitHub {
    owner = "Bullish-Design";
    repo = "templateer_v2";
    rev = "55af56f91ecf5ea30cf2bb90d0aefd056830bd65";
    hash = "sha256-JgJQ9zSwvuTJ7disfUQtDpvgmcRctgBNflvQ0NZ1oAY=";
  };
  pyproject = true;

  build-system = [ hatchling ];

  dependencies = [
    click
    minijinja
    openai
    pydantic
    pydantic-ai-slim
    pyyaml
  ];

  doCheck = false;
  pythonImportsCheck = [ "templateer" ];

  meta = with lib; {
    description = "Typed artifact generation and validation";
    license = licenses.mit;
    platforms = [ "x86_64-linux" ];
  };
}
