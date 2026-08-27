#!/bin/sh
# Installs the pre-push guard globally. Read it before running it.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)/pre-push"
DEST="$HOME/.git-hooks"
CURRENT=$(git config --global --get core.hooksPath || true)

if [ -n "$CURRENT" ] && [ "$CURRENT" != "$DEST" ] && [ "$CURRENT" != "~/.git-hooks" ]; then
  echo "core.hooksPath is already set to: $CURRENT"
  echo "Not touching it. Copy pre-push into that directory yourself, or chain to it from there."
  exit 1
fi

mkdir -p "$DEST"
cp "$SRC" "$DEST/pre-push"
chmod +x "$DEST/pre-push"
git config --global core.hooksPath "$DEST"

echo "Installed $DEST/pre-push and set core.hooksPath."
echo
echo "Repositories that set their own core.hooksPath, husky among them, ignore this."
echo "Check one with: git config core.hooksPath"
echo "For those, see the husky section of the README."
