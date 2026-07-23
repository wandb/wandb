//! The terminal application shell: event loop, terminal lifecycle, and
//! top-level view routing (Workspace ↔ Run).

use std::io::{self, Write};
use std::sync::mpsc::{Receiver, RecvTimeoutError, Sender, channel};
use std::time::{Duration, Instant};

use crossterm::event::{
    DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers,
    MouseEvent, MouseEventKind,
};
use crossterm::{cursor, execute, terminal};
use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;

use crate::config::{ConfigManager, STARTUP_MODE_SINGLE_RUN_LATEST, leet_config_path};
use crate::help::{HelpModel, ViewMode};
use crate::msg::Msg;
use crate::run::{RunAction, RunView};
use crate::store::live::run_wandb_file;
use crate::workspace::{WorkspaceAction, WorkspaceView};

/// Animation frame interval (matches the Go implementation).
const ANIMATION_FRAME: Duration = Duration::from_millis(15);

/// Idle event-poll timeout when nothing is animating.
const IDLE_POLL: Duration = Duration::from_millis(100);

/// The conventional symlink name that wandb creates to the latest run.
const LATEST_RUN_LINK_NAME: &str = "latest-run";

/// Which top-level view is active.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    Workspace,
    Run,
}

/// The top-level application: owns the views and shared chrome.
pub struct App {
    config: ConfigManager,
    help: HelpModel,
    workspace: WorkspaceView,
    run: Option<RunView>,
    mode: Mode,
    tx: Option<Sender<Msg>>,
    width: i32,
    height: i32,
    should_quit: bool,
}

impl App {
    /// Creates the app.
    ///
    /// Starts in single-run view when `run_file` is given, or when the
    /// configured startup mode is `single_run_latest` and a latest run can be
    /// resolved. Otherwise starts in the workspace.
    pub fn new(wandb_dir: String, run_file: Option<String>) -> Self {
        Self::with_config(wandb_dir, run_file, ConfigManager::new(leet_config_path()))
    }

    fn with_config(wandb_dir: String, run_file: Option<String>, config: ConfigManager) -> Self {
        let run_file = run_file.or_else(|| {
            if config.config().startup_mode == STARTUP_MODE_SINGLE_RUN_LATEST {
                wandb_file_from_latest_run_link(&wandb_dir)
            } else {
                None
            }
        });

        let workspace = WorkspaceView::new(wandb_dir, &config);
        let run = run_file.map(|file| RunView::new(file, &config));
        let mode = if run.is_some() {
            Mode::Run
        } else {
            Mode::Workspace
        };

        let mut help = HelpModel::new();
        help.set_mode(match mode {
            Mode::Workspace => ViewMode::Workspace,
            Mode::Run => ViewMode::Run,
        });

        Self {
            config,
            help,
            workspace,
            run,
            mode,
            tx: None,
            width: 0,
            height: 0,
            should_quit: false,
        }
    }

    /// Creates an app showing a single run from a `.wandb` file.
    pub fn new_single_run(wandb_dir: String, run_file: String) -> Self {
        Self::new(wandb_dir, Some(run_file))
    }

    /// Runs the blocking terminal event loop.
    pub fn run(&mut self) -> io::Result<()> {
        let mut stdout = io::stdout();
        terminal::enable_raw_mode()?;

        // Detect the real background before the event loop owns stdin, so
        // adaptive colors and the zebra tint match the terminal.
        crate::theme::set_terminal_background(crate::termbg::query_background(150));

        execute!(
            stdout,
            terminal::EnterAlternateScreen,
            EnableMouseCapture,
            cursor::Hide
        )?;

        let result = self.event_loop();

        let mut stdout = io::stdout();
        let _ = execute!(
            stdout,
            cursor::Show,
            DisableMouseCapture,
            terminal::LeaveAlternateScreen
        );
        let _ = terminal::disable_raw_mode();
        result
    }

