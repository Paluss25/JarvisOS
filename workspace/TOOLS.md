# TOOLS.md — Tool Conventions

## Permission Matrix

### Free (no approval needed)
- Web search, file reading, docker inspect/ps/logs, git status/log/diff

### Requires confirmation
- File write/delete, docker run/stop/rm, git push/merge, sudo, package installs

## Tool Notes
- **Perplexity:** Pro tier. Key in PERPLEXITY_API_KEY.
- **GitHub:** Full push. Token in GITHUB_TOKEN.
- **Python/Bash:** Log all executions to daily memory.
- **Docker:** Socket mounted. Destructive ops need approval.

## MCP Servers
- Registry: config/mcp-servers.json. Hot-reload on edit.
