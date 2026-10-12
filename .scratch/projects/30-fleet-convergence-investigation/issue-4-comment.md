Draft comment for issue #4. Not posted.

---

**The refusal is intended.** 0.8.0 replaced Copier with local Templateer
sources and jj (`df9b9d4`, project 27 guide). The defect is that the exit the
refusal advertises does not work for the fleet:

1. `adopt` needs a Templateer source (`manifest.json`). template-py and
   template-nix are Copier templates.
2. `templatize` freezes one render as literal files. It does not convert a
   template that has variables.
3. The message suggests that the Copier answers file can be `--answers FILE`.
   FILE must be JSON.
4. `adopt --write` fails on every devman-linked repo. CopyRoom reads the
   project by a filesystem walk that ignores `.gitignore`. jj's tracked tree
   omits the ignored `.agents` link, so the two digests differ. The command
   exits 1 with "adoption merge did not preserve the project tree" and leaves
   `.jj`, `.git`, and a baseline commit behind.

**Plan.** We will go forward only, with no Copier compatibility mode:

1. CopyRoom reads the project through jj's tracked view. A failed adopt rolls
   back. The refusal text names the real steps. This is the first lane, and
   it lands alone.
2. Release v0.8.2 from `main`. That release also fixes the
   `../templateer_v2` path source in v0.8.0 and v0.8.1.
3. A one-time converter turns template-py and template-nix into Templateer
   sources. A prototype reproduced both templates byte for byte. The
   templates stop shipping `.agents/**`.
4. A one-time fleet script converts `.copier-answers.yml` to JSON answers. It
   adopts each repo at its creation version (v0.5.0), deletes the Copier
   marker, and then runs `update` to the new source.
5. After the fleet migrates, CopyRoom drops the legacy-marker refusal and the
   Copier docs.

Investigation report: `.scratch/projects/30-fleet-convergence-investigation/REPORT.md`.
