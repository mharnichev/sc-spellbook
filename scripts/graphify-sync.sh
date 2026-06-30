#!/usr/bin/env bash
set -euo pipefail

SC_ROOT="${SC_ROOT:-/Users/markgarnicev/sc}"
GRAPHIFY_BIN="${GRAPHIFY_BIN:-}"

if [[ -z "$GRAPHIFY_BIN" ]]; then
  for candidate in \
    "$HOME/.local/bin/graphify" \
    "$HOME/.local/share/uv/tools/graphifyy/bin/graphify" \
    graphify
  do
    if [[ -x "$candidate" ]]; then
      GRAPHIFY_BIN="$candidate"
      break
    fi
    if command -v "$candidate" >/dev/null 2>&1; then
      GRAPHIFY_BIN="$(command -v "$candidate")"
      break
    fi
  done
fi

if [[ -z "$GRAPHIFY_BIN" ]]; then
  echo "graphify not found. Install it with: uv tool install 'graphifyy[all]'" >&2
  exit 1
fi

repos=(sc-fe sc-be sc-spellbook)
command_name="${1:-update}"

repo_path() {
  printf '%s/%s' "$SC_ROOT" "$1"
}

ensure_repo() {
  local repo="$1"
  local path
  path="$(repo_path "$repo")"
  if [[ ! -d "$path" ]]; then
    echo "missing repo: $path" >&2
    exit 1
  fi
}

update_repo() {
  local repo="$1"
  local path
  path="$(repo_path "$repo")"
  echo "==> graphify update: $repo"
  "$GRAPHIFY_BIN" update "$path"
}

export_repo() {
  local repo="$1"
  local path
  path="$(repo_path "$repo")"
  local graph="$path/graphify-out/graph.json"
  if [[ ! -f "$graph" ]]; then
    echo "skip export for $repo: graph not found at $graph" >&2
    return 1
  fi
  echo "==> graphify exports: $repo"
  "$GRAPHIFY_BIN" export obsidian \
    --graph "$graph" \
    --dir "$path/graphify-out/obsidian"
  "$GRAPHIFY_BIN" export html --graph "$graph"
  "$GRAPHIFY_BIN" export callflow-html "$graph" \
    --output "$path/graphify-out/${repo}-callflow.html"
}

add_global_repo() {
  local repo="$1"
  local path
  path="$(repo_path "$repo")"
  local graph="$path/graphify-out/graph.json"
  if [[ -f "$graph" ]]; then
    echo "==> graphify global add: $repo"
    "$GRAPHIFY_BIN" global add "$graph" --as "$repo"
  fi
}

install_repo() {
  local repo="$1"
  local path
  path="$(repo_path "$repo")"
  echo "==> graphify codex install --project: $repo"
  (cd "$path" && "$GRAPHIFY_BIN" codex install --project)
}

install_hooks_repo() {
  local repo="$1"
  local path
  path="$(repo_path "$repo")"
  echo "==> graphify hook install: $repo"
  (cd "$path" && "$GRAPHIFY_BIN" hook install)
}

hook_status_repo() {
  local repo="$1"
  local path
  path="$(repo_path "$repo")"
  echo "==> graphify hook status: $repo"
  (cd "$path" && "$GRAPHIFY_BIN" hook status)
}

case "$command_name" in
  install)
    for repo in "${repos[@]}"; do
      ensure_repo "$repo"
      install_repo "$repo"
    done
    ;;
  auto|install-hooks)
    for repo in "${repos[@]}"; do
      ensure_repo "$repo"
      install_repo "$repo"
      install_hooks_repo "$repo"
    done
    ;;
  update)
    for repo in "${repos[@]}"; do
      ensure_repo "$repo"
      update_repo "$repo"
      export_repo "$repo"
      add_global_repo "$repo"
    done
    "$GRAPHIFY_BIN" global list || true
    ;;
  release)
    for repo in "${repos[@]}"; do
      ensure_repo "$repo"
      update_repo "$repo"
      export_repo "$repo"
      add_global_repo "$repo"
    done
    echo "Global graph: $("$GRAPHIFY_BIN" global path)"
    ;;
  status)
    for repo in "${repos[@]}"; do
      path="$(repo_path "$repo")"
      graph="$path/graphify-out/graph.json"
      if [[ -f "$graph" ]]; then
        printf '%s: %s\n' "$repo" "$graph"
      else
        printf '%s: no graph yet\n' "$repo"
      fi
    done
    "$GRAPHIFY_BIN" global list || true
    for repo in "${repos[@]}"; do
      hook_status_repo "$repo"
    done
    ;;
  *)
    echo "Usage: $0 [install|auto|install-hooks|update|release|status]" >&2
    exit 2
    ;;
esac
