// Optimized Windows releases use the in-app diagnostics surface and backend
// log, so they do not need a second console window. Debug portfolio builds keep
// the console available because it is valuable evidence when startup fails.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    saga_studio_lib::run();
}
