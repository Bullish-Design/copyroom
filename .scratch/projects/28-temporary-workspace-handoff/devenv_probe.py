"""Measure PATH wrapper reach from the root devenv in disposable state."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from harness import JJ_BIN, make_project

from copyroom.local.jj import JJ


def run(command: list[str], env: dict[str, str], cwd: Path) -> dict[str, object]:
    result = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, check=False, timeout=45)
    return {
        "command": command,
        "exit": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip()[-1200:],
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="copyroom-devenv-path-") as temp:
        root = Path(temp)
        source, project, _ = make_project(root)
        wrapper_dir = root / "bin"
        wrapper_dir.mkdir()
        wrapper_log = root / "wrapper.log"
        wrapper = wrapper_dir / "jj"
        wrapper.write_text(
            "#!/bin/sh\n"
            'printf "%s\\n" "$*" >> "$COPYROOM_WRAPPER_LOG"\n'
            'exec "$COPYROOM_REAL_JJ" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{wrapper_dir}:{env['PATH']}"
        env["COPYROOM_REAL_JJ"] = JJ_BIN
        env["COPYROOM_WRAPPER_LOG"] = str(wrapper_log)
        cases = [
            run(["bash", "-c", "command -v jj; jj --version"], env, project),
            run([JJ_BIN, "--version"], env, project),
            run(["bash", "-c", "command -v jj; jj --version"], env, project),
            run(["devenv", "shell", "--", "bash", "-c", "command -v jj; jj --version"], env, Path.cwd()),
            run(["bash", "-c", "jj status --ignore-working-copy"], env, project),
        ]
        before = wrapper_log.read_text() if wrapper_log.exists() else ""
        old_path = os.environ["PATH"]
        try:
            os.environ["PATH"] = env["PATH"]
            os.environ["COPYROOM_REAL_JJ"] = JJ_BIN
            os.environ["COPYROOM_WRAPPER_LOG"] = str(wrapper_log)
            JJ(project).run("status", "--ignore-working-copy")
        finally:
            os.environ["PATH"] = old_path
        after = wrapper_log.read_text()
        direct_file = project / "direct-writer.txt"
        direct_file.write_text("editor style write\n", encoding="utf-8")
        output = {
            "jj_binary": JJ_BIN,
            "python": sys.version.split()[0],
            "devenv_root": os.environ.get("DEVENV_ROOT"),
            "wrapper": str(wrapper),
            "cases": cases,
            "wrapper_log_before_copyroom_jj": before.splitlines(),
            "wrapper_log_after_copyroom_jj": after.splitlines(),
            "direct_file_exists": direct_file.exists(),
            "wrapper_calls_after_direct_file": wrapper_log.read_text().splitlines(),
            "plain_subprocess_lookup": shutil.which("jj", path=env["PATH"]),
        }
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
