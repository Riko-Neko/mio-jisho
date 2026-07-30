use std::path::PathBuf;

#[tauri::command]
fn write_export_file(path: String, contents: String) -> Result<(), String> {
    let mut path = PathBuf::from(path);
    if path.extension().is_none() {
        path.set_extension("json");
    }
    std::fs::write(path, contents).map_err(|error| error.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![write_export_file])
        .run(tauri::generate_context!())
        .expect("error while running Mio Jisho");
}
