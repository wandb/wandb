//! Colors. The base palette is W&B's "moon" scale plus leet's dark run palette
//! (`core/internal/leet/styles.go`).

use gpui::{Hsla, rgb};

pub fn bg() -> Hsla {
    rgb(0x171A1F).into()
}
pub fn panel() -> Hsla {
    rgb(0x1D2127).into()
}
pub fn border() -> Hsla {
    rgb(0x2B3038).into()
}
pub fn grid() -> Hsla {
    rgb(0x252A32).into()
}
pub fn cursor() -> Hsla {
    rgb(0x2C323C).into()
}
pub fn text() -> Hsla {
    rgb(0xD8DBE0).into()
}
pub fn muted() -> Hsla {
    rgb(0x8A8D91).into()
}
pub fn accent() -> Hsla {
    rgb(0xFCBC32).into()
}
pub fn focus() -> Hsla {
    rgb(0x58D3DB).into()
}
pub fn failed() -> Hsla {
    rgb(0xFF7A88).into()
}

const RUN_PALETTE: [u32; 9] = [
    0x58D3DB, 0x5ED6A4, 0xFCA36F, 0xFF7A88, 0x7DB1FA, 0xBBE06B, 0xFFCF4D, 0xE180FF, 0xB199FF,
];

pub fn run_color(ix: usize) -> Hsla {
    rgb(RUN_PALETTE[ix % RUN_PALETTE.len()]).into()
}

pub const FONT: &str = if cfg!(target_os = "macos") {
    "Menlo"
} else {
    "monospace"
};
