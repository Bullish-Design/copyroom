#!/usr/bin/env python3
"""Deterministic, dependency-free stand-in for the real renderer.

This spike tests jj's merge, not Jinja. The renderer exists only to make
render(template, answers) a reproducible function of its inputs, which is the
invariant the whole design rests on (Q8): if the render is not byte-stable, the
merge base is garbage and every update conflicts spuriously.

Rules, chosen to mirror the real renderer's contract:

  - `{{ name }}` is substituted in file CONTENT and in PATH segments.
  - An unknown name is a hard error (mirrors MiniJinja strict undefined).
  - Walk order is sorted, output is LF-only, mode is 0644 (0755 if the source
    is executable).
  - Nothing reads the clock, the environment, or hash iteration order.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

VAR = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def subst(text: str, answers: dict[str, object], where: str) -> str:
    missing: list[str] = []

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in answers:
            missing.append(key)
            return ""
        return str(answers[key])

    out = VAR.sub(repl, text)
    if missing:
        sys.exit(f"render: undefined variable(s) {sorted(set(missing))} in {where}")
    return out


def main() -> None:
    if len(sys.argv) != 4:
        sys.exit("usage: render.py <template-dir> <answers.json> <out-dir>")
    template, answers_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    answers = json.loads(answers_path.read_text(encoding="utf-8"))

    files = sorted(p for p in template.rglob("*") if p.is_file())
    for src in files:
        rel = src.relative_to(template)
        dst = out / Path(*[subst(part, answers, str(rel)) for part in rel.parts])
        dst.parent.mkdir(parents=True, exist_ok=True)
        rendered = subst(src.read_text(encoding="utf-8"), answers, str(rel))
        if not rendered.endswith("\n"):
            rendered += "\n"
        dst.write_text(rendered, encoding="utf-8", newline="\n")
        dst.chmod(0o755 if os.access(src, os.X_OK) else 0o644)

    print(f"render: {len(files)} file(s) {template.name} -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
