//! Port of `core/internal/leet/model.go` — the top-level app model.
//!
//! Implements [`crate::runtime::App`] (Go: `tea.Model`); the runtime owns
//! the concerns Go put on the returned `tea.View` value (window title,
//! alt screen, mouse mode) and the test-ack protocol (`testAckUpdate` /
//! `testAckView`, testmode.go).

use std::cell::RefCell;
use std::io;
use std::path::Path;
use std::rc::Rc;

use leet_charts::styles::{STATUS_BAR_PADDING, default_dark_background};
use leet_data::config::{ConfigManager, STARTUP_MODE_SINGLE_RUN_LATEST, leet_config_path};
use leet_data::test_mode;
use ratatui::layout::Size;
use ratatui::text::Text;

use crate::command::Command;
use crate::event::Event;
// PARITY: Go declares `viewMode` in model.go:15-23; the port hosts it in
// help.rs (see the note there) and re-exports it here so `model` remains the
// canonical path.
pub use crate::help::ViewMode;
use crate::help::{HelpCmd, HelpModel};
use crate::key::KeyCode;
use crate::layout::{
    LEFT, RIGHT, TOP, join_vertical, place, place_horizontal, status_bar_style, text_from_str,
};
use crate::run::{Run, RunParams};
use crate::runtime::App;
// PARITY: `extractRunID` / `runWandbFile` are declared in model.go:439-464
// but were ported into workspace.rs (which also uses them); `extract_run_id`
// is reused here, not re-declared. `run_wandb_file` is NOT reused by
// `wandb_file_from_latest_run_link` — see the filepath.Join note there.
use crate::workspace::{Workspace, extract_run_id};

/// latestRunLinkName is the conventional symlink name that wandb creates to
/// point at the most recently started run directory.
const LATEST_RUN_LINK_NAME: &str = "latest-run";

/// Model is the top-level app model.
///
/// It owns the workspace (always present) and optionally a single-run detail
/// view. The help overlay is shared across both modes.
///
/// Implements [`App`] (Go: tea.Model).
// PARITY: fields are pub(crate) — Go's package-private access from tests
// maps to crate-module access (PORTING.md Testing conventions).
pub struct Model {
    /// mode tracks which sub-model currently owns the screen and user input.
    pub(crate) mode: ViewMode,

    /// workspace is the multi-run view. It is created at startup and kept
    /// alive for the entire session so its watchers and heartbeats continue
    /// streaming data in the background while the user is in single-run view.
    // PARITY: Go stores `*Workspace`, but NewModel always sets it; the
    // `m.workspace != nil` checks (model.go:134, 274) are vacuous and drop
    // with the pointer.
    pub(crate) workspace: Workspace,

    /// run is the single-run detail view. It is `None` when the user is in
    /// workspace mode and created on-demand when they press Enter on a run.
    pub(crate) run: Option<Run>,

    /// width and height cache the latest terminal dimensions for layout.
    pub(crate) width: isize,
    pub(crate) height: isize,

    /// help is the full-screen help overlay, shared across both modes.
    pub(crate) help: HelpModel,

    /// shouldRestart is the restart flag.
    pub(crate) should_restart: bool,

    /// config is the shared application configuration (grid sizes, color
    /// schemes, sidebar visibility, etc.).
    pub(crate) config: Rc<RefCell<ConfigManager>>,

    /// Port of the `darkBackground` package global (styles.go:17-31,
    /// CONCURRENCY.md S13): update and view share one thread, so the flag
    /// lives on the model and is threaded into the sub-views explicitly.
    pub(crate) dark: bool,
    // PARITY: `logger *observability.CoreLogger` — the port logs via
    // `tracing` at the same call sites.
}

pub struct ModelParams {
    /// WandbDir is the path to the wandb directory (typically "./wandb")
    /// that contains run directories and the "latest-run" symlink.
    pub wandb_dir: String,

    /// RunParams contains information about the run to load.
    ///
    /// When RunParams is `None`, LEET starts in Config.StartupMode.
    pub run_params: Option<RunParams>,

    pub config: Option<Rc<RefCell<ConfigManager>>>,
    // PARITY: `Logger *observability.CoreLogger` — tracing.
}

