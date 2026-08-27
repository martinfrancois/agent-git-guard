#!/usr/bin/env bash
# Test suite for the pre-push guard. Creates throwaway repositories under a temp
# directory, runs real pushes against local remotes, and cleans up after itself.
#
#   ./test/run-tests.sh
#
# Local remotes are exempt in normal use, so the end-to-end tests run against a
# copy of the hook with that exemption disabled. The exemption itself is covered
# by the unit tests, which call the hook directly with the arguments git passes.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/pre-push"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0
export GIT_AUTHOR_NAME=guard-test GIT_AUTHOR_EMAIL=test@example.invalid
export GIT_COMMITTER_NAME=guard-test GIT_COMMITTER_EMAIL=test@example.invalid
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=init.defaultBranch GIT_CONFIG_VALUE_0=main

ok()    { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()   { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }
check() { [ "$1" = "$2" ] && ok "$3" || bad "$3 (got $1, want $2)"; }

STRICT="$TMP/strict-pre-push"
sed 's|  file://\*|  __no_match__*|' "$HOOK" > "$STRICT"; chmod +x "$STRICT"
Z=0000000000000000000000000000000000000000
agent() { AGENT_GUARD=1 "$@"; }
human() { env -u CLAUDECODE -u CODEX_THREAD_ID -u AGENT_GUARD "$@"; }

echo "unit: which remotes and refs the guard acts on"
mkdir -p "$TMP/u"; cd "$TMP/u"; git init -q -b main .
echo a > a.txt; git add -A; git commit -qm one
echo b > b.txt; git add -A; git commit -qm two
OLD=$(git rev-parse HEAD~1); NEW=$(git rev-parse HEAD)
unit() { printf '%s\n' "$3" | agent "$HOOK" origin "$2" >/dev/null 2>&1; check "$?" "$1" "$4"; }
unit 1 "https://example.invalid/x.git" "refs/heads/main $NEW refs/heads/main $OLD"       "main on a hosted remote is refused"
unit 1 "user@example.invalid:x/y.git"  "refs/heads/master $NEW refs/heads/master $OLD"   "master on an ssh remote is refused"
unit 0 "file:///tmp/x.git"             "refs/heads/main $NEW refs/heads/main $OLD"       "main on a file:// remote is allowed"
unit 0 "/tmp/x.git"                    "refs/heads/main $NEW refs/heads/main $OLD"       "main on a path remote is allowed"
unit 0 "https://example.invalid/x.git" "refs/heads/feature $NEW refs/heads/feature $OLD" "fast-forward on a branch is allowed"
unit 0 "https://example.invalid/x.git" "refs/heads/feature $NEW refs/heads/feature $Z"   "a new branch is allowed"
unit 0 "https://example.invalid/x.git" "(delete) $Z refs/heads/feature $NEW"             "deleting a branch is allowed"
printf '%s\n' "refs/heads/main $NEW refs/heads/main $OLD" | \
  human "$HOOK" origin "https://example.invalid/x.git" >/dev/null 2>&1
check "$?" 0 "with no agent marker the guard does nothing"

echo
echo "end to end: real pushes"
mk() {
  git init -q --bare -b main "$TMP/$1.git"
  git clone -q "file://$TMP/$1.git" "$TMP/$1" 2>/dev/null
  cd "$TMP/$1"; mkdir -p "$TMP/hooks-$1"; cp "$STRICT" "$TMP/hooks-$1/pre-push"
  git config core.hooksPath "$TMP/hooks-$1"
  echo a > a.txt; git add -A; git commit -qm base
  git push -q --no-verify origin main
}

mk main1
echo b > b.txt; git add -A; git commit -qm change
agent git push -q origin main 2>/dev/null; check "$?" 1 "agent pushing to main is refused"
human git push -q origin main 2>/dev/null; check "$?" 0 "human pushing to main is allowed"

mk approve1
echo b > b.txt; git add -A; git commit -qm change
agent env AGENT_GUARD_APPROVE=1 git push -q origin main 2>/dev/null
check "$?" 0 "an explicitly approved push to main is allowed"
echo c > c.txt; git add -A; git commit -qm "another change"
agent env AGENT_GUARD_APPROVE= git push -q origin main 2>/dev/null
check "$?" 1 "an empty approval value is not an approval"

mk branch1
git checkout -qb feature; echo b > b.txt; git add -A; git commit -qm work
agent git push -q origin feature 2>/dev/null; check "$?" 0 "agent pushing a new branch is allowed"
echo c > b.txt; git commit -qam more
agent git push -q origin feature 2>/dev/null; check "$?" 0 "agent fast-forwarding a branch is allowed"
echo d > d.txt; git add -A; git commit -q --amend -m amended
agent git push -q --force origin feature 2>/dev/null; check "$?" 0 "agent rewriting its own commits is allowed"

mk rewrite1
git checkout -qb feature; echo b > b.txt; git add -A; git commit -qm mine
agent git push -q origin feature 2>/dev/null
git clone -q "file://$TMP/rewrite1.git" "$TMP/other" 2>/dev/null
git -C "$TMP/other" checkout -q -b feature origin/feature
echo y > "$TMP/other/y.txt"; git -C "$TMP/other" add -A
git -C "$TMP/other" commit -qm "someone else"
git -C "$TMP/other" push -q --no-verify origin feature
THEIRS=$(git -C "$TMP/other" rev-parse feature)
cd "$TMP/rewrite1"; git fetch -q origin
echo z > z.txt; git add -A; git commit -q --amend -m "mine, rewritten"
agent git push -q --force-with-lease origin feature 2>/dev/null
check "$?" 1 "a rewrite dropping commits the branch never had is refused"
git merge-base --is-ancestor "$THEIRS" "$(git ls-remote origin feature | cut -f1)" 2>/dev/null
check "$?" 0 "the other person's commit survived"
git rebase -q origin/feature 2>/dev/null
agent git push -q --force-with-lease --force-if-includes origin feature 2>/dev/null
check "$?" 0 "the same rewrite is allowed once their work is integrated"

mk script1
printf 'import subprocess, sys\nsys.exit(subprocess.run(["git","-C","%s","push","origin","main"]).returncode)\n' "$TMP/script1" > "$TMP/bot.py"
echo b > b.txt; git add -A; git commit -qm "automated change"
agent python3 "$TMP/bot.py" >/dev/null 2>&1
check "$?" 1 "a push from inside a script the agent runs is refused"

echo
echo "end to end: living with other hooks"
mk chain1
printf '#!/bin/sh\necho "repo hook ran" >&2\nexit 0\n' > "$TMP/chain1/.git/hooks/pre-push"
chmod +x "$TMP/chain1/.git/hooks/pre-push"
git checkout -qb feature; echo b > b.txt; git add -A; git commit -qm work
agent git push origin feature 2>&1 | grep -q "repo hook ran"
check "$?" 0 "the repository's own pre-push hook still runs"

mk husky1
mkdir -p .husky; git config core.hooksPath .husky
echo b > b.txt; git add -A; git commit -qm change
printf '#!/bin/sh\n%s "$@" || exit 1\necho "husky hook ran" >&2\ncat > /dev/null\n' "$STRICT" > .husky/pre-push
chmod +x .husky/pre-push
agent git push -q origin main 2>/dev/null; check "$?" 1 "in a husky repo the guard placed first is refused"
printf '#!/bin/sh\necho "husky hook ran" >&2\ncat > /dev/null\n%s "$@" || exit 1\n' "$STRICT" > .husky/pre-push
agent git push -q origin main 2>/dev/null; check "$?" 0 "placed last, a stdin-reading hook starves it: why order matters"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
