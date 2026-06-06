#!/bin/bash
# =============================================================================
# FFBB MCP Server - Bash Helpers
# Based on: antigravity-awesome-skills bash-linux
# =============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging helpers
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# =============================================================================
# Project Helpers
# =============================================================================

# Get project version
get_version() {
    .venv/bin/python -c "from ffbb_mcp import __version__; print(__version__)"
}

# Run tests with coverage
run_tests() {
    .venv/bin/python -m pytest -q --cov=src --cov-report=term-missing "$@"
}

# Run linting
run_lint() {
    .venv/bin/python -m ruff check src/ "$@"
}

# Run formatting check
run_format_check() {
    .venv/bin/python -m ruff format --check src/ "$@"
}

# Run type check
run_typecheck() {
    .venv/bin/python -m mypy src/ --ignore-missing-imports "$@"
}

# Run all quality checks
run_quality() {
    log_step "Running all quality checks..."
    run_lint && log_info "Lint: OK" || log_error "Lint: FAILED"
    run_format_check && log_info "Format: OK" || log_error "Format: FAILED"
    run_typecheck && log_info "Typecheck: OK" || log_error "Typecheck: FAILED"
}

# Run graph health check
run_graph_health() {
    .venv/bin/python tools/check_graph_health.py "$@"
}

# Update AGENTS.md
update_agents_md() {
    .venv/bin/python tools/update_agents_md.py
    git diff --exit-code AGENTS.md || log_warn "AGENTS.md needs commit"
}

# =============================================================================
# Git Helpers
# =============================================================================

# Get current branch
current_branch() {
    git rev-parse --abbrev-ref HEAD
}

# Check if working directory is clean
is_clean() {
    [ -z "$(git status --porcelain)" ]
}

# Get last commit hash
last_commit() {
    git rev-parse --short HEAD
}

# Safe push with checks
safe_push() {
    if ! is_clean; then
        log_error "Working directory is not clean. Commit or stash changes first."
        return 1
    fi

    log_info "Pushing to origin $(current_branch)..."
    git push origin "$(current_branch)"
}

# =============================================================================
# Process Helpers
# =============================================================================

# Check if a port is in use
port_in_use() {
    lsof -i :"$1" >/dev/null 2>&1
}

# Kill process on port
kill_port() {
    if port_in_use "$1"; then
        log_info "Killing process on port $1..."
        kill -9 $(lsof -t -i :"$1") 2>/dev/null || true
    fi
}

# Wait for port to be available
wait_for_port() {
    local port=$1
    local timeout=${2:-30}
    local elapsed=0

    while port_in_use "$port"; do
        if [ $elapsed -ge $timeout ]; then
            log_error "Timeout waiting for port $port"
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    log_info "Port $port is available"
}

# =============================================================================
# File Helpers
# =============================================================================

# Find files by pattern
find_files() {
    find . -name "$1" -type f 2>/dev/null
}

# Count lines in Python files
count_python_lines() {
    find src -name "*.py" -exec cat {} + | wc -l
}

# Show disk usage
show_disk_usage() {
    du -sh src/ tests/ .venv/ 2>/dev/null
}

# =============================================================================
# Network Helpers
# =============================================================================

# Check if URL is reachable
check_url() {
    curl -s --head --fail "$1" >/dev/null 2>&1
}

# Test API endpoint
test_api() {
    local url=${1:-"http://localhost:9123/health"}
    curl -s "$url" | .venv/bin/python -m json.tool 2>/dev/null || curl -s "$url"
}

# =============================================================================
# Cleanup Helpers
# =============================================================================

# Clean Python cache
clean_cache() {
    log_info "Cleaning Python cache..."
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    log_info "Cache cleaned."
}

# Clean test artifacts
clean_test_artifacts() {
    log_info "Cleaning test artifacts..."
    rm -rf .pytest_cache/ htmlcov/ coverage.xml .coverage 2>/dev/null || true
    log_info "Test artifacts cleaned."
}

# Clean all
clean_all() {
    clean_cache
    clean_test_artifacts
    log_info "All artifacts cleaned."
}

# =============================================================================
# Usage
# =============================================================================
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "FFBB MCP Server - Bash Helpers"
    echo ""
    echo "Usage: source tools/helpers.sh"
    echo ""
    echo "Available functions:"
    echo "  Project: get_version, run_tests, run_lint, run_format_check, run_typecheck, run_quality, run_graph_health, update_agents_md"
    echo "  Git:     current_branch, is_clean, last_commit, safe_push"
    echo "  Process: port_in_use, kill_port, wait_for_port"
    echo "  File:    find_files, count_python_lines, show_disk_usage"
    echo "  Network: check_url, test_api"
    echo "  Clean:   clean_cache, clean_test_artifacts, clean_all"
fi