impl Model {
    /// Port of Go `NewModel`.
    ///
    /// Startup behavior depends on the combination of RunFile and
    /// Config.StartupMode:
    ///
    ///   - RunFile is set → start in single-run view for that file.
    ///   - RunFile is empty + StartupModeSingleRunLatest → resolve the
    ///     "latest-run" symlink and start in single-run view.
    ///   - RunFile is empty + StartupModeWorkspaceLatest (default) → start in
    ///     workspace view; the workspace will auto-select the latest run once
    ///     the directory poll completes.
    pub fn new(mut params: ModelParams) -> Model {
        let config = params
            .config
            .take()
            .unwrap_or_else(|| Rc::new(RefCell::new(ConfigManager::new(leet_config_path()))));

        if params.run_params.is_none()
            && config.borrow().startup_mode() == STARTUP_MODE_SINGLE_RUN_LATEST
        {
            let latest = match wandb_file_from_latest_run_link(&params.wandb_dir) {
                Ok(latest) => latest,
                Err(err) => {
                    tracing::error!("model: failed to find latest run: {err}");
                    String::new()
                }
            };
            if !latest.is_empty() {
                params.run_params = Some(RunParams {
                    run_file: latest,
                    remote: None,
                });
            }
        }

        let mut m = Model {
            mode: ViewMode::Workspace,
            workspace: Workspace::new(&params.wandb_dir, Some(Rc::clone(&config))),
            run: None,
            width: 0,
            height: 0,
            help: HelpModel::new(),
            should_restart: false,
            config,
            dark: default_dark_background(),
        };

        if let Some(run_params) = params.run_params {
            m.run = Some(Run::new(run_params, Some(Rc::clone(&m.config))));
            m.mode = ViewMode::Run;
        }

        m
    }

    /// Go `SetDarkBackground` (styles.go:26-31) writes the package global;
    /// the port keeps the flag on the model and forwards it to the help
    /// overlay (which bakes colors at content generation) — the workspace
    /// and run views take it per view call.
    fn set_dark_background(&mut self, dark: bool) {
        self.dark = dark;
        self.help.set_dark_background(dark);
    }

    /// updateSubComponents forwards the message to the active sub-models.
    fn update_sub_components(&mut self, msg: &Event) -> Vec<Command> {
        let mut cmds: Vec<Command> = Vec::new();
        match self.mode {
            ViewMode::Workspace => {
                cmds.extend(self.workspace.update(msg));
            }
            ViewMode::Run => {
                // Keep the workspace's background tasks (watchers/heartbeats)
                // alive while we're in the single-run view while omitting
                // user input.
                let run_is_remote = self.run.as_ref().is_some_and(|r| r.is_remote());
                if !run_is_remote && !is_user_input_msg(msg) {
                    cmds.extend(self.workspace.update(msg));
                }
                if let Some(run) = self.run.as_mut() {
                    cmds.extend(run.update(msg));
                }
            }
            _ => {}
        }
        cmds
    }

    /// handleModeSwitch checks for Enter/Esc and transitions between views.
    ///
    /// awaitingInput must be snapshotted before sub-components process the
    /// message, because an Enter in filter mode exits the filter and would
    /// otherwise fall through to a view switch.
    ///
    /// Returns `Some` when Go returns a non-nil `tea.Cmd` (model.go:175-177:
    /// the caller then returns it INSTEAD of the sub-component batch). The
    /// exit path's teardown commands — Go side effects of `exitRunView`
    /// behind its nil return — are pushed into `cmds` and ride the normal
    /// batch.
    fn handle_mode_switch(
        &mut self,
        msg: &Event,
        awaiting_input: bool,
        cmds: &mut Vec<Command>,
    ) -> Option<Vec<Command>> {
        let Event::Key(key_msg) = msg else {
            return None;
        };

        match self.mode {
            ViewMode::Workspace => {
                if key_msg.code == KeyCode::Enter
                    && !awaiting_input
                    && self.workspace.run_selector_active()
                {
                    return self.enter_run_view();
                }
            }
            ViewMode::Run => {
                let run_captures_esc = self.run.as_ref().is_some_and(|r| r.media_fullscreen());
                if key_msg.code == KeyCode::Esc && !awaiting_input && !run_captures_esc {
                    // PARITY: Go `exitRunView` always returns nil; its
                    // cleanup side effects surface here as commands.
                    cmds.extend(self.exit_run_view());
                }
            }
            _ => {}
        }
        None
    }

    /// ShouldRestart reports whether the application should perform a full
    /// restart. (Also on the [`App`] impl; kept inherent so callers holding
    /// a concrete `Model` need no trait import.)
    pub fn should_restart(&self) -> bool {
        self.should_restart
    }

    fn is_remote_run_mode(&self) -> bool {
        self.mode == ViewMode::Run && self.run.as_ref().is_some_and(|r| r.is_remote())
    }

    // --------------------------------------------------------------------
    // Input state helpers
    // --------------------------------------------------------------------

    /// isAwaitingUserInput reports whether any sub-component is capturing
    /// free-form keyboard input (filter text, grid config digit, etc.).
    ///
    /// When true, global key bindings like Enter (mode switch) and h (help
    /// toggle) must be suppressed so keystrokes reach the active input.
    fn is_awaiting_user_input(&self) -> bool {
        // PARITY: Go nil-checks m.config (model.go:293); always set here.
        if self.config.borrow().is_awaiting_grid_config() {
            return true;
        }
        match self.mode {
            ViewMode::Workspace => self.workspace.is_filtering(),
            ViewMode::Run => self.run.as_ref().is_some_and(|r| r.is_filtering()),
            _ => false,
        }
    }

    // --------------------------------------------------------------------
    // Mode transitions
    // --------------------------------------------------------------------

