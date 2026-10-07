#!/usr/bin/env python3
"""Test path ownership preflight before disposable jj project changes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence.json"
CHECKS: list[str] = []
REJECTIONS: list[dict[str, str]] = []


class Collision(Exception):
    """Two owners would claim one file or a file and its child."""


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    CHECKS.append(label)
    print(f"PASS {label}")


def jj(project: Path, *args: str) -> str:
    result = subprocess.run(["jj", *args], cwd=project, capture_output=True, text=True, check=False)
    if result.returncode:
        raise AssertionError(f"jj {' '.join(args)}: {result.stderr}")
    return result.stdout.strip()


def head(project: Path) -> str:
    return jj(project, "log", "--no-graph", "--ignore-working-copy", "-r", "@", "-T", "commit_id")


def tree(project: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(project.rglob("*")):
        if not path.is_file() or any(part in {".jj", ".git"} for part in path.relative_to(project).parts):
            continue
        name = path.relative_to(project).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(name).to_bytes(4, "big") + name)
        digest.update(len(content).to_bytes(8, "big") + content)
        digest.update(b"x" if path.stat().st_mode & 0o111 else b"f")
    return digest.hexdigest()


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or "\\" in value
        or "\x00" in value
        or any(part in {"", ".", "..", ".jj", ".git"} for part in value.split("/"))
        or path.as_posix() != value
    ):
        raise ValueError(f"unsafe path {value!r}")
    return value


def conflict(left: str, right: str) -> str | None:
    if left == right:
        return "exact"
    if left.startswith(right + "/") or right.startswith(left + "/"):
        return "file-directory"
    return None


def preflight(owners: dict[str, set[str]]) -> None:
    claims = [(owner, safe_path(path)) for owner, paths in owners.items() for path in paths]
    for index, (owner, path) in enumerate(claims):
        for other_owner, other_path in claims[index + 1 :]:
            reason = conflict(path, other_path)
            if reason:
                raise Collision(f"{reason}: {owner}:{path} vs {other_owner}:{other_path}")


def staged(root: Path, label: str, contents: dict[str, str]) -> tuple[Path, set[str]]:
    source = root / "stages" / label
    source.mkdir(parents=True)
    for name, content in contents.items():
        target = source / safe_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    paths = {path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()}
    return source, paths


def apply(
    project: Path,
    owner: str,
    candidate: Path,
    paths: set[str],
    owners: dict[str, set[str]],
    omitted: set[str] | None = None,
) -> None:
    proposed = {key: set(value) for key, value in owners.items()}
    proposed[owner] = paths
    preflight(proposed)
    for path in owners.get(owner, set()):
        old = project / path
        if old.is_file():
            old.unlink()
    for path in paths:
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((candidate / path).read_bytes())
    owners[owner] = paths
    marker = {
        "owners": {key: sorted(value) for key, value in sorted(owners.items())},
        "overlay_omitted": sorted(omitted or set()),
    }
    (project / ".ownership.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    jj(project, "commit", "-m", f"apply {owner}")


def rejected(
    project: Path, owner: str, candidate: Path, paths: set[str], owners: dict[str, set[str]], label: str, reason: str
) -> None:
    before = head(project), tree(project)
    proposed = {key: set(value) for key, value in owners.items()}
    proposed[owner] = paths
    try:
        preflight(proposed)
    except Collision as error:
        check(label + " classified", reason in str(error))
        REJECTIONS.append({"case": label, "reason": str(error)})
    else:
        raise AssertionError(f"{label} passed preflight unexpectedly")
    check(label + " keeps @", head(project) == before[0])
    check(label + " keeps files", tree(project) == before[1])
    check(label + " candidate stayed outside project", candidate != project)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="copyroom-ownership-") as temporary:
        root = Path(temporary)
        project = root / "project"
        owners: dict[str, set[str]] = {}

        base_v1, base_paths = staged(
            root,
            "base-v1",
            {
                "README.md": "base readme\n",
                "config.toml": "owner='base'\n",
            },
        )
        generated_bad, generated_bad_paths = staged(root, "generated-new-bad", {"README.md": "generated\n"})
        try:
            preflight({"base": base_paths, "generated": generated_bad_paths})
        except Collision as error:
            check("initial new rejects exact collision", "exact" in str(error))
            REJECTIONS.append({"case": "initial new", "reason": str(error)})
        else:
            raise AssertionError("initial new collision passed")
        check("rejected new creates no repository", not project.exists())
        check("new candidate sources stay outside target", base_v1 != project and generated_bad != project)
        generated_new_prefix, generated_new_prefix_paths = staged(
            root,
            "generated-new-prefix",
            {
                "README.md/child": "generated\n",
            },
        )
        try:
            preflight({"base": base_paths, "generated": generated_new_prefix_paths})
        except Collision as error:
            check("initial new rejects prefix collision", "file-directory" in str(error))
            REJECTIONS.append({"case": "initial new prefix", "reason": str(error)})
        else:
            raise AssertionError("initial new prefix collision passed")
        check("prefix rejection creates no repository", not project.exists())

        project.mkdir()
        jj(project, "git", "init", "--colocate")
        apply(project, "base", base_v1, base_paths, owners)
        check("accepted new records base paths", owners["base"] == {"README.md", "config.toml"})
        generated_v1, generated_v1_paths = staged(root, "generated-v1", {"generated.txt": "frozen artifact 1\n"})
        apply(project, "generated", generated_v1, generated_v1_paths, owners)
        check("accepted new records generated paths", owners["generated"] == {"generated.txt"})

        overlay_exact, overlay_exact_paths = staged(root, "overlay-add-exact", {"README.md": "overlay\n"})
        rejected(project, "overlay", overlay_exact, overlay_exact_paths, owners, "layer add exact", "exact")
        overlay_prefix, overlay_prefix_paths = staged(root, "overlay-add-prefix", {"README.md/child": "overlay\n"})
        rejected(project, "overlay", overlay_prefix, overlay_prefix_paths, owners, "layer add prefix", "file-directory")

        # The overlay source contains a conditional seed for config.toml.
        # The recorded omission keeps the base layer as the sole owner.
        overlay_raw, overlay_raw_paths = staged(
            root,
            "overlay-v1-raw",
            {
                "config.toml": "seed='overlay'\n",
                "docs/guide.md": "guide 1\n",
            },
        )
        omission = {"config.toml"}
        effective_overlay = overlay_raw_paths - omission
        apply(project, "overlay", overlay_raw, effective_overlay, owners, omission)
        check("conditional seed is absent from overlay ownership", "config.toml" not in owners["overlay"])
        check("base config bytes remain", (project / "config.toml").read_text() == "owner='base'\n")

        base_update, base_update_paths = staged(
            root,
            "base-update-bad",
            {
                "README.md": "readme 2\n",
                "config.toml": "owner='base'\n",
                "docs/guide.md": "stolen\n",
            },
        )
        rejected(project, "base", base_update, base_update_paths, owners, "base update exact", "exact")
        base_prefix, base_prefix_paths = staged(
            root,
            "base-update-prefix",
            {
                "README.md": "readme 2\n",
                "config.toml": "owner='base'\n",
                "docs": "file\n",
            },
        )
        rejected(project, "base", base_prefix, base_prefix_paths, owners, "base update prefix", "file-directory")
        base_good, base_good_paths = staged(
            root,
            "base-update-good",
            {
                "README.md": "base readme 2\n",
                "config.toml": "owner='base'\n",
                "src/main.py": "pass\n",
            },
        )
        apply(project, "base", base_good, base_good_paths, owners, omission)
        check("accepted base update changes base content", (project / "README.md").read_text() == "base readme 2\n")
        check("accepted base update adds its own path", owners["base"] == set(base_good_paths))

        generated_refresh, refresh_paths = staged(root, "generated-refresh-bad", {"docs": "file\n"})
        rejected(
            project, "generated", generated_refresh, refresh_paths, owners, "generated refresh prefix", "file-directory"
        )
        generated_exact, generated_exact_paths = staged(root, "generated-refresh-exact", {"config.toml": "bad\n"})
        rejected(
            project, "generated", generated_exact, generated_exact_paths, owners, "generated refresh exact", "exact"
        )

        good_generated, good_generated_paths = staged(root, "generated-good", {"generated.txt": "frozen artifact 2\n"})
        apply(project, "generated", good_generated, good_generated_paths, owners, omission)
        check("accepted generated refresh records owner", owners["generated"] == {"generated.txt"})
        check(
            "accepted generated refresh changes bytes", (project / "generated.txt").read_text() == "frozen artifact 2\n"
        )

        overlay_update_raw, overlay_update_raw_paths = staged(
            root,
            "overlay-v2-raw",
            {
                "config.toml": "seed='overlay v2'\n",
                "docs/guide.md": "guide 2\n",
                "docs/faq.md": "faq\n",
            },
        )
        rejected(
            project, "overlay", overlay_update_raw, overlay_update_raw_paths, owners, "unfrozen seed update", "exact"
        )
        apply(project, "overlay", overlay_update_raw, overlay_update_raw_paths - omission, owners, omission)
        check("frozen omission survives overlay update", "config.toml" not in owners["overlay"])
        check("base still owns omitted path", (project / "config.toml").read_text() == "owner='base'\n")
        check("overlay update applies other files", (project / "docs/faq.md").read_text() == "faq\n")
        saved = json.loads((project / ".ownership.json").read_text())
        check("project marker records omitted path", saved["overlay_omitted"] == ["config.toml"])

    EVIDENCE.write_text(
        json.dumps({"checks": CHECKS, "rejections": REJECTIONS}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"RESULT {len(CHECKS)} checks passed, {len(REJECTIONS)} collisions rejected")


if __name__ == "__main__":
    main()
