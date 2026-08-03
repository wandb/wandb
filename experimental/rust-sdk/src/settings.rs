//! Session and run settings, including credential resolution.

use std::env;
use std::path::PathBuf;

use crate::wandb_internal as pb;

/// The default W&B server URL.
pub const DEFAULT_BASE_URL: &str = "https://api.wandb.ai";

/// Where run data is sent.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    /// Stream data to the W&B server as the run progresses.
    #[default]
    Online,
    /// Write data to disk only; upload later with `wandb sync`.
    Offline,
}

/// Settings for a W&B session and its runs.
///
/// Every field is optional. An unset field falls back to the corresponding
/// `WANDB_*` environment variable, then to a default. Construct with struct
/// update syntax:
///
/// ```no_run
/// let settings = wandb::Settings {
///     project: Some("my-project".to_string()),
///     ..Default::default()
/// };
/// ```
#[derive(Clone, Debug, Default)]
pub struct Settings {
    /// W&B API key.
    ///
    /// Falls back to `WANDB_API_KEY`, then to the entry for the W&B server
    /// host in the netrc file (`NETRC` or `~/.netrc`), where `wandb login`
    /// stores keys.
    pub api_key: Option<String>,

    /// URL of the W&B server. Falls back to `WANDB_BASE_URL`, then to
    /// `https://api.wandb.ai`.
    pub base_url: Option<String>,

    /// File that caches access tokens obtained via the identity token.
    /// Falls back to `WANDB_CREDENTIALS_FILE`, then to
    /// `~/.config/wandb/credentials.json`.
    pub credentials_file: Option<PathBuf>,

    /// Entity (user or team) that owns the run. Falls back to
    /// `WANDB_ENTITY`, then to the server-side default entity.
    pub entity: Option<String>,

    /// File containing a JWT identity token for authentication via identity
    /// federation. Falls back to `WANDB_IDENTITY_TOKEN_FILE`. Takes
    /// precedence over the API key when set.
    pub identity_token_file: Option<PathBuf>,

    /// Whether to stream data to the server or store it locally.
    /// Falls back to `WANDB_MODE` (`"online"` or `"offline"`).
    pub mode: Option<Mode>,

    /// Project the run belongs to. Falls back to `WANDB_PROJECT`, then to
    /// `"uncategorized"`.
    pub project: Option<String>,

    /// Directory to store run data in (a `wandb` subdirectory is created).
    /// Falls back to `WANDB_DIR`, then to the current directory.
    pub root_dir: Option<PathBuf>,

    /// ID for the run. Falls back to `WANDB_RUN_ID`, then to a random ID.
    pub run_id: Option<String>,

    /// Display name for the run. Falls back to `WANDB_NAME`, then to a
    /// server-generated name.
    pub run_name: Option<String>,

    /// Tags for the run. Falls back to `WANDB_TAGS` (comma-separated).
    pub run_tags: Option<Vec<String>>,
}

impl Settings {
    /// The resolved W&B server URL, without a trailing slash.
    pub fn base_url(&self) -> String {
        self.base_url
            .clone()
            .or_else(|| env_nonempty("WANDB_BASE_URL"))
            .unwrap_or_else(|| DEFAULT_BASE_URL.to_string())
            .trim_end_matches('/')
            .to_string()
    }

    /// The resolved API key, if any.
    pub fn api_key(&self) -> Option<String> {
        self.api_key
            .clone()
            .or_else(|| env_nonempty("WANDB_API_KEY"))
            .or_else(|| netrc_api_key(&self.base_url()))
    }

    /// The resolved identity token file, if any.
    pub fn identity_token_file(&self) -> Option<PathBuf> {
        self.identity_token_file
            .clone()
            .or_else(|| env_nonempty("WANDB_IDENTITY_TOKEN_FILE").map(PathBuf::from))
    }

