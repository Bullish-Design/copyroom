# Research report — local git+file devenv input

Date: 2026-10-07 UTC

## Question and method

Test whether a `git+file://` input locks a local template commit. Test an
uncommitted edit, a new commit on `main`, and `devenv update local-template`.
Run [reproduce.sh](reproduce.sh) from spike 12's devenv shell:

```sh
cd .scratch/projects/12-jj-render-merge
devenv shell -- bash ../22-devenv-git-file/reproduce.sh
```

The script creates a disposable colocated jj/Git template repository under
this spike's `.devenv/state`. It writes only to this spike and its generated
state. It uses devenv 2.4.0 and jj 0.45.1. The [run output](evidence/2026-10-07-results.txt)
and saved [v1](evidence/lock-v1.json),
[v2 before update](evidence/lock-v2-before-update.json), and
[v2 after update](evidence/lock-v2-after-update.json) locks hold the evidence.

## Result

**A local `git+file://` input did not lock the template commit in this
environment.** Its `locked` node contained `ref: main`, `type: git`, and the
local file URL. It contained no `rev` or `narHash`. The lock checksum stayed
`74022d5daaf0893eaf7c0904e1f1489c53111a214471c65115fa923591f7a556`
through all stages.

The initial `main` bookmark pointed to commit
`ab7e4a82e5ed060f123741d8bc180c4d332fe44b`. A fresh devenv evaluation
read version one from a Nix store path. An uncommitted edit to version two
remained invisible after another fresh evaluation. This confirms that the
input read committed Git content from the branch, not the working copy.

The script committed the edit and moved `main` to
`62c0f631b4cbe89607fd51f68024f22b5281297e`. A fresh evaluation read
version two from a different store path **before** `devenv update`. The lock
checksum stayed the same. `devenv update local-template` then left the lock
unchanged and still read version two. Thus the input follows the local branch
tip when evaluation refreshes; the lock does not hold the former tip.

The [devenv inputs guide](https://devenv.sh/inputs/) lists `git+file://` for
local Git repositories. It also describes revision locking for fetched
inputs. The observed local `git+file://` lock did not contain a revision.
This is a result for devenv 2.4.0 and this URL form with `?ref=main`.

## Design consequence

`git+file://` removes uncommitted edits from the render input, but the
`devenv.lock` entry cannot identify the committed source used for a render.
Record the template commit ID separately, or use an explicit immutable
revision in the source reference and verify it. Keep the rendered bytes in
the project render commit. This spike did not test a `git+file` URL with an
explicit `rev` parameter, a remote Git URL, or moving the template repo.