    /// handleHelp centralizes help toggle and routing while active.
    ///
    /// Returns `Some(batch)` where Go returns `handled == true`.
    fn handle_help(&mut self, msg: &Event) -> Option<Vec<Command>> {
        if self.is_awaiting_user_input() {
            return None;
        }

        // Toggle on 'h' / '?'
        if let Event::Key(km) = msg {
            // PARITY: Go matches on `km.Code` alone (model.go:333-336), so
            // modified presses (ctrl+h, alt+h, shift → 'H') toggle too.
            if matches!(km.code, KeyCode::Char('h' | '?')) {
                self.help.set_mode(self.mode);
                self.help.toggle();
                return Some(Vec::new());
            }
        }

        // When help is visible, it owns key/mouse events.
        if self.help.is_active() && matches!(msg, Event::Key(_) | Event::Mouse(_)) {
            let cmd = match self.help.update(msg) {
                Some(HelpCmd::Quit) => vec![Command::Quit],
                None => Vec::new(),
            };
            return Some(cmd);
        }
        None
    }

    fn handle_restart(&mut self, msg: &Event) -> Option<Vec<Command>> {
        if let Event::Key(km) = msg
            && km.key_string() == "alt+r"
        {
            tracing::debug!("model: restart requested");
            self.should_restart = true;

            return Some(vec![Command::Quit]);
        }
        None
    }

    /// renderHelpScreen renders the help screen.
    fn render_help_screen(&self) -> Text<'static> {
        let help_view = self.help.view();

        let help_text = "h: help";
        let space_for_help = (self.width as i64 - 2 * STATUS_BAR_PADDING).max(0);
        let right_aligned = place_horizontal(space_for_help, RIGHT, text_from_str(help_text));

        let status_bar = status_bar_style(self.dark)
            .width(self.width as i64)
            .max_width(self.width as i64)
            .render_text(right_aligned);

        let content = join_vertical(LEFT, vec![help_view, status_bar]);
        place(self.width as i64, self.height as i64, LEFT, TOP, content)
    }

    /// enterRunView switches to single-run view for the selected run.
    fn enter_run_view(&mut self) -> Option<Vec<Command>> {
        let wandb_file = self.workspace.selected_run_wandb_file();
        if wandb_file.is_empty() {
            return None;
        }

        let mut run = Run::new(
            RunParams {
                run_file: wandb_file,
                remote: None,
            },
            Some(Rc::clone(&self.config)),
        );
        self.mode = ViewMode::Run;

        // Share the workspace's media store so data persists across transitions.
        let run_key = self.workspace.selected_run_key();
        if let Some(store) = self.workspace.media_store_for_run(&run_key) {
            run.set_media_store(store);
        }
        // Restore saved media pane view state (scroll position, selection).
        if let Some(state) = self.workspace.load_media_pane_state(&run_key) {
            run.media_pane.restore_view_state(state);
        }

        // Initialize with current dimensions and start loading.
        let mut cmds = run.init();
        // PARITY: the synthetic `tea.WindowSizeMsg` cmd (model.go:406-408).
        cmds.push(Command::Emit(Box::new(Event::Resize {
            width: self.width,
            height: self.height,
        })));
        self.run = Some(run);
        Some(cmds)
    }

    /// exitRunView returns to the workspace view.
    ///
    /// Go returns a nil `tea.Cmd`; the returned commands here are the Rust
    /// materialization of `run.Cleanup()`'s side effects (heartbeat cancel,
    /// reader close — CONCURRENCY.md §2.9) and must be dispatched.
    fn exit_run_view(&mut self) -> Vec<Command> {
        // Do not exit to workspace view for remote projects.
        if self.run.as_ref().is_some_and(|r| r.is_remote()) {
            return Vec::new();
        }

        let mut cmds = Vec::new();
        if let Some(mut run) = self.run.take() {
            // Save media pane view state for later restoration.
            let run_key = self.workspace.selected_run_key();
            if !run_key.is_empty() {
                self.workspace
                    .save_media_pane_state(&run_key, run.media_pane.save_view_state());
                // Force the workspace pane to re-sync from the saved per-run state on return.
                self.workspace.current_media_run_key = String::new();
            }
            cmds = run.cleanup();
            // Go `m.run = nil` — `run` drops here.
        }

        self.mode = ViewMode::Workspace;
        cmds
    }

    /// Drains the media panes' coalesced prepare requests recorded by the
    /// draw that just completed (Go's `mediaPanePrepareMsg` pump,
    /// run.go:226-230 / workspace.go:221-224). Called by the runtime right
    /// after every draw ([`crate::runtime::App::after_draw`]) — Go's cap-1
    /// prepare channel wakes the loop with a dedicated message right after
    /// the render without waiting for further input, and a lone `k` (Kitty
    /// toggle) must render the same way here.
    fn drain_after_draw(&mut self) -> Vec<Command> {
        let mut cmds = self.workspace.after_draw();
        if let Some(run) = self.run.as_mut() {
            cmds.extend(run.after_draw());
        }
        cmds
    }
}

