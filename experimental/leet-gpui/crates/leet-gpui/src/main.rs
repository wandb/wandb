//! W&B LEET as a native GPUI app: the workspace view of a local wandb
//! directory with keyboard-first navigation.

mod actions;
mod chart;
mod source;
mod theme;
mod workspace;

use std::path::PathBuf;

use gpui::{
    App, AppContext, Application, Bounds, TitlebarOptions, WindowBounds, WindowOptions, px, size,
};

use crate::workspace::Workspace;

fn main() {
    let path = std::env::args()
        .nth(1)
        .map_or_else(|| PathBuf::from("wandb"), PathBuf::from);
    let (wandb_dir, run) = source::resolve(&path);

    Application::new().run(move |cx: &mut App| {
        let help = actions::bind(cx);
        cx.on_action(|_: &actions::Quit, cx| cx.quit());

        let bounds = Bounds::centered(None, size(px(1440.), px(900.)), cx);
        cx.open_window(
            WindowOptions {
                window_bounds: Some(WindowBounds::Windowed(bounds)),
                titlebar: Some(TitlebarOptions {
                    title: Some("W&B LEET".into()),
                    ..Default::default()
                }),
                ..Default::default()
            },
            |window, cx| {
                let workspace = cx.new(|cx| Workspace::new(wandb_dir, run, help, cx));
                let focus = workspace.read(cx).focus_handle.clone();
                window.focus(&focus);
                workspace
            },
        )
        .expect("open the main window");
        cx.activate(true);
    });
}
