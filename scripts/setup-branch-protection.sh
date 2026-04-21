#!/usr/bin/env bash
# setup-branch-protection.sh
# Run once to configure GitHub branch protection and labels for the PR workflow.
# Requires: gh CLI authenticated as a repo admin.
#
# Usage: bash scripts/setup-branch-protection.sh

set -euo pipefail

REPO="${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
BRANCH="main"

echo "Configuring branch protection for $REPO/$BRANCH ..."

gh api "repos/$REPO/branches/$BRANCH/protection" \
  --method PUT \
  --header "Accept: application/vnd.github+json" \
  --field "required_status_checks[strict]=true" \
  --field "required_status_checks[contexts][]=lint" \
  --field "required_status_checks[contexts][]=type-check" \
  --field "required_status_checks[contexts][]=test (3.10)" \
  --field "required_status_checks[contexts][]=test (3.11)" \
  --field "required_status_checks[contexts][]=test (3.12)" \
  --field "required_status_checks[contexts][]=test (3.13)" \
  --field "required_status_checks[contexts][]=docker" \
  --field "required_pull_request_reviews[required_approving_review_count]=1" \
  --field "required_pull_request_reviews[require_code_owner_reviews]=true" \
  --field "required_pull_request_reviews[dismiss_stale_reviews]=true" \
  --field "enforce_admins=false" \
  --field "restrictions=null" \
  --field "allow_force_pushes=false" \
  --field "allow_deletions=false"

echo "Branch protection applied."
echo ""
echo "Creating PR labels ..."

create_label() {
  local name="$1" color="$2" description="$3"
  gh label create "$name" --color "$color" --description "$description" --force 2>/dev/null || true
}

create_label "feature"       "0075ca" "New feature or capability"
create_label "bug"           "d73a4a" "Something is broken"
create_label "adapter"       "e4e669" "New CCTV system adapter"
create_label "documentation" "0075ca" "Documentation only"
create_label "refactor"      "cfd3d7" "Code refactor, no behavior change"
create_label "testing"       "bfd4f2" "Tests only"
create_label "chore"         "fef2c0" "Maintenance, deps, CI"
create_label "needs-changes" "e99695" "Reviewer requested changes"
create_label "ready-to-merge" "0e8a16" "Approved and ready to merge"

echo "Labels created."
echo ""
echo "Done. PR approval flow:"
echo "  1. Contributor opens PR against main"
echo "  2. pr-checks: validates template, adds label, warns on large PRs"
echo "  3. CI: lint / type-check / tests / docker"
echo "  4. auto-approve: bot approves when all CI jobs pass"
echo "  5. You (@arunrajiah) do the final review and merge"
