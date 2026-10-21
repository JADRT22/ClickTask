#!/usr/bin/env bash
# Build the release archive, its SHA256SUMS and (when a signing key is given)
# SHA256SUMS.sig, then optionally upload all three to an existing GitHub release.
#
#   tools/sign-release.sh v1.2.0 ~/.config/clicktask/release-key
#   tools/sign-release.sh v1.2.0 ~/.config/clicktask/release-key --upload
#   tools/sign-release.sh v1.2.0 - --upload          # checksums only, no signature
#
# The updater verifies the signature against the public key pinned in
# src/release_key.py, so rotating the key means a new ClickTask release.
set -euo pipefail

TAG="${1:-}"
KEY="${2:-}"
UPLOAD="${3:-}"

if [ -z "$TAG" ] || [ -z "$KEY" ]; then
    echo "usage: $0 TAG SIGNING_KEY [--upload]" >&2
    exit 2
fi
SIGN=1
if [ "$KEY" = "-" ]; then
    SIGN=0
elif [ ! -f "$KEY" ]; then
    echo "signing key not found: $KEY (use - for an unsigned release)" >&2
    echo "create one with: ssh-keygen -t ed25519 -C clicktask-release -f $KEY" >&2
    exit 2
fi
if [ "$SIGN" = 1 ]; then
    command -v ssh-keygen >/dev/null || { echo "ssh-keygen is required" >&2; exit 2; }
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${TAG#v}"
NAME="ClickTask-$TAG.tar.gz"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

cd "$REPO_DIR"
git archive --format=tar.gz --prefix="ClickTask-$VERSION/" \
    --output="$OUT/$NAME" "$TAG"
(
    cd "$OUT"
    sha256sum "$NAME" > SHA256SUMS
    if [ "$SIGN" = 1 ]; then
        ssh-keygen -Y sign -f "$KEY" -n clicktask SHA256SUMS
    fi
)

ASSETS=("$OUT/$NAME" "$OUT/SHA256SUMS")
if [ "$SIGN" = 1 ]; then
    ASSETS+=("$OUT/SHA256SUMS.sig")
else
    echo "warning: unsigned release — updater checks only the SHA256 digest" >&2
fi

echo "built:"
ls -l "$OUT"
echo
echo "SHA256SUMS:"
cat "$OUT/SHA256SUMS"

if [ "$UPLOAD" = "--upload" ]; then
    command -v gh >/dev/null || { echo "gh is required for --upload" >&2; exit 2; }
    gh release upload "$TAG" "${ASSETS[@]}" --clobber
    echo "uploaded to release $TAG"
else
    echo "upload with: gh release upload $TAG ${ASSETS[*]@Q}"
fi
