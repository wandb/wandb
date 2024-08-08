#[cfg(target_os = "linux")]
pub mod event_loop;
#[cfg(target_os = "linux")]
pub use self::event_loop::{Event, EventLoop, EventLoopProvider};
