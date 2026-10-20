//! The scrollable help screen.

use crossterm::event::{KeyCode, KeyEvent};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span};
use unicode_width::UnicodeWidthStr;

use crate::keybindings::{
    HelpCategory, run_key_bindings, symon_key_bindings, workspace_key_bindings,
};
use crate::theme::{
    COLOR_HEADING, COLOR_SUBHEADING, COLOR_TEXT, LEET_ART, STATUS_BAR_HEIGHT, WANDB_ART,
};

/// Which top-level view is active.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ViewMode {
    Workspace,
    Run,
    Symon,
}

const HELP_KEY_COL_WIDTH: usize = 24;
const HELP_MARGIN_LEFT: u16 = 2;
const HELP_MARGIN_TOP: u16 = 1;

/// A single entry in the help screen.
struct HelpEntry {
    key: String,
    description: String,
}

impl HelpEntry {
    fn blank() -> Self {
        Self {
            key: String::new(),
            description: String::new(),
        }
    }
}

/// The help screen: a scrollable list of key bindings and tips.
pub struct HelpModel {
    active: bool,
    width: u16,
    height: u16,
    mode: ViewMode,
    scroll: usize,
    lines: Vec<Line<'static>>,
}

impl HelpModel {
    pub fn new() -> Self {
        Self {
            active: false,
            width: 80,
            height: 20,
            mode: ViewMode::Workspace,
            scroll: 0,
            lines: Vec::new(),
        }
    }

    pub fn set_mode(&mut self, mode: ViewMode) {
        self.mode = mode;
        if self.active {
            self.regenerate();
        }
    }

    pub fn set_size(&mut self, width: u16, height: u16) {
        self.width = width;
        self.height = height.saturating_sub(STATUS_BAR_HEIGHT);
        if self.active {
            self.regenerate();
        }
    }

    pub fn toggle(&mut self) {
        self.active = !self.active;
        if self.active {
            self.scroll = 0;
            self.regenerate();
        }
    }

    pub fn is_active(&self) -> bool {
        self.active
    }

    fn viewport_height(&self) -> usize {
        (self.height.saturating_sub(HELP_MARGIN_TOP)) as usize
    }

    fn max_scroll(&self) -> usize {
        self.lines.len().saturating_sub(self.viewport_height())
    }

    /// Handles a key press while the help screen is active. Returns true
    /// while the help screen remains open (i.e. the key was consumed).
    pub fn handle_key(&mut self, key: &KeyEvent) -> bool {
        if !self.active {
            return false;
        }
        match key.code {
            KeyCode::Char('h') | KeyCode::Char('?') | KeyCode::Esc => {
                self.toggle();
            }
            KeyCode::Up | KeyCode::Char('k') => {
                self.scroll = self.scroll.saturating_sub(1);
            }
            KeyCode::Down | KeyCode::Char('j') => {
                self.scroll = (self.scroll + 1).min(self.max_scroll());
            }
            KeyCode::PageUp | KeyCode::Char('b') => {
                self.scroll = self.scroll.saturating_sub(self.viewport_height());
            }
            KeyCode::PageDown | KeyCode::Char(' ') | KeyCode::Char('f') => {
                self.scroll = (self.scroll + self.viewport_height()).min(self.max_scroll());
            }
            KeyCode::Home | KeyCode::Char('g') => {
                self.scroll = 0;
            }
            KeyCode::End | KeyCode::Char('G') => {
                self.scroll = self.max_scroll();
            }
            _ => {}
        }
        true
    }

    /// Scrolls the help screen by mouse wheel.
    pub fn handle_wheel(&mut self, up: bool) {
        if up {
            self.scroll = self.scroll.saturating_sub(3);
        } else {
            self.scroll = (self.scroll + 3).min(self.max_scroll());
        }
    }

    pub fn render(&self, area: Rect, buf: &mut Buffer) {
        if !self.active {
            return;
        }
        let x = area.x + HELP_MARGIN_LEFT;
        let mut y = area.y + HELP_MARGIN_TOP;
        let width = area.width.saturating_sub(HELP_MARGIN_LEFT);
        let bottom = area.y + self.height.min(area.height);

        for line in self.lines.iter().skip(self.scroll) {
            if y >= bottom {
                break;
            }
            buf.set_line(x, y, line, width);
            y += 1;
        }
    }

