//! The run overview sidebar: run info, environment, config, and summary of
//! the context run as sections that page on their own, so a large config
//! never hides the summary. The paged sections share the height by weights
//! the user drags.

use gpui::prelude::*;
use gpui::{Context, CursorStyle, Div, MouseButton, Stateful, div, px};
use leet_data::run_overview::KeyValuePair;

use crate::theme;
use crate::workspace::{Pane, Separator, Workspace, pane_header, wheel_lines};

pub const ROW_HEIGHT: f32 = 20.;
pub const SECTION_HEADER: f32 = 22.;
pub const SEPARATOR: f32 = 6.;
pub const RUN: usize = 0;
pub const ENVIRONMENT: usize = 1;
pub const CONFIG: usize = 2;
pub const SUMMARY: usize = 3;
const TITLES: [&str; 4] = ["run", "environment", "config", "summary"];

pub struct Row {
    pub key: String,
    pub value: String,
}

pub struct Section {
    pub kind: usize,
    pub rows: Vec<Row>,
}

/// The non-empty sections of the context run, after the overview filter.
pub fn sections(workspace: &Workspace) -> Vec<Section> {
    let Some(ix) = workspace.context_run() else {
        return Vec::new();
    };
    let run = &workspace.runs[ix];
    let overview = &run.overview;
    let pair = |key: &str, value: String| KeyValuePair {
        key: key.to_string(),
        value,
        path: Vec::new(),
    };
    let info: Vec<KeyValuePair> = vec![
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
    .collect();
    let filter = &workspace.filters.overview;
    [
        (RUN, info),
        (ENVIRONMENT, overview.environment_items()),
        (CONFIG, overview.config_items()),
        (SUMMARY, overview.summary_items()),
    ]
    .into_iter()
    .map(|(kind, items)| Section {
        kind,
        rows: items
            .into_iter()
            .filter(|item| filter.matches(&item.key) || filter.matches(&item.value))
            .map(|item| Row {
                key: item.key,
                value: item.value,
            })
            .collect(),
    })
    .filter(|section| !section.rows.is_empty())
    .collect()
}

/// Where each section sits in a sidebar `height` tall: run info at its
/// natural height, the paged sections sharing the rest by `weights`.
pub struct SectionBox {
    pub kind: usize,
    pub top: f32,
    pub height: f32,
}

pub fn layout(sections: &[Section], weights: [f32; 4], height: f32) -> Vec<SectionBox> {
    let run_height = sections
        .iter()
        .find(|s| s.kind == RUN)
        .map_or(0., |s| SECTION_HEADER + s.rows.len() as f32 * ROW_HEIGHT);
    let paged: Vec<&Section> = sections.iter().filter(|s| s.kind != RUN).collect();
    let separators = paged.len().saturating_sub(1) as f32 * SEPARATOR;
    let area = (height - run_height - separators).max(0.);
    let total_weight: f32 = paged
        .iter()
        .map(|s| weights[s.kind])
        .sum::<f32>()
        .max(f32::EPSILON);
    let mut boxes = Vec::new();
    let mut top = 0.;
    if sections.iter().any(|s| s.kind == RUN) {
        boxes.push(SectionBox {
            kind: RUN,
            top,
            height: run_height,
        });
        top += run_height;
    }
    for (i, section) in paged.iter().enumerate() {
        if i > 0 {
            top += SEPARATOR;
        }
        let section_height = area * weights[section.kind] / total_weight;
        boxes.push(SectionBox {
            kind: section.kind,
            top,
            height: section_height,
        });
        top += section_height;
    }
    boxes
}

pub fn render_overview(
    workspace: &Workspace,
    width: gpui::Pixels,
    height: gpui::Pixels,
    cx: &mut Context<Workspace>,
) -> Stateful<Div> {
    let focused = workspace.focus == Pane::Overview;
    let sections = workspace.overview_sections();
    let boxes = layout(&sections, workspace.overview_weights(), f32::from(height));
    let active = workspace.overview_locate(workspace.overview_cursor);
    let mut flat_start = 0;
    let mut previous_paged: Option<usize> = None;
    let mut children: Vec<Div> = Vec::new();
    for (section, section_box) in sections.iter().zip(&boxes) {
        let kind = section.kind;
        if kind != RUN {
            if let Some(above) = previous_paged {
                children.push(
                    div()
                        .h(px(SEPARATOR))
                        .w_full()
                        .flex_shrink_0()
                        .bg(
                            if workspace.dragging_separator() == Some(Separator::Overview(above)) {
                                theme::focus()
                            } else {
                                theme::border()
                            },
                        )
                        .cursor(CursorStyle::ResizeUpDown)
                        .on_mouse_down(
                            MouseButton::Left,
                            cx.listener(move |workspace, _, _, cx| {
                                workspace.start_drag(Separator::Overview(above));
                                cx.notify();
                            }),
                        ),
                );
            }
            previous_paged = Some(kind);
        }
        let cursor_in_section = match active {
            Some((active_kind, row)) if active_kind == kind => Some(row),
            _ => None,
        };
        let paged = &workspace.overview_paged[kind];
        let shown = cursor_in_section
            .unwrap_or(workspace.overview_memory[kind])
            .min(section.rows.len().saturating_sub(1));
        let range = if kind == RUN {
            0..section.rows.len()
        } else {
            paged.range(shown, section.rows.len())
        };
        let title = if kind == RUN {
            TITLES[kind].to_string()
        } else {
            format!(
                "{}  {}",
                TITLES[kind],
                paged.label(shown, section.rows.len())
            )
        };
        let section_start = flat_start;
        children.push(
            div()
                .h(px(section_box.height))
                .w_full()
                .overflow_hidden()
                .flex()
                .flex_col()
                .child(
                    div()
                        .h(px(SECTION_HEADER))
                        .px_2()
                        .flex()
                        .items_center()
                        .text_color(theme::accent())
                        .whitespace_nowrap()
                        .child(title),
                )
                .children(range.map(|row_ix| {
                    let row = &section.rows[row_ix];
                    let flat = section_start + row_ix;
                    div()
                        .id(flat)
                        .w_full()
                        .h(px(ROW_HEIGHT))
                        .px_2()
                        .flex()
                        .gap_2()
                        .whitespace_nowrap()
                        .when(focused && cursor_in_section == Some(row_ix), |r| {
                            r.bg(theme::cursor())
                        })
                        .on_mouse_down(
                            MouseButton::Left,
                            cx.listener(move |workspace, _, _, cx| {
                                workspace.focus = Pane::Overview;
                                workspace.set_overview_cursor(flat);
                                cx.notify();
                            }),
                        )
                        .child(div().text_color(theme::muted()).child(row.key.clone()))
                        .child(
                            div()
                                .flex_1()
                                .overflow_hidden()
                                .text_ellipsis()
                                .child(row.value.clone()),
                        )
                })),
        );
        flat_start += section.rows.len();
    }
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
        .on_mouse_down(
            MouseButton::Left,
            cx.listener(|workspace, _, _, cx| {
                workspace.focus = Pane::Overview;
                cx.notify();
            }),
        )
        .on_scroll_wheel(cx.listener(|workspace, event, _, cx| {
            if let Some(delta) = wheel_lines(event) {
                workspace.turn_list_page(Pane::Overview, delta);
                cx.notify();
            }
        }))
        .child(pane_header(
            "overview".to_string(),
            &workspace.filters.overview,
            focused,
        ))
        .children(children)
}