    fn event_loop(&mut self) -> io::Result<()> {
        let backend = CrosstermBackend::new(io::stdout());
        let mut terminal = Terminal::new(backend)?;

        let (tx, rx) = channel::<Msg>();
        spawn_input_thread(tx.clone());
        self.workspace.start(tx.clone());
        if let Some(run) = &mut self.run {
            run.start(tx.clone());
        }
        self.tx = Some(tx);

        let size = terminal.size()?;
        self.handle_resize(size.width as i32, size.height as i32);

        let mut needs_draw = true;
        let mut animating = false;
        let mut last_frame = Instant::now();

        while !self.should_quit {
            // Single blocking wait point: input events and reader messages
            // arrive on one channel, so keys are handled the moment they
            // arrive. While animating, wake for the next frame instead.
            let timeout = if needs_draw {
                Duration::ZERO
            } else if animating {
                ANIMATION_FRAME.saturating_sub(last_frame.elapsed())
            } else {
                IDLE_POLL
            };
            needs_draw |= self.drain_msgs(&rx, timeout);

            // Advance animations at the frame rate.
            let now = Instant::now();
            if animating && now.duration_since(last_frame) >= ANIMATION_FRAME {
                needs_draw = true;
            }

            if needs_draw {
                animating = self.tick(now);
                last_frame = now;
                terminal.draw(|frame| {
                    let area = frame.area();
                    let buf = frame.buffer_mut();
                    if self.help.is_active() {
                        self.help.render(area, buf);
                    } else {
                        match self.mode {
                            Mode::Run => {
                                if let Some(run) = &mut self.run {
                                    run.render(area, buf, &self.config);
                                }
                            }
                            Mode::Workspace => {
                                self.workspace.render(area, buf, &self.config);
                            }
                        }
                    }
                })?;
                self.flush_media_output()?;
                needs_draw = animating;
            }
        }

        if let Some(run) = &mut self.run {
            run.cleanup();
        }
        self.workspace.cleanup();
        Ok(())
    }

    fn tick(&mut self, now: Instant) -> bool {
        match self.mode {
            Mode::Run => self.run.as_mut().is_some_and(|run| run.tick(now)),
            Mode::Workspace => self.workspace.tick(now),
        }
    }

    fn handle_resize(&mut self, width: i32, height: i32) {
        self.width = width;
        self.height = height;
        self.workspace.handle_resize(width, height);
        if let Some(run) = &mut self.run {
            run.handle_resize(width, height);
        }
        self.help.set_size(width as u16, height as u16);
    }

    /// Writes any pending raw escape sequences (Kitty graphics) after a draw.
    fn flush_media_output(&mut self) -> io::Result<()> {
        let pending = match self.mode {
            Mode::Run => self
                .run
                .as_mut()
                .and_then(|run| run.media_pane.renderer.take_pending_output()),
            Mode::Workspace => self.workspace.media_pane.renderer.take_pending_output(),
        };
        if let Some(out) = pending {
            let mut stdout = io::stdout();
            stdout.write_all(out.as_bytes())?;
            stdout.flush()?;
        }
        Ok(())
    }

    /// Waits up to `timeout` for reader messages and drains everything
    /// pending. Returns whether any message was processed.
    fn drain_msgs(&mut self, rx: &Receiver<Msg>, timeout: Duration) -> bool {
        let first = if timeout.is_zero() {
            rx.try_recv().ok()
        } else {
            match rx.recv_timeout(timeout) {
                Ok(msg) => Some(msg),
                Err(RecvTimeoutError::Timeout) | Err(RecvTimeoutError::Disconnected) => None,
            }
        };
        let Some(first) = first else { return false };

        self.route_msg(first);
        while let Ok(msg) = rx.try_recv() {
            self.route_msg(msg);
        }
        true
    }

    /// Routes a message to the input handler or the view that owns its
    /// source.
    ///
    /// The workspace keeps consuming data messages while the single-run view
    /// is active so its background state stays current.
    fn route_msg(&mut self, msg: Msg) {
        match msg {
            Msg::Term(event) => self.handle_event(event),
            Msg::Batch { source_id, .. } | Msg::ReaderError { source_id, .. } => {
                if let Some(run) = &mut self.run
                    && run.source_id() == Some(source_id)
                {
                    run.handle_msg(msg);
                    return;
                }
                self.workspace.handle_msg(msg, &self.config);
            }
            _ => self.workspace.handle_msg(msg, &self.config),
        }
    }

    fn handle_event(&mut self, event: Event) {
        match event {
            Event::Key(key) if key.kind != KeyEventKind::Release => self.handle_key(&key),
            Event::Mouse(mouse) => self.handle_mouse(&mouse),
            Event::Resize(w, h) => self.handle_resize(w as i32, h as i32),
            _ => {}
        }
    }

