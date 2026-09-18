//! The run overview sidebar: run info, environment, config, and summary of
//! the context run as one filterable list with section headers.

use gpui::prelude::*;
use gpui::{Context, Div, Stateful, div, px};
use leet_data::run_overview::KeyValuePair;

use crate::theme;
use crate::workspace::{Pane, Workspace, pane_header, wheel_lines};

pub struct Row {
    pub key: String,
    pub value: String,
    pub header: bool,
}

pub fn rows(workspace: &Workspace) -> Vec<Row> {
    let Some(ix) = workspace.context_run() else {
        return Vec::new();
    };
    let run = &workspace.runs[ix];
    let overview = &run.overview;
    let mut rows = Vec::new();
    let mut section = |title: &str, items: Vec<KeyValuePair>| {
        let items: Vec<KeyValuePair> = items
            .into_iter()
            .filter(|item| {
                workspace.filters.overview.matches(&item.key)
                    || workspace.filters.overview.matches(&item.value)
            })
            .collect();
        if items.is_empty() {
            return;
        }
        rows.push(Row {
            key: title.to_string(),
            value: String::new(),
            header: true,
        });
        rows.extend(items.into_iter().map(|item| Row {
            key: item.key,
            value: item.value,
            header: false,
        }));
    };
    let pair = |key: &str, value: String| KeyValuePair {
        key: key.to_string(),
        value,
        path: Vec::new(),
    };
    section(
        "run",
        vec![
            pair("id", overview.id().to_string()),
            pair("name", overview.display_name().to_string()),
            pair("project", overview.project().to_string()),
            pair("state", overview.state_string().to_string()),
            pair("tags", overview.tags().join(", ")),
            pair("notes", overview.notes().to_string()),
            pair("dir", run.dir.dir_name.clone()),
        ]
        .into_iter()
        .filter(|item| !item.value.is_empty())
        .collect(),
    );
    section("environment", overview.environment_items());
    section("config", overview.config_items());
    section("summary", overview.summary_items());
    rows
}

pub const ROW_HEIGHT: f32 = 20.;

pub fn render_overview(
    workspace: &Workspace,
    width: gpui::Pixels,
    cx: &mut Context<Workspace>,
) -> Stateful<Div> {
    let focused = workspace.focus == Pane::Overview;
    let rows = workspace.overview_rows();
    let paged = &workspace.overview_paged;
    let cursor = workspace.overview_cursor.min(rows.len().saturating_sub(1));
    let header = format!("overview  {}", paged.label(cursor, rows.len()));
    let range = paged.range(cursor, rows.len());
    div()
        .id("overview")
        .w(width)
        .h_full()
        .overflow_hidden()
        .flex()
        .flex_col()
        .border_l_1()
        .border_color(if focused {
            theme::focus()
        } else {
            theme::border()
        })
        .child(pane_header(header, &workspace.filters.overview, focused))
        .child(
            div()
                .flex_1()
                .flex()
                .flex_col()
                .on_scroll_wheel(cx.listener(|workspace, event, _, cx| {
                    if let Some(delta) = wheel_lines(event) {
                        workspace.turn_list_page(Pane::Overview, delta);
                        cx.notify();
                    }
                }))
                .children(range.map(|pos| {
                    let row = &rows[pos];
                    div()
                        .id(pos)
                        .w_full()
                        .h(px(ROW_HEIGHT))
                        .px_2()
                        .flex()
                        .gap_2()
                        .whitespace_nowrap()
                        .when(focused && pos == cursor, |r| r.bg(theme::cursor()))
                        .when(row.header, |r| {
                            r.text_color(theme::accent()).child(row.key.clone())
                        })
                        .when(!row.header, |r| {
                            r.child(div().text_color(theme::muted()).child(row.key.clone()))
                                .child(
                                    div()
                                        .flex_1()
                                        .overflow_hidden()
                                        .text_ellipsis()
                                        .child(row.value.clone()),
                                )
                        })
                })),
        )
}
