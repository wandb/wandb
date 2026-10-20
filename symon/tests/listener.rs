//! Starts the wandb-symon binary and checks the address it publishes.

#![cfg(not(target_os = "windows"))]

use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// Runs the binary with the given TMPDIR and returns the portfile token.
fn portfile_token(tmpdir: &std::path::Path) -> String {
    let portfile = tempfile::NamedTempFile::new().unwrap();
    let mut child = Command::new(env!("CARGO_BIN_EXE_wandb-symon"))
        .arg("--portfile")
        .arg(portfile.path())
        .env("TMPDIR", tmpdir)
        .env("WANDB_CACHE_DIR", tmpdir)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();

    let deadline = Instant::now() + Duration::from_secs(10);
    let token = loop {
        let token = std::fs::read_to_string(portfile.path()).unwrap();
        if !token.is_empty() {
            break token;
        }
        assert!(Instant::now() < deadline, "wandb-symon wrote no portfile");
        assert!(child.try_wait().unwrap().is_none(), "wandb-symon exited");
        std::thread::sleep(Duration::from_millis(20));
    };
    let _ = child.kill();
    let _ = child.wait();
    token
}

#[test]
fn falls_back_to_tcp_when_the_socket_path_is_too_long() {
    let dir = tempfile::tempdir().unwrap();
    let long = dir.path().join("x".repeat(120));
    std::fs::create_dir(&long).unwrap();
    assert!(portfile_token(&long).starts_with("sock="));
}