    fn handle_mouse(&mut self, mouse: &MouseEvent) {
        if self.help.is_active() {
            match mouse.kind {
                MouseEventKind::ScrollUp => self.help.handle_wheel(true),
                MouseEventKind::ScrollDown => self.help.handle_wheel(false),
                _ => {}
            }
            return;
        }
        match self.mode {
            Mode::Run => {
                if let Some(run) = &mut self.run {
                    run.handle_mouse(mouse, &mut self.config);
                }
            }
            Mode::Workspace => self.workspace.handle_mouse(mouse, &mut self.config),
        }
    }

    /// Reports whether any sub-component is capturing free-form keyboard
    /// input (filter text, grid config digit, etc.).
    fn is_awaiting_input(&self) -> bool {
        if self.config.is_awaiting_grid_config() {
            return true;
        }
        match self.mode {
            Mode::Workspace => self.workspace.is_filtering(),
            Mode::Run => self.run.as_ref().is_some_and(|run| run.is_filtering()),
        }
    }

    fn handle_key(&mut self, key: &KeyEvent) {
        if self.help.is_active() {
            if matches!(key.code, KeyCode::Char('q'))
                || (key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL))
            {
                self.should_quit = true;
                return;
            }
            self.help.handle_key(key);
            return;
        }

        // Snapshot before sub-views consume the key — a filter's Enter exits
        // filter mode, so checking after would miss it.
        let awaiting_input = self.is_awaiting_input();

        // Help toggle (outside filter/config input).
        if matches!(key.code, KeyCode::Char('h') | KeyCode::Char('?')) && !awaiting_input {
            self.help.set_mode(match self.mode {
                Mode::Workspace => ViewMode::Workspace,
                Mode::Run => ViewMode::Run,
            });
            self.help.toggle();
            return;
        }

        match self.mode {
            Mode::Workspace => match self.workspace.handle_key(key, &mut self.config) {
                WorkspaceAction::Quit => self.should_quit = true,
                WorkspaceAction::OpenRun { wandb_file, .. } => {
                    self.enter_run_view(wandb_file);
                }
                WorkspaceAction::None => {}
            },
            Mode::Run => {
                let Some(run) = &mut self.run else { return };

                // Esc returns to the workspace unless something captures it.
                if key.code == KeyCode::Esc && !awaiting_input && !run.media_fullscreen() {
                    self.exit_run_view();
                    return;
                }

                if run.handle_key(key, &mut self.config) == RunAction::Quit {
                    self.should_quit = true;
                }
            }
        }
    }

    /// Switches to single-run view for the selected run.
    fn enter_run_view(&mut self, wandb_file: String) {
        let mut run = RunView::new(wandb_file, &self.config);
        if let Some(tx) = &self.tx {
            run.start(tx.clone());
        }
        run.handle_resize(self.width, self.height);
        self.run = Some(run);
        self.mode = Mode::Run;
    }

    /// Returns to the workspace view.
    fn exit_run_view(&mut self) {
        if let Some(mut run) = self.run.take() {
            run.cleanup();
        }
        self.mode = Mode::Workspace;
        self.workspace.handle_resize(self.width, self.height);
    }
}

/// Forwards terminal input events into the UI message channel.
///
/// Input wakes the poll immediately; the timeout only paces the idle loop.
/// The thread exits when the receiver hangs up (or with the process).
fn spawn_input_thread(tx: Sender<Msg>) {
    std::thread::spawn(move || {
        loop {
            match crossterm::event::poll(Duration::from_millis(100)) {
                Ok(true) => {
                    let Ok(event) = crossterm::event::read() else {
                        return;
                    };
                    if tx.send(Msg::Term(event)).is_err() {
                        return;
                    }
                }
                Ok(false) => {}
                Err(_) => return,
            }
        }
    });
}

