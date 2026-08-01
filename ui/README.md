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
```

The portable D:-local Rust/LLVM toolchain is intentionally ignored by Git.
