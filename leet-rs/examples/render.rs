//! Headless render smoke test: reads a .wandb file and prints one frame.

use std::sync::mpsc::channel;
use std::time::Duration;

use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use wandb_leet::config::ConfigManager;
use wandb_leet::run::RunView;

fn main() {
    let path = std::env::args().nth(1).expect("usage: render <run.wandb>");
    let (w, h) = (200u16, 50u16);

    let config = ConfigManager::new(std::env::temp_dir().join("leet-render-test.json"));
    let mut run = RunView::new(path, &config);

    let (tx, rx) = channel();
    run.start(tx);
    run.handle_resize(w as i32, h as i32);

    // Drain messages until the reader catches up or times out.
    let deadline = std::time::Instant::now() + Duration::from_secs(30);
    while std::time::Instant::now() < deadline {
        match rx.recv_timeout(Duration::from_secs(2)) {
            Ok(wandb_leet::msg::Msg::Batch {
                source_id,
                msgs,
                progress,
                caught_up,
            }) => {
                let done = caught_up
                    || msgs
                        .iter()
                        .any(|m| matches!(m, wandb_leet::msg::RecordMsg::FileComplete { .. }));
                run.handle_msg(wandb_leet::msg::Msg::Batch {
                    source_id,
                    msgs,
                    progress,
                    caught_up,
                });
                if done {
                    break;
                }
            }
            Ok(msg) => run.handle_msg(msg),
            Err(_) => break,
        }
    }

    let area = Rect::new(0, 0, w, h);
    let mut buf = Buffer::empty(area);
    run.render(area, &mut buf, &config);

    for y in 0..h {
        let mut line = String::new();
        for x in 0..w {
            line.push_str(buf[(x, y)].symbol());
        }
        println!("{}", line.trim_end());
    }
}
