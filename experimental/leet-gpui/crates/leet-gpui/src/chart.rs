//! A line chart painted straight into a GPUI canvas: decimated polylines,
//! nice ticks, and a hover crosshair with the nearest value of every series.
//! The data comes from the workspace's series caches at paint time.

use gpui::{
    App, Bounds, ContentMask, Corners, Entity, Hsla, PathBuilder, Pixels, Point, SharedString,
    Styled, TextRun, Window, canvas, fill, point, px, size,
};
use leet_plot::{Range, Scale, format_duration_tick, format_tick};

use crate::theme;
use crate::workspace::Workspace;

const LEFT: f32 = 48.;
const RIGHT: f32 = 10.;
const TOP: f32 = 8.;
const BOTTOM: f32 = 18.;
const FONT_SIZE: f32 = 10.;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Table {
    Metrics,
    System,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum XAxis {
    Step,
    /// Unix seconds, drawn relative to the first sample.
    Time,
}

#[derive(Debug, Clone)]
pub struct SeriesRef {
    pub run: usize,
    pub table: Table,
    pub series: usize,
    pub name: SharedString,
    pub color: Hsla,
}

#[derive(Debug, Clone)]
pub struct ChartSpec {
    pub x_axis: XAxis,
    pub log: bool,
    /// A y range to show even when the data spans less, as for percentages.
    pub fixed_y: Option<Range>,
    pub series: Vec<SeriesRef>,
}

pub struct SeriesDraw {
    pub name: SharedString,
    pub color: Hsla,
    pub line: Vec<leet_plot::Point>,
    pub raw: Option<Vec<leet_plot::Point>>,
    pub hover: Option<(f64, f64)>,
}

pub struct ChartData {
    pub x_range: Range,
    pub y_range: Range,
    pub series: Vec<SeriesDraw>,
}

pub fn chart(workspace: Entity<Workspace>, spec: ChartSpec) -> impl gpui::IntoElement {
    canvas(
        |_, _, _| (),
        move |bounds, _, window, cx| paint(&workspace, &spec, bounds, window, cx),
    )
    .size_full()
}

struct Frame {
    plot: Bounds<Pixels>,
    x_range: Range,
    y_range: Range,
    y_scale: Scale,
}

impl Frame {
    fn to_px(&self, x: f64, y: f64) -> Point<Pixels> {
        let tx = Scale::Linear.normalize(self.x_range, x) as f32;
        let ty = self.y_scale.normalize(self.y_range, y) as f32;
        point(
            self.plot.origin.x + self.plot.size.width * tx,
            self.plot.origin.y + self.plot.size.height * (1.0 - ty),
        )
    }
}

fn paint(
    workspace: &Entity<Workspace>,
    spec: &ChartSpec,
    bounds: Bounds<Pixels>,
    window: &mut Window,
    cx: &mut App,
) {
    let plot = Bounds {
        origin: point(bounds.origin.x + px(LEFT), bounds.origin.y + px(TOP)),
        size: size(
            bounds.size.width - px(LEFT + RIGHT),
            bounds.size.height - px(TOP + BOTTOM),
        ),
    };
    if plot.size.width < px(20.) || plot.size.height < px(20.) {
        return;
    }
    let mouse = window.mouse_position();
    let hover_x = plot.contains(&mouse).then_some(mouse.x);
    let hover_t =
        hover_x.map(|x| (f32::from(x - plot.origin.x) / f32::from(plot.size.width)) as f64);
    let columns = f32::from(plot.size.width) as usize;

    let data = workspace.update(cx, |workspace, _| {
        workspace.chart_data(spec, columns, hover_t)
    });
    let Some(data) = data else {
        paint_text(
            window,
            cx,
            "no data",
            plot.center(),
            theme::muted(),
            Align::Center,
        );
        return;
    };
    let y_scale = if spec.log {
        Scale::Log10
    } else {
        Scale::Linear
    };
    let frame = Frame {
        plot,
        x_range: data.x_range,
        y_range: data.y_range,
        y_scale,
    };

    for tick in y_scale.ticks(
        frame.y_range,
        (f32::from(plot.size.height) / 40.).max(2.) as usize,
    ) {
        let y = frame.to_px(frame.x_range.min, tick).y;
        window.paint_quad(fill(
            Bounds {
                origin: point(plot.origin.x, y),
                size: size(plot.size.width, px(1.)),
            },
            theme::grid(),
        ));
        paint_text(
            window,
            cx,
            &format_tick(tick),
            point(plot.origin.x - px(6.), y - px(7.)),
            theme::muted(),
            Align::Right,
        );
    }
    let x_offset = match spec.x_axis {
        XAxis::Step => 0.0,
        XAxis::Time => frame.x_range.min,
    };
    let x_label = |x: f64| match spec.x_axis {
        XAxis::Step => format_tick(x),
        XAxis::Time => format_duration_tick(x - x_offset),
    };
    let shifted = Range {
        min: frame.x_range.min - x_offset,
        max: frame.x_range.max - x_offset,
    };
    for tick in Scale::Linear.ticks(shifted, (f32::from(plot.size.width) / 90.).max(2.) as usize) {
        let x = frame.to_px(tick + x_offset, frame.y_range.min).x;
        window.paint_quad(fill(
            Bounds {
                origin: point(x, plot.origin.y),
                size: size(px(1.), plot.size.height),
            },
            theme::grid(),
        ));
        paint_text(
            window,
            cx,
            &x_label(tick + x_offset),
            point(x, plot.origin.y + plot.size.height + px(3.)),
            theme::muted(),
            Align::Center,
        );
    }

    window.with_content_mask(Some(ContentMask { bounds: plot }), |window| {
        for s in &data.series {
            if let Some(raw) = &s.raw {
                stroke(window, &frame, raw, s.color.opacity(0.25), 1.);
            }
            stroke(window, &frame, &s.line, s.color, 1.5);
        }
    });

    let Some(hover_x) = hover_x else {
        return;
    };
    window.paint_quad(fill(
        Bounds {
            origin: point(hover_x, plot.origin.y),
            size: size(px(1.), plot.size.height),
        },
        theme::muted().opacity(0.6),
    ));
    let mut row_y = plot.origin.y + px(4.);
    let mut hovered_x: Option<f64> = None;
    for s in &data.series {
        let Some((x, y)) = s.hover else {
            continue;
        };
        hovered_x.get_or_insert(x);
        let p = frame.to_px(x, y);
        window.paint_quad(
            fill(
                Bounds {
                    origin: point(p.x - px(3.), p.y - px(3.)),
                    size: size(px(6.), px(6.)),
                },
                s.color,
            )
            .corner_radii(Corners::all(px(3.))),
        );
        paint_text(
            window,
            cx,
            &format!("{}  {}", s.name, format_value(y)),
            point(plot.origin.x + px(6.), row_y),
            s.color,
            Align::Left,
        );
        row_y += px(14.);
    }
    if let Some(x) = hovered_x {
        let label = match spec.x_axis {
            XAxis::Step => format!("step {}", format_tick(x)),
            XAxis::Time => format!("+{}", format_duration_tick(x - x_offset)),
        };
        let anchor = point(hover_x, plot.origin.y + plot.size.height - px(14.));
        paint_text(window, cx, &label, anchor, theme::text(), Align::Center);
    }
}

fn stroke(
    window: &mut Window,
    frame: &Frame,
    points: &[leet_plot::Point],
    color: Hsla,
    width: f32,
) {
    let mut path = PathBuilder::stroke(px(width));
    let mut iter = points.iter().map(|p| frame.to_px(p.x, p.y));
    let Some(first) = iter.next() else {
        return;
    };
    path.move_to(first);
    for p in iter {
        path.line_to(p);
    }
    if let Ok(path) = path.build() {
        window.paint_path(path, color);
    }
}

pub fn format_value(v: f64) -> String {
    if v == 0. || (1e-3..1e6).contains(&v.abs()) {
        let s = format!("{v:.5}");
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        format!("{v:.4e}")
    }
}

enum Align {
    Left,
    Center,
    Right,
}

fn paint_text(
    window: &mut Window,
    cx: &mut App,
    text: &str,
    origin: Point<Pixels>,
    color: Hsla,
    align: Align,
) {
    let font = window.text_style().font();
    let run = TextRun {
        len: text.len(),
        font,
        color,
        background_color: None,
        underline: None,
        strikethrough: None,
    };
    let line = window.text_system().shape_line(
        SharedString::from(text.to_string()),
        px(FONT_SIZE),
        &[run],
        None,
    );
    let x = match align {
        Align::Left => origin.x,
        Align::Center => origin.x - line.width / 2.,
        Align::Right => origin.x - line.width,
    };
    line.paint(point(x, origin.y), px(FONT_SIZE * 1.4), window, cx)
        .ok();
}
