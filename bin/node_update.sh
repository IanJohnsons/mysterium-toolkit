#!/usr/bin/env bash
# Mysterium Toolkit — install a Mysterium node release from GitHub.
#
# Why this exists: myst-updater only installs packages that come from the
# Mysterium PPA. That PPA trails the GitHub tags by a long way, has no suite for
# Debian, and refuses to touch a node whose .deb was installed by hand. On a node
# installed that way the timer runs every six hours and achieves nothing. This is
# the deliberate override for that situation.
#
# Called as: sudo bin/node_update.sh <version>
# The caller passes a version number and nothing else. No URL, no path, no file
# name — everything else is derived here, so a compromised dashboard cannot point
# this at an arbitrary package.
#
# Output is one JSON object on stdout so the backend does not have to scrape text.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLKIT_DIR="$(dirname "$SCRIPT_DIR")"
WORK_DIR="$TOOLKIT_DIR/.node-update"

VERSION="${1:-}"
STAGE="start"

# Single exit path so every failure reports the stage it died at, rather than
# disappearing into an empty response.
fail() {
  printf '{"ok":false,"stage":"%s","error":"%s"}\n' "$STAGE" "${1//\"/\'}"
  cleanup
  exit 1
}

cleanup() {
  [ -n "${DEB_FILE:-}" ] && [ -f "$DEB_FILE" ] && rm -f "$DEB_FILE"
  [ -d "$WORK_DIR" ] && rmdir "$WORK_DIR" 2>/dev/null
  return 0
}

# ── Validate the one argument we accept ───────────────────────────────────────
STAGE="validate"
[ -n "$VERSION" ] || fail "no version given"
if ! printf '%s' "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  fail "version must look like 1.39.3"
fi

# The distribution name is deliberately never checked. The official install.sh
# reads ID from /etc/os-release and calls anything it does not recognise
# unsupported — which is why Parrot (ID=parrot), Kali and Mint fall over there
# despite being Debian underneath. It has to know the name because it adds an APT
# suite. This script adds no repository, so dpkg is the only thing that matters.
command -v curl >/dev/null 2>&1 || fail "curl is not installed"
command -v sha256sum >/dev/null 2>&1 || fail "sha256sum is not installed"
if ! command -v dpkg >/dev/null 2>&1; then
  fail "this system has no dpkg, so the .deb cannot be installed here — the release also ships myst_linux_<arch>.tar.gz, which needs a different install path than this script provides"
fi

# ── Architecture ──────────────────────────────────────────────────────────────
STAGE="arch"
MACHINE="$(uname -m)"
case "$MACHINE" in
  x86_64)  ARCH="amd64"  ;;
  aarch64|arm64) ARCH="arm64" ;;
  armv7l)  ARCH="armhf"  ;;
  armv6l)  ARCH="armv6l" ;;
  *) fail "unsupported architecture $MACHINE" ;;
esac
ASSET="myst_linux_${ARCH}.deb"

# ── Release metadata, including the checksum GitHub publishes per asset ───────
STAGE="metadata"
API="https://api.github.com/repos/mysteriumnetwork/node/releases/tags/${VERSION}"
META="$(curl -fsSL --max-time 30 -H 'User-Agent: mysterium-toolkit' "$API" 2>/dev/null)" \
  || fail "could not reach the GitHub release API"

# python3 is a hard dependency of the toolkit itself, so parsing here is safe.
read -r DEB_URL DIGEST SIZE <<< "$(printf '%s' "$META" | python3 -c "
import json, sys
try:
    data = json.loads(sys.stdin.read(), strict=False)
except Exception:
    print('- - -'); sys.exit()
for asset in data.get('assets', []):
    if asset.get('name') == '${ASSET}':
        print(asset.get('browser_download_url', '-'),
              (asset.get('digest') or '-'),
              asset.get('size', '-'))
        break
else:
    print('- - -')
" 2>/dev/null)"

[ "${DEB_URL:-}" != "-" ] && [ -n "${DEB_URL:-}" ] || fail "release $VERSION has no $ASSET"

# The URL comes from GitHub, but it is still checked against the only prefix this
# script will ever download from. A redirect or a tampered response cannot make
# this fetch something else.
EXPECTED_PREFIX="https://github.com/mysteriumnetwork/node/releases/download/${VERSION}/"
case "$DEB_URL" in
  "${EXPECTED_PREFIX}"*) : ;;
  *) fail "asset url is not a mysteriumnetwork/node release download" ;;
esac

# ── Download ──────────────────────────────────────────────────────────────────
# Not /tmp: the toolkit keeps its working files under its own directory.
STAGE="download"
mkdir -p "$WORK_DIR" || fail "could not create $WORK_DIR"
chmod 700 "$WORK_DIR"
DEB_FILE="$WORK_DIR/$ASSET"
curl -fsSL --max-time 300 "$DEB_URL" -o "$DEB_FILE" || fail "download failed"
[ -s "$DEB_FILE" ] || fail "downloaded file is empty"

# ── Verify before touching dpkg ───────────────────────────────────────────────
STAGE="verify"
if [ "${DIGEST:-}" != "-" ] && [ -n "${DIGEST:-}" ]; then
  EXPECTED="${DIGEST#sha256:}"
  ACTUAL="$(sha256sum "$DEB_FILE" | awk '{print $1}')"
  if [ "$EXPECTED" != "$ACTUAL" ]; then
    fail "checksum mismatch — expected ${EXPECTED:0:16}… got ${ACTUAL:0:16}…"
  fi
  VERIFIED="sha256"
else
  # GitHub has published a digest per asset since 2025, but an older release may
  # not carry one. Say so rather than pretending the download was verified.
  VERIFIED="https-only"
fi

# ── Install ───────────────────────────────────────────────────────────────────
STAGE="install"
INSTALL_OUT="$(dpkg -i "$DEB_FILE" 2>&1)"
DPKG_RC=$?
if [ $DPKG_RC -ne 0 ]; then
  # Missing dependencies are the normal reason dpkg -i fails, and apt fixes them.
  apt-get install -f -y >/dev/null 2>&1
  INSTALLED_NOW="$(dpkg-query -W -f='${Version}' myst 2>/dev/null)"
  case "$INSTALLED_NOW" in
    "$VERSION"*) : ;;
    *) fail "dpkg failed: $(printf '%s' "$INSTALL_OUT" | tail -1)" ;;
  esac
fi

# ── Restart the node ──────────────────────────────────────────────────────────
# stop + start, never `systemctl restart`.
STAGE="restart"
systemctl stop mysterium-node >/dev/null 2>&1
sleep 2
systemctl start mysterium-node >/dev/null 2>&1
sleep 3
NODE_ACTIVE="$(systemctl is-active mysterium-node 2>/dev/null)"

# ── Report ────────────────────────────────────────────────────────────────────
STAGE="done"
INSTALLED="$(dpkg-query -W -f='${Version}' myst 2>/dev/null)"
cleanup

# A node that did not come back up is not a success, whatever dpkg said. The
# backend reads the JSON, so the verdict has to be in the JSON and not only in
# the exit code.
if [ "$NODE_ACTIVE" = "active" ]; then OK="true"; else OK="false"; fi

printf '{"ok":%s,"stage":"done","installed":"%s","requested":"%s","arch":"%s","verified":"%s","node_active":"%s"}\n' \
  "$OK" "$INSTALLED" "$VERSION" "$ARCH" "$VERIFIED" "$NODE_ACTIVE"

[ "$OK" = "true" ] || exit 2
exit 0
