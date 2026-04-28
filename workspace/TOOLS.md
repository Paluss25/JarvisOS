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

## daily_log Tag Conventions

Use these tags consistently when calling `daily_log` so logs are machine-filterable in Loki/Grafana.

| Tag | When to use |
|-----|-------------|
| `[INCIDENT]` | Unrecoverable error, service down, anomaly requiring attention |
| `[INFRA EVENT]` | Infrastructure change or alert (restart, deploy, config change) |
| `[STRATEGIC DECISION]` | High-impact decision made on behalf of the user |
| `[ROUTING EVENT]` | Email or task routed to another agent |
| `[FINANCIAL EVENT]` | Financial operation recorded or anomaly detected |
| `[SPORT EVENT]` | Sport/fitness activity logged |
| `[MEDICAL GATE]` | Health check gate evaluated |
| `[EMAIL EXTRACTION]` | Email classified and extracted |