    /// The resolved credentials file.
    pub fn credentials_file(&self) -> PathBuf {
        self.credentials_file
            .clone()
            .or_else(|| env_nonempty("WANDB_CREDENTIALS_FILE").map(PathBuf::from))
            .unwrap_or_else(|| {
                home_dir()
                    .unwrap_or_default()
                    .join(".config/wandb/credentials.json")
            })
    }

    /// The resolved mode.
    pub fn mode(&self) -> Mode {
        self.mode
            .unwrap_or_else(|| match env_nonempty("WANDB_MODE").as_deref() {
                // "dryrun" is the legacy name for offline mode.
                Some("offline") | Some("dryrun") => Mode::Offline,
                _ => Mode::Online,
            })
    }

    pub(crate) fn entity(&self) -> String {
        self.entity
            .clone()
            .or_else(|| env_nonempty("WANDB_ENTITY"))
            .unwrap_or_default()
    }

    pub(crate) fn project(&self) -> String {
        self.project
            .clone()
            .or_else(|| env_nonempty("WANDB_PROJECT"))
            .unwrap_or_else(|| "uncategorized".to_string())
    }

    pub(crate) fn run_id(&self) -> Option<String> {
        self.run_id.clone().or_else(|| env_nonempty("WANDB_RUN_ID"))
    }

    pub(crate) fn run_name(&self) -> String {
        self.run_name
            .clone()
            .or_else(|| env_nonempty("WANDB_NAME"))
            .unwrap_or_default()
    }

    pub(crate) fn run_tags(&self) -> Vec<String> {
        self.run_tags.clone().unwrap_or_else(|| {
            env_nonempty("WANDB_TAGS")
                .map(|tags| tags.split(',').map(|t| t.trim().to_string()).collect())
                .unwrap_or_default()
        })
    }

    pub(crate) fn root_dir(&self) -> PathBuf {
        self.root_dir
            .clone()
            .or_else(|| env_nonempty("WANDB_DIR").map(PathBuf::from))
            .unwrap_or_else(|| env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
    }
}

/// Settings for a single run, with all values resolved.
#[derive(Clone, Debug)]
pub(crate) struct RunSettings {
    pub api_key: Option<String>,
    pub base_url: String,
    pub credentials_file: PathBuf,
    pub entity: String,
    pub identity_token_file: Option<PathBuf>,
    pub mode: Mode,
    pub project: String,
    pub run_id: String,
    pub run_name: String,
    pub run_tags: Vec<String>,
    pub timespec: String,
    pub wandb_dir: PathBuf,
}

impl RunSettings {
    /// Resolves run settings from user settings and the environment.
    pub fn resolve(settings: &Settings) -> Self {
        RunSettings {
            api_key: settings.api_key(),
            base_url: settings.base_url(),
            credentials_file: settings.credentials_file(),
            entity: settings.entity(),
            identity_token_file: settings.identity_token_file(),
            mode: settings.mode(),
            project: settings.project(),
            run_id: settings.run_id().unwrap_or_else(|| crate::generate_id(8)),
            run_name: settings.run_name(),
            run_tags: settings.run_tags(),
            timespec: chrono::Local::now().format("%Y%m%d_%H%M%S").to_string(),
            wandb_dir: settings.root_dir().join("wandb"),
        }
    }

    pub fn offline(&self) -> bool {
        self.mode == Mode::Offline
    }

    fn run_mode(&self) -> &'static str {
        if self.offline() {
            "offline-run"
        } else {
            "run"
        }
    }

    pub fn sync_dir(&self) -> PathBuf {
        self.wandb_dir.join(format!(
            "{}-{}-{}",
            self.run_mode(),
            self.timespec,
            self.run_id
        ))
    }

    pub fn sync_file(&self) -> PathBuf {
        self.sync_dir().join(format!("run-{}.wandb", self.run_id))
    }

    pub fn files_dir(&self) -> PathBuf {
        self.sync_dir().join("files")
    }

    pub fn log_dir(&self) -> PathBuf {
        self.sync_dir().join("logs")
    }

