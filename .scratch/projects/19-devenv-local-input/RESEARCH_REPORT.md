# Research report — local devenv path input

Date: 2026-10-07 UTC

## Question and method

Can `path:` in `devenv.yaml` and `devenv.lock` identify an immutable local
template revision? The [reproduction script](reproduce.sh) tests a plain
directory and a local jj repository. Run it from spike 12's devenv shell:

```sh
cd .scratch/projects/12-jj-render-merge
devenv shell -- bash ../19-devenv-local-input/reproduce.sh
```

The script keeps Nix state under this spike. It uses devenv 2.4.0 and the
spike 12 jj toolchain. The [run output](evidence/2026-10-07-results.txt)
records paths and content. The saved lock files show the input before and
after each change.

## Result

**The local `path:` input does not pin an immutable template revision.** Both
lock files record only `"path"` and `"type": "path"` for `local-template`.
They record no revision or content hash. `devenv update local-template` left
the plain directory lock file byte-identical. The lock checksum stayed
`3f5efb2a98505ba906b128e9593dfe3f0b1d0495736ecfb80df79343d8b9f4b0`.

For `path:./template`, a fresh evaluation copied version one to a Nix store
path. Editing the source to version two left a normal shell on version one.
`devenv update local-template` still showed version one. Running
`devenv shell --refresh-eval-cache` then showed version two at a new store
path, with the same lock checksum. The evaluation cache affected when the
source change appeared. It did not make the lock an immutable source record.

For `path:../.devenv/state/template-repo`, the input resolved to the live
local repository path. An uncommitted edit from version one to version two
appeared on the next normal shell call. The local repository lock file still
held only the relative path. The run did not need a template commit or
`devenv update` to change rendered input bytes.

The [devenv inputs guide](https://devenv.sh/inputs/) describes local path
inputs and says they copy the whole directory without `.gitignore` rules.
The [composition guide](https://devenv.sh/composing-using-imports/) says
local `path:` changes can enter evaluation automatically. These statements
describe development inputs. The local result above shows why a `path:` lock
cannot replace template source and revision records for a reproducible render.

## Design consequence

Keep an explicit source locator and immutable source identity for each
render. Record a jj commit ID or a content digest, and save the rendered
bytes in the render commit. Use a local path as a convenient source locator,
not as version evidence. A `git+file` input may have different lock behavior;
this spike did not test it.

The plain directory result also shows a cache limit. A normal shell can keep
old bytes after a source edit, while a cache refresh sees new bytes without
a lock change. A render command must read and verify its intended source
directly or use an explicit immutable source reference. It must not infer
template revision from `devenv.lock` for local `path:` inputs.
