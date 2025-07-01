pub mod connection;
pub mod launcher;
pub mod printer;
pub mod run;
pub mod session;
pub mod settings;
pub mod wandb_internal;

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
