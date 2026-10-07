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
  version = "0.4.1";

  src = fetchFromGitHub {
    owner = "Bullish-Design";
    repo = "templateer_v2";
    rev = "70f13f5755c485486c9e98f1007a4fdacad74a9e";
    hash = "sha256-nvS3bcuJOWWyuG8qds+mpO7ANRNjU9tR8N5VT93u7Qk=";
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
