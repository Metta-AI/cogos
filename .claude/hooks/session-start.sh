#!/bin/bash
branch=$(git branch --show-current 2> /dev/null)
if [ -n "$branch" ]; then
  echo "Branch: $branch"
  echo "Recent commits:"
  git log --oneline -3 2> /dev/null
  uncommitted=$(git status --short 2> /dev/null | wc -l | tr -d ' ')
  if [ "$uncommitted" -gt 0 ]; then
    echo "Uncommitted changes: $uncommitted files"
  fi
fi

plugins_file="$HOME/.claude/plugins/installed_plugins.json"
if ! grep -q '"pr-workflow@softmax-plugins"' "$plugins_file" 2>/dev/null; then
  echo ""
  echo "Missing shared plugins. Ask the user to run:"
  echo "  /plugin marketplace add Metta-AI/softmax-plugins"
  echo "  /plugin install pr-workflow@softmax-plugins"
fi

exit 0