impl App for Model {
    /// Init returns the initial commands for the top-level model.
    ///
    /// The workspace is initialized unless LEET starts in remote single-run
    /// mode. If starting in single-run mode, the run's reader and watcher
    /// commands are also started.
    fn init(&mut self) -> Vec<Command> {
        let mut cmds: Vec<Command> = Vec::new();
        if test_mode::enabled() {
            // No OSC round-trip under the test harness; the background is forced.
            // PARITY: Go `SetDarkBackground(!testForcedLightBackground())`
            // (model.go:128) == `default_dark_background()`.
            self.set_dark_background(default_dark_background());
        } else {
            cmds.push(Command::RequestBackgroundColor);
        }

        // Workspace always exists; initialize its long‑running commands.
        if !self.is_remote_run_mode() {
            cmds.extend(self.workspace.init());
        }

        if self.mode == ViewMode::Run
            && let Some(run) = self.run.as_mut()
        {
            cmds.extend(run.init());
        }

        cmds
    }

    /// Update handles incoming events and updates the model accordingly.
    fn update(&mut self, event: Event) -> Vec<Command> {
        // PARITY: `defer testAckUpdate(msg)` (model.go:151) is the runtime's
        // job (runtime.rs `deliver`).
        let msg = &event;

        let mut cmds: Vec<Command> = Vec::new();

        if let Event::Resize { width, height } = msg {
            self.width = *width;
            self.height = *height;
            self.help.set_size(*width as i64, *height as i64);
        }

        if let Event::BackgroundColor { is_dark, rgb } = msg {
            self.set_dark_background(*is_dark);
            // PARITY: Go's runs-list zebra stripe re-queries the terminal
            // via termenv on first render (styles.go `initTerminalBg`); the
            // port forwards the same OSC 11 answer to the workspace. No RGB
            // (a reply form termenv rejects) keeps the fallback, like Go's
            // `termBgDetected == false`.
            if let Some(rgb) = rgb {
                self.workspace.set_terminal_bg(*rgb);
            }
        }

        if let Some(mut help_cmds) = self.handle_help(msg) {
            cmds.append(&mut help_cmds);
            return cmds;
        }

        if let Some(mut restart_cmds) = self.handle_restart(msg) {
            cmds.append(&mut restart_cmds);
            return cmds;
        }

        // Snapshot before sub-models consume the key — a filter's Enter
        // exits filter mode, so checking after would miss it.
        let awaiting_input = self.is_awaiting_user_input();

        let mut sub_cmds = self.update_sub_components(msg);

        if let Some(mut switch_cmds) = self.handle_mode_switch(msg, awaiting_input, &mut sub_cmds) {
            // PARITY: Go returns the mode-switch cmd alone, DROPPING the
            // sub-component batch (model.go:175-177).
            cmds.append(&mut switch_cmds);
            return cmds;
        }

        cmds.extend(sub_cmds);
        cmds
    }

    /// View renders the UI based on the data in the model.
    // PARITY: Go sizes from the dims cached off `tea.WindowSizeMsg`
    // (model.go:49), not from the frame; the runtime's `size` is unused.
    fn view(&mut self, _size: Size) -> Text<'static> {
        // PARITY: `defer testAckView()` (model.go:237) is the runtime's job.
        if self.help.is_active() {
            self.render_help_screen()
        } else {
            match self.mode {
                ViewMode::Workspace => self.workspace.view(self.dark),
                ViewMode::Run => match self.run.as_mut() {
                    Some(run) => run.view(self.dark),
                    // PARITY: unreachable (mode == Run ⇒ run set); Go would
                    // nil-panic here.
                    None => Text::default(),
                },
                // PARITY: Go's switch leaves `vs` empty for
                // undefined/symon modes.
                _ => Text::default(),
            }
        }
        // PARITY: v.WindowTitle / v.AltScreen / v.MouseMode
        // (model.go:253-255) are applied by the runtime (setup_terminal).
    }

    /// The Go view's `WindowTitle` (model.go:253), applied once by the
    /// runtime.
    fn window_title(&self) -> &str {
        "wandb leet"
    }

    /// See [`Model::drain_after_draw`] — Go's prepare pump delivery point.
    fn after_draw(&mut self) -> Vec<Command> {
        self.drain_after_draw()
    }

    /// ShouldRestart reports whether the application should perform a full
    /// restart.
    fn should_restart(&self) -> bool {
        Model::should_restart(self)
    }

    /// Cleanup releases resources held by the model's sub-views: file
    /// watchers, heartbeat timers, and open .wandb readers.
    ///
    /// Safe to call multiple times. Called after the program exits, e.g.
    /// before a full restart.
    fn cleanup(&mut self) {
        // The returned teardown commands (heartbeat cancels, reader closes)
        // are dropped: cleanup runs as the session's scheduler and readers
        // are being torn down with the runtime anyway (CONCURRENCY.md §2.9);
        // the watcher unregistrations Go performs here happen inside
        // `cleanup` as direct calls.
        if let Some(run) = self.run.as_mut() {
            let _ = run.cleanup();
        }
        let _ = self.workspace.cleanup();
    }
}

