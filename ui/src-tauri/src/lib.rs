use std::{
  env,
  fs::{self, OpenOptions},
  io::Write,
  net::{SocketAddr, TcpStream},
  path::{Path, PathBuf},
  process::{Child, Command, Stdio},
  sync::Mutex,
  time::Duration,
};

use tauri::{Manager, WindowEvent};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const API_ADDRESS: &str = "127.0.0.1:8765";

#[derive(Default)]
struct BackendProcess(Mutex<Option<Child>>);

fn api_is_running() -> bool {
  let Ok(address) = API_ADDRESS.parse::<SocketAddr>() else {
    return false;
  };
  TcpStream::connect_timeout(&address, Duration::from_millis(180)).is_ok()
}

fn is_saga_root(path: &Path) -> bool {
  path.join("pyproject.toml").is_file()
    && path.join("src").join("saga").join("ui_api.py").is_file()
    && path.join("ui").join("package.json").is_file()
}

fn find_in_ancestors(path: &Path) -> Option<PathBuf> {
  path.ancestors().find(|candidate| is_saga_root(candidate)).map(Path::to_path_buf)
}

fn saga_root() -> Option<PathBuf> {
  if let Some(root) = env::var_os("SAGA_ROOT").map(PathBuf::from) {
    if is_saga_root(&root) {
      return Some(root);
    }
  }
  if let Some(root) = option_env!("SAGA_SOURCE_ROOT").map(PathBuf::from) {
    if is_saga_root(&root) {
      return Some(root);
    }
  }
  if let Ok(current) = env::current_dir() {
    if let Some(root) = find_in_ancestors(&current) {
      return Some(root);
    }
  }
  env::current_exe().ok().and_then(|path| find_in_ancestors(&path))
}

fn backend_python(root: &Path) -> PathBuf {
  #[cfg(windows)]
  {
    root.join(".venv").join("Scripts").join("python.exe")
  }
  #[cfg(not(windows))]
  {
    root.join(".venv").join("bin").join("python")
  }
}

fn launch_backend() -> Result<Option<Child>, String> {
  if api_is_running() {
    return Ok(None);
  }
  let root = saga_root().ok_or_else(|| {
    "Could not locate the SAGA checkout. Set SAGA_ROOT to the repository folder.".to_string()
  })?;
  let python = backend_python(&root);
  if !python.is_file() {
    return Err(format!(
      "SAGA's Python environment is missing at {}. Run uv sync first.",
      python.display()
    ));
  }

  let log_dir = root.join("output").join("service_logs");
  fs::create_dir_all(&log_dir).map_err(|error| format!("Could not create backend log folder: {error}"))?;
  let log_path = log_dir.join("studio-api.log");
  let stdout = OpenOptions::new()
    .create(true)
    .append(true)
    .open(&log_path)
    .map_err(|error| format!("Could not open {}: {error}", log_path.display()))?;
  let stderr = stdout.try_clone().map_err(|error| format!("Could not clone backend log: {error}"))?;

  let mut command = Command::new(python);
  command
    .args(["-u", "-m", "saga.ui_api"])
    .current_dir(&root)
    .env("PYTHONUNBUFFERED", "1")
    .stdin(Stdio::null())
    .stdout(Stdio::from(stdout))
    .stderr(Stdio::from(stderr));
  #[cfg(windows)]
  command.creation_flags(CREATE_NO_WINDOW);

  command
    .spawn()
    .map(Some)
    .map_err(|error| format!("Could not launch SAGA's local backend: {error}"))
}

fn write_shell_log(message: &str) {
  let Some(root) = saga_root() else {
    return;
  };
  let log_dir = root.join("output").join("service_logs");
  if fs::create_dir_all(&log_dir).is_err() {
    return;
  }
  if let Ok(mut file) = OpenOptions::new()
    .create(true)
    .append(true)
    .open(log_dir.join("studio-shell.log"))
  {
    let _ = writeln!(file, "{message}");
  }
}

fn stop_backend(state: &BackendProcess) {
  let Ok(mut guard) = state.0.lock() else {
    return;
  };
  let Some(child) = guard.as_mut() else {
    return;
  };
  if child.try_wait().ok().flatten().is_none() {
    let _ = child.kill();
    let _ = child.wait();
  }
  *guard = None;
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .manage(BackendProcess::default())
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
        // In `tauri dev`, the before-dev command normally owns the API. Give
        // that process a brief head start before deciding a backend is absent.
        if !api_is_running() {
          std::thread::sleep(Duration::from_millis(1200));
        }
      }
      match launch_backend() {
        Ok(child) => {
          write_shell_log(if child.is_some() {
            "Started an owned SAGA backend process."
          } else {
            "Connected to an existing SAGA backend process."
          });
          *app
            .state::<BackendProcess>()
            .0
            .lock()
            .expect("backend lock poisoned") = child;
        }
        Err(error) => {
          write_shell_log(&format!("Backend startup failed: {error}"));
          eprintln!("SAGA backend startup: {error}");
        }
      }
      Ok(())
    })
    .on_window_event(|window, event| {
      if matches!(event, WindowEvent::Destroyed) {
        stop_backend(&window.state::<BackendProcess>());
      }
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
  use super::*;

  #[test]
  fn repository_root_contract_matches_this_checkout() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..");
    assert!(is_saga_root(&root));
  }

  #[test]
  fn ancestor_search_finds_the_repository_from_tauri_sources() {
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src").join("lib.rs");
    assert!(find_in_ancestors(&source).is_some());
  }
}
