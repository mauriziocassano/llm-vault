#!/usr/bin/env bash
# init-vault.sh — Bootstrap a second brain vault (v4).
#
# Usage:
#   ./init-vault.sh                         # creates ./second-brain-vault
#   ./init-vault.sh /path/to/vault          # explicit path
#   ./init-vault.sh --here                  # use current directory
#   ./init-vault.sh --help
#
# What it does:
#   1. Creates folder structure (raw/, wiki/pages/, wiki/views/, ...)
#   2. Installs the two skills (inbox-fetcher, vault-linter, view-builder)
#   3. Installs four slash commands (/save, /view, /reflect, /forget)
#   4. Writes CLAUDE.md, inbox.md, wiki/{hot,index,log}.md
#   5. Creates AGENTS.md as a symlink to CLAUDE.md
#   6. Optionally: git init, checks Python dependencies
#
# Idempotent: safe to re-run. Asks before overwriting CLAUDE.md.

set -euo pipefail

# --- Colors ----------------------------------------------------------------
if [ -t 1 ]; then
    C_BOLD=$(tput bold 2>/dev/null || echo "")
    C_DIM=$(tput dim 2>/dev/null || echo "")
    C_GREEN=$(tput setaf 2 2>/dev/null || echo "")
    C_YELLOW=$(tput setaf 3 2>/dev/null || echo "")
    C_BLUE=$(tput setaf 4 2>/dev/null || echo "")
    C_RED=$(tput setaf 1 2>/dev/null || echo "")
    C_RESET=$(tput sgr0 2>/dev/null || echo "")
else
    C_BOLD="" C_DIM="" C_GREEN="" C_YELLOW="" C_BLUE="" C_RED="" C_RESET=""
fi

info() { echo "${C_BLUE}==>${C_RESET} $*"; }
ok()   { echo "${C_GREEN}  ✓${C_RESET} $*"; }
skip() { echo "${C_DIM}  ·${C_RESET} $*"; }
warn() { echo "${C_YELLOW}  ⚠${C_RESET} $*"; }
err()  { echo "${C_RED}  ✗${C_RESET} $*" >&2; }

usage() {
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

# --- Arg parsing -----------------------------------------------------------
VAULT_DIR=""
USE_CWD=0

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage ;;
        --here)    USE_CWD=1; shift ;;
        -*)        err "Unknown option: $1"; exit 1 ;;
        *)         VAULT_DIR="$1"; shift ;;
    esac
done

if [ "$USE_CWD" -eq 1 ]; then
    VAULT_DIR="$(pwd)"
elif [ -z "$VAULT_DIR" ]; then
    VAULT_DIR="./second-brain-vault"
fi

mkdir -p "$VAULT_DIR"
VAULT_DIR="$(cd "$VAULT_DIR" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo
echo "${C_BOLD}Second Brain Vault — init (v4)${C_RESET}"
echo "${C_DIM}target: $VAULT_DIR${C_RESET}"
echo

# --- Safety check ----------------------------------------------------------
OVERWRITE_CLAUDE=1
if [ -f "$VAULT_DIR/CLAUDE.md" ]; then
    warn "CLAUDE.md already exists"
    read -r -p "  Overwrite? [y/N] " ans
    case "$ans" in
        [yY]*) OVERWRITE_CLAUDE=1 ;;
        *)     OVERWRITE_CLAUDE=0; skip "keeping existing CLAUDE.md" ;;
    esac
fi

# --- Folder structure ------------------------------------------------------
info "Creating folder structure"
DIRS=(
    "raw/papers"
    "raw/web"
    "wiki/pages"
    "wiki/sources"
    "wiki/views/assets"
    "conversations"
    ".lint"
    ".claude/skills/inbox-fetcher/scripts"
    ".claude/skills/vault-linter/scripts"
    ".claude/skills/view-builder/templates"
    ".claude/commands"
)
for d in "${DIRS[@]}"; do
    mkdir -p "$VAULT_DIR/$d"
done

for d in raw/papers raw/web wiki/pages wiki/sources wiki/views wiki/views/assets conversations .lint; do
    [ -f "$VAULT_DIR/$d/.gitkeep" ] || touch "$VAULT_DIR/$d/.gitkeep"
