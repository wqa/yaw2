// Thin binary entry point — the app lives in lib.rs (yaw_lib) so the same code can
// also drive a mobile build later. See lib.rs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    yaw_lib::run()
}
