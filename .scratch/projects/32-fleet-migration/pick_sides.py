#!/usr/bin/env python3
"""Resolve jj conflict hunks in one file by choosing a side for each hunk.

Usage:  pick_sides.py FILE CHOICE...

One CHOICE per hunk, in file order:
  P  keep the project side (the side that holds the hand edits)
  T  keep the template side (the CopyRoom render of the new source)
  B  keep the base (the render of the old source)
  @FILE  use the text of a file as the hunk

jj marks the template side with a commit description that starts with
"copyroom:render". The other side is the project side.

Exit codes: 0 ok, 1 the choice count does not match the hunk count, 3 usage.
"""
import sys
from pathlib import Path

OPEN, CLOSE = "<<<<<<<", ">>>>>>>"


def parse_hunk(lines):
    """Return {"P": text, "T": text, "B": text} for the lines of one hunk."""
    sides = {"P": None, "T": None, "B": None}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("+++++++ "):
            role = "T" if '"copyroom:render' in line else "P"
            i += 1
            body = []
            while i < len(lines) and not lines[i].startswith(("+++++++ ", "%%%%%%% ")):
                body.append(lines[i])
                i += 1
            sides[role] = "".join(body)
        elif line.startswith("%%%%%%% "):
            to_line = lines[i + 1]
            role = "T" if '"copyroom:render' in to_line else "P"
            i += 2
            new, old = [], []
            while i < len(lines) and not lines[i].startswith(("+++++++ ", "%%%%%%% ")):
                tag, text = lines[i][:1], lines[i][1:]
                if tag == " ":
                    new.append(text)
                    old.append(text)
                elif tag == "+":
                    new.append(text)
                elif tag == "-":
                    old.append(text)
                i += 1
            sides[role] = "".join(new)
            sides["B"] = "".join(old)
        else:
            i += 1
    return sides


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 3
    path, choices = Path(argv[1]), argv[2:]
    out, hunk, count = [], None, 0
    for line in path.read_text().splitlines(keepends=True):
        if hunk is None and line.startswith(OPEN):
            hunk = []
        elif hunk is not None and line.startswith(CLOSE):
            if count >= len(choices):
                print(f"{path}: more hunks than choices", file=sys.stderr)
                return 1
            choice = choices[count]
            if choice.startswith("@"):
                out.append(Path(choice[1:]).read_text())
            else:
                out.append(parse_hunk(hunk)[choice] or "")
            count, hunk = count + 1, None
        elif hunk is not None:
            hunk.append(line)
        else:
            out.append(line)
    if count != len(choices):
        print(f"{path}: {count} hunks, {len(choices)} choices", file=sys.stderr)
        return 1
    path.write_text("".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
