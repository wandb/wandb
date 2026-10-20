//! Headless workspace render smoke test: scans a wandb dir and prints frames.

use std::sync::mpsc::channel;
use std::time::Duration;

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use wandb_leet::config::ConfigManager;
use wandb_leet::msg::{Msg, RecordMsg};
use wandb_leet::workspace::WorkspaceView;

fn main() {
    let wandb_dir = std::env::args()
        .nth(1)
        .expect("usage: render_workspace <wandb-dir>");
    let (w, h) = (200u16, 50u16);

    let config = ConfigManager::new(std::env::temp_dir().join("leet-render-ws-test.json"));
    let mut ws = WorkspaceView::new(wandb_dir, &config);

    let (tx, rx) = channel();
    ws.start(tx);
    ws.handle_resize(w as i32, h as i32);

    // Drain messages until the auto-selected run's reader catches up.
    let deadline = std::time::Instant::now() + Duration::from_secs(30);
    while std::time::Instant::now() < deadline {
        match rx.recv_timeout(Duration::from_secs(2)) {
            Ok(Msg::Batch {
                source_id,
                msgs,
                progress,
                caught_up,
            }) => {
                let done = caught_up
                    || msgs
                        .iter()
                        .any(|m| matches!(m, RecordMsg::FileComplete { .. }));
                ws.handle_msg(
                    Msg::Batch {
                        source_id,
                        msgs,
                        progress,
                        caught_up,
                    },
                    &config,
                );
                if done {
                    break;
                }
            }
            Ok(msg) => ws.handle_msg(msg, &config),
            Err(_) => break,
        }
    }

    // Let animations settle to their final values.
    let end = std::time::Instant::now() + Duration::from_secs(2);
    while ws.tick(std::time::Instant::now()) && std::time::Instant::now() < end {
        std::thread::sleep(Duration::from_millis(15));
    }

    let area = Rect::new(0, 0, w, h);
    let mut buf = Buffer::empty(area);
    ws.render(area, &mut buf, &config);

    for y in 0..h {
        let mut line = String::new();
        for x in 0..w {
            line.push_str(buf[(x, y)].symbol());
        }
        println!("{}", line.trim_end());
    }
}
