#!/usr/bin/env python3
"""Move one template-py repo from Copier to CopyRoom 0.8.5 or newer.

Usage:
    migrate.py [options] REPO TEMPLATE_REPO REF WORKDIR

    REPO           path of the fleet repo (a jj workspace with .copier-answers.yml)
    TEMPLATE_REPO  path of a local clone of template-py (tags must exist locally)
    REF            tag of template-py to move to, for example v0.8.0
    WORKDIR        scratch directory for sources, answers, preview, and the log

Run the script in the CopyRoom devenv shell. It needs copyroom, jj, git, and uv.

The steps run in this order. Each step checks the repo first, so a second run
skips the steps that are done:

    1. preflight      clean jj tree, template-py marker, record the symlinks
    2. baseline       build the Templateer source of the version that made the repo
    3. answers        convert .copier-answers.yml to JSON for both versions
    4. adopt          `copyroom adopt --write` against the baseline source
    5. drop marker    delete .copier-answers.yml, commit it with jj
    6. preview        `copyroom update --source --ref`; STOP with a conflict list
    7. apply          only with --apply: publish the reviewed preview, then verify

The script never pushes. It never moves a bookmark. It never creates a tag.
Landing the result on main is a separate step for the person or agent.

Exit codes (an API):
    0  done, or nothing left to do
    1  a finding or a decision: conflicts to resolve, a dirty tree, a failed check
    2  infrastructure or configuration: no jj workspace, missing tool, command error
    3  usage error
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

OK, FINDING, INFRA, USAGE = 0, 1, 2, 3
MIN_COPYROOM = (0, 8, 5)
MARKER = ".copyroom-local.json"
LEGACY = ".copier-answers.yml"
# devman links these paths into a repo. The script records them and checks them at the end.
DEVMAN_LINKS = [".agents", ".claude/skills", ".envrc", ".loci", "devenv.local.nix"]
# The baseline schema that matches each template-py minor version.
SCHEMA_BY_MINOR = {"v0.5": "schemas/v0_5.py", "v0.7": "schemas/v0_7.py"}
# Answers that never go into JSON. Copier-only keys start with an underscore.
ALWAYS_DROP = {"repoman_dev_root"}


def is_devman_view_path(path: str) -> bool:
    """Return whether a tracked path belongs to a machine-local devman view."""
    return (
        path == ".agents"
        or path.startswith(".agents/")
        or path == ".claude/skills"
        or path.startswith(".claude/skills/")
    )


class Stop(Exception):
    """End the run with an exit code and a message."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Parser(argparse.ArgumentParser):
    def error(self, message: str):  # usage errors exit 3, not 2
        self.print_usage(sys.stderr)
        print(f"migrate: {message}", file=sys.stderr)
        sys.exit(USAGE)


class Ctx:
    """Paths and options that every step shares."""

    def __init__(self, args: argparse.Namespace):
        self.repo = Path(args.repo).resolve()
        self.template = Path(args.template_repo).resolve()
        self.ref = args.ref
        self.work = Path(args.workdir).resolve()
        self.args = args
        self.log_path = self.work / "migrate.log"
        self.preview = self.work / "preview"
        self.links_path = self.work / "links.json"


def say(text: str) -> None:
    print(f"migrate: {text}")


def run(ctx: Ctx, cmd: list[str], cwd: Path | None = None, env: dict | None = None):
    """Run a command, append it and its exit code to the log, return the result."""
    full_env = {**os.environ, **(env or {})}
    done = subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=True, text=True)
    with ctx.log_path.open("a") as log:
        log.write(f"$ (cd {cwd or '.'} && {' '.join(cmd)})\n")
        log.write(f"exit {done.returncode}\n")
        for stream in (done.stdout, done.stderr):
            if stream.strip():
                log.write(stream[:4000] + ("\n" if not stream.endswith("\n") else ""))
    return done


