// YAW desktop (Tauri v2). Wraps the web client (../../web) in a native window.
//
// The web frontend runs unchanged — its identity seed lives in the webview's
// localStorage by default. The three commands below let the frontend instead store
// the seed in the OS keychain (macOS Keychain / Windows Credential Manager / Linux
// libsecret), which survives "clear browsing data" and is the desktop value-add.
// Wiring the web client to prefer these when `window.__TAURI__` exists is the next
// step — see desktop/README.md.

use keyring::Entry;

const SERVICE: &str = "yaw";

#[tauri::command]
fn key_save(account: String, secret: String) -> Result<(), String> {
    Entry::new(SERVICE, &account)
        .map_err(|e| e.to_string())?
        .set_password(&secret)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn key_load(account: String) -> Result<Option<String>, String> {
    let entry = Entry::new(SERVICE, &account).map_err(|e| e.to_string())?;
    match entry.get_password() {
        Ok(secret) => Ok(Some(secret)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
fn key_delete(account: String) -> Result<(), String> {
    let entry = Entry::new(SERVICE, &account).map_err(|e| e.to_string())?;
    match entry.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(e.to_string()),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![key_save, key_load, key_delete])
        .run(tauri::generate_context!())
        .expect("error while running YAW desktop");
}
