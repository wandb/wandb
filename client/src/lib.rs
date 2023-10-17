use pyo3::prelude::*;

pub mod connection;
pub mod launcher;
pub mod run;
pub mod session;
pub mod wandb_internal;

/// Communication layer between user code and nexus

/// A Python module implemented in Rust. The name of this function must match
/// the `lib.name` setting in the `Cargo.toml`, else Python will not be able to
/// import the module.
#[pymodule]
fn wandbinder(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(session::generate_run_id, m)?)?;
    m.add_class::<session::Settings>()?;
    m.add_class::<session::Session>()?;
    m.add_class::<run::Run>()?;
    Ok(())
}