/// isUserInputMsg reports whether msg originates from direct user interaction.
///
/// Used to gate which messages reach the workspace while the user is in
/// single-run mode: user input goes exclusively to the run, while data
/// messages (file changes, heartbeats, batched records) are forwarded to
/// the workspace to keep its background state current.
fn is_user_input_msg(msg: &Event) -> bool {
    matches!(msg, Event::Key(_) | Event::Mouse(_))
}

// --------------------------------------------------------------------
// Path resolution utilities
// --------------------------------------------------------------------
// (`extractRunID` / `runWandbFile` live in workspace.rs — see the import
// note at the top.)

fn wandb_file_from_latest_run_link(wandb_dir: &str) -> io::Result<String> {
    // PARITY: Go `filepath.Abs` also cleans the path lexically;
    // `std::path::absolute` resolves against the cwd without collapsing
    // `..` — identical for the paths leet passes.
    let latest_run_path = std::path::absolute(Path::new(wandb_dir).join(LATEST_RUN_LINK_NAME))?;

    let info = std::fs::metadata(&latest_run_path)?; // follows symlinks
    if !info.is_dir() {
        // PARITY: Go returns ("", nil) when the stat succeeds but the
        // target is not a directory (model.go:472-475).
        return Ok(String::new());
    }

    let resolved_latest_run_path = std::fs::read_link(&latest_run_path)?;

    // Inlined `runWandbFile` (model.go:458-464) with Go-true join semantics.
    //
    // PARITY(review): Go's filepath.Join CONCATENATES its elements and
    // lexically cleans the result, while `Path::join` (used by workspace.rs
    // `run_wandb_file`) REPLACES the base when the joined component is
    // absolute. wandb itself writes relative link targets, but for a
    // user/tool-created ABSOLUTE target Go forms
    // `<wandbDir>/<abs-target>/run-<id>.wandb`, whose stat fails → the
    // caller stays in workspace mode (model.go:483-485); `..`/`//`/`./`
    // segments are also cleaned. This is the only call site that can see an
    // absolute or dotted run dir (the workspace call sites only ever pass
    // bare `run-*` directory names), so the Go join is replicated here.
    let run_dir = resolved_latest_run_path.to_string_lossy();
    let run_id = extract_run_id(&run_dir);
    let latest_wandb_file = if run_id.is_empty() {
        String::new()
    } else {
        go_filepath_join(&[wandb_dir, &run_dir, &format!("run-{run_id}.wandb")])
    };
    // PARITY: `runWandbFile` may return "" (unmatched dir name); Go then
    // stats "" and returns that error, exactly like a missing file.
    std::fs::metadata(&latest_wandb_file)?;

    Ok(latest_wandb_file)
}

/// Port of Go `path/filepath.Join` (Unix flavor): join the non-empty
/// elements with "/" and lexically clean the result.
// PARITY: Go filepath is OS-specific; leet only targets Unix-style paths
// here (consistent with the rest of the port).
fn go_filepath_join(elem: &[&str]) -> String {
    for (i, e) in elem.iter().enumerate() {
        if !e.is_empty() {
            return go_filepath_clean(&elem[i..].join("/"));
        }
    }
    String::new()
}

/// Port of Go `path/filepath.Clean` (Unix flavor): the classic lexical
/// cleaner — collapse multiple separators, drop `.` elements, resolve `..`
/// against parent elements (kept when they would escape a relative root,
/// dropped at an absolute root), no trailing slash, "." for empty results.
fn go_filepath_clean(path: &str) -> String {
    if path.is_empty() {
        return ".".to_string();
    }
    let b = path.as_bytes();
    let rooted = b[0] == b'/';
    let n = b.len();

    // Invariants (from Go's implementation):
    //  reading from path; r is index of next byte to process.
    //  writing to out; out is valid output so far.
    //  dotdot is index in out where .. must stop, either because
    //    it is the leading slash or it is a leading ../../.. prefix.
    let mut out: Vec<u8> = Vec::with_capacity(n);
    let mut r = 0usize;
    let mut dotdot = 0usize;
    if rooted {
        out.push(b'/');
        r = 1;
        dotdot = 1;
    }
    while r < n {
        if b[r] == b'/' {
            // empty path element
            r += 1;
        } else if b[r] == b'.' && (r + 1 == n || b[r + 1] == b'/') {
            // . element
            r += 1;
        } else if b[r] == b'.' && b[r + 1] == b'.' && (r + 2 == n || b[r + 2] == b'/') {
            // .. element: remove to last separator
            r += 2;
            if out.len() > dotdot {
                // can backtrack (Go walks `out.w` back past the element AND
                // its leading separator: the loop stops ON the separator,
                // which the truncate then drops).
                let mut w = out.len() - 1;
                while w > dotdot && out[w] != b'/' {
                    w -= 1;
                }
                out.truncate(w);
            } else if !rooted {
                // cannot backtrack, but not rooted, so append .. element.
                if !out.is_empty() {
                    out.push(b'/');
                }
                out.extend_from_slice(b"..");
                dotdot = out.len();
            }
        } else {
            // real path element.
            // add slash if needed
            if (rooted && out.len() != 1) || (!rooted && !out.is_empty()) {
                out.push(b'/');
            }
            // copy element
            while r < n && b[r] != b'/' {
                out.push(b[r]);
                r += 1;
            }
        }
    }
    // Turn empty string into "."
    if out.is_empty() {
        out.push(b'.');
    }
    // Only ASCII '/' and '.' bytes are inspected/inserted; multi-byte UTF-8
    // sequences are copied through whole (no UTF-8 byte is '/').
    String::from_utf8(out).expect("Clean preserves UTF-8")
}