    /// The URL of the run in the W&B UI.
    pub fn run_url(&self) -> String {
        let app_url = self.base_url.replace("//api.wandb.ai", "//wandb.ai");
        format!(
            "{}/{}/{}/runs/{}",
            app_url, self.entity, self.project, self.run_id
        )
    }

    /// Creates the local directories that wandb-core writes run data to.
    pub fn create_dirs(&self) -> std::io::Result<()> {
        std::fs::create_dir_all(self.files_dir())?;
        std::fs::create_dir_all(self.log_dir())
    }

    /// Converts to the settings proto sent to wandb-core.
    ///
    /// Fails if a path is not valid UTF-8, since the proto cannot represent
    /// it and wandb-core would operate on a different path than the SDK.
    pub fn to_proto(&self) -> crate::Result<pb::Settings> {
        let path = |p: PathBuf| match p.into_os_string().into_string() {
            Ok(p) => Ok(Some(p)),
            Err(p) => Err(crate::Error::InvalidInput(format!(
                "path is not valid UTF-8: {}",
                PathBuf::from(p).display()
            ))),
        };
        Ok(pb::Settings {
            api_key: self.api_key.clone(),
            base_url: Some(self.base_url.clone()),
            credentials_file: path(self.credentials_file.clone())?,
            entity: Some(self.entity.clone()),
            identity_token_file: match self.identity_token_file.clone() {
                Some(p) => path(p)?,
                None => None,
            },
            mode: Some(if self.offline() { "offline" } else { "online" }.to_string()),
            offline: Some(self.offline()),
            run_id: Some(self.run_id.clone()),
            run_mode: Some(self.run_mode().to_string()),
            run_name: Some(self.run_name.clone()),
            run_tags: Some(pb::ListStringValue {
                value: self.run_tags.clone(),
            }),
            timespec: Some(self.timespec.clone()),
            wandb_dir: path(self.wandb_dir.clone())?,
            sync_dir: path(self.sync_dir())?,
            sync_file: path(self.sync_file())?,
            log_dir: path(self.log_dir())?,
            log_internal: path(self.log_dir().join("debug-internal.log"))?,
            log_user: path(self.log_dir().join("debug.log"))?,
            x_stats_pid: Some(std::process::id() as i32),
            // Features that require client-side support we don't implement:
            // console capture, code/git/requirements saving, W&B Launch jobs.
            console: Some("off".to_string()),
            disable_code: Some(true),
            disable_git: Some(true),
            disable_job_creation: Some(true),
            save_code: Some(false),
            x_save_requirements: Some(false),
            ..Default::default()
        })
    }
}

/// Returns the value of the environment variable if it is set and non-empty.
fn env_nonempty(name: &str) -> Option<String> {
    env::var(name).ok().filter(|v| !v.is_empty())
}

fn home_dir() -> Option<PathBuf> {
    env::var_os("HOME")
        .or_else(|| env::var_os("USERPROFILE"))
        .map(PathBuf::from)
}

/// Looks up the API key for the given base URL's host in the netrc file,
/// where `wandb login` stores API keys.
fn netrc_api_key(base_url: &str) -> Option<String> {
    let host = base_url.split("//").nth(1)?.split(['/', ':']).next()?;
    let path = env::var_os("NETRC")
        .map(PathBuf::from)
        .or_else(find_default_netrc)?;
    let content = std::fs::read_to_string(path).ok()?;
    parse_netrc(&content, host)
}

fn find_default_netrc() -> Option<PathBuf> {
    let home = home_dir()?;
    [".netrc", "_netrc"]
        .iter()
        .map(|name| home.join(name))
        .find(|p| p.exists())
}

