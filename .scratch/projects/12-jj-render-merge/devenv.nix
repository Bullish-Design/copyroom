# Spike 12 — can jj (jujutsu) replace Copier's three-way merge?
#
# The design under evaluation models a template render as a commit:
#
#   T0 = render(template@v1, answers)      a commit holding ONLY generated files
#   trunk                                  merged T0 at scaffold time
#   T1 = render(template@v2, answers)      a child of T0
#   update = `jj new trunk T1`             jj computes merge-base(trunk, T1) = T0
#
# If that holds, `_commit` bookkeeping, the clean-worktree guard, the `.rej`
# scanner, the preview sandbox and the layer-ordering hack all become dead code.
#
# The spike must answer, in order:
#   Q1  Does jj merge a commit that holds only a SUBTREE of the project cleanly?
#   Q2  Does merge-base hold across two successive renders (T0 -> T1)?
#   Q3  Does a local edit to a template-owned file survive the merge?
#   Q4  Does a file DELETED between v1 and v2 get removed from trunk?
#   Q5  Is a conflict recorded in the commit, leaving other jj ops usable?
#   Q6  Does `jj undo` fully reverse the merge? (preview-only, no sandbox)
#   Q7  Does an n-parent merge converge two layers at once, order-free?
#   Q8  Is render(template, answers) byte-identical across runs? (load-bearing)
{
  pkgs,
  config,
  lib,
  ...
}:

{
  # https://devenv.sh/packages/
  packages = [
    pkgs.jujutsu # the tool under test; `jj`
    pkgs.git # jj runs colocated, as the family's repos do
    pkgs.diffutils # byte comparison in the spike scripts
    pkgs.jq # parsing `jj log -T json` style output

    # The scripts' whole toolbox must be IN the profile, because enterTest
    # scrubs PATH to $DEVENV_PROFILE/bin (see below). Finding, spike 12: these
    # were silently inherited from the host until the scrub exposed it, and the
    # resulting `command not found` cascade read as seven failed jj experiments.
    pkgs.coreutils # sha256sum, sort, cut, tee
    pkgs.findutils # find, xargs
    pkgs.gnugrep
    pkgs.gnused
    pkgs.gawk
  ];

  # Pinned, as the design premise requires. A spurious merge conflict caused by
  # a renderer version drifting under us would invalidate every finding.
  languages.python = {
    enable = true;
    version = "3.13";
    # The spike renderer is deliberately dependency-free: the thing under test
    # is jj's merge, not Jinja. No venv, no uv, no lockfile.
    venv.enable = false;
  };

  env = {
    # --- Determinism ------------------------------------------------------
    # Q8 is load-bearing for the whole design: if render() is not byte-stable,
    # the merge base is garbage and every update conflicts spuriously. Remove
    # the ambient causes of drift so the spike measures the renderer, not the
    # machine.
    TZ = "UTC";
    LC_ALL = "C";
    LANG = "C";
    PYTHONHASHSEED = "0";
    PYTHONDONTWRITEBYTECODE = "1";
    SOURCE_DATE_EPOCH = "1735689600"; # 2025-01-01T00:00:00Z

    # --- jj isolation -----------------------------------------------------
    # Point jj at an immutable store-path config so a finding is a property of
    # jj and not of the contributor's ~/.config/jj.
    JJ_CONFIG = toString (
      pkgs.writeText "jj-spike.toml" ''
        [user]
        name = "CopyRoom Spike"
        email = "spike@example.invalid"

        [ui]
        paginate = "never"
        color = "never"
        default-command = "status"
      ''
    );

    # DO NOT pin JJ_RANDOMNESS_SEED or JJ_TIMESTAMP here.
    #
    # Finding, spike 12, jj 0.45.1: jj HONOURS both. With the seed fixed, every
    # jj process generates the same change-id sequence, so every commit shares
    # one change id and shows as `(divergent)`. `jj new <T0>` then dies with
    # "Newly-created commit <id> already exists", because the new empty commit
    # matches an existing one in change id, parent, tree, author AND timestamp.
    # The spike silently built the wrong DAG and reported a false Q2 failure.
    #
    # The determinism this design needs is of the RENDERER (Q8), not of jj's
    # ids. These two buy nothing here and actively corrupt the experiment.

    # Scratch root. Under .devenv/state, which devenv already ignores, so the
    # spike never dirties the CopyRoom worktree it lives in.
    SPIKE_WORK = "${config.env.DEVENV_STATE}/spike";
  };

  # https://devenv.sh/scripts/
  # Record the toolchain into the findings. SPIKE.md in this repo states its
  # environment ("Copier 9.17.1, Git 2.55.0, Python 3.13"); keep that habit, and
  # prove `copier` is absent so a pass cannot be Copier's doing.
  scripts.spike-versions.exec = ''
    set -eu
    # devenv LAYERS its profile onto the host PATH, it does not replace it, so a
    # parent environment leaks in: CopyRoom's own .devenv venv ships `copier`.
    # Scrub to the profile, which carries every tool this spike needs (jj, git,
    # python3, diff, jq, and the spike scripts themselves). This makes the
    # isolation claim enforced rather than merely stated.
    export PATH="$DEVENV_PROFILE/bin"
    # `devenv test` hides stdout on success, so write the record to a file as
    # well. SPIKE.md must state its environment the way spike 11 does; cite
    # $SPIKE_WORK/toolchain.txt rather than retyping versions by hand.
    mkdir -p "$SPIKE_WORK"

    # Every tool the scripts use must resolve INSIDE the scrubbed PATH. Without
    # this check, a missing coreutil reads as a failed experiment rather than a
    # broken environment.
    missing=""
    for t in jj git python3 find grep sed awk xargs diff sort cut tee sha256sum; do
      command -v "$t" >/dev/null 2>&1 || missing="$missing $t"
    done
    if [ -n "$missing" ]; then
      echo "FATAL  not in \$DEVENV_PROFILE/bin:$missing" >&2
      echo "       add the providing package to devenv.nix packages" >&2
      exit 2
    fi

    # Resolve the guard BEFORE the pipeline: `exit` inside `{ } | tee` runs in a
    # subshell and would not fail the run.
    if command -v copier >/dev/null 2>&1; then
      copier_state="PRESENT at $(command -v copier) — this environment is not isolated"
      isolated=0
    else
      copier_state="absent (as intended)"
      isolated=1
    fi

    {
      echo "jj       $(jj --version)"
      echo "git      $(git --version)"
      echo "python   $(python3 --version)"
      echo "JJ_CONFIG=$JJ_CONFIG"
      echo "copier   $copier_state"
    } | tee "$SPIKE_WORK/toolchain.txt"

    [ "$isolated" = 1 ] || exit 2
  '';

  scripts.spike-clean.exec = ''
    set -eu
    rm -rf "$SPIKE_WORK"
    echo "cleared $SPIKE_WORK"
  '';

  # https://devenv.sh/tasks/
  tasks = {
    "spike:versions".exec = "spike-versions";
    "spike:clean".exec = "spike-clean";
  };

  # https://devenv.sh/tests/
  # `devenv test` is the entry point, which is itself part of the design being
  # evaluated: a template ships its checks as devenv `enterTest`, so the tool
  # needs no `checks:` DSL and no `sh -c` runner of its own.
  enterTest = ''
    # pipefail matters: enterTest pipes each script through `tee`, and without it
    # the pipeline's status is tee's (always 0), so a failing experiment would be
    # silently reported as a pass.
    set -euo pipefail
    # devenv LAYERS its profile onto the host PATH, it does not replace it, so a
    # parent environment leaks in: CopyRoom's own .devenv venv ships `copier`.
    # Scrub to the profile, which carries every tool this spike needs (jj, git,
    # python3, diff, jq, and the spike scripts themselves). This makes the
    # isolation claim enforced rather than merely stated.
    export PATH="$DEVENV_PROFILE/bin"
    spike-versions
    mkdir -p "$SPIKE_WORK"

    shopt -s nullglob
    scripts=("$DEVENV_ROOT"/spike-*.sh)
    if [ ''${#scripts[@]} -eq 0 ]; then
      echo "No spike-*.sh yet — environment is ready, experiments not written." >&2
      exit 0
    fi

    # Run EVERY experiment even when one fails. A spike that stops at the first
    # failure hides the findings behind it, and a failed question is a result
    # here, not an error.
    failed=()
    for s in "''${scripts[@]}"; do
      echo ""
      echo "=== $(basename "$s") ==="
      # Tee the transcript: `devenv test` hides stdout on success, so without
      # this a green run leaves no record of WHAT passed.
      if bash "$s" 2>&1 | tee -a "$SPIKE_WORK/transcript.txt"; then :; else
        failed+=("$(basename "$s")")
      fi
    done
    echo "transcript: $SPIKE_WORK/transcript.txt" >&2

    echo ""
    echo "=== spike 12 summary ==="
    if [ ''${#failed[@]} -eq 0 ]; then
      echo "all experiments passed"
    else
      printf 'experiments with failures: %s\n' "''${failed[*]}"
      exit 1
    fi
  '';

  enterShell = ''
    echo "Spike 12 — jj render/merge evaluation."
    echo "  devenv test      run every spike-*.sh"
    echo "  spike-versions   record the toolchain"
    echo "  spike-clean      wipe $SPIKE_WORK"
  '';
}
