#!/usr/bin/env python3
"""Race real jj workspace operations against a handoff rebase in disposable repos."""
import concurrent.futures
import pathlib
import re
import subprocess
import tempfile
import threading


def run(args, cwd=None, check=True):
    p = subprocess.run(["jj", *args], cwd=cwd, text=True, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f"jj {args} failed ({p.returncode}): {p.stdout}{p.stderr}")
    return p


def main():
    root = pathlib.Path(tempfile.mkdtemp(prefix="jj-handoff-races-"))
    print("ARTIFACT ROOT", root)
    version_printed = False
    for kind in ("plain-file", "committed-change", "bookmark-change", "new-operation"):
        case = root / kind
        repo = case / "repo"
        ext = case / "external"
        case.mkdir(parents=True)
        run(["git", "init", "--no-colocate", str(repo)])
        if not version_printed:
            print("JJ VERSION", run(["--version"], cwd=repo).stdout.strip())
            for label, args in (
                ("UPDATE STALE HELP", ["workspace", "update-stale", "--help"]),
                ("EDIT HELP", ["edit", "--help"]),
                (
                    "CONDITIONAL UPDATE STALE PROBE",
                    ["workspace", "update-stale", "--expected-operation=deadbeef"],
                ),
                ("CONDITIONAL EDIT PROBE", ["edit", "--expected-current=@", "@"]),
            ):
                result = run(args, cwd=repo, check=False)
                print(label, result.returncode)
                print((result.stdout + result.stderr).strip())
            version_printed = True
        run(["config", "set", "--repo", "user.name", "race tester"], cwd=repo)
        run(["config", "set", "--repo", "user.email", "race@example.invalid"], cwd=repo)
        (repo / "base.txt").write_text("base\n")
        run(["describe", "-m", "base"], cwd=repo)
        run(["bookmark", "create", "base", "-r", "@"], cwd=repo)
        run(["new", "-m", "handoff draft"], cwd=repo)
        run(["workspace", "add", "--name", "external", str(ext)], cwd=repo)
        barrier = threading.Barrier(2)

        def handoff(repo=repo, barrier=barrier):
            barrier.wait()
            return run(["rebase", "-s", "@", "-o", "base"], cwd=repo, check=False)

        def external_action(kind=kind, repo=repo, ext=ext, barrier=barrier):
            barrier.wait()
            if kind == "plain-file":
                (repo / "external.txt").write_text("plain external write\n")
                return "plain write completed"
            if kind == "committed-change":
                (ext / "external.txt").write_text("external committed content\n")
                return run(["describe", "-m", "external committed change"], cwd=ext, check=False)
            if kind == "bookmark-change":
                return run(["bookmark", "set", "external-bookmark", "-r", "@"], cwd=ext, check=False)
            return run(["new", "-m", "concurrent operation"], cwd=ext, check=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(handoff)
            b = pool.submit(external_action)
            ar, br = a.result(), b.result()
        print("\nCASE", kind)
        print("handoff exit", ar.returncode, "stdout", ar.stdout.strip(), "stderr", ar.stderr.strip())
        if isinstance(br, str):
            print("external", br)
        else:
            print("external exit", br.returncode, "stdout", br.stdout.strip(), "stderr", br.stderr.strip())
        for label, args in (("WORKSPACES", ["workspace", "list"]),
                            ("LOG", ["log", "--no-graph", "-n", "10"]),
                            ("OPS", ["op", "log", "--limit", "10"])):
            p = run(args, cwd=repo, check=False)
            print(label, "exit", p.returncode)
            print((p.stdout + p.stderr).strip())
        status = run(["status"], cwd=repo, check=False)
        print("MAIN STATUS", status.stdout.strip(), status.stderr.strip())
        if (repo / "external.txt").exists():
            print("MAIN EXTERNAL CONTENT", (repo / "external.txt").read_text().strip())
        if (ext / "external.txt").exists():
            print("EXT CONTENT", (ext / "external.txt").read_text().strip())

    # Force the harder op-log case: two commands branch from one exact operation,
    # do not integrate, then the experiment integrates both results.
    case = root / "concurrent-operation-branches"
    repo, ext = case / "repo", case / "external"
    case.mkdir()
    run(["git", "init", "--no-colocate", str(repo)])
    run(["config", "set", "--repo", "user.name", "race tester"], cwd=repo)
    run(["config", "set", "--repo", "user.email", "race@example.invalid"], cwd=repo)
    (repo / "base.txt").write_text("base\n")
    run(["describe", "-m", "base"], cwd=repo)
    run(["bookmark", "create", "base", "-r", "@"], cwd=repo)
    run(["new", "-m", "handoff draft"], cwd=repo)
    (repo / "draft.txt").write_text("handoff content\n")
    run(["describe", "-m", "handoff draft with content"], cwd=repo)
    run(["workspace", "add", "--name", "external", str(ext)], cwd=repo)
    op_log = run(["op", "log", "--limit", "1"], cwd=repo).stdout
    base_op = op_log.splitlines()[0].split()[1]
    print("\nCASE concurrent-operation-branches; base op", base_op)
    barrier = threading.Barrier(2)

    def branch(label, args, cwd):
        barrier.wait()
        return run([f"--at-operation={base_op}", "--no-integrate-operation", *args], cwd=cwd, check=False)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        rebase = pool.submit(branch, "rebase", ["rebase", "-s", "@", "-o", "root()"], repo)
        creation = pool.submit(branch, "new", ["new", "-m", "parallel op"], ext)
        left, right = rebase.result(), creation.result()
    print("rebase branch exit", left.returncode, (left.stdout + left.stderr).strip())
    print("new branch exit", right.returncode, (right.stdout + right.stderr).strip())
    # Integrate each emitted op id. This deliberately exercises jj's recovery path
    # for work created concurrently from the same operation.
    for result in (left, right):
        match = re.search(r"Operation left uncommitted.*?: ([0-9a-f]{12,})", result.stdout + result.stderr)
        if match:
            candidate = match.group(1)
            p = run(["op", "integrate", candidate], cwd=repo, check=False)
            print("integrate", candidate, "exit", p.returncode, (p.stdout + p.stderr).strip())
    p = run(["op", "log", "--limit", "12"], cwd=repo, check=False)
    print("BRANCHED OPS", (p.stdout + p.stderr).strip())
    p = run(["workspace", "list"], cwd=repo, check=False)
    print("BRANCHED WORKSPACES", (p.stdout + p.stderr).strip())
    p = run(["workspace", "update-stale"], cwd=repo, check=False)
    print("UPDATE STALE", p.returncode, (p.stdout + p.stderr).strip())
    p = run(["op", "log", "--limit", "12"], cwd=repo, check=False)
    print("OPS AFTER RECOVERY", (p.stdout + p.stderr).strip())
    p = run(["workspace", "list"], cwd=repo, check=False)
    print("WORKSPACES AFTER RECOVERY", (p.stdout + p.stderr).strip())
    print(
        "\nRECOVERY CHECK: ordinary command races stayed usable; the deliberately "
        "unintegrated branch case required update-stale and recovered successfully"
    )


if __name__ == "__main__":
    main()
