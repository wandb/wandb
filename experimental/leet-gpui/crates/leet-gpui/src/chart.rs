//! A line chart of one metric across the selected runs, painted straight into
//! a GPUI canvas: decimated polylines, nice ticks, and a hover crosshair with
//! the nearest value of every run.

use std::borrow::Cow;

use gpui::{
    App, Bounds, ContentMask, Corners, Entity, Hsla, PathBuilder, Pixels, Point, SharedString,
    Styled, TextRun, Window, canvas, fill, point, px, size,
};
use leet_plot::{Range, Scale, decimate, ema, format_tick, nearest};

use crate::theme;
use crate::workspace::Workspace;

const LEFT: f32 = 48.;
const RIGHT: f32 = 10.;
const TOP: f32 = 8.;
const BOTTOM: f32 = 18.;
const FONT_SIZE: f32 = 10.;

pub fn chart(workspace: Entity<Workspace>, metric: SharedString) -> impl gpui::IntoElement {
    canvas(
        |_, _, _| (),
        move |bounds, _, window, cx| paint(&workspace, &metric, bounds, window, cx),
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

    fn x_at(&self, px_x: Pixels) -> f64 {
        let t = f32::from(px_x - self.plot.origin.x) / f32::from(self.plot.size.width);
        Scale::Linear.denormalize(self.x_range, t as f64)
    }
}

struct Series {
    name: String,
    color: Hsla,
    line: Vec<leet_plot::Point>,
    raw: Option<Vec<leet_plot::Point>>,
    hover: Option<(f64, f64)>,
}

fn paint(
    workspace: &Entity<Workspace>,
    metric: &str,
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

    let Some((frame, series)) = layout(workspace, metric, plot, hover_x, cx) else {
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

    let y_ticks = frame.y_scale.ticks(
        frame.y_range,
        (f32::from(plot.size.height) / 40.).max(2.) as usize,
    );
    for tick in &y_ticks {
        let y = frame.to_px(frame.x_range.min, *tick).y;
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
            &format_tick(*tick),
            point(plot.origin.x - px(6.), y - px(7.)),
            theme::muted(),
            Align::Right,
        );
    }
    let x_ticks = Scale::Linear.ticks(
        frame.x_range,
        (f32::from(plot.size.width) / 90.).max(2.) as usize,
    );
    for tick in &x_ticks {
        let x = frame.to_px(*tick, frame.y_range.min).x;
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
            &format_tick(*tick),
            point(x, plot.origin.y + plot.size.height + px(3.)),
            theme::muted(),
            Align::Center,
        );
    }

    window.with_content_mask(Some(ContentMask { bounds: plot }), |window| {
        for s in &series {
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
    let mut x_label: Option<f64> = None;
    for s in &series {
        let Some((x, y)) = s.hover else {
            continue;
        };
        x_label.get_or_insert(x);
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
        let label = format!("{}  {}", s.name, format_value(y));
        paint_text(
            window,
            cx,
            &label,
            point(plot.origin.x + px(6.), row_y),
            s.color,
            Align::Left,
        );
        row_y += px(14.);
    }
    if let Some(x) = x_label {
        let anchor = point(hover_x, plot.origin.y + plot.size.height - px(14.));
        paint_text(
            window,
            cx,
            &format!("step {}", format_tick(x)),
            anchor,
            theme::text(),
            Align::Center,
        );
    }
}

fn layout(
    workspace: &Entity<Workspace>,
    metric: &str,
    plot: Bounds<Pixels>,
    hover_x: Option<Pixels>,
    cx: &App,
) -> Option<(Frame, Vec<Series>)> {
    let ws = workspace.read(cx);
    let y_scale = if ws.log_y.contains(metric) {
        Scale::Log10
    } else {
        Scale::Linear
    };
    let weight = ws.smoothing_weight();

    struct Raw<'a> {
        name: &'a str,
        color: Hsla,
        xs: &'a [f64],
        ys: Cow<'a, [f64]>,
        raw: Option<&'a [f64]>,
    }
    let mut x_range: Option<Range> = None;
    let mut y_range: Option<Range> = None;
    let mut raws = Vec::new();
    for run in ws.selected_runs() {
        let Some(data) = run.metrics.get(metric) else {
            continue;
        };
        let (ys, raw): (Cow<[f64]>, Option<&[f64]>) = if weight > 0. {
            (Cow::Owned(ema(&data.y, weight)), Some(&data.y))
        } else {
            (Cow::Borrowed(&data.y), None)
        };
        let positive = |v: &f64| y_scale == Scale::Linear || *v > 0.;
        x_range = merge(x_range, Range::of(data.x.iter().copied()));
        y_range = merge(y_range, Range::of(ys.iter().copied().filter(positive)));
        raws.push(Raw {
            name: &run.name,
            color: theme::run_color(run.color),
            xs: &data.x,
            ys,
            raw,
        });
    }
    let x_range = x_range?.non_degenerate();
    let y_range = match y_scale {
        Scale::Linear => y_range?.non_degenerate().padded(0.05),
        Scale::Log10 => y_range?.non_degenerate(),
    };
    let frame = Frame {
        plot,
        x_range,
        y_range,
        y_scale,
    };
    let columns = f32::from(plot.size.width) as usize;
    let hover_value = hover_x.map(|x| frame.x_at(x));
    let series = raws
        .iter()
        .map(|r| Series {
            name: r.name.to_string(),
            color: r.color,
            line: decimate(r.xs, &r.ys, x_range, columns),
            raw: r.raw.map(|ys| decimate(r.xs, ys, x_range, columns)),
            hover: hover_value
                .and_then(|x| nearest(r.xs, x))
                .map(|i| (r.xs[i], r.ys[i])),
        })
        .collect();
    Some((frame, series))
}

fn merge(acc: Option<Range>, next: Option<Range>) -> Option<Range> {
    match (acc, next) {
        (Some(a), Some(b)) => Some(a.union(b)),
        (a, b) => a.or(b),
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

fn format_value(v: f64) -> String {
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
