//! The console logs pane: the context run's stdout and stderr, one page at
//! a time, following new output until the user moves the cursor.

use chrono::{DateTime, Local};
use gpui::prelude::*;
use gpui::{Context, Div, MouseButton, SharedString, Stateful, div, px};

use crate::run::RunState;
use crate::theme;
use crate::workspace::{Pane, Workspace, pane_header, wheel_lines};

pub const ROW_HEIGHT: f32 = 18.;

pub fn render_console(
    workspace: &Workspace,
    height: gpui::Pixels,
    cx: &mut Context<Workspace>,
) -> Stateful<Div> {
    let focused = workspace.focus == Pane::Console;
    let run = workspace.context_run();
    let lines: Vec<usize> = run
        .map(|ix| {
            let run = &workspace.runs[ix];
            (0..run.console.len())
                .filter(|&i| workspace.filters.console.matches(&run.console[i].text))
                .collect()
        })
        .unwrap_or_default();
    let cursor = workspace
        .console_cursor
        .unwrap_or(lines.len().saturating_sub(1));
    let paged = &workspace.console_paged;
    let title = match run {
        Some(ix) => format!(
            "console  {}  {} lines  {}",
            workspace.runs[ix].name,
            lines.len(),
            paged.label(cursor, lines.len())
        ),
        None => "console".to_string(),
    };
    let hint: Option<SharedString> = match run {
        _ if !lines.is_empty() => None,
        None => Some("no run".into()),
        Some(ix) => {
            let run = &workspace.runs[ix];
            Some(if !run.reading {
                format!("select {} (space) to load its console", run.name).into()
            } else if !run.console.is_empty() {
                format!("no lines match \"{}\"", workspace.filters.console.text).into()
            } else if matches!(run.state, RunState::Unknown | RunState::Loading) {
                "loading".into()
            } else {
                "no console output".into()
            })
        }
    };
    let range = paged.range(cursor, lines.len());
    div()
        .id("console")
        .h(height)
        .overflow_hidden()
        .flex()
        .flex_col()
        .border_t_1()
        .border_color(if focused {
            theme::focus()
        } else {
            theme::border()
        })
        .on_mouse_down(
            MouseButton::Left,
            cx.listener(|workspace, _, _, cx| {
                workspace.focus = Pane::Console;
                cx.notify();
            }),
        )
        .child(pane_header(title, &workspace.filters.console, focused))
        .when_some(hint, |pane, hint| {
            pane.child(
                div()
                    .flex_1()
                    .flex()
                    .items_center()
                    .justify_center()
                    .text_color(theme::muted())
                    .child(hint),
            )
        })
        .child(
            div()
                .flex_1()
                .flex()
                .flex_col()
                .on_scroll_wheel(cx.listener(|workspace, event, _, cx| {
                    if let Some(delta) = wheel_lines(event) {
                        workspace.turn_list_page(Pane::Console, delta);
                        cx.notify();
                    }
                }))
                .children(range.filter_map(|pos| {
                    let run = &workspace.runs[run?];
                    let line = &run.console[lines[pos]];
                    let time = line
                        .time
                        .and_then(|t| DateTime::<chrono::Utc>::from_timestamp(t, 0))
                        .map(|t| t.with_timezone(&Local).format("%H:%M:%S").to_string())
                        .unwrap_or_default();
                    Some(
                        div()
                            .id(pos)
                            .w_full()
                            .h(px(ROW_HEIGHT))
                            .px_2()
                            .flex()
                            .gap_3()
                            .whitespace_nowrap()
                            .when(focused && pos == cursor, |row| row.bg(theme::cursor()))
                            .child(div().w(px(64.)).text_color(theme::muted()).child(time))
                            .child(
                                div()
                                    .flex_1()
                                    .overflow_hidden()
                                    .text_color(if line.stderr {
                                        theme::failed()
                                    } else {
                                        theme::text()
                                    })
                                    .child(line.text.clone()),
                            ),
                    )
                })),
        )
}
