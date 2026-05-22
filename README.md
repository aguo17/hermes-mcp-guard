# 🛡️ Hermes MCP Guard

> **A Zero-Latency, Self-Healing System Guard Server for AI Agents.**

Hermes MCP Guard is a lightweight, high-performance security and management layer designed for AI Agents. It provides **Layer 1 static analysis**, automated **knowledge graph-based risk prediction**, and **self-healing capabilities** to protect your local system from dangerous shell operations, resource exhaustion, and common system-level errors.

By leveraging the **Model Context Protocol (MCP)**, Hermes seamlessly integrates with AI Agents to provide a standardized, secure, and robust interface for system operations.

---

## 🚀 Key Features

- **Zero-Latency "Shift-Left" Defense**: Uses static analysis to intercept dangerous commands (e.g., unauthorized `json.loads` calls, dangerous shell injections) at the Bash layer (Layer 1) *before* execution.
- **Knowledge Graph-based Pre-flight Checks**: Automatically predicts risks (e.g., Port conflicts, OOM threats) by matching current commands against a learned, local knowledge graph.
- **Self-Evolving Immune System**: When an error is resolved, the system records it as a new "antibody" in `pitfalls.json`, achieving *"once broken, always immune"* protection. Includes automatic de-duplication, 200-rule cap, and auto-pruning.
- **Standardized MCP Interface**: Communicates via the Model Context Protocol (MCP) using `stdio`. No network ports are opened, ensuring maximum security.
- **Zero-Token Overhead**: Risk checks are performed locally using Python and Bash, consuming **zero API tokens**.

---

## 🛠️ Quick Start

### 1. Installation

```bash
git clone https://github.com/aguo17/hermes-mcp-guard.git
cd hermes-mcp-guard
chmod +x ./setup.sh
./setup.sh
```

### 2. Configuration (Claude Desktop / Cursor / Hermes Agent)

Add the following to your MCP configuration file:

```json
{
  "mcpServers": {
    "hermes-guard": {
      "command": "python3",
      "args": ["/absolute/path/to/hermes-mcp-guard/hermes_mcp.py"]
    }
  }
}
```

---

## 🛡️ Included Tools

| Tool Name | Description |
|---|---|
| `execute_command` | Executes terminal commands within the Hermes protective shell (Linter → KG Preflight → Execute → Intercept → Auto-Fix). |
| `kill_resource` | Safely terminates unresponsive processes or releases occupied ports using 3-layer graceful degradation. |
| `register_new_antibody` | Teaches the system how to handle new error patterns automatically (with de-duplication and size limits). |
| `inspect_system_health` | Monitors hardware resource status (RAM, CPU, Disk, Load) before high-stakes operations. |
| `get_active_defense_rules` | Transparency panel — view all currently active antibodies for full user control. |
| `cleanup_all` | Environment cleanup — releases zombie processes, orphaned ports, and stale child processes. |

## 🐧 OS Kernel Watchdogs (Phase 1+2)

Beyond application-layer defense, Hermes includes **7 battle-tested watchdogs** that monitor the OS kernel and sensory layers — the "silent killers" that `df -h` and traditional monitoring miss:

```
core/watchdogs/
├── os_kernel_health.sh      # Phase 1: Kernel internals (inode, FS-ro, Zombie, FD, oops, entropy)
├── os_network_health.sh     # Phase 2: Gray failure detection (NIC/DNS/Journald via pure sysfs+glibc)
└── reflect_daily.sh         # Knowledge graph nightly reflection worker
```

| Layer | Watchdog | What It Catches | Probe Method |
|-------|----------|----------------|-------------|
| **Kernel** | `os_kernel_health.sh` | inode exhaustion, forced read-only FS, zombie overflow, kernel oops | `/proc`, `sysfs`, `dmesg` |
| **Sensory** | `os_network_health.sh` | NIC link down, DNS resolution failure, journald bloat | `/sys/class/net`, `getent`, `du -sm` |
| **Cognition** | `reflect_daily.sh` | Pattern extraction from evolution logs → knowledge graph | Regex-based, zero-token |

**Design philosophy**: *Silent unless alert*. All 7 watchdogs produce zero output on healthy systems, eliminating alert fatigue.

### 🧪 Chaos Engineering Validated

All Phase 2 watchdogs have passed three zero-risk chaos experiments:

| Test | Injection Method | Result |
|------|-----------------|--------|
| Phantom NIC | `ip link add eth-chaos type dummy` → set down | ✅ Detected as Link Down |
| Journal Bloat | `fallocate -l 2100M` (0.001s, zero write wear) | ✅ Detected >2GB |
| DNS Isolation | `unshare -n` (isolated network namespace) | ✅ 2s timeout, host unaffected |

---

## 🔒 Security Policy

- **Telemetry-Free**: This project does **not** collect, log, or transmit any user data or system logs to any external server.
- **Local Execution**: All operations are performed locally on your machine.
- **Principle of Least Privilege**: It is **strongly recommended** to run this tool as a standard user, never as `root`. Both `hermes_mcp.py` and `hermes_guard.sh` will warn or refuse root execution.
- **Vulnerability Reporting**: See [SECURITY.md](SECURITY.md) for how to report security issues privately.

> ⚠️ **Safety Notice**: This tool executes shell commands on your local machine. Please review `hermes_guard.sh` before running it to understand the permissions granted to your AI agents. This project is intended for **educational and technical experimentation**.

---

## 🔧 Troubleshooting

### PEP 668: externally-managed-environment

```
error: externally-managed-environment
```

Ubuntu's system protection blocks global `pip install`. Solutions (in priority order):

1. **Virtual environment (preferred)**: `python3 -m venv venv && source venv/bin/activate && pip install <package>`
2. **Module flag**: `python3 -m pip install <package>`
3. **Last resort**: `pip install --break-system-packages <package>`

### Port Conflict: Address already in use

```
OSError: [Errno 98] Address already in use
```

1. Check occupied port: `ss -tlnp | grep :8000`
2. Call MCP tool `kill_resource` with the port number
3. Or increment your service port by +1

### JSONDecodeError: Expecting value

API responses contaminated by Markdown code blocks. Before `json.loads()`:

```python
import re
text = re.sub(r'^```(?:json)?\s*\n?|\n?```$', '', response_text, flags=re.DOTALL).strip()
data = json.loads(text)
```

### MCP Server Won't Start

Run the pre-flight check before debugging:

```bash
bash release_check.sh   # Environment diagnostics
```

---

## 🤝 Contributing

Contributions are welcome! Please open an issue or submit a pull request if you find bugs, have ideas for new system-level "antibodies," or want to improve the knowledge graph.

---

## 📜 License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <b>Made with 🧬 in Taiwan</b><br>
  <sub>Built with passion for the local AI engineering community.</sub>
</p>
