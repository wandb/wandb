//! Differential test harness for the leet Go→Rust port.
//!
//! The Go implementation (`core/internal/leet`, run as `wandb-core leet`
//! under `WANDB_LEET_TEST=1`) is the behavioral oracle. This crate spawns it
//! in a PTY behind a frozen terminal persona, drives JSON scenarios over an
//! ack protocol, parses frames into normalized cell grids, and diffs them —
//! against a second oracle run (the null test) or against the Rust
//! implementation (parity tests, from Phase 3 on).
//!
//! See `leet/docs/PARITY.md` for the scenario map and diff-tier policy.

pub mod ack;
pub mod diff;
pub mod grid;
pub mod persona;
pub mod pty;
pub mod runner;
pub mod scenario;
pub mod snapshot;
