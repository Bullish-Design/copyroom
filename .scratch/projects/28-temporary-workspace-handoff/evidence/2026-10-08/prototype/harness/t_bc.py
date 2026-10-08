from common import *
import sys

def b(jjbin, tag):
    repo = mkrepo("reject-b-" + tag, jjbin=jjbin)
    ev = Evidence(f"b-reject-committed-foreign-{tag}.txt")
    exp = cid(repo, "@", jjbin); p = cid(repo, 'description(exact:"prepared\n")', jjbin)
    ev.w("writer CLI:", jjbin)
    ev.w("expected=", exp, "P=", p)
    # preparation done. foreign writer: jj new -m foreign, edit, commit
    jj(repo, "new", "-m", "foreign", jjbin=jjbin)
    (repo / "foreign.txt").write_text("foreign bytes\n")
    jj(repo, "commit", "-m", "foreign work", jjbin=jjbin)
    ev.block("jj log BEFORE publish_if", log(repo, jjbin)); ev.block("jj op log BEFORE", oplog(repo, jjbin=jjbin))
    ops0 = opids(repo, jjbin); at0 = cid(repo, "@", jjbin); sig0 = tree_sig(repo)
    r = run(publish_cmd(repo, exp, p, "publish_if: should-not-exist"), check=False)
    ev.w("publish_if exit", r.returncode, "stdout:", r.stdout.strip(), "stderr:", r.stderr.strip())
    ops1 = opids(repo, jjbin); at1 = cid(repo, "@", jjbin)
    ev.block("jj log AFTER", log(repo, jjbin)); ev.block("jj op log AFTER", oplog(repo, jjbin=jjbin))
    ev.w("op log unchanged:", ops0 == ops1, "| @ unchanged:", at0 == at1, "| op heads:", op_heads(repo))
    ev.w("sig diff of .jj:", sig_diff(sig0, tree_sig(repo)))
    ev.w("foreign.txt on disk:", (repo/"foreign.txt").read_text().strip())
    ev.w("foreign commit has file:", jj(repo,"file","show","-r","@-","foreign.txt",observe=True).stdout.strip())
    ev.w("jj status:", jj(repo,"status",jjbin=jjbin).stdout.strip().replace("\n"," | "))
    ev.w("OUTCOME b/%s:" % tag, "PASS" if (r.returncode==1 and ops0==ops1 and at0==at1) else "FAIL")

def c():
    repo = mkrepo("reject-c")
    ev = Evidence("c-reject-dirty-file-edit.txt")
    exp = cid(repo, "@"); p = cid(repo, 'description(exact:"prepared\n")')
    ev.w("expected=", exp, "P=", p)
    # direct edit, no jj command: modify a tracked file AND create a new file
    run([PY, "-c", "open('a.txt','w').write('EDITED BY PLAIN PYTHON\\n'); open('new.txt','w').write('brand new\\n')"], cwd=repo)
    ev.block("jj op log BEFORE", oplog(repo)); ops0 = opids(repo)
    sig0 = tree_sig(repo)
    objs0 = len([1 for _ in (repo/".jj/repo/store/git/objects").rglob("*") if _.is_file()])
    r = run(publish_cmd(repo, exp, p, "publish_if: should-not-exist"), check=False)
    ev.w("publish_if exit", r.returncode, "stdout:", r.stdout.strip(), "stderr:", r.stderr.strip())
    ops1 = opids(repo)
    ev.w("op log unchanged:", ops0 == ops1, "| op heads:", op_heads(repo))
    d = sig_diff(sig0, tree_sig(repo)); ev.w("sig diff of .jj (file hashes):", d)
    objs1 = len([1 for _ in (repo/".jj/repo/store/git/objects").rglob("*") if _.is_file()])
    ev.w("git object files in store BEFORE/AFTER:", objs0, objs1, "(new unreferenced blobs/trees written by the in-memory snapshot)")
    ev.w("a.txt on disk:", repr((repo/"a.txt").read_text()), "new.txt on disk:", repr((repo/"new.txt").read_text()))
    ev.w("@ still:", cid(repo,"@") == exp, "(jj --ignore-working-copy, no snapshot)")
    # now a normal jj command: it snapshots the writer's bytes into @
    st = jj(repo, "status").stdout
    ev.block("jj status afterwards (normal CLI snapshots the bytes)", st)
    ev.w("snapshot now in op log:", oplog(repo, 2).splitlines())
    ev.w("@ now:", cid(repo,"@"), "contains a.txt =", repr(jj(repo,"file","show","-r","@","a.txt",observe=True).stdout), "and new.txt =", repr(jj(repo,"file","show","-r","@","new.txt",observe=True).stdout))
    # retry publish_if with the new @ id as expected: still rejects? expected=new @ -> clean now so would succeed
    ev.w("OUTCOME c:", "PASS" if (r.returncode==1 and ops0==ops1) else "FAIL")
    # also: dirty + the caller's expected equals new snapshot id? impossible, shown above.

b(JJ44, "jj044"); b(JJ43, "jj043"); c()
