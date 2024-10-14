use sentry::types::Dsn;

fn parse_bool(s: &str) -> bool {
    match s.to_lowercase().as_str() {
        "true" | "1" => true,
        "false" | "0" => false,
        _ => true,
    }
}

/// Setup Sentry error reporting.
pub fn setup_sentry() {
    let error_reporting_enabled = std::env::var("WANDB_ERROR_REPORTING")
        .map(|v| parse_bool(&v))
        .unwrap_or(true);

    let dsn: Option<Dsn> = if error_reporting_enabled {
        "https://9e9d0694aa7ccd41aeb5bc34aadd716a@o151352.ingest.us.sentry.io/4506068829470720"
            .parse()
            .ok()
    } else {
        None
    };

    let _guard = sentry::init(sentry::ClientOptions {
        dsn,
        release: sentry::release_name!(),
        ..Default::default()
    });
}
