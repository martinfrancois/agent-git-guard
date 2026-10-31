#!/bin/sh
# Register a configured hook without replacing repository hook paths.
set -eu
SRC="$(cd "$(dirname "$0")" && pwd)/pre-push"
DEST=${AGENT_GUARD_INSTALL_DIR:-"$HOME/.local/share/agent-git-guard"}
MODE=${1:-}
case "$MODE" in
  ''|--migrate-legacy) ;;
  *) echo 'cannot install guard "argument": use no argument or --migrate-legacy' >&2; exit 1 ;;
esac

# Probe the capability, not a version string. Unsupported Git must not leave a
# global hook path that silently disables a repository's own hooks.
if ! git -c hook.agent-git-guard-probe.event=pre-push \
         -c hook.agent-git-guard-probe.command=: hook list pre-push >/dev/null 2>&1; then
  echo 'cannot install guard "git hook list": upgrade Git to a release with configured hooks; no configuration changed' >&2
  exit 1
fi
CURRENT=$(git config --global --get core.hooksPath || true)
# Compare the literal tilde accepted by Git config.
# shellcheck disable=SC2088
if [ "$MODE" = --migrate-legacy ]; then
  case "$CURRENT" in
    "$HOME/.git-hooks"|'~/.git-hooks') ;;
    *) echo 'cannot migrate guard "core.hooksPath": expected the old ~/.git-hooks installation; no configuration changed' >&2; exit 1 ;;
  esac
elif [ "$CURRENT" = "$HOME/.git-hooks" ] || [ "$CURRENT" = '~/.git-hooks' ]; then
  echo 'cannot install guard "legacy hook path": inspect ~/.git-hooks, then use --migrate-legacy to restore native repository hooks' >&2
  exit 1
fi

mkdir -p "$DEST"
cp "$SRC" "$DEST/pre-push"
chmod +x "$DEST/pre-push"
# Quote the executable path as shell data, including spaces and apostrophes.
quoted=$(printf "%s" "$DEST/pre-push" | sed "s/'/'\\\\''/g")
git config --global --replace-all hook.agent-git-guard.command "'$quoted' --config-hook"
git config --global --replace-all hook.agent-git-guard.event pre-push
git config --global hook.agent-git-guard.enabled true
if [ "$MODE" = --migrate-legacy ]; then
  git config --global --unset-all core.hooksPath
fi
git hook list pre-push
echo 'Installed agent-git-guard alongside repository hooks.'
echo 'Legacy files remain in place. No repository hook was edited.'
