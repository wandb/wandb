//! A small flexbox-style vertical stack layout for the central column.

use crate::theme::{
    SIDEBAR_MAX_WIDTH, SIDEBAR_MIN_WIDTH, SIDEBAR_OVERHEAD, SIDEBAR_WIDTH_RATIO,
    SIDEBAR_WIDTH_RATIO_BOTH,
};

/// Identifies a vertically stacked pane in the main content area.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StackSection {
    Metrics = 0,
    SystemMetrics = 1,
    Media = 2,
    ConsoleLogs = 3,
}

pub const STACK_SECTION_COUNT: usize = 4;

/// Describes one pane in a vertical stack.
#[derive(Debug, Clone, Copy)]
pub struct StackSectionSpec {
    pub id: StackSection,
    pub visible: bool,
    pub height: i32,
    pub flex: bool,
}

/// The computed origin and height of one pane.
#[derive(Debug, Clone, Copy, Default)]
pub struct StackSectionLayout {
    pub y: i32,
    pub height: i32,
}

/// A computed top-to-bottom stack.
///
/// Fixed-height panes (system/media/logs) keep their current animated
/// heights. The optional flex pane (metrics) consumes the remaining height
/// after gaps.
#[derive(Debug, Clone, Copy, Default)]
pub struct VerticalStackLayout {
    pub total_height: i32,
    pub visible_count: usize,
    sections: [StackSectionLayout; STACK_SECTION_COUNT],
}

impl VerticalStackLayout {
    pub fn height(&self, id: StackSection) -> i32 {
        self.sections[id as usize].height
    }

    pub fn y(&self, id: StackSection) -> i32 {
        self.sections[id as usize].y
    }
}

/// Computes a top-to-bottom stack with a 1-line gap between adjacent visible
/// panes.
pub fn compute_vertical_stack_layout(
    total_height: i32,
    specs: &[StackSectionSpec],
) -> VerticalStackLayout {
    let mut layout = VerticalStackLayout {
        total_height: total_height.max(0),
        ..Default::default()
    };

    let mut visible: Vec<StackSectionSpec> = Vec::with_capacity(specs.len());
    let mut fixed_height = 0;
    let mut flex_index: Option<usize> = None;
    for spec in specs {
        if !spec.visible {
            continue;
        }
        let mut spec = *spec;
        spec.height = spec.height.max(0);
        if spec.flex {
            flex_index = Some(visible.len());
        } else {
            fixed_height += spec.height;
        }
        visible.push(spec);
    }

    layout.visible_count = visible.len();
    if visible.is_empty() {
        return layout;
    }

    let gap_lines = (visible.len() as i32 - 1).max(0);
    let remaining = (layout.total_height - fixed_height - gap_lines).max(0);
    if let Some(i) = flex_index {
        visible[i].height = remaining;
    }

    let mut y = 0;
    let last = visible.len() - 1;
    for (i, spec) in visible.iter().enumerate() {
        layout.sections[spec.id as usize] = StackSectionLayout {
            y,
            height: spec.height,
        };
        y += spec.height;
        if i < last {
            y += 1;
        }
    }

    layout
}

/// The full width of an expanded sidebar for the given terminal width.
pub fn expanded_sidebar_width(terminal_width: i32, opposite_visible: bool) -> i32 {
    let ratio = if opposite_visible {
        SIDEBAR_WIDTH_RATIO_BOTH
    } else {
        SIDEBAR_WIDTH_RATIO
    };
    ((terminal_width as f64 * ratio) as i32).clamp(SIDEBAR_MIN_WIDTH, SIDEBAR_MAX_WIDTH)
}

/// Minimum sidebar width while resizing with the mouse. Narrower than the
/// default clamp so users can deliberately shrink a sidebar.
pub const SIDEBAR_DRAG_MIN_WIDTH: i32 = 20;

/// Minimum central column width preserved while resizing sidebars.
pub const MAIN_DRAG_MIN_WIDTH: i32 = 24;

/// The expanded sidebar width, honoring a user-set fraction of the terminal
/// width when present.
pub fn sidebar_width_for(
    terminal_width: i32,
    opposite_visible: bool,
    fraction: Option<f64>,
) -> i32 {
    match fraction {
        Some(f) => {
            let max = (terminal_width - MAIN_DRAG_MIN_WIDTH).max(SIDEBAR_DRAG_MIN_WIDTH);
            ((terminal_width as f64 * f).round() as i32).clamp(SIDEBAR_DRAG_MIN_WIDTH, max)
        }
        None => expanded_sidebar_width(terminal_width, opposite_visible),
    }
}

/// The width available for text content inside a sidebar after subtracting
/// the vertical border and both padding columns.
pub fn sidebar_content_width(total_width: i32) -> i32 {
    (total_width - SIDEBAR_OVERHEAD).max(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stack_layout_with_flex() {
        let layout = compute_vertical_stack_layout(
            40,
            &[
                StackSectionSpec {
                    id: StackSection::Metrics,
                    visible: true,
                    height: 0,
                    flex: true,
                },
                StackSectionSpec {
                    id: StackSection::SystemMetrics,
                    visible: true,
                    height: 10,
                    flex: false,
                },
                StackSectionSpec {
                    id: StackSection::ConsoleLogs,
                    visible: false,
                    height: 5,
                    flex: false,
                },
            ],
        );
        assert_eq!(layout.visible_count, 2);
        // Metrics gets 40 - 10 fixed - 1 gap = 29.
        assert_eq!(layout.height(StackSection::Metrics), 29);
        assert_eq!(layout.y(StackSection::Metrics), 0);
        assert_eq!(layout.y(StackSection::SystemMetrics), 30);
    }
}
