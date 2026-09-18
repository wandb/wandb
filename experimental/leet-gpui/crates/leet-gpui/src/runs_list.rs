//! The runs sidebar: every run in the directory, newest first, with its
//! selection mark, pin, and state.

use std::ops::Range;

use gpui::prelude::*;
use gpui::{Context, Div, Stateful, div, px, uniform_list};

use crate::run::RunState;
use crate::theme;
use crate::workspace::{Pane, Workspace, pane_header};

pub fn render_runs(
    workspace: &Workspace,
    width: gpui::Pixels,
    cx: &mut Context<Workspace>,
) -> Stateful<Div> {
    let visible = workspace.visible();
    let focused = workspace.focus == Pane::Runs;
    let header = format!("runs {}/{}", visible.len(), workspace.runs.len());
    div()
        .id("runs")
        .w(width)
        .h_full()
        .flex()
        .flex_col()
        .border_r_1()
        .border_color(if focused {
            theme::focus()
        } else {
            theme::border()
        })
        .child(pane_header(header, &workspace.filters.runs, focused))
        .child(
            uniform_list(
                "runs-list",
                visible.len(),
                cx.processor(move |workspace, range: Range<usize>, _, cx| {
                    range
                        .map(|pos| render_run_row(workspace, visible[pos], pos, cx))
                        .collect()
                }),
            )
            .flex_1()
            .track_scroll(workspace.runs_scroll.clone()),
        )
}

pub fn state_glyph(state: RunState) -> (&'static str, gpui::Hsla) {
    match state {
        RunState::Unknown => ("", theme::muted()),
        RunState::Loading => ("…", theme::muted()),
        RunState::Running => ("▶", theme::accent()),
        RunState::Finished => ("✓", theme::muted()),
        RunState::Failed => ("✗", theme::failed()),
    }
}

fn render_run_row(
    workspace: &Workspace,
    ix: usize,
    pos: usize,
    cx: &mut Context<Workspace>,
) -> Stateful<Div> {
    let run = &workspace.runs[ix];
    let selected = workspace.selected.contains(&run.dir.dir_name);
    let pinned = workspace.pinned.as_deref() == Some(run.dir.dir_name.as_str());
    let mark = match (pinned, selected) {
        (true, _) => "▶",
        (false, true) => "●",
        (false, false) => "○",
    };
    let mark_color = if selected || pinned {
        theme::run_color(run.color)
    } else {
        theme::muted()
    };
    let (state, state_color) = state_glyph(run.state);
    div()
        .id(pos)
        .h(px(22.))
        .px_2()
        .flex()
        .items_center()
        .gap_2()
        .when(pos == workspace.cursor, |row| row.bg(theme::cursor()))
        .on_click(cx.listener(move |workspace, _, _, cx| {
            workspace.focus = Pane::Runs;
            workspace.set_cursor(pos);
            cx.notify();
        }))
        .child(div().text_color(mark_color).child(mark))
        .child(
            div()
                .flex_1()
                .overflow_hidden()
                .whitespace_nowrap()
                .text_ellipsis()
                .child(run.name.clone()),
        )
        .child(div().text_color(state_color).child(state))
}
