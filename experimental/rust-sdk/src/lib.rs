use std::sync::OnceLock;

pub mod connection;
pub mod launcher;
pub mod printer;
pub mod run;
pub mod session;
pub mod settings;
pub mod wandb_internal;

/// Communication layer between user code and nexus

pub fn get_core_version() -> &'static str {
    static VERSION: OnceLock<String> = OnceLock::new();
    VERSION.get_or_init(|| {
        let version = env!("CARGO_PKG_VERSION");
        version
            .replace("-alpha.", "a")
            .replace("-beta.", "b")
            .replace("-rc.", "rc")
    })
}

pub fn init(
    project: Option<String>,
    settings: Option<settings::Settings>,
) -> Result<run::Run, std::io::Error> {
    let mut settings = settings.unwrap_or_default();

    if let Some(project) = project {
        settings.set_project(project);
    }

    let sess = session::Session::new(settings)?;
    sess.init_run(None)
}
