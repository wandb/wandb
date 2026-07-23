//! Reproduces pane-toggle visibility glitches: toggles system metrics and
//! media panes and prints the frame after each step.

use std::sync::mpsc::channel;
use std::time::{Duration, Instant};

use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use wandb_leet::config::ConfigManager;
use wandb_leet::workspace::WorkspaceView;

fn dump(ws: &mut WorkspaceView, config: &ConfigManager, area: Rect, label: &str) {
    let mut buf = Buffer::empty(area);
    ws.render(area, &mut buf, config);
    println!("==== {label} ====");
    let l = ws.compute_viewports();
    println!(
        "layout: metrics_h={} sys_y={} sys_h={} media_y={} media_h={} logs_y={} logs_h={} total_h={}",
        l.height,
        l.system_metrics_y,
        l.system_metrics_height,
        l.media_y,
        l.media_height,
        l.console_logs_y,
        l.console_logs_height,
        l.total_content_area_height,
    );
    println!(
        "panes: sys_h={} sys_anim={} media_h={} media_anim={}",
        ws.system_metrics_pane.height(),
        ws.system_metrics_pane.is_animating(),
        ws.media_pane.height(),
        ws.media_pane.is_animating(),
    );
    for y in 0..area.height {
        let mut line = String::new();
        for x in 0..area.width {
            line.push_str(buf[(x, y)].symbol());
        }
        println!("|{}", line.trim_end());
    }
}

fn main() {
    let wandb_dir = std::env::args()
        .nth(1)
        .expect("usage: toggle_repro <wandb-dir>");
    let (w, h) = (180u16, 46u16);
    let area = Rect::new(0, 0, w, h);

    let cfg_path = std::env::temp_dir().join("leet-toggle-repro.json");
    let _ = std::fs::remove_file(&cfg_path);
    let mut config = ConfigManager::new(cfg_path);
    let mut ws = WorkspaceView::new(wandb_dir, &config);

    let (tx, rx) = channel();
    ws.start(tx);
    ws.handle_resize(w as i32, h as i32);

    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        match rx.recv_timeout(Duration::from_millis(300)) {
            Ok(msg) => ws.handle_msg(msg, &config),
            Err(_) => break,
        }
    }

    let settle = |ws: &mut WorkspaceView| {
        let end = Instant::now() + Duration::from_secs(2);
        while ws.tick(Instant::now()) && Instant::now() < end {
            std::thread::sleep(Duration::from_millis(15));
        }
    };
    let key = |ws: &mut WorkspaceView, config: &mut ConfigManager, c: char| {
        ws.handle_key(&KeyEvent::new(KeyCode::Char(c), KeyModifiers::NONE), config);
    };

    settle(&mut ws);
    dump(&mut ws, &config, area, "initial");

    key(&mut ws, &mut config, '2');
    settle(&mut ws);
    dump(&mut ws, &config, area, "after '2' (system on)");

    key(&mut ws, &mut config, '3');
    settle(&mut ws);
    dump(&mut ws, &config, area, "after '3' (media on)");

    key(&mut ws, &mut config, '3');
    settle(&mut ws);
    dump(&mut ws, &config, area, "after '3' again (media off)");

    key(&mut ws, &mut config, '2');
    settle(&mut ws);
    dump(&mut ws, &config, area, "after '2' again (system off)");
}