def need(ctx: Ctx, cmd: list[str], cwd: Path | None = None, ok=(0,), env=None):
    """Run a command. Stop with exit code 2 when its exit code is not in `ok`."""
    done = run(ctx, cmd, cwd, env)
    if done.returncode not in ok:
        tail = (done.stderr or done.stdout).strip()[-600:]
        raise Stop(INFRA, f"`{' '.join(cmd[:3])}` exited {done.returncode}: {tail}")
    return done


def jj_clean(ctx: Ctx, where: Path) -> list[str]:
    """Return the changed paths of the working copy (jj snapshots it first)."""
    done = need(ctx, ["jj", "diff", "--summary"], where)
    return [line for line in done.stdout.splitlines() if line.strip()]


def copyroom_version(ctx: Ctx) -> tuple[int, ...]:
    done = need(ctx, ["copyroom", "--version"])
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", done.stdout)
    if not match:
        raise Stop(INFRA, f"cannot read the copyroom version: {done.stdout!r}")
    return tuple(int(part) for part in match.groups())


def load_yaml(path: Path) -> dict:
    import yaml  # the copyroom interpreter has PyYAML

    return yaml.safe_load(path.read_text()) or {}


# --- step 1: preflight -------------------------------------------------------


def preflight(ctx: Ctx) -> dict:
    for tool in ("copyroom", "jj", "git"):
        if not shutil.which(tool):
            raise Stop(INFRA, f"{tool} is not on PATH; run inside the CopyRoom devenv shell")
    if copyroom_version(ctx) < MIN_COPYROOM:
        raise Stop(INFRA, "copyroom is older than 0.8.5 (earlier versions do not normalize project file modes)")
    if not ctx.repo.is_dir():
        raise Stop(INFRA, f"{ctx.repo} is not a directory")
    if not (ctx.repo / ".jj").is_dir() or run(ctx, ["jj", "root"], ctx.repo).returncode != 0:
        raise Stop(INFRA, f"{ctx.repo} is not a jj workspace; refusing to run")
    changed = jj_clean(ctx, ctx.repo)
    if changed:
        raise Stop(FINDING, "the jj working copy is not clean: " + ", ".join(changed[:5]))
    if not (ctx.template / ".git").exists():
        raise Stop(INFRA, f"{ctx.template} is not a git clone of template-py")
    ref_ok = run(ctx, ["git", "rev-parse", "--verify", f"{ctx.ref}^{{commit}}"], ctx.template)
    if ref_ok.returncode != 0:
        raise Stop(INFRA, f"ref {ctx.ref} not found in {ctx.template}; fetch or tag it first")
    manifest = run(ctx, ["git", "cat-file", "-e", f"{ctx.ref}:source/manifest.json"], ctx.template)
    if manifest.returncode != 0:
        raise Stop(INFRA, f"{ctx.ref} has no source/manifest.json: not a Templateer source")

    ctx.work.mkdir(parents=True, exist_ok=True)
    info: dict = {"adopted": (ctx.repo / MARKER).exists(), "answers": {}}
    legacy = ctx.repo / LEGACY
    if legacy.exists():
        answers = load_yaml(legacy)
        if "template-py" not in str(answers.get("_src_path", "")):
            raise Stop(FINDING, f"{LEGACY} is not from template-py: {answers.get('_src_path')!r}")
        if not answers.get("_commit"):
            raise Stop(FINDING, f"{LEGACY} has no _commit")
        info["answers"] = answers
    elif not info["adopted"]:
        raise Stop(FINDING, f"neither {LEGACY} nor {MARKER} exists: nothing to migrate")

    # Record the devman links once. Later runs compare against this first record.
    if not ctx.links_path.exists():
        links = {n: os.readlink(ctx.repo / n) for n in DEVMAN_LINKS if (ctx.repo / n).is_symlink()}
        ctx.links_path.write_text(json.dumps(links, indent=2) + "\n")
    say(f"preflight ok; links recorded: {ctx.links_path.read_text().strip() or '{}'}")
    return info