/// Returns the password for the given machine in netrc-formatted `content`.
///
/// Follows Python's `netrc` module: `#` starts a comment that runs to the
/// end of the line, `macdef` bodies extend to the next blank line, a
/// machine-specific entry takes precedence over a `default` entry, and the
/// last entry wins among duplicates.
fn parse_netrc(content: &str, machine: &str) -> Option<String> {
    // Flatten to a token stream with comments and macro bodies removed.
    let mut tokens = Vec::new();
    let mut in_macdef = false;
    for line in content.lines() {
        if in_macdef {
            in_macdef = !line.trim().is_empty();
            continue;
        }
        for token in line.split_whitespace() {
            if token.starts_with('#') {
                break;
            }
            tokens.push(token);
            if token == "macdef" {
                in_macdef = true;
                break;
            }
        }
    }

    #[derive(PartialEq)]
    enum Scope {
        None,
        Machine,
        Default,
        OtherMachine,
    }
    let mut scope = Scope::None;
    let mut machine_password = None;
    let mut default_password = None;
    let mut tokens = tokens.into_iter();
    while let Some(token) = tokens.next() {
        match token {
            "machine" => {
                let Some(name) = tokens.next() else { break };
                scope = if name == machine {
                    Scope::Machine
                } else {
                    Scope::OtherMachine
                };
            }
            "default" => scope = Scope::Default,
            "password" => {
                let Some(password) = tokens.next() else { break };
                match scope {
                    Scope::Machine => machine_password = Some(password.to_string()),
                    Scope::Default => default_password = Some(password.to_string()),
                    _ => {}
                }
            }
            _ => {}
        }
    }
    machine_password.or(default_password)
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::*;

    #[test]
    fn parse_netrc_finds_machine() {
        let netrc = "\
machine example.com\n  login user\n  password secret1\n\
machine api.wandb.ai\n  login user\n  password secret2\n";
        assert_eq!(
            parse_netrc(netrc, "api.wandb.ai").as_deref(),
            Some("secret2")
        );
        assert_eq!(
            parse_netrc(netrc, "example.com").as_deref(),
            Some("secret1")
        );
        assert_eq!(parse_netrc(netrc, "other.com"), None);
    }

    #[test]
    fn parse_netrc_default_entry() {
        let netrc = "machine example.com password a\ndefault password b\n";
        assert_eq!(parse_netrc(netrc, "missing.com").as_deref(), Some("b"));
    }

    #[test]
    fn parse_netrc_machine_beats_default() {
        let netrc = "default password fallback\nmachine api.wandb.ai password real\n";
        assert_eq!(parse_netrc(netrc, "api.wandb.ai").as_deref(), Some("real"));
    }

    #[test]
    fn parse_netrc_ignores_comments() {
        let netrc = "\
machine api.wandb.ai\n  login user\n  # password hint: in the vault\n  password real\n";
        assert_eq!(parse_netrc(netrc, "api.wandb.ai").as_deref(), Some("real"));
    }

    #[test]
    fn parse_netrc_skips_macdef_bodies() {
        let netrc = "\
macdef init\nmachine evil.com password stolen\n\n\
machine api.wandb.ai password real\n";
        assert_eq!(parse_netrc(netrc, "api.wandb.ai").as_deref(), Some("real"));
        assert_eq!(parse_netrc(netrc, "evil.com"), None);
    }

    #[test]
    fn run_settings_paths() {
        let settings = RunSettings {
            api_key: None,
            base_url: DEFAULT_BASE_URL.to_string(),
            credentials_file: PathBuf::new(),
            entity: "team".to_string(),
            identity_token_file: None,
            mode: Mode::Offline,
            project: "proj".to_string(),
            run_id: "abcd1234".to_string(),
            run_name: String::new(),
            run_tags: vec![],
            timespec: "20260101_120000".to_string(),
            wandb_dir: PathBuf::from("/tmp/wandb"),
        };
        assert_eq!(
            settings.sync_dir(),
            Path::new("/tmp/wandb/offline-run-20260101_120000-abcd1234")
        );
        assert_eq!(
            settings.sync_file(),
            settings.sync_dir().join("run-abcd1234.wandb")
        );
        assert_eq!(
            settings.run_url(),
            "https://wandb.ai/team/proj/runs/abcd1234"
        );
    }
}