    fn regenerate(&mut self) {
        let art_style = Style::new().fg(COLOR_HEADING).add_modifier(Modifier::BOLD);
        let key_style = Style::new()
            .fg(COLOR_SUBHEADING.color())
            .add_modifier(Modifier::BOLD);
        let desc_style = Style::new().fg(COLOR_TEXT.color());
        let section_style = Style::new().fg(COLOR_HEADING).add_modifier(Modifier::BOLD);

        let mut lines = Vec::new();

        for art_line in joined_art_lines() {
            lines.push(Line::from(Span::styled(art_line, art_style)));
        }
        lines.push(Line::default());

        for entry in self.entries_for_mode() {
            if entry.key.is_empty() {
                lines.push(Line::default());
            } else if entry.description.is_empty() {
                lines.push(Line::from(Span::styled(entry.key, section_style)));
            } else {
                let pad = HELP_KEY_COL_WIDTH.saturating_sub(entry.key.width());
                lines.push(Line::from(vec![
                    Span::styled(entry.key, key_style),
                    Span::raw(" ".repeat(pad)),
                    Span::styled(entry.description, desc_style),
                ]));
            }
        }

        self.lines = lines;
    }

    fn entries_for_mode(&self) -> Vec<HelpEntry> {
        let mut entries = vec![
            HelpEntry {
                key: "── W&B LEET: Lightweight Experiment Exploration Tool ──".to_string(),
                description: String::new(),
            },
            HelpEntry {
                key: "version".to_string(),
                description: env!("CARGO_PKG_VERSION").to_string(),
            },
            HelpEntry {
                key: "view".to_string(),
                description: self.mode_label().to_string(),
            },
            HelpEntry::blank(),
        ];

        match self.mode {
            ViewMode::Workspace => {
                entries.extend(entries_from_categories(&workspace_key_bindings()));
                entries.extend(tips_entries());
            }
            ViewMode::Run => {
                entries.extend(entries_from_categories(&run_key_bindings()));
                entries.extend(tips_entries());
            }
            ViewMode::Symon => {
                entries.extend(entries_from_categories(&symon_key_bindings()));
                entries.extend(symon_tips_entries());
            }
        }

        entries
    }

    fn mode_label(&self) -> &'static str {
        match self.mode {
            ViewMode::Workspace => "workspace",
            ViewMode::Run => "single run",
            ViewMode::Symon => "symon",
        }
    }
}

impl Default for HelpModel {
    fn default() -> Self {
        Self::new()
    }
}

/// Joins the W&B and LEET art blocks side by side.
fn joined_art_lines() -> Vec<String> {
    let wandb: Vec<&str> = WANDB_ART.trim_matches('\n').lines().collect();
    let leet: Vec<&str> = LEET_ART.trim_matches('\n').lines().collect();
    let wandb_width = wandb.iter().map(|l| l.width()).max().unwrap_or(0);

    let rows = wandb.len().max(leet.len());
    (0..rows)
        .map(|i| {
            let left = wandb.get(i).copied().unwrap_or("");
            let right = leet.get(i).copied().unwrap_or("");
            format!("{left:<w$}    {right}", w = wandb_width)
        })
        .collect()
}

fn entries_from_categories(categories: &[HelpCategory]) -> Vec<HelpEntry> {
    let mut entries = Vec::new();
    for category in categories {
        entries.push(HelpEntry {
            key: category.name.to_string(),
            description: String::new(),
        });
        for binding in &category.bindings {
            entries.push(HelpEntry {
                key: binding.keys.join(", "),
                description: binding.description.to_string(),
            });
        }
        entries.push(HelpEntry::blank());
    }
    entries
}

fn tips_entries() -> Vec<HelpEntry> {
    vec![
        HelpEntry {
            key: "Tips".to_string(),
            description: String::new(),
        },
        HelpEntry {
            key: "Runs filter".to_string(),
            description: "Bare terms search run key/name/id/project/tags/notes. \
                Qualifiers: project:, name:, id:, tag:, note:, config:, cfg.<path>:, has:. \
                Boolean: space/AND, OR or |, -/!/NOT."
                .to_string(),
        },
        HelpEntry {
            key: "Runs filter example".to_string(),
            description: "project:vision tag:baseline cfg.lr>=1e-3 -note:debug | project:nlp"
                .to_string(),
        },
        HelpEntry::blank(),
    ]
}

fn symon_tips_entries() -> Vec<HelpEntry> {
    vec![
        HelpEntry {
            key: "Tips".to_string(),
            description: String::new(),
        },
        HelpEntry {
            key: "SYMON".to_string(),
            description: "Live system monitor".to_string(),
        },
        HelpEntry::blank(),
    ]
}
