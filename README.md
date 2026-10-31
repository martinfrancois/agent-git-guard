# agent-git-guard

A Git `pre-push` hook that blocks agent updates to the default branch and rejects
rewrites when the local branch never incorporated the remote tip. It allows
routine PR branch rewrites after the agent integrates incoming work. Human pushes
are unaffected.

It exists because a coding agent pushed commits deleting every file in two
repositories to `main`, triggering a production deployment. The incident is in
[How my coding agent pushed a commit deleting every file to main](https://dev.karakun.com/2026/08/28/coding-agent-pushed-deletion-to-main.html).

## What the hook checks

| Agent action | Result |
| --- | --- |
| Create or fast-forward a task branch | Allowed |
| Amend, squash, or rebase a branch that incorporated the remote tip | Allowed in a full clone |
| Rewrite without incorporating the current remote tip | Rejected; integrate, review, and retry |
| Rewrite from a shallow clone | Rejected; obtain full history first |
| Update or delete `main`, `master`, or the remote's actual default branch | Rejected |
| Update a ref listed in `agentGitGuard.protectedRef` | Rejected |
| Push from a script the agent started | Same checks |
| Push to a local path or `file://` remote | Exempt |
| Push without an agent marker | Unchanged |

The hook reads the default branch from the actual push destination. A failed
lookup stops the push. This adds one `ls-remote` call per nonempty hosted push;
remote-tracking HEAD alone would miss a default-branch change. An empty HEAD
result triggers a second lookup to distinguish an empty repository from a
nonempty repository with an unresolved default. The latter is rejected until
the remote HEAD is repaired. Empty repositories still permit first task branches.

The hook recognizes `CLAUDECODE`, `CODEX_THREAD_ID`, and `CODEX_SESSION_ID`.
Set `AGENT_GUARD=1` when invoking another agent. Detection uses inherited
process environment, so it covers subprocesses without parsing shell commands.

## Install without replacing repository hooks

```sh
git clone https://github.com/martinfrancois/agent-git-guard.git
cd agent-git-guard
./install.sh
```

The installer uses Git's configured hooks. It registers `agent-git-guard` for
`pre-push` and leaves `core.hooksPath` unchanged. Husky and native repository hooks
continue to run, with their own copy of stdin. No per-repository edits are needed.
Git runs the other hooks even when the guard rejects a push.

The installer probes configured-hook support before changing anything. If your
Git lacks it, upgrade Git and rerun the installer. Git 2.56.0 is tested here; the
probe is authoritative for other builds. The hook itself is POSIX shell, with no
Linux `/proc` dependency. Tests on Linux do not establish macOS or Windows support.

Verify registration from a repository:

```sh
git hook list pre-push
```

The default installation directory is `~/.local/share/agent-git-guard`.
`AGENT_GUARD_INSTALL_DIR` selects a different directory at installation time.
Reinstalling updates the hook without adding duplicate registrations.

### Migrating the old global hook path

The old installer set `core.hooksPath=~/.git-hooks`. Inspect that directory for
custom hooks before migrating:

```sh
./install.sh --migrate-legacy
```

Migration removes that global hook-path setting and restores Git's native
repository-hook lookup. It keeps the old files, registers the new guard, and
leaves repository-local hook paths unchanged. Move any custom global hooks you
want to retain into separate configured-hook registrations first. An unrelated
global hook path is preserved by the normal installer.

Old manual installations remain supported when the script runs without
`--config-hook`; that mode chains to the repository's common Git hooks directory.
It retains the old limitations: a repository hook path overrides a global hook
path, and an earlier stdin reader starves a manually chained guard. Prefer the
configured installation.

### Additional protected branches

List full refs for integration or release branches whose updates need approval:

```sh
git config --add agentGitGuard.protectedRef refs/heads/develop
git config --add agentGitGuard.protectedRef refs/heads/release/1.x
```

This is local configuration. The hook does not query GitHub or another host's
branch-protection API. Enforce repository-wide rules on the remote too.

## Agent instructions

A hook cannot decide whether the rewritten code preserves the intended behavior.
Use instructions such as these when routine PR rewrites have your standing approval:

```md
Routine task-branch pushes and clean-history rewrites have standing approval.
Preserve incoming remote work. Fetch, incorporate, review, and retry without asking
merely because the remote advanced. Keep one commit per logical change.
Use full history and an explicit lease pinned to the remote tip incorporated
before the rewrite. Review the resulting diff and run the relevant checks.
A rejection means satisfy the failed check, never weaken it.
Updating the default or another protected branch still needs specific approval.
Ask when competing changes leave the intended result unclear. Keep hooks and
agent markers enabled; standing rewrite approval does not authorize bypasses.
```

A more detailed procedure is available in the companion `git-safety` skill.
The skill and this hook have different limits; compare them against the tasks
that matter in your workflow.

## Limits

The reflog check proves that the branch previously contained the remote tip.
It does not prove that the final tree preserves that work. An agent that first
incorporates a contributor's commit and later discards it passes this check.
An ordinary fast-forward containing accidental file deletions also passes.
Content review and tests remain necessary. A content-preserving rewrite is also
rejected when the named source branch's reflog does not establish incorporation
of the remote tip. Replaying the correct patches on a new branch does not satisfy
that prerequisite by itself.

A push should use `--force-with-lease=<full-ref>:<recorded-oid>`. A background
fetch does not refresh that explicit lease. Git's `--force-if-includes` adds no
check to an explicit-ID lease. This hook independently checks the local branch's
reflog. It does not inspect push flags, so plain `--force` still passes when the
reflog condition holds. The instruction layer prohibits that substitution.

Git invokes pre-push hooks during `git push --dry-run` too. The hook does not
receive that flag, so it rejects dry runs targeting protected refs. Inspecting
push configuration directly avoids this diagnostic limitation. Treat rejection
counts as failed prerequisites, not a count of prevented data loss.

Local remotes are exempt to support disposable tests. This is a boundary of the
hook, not permission to overwrite a shared repository accessed by a local path.

The guard is a convention, not a sandbox. `--no-verify`, disabling configured
hooks, or clearing agent markers bypasses it. `AGENT_GUARD_APPROVE=1` remains an
explicit per-push override and prints a diagnostic. Agents need the user's
specific permission to use these overrides. A repository can override configured
hook settings, so remote branch protection is the enforcement layer across machines.

## Measurements

The [validation report](docs/validation-2026-10-31.md) compares the old and new
hooks, records compatibility checks, and states what remains unprotected.

## Tests

```sh
./test/run-tests.sh
python3 test/config-hooks.py
```

Both use disposable local repositories. The second suite tests configured-hook
installation, stdin readers, Husky-style paths, worktrees, different object-ID
formats, and shallow-history rejection. Its hosted-looking remotes use a local
transport helper; no push reaches a hosted service.

## License

Apache License 2.0. See [LICENSE](LICENSE).