done
ok "directories"

# --- CLAUDE.md -------------------------------------------------------------
info "Installing CLAUDE.md"
if [ "$OVERWRITE_CLAUDE" -eq 1 ]; then
    cp "$SCRIPT_DIR/CLAUDE.md" "$VAULT_DIR/CLAUDE.md"
    ok "CLAUDE.md"
fi

# AGENTS.md as symlink (some CLIs look for this name)
if [ ! -e "$VAULT_DIR/AGENTS.md" ]; then
    (cd "$VAULT_DIR" && ln -s CLAUDE.md AGENTS.md)
    ok "AGENTS.md → CLAUDE.md (symlink)"
fi

# --- Base files ------------------------------------------------------------
info "Writing base files"

if [ ! -f "$VAULT_DIR/inbox.md" ]; then
    cat > "$VAULT_DIR/inbox.md" <<'EOF'
# Inbox

URLs to process. The `inbox-fetcher` skill reads this file and pulls
the URLs into `raw/web/`. Check items after fetching.

## To process

<!-- Add URLs here as a task list:
- [ ] https://example.com/article
- [ ] https://arxiv.org/abs/2024.12345
-->

## Done

<!-- Automatically moved here after fetch. -->
EOF
    ok "inbox.md"
else
    skip "inbox.md (exists)"
fi

if [ ! -f "$VAULT_DIR/wiki/index.md" ]; then
    cat > "$VAULT_DIR/wiki/index.md" <<'EOF'
# Index

Catalog of the vault. Updated on every write operation.

## Pages

<!-- Will be populated as you ingest content. -->

## Sources

<!-- One entry per source. -->

## Views

<!-- Timelines, comparisons, slides, etc. -->
EOF
    ok "wiki/index.md"
else
    skip "wiki/index.md (exists)"
fi

if [ ! -f "$VAULT_DIR/wiki/log.md" ]; then
    cat > "$VAULT_DIR/wiki/log.md" <<'EOF'
# Log

Append-only log of vault operations.

Format: `## [YYYY-MM-DD] op | title`
EOF
    ok "wiki/log.md"
else
    skip "wiki/log.md (exists)"
fi

if [ ! -f "$VAULT_DIR/wiki/hot.md" ]; then
    cat > "$VAULT_DIR/wiki/hot.md" <<'EOF'
---
type: page
created: INIT
updated: INIT
tags: [hot-cache]
---

# Hot Cache

Short rolling memory of recent sessions. Rewritten at session end.
Read by the agent at session start.

## Recent sessions

<!-- Populated by /save and at session end. -->

## Open threads

<!-- Things left hanging. -->
EOF
    ok "wiki/hot.md"
else
    skip "wiki/hot.md (exists)"
fi

# .lint state
if [ ! -f "$VAULT_DIR/.lint/state.yaml" ]; then
    cat > "$VAULT_DIR/.lint/state.yaml" <<EOF
last_lint: null
ingests_since_last_lint: 0
last_exit_code: null
last_findings_count: 0
EOF
    ok ".lint/state.yaml"
fi

if [ ! -f "$VAULT_DIR/.lint/report.md" ]; then
    cat > "$VAULT_DIR/.lint/report.md" <<'EOF'
# Lint Report

No lint run yet. Run `python .claude/skills/vault-linter/scripts/lint.py`
from the vault root.
EOF
    ok ".lint/report.md"
fi

# .gitignore
if [ ! -f "$VAULT_DIR/.gitignore" ]; then
    cat > "$VAULT_DIR/.gitignore" <<'EOF'
# System
.DS_Store
Thumbs.db

# Editor
.vscode/
.idea/
*.swp

# Python
__pycache__/
*.pyc
.venv/
venv/

# Obsidian workspace (keep vault files, skip user-specific state)
.obsidian/workspace*
.obsidian/cache
EOF
    ok ".gitignore"
fi

# --- Skills ----------------------------------------------------------------
info "Installing skills"

