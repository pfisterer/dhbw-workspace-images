#!/bin/sh
# Claude Code on first use (/usr/local/bin/claude, see the Dockerfile): fetches the release pinned in the image from npm into the person's ~/.cache, checks its SHA-256 and runs it from there. Anthropic's software is fetched by the person who runs it and not shipped in the image (its terms do not allow redistribution). Gateway, key and models come from the server's ANTHROPIC_* variables, which the AI service's JupyterHub sets with the project's LLM key; ~/.claude/settings.json still wins over them.
set -eu
VERSION="@VERSION@"
case "$(uname -m)" in
  x86_64) ARCH=x64; SHA="@SHA_AMD64@" ;;
  aarch64|arm64) ARCH=arm64; SHA="@SHA_ARM64@" ;;
  *) echo "claude: kein Build für $(uname -m)" >&2; exit 1 ;;
esac
BASE="${XDG_CACHE_HOME:-$HOME/.cache}/dhbw-claude-code"
DIR="$BASE/$VERSION-$ARCH"
if [ ! -x "$DIR/claude" ]; then
  echo "Claude Code $VERSION wird einmalig heruntergeladen (etwa 130 MB) …" >&2
  TMP="$(mktemp -d)"
  curl -fsSL -o "$TMP/c.tgz" "https://registry.npmjs.org/@anthropic-ai/claude-code-linux-$ARCH/-/claude-code-linux-$ARCH-$VERSION.tgz"
  if ! echo "$SHA  $TMP/c.tgz" | sha256sum -c - >/dev/null 2>&1; then
    rm -rf "$TMP"
    echo "claude: Prüfsumme des Downloads stimmt nicht, abgebrochen" >&2
    exit 1
  fi
  tar -xzf "$TMP/c.tgz" -C "$TMP" package/claude
  mkdir -p "$DIR"
  chmod 755 "$TMP/package/claude"
  mv "$TMP/package/claude" "$DIR/claude"
  rm -rf "$TMP"
  # Versions of earlier images go: about 280 MB each in the home.
  for d in "$BASE"/*; do
    [ "$d" = "$DIR" ] || rm -rf "$d"
  done
fi
# A person's own Claude subscription: after /login its credentials are in ~/.claude/.credentials.json, and the gateway's variables would override them (ANTHROPIC_AUTH_TOKEN before the login, our model names unknown at Anthropic), so they go. DHBW_CLAUDE=abo starts without them for the first /login; /logout deletes the credentials and returns to the DHBW models. The login is per project, like the home it lives in.
if [ "${DHBW_CLAUDE:-}" = "abo" ] || [ -s "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/.credentials.json" ]; then
  unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL CLAUDE_CODE_SUBAGENT_MODEL CLAUDE_CODE_MAX_CONTEXT_TOKENS CLAUDE_CODE_MAX_OUTPUT_TOKENS CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS
fi
exec "$DIR/claude" "$@"
