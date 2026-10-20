//! Starts the wandb-symon binary and checks the address it prints.

#![cfg(not(target_os = "windows"))]

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};

/// Runs the binary with the given TMPDIR and returns its address line.
fn address_line(tmpdir: &std::path::Path) -> String {
    let mut child = Command::new(env!("CARGO_BIN_EXE_wandb-symon"))
        .env("TMPDIR", tmpdir)
        .env("WANDB_CACHE_DIR", tmpdir)
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();

    let mut line = String::new();
    BufReader::new(child.stdout.take().unwrap())
        .read_line(&mut line)
        .unwrap();
    let _ = child.kill();
    let _ = child.wait();
    line
}

#[test]
fn falls_back_to_tcp_when_the_socket_path_is_too_long() {
    let dir = tempfile::tempdir().unwrap();
    let long = dir.path().join("x".repeat(120));
    std::fs::create_dir(&long).unwrap();
    assert!(address_line(&long).starts_with("sock="));
}