# inbox-fetcher
if [ -d "$SCRIPT_DIR/skills/inbox-fetcher" ]; then
    cp "$SCRIPT_DIR/skills/inbox-fetcher/SKILL.md" \
       "$VAULT_DIR/.claude/skills/inbox-fetcher/SKILL.md"
    cp "$SCRIPT_DIR/skills/inbox-fetcher/scripts/fetch_inbox.py" \
       "$VAULT_DIR/.claude/skills/inbox-fetcher/scripts/fetch_inbox.py"
    chmod +x "$VAULT_DIR/.claude/skills/inbox-fetcher/scripts/fetch_inbox.py"
    ok "skill: inbox-fetcher"
else
    warn "inbox-fetcher skill not found in bundle"
fi

# vault-linter
if [ -d "$SCRIPT_DIR/skills/vault-linter" ]; then
    cp "$SCRIPT_DIR/skills/vault-linter/SKILL.md" \
       "$VAULT_DIR/.claude/skills/vault-linter/SKILL.md"
    cp "$SCRIPT_DIR/skills/vault-linter/scripts/lint.py" \
       "$VAULT_DIR/.claude/skills/vault-linter/scripts/lint.py"
    chmod +x "$VAULT_DIR/.claude/skills/vault-linter/scripts/lint.py"
    ok "skill: vault-linter"
else
    warn "vault-linter skill not found in bundle"
fi

# view-builder
if [ -d "$SCRIPT_DIR/skills/view-builder" ]; then
    cp "$SCRIPT_DIR/skills/view-builder/SKILL.md" \
       "$VAULT_DIR/.claude/skills/view-builder/SKILL.md"
    if [ -d "$SCRIPT_DIR/skills/view-builder/templates" ]; then
        cp "$SCRIPT_DIR/skills/view-builder/templates/"* \
           "$VAULT_DIR/.claude/skills/view-builder/templates/" 2>/dev/null || true
    fi
    ok "skill: view-builder"
else
    warn "view-builder skill not found in bundle"
fi

# --- Slash commands --------------------------------------------------------
info "Installing slash commands"
for cmd in save view reflect forget; do
    if [ -f "$SCRIPT_DIR/commands/$cmd.md" ]; then
        cp "$SCRIPT_DIR/commands/$cmd.md" \
           "$VAULT_DIR/.claude/commands/$cmd.md"
        ok "command: /$cmd"
    else
        warn "command $cmd not found in bundle"
    fi
done

# --- Optional: git init ----------------------------------------------------
info "Git"
if [ ! -d "$VAULT_DIR/.git" ]; then
    read -r -p "  Initialize a git repo? [Y/n] " ans
    case "$ans" in
        [nN]*) skip "no git" ;;
        *)
            (cd "$VAULT_DIR" && git init -q && git add -A && \
             git commit -q -m "initial vault bootstrap (v4)" 2>/dev/null || true)
            ok "git initialized"
            ;;
    esac
else
    skip "git repo already exists"
fi

# --- Python dependency check ----------------------------------------------
info "Checking Python dependencies"
if command -v python3 >/dev/null 2>&1; then
    ok "python3 found: $(python3 --version 2>&1)"
    missing=()
    for pkg in trafilatura requests slugify; do
        if ! python3 -c "import $pkg" 2>/dev/null; then
            missing+=("$pkg")
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        warn "missing Python packages (needed by inbox-fetcher): ${missing[*]}"
        echo "      install with: pip install trafilatura requests python-slugify"
    else
        ok "all Python dependencies installed"
    fi
else
    warn "python3 not found — inbox-fetcher and linter won't work"
fi

# --- Done ------------------------------------------------------------------
echo
echo "${C_BOLD}${C_GREEN}Vault ready!${C_RESET}"
echo
echo "  Path: $VAULT_DIR"
echo
echo "Next steps:"
echo "  1. cd $VAULT_DIR"
echo "  2. Add URLs to inbox.md (or drop PDFs in raw/papers/)"
echo "  3. Open Claude Code (or another CLI) in this folder"
echo "  4. Ask: \"process the inbox\", then \"ingest the new content\""
echo "  5. Use /view to build timelines/comparisons/slides"
echo "  6. Use /save for important conversations"
echo "  7. Periodically: /reflect → read wiki/compass.md"
echo
