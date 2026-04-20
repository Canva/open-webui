#!/usr/bin/env bash
# Block git push and gh pr create commands that target non-Canva remotes.
set -euo pipefail

input=$(cat)
command=$(echo "$input" | jq -r '.command // empty')

is_canva_url() {
  echo "$1" | grep -qi 'github\.com[:/]Canva/'
}

# Check git push: resolve the remote URL being pushed to
if echo "$command" | grep -qE 'git[[:space:]]+push'; then
  # Extract the first non-flag argument after "git push" as the remote name
  remote=$(echo "$command" | sed -E 's/.*git[[:space:]]+push[[:space:]]+(-[^ ]+[[:space:]]+)*//' | awk '{print $1}')
  remote="${remote:-origin}"
  url=$(git remote get-url "$remote" 2>/dev/null || echo "")

  if [ -n "$url" ] && ! is_canva_url "$url"; then
    echo "{
      \"permission\": \"deny\",
      \"user_message\": \"Blocked: git push targets non-Canva remote '$remote' ($url). Only pushes to github.com/Canva/* are allowed.\",
      \"agent_message\": \"The pre-push guard blocked this command because the remote '$remote' does not point to a Canva org repository.\"
    }"
    exit 0
  fi
fi

# Check gh pr create: ensure --repo targets Canva or default repo is Canva
if echo "$command" | grep -qE 'gh[[:space:]]+pr[[:space:]]+create'; then
  if echo "$command" | grep -qE '\-\-repo[[:space:]]+'; then
    repo=$(echo "$command" | sed -E 's/.*--repo[[:space:]]+//' | awk '{print $1}')
    if ! echo "$repo" | grep -qi '^Canva/'; then
      echo "{
        \"permission\": \"deny\",
        \"user_message\": \"Blocked: gh pr create targets non-Canva repo '$repo'. Use --repo Canva/<name>.\",
        \"agent_message\": \"The guard blocked this gh pr create because --repo '$repo' is not in the Canva org.\"
      }"
      exit 0
    fi
  else
    default_repo=$(gh repo set-default --view 2>/dev/null || echo "")
    if [ -n "$default_repo" ] && ! echo "$default_repo" | grep -qi 'Canva/'; then
      echo "{
        \"permission\": \"deny\",
        \"user_message\": \"Blocked: gh pr create would target non-Canva default repo ($default_repo). Use --repo Canva/<name>.\",
        \"agent_message\": \"The guard blocked this gh pr create because the default repo is not in the Canva org.\"
      }"
      exit 0
    fi
  fi
fi

echo '{ "permission": "allow" }'
exit 0
