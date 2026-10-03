# Project 11 — independent template layers

This record documents the design and rollout work that added Copier layers to
CopyRoom. The rollout data is historical. It does not describe current machine
state.

The original work used a cross-repo configuration template to test the layer
feature. Current product examples use a neutral documentation overlay. The
general layer mechanism remains in CopyRoom.

## Documents

| File | What it holds |
|------|---------------|
| [`FINDINGS.md`](FINDINGS.md) | Ownership and update problems found in the original distribution model |
| [`SPIKE.md`](SPIKE.md) | Copier tests for independent answers files and layer updates |
| [`spike-layers.sh`](spike-layers.sh) | The runnable synthetic test for five Copier behaviors |
| [`DESIGN.md`](DESIGN.md) | The layer model, command surface, and implementation decisions |
| [`IMPLEMENTATION.md`](IMPLEMENTATION.md) | Code changes, measurements, and rollout lessons |
| [`verify-overlay-layer.sh`](verify-overlay-layer.sh) | Layer behavior against a real CopyRoom-managed repo |
| [`verify-two-real-layers.sh`](verify-two-real-layers.sh) | Independent updates on a repo with a real base template |
| [`ROLLOUT.md`](ROLLOUT.md) | Historical fleet rollout results and issues found |

## Historical status

CopyRoom 0.7.2 shipped the layer feature. At that time, 589 tests passed, Ruff
was clean, the walkthrough passed, and both verification scripts passed.
Later work removed the cross-repo configuration deployments. The counts in
[`ROLLOUT.md`](ROLLOUT.md) describe that earlier rollout only.

Dogfooding found three implementation issues: `layer add` needed overwrite
behavior, update order mattered when templates seeded the same file, and the
layer command recorded a local cache path instead of the caller's source. The
fixes and measurements remain in [`IMPLEMENTATION.md`](IMPLEMENTATION.md).
