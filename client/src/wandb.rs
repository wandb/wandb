use pyo3::prelude::*;

use crate::run;
use crate::session::Session;
use crate::settings;

#[pyfunction]
pub fn init(settings: settings::Settings) -> run::Run {
    let session = Session::new(settings);
    session.init_run(None)
}
