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
  version = "0.6.0";

  src = fetchFromGitHub {
    owner = "Bullish-Design";
    repo = "templateer_v2";
    rev = "a6d609d5b662d79a8f2512772e23ec32129c59ec";
    hash = "sha256-05j3nadtG/0P/BIHyQGkhkuMVcXKA+oMQOkXQjKaoyE=";
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
