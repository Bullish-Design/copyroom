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
  version = "0.4.2";

  src = fetchFromGitHub {
    owner = "Bullish-Design";
    repo = "templateer_v2";
    rev = "a342d1e473b406ad141d028c00756bd0bf958d53";
    hash = "sha256-H3B3qMlKnko7GMOLupmGZP0/HH+p7Z0dwA2rMHC3bI4=";
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