#[cfg(test)]
mod tests {
    //! model.go has no Go unit-test file — its behavior is covered by
    //! tui_test.go's teatest integration tests, which are superseded by the
    //! differential harness (PARITY.md §5). The tests below pin the ported
    //! model.go behaviors directly.

    use pretty_assertions::assert_eq;

    use leet_charts::styles::{Rgb, get_odd_run_style_color};

    use super::*;
    use crate::command::{HeartbeatOwner, TimerId};
    use crate::key::{KeyEvent, KeyMods};
    use crate::workspace::test_support::{key_code, key_rune, test_config, update_run_dirs};

    const RUN_DIR: &str = "run-20240101_120000-abc123";

    fn test_model(wandb_dir: &str) -> (tempfile::TempDir, Model) {
        let (dir, cfg) = test_config();
        let m = Model::new(ModelParams {
            wandb_dir: wandb_dir.to_string(),
            run_params: None,
            config: Some(cfg),
        });
        (dir, m)
    }

    /// Sends a key through the full `App::update` path.
    fn update_key(m: &mut Model, key: KeyEvent) -> Vec<Command> {
        App::update(m, Event::Key(key))
    }

    #[test]
    fn new_model_defaults_to_workspace_mode() {
        let (_dir, m) = test_model("/tmp/wandb");
        assert_eq!(m.mode, ViewMode::Workspace);
        assert!(m.run.is_none());
    }

    #[test]
    fn new_model_with_run_file_starts_in_run_view() {
        let (_dir, cfg) = test_config();
        let m = Model::new(ModelParams {
            wandb_dir: "/tmp/wandb".to_string(),
            run_params: Some(RunParams {
                run_file: "/tmp/wandb/run.wandb".to_string(),
                remote: None,
            }),
            config: Some(cfg),
        });
        assert_eq!(m.mode, ViewMode::Run);
        assert!(m.run.is_some());
    }

    #[cfg(unix)]
    #[test]
    fn new_model_single_run_latest_resolves_latest_run_link() {
        let tmp = tempfile::tempdir().unwrap();
        let wandb_dir = tmp.path().join("wandb");
        let run_dir = wandb_dir.join(RUN_DIR);
        std::fs::create_dir_all(&run_dir).unwrap();
        let wandb_file = run_dir.join("run-abc123.wandb");
        std::fs::write(&wandb_file, b"").unwrap();
        // wandb creates the link with a relative target (the dir name).
        std::os::unix::fs::symlink(RUN_DIR, wandb_dir.join(LATEST_RUN_LINK_NAME)).unwrap();

        let (_dir, cfg) = test_config();
        cfg.borrow_mut()
            .set_startup_mode(STARTUP_MODE_SINGLE_RUN_LATEST)
            .unwrap();
        let m = Model::new(ModelParams {
            wandb_dir: wandb_dir.to_string_lossy().into_owned(),
            run_params: None,
            config: Some(cfg),
        });

        assert_eq!(m.mode, ViewMode::Run);
        assert_eq!(
            m.run.as_ref().unwrap().run_params.run_file,
            wandb_file.to_string_lossy()
        );
    }

    #[test]
    fn new_model_single_run_latest_without_link_stays_in_workspace() {
        let tmp = tempfile::tempdir().unwrap();
        let (_dir, cfg) = test_config();
        cfg.borrow_mut()
            .set_startup_mode(STARTUP_MODE_SINGLE_RUN_LATEST)
            .unwrap();
        let m = Model::new(ModelParams {
            wandb_dir: tmp.path().to_string_lossy().into_owned(),
            run_params: None,
            config: Some(cfg),
        });
        assert_eq!(m.mode, ViewMode::Workspace);
        assert!(m.run.is_none());
    }

