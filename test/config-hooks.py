#!/usr/bin/env python3
"""Exercise configured hooks with real local pushes and isolated Git configuration."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(tempfile.mkdtemp(prefix="guard-compat-", dir=os.environ.get("TMPDIR", "/var/tmp")))
RESULTS = []


def run(args, cwd, env, ok=True):
    p = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if ok and p.returncode:
        raise RuntimeError(f'cannot run fixture command "{args[0]}": {p.stderr.strip()}')
    return p


def check(name, value):
    RESULTS.append({"name": name, "pass": bool(value)})
    print(f"{'PASS' if value else 'FAIL'} {name}", flush=True)


def fixture(label, object_format="sha1"):
    root = BASE / label
    root.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=str(root / "gitconfig"), GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="guard-test", GIT_AUTHOR_EMAIL="test@example.invalid",
               GIT_COMMITTER_NAME="guard-test", GIT_COMMITTER_EMAIL="test@example.invalid",
               AGENT_GUARD="1", AGENT_GUARD_INSTALL_DIR=str(root / "guard's files"))
    (root / "gitconfig").write_text("[init]\n defaultBranch = main\n")
    origin, work = root / "origin.git", root / "work"
    run(["git", "init", "-q", "--bare", f"--object-format={object_format}", str(origin)], root, env)
    run(["git", "clone", "-q", str(origin), str(work)], root, env)
    (work / "base").write_text("base\n")
    run(["git", "add", "base"], work, env)
    run(["git", "commit", "-qm", "base"], work, env)
    run(["git", "push", "-q", "origin", "main"], work, env)
    # The remote has a hosted-looking URL but Git's transport stays local.
    url = "https://fixture.invalid/repo.git"
    real_exec = Path(run(["git", "--exec-path"], work, env).stdout.strip())
    farm = root / "git-exec"
    farm.mkdir()
    for entry in real_exec.iterdir():
        if entry.name != "git-remote-https":
            (farm / entry.name).symlink_to(entry)
    helper = farm / "git-remote-https"
    helper.write_text('#!/bin/sh\nwhile read -r line; do\ncase "$line" in\n'
                      'capabilities) printf "connect\\n\\n" ;;\n'
                      f'"connect "*) printf "\\n"; exec "${{line#connect }}" "{origin}" ;;\n'
                      '"") exit 0 ;;\nesac\ndone\n')
    helper.chmod(0o755)
    env["GIT_EXEC_PATH"] = str(farm)
    run(["git", "remote", "set-url", "origin", url], work, env)
    run([str(ROOT / "install.sh")], work, env)
    return root, work, env


def hook_file(directory):
    directory.mkdir(parents=True, exist_ok=True)
    hook = directory / "pre-push"
    hook.write_text('#!/bin/sh\ncat >> "$FIXTURE_HOOK_LOG"\necho ran >> "$FIXTURE_HOOK_RUNS"\n')
    hook.chmod(0o755)


def compatibility(label, custom=False, reader=False, linked=False):
    root, work, env = fixture(label)
    env.update(FIXTURE_HOOK_LOG=str(root / "hook-refs"), FIXTURE_HOOK_RUNS=str(root / "hook-runs"))
    hooks = work / ".git/hooks"
    if custom:
        hooks = work / ".husky/_"
        run(["git", "config", "core.hooksPath", str(hooks)], work, env)
    if reader:
        hook_file(hooks)
    if linked:
        linked_path = root / "linked"
        run(["git", "worktree", "add", "-qb", "feature", str(linked_path)], work, env)
        work = linked_path
    else:
        run(["git", "checkout", "-qb", "feature"], work, env)
    (work / "change").write_text("reviewed\n")
    run(["git", "add", "change"], work, env)
    run(["git", "commit", "-qm", "change"], work, env)
    allowed = run(["git", "push", "origin", "feature"], work, env, False)
    check(f"{label}: feature push allowed", allowed.returncode == 0)
    if reader:
        check(f"{label}: hook ran once for allowed push", (root / "hook-runs").read_text().splitlines().count("ran") == 1)
    denied = run(["git", "push", "origin", "feature:main"], work, env, False)
    check(f"{label}: main update rejected", denied.returncode != 0 and 'cannot push ref' in denied.stderr)
    if reader:
        check(f"{label}: hook received refs", "refs/heads/feature" in (root / "hook-refs").read_text())
        check(f"{label}: hook ran once for rejected push", (root / "hook-runs").read_text().splitlines().count("ran") == 2)
    before = run(["git", "config", "--get", "core.hooksPath"], work, env, False).stdout
    run([str(ROOT / "install.sh")], work, env)
    after = run(["git", "config", "--get", "core.hooksPath"], work, env, False).stdout
    check(f"{label}: installer preserves hook path", before == after)
    events = run(["git", "config", "--global", "--get-all", "hook.agent-git-guard.event"], work, env).stdout
    check(f"{label}: reinstall keeps one registration", events.splitlines() == ["pre-push"])


for args in [("plain", False, True, False), ("husky-empty", True, False, False),
             ("husky-reader", True, True, False), ("worktree", False, True, True)]:
    compatibility(*args)

for object_format in ("sha1", "sha256"):
    root, work, env = fixture(object_format, object_format)
    run(["git", "checkout", "-qb", "feature"], work, env)
    (work / "change").write_text("reviewed\n")
    run(["git", "add", "change"], work, env)
    run(["git", "commit", "-qm", "change"], work, env)
    run(["git", "push", "-q", "origin", "feature"], work, env)
    expected = run(["git", "rev-parse", "HEAD"], work, env).stdout.strip()
    run(["git", "commit", "-q", "--amend", "-m", "reviewed change"], work, env)
    p = run(["git", "push", f"--force-with-lease=refs/heads/feature:{expected}", "origin", "feature"], work, env, False)
    check(f"{object_format}: own rewrite allowed", p.returncode == 0)
    p = run(["git", "push", "origin", "--delete", "main"], work, env, False)
    check(f"{object_format}: main deletion rejected", p.returncode != 0 and "cannot push ref" in p.stderr)
    run(["git", "--git-dir", str(root / "origin.git"), "symbolic-ref", "HEAD", "refs/heads/feature"], work, env)
    (work / "change").write_text("new\n")
    run(["git", "commit", "-qam", "more"], work, env)
    p = run(["git", "push", "origin", "feature"], work, env, False)
    check(f"{object_format}: changed remote default detected", p.returncode != 0 and "default-branch" in p.stderr)

root, work, env = fixture("shallow")
run(["git", "checkout", "-qb", "feature"], work, env)
(work / "change").write_text("reviewed\n")
run(["git", "add", "change"], work, env)
run(["git", "commit", "-qm", "change"], work, env)
run(["git", "push", "-q", "origin", "feature"], work, env)
shallow = root / "shallow"
run(["git", "clone", "-q", "--depth=1", "-b", "feature", "https://fixture.invalid/repo.git", str(shallow)], root, env)
expected = run(["git", "rev-parse", "HEAD"], shallow, env).stdout.strip()
run(["git", "commit", "-q", "--amend", "-m", "corrected"], shallow, env)
p = run(["git", "push", f"--force-with-lease=refs/heads/feature:{expected}", "origin", "feature"], shallow, env, False)
check("shallow rewrite rejected", p.returncode != 0 and "full history" in p.stderr)
run(["git", "fetch", "--unshallow", "origin"], shallow, env)
p = run(["git", "push", f"--force-with-lease=refs/heads/feature:{expected}", "origin", "feature"], shallow, env, False)
check("rewrite allowed after obtaining full history", p.returncode == 0)
run(["git", "config", "--add", "agentGitGuard.protectedRef", "refs/heads/feature"], shallow, env)
(work / "change").write_text("another\n")
run(["git", "commit", "-qam", "another"], work, env)
p = run(["git", "push", "origin", "HEAD:feature"], shallow, env, False)
# Deletion guarantees a nonempty update even when the source tip is unchanged.
p = run(["git", "push", "origin", "--delete", "feature"], shallow, env, False)
check("explicit protected ref rejected", p.returncode != 0 and "configured as protected" in p.stderr)

root, work, env = fixture("dangling-head")
origin = root / "origin.git"
run(["git", "--git-dir", str(origin), "symbolic-ref", "HEAD", "refs/heads/production"], work, env)
before = run(["git", "ls-remote", "--refs", "origin"], work, env).stdout
p = run(["git", "push", "origin", "HEAD:refs/heads/production"], work, env, False)
check("dangling remote HEAD rejected", p.returncode != 0 and "no resolvable default branch" in p.stderr)
check("dangling remote HEAD rejection preserves refs", before == run(["git", "ls-remote", "--refs", "origin"], work, env).stdout)
# An empty repository still permits a first task-branch push.
run(["git", "--git-dir", str(origin), "update-ref", "-d", "refs/heads/main"], work, env)
p = run(["git", "push", "origin", "HEAD:refs/heads/main"], work, env, False)
check("empty remote main creation rejected", p.returncode != 0 and "cannot push ref" in p.stderr)
p = run(["git", "push", "origin", "HEAD:refs/heads/task"], work, env, False)
check("empty remote task creation allowed", p.returncode == 0 and run(["git", "--git-dir", str(origin), "rev-parse", "refs/heads/task"], work, env).stdout == run(["git", "rev-parse", "HEAD"], work, env).stdout)

root, work, env = fixture("installer")
config = root / "gitconfig"
run(["git", "config", "--global", "core.hooksPath", str(root / "custom-global-hooks")], work, env)
run([str(ROOT / "install.sh")], work, env)
check("unrelated global hook path preserved", run(["git", "config", "--global", "--get", "core.hooksPath"], work, env).stdout.strip() == str(root / "custom-global-hooks"))
run(["git", "config", "--global", "core.hooksPath", str(Path.home() / ".git-hooks")], work, env)
before = config.read_bytes()
p = run([str(ROOT / "install.sh")], work, env, False)
check("legacy migration requires explicit install option", p.returncode != 0 and config.read_bytes() == before)
run([str(ROOT / "install.sh"), "--migrate-legacy"], work, env)
check("legacy migration restores native hook lookup", run(["git", "config", "--global", "--get", "core.hooksPath"], work, env, False).returncode == 1)
fakebin = root / "fakebin"
fakebin.mkdir()
real_git = shutil.which("git")
fakegit = fakebin / "git"
fakegit.write_text('#!/bin/sh\ncase "$*" in *"hook list pre-push"*) exit 129 ;; esac\n' + f'exec "{real_git}" "$@"\n')
fakegit.chmod(0o755)
old_env = dict(env, PATH=str(fakebin) + os.pathsep + env["PATH"], AGENT_GUARD_INSTALL_DIR=str(root / "unsupported-install"))
before = config.read_bytes()
p = run([str(ROOT / "install.sh")], work, old_env, False)
check("unsupported Git fails without configuration mutation", p.returncode != 0 and config.read_bytes() == before and not (root / "unsupported-install").exists())

print(json.dumps({"checks": RESULTS, "artifacts": str(BASE)}, indent=2))
raise SystemExit(0 if all(r["pass"] for r in RESULTS) else 1)
