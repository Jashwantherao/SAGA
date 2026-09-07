# SAGA Studio UI

Tauri 2 + React desktop control room for SAGA. The frontend talks only to the
loopback FastAPI service in `saga.ui_api`; API keys, filesystem access, and
process launches remain in Python.

```powershell
# Browser development (API + Vite)
D:\SAGA\scripts\saga_ui.ps1 -Mode browser

# Native Tauri development
D:\SAGA\scripts\saga_ui.ps1 -Mode desktop

# Finite Rust compile check
D:\SAGA\scripts\saga_ui.ps1 -Mode check

# Build the reliable D:-local portfolio executable
D:\SAGA\scripts\saga_ui.ps1 -Mode package

# Build an optimized executable (may require a Defender exclusion for the
# D:-local GNU target directory on this workstation)
D:\SAGA\scripts\saga_ui.ps1 -Mode release
```

The release app starts `saga.ui_api` itself from the checkout's `.venv`, writes
its log to `output/service_logs/studio-api.log`, and stops only the backend
process it owns when the window closes. Set `SAGA_ROOT` if the checkout moves.
Both commands avoid Tauri's WiX/NSIS bundlers because those tools hard-code a
cache beneath `%LOCALAPPDATA%`; SAGA's development contract permits writes only
on D:. The finished executable and its SHA-256 checksum are copied to
`release/`.
The portable D:-local Rust/LLVM toolchain is intentionally ignored by Git.
