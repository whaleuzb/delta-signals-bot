// 452: Trade Controller — kompyuter ilovasi. Oyna serverdagi Mini App'ni (/app?desk=1) ochadi,
// shuning uchun interfeys yangilanishlari ilovani qayta o'rnatmasdan darhol keladi.
// Boshqa saytlarga (t.me, birjalar va h.k.) o'tishlar tizim brauzerida/Telegram'da ochiladi.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;

const HOST: &str = "web-production-addc3.up.railway.app";

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            let h = app.handle().clone();
            let url = format!("https://{HOST}/app?desk=1");
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse().unwrap()))
                .title("Trade Controller")
                .inner_size(1360.0, 860.0)
                .min_inner_size(400.0, 560.0)
                .center()
                .on_navigation(move |u| {
                    let own = u.host_str() == Some(HOST);
                    if own || matches!(u.scheme(), "about" | "data" | "blob" | "tauri") {
                        return true;
                    }
                    let _ = h.opener().open_url(u.as_str(), None::<&str>);
                    false
                })
                .build()?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("Trade Controller ishga tushmadi");
}
