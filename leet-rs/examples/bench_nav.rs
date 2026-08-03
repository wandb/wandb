//! Measures per-keypress latency in the workspace run list: key handling and
//! a full frame render, against a real wandb directory.

use std::sync::mpsc::channel;
use std::time::{Duration, Instant};

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use wandb_leet::config::ConfigManager;
use wandb_leet::workspace::WorkspaceView;

fn main() {
    let wandb_dir = std::env::args()
        .nth(1)
        .expect("usage: bench_nav <wandb-dir>");
    let (w, h) = (220u16, 60u16);

    let config = ConfigManager::new(std::env::temp_dir().join("leet-bench-nav.json"));
    let mut ws = WorkspaceView::new(wandb_dir, &config);

    let (tx, rx) = channel();
    ws.start(tx);
    ws.handle_resize(w as i32, h as i32);

    // Ingest for a fixed window so charts/list have data.
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        match rx.recv_timeout(Duration::from_millis(200)) {
            Ok(msg) => ws.handle_msg(msg, &config),
            Err(_) => break,
        }
    }
    while ws.tick(Instant::now()) {
        std::thread::sleep(Duration::from_millis(15));
    }

    let area = Rect::new(0, 0, w, h);
    let key = |code| KeyEvent::new(code, KeyModifiers::NONE);

    // Warm-up render.
    let mut buf = Buffer::empty(area);
    ws.render(area, &mut buf, &config);

    for (label, code) in [("down", KeyCode::Down), ("up", KeyCode::Up)] {
        let mut key_total = Duration::ZERO;
        let mut render_total = Duration::ZERO;
        let mut render_max = Duration::ZERO;
        const N: u32 = 50;
        for _ in 0..N {
            let t0 = Instant::now();
            ws.handle_key(
                &key(code),
                &mut ConfigManager::new(std::env::temp_dir().join("leet-bench-nav.json")),
            );
            let t1 = Instant::now();
            let mut buf = Buffer::empty(area);
            ws.render(area, &mut buf, &config);
            let t2 = Instant::now();
            key_total += t1 - t0;
            let r = t2 - t1;
            render_total += r;
            render_max = render_max.max(r);
        }
        println!(
            "{label}: key avg {:?}, render avg {:?}, render max {:?}",
            key_total / N,
            render_total / N,
            render_max
        );
    }
}
