{ pkgs, ... }:
{
  packages = [ pkgs.jujutsu pkgs.git pkgs.uv ];
  languages.python = {
    enable = true;
    version = "3.13";
    venv.enable = false;
  };
  env = {
    PYTHONDONTWRITEBYTECODE = "1";
    JJ_CONFIG = toString (pkgs.writeText "jj-templateer-slice.toml" ''
      [user]
      name = "CopyRoom Slice"
      email = "slice@example.invalid"
      [ui]
      paginate = "never"
      color = "never"
    '');
  };
  enterTest = ''
    cd "$DEVENV_ROOT"
    uv run python -m unittest discover -s tests -v
    uv run ruff check slice.py tests/
  '';
}