# --- step 2 and 3: baseline source and answers --------------------------------


def schema_fields(text: str) -> set[str]:
    """Return the field names of the ProjectModel class in a schema.py text."""
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ProjectModel":
            return {
                item.target.id
                for item in node.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            }
    raise Stop(INFRA, "schema.py has no ProjectModel class")


def repo_pins(repo: Path) -> dict[str, str]:
    """Read the RepoMan and Testee tags that devenv.yaml pins today."""
    path = repo / "devenv.yaml"
    pins: dict[str, str] = {}
    if path.exists():
        text = path.read_text()
        for key, pattern in (
            ("repoman_ref", r"repoman\?dir=modules&ref=refs/tags/(\S+?)\""),
            ("testee_ref", r"testee\?ref=refs/tags/(\S+?)\""),
        ):
            found = re.search(pattern, text)
            if found:
                pins[key] = found.group(1)
    return pins


def write_answers(
    ctx: Ctx, answers: dict, fields: set[str], out: Path, use_pins: bool, quiet: bool = False
) -> None:
    kept = {k: v for k, v in answers.items() if not k.startswith("_") and k not in ALWAYS_DROP}
    dropped = sorted(set(kept) - fields)
    kept = {k: v for k, v in kept.items() if k in fields}
    if dropped and not quiet:
        say(f"{out.name}: dropped answers the schema does not know: {dropped}")
    if use_pins:
        for key, tag in repo_pins(ctx.repo).items():
            if key in kept and kept[key] != tag:
                say(f"{out.name}: {key} {kept[key]} -> {tag} (devenv.yaml is newer than the answers)")
                kept[key] = tag
    out.write_text(json.dumps(kept, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def copyroom_python() -> str:
    """Return the interpreter of the installed copyroom (it has templateer and PyYAML)."""
    exe = shutil.which("copyroom")
    first = Path(exe).read_text().splitlines()[0] if exe else ""
    return first[2:].strip() if first.startswith("#!") else sys.executable


def build_baseline(ctx: Ctx, conv: Path, tag: str, schema: Path, source: Path) -> None:
    """Convert one template-py tag to a Templateer source with the INSTALLED copyroom.

    build-source.sh runs `uv run --project <copyroom checkout>`, so it uses whatever
    version that checkout has. This function does the same steps with the interpreter of
    the copyroom on PATH, so the version that the script checked is the version that runs.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        archive = subprocess.run(["git", "archive", tag], cwd=ctx.template, capture_output=True)
        if archive.returncode != 0:
            raise Stop(INFRA, f"git archive {tag} failed: {archive.stderr.decode()[-300:]}")
        untar = subprocess.run(["tar", "-x", "-C", tmp], input=archive.stdout, capture_output=True)
        if untar.returncode != 0:
            raise Stop(INFRA, f"tar failed: {untar.stderr.decode()[-300:]}")
        need(ctx, [copyroom_python(), str(conv / "convert.py"), tmp, str(source), "--schema", str(schema.resolve())])


def baseline_and_answers(ctx: Ctx, info: dict) -> tuple[Path | None, Path]:
    """Build the baseline source and write both answers files. Return their paths."""
    new_answers = ctx.work / "answers-target.json"
    target_schema = need(ctx, ["git", "show", f"{ctx.ref}:source/schema.py"], ctx.template).stdout
    if info["adopted"]:
        # The repo is adopted already. The marker holds the answers; read them from it.
        marker = json.loads((ctx.repo / MARKER).read_text())
        layer = marker.get("layers", {}).get("base", {})
        current = layer.get("answers") or marker.get("answers") or {}
        write_answers(ctx, current, schema_fields(target_schema), new_answers, use_pins=False, quiet=True)
        return None, new_answers

    answers = info["answers"]
    base_tag = str(answers["_commit"])
    resolved = run(ctx, ["git", "rev-parse", "--verify", f"{base_tag}^{{commit}}"], ctx.template)
    if resolved.returncode != 0:
        raise Stop(FINDING, f"_commit {base_tag} is not a tag in {ctx.template}")
    minor = ".".join(base_tag.split(".")[:2])
    schema_arg = ctx.args.baseline_schema or SCHEMA_BY_MINOR.get(minor)
    if not schema_arg:
        raise Stop(FINDING, f"no baseline schema for {base_tag}; pass --baseline-schema FILE")
    conv = Path(ctx.args.converter_dir or ctx.template / ".scratch/projects/01-templateer-conversion")
    schema = Path(schema_arg) if Path(schema_arg).is_absolute() else conv / schema_arg
    if not schema.is_file():
        raise Stop(INFRA, f"baseline schema {schema} not found")

    source = ctx.work / f"src-{base_tag}"
    if not (source / "manifest.json").exists():
        if source.exists():
            shutil.rmtree(source)  # a partial build inside our own work directory
        build_baseline(ctx, conv, base_tag, schema, source)
    say(f"baseline source: {source}")

    write_answers(ctx, answers, schema_fields(schema.read_text()), ctx.work / "answers-baseline.json", False)
    write_answers(ctx, answers, schema_fields(target_schema), new_answers, not ctx.args.keep_answer_refs)
    return source, new_answers


# --- step 4 and 5: adopt and drop the marker ---------------------------------


def adopt(ctx: Ctx, info: dict, source: Path | None) -> None:
    if info["adopted"]:
        say("already adopted; skip adopt")
        return
    assert source is not None
    base = ["copyroom", "adopt", str(source), "--answers", str(ctx.work / "answers-baseline.json"),
            "--project", str(ctx.repo)]
    if ctx.args.template_only:
        base += ["--template-only", ctx.args.template_only]
    dry = need(ctx, base + ["--json"], ok=(0, 1))
    report = json.loads(dry.stdout)
    say(f"adopt dry run exit {dry.returncode}: {len(report.get('changed', []))} paths differ from the "
        f"baseline render (expected; they become merge input)")
    if report.get("template_only") and not ctx.args.template_only:
        raise Stop(FINDING, "paths exist only in the template: " + ", ".join(report["template_only"][:8])
                   + "; decide, then pass --template-only keep")
    need(ctx, base + ["--write", "--json"])
    if jj_clean(ctx, ctx.repo):
        raise Stop(FINDING, "adopt left changes in the working copy")
    say("adopt --write ok")


def drop_marker(ctx: Ctx) -> None:
    legacy = ctx.repo / LEGACY
    if not legacy.exists():
        say("no Copier marker; skip drop")
        return
    legacy.unlink()
    changed = jj_clean(ctx, ctx.repo)
    if changed != [f"D {LEGACY}"]:
        raise Stop(FINDING, f"expected only the marker to change, got: {changed}")
    need(ctx, ["jj", "commit", "-m", "copyroom: drop the Copier marker"], ctx.repo)
    say("Copier marker dropped and committed")


# --- step 6: preview ----------------------------------------------------------


def status(ctx: Ctx) -> tuple[int, dict]:
    done = run(ctx, ["copyroom", "status", "--json"], ctx.repo)
    try:
        return done.returncode, json.loads(done.stdout)
    except json.JSONDecodeError:
        return done.returncode, {}


def target_commit(ctx: Ctx) -> str:
    return need(ctx, ["git", "rev-parse", f"{ctx.ref}^{{commit}}"], ctx.template).stdout.strip()


def already_pinned(ctx: Ctx) -> bool:
    code, data = status(ctx)
    layer = data.get("layers", {}).get("base", {})
    return code == 0 and layer.get("ref") == ctx.ref and layer.get("commit") == target_commit(ctx)


def conflicted(ctx: Ctx) -> list[str]:
    """List the conflicted paths of the preview, and the earliest conflicted change."""
    listing = run(ctx, ["jj", "resolve", "--list"], ctx.preview)
    paths = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
    return paths


def describe_conflicts(ctx: Ctx, paths: list[str]) -> None:
    roots = run(ctx, ["jj", "log", "-r", "roots(conflicts() & ::@)", "--no-graph",
                      "-T", "change_id.short() ++ \"\\n\""], ctx.preview).stdout.split()
    (ctx.work / "CONFLICTS.txt").write_text("\n".join(paths) + "\n")
    say("conflicts to resolve (also in CONFLICTS.txt):")
    for line in paths:
        print(f"  {line}")
    print(f"""
migrate: next steps, in the preview workspace {ctx.preview}
  1. Edit each conflicted file. A helper picks sides: pick_sides.py FILE P|T|B ...
     (P = project side, T = template side). Delete a file that the template dropped.
  2. Move the resolution into the first conflicted change:
       jj squash --from @ --into {roots[0] if roots else 'FIRST_CONFLICTED_CHANGE'}
  3. Check: jj resolve --list   (must be empty), and run the project checks.
  4. Apply: migrate.py --apply {ctx.repo} {ctx.template} {ctx.ref} {ctx.work}""")


def make_preview(ctx: Ctx) -> int:
    """Create or reuse the preview. Return 0 when it is clean, 1 when it has conflicts."""
    if already_pinned(ctx):
        say(f"already pinned at {ctx.ref}; nothing to preview")
        return OK
    if ctx.preview.exists():
        say(f"reusing the existing preview {ctx.preview}")
        paths = conflicted(ctx)
        if paths:
            describe_conflicts(ctx, paths)
            return FINDING
        return OK
    cmd = ["copyroom", "update", "--source", str(ctx.template / "source"), "--ref", ctx.ref,
           "--answers", str(ctx.work / "answers-target.json"), "--out", str(ctx.preview), "--json"]
    done = run(ctx, cmd, ctx.repo)
    if done.returncode not in (0, 1):
        raise Stop(INFRA, f"copyroom update exited {done.returncode}: {done.stderr.strip()[-600:]}")
    data = json.loads(done.stdout)
    if data.get("result") == "no-change":
        say("the update has no change")
        return OK
    (ctx.work / "preview.json").write_text(json.dumps(data, indent=2) + "\n")
    paths = conflicted(ctx)
    if done.returncode == 1 or paths:
        describe_conflicts(ctx, paths or data.get("conflicts", []))
        return FINDING
    say(f"clean preview at {ctx.preview}; review it, then rerun with --apply")
    return OK


# --- step 7: apply and verify -------------------------------------------------


def apply_preview(ctx: Ctx) -> None:
    if not ctx.preview.exists():
        raise Stop(FINDING, f"no preview at {ctx.preview}; run without --apply first")
    paths = conflicted(ctx)
    if paths:
        raise Stop(FINDING, "the preview still has conflicts: " + ", ".join(paths))
    cmd = ["copyroom", "update", "--apply", str(ctx.preview)]
    if ctx.args.unguarded:
        cmd.append("--publish-unguarded")  # only for the child-workspace guard; see the log
    done = run(ctx, cmd, ctx.repo)
    if done.returncode != 0:
        raise Stop(FINDING if done.returncode == 1 else INFRA,
                   f"apply exited {done.returncode}: {(done.stderr or done.stdout).strip()[-600:]}")
    say("apply ok")


def verify(ctx: Ctx) -> None:
    problems: list[str] = []
    code, data = status(ctx)
    layer = data.get("layers", {}).get("base", {})
    if code != 0:
        problems.append(f"copyroom status exited {code}")
    if layer.get("ref") != ctx.ref or layer.get("commit") != target_commit(ctx):
        problems.append(f"pin is {layer.get('ref')}@{layer.get('commit')}, not {ctx.ref}")
    if jj_clean(ctx, ctx.repo):
        problems.append("jj working copy is not clean")
    if (ctx.repo / LEGACY).exists():
        problems.append(f"{LEGACY} still exists")
    recorded = json.loads(ctx.links_path.read_text()) if ctx.links_path.exists() else {}
    for name, target in recorded.items():
        path = ctx.repo / name
        if not path.is_symlink() or os.readlink(path) != target:
            problems.append(f"link {name} changed or vanished")
    tracked = run(ctx, ["jj", "file", "list", "-r", "@"], ctx.repo).stdout.splitlines()
    # CopyRoom 0.8.5 tracks no source copy: .copyroom-local/ holds only untracked state.
    bad = [t for t in tracked if t.startswith(".copyroom-local/")]
    bad += [t for t in tracked if is_devman_view_path(t)]
    if bad:
        problems.append(f"state tracked wrongly: {bad[:5]}")
    # CopyRoom 0.8.5 keeps sources in private Git refs. They must exist, and no jj bookmark may name them.
    refs = run(ctx, ["git", "for-each-ref", "refs/copyroom/sources/"], ctx.repo).stdout.strip()
    digest = str(layer.get("source_digest") or "")
    if not digest or f"refs/copyroom/sources/{digest}" not in refs:
        problems.append("the private source ref of the pinned source is missing")
    marks = run(ctx, ["jj", "bookmark", "list", "--all", "-T", 'name ++ "\\n"'], ctx.repo).stdout
    if "copyroom" in marks.lower():
        problems.append("a jj bookmark names a copyroom ref")
    if problems:
        raise Stop(FINDING, "verify failed: " + "; ".join(problems))
    say(f"verify ok: pinned {ctx.ref}, tree clean, links unchanged. Land the work; the script never pushes.")


# --- main ---------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = Parser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("repo")
    parser.add_argument("template_repo")
    parser.add_argument("ref")
    parser.add_argument("workdir")
    parser.add_argument("--apply", action="store_true", help="publish the reviewed preview")
    parser.add_argument("--check", action="store_true", help="run the preflight only")
    parser.add_argument("--unguarded", action="store_true",
                        help="pass --publish-unguarded to apply (child-workspace guard only)")
    parser.add_argument("--template-only", help="pass --template-only VALUE to adopt")
    parser.add_argument("--baseline-schema", help="schema file for the baseline source")
    parser.add_argument("--converter-dir", help="directory of convert.py and schemas/")
    parser.add_argument("--keep-answer-refs", action="store_true",
                        help="keep repoman_ref/testee_ref from the answers (default: use devenv.yaml pins)")
    args = parser.parse_args(argv)

    ctx = Ctx(args)
    try:
        try:
            ctx.work.mkdir(parents=True, exist_ok=True)
            import yaml  # noqa: F401
        except ImportError:  # run again with the interpreter of the copyroom install
            exe = shutil.which("copyroom")
            first = Path(exe).read_text().splitlines()[0] if exe else ""
            if first.startswith("#!") and not os.environ.get("MIGRATE_REEXEC"):
                os.environ["MIGRATE_REEXEC"] = "1"
                interpreter = first[2:].strip()
                os.execv(interpreter, [interpreter, __file__, *argv])
            raise Stop(INFRA, "PyYAML is missing; run with the Python of the copyroom install")
        info = preflight(ctx)
        if args.check:
            say("check only: preflight ok")
            return OK
        if args.apply:
            apply_preview(ctx)
            verify(ctx)
            return OK
        source, _ = baseline_and_answers(ctx, info)
        adopt(ctx, info, source)
        drop_marker(ctx)
        code = make_preview(ctx)
        if code == OK and already_pinned(ctx):
            verify(ctx)
        return code
    except Stop as stop:
        print(f"migrate: {stop.message}", file=sys.stderr)
        return stop.code
    except Exception as exc:  # any other failure is an infrastructure error
        print(f"migrate: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return INFRA


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