/// Resolves the `.wandb` file behind the `latest-run` symlink, if any.
pub(crate) fn wandb_file_from_latest_run_link(wandb_dir: &str) -> Option<String> {
    let link = std::path::Path::new(wandb_dir).join(LATEST_RUN_LINK_NAME);
    if !link.is_dir() {
        return None;
    }
    let resolved = std::fs::read_link(&link).ok()?;
    let run_dir = resolved.file_name()?.to_str()?.to_string();
    let file = run_wandb_file(wandb_dir, &run_dir)?;
    if !file.is_file() {
        return None;
    }
    Some(file.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    pub(super) fn test_app(name: &str, run_file: Option<&str>) -> App {
        let path = std::env::temp_dir().join(format!("leet-app-test-{name}.json"));
        let _ = std::fs::remove_file(&path);
        let config = ConfigManager::new(path);
        let mut app = App::with_config("wandb".to_string(), run_file.map(str::to_string), config);
        app.handle_resize(200, 50);
        app
    }

    fn key(code: KeyCode) -> KeyEvent {
        KeyEvent::new(code, KeyModifiers::NONE)
    }

    /// Runs animations to completion by ticking with a far-future instant.
    fn settle(app: &mut App) {
        let future = Instant::now() + Duration::from_secs(1);
        while app.tick(future) {}
    }

    /// End-to-end simulation against real demo data (run manually):
    /// `cargo test e2e_workspace_run_roundtrip -- --ignored --nocapture`
    #[test]
    #[ignore]
    fn e2e_workspace_run_roundtrip() {
        use std::sync::mpsc::channel;
        use std::time::Duration;

        let demo = "/Users/dduev/code/leet-demo/wandb";
        let path = std::env::temp_dir().join("leet-app-e2e.json");
        let _ = std::fs::remove_file(&path);
        let config = ConfigManager::new(path);
        let mut app = App::with_config(demo.to_string(), None, config);

        let (tx, rx) = channel::<Msg>();
        app.workspace.start(tx.clone());
        app.tx = Some(tx);
        app.handle_resize(200, 50);

        let pump = |app: &mut App, ms: u64| {
            let area = ratatui::layout::Rect::new(0, 0, 200, 50);
            let deadline = std::time::Instant::now() + Duration::from_millis(ms);
            while std::time::Instant::now() < deadline {
                while let Ok(msg) = rx.try_recv() {
                    app.route_msg(msg);
                }
                app.tick(std::time::Instant::now());
                let mut buf = ratatui::buffer::Buffer::empty(area);
                match app.mode {
                    Mode::Run => {
                        if let Some(run) = &mut app.run {
                            run.render(area, &mut buf, &app.config);
                        }
                    }
                    Mode::Workspace => app.workspace.render(area, &mut buf, &app.config),
                }
                std::thread::sleep(Duration::from_millis(10));
            }
        };

        pump(&mut app, 2000);
        assert_eq!(app.mode, Mode::Workspace);

        // Open the selected run.
        app.handle_key(&key(KeyCode::Enter));
        eprintln!("after Enter: mode={:?}", app.mode);
        assert_eq!(app.mode, Mode::Run);
        pump(&mut app, 1500);

        // Toggle the left sidebar and let the animation finish.
        let w_before = app.run.as_ref().unwrap().left_sidebar.width();
        app.handle_key(&key(KeyCode::Char('[')));
        pump(&mut app, 400);
        let w_after = app.run.as_ref().unwrap().left_sidebar.width();
        eprintln!("sidebar width {w_before} -> {w_after}");
        assert_ne!(w_before, w_after);

        // Esc returns to the workspace.
        app.handle_key(&key(KeyCode::Esc));
        eprintln!("after Esc: mode={:?}", app.mode);
        assert_eq!(app.mode, Mode::Workspace);
    }

    #[test]
    fn esc_returns_to_workspace() {
        let mut app = test_app("esc", Some("/tmp/run-x.wandb"));
        assert_eq!(app.mode, Mode::Run);
        app.handle_key(&key(KeyCode::Esc));
        assert_eq!(app.mode, Mode::Workspace);
        assert!(app.run.is_none());
    }

    #[test]
    fn brackets_toggle_run_sidebars() {
        let mut app = test_app("run-brackets", Some("/tmp/run-x.wandb"));
        let before = app.config.config().left_sidebar_visible;
        app.handle_key(&key(KeyCode::Char('[')));
        assert_ne!(app.config.config().left_sidebar_visible, before);

        // Toggles are ignored mid-animation; finish it before the next one.
        settle(&mut app);

        let before = app.config.config().right_sidebar_visible;
        app.handle_key(&key(KeyCode::Char(']')));
        assert_ne!(app.config.config().right_sidebar_visible, before);
    }

    #[test]
    fn brackets_toggle_workspace_sidebars() {
        let mut app = test_app("ws-brackets", None);
        assert_eq!(app.mode, Mode::Workspace);

        let before = app.workspace.runs_sidebar_target_visible();
        app.handle_key(&key(KeyCode::Char('[')));
        assert_ne!(app.workspace.runs_sidebar_target_visible(), before);

        let before = app.config.config().workspace_overview_visible;
        app.handle_key(&key(KeyCode::Char(']')));
        assert_ne!(app.config.config().workspace_overview_visible, before);
    }
}
