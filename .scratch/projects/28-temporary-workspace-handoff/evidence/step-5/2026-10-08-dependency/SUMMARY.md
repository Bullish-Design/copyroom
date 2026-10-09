# Step 5: pyjutsu as a CopyRoom dependency (2026-10-08)

pyjutsu v0.23.0 is released on GitHub (tag `v0.23.0` at `ce785dd`, wheel and sdist attached).
The wheel was rebuilt from the tagged tree. It reports `has_test_hooks False`, and `publish-if` answers the
probe. The downloaded release wheel has the same sha256 as the rebuilt file
(`505b0157a19c680fe347b6c44a36c6e6c1585c9b55a7961473810b2bb596b4ef`).

## Change

- `pyproject.toml`: dependency `pyjutsu==0.23.0` and a `[tool.uv.sources]` URL to the release wheel.
- `uv.lock`: gains pyjutsu only (+16 lines).

## Gates (final tree, no environment variable; the guard resolves from the venv)

| Command | Result |
| --- | --- |
| `uv run pytest -q` | exit 0; 158 passed, 0 skipped (guarded mode is now the default) |
| `uv run pytest -q -m slow` | exit 0; 26 passed |
| `uv run ruff check src/ tests/` | exit 0 |
| `bash demo/walkthrough.sh` | exit 0 (publishes through the guard) |

`pyjutsu-on-path.txt` was recaptured after the gates. The first capture ran before `uv run` synced the venv and
showed the old 0.22.0. Every gate ran after the sync.

## Limits

- The wheel needs Linux x86-64 with glibc 2.39 or later. Other platforms build the sdist and need Rust 1.89 or later.
- Step 4 (Vendomat and nix-meta pins, the system toolchain) is not done.
