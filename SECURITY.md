# Security Policy

## Reporting a Vulnerability

The Hermes MCP Guard project takes security seriously. If you discover a security vulnerability, please **do not** open a public GitHub issue.

### Preferred Reporting Channels

1. **GitHub Private Advisory**: Open a [private security advisory](https://github.com/aguo17/hermes-mcp-guard/security/advisories/new) on the repository.
2. **Email**: Send details to the repository owner via the GitHub profile contact.

### What to Include

- A clear description of the vulnerability
- Steps to reproduce (if possible)
- Affected versions
- Any potential mitigations you've identified

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 5 business days
- **Patch Release**: Depends on severity; critical fixes prioritized for immediate release

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | ✅ Active support  |

## Scope

This policy covers:

- The `hermes_mcp.py` MCP server
- The `hermes_guard.sh` CLI bridge
- The `core/hermes_guard.py` engine
- The `core/pitfalls.json` antibody database

## Out of Scope

- Issues requiring root/sudo access (the tool explicitly warns against this)
- Social engineering attacks against users
- Third-party MCP client vulnerabilities

---

Thank you for helping keep the community safe. 🛡️
