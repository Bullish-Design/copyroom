from common import *
for colocate in (False, True):
    repo = mkrepo("happy" + ("-colo" if colocate else ""), colocate=colocate)
    ev = Evidence("a-happy" + ("-colocated" if colocate else "") + ".txt")
    exp = cid(repo, "@"); p = cid(repo, 'description(exact:"prepared\n")')
    ev.w("expected(@)=", exp, "P=", p)
    ev.block("jj log BEFORE", log(repo)); ev.block("jj op log BEFORE", oplog(repo))
    before_ops = opids(repo)
    before_sig = tree_sig(repo)
    r = run(publish_cmd(repo, exp, p, "publish_if: happy"), check=False)
    ev.w("exit", r.returncode, "stdout", r.stdout.strip(), "stderr", r.stderr.strip())
    ev.block("jj log AFTER", log(repo)); ev.block("jj op log AFTER", oplog(repo))
    after_ops = opids(repo)
    new_ops = [o for o in after_ops if o not in before_ops]
    ev.w("new operations:", new_ops, "count=", len(new_ops))
    ev.w("op heads dir:", op_heads(repo))
    at = cid(repo, "@"); atp = cid(repo, "@-")
    ev.w("@ parent == P:", atp == p, " @ empty:", jj(repo,"log","-r","@","--no-graph","-T","empty",observe=True).stdout)
    t_at = jj(repo,"log","-r","@","--no-graph","-T","commit_id ++ \" \" ++ parents.len()",observe=True).stdout
    ev.w("@ commit/parents:", t_at)
    # tree equality: diff P..@ must be empty
    d = jj(repo,"diff","--from",p,"--to","@","--summary",observe=True).stdout
    ev.w("diff P->@ (empty means equal trees):", repr(d))
    ev.w("files on disk:", sorted(x.name for x in repo.iterdir() if not x.name.startswith(".")))
    ev.w("p.txt:", (repo/"p.txt").read_text().strip())
    st = jj(repo, "status").stdout
    ev.block("jj status (a normal jj command; must show no stale WC)", st)
    ev.w("op log after jj status (a clean status must add no op):", len(opids(repo)) - len(after_ops), "extra ops")
    if colocate:
        g = run(["git","-C",str(repo),"status","--short","--branch"]).stdout
        ev.block("git status in colocated repo", g)
        ev.w("git HEAD:", run(["git","-C",str(repo),"rev-parse","HEAD"]).stdout.strip())
