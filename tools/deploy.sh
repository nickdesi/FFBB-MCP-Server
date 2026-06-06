#!/bin/bash
set -euo pipefail

# =============================================================================
# FFBB MCP Server - Deployment Script
# Based on: antigravity-awesome-skills deployment-procedures
# =============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Logging
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# =============================================================================
# Phase 1: PREPARE
# =============================================================================
prepare() {
    log_step "Phase 1: PREPARE"
    cd "$PROJECT_DIR"

    # Check tests
    log_info "Running tests..."
    if ! .venv/bin/python -m pytest -q --tb=short; then
        log_error "Tests failed. Aborting deployment."
        exit 1
    fi

    # Check linting
    log_info "Running ruff check..."
    if ! .venv/bin/python -m ruff check src/; then
        log_error "Linting failed. Aborting deployment."
        exit 1
    fi

    # Check type check
    log_info "Running mypy..."
    if ! .venv/bin/python -m mypy src/ --ignore-missing-imports; then
        log_error "Type check failed. Aborting deployment."
        exit 1
    fi

    # Check graph health
    log_info "Running graph health check..."
    if ! .venv/bin/python tools/check_graph_health.py; then
        log_warn "Graph health check failed (non-blocking)."
    fi

    log_info "Pre-deployment checks passed."
}

# =============================================================================
# Phase 2: BACKUP
# =============================================================================
backup() {
    log_step "Phase 2: BACKUP"

    # Get current version
    CURRENT_VERSION=$(.venv/bin/python -c "from ffbb_mcp import __version__; print(__version__)" 2>/dev/null || echo "unknown")
    log_info "Current version: $CURRENT_VERSION"

    # Save git state
    git rev-parse HEAD > ".last-deploy-commit"
    log_info "Current commit saved: $(cat .last-deploy-commit)"

    # Tag current version
    if [ "$CURRENT_VERSION" != "unknown" ]; then
        log_info "Current version tag: v$CURRENT_VERSION"
    fi
}

# =============================================================================
# Phase 3: DEPLOY
# =============================================================================
deploy() {
    log_step "Phase 3: DEPLOY"

    # Push to remote
    log_info "Pushing to remote..."
    git push origin main

    # Push tags if any
    if git describe --tags --abbrev=0 2>/dev/null; then
        log_info "Pushing tags..."
        git push --tags
    fi

    log_info "Deployment pushed successfully."
}

# =============================================================================
# Phase 4: VERIFY
# =============================================================================
verify() {
    log_step "Phase 4: VERIFY"

    # Wait for GitHub Actions
    log_info "Waiting for CI to start..."
    sleep 10

    # Check if there are any new commits
    git fetch origin
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)

    if [ "$LOCAL" = "$REMOTE" ]; then
        log_info "Local and remote are in sync."
    else
        log_warn "Local and remote are out of sync."
    fi
}

# =============================================================================
# Phase 5: CONFIRM
# =============================================================================
confirm() {
    log_step "Phase 5: CONFIRM"
    log_info "Deployment completed successfully!"
    log_info "Monitor GitHub Actions: https://github.com/nickdesi/FFBB-MCP-Server/actions"
}

# =============================================================================
# ROLLBACK
# =============================================================================
rollback() {
    log_step "ROLLBACK"

    if [ -f ".last-deploy-commit" ]; then
        PREV_COMMIT=$(cat .last-deploy-commit)
        log_warn "Rolling back to commit: $PREV_COMMIT"

        git checkout "$PREV_COMMIT"
        git push origin main --force
        rm -f ".last-deploy-commit"

        log_info "Rollback completed."
    else
        log_error "No backup commit found. Manual rollback required."
        exit 1
    fi
}

# =============================================================================
# MAIN
# =============================================================================
main() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  FFBB MCP Server Deployment Script${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""

    case "${1:-deploy}" in
        prepare)
            prepare
            ;;
        backup)
            backup
            ;;
        deploy)
            prepare
            backup
            deploy
            verify
            confirm
            ;;
        verify)
            verify
            ;;
        rollback)
            rollback
            ;;
        *)
            echo "Usage: $0 {prepare|backup|deploy|verify|rollback}"
            exit 1
            ;;
    esac
}

main "$@"