    #[cfg(unix)]
    #[test]
    fn new_model_single_run_latest_absolute_link_target_stays_in_workspace() {
        // PARITY(review): Go filepath.Join(wandbDir, target, …) CONCATENATES,
        // so an ABSOLUTE latest-run target stats the nonexistent
        // `<wandbDir>/<abs-target>/run-<id>.wandb` → error → the model stays
        // in workspace mode (model.go:483-485). A base-replacing Path::join
        // would find the real file and wrongly open single-run view.
        let tmp = tempfile::tempdir().unwrap();
        let wandb_dir = tmp.path().join("wandb");
        let run_dir = wandb_dir.join(RUN_DIR);
        std::fs::create_dir_all(&run_dir).unwrap();
        std::fs::write(run_dir.join("run-abc123.wandb"), b"").unwrap();
        // Absolute target: user/tool-created; wandb itself writes relative
        // targets.
        std::os::unix::fs::symlink(&run_dir, wandb_dir.join(LATEST_RUN_LINK_NAME)).unwrap();

        let (_dir, cfg) = test_config();
        cfg.borrow_mut()
            .set_startup_mode(STARTUP_MODE_SINGLE_RUN_LATEST)
            .unwrap();
        let m = Model::new(ModelParams {
            wandb_dir: wandb_dir.to_string_lossy().into_owned(),
            run_params: None,
            config: Some(cfg),
        });

        assert_eq!(m.mode, ViewMode::Workspace);
        assert!(m.run.is_none());
    }

    #[test]
    fn go_filepath_join_matches_go_semantics() {
        // Cases verified against Go filepath.Join/Clean (Unix).
        assert_eq!(
            go_filepath_join(&["/tmp/wandb", "run-x", "f.wandb"]),
            "/tmp/wandb/run-x/f.wandb"
        );
        // An absolute second element CONCATENATES (Path::join would replace
        // the base).
        assert_eq!(
            go_filepath_join(&["/tmp/wandb", "/abs/run-x", "f.wandb"]),
            "/tmp/wandb/abs/run-x/f.wandb"
        );
        // Lexical cleaning: ./ prefix, .., doubled separators, empties.
        assert_eq!(
            go_filepath_join(&["./wandb", "run-x", "f.wandb"]),
            "wandb/run-x/f.wandb"
        );
        assert_eq!(
            go_filepath_join(&["/tmp/wandb", "../run-x", "f.wandb"]),
            "/tmp/run-x/f.wandb"
        );
        assert_eq!(
            go_filepath_join(&["/tmp//wandb/", "run-x//", "f.wandb"]),
            "/tmp/wandb/run-x/f.wandb"
        );
        assert_eq!(go_filepath_join(&["", "", ""]), "");
        assert_eq!(go_filepath_join(&["", "a", "b"]), "a/b");

        // filepath.Clean edges (subset of Go's TestClean table).
        assert_eq!(go_filepath_clean(""), ".");
        assert_eq!(go_filepath_clean("./"), ".");
        assert_eq!(go_filepath_clean("/.."), "/");
        assert_eq!(go_filepath_clean("abc/../.."), "..");
        assert_eq!(go_filepath_clean("a/c/b/.."), "a/c");
    }

    #[cfg(unix)]
    #[test]
    fn wandb_file_from_latest_run_link_non_dir_target_is_empty_and_ok() {
        // PARITY: model.go:472-475 — stat succeeds, not a dir → ("", nil).
        let tmp = tempfile::tempdir().unwrap();
        let file = tmp.path().join("some-file");
        std::fs::write(&file, b"").unwrap();
        std::os::unix::fs::symlink(&file, tmp.path().join(LATEST_RUN_LINK_NAME)).unwrap();

        let got = wandb_file_from_latest_run_link(&tmp.path().to_string_lossy()).unwrap();
        assert_eq!(got, "");
    }

    #[test]
    fn init_outside_test_mode_requests_background_color_and_inits_workspace() {
        let (_dir, mut m) = test_model("/tmp/wandb");
        let cmds = App::init(&mut m);
        assert!(
            matches!(cmds.first(), Some(Command::RequestBackgroundColor)),
            "first init command must be RequestBackgroundColor, got {cmds:?}"
        );
        assert!(
            cmds.iter()
                .any(|c| matches!(c, Command::PollWandbDir { .. })),
            "workspace Init must arm the dir poll, got {cmds:?}"
        );
    }

    #[test]
    fn alt_r_sets_restart_and_quits() {
        let (_dir, mut m) = test_model("/tmp/wandb");
        let cmds = update_key(
            &mut m,
            KeyEvent {
                code: KeyCode::Char('r'),
                text: None,
                mods: KeyMods::ALT,
            },
        );
        assert!(m.should_restart());
        assert!(matches!(cmds.as_slice(), [Command::Quit]));
    }

    #[test]
    fn h_toggles_help_and_q_quits_from_help() {
        let (_dir, mut m) = test_model("/tmp/wandb");
        App::update(
            &mut m,
            Event::Resize {
                width: 100,
                height: 30,
            },
        );

        let cmds = update_key(&mut m, key_rune('h'));
        assert!(m.help.is_active());
        assert!(cmds.is_empty());

        // While help is active it owns keys: 'q' quits.
        let cmds = update_key(&mut m, key_rune('q'));
        assert!(matches!(cmds.as_slice(), [Command::Quit]));

        // 'h' again closes it (the toggle branch fires before routing).
        update_key(&mut m, key_rune('h'));
        assert!(!m.help.is_active());
    }

