from common import *
repo = mkrepo("smoke")
print(log(repo)); print(oplog(repo))
exp = cid(repo, "@"); p = cid(repo, 'description(exact:"prepared\n")')
print(exp, p)
r = run(publish_cmd(repo, exp, p), check=False); print(r.returncode, r.stdout, r.stderr)
print(log(repo)); print(oplog(repo)); print(jj(repo,"status").stdout); print(sorted(x.name for x in repo.iterdir()))
