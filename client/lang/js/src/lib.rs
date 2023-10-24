#![deny(clippy::all)]
use napi::bindgen_prelude::{Env, FromNapiValue};
use napi::sys;
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

/*
impl FromNapiValue for JsMedia {
  unsafe fn from_napi_value(
    env: sys::napi_env,
    napi_val: sys::napi_value,
  ) -> Result<Self, napi::Error> {
    // Attempt to convert the NAPI value to a serde_json::Value
    if let Ok(json_val) = <JsonValue as FromNapiValue>::from_napi_value(env, napi_val) {
      return Ok(JsMedia(json_val));
    }

    // For simplicity, we're ignoring the Ndarray case
    Err(napi::Error::from_reason(
      "Unable to convert NAPI value to LogValue".to_string(),
    ))
  }
}*/

#[napi]
impl JsRun {
  #[napi(constructor)]
  pub fn new(session: &JsSession, run_id: Option<String>) -> Self {
    JsRun {
      inner: session.inner.init_run(run_id),
    }
  }

  #[napi]
  pub fn log(&self, env: Env, data: HashMap<String, JsonValue>) {
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