    #[test]
    fn enter_opens_run_view_and_esc_returns_to_workspace() {
        let (_dir, mut m) = test_model("/tmp/wandb");
        App::update(
            &mut m,
            Event::Resize {
                width: 120,
                height: 40,
            },
        );
        update_run_dirs(&mut m.workspace, &[RUN_DIR]);

        let cmds = update_key(&mut m, key_code(KeyCode::Enter));
        assert_eq!(m.mode, ViewMode::Run);
        assert!(m.run.is_some());
        // enterRunView batches run.Init() + the synthetic WindowSizeMsg.
        assert!(
            cmds.iter().any(|c| matches!(c, Command::InitReader { .. })),
            "expected the run reader init, got {cmds:?}"
        );
        assert!(
            cmds.iter().any(|c| matches!(
                c,
                Command::Emit(e) if matches!(**e, Event::Resize { width: 120, height: 40 })
            )),
            "expected the synthetic WindowSizeMsg emit, got {cmds:?}"
        );

        let cmds = update_key(&mut m, key_code(KeyCode::Esc));
        assert_eq!(m.mode, ViewMode::Workspace);
        assert!(m.run.is_none());
        // exitRunView's cleanup cancels the run heartbeat (§2.9).
        assert!(
            cmds.iter().any(|c| matches!(
                c,
                Command::CancelTimer {
                    id: TimerId::Heartbeat(HeartbeatOwner::Run)
                }
            )),
            "expected the run heartbeat cancel, got {cmds:?}"
        );
    }

    #[test]
    fn filter_enter_exits_filter_without_switching_mode() {
        // The awaitingInput snapshot subtlety (model.go:168-173): the Enter
        // that exits filter mode must not fall through to enterRunView.
        let (_dir, mut m) = test_model("/tmp/wandb");
        App::update(
            &mut m,
            Event::Resize {
                width: 120,
                height: 40,
            },
        );
        update_run_dirs(&mut m.workspace, &[RUN_DIR]);

        update_key(&mut m, key_rune('f'));
        assert!(m.workspace.is_filtering(), "f must open the runs filter");

        update_key(&mut m, key_code(KeyCode::Enter));
        assert!(!m.workspace.is_filtering(), "Enter must exit the filter");
        assert_eq!(m.mode, ViewMode::Workspace, "mode must not switch");

        // A second Enter (filter closed) does switch.
        update_key(&mut m, key_code(KeyCode::Enter));
        assert_eq!(m.mode, ViewMode::Run);
    }

    #[test]
    fn background_color_event_sets_dark_flag() {
        let (_dir, mut m) = test_model("/tmp/wandb");
        assert!(m.dark, "default is dark (styles.go:23)");
        App::update(
            &mut m,
            Event::BackgroundColor {
                is_dark: false,
                rgb: None,
            },
        );
        assert!(!m.dark);
        App::update(
            &mut m,
            Event::BackgroundColor {
                is_dark: true,
                rgb: None,
            },
        );
        assert!(m.dark);
    }

    /// The OSC 11 RGB carried on tea.BackgroundColorMsg reaches the
    /// workspace zebra stripe: Go's `getOddRunStyleColor` blends the REAL
    /// terminal background 5% toward gray 128 (styles.go:97-109) instead of
    /// the fixed #d0d0d0/#1c1c1c fallback.
    #[test]
    fn background_color_event_updates_workspace_zebra() {
        let (_dir, mut m) = test_model("/tmp/wandb");
        // Not test mode, no reply yet: the zebra uses the fallback.
        assert_eq!(m.workspace.terminal_bg, None);
        assert_eq!(
            get_odd_run_style_color(m.workspace.terminal_bg).dark,
            Rgb(0x1c, 0x1c, 0x1c)
        );

        App::update(
            &mut m,
            Event::BackgroundColor {
                is_dark: true,
                rgb: Some(Rgb(0x28, 0x2c, 0x34)),
            },
        );
        assert_eq!(m.workspace.terminal_bg, Some(Rgb(0x28, 0x2c, 0x34)));
        // blendRGB(0x28,0x2c,0x34 → gray 128, alpha 0.05), truncated like Go.
        let zebra = get_odd_run_style_color(m.workspace.terminal_bg);
        assert_eq!(zebra.dark, Rgb(44, 48, 55));
        assert_eq!(zebra.light, Rgb(44, 48, 55), "detected bg is uniform");

        // A later reply without an RGB (termenv-rejected form) must not
        // clear the detected value — Go's termBg globals are set once.
        App::update(
            &mut m,
            Event::BackgroundColor {
                is_dark: true,
                rgb: None,
            },
        );
        assert_eq!(m.workspace.terminal_bg, Some(Rgb(0x28, 0x2c, 0x34)));
    }

    #[test]
    fn cleanup_is_idempotent() {
        let (_dir, mut m) = test_model("/tmp/wandb");
        App::cleanup(&mut m);
        App::cleanup(&mut m);
    }
}
