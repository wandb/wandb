//! The console logs pane: the context run's stdout and stderr, following
//! new output until the user scrolls.

use std::ops::Range;

use chrono::{DateTime, Local};
use gpui::prelude::*;
use gpui::{Context, Div, ScrollStrategy, SharedString, Stateful, div, px, uniform_list};

use crate::run::RunState;
use crate::theme;
use crate::workspace::{Pane, Workspace, pane_header};

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
    let title = match run {
        Some(ix) => format!(
            "console  {}  {} lines",
            workspace.runs[ix].name,
            lines.len()
        ),
        None => "console".to_string(),
    };
    if let Some(last) = lines.len().checked_sub(1) {
        let target = workspace
            .console_cursor
            .map_or(last, |cursor| cursor.min(last));
        workspace
            .console_scroll
            .scroll_to_item(target, ScrollStrategy::Bottom);
    }
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
        .child(pane_header(title, &workspace.filters.console, focused))
        .when_some(hint.clone(), |pane, hint| {
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
        .when(hint.is_none(), |pane| {
            pane.child(
                uniform_list(
                    "console-lines",
                    lines.len(),
                    cx.processor(move |workspace, range: Range<usize>, _, _| {
                        let Some(ix) = workspace.context_run() else {
                            return Vec::new();
                        };
                        let run = &workspace.runs[ix];
                        range
                            .map(|pos| {
                                let line = &run.console[lines[pos]];
                                let time = line
                                    .time
                                    .and_then(|t| DateTime::from_timestamp(t, 0))
                                    .map(|t| t.with_timezone(&Local).format("%H:%M:%S").to_string())
                                    .unwrap_or_default();
                                div()
                                    .id(pos)
                                    .h(px(18.))
                                    .px_2()
                                    .flex()
                                    .gap_3()
                                    .whitespace_nowrap()
                                    .when(Some(pos) == workspace.console_cursor, |row| {
                                        row.bg(theme::cursor())
                                    })
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
                                    )
                            })
                            .collect()
                    }),
                )
                .flex_1()
                .track_scroll(workspace.console_scroll.clone()),
            )
        })
}
