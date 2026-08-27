# agent-git-guard

A `pre-push` hook that stops a coding agent pushing to `main`, or discarding
commits it has never seen, and leaves you alone when you push the same things
yourself.

It exists because a coding agent of mine pushed a commit deleting every file in
two repositories to `main`, and one of those pushes triggered a production
deployment. The full story is in
[How my coding agent pushed the deletion of every file to main](https://dev.karakun.com/2026/08/27/coding-agent-pushed-deletion-to-main.html).

## Why a git hook rather than an agent hook

Claude Code and Codex both have hooks that can refuse a command before it runs.
They are worth having, but they only see what the agent runs as a command, and
they see it as text. The push that caused my incident came from inside a script
the agent wrote. No agent hook can see that one. Git sees every push, whoever or
whatever started it.

## What it does

| the agent pushes | result |
| --- | --- |
| a branch, or a new branch | allowed |
| an amend of its own commits, force-pushed | allowed |
| a rewrite dropping commits the branch never had | refused |
| anything to `main` or `master` | refused |
| `main` from inside a script it wrote | refused |
| anything to a `file://` or local path remote | allowed |
| and when it is you pushing, not an agent | allowed |

The rewrite rule does not look at which force flag was used. It asks whether the
branch ever contained the commit that is on the remote, and answers from the
reflog. If it did, the rewrite is the agent's own work and even a plain `--force`
is fine. If it did not, the push would discard work nobody on this machine has
seen, and no flag makes that safe.

That check exists in git as `--force-if-includes`. It is in the hook because
`--force-with-lease` alone is not enough under an agent: the lease compares
against your remote-tracking ref, agent tooling fetches in the background, and a
refreshed ref satisfies the lease for commits you never had.

## Install

```sh
git clone https://github.com/martinfrancois/agent-git-guard.git
cd agent-git-guard
./install.sh
```

Or without the script, which is all it does:

```sh
mkdir -p ~/.git-hooks
cp pre-push ~/.git-hooks/pre-push
chmod +x ~/.git-hooks/pre-push
git config --global core.hooksPath ~/.git-hooks
```

POSIX `sh`, no bashisms, no `/proc`. Linux, macOS, and Git for Windows from Git
Bash.

### If you use husky

Husky sets `core.hooksPath` in the repository, and repository config beats global
config, so in a husky repo the global hook never runs at all. Those repositories
need the guard inside husky's own hook. Once per repository, from the repository
root:

```sh
{ printf '#!/bin/sh\n"$HOME"/.git-hooks/pre-push "$@" || exit 1\n'
  if [ -f .husky/pre-push ]; then tail -n +2 .husky/pre-push; fi
} > .husky/pre-push.tmp && mv .husky/pre-push.tmp .husky/pre-push && chmod +x .husky/pre-push
```

The guard line has to come first. Git feeds the pushed refs to the hook on stdin,
and a hook that reads stdin consumes them, so a guard placed after one of those
gets an empty list and allows every push. There is a test for exactly that.

## How it tells an agent from a human

Coding agents mark the environment of every command they run, and the environment
is inherited, so the marker is still present when a script the agent wrote pushes
on its own. The hook enforces when it sees one and does nothing when it does not.

| tool | marker |
| --- | --- |
| Claude Code | `CLAUDECODE` |
| Codex | `CODEX_THREAD_ID` |
| anything else | set `AGENT_GUARD=1` |

For another tool, run `env | sort` inside an agent session, find a variable that
is not in your own shell, and add it to the check near the top of the hook.

## The instruction block that goes with it

The hook is the layer that holds. This is the layer that makes the agent behave
sensibly when it hits one. Codex reads `AGENTS.md`, Claude Code reads
`CLAUDE.md`.

```md
## Git

- Read `git diff --cached --stat` before every commit and account for every file it lists. A file or a deletion you did not intend: stop and tell me.
- Land changes on the default branch through a pull request, and ask before merging unless a standing rule allows self-merge.
- A rejected push is a stop signal: fetch, look at the remote, tell me. Force-push only when I approve, with `--force-with-lease --force-if-includes`.
- If a push already did damage, tell me before you repair it. Repair by adding a commit.
- A `pre-push` hook refuses these pushes, including ones a script makes. When it fires, stop and tell me. `--no-verify`, `AGENT_GUARD_APPROVE`, and clearing the environment marker it uses to tell an agent from a human, are my overrides, never yours.
```

## Verify it

```sh
./test/run-tests.sh
```

20 checks. It builds throwaway repositories in a temp directory, runs real
pushes, and cleans up after itself. Nothing leaves your machine.

## Limits worth knowing before you rely on it

**It protects this machine, not your repository.** Another laptop, a CI runner, a
colleague, none of them have it. Branch protection on the remote is the layer
that protects the repository. If you already work through pull requests, turning
it on costs nothing and covers every machine at once.

**The marker is a convention, not a sandbox.** An agent that decides to unset
`CLAUDECODE` gets through. That is a deliberate act rather than a judgment call,
which is the difference this hook is built on, but it is not a wall.

**`--no-verify` skips it.** That is deliberate. It is your override as a human,
and it is worth telling your agent in writing that the flag is not theirs.

**`AGENT_GUARD_APPROVE=1` on a single push skips it too.** That one is for the times
you tell the agent to go ahead anyway. Anything the agent can type is a soft
limit rather than a wall: this exists so an approved push is deliberate and
visible in the transcript, not so the guard cannot be bypassed. It prints a line
to stderr when it is used.

**A global `core.hooksPath` makes git ignore each repository's own
`.git/hooks`.** The hook hands control back to the repository's hook when there
is one, so nothing you installed yourself stops working. Keep that part if you
edit the file.

## License

Apache License 2.0. See [LICENSE](LICENSE).
