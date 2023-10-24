#![deny(clippy::all)]
use serde_json::Value as JsonValue;
use std::collections::HashMap;
use tracing_subscriber;
use wandbinder::{run, session, settings};

#[macro_use]
extern crate napi_derive;

#[napi::module_init]
fn init() {
  let log_level = tracing::Level::INFO;
  //println!("Debug mode enabled!");
  //let log_level = tracing::Level::DEBUG;
  tracing_subscriber::fmt().with_max_level(log_level).init();
}

#[napi(js_name = "Settings")]
pub struct JsSettings {
  inner: settings::Settings,
}

#[napi]
impl JsSettings {
  #[napi(constructor)]
  pub fn new() -> Self {
    JsSettings {
      inner: settings::Settings::new(None, None, None, None, None),
    }
  }
}

#[napi(js_name = "Session")]
pub struct JsSession {
  inner: session::Session,
}

#[napi]
impl JsSession {
  #[napi(constructor)]
  pub fn new(settings: &JsSettings) -> Self {
    JsSession {
      inner: session::Session::new(settings.inner.clone()),
    }
  }

  #[napi]
  pub fn init_run(&self, run_id: Option<String>) -> JsRun {
    let run = self.inner.init_run(run_id);
    JsRun { inner: run }
  }
}

#[napi(js_name = "Run")]
pub struct JsRun {
  inner: run::Run,
}

#[napi]
impl JsRun {
  #[napi(constructor)]
  pub fn new(session: &JsSession, run_id: Option<String>) -> Self {
    JsRun {
      inner: session.inner.init_run(run_id),
    }
  }

  #[napi]
  pub fn log(&self, data: HashMap<String, JsonValue>) {
    self.inner.log(data);
  }

  #[napi]
  pub fn finish(&mut self) {
    self.inner.finish();
  }
}

#[napi(js_name = "init")]
pub fn wandb_init(settings: Option<&JsSettings>) -> JsRun {
  let settings = match settings {
    Some(settings) => settings.inner.clone(),
    None => JsSettings::new().inner,
  };
  let session = session::Session::new(settings);
  let run = session.init_run(None);
  JsRun { inner: run }
}
