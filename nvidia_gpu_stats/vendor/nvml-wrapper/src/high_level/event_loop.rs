/*!
A convenient abstraction for working with events.

Simply register the devices you wish to receive events for and then compose
a handler for the events. Event handling looks like this (details removed):

```no_run
# extern crate nvml_wrapper as nvml;
#
# #[cfg(target_os = "linux")]
# fn main() {
#     example::actual_main().unwrap();
# }
#
# #[cfg(target_os = "windows")]
# fn main() {}
#
# #[cfg(target_os = "linux")]
# mod example {
# use nvml::Nvml;
# use nvml::error::{NvmlError, NvmlErrorWithSource};
# use nvml::high_level::EventLoopProvider;
# use nvml::high_level::Event::*;
#
# pub fn actual_main() -> Result<(), NvmlErrorWithSource> {
# let nvml = Nvml::init()?;
# let device = nvml.device_by_index(0)?;
# let mut event_loop = nvml.create_event_loop(vec![&device])?;
#
event_loop.run_forever(|event, state| match event {
    // If there were no errors, extract the event
    Ok(event) => match event {
        ClockChange(device) => { /* ... */ },
        PowerStateChange(device) => { /* ... */ },
        _ => { /* ... */ }
    },

    // If there was an error, handle it
    Err(error) => match error {
        // If the error is `Unknown`, continue looping and hope for the best
        NvmlError::Unknown => {},
        // The other errors that can occur are almost guaranteed to mean that
        // further looping will never be successful (`GpuLost` and
        // `Uninitialized`), so we stop looping
        _ => state.interrupt()
    }
});

# Ok(())
# }
# }
```

The full, fleshed-out example can be viewed in the examples directory
(`event_loop.rs`). Run it as follows:

```bash
cargo run --example event_loop
```

The functionality in this module is only available on Linux platforms; NVML does
not support events on any other platform.
*/

use crate::bitmasks::event::EventTypes;
use crate::enums::event::XidError;
use crate::error::{NvmlError, NvmlErrorWithSource};
use crate::struct_wrappers::event::EventData;
use crate::Device;
use crate::EventSet;
use crate::Nvml;
#[cfg(feature = "serde")]
use serde_derive::{Deserialize, Serialize};

// TODO: Tests

/**
Represents the event types that an `EventLoop` can gather for you.

These are analagous to the constants in `bitmasks::event`.

Checking to see if the `Device` within an `Event` is the same physical device as
another `Device` that you have on hand can be accomplished via `Device.uuid()`.
*/
#[derive(Debug)]
pub enum Event<'nvml> {
    ClockChange(Device<'nvml>),
    CriticalXidError(Device<'nvml>, XidError),
    DoubleBitEccError(Device<'nvml>),
    PowerStateChange(Device<'nvml>),
    SingleBitEccError(Device<'nvml>),
    /// Returned if none of the other `Events` are contained in the `EventData`
    /// the `EventLoop` processes.
    Unknown,
}

impl<'nvml> From<EventData<'nvml>> for Event<'nvml> {
    fn from(struct_: EventData<'nvml>) -> Self {
        if struct_.event_type.contains(EventTypes::CLOCK_CHANGE) {
            Event::ClockChange(struct_.device)
        } else if struct_.event_type.contains(EventTypes::CRITICAL_XID_ERROR) {
            // We can unwrap here because we know `event_data` will be `Some`
            // since the error is `CRITICAL_XID_ERROR`
            Event::CriticalXidError(struct_.device, struct_.event_data.unwrap())
        } else if struct_
            .event_type
            .contains(EventTypes::DOUBLE_BIT_ECC_ERROR)
        {
            Event::DoubleBitEccError(struct_.device)
        } else if struct_.event_type.contains(EventTypes::PSTATE_CHANGE) {
            Event::PowerStateChange(struct_.device)
        } else if struct_
            .event_type
            .contains(EventTypes::SINGLE_BIT_ECC_ERROR)
        {
            Event::SingleBitEccError(struct_.device)
        } else {
            Event::Unknown
        }
    }
}

/**
Holds the `EventSet` utilized within an event loop.

A usage example is available (`examples/event_loop.rs`). It can be run as
follows:

```bash
cargo run --example event_loop
```
*/
pub struct EventLoop<'nvml> {
    set: EventSet<'nvml>,
}

impl<'nvml> EventLoop<'nvml> {
    /**
    Register another device that this `EventLoop` should receive events for.

    This method takes ownership of this struct and then hands it back to you if
    everything went well with the registration process.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `GpuLost`, if a GPU has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Platform Support

    Only supports Linux.
    */
    pub fn register_device(
        mut self,
        device: &'nvml Device<'nvml>,
    ) -> Result<Self, NvmlErrorWithSource> {
        self.set = device.register_events(device.supported_event_types()?, self.set)?;

        Ok(self)
    }

    /**
    Handle events with the given callback until the loop is manually interrupted.

    # Errors

    The function itself does not return anything. You will be given errors to
    handle within your closure if they occur; events are handed to you wrapped
    in a `Result`.

    The errors that you will need to handle are:

    * `Uninitialized`, if the library has not been successfully initialized
    * `GpuLost`, if a GPU has fallen off the bus or is otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Examples

    See the `event_loop` example in the `examples` directory at the root.

    # Platform Support

    Only supports Linux.
    */
    pub fn run_forever<F>(&mut self, mut callback: F)
    where
        F: FnMut(Result<Event<'nvml>, NvmlError>, &mut EventLoopState),
    {
        let mut state = EventLoopState { interrupted: false };

        loop {
            if state.interrupted {
                break;
            };

            match self.set.wait(1) {
                Ok(data) => {
                    callback(Ok(data.into()), &mut state);
                }
                Err(NvmlError::Timeout) => continue,
                value => callback(value.map(|d| d.into()), &mut state),
            };
        }
    }

    /// Obtain a reference to the `EventSet` contained within this struct.
    pub fn as_inner(&'nvml self) -> &'nvml EventSet<'nvml> {
        &(self.set)
    }

    /// Obtain a mutable reference to the `EventSet` contained within this
    /// struct.
    pub fn as_mut_inner(&'nvml mut self) -> &'nvml mut EventSet<'nvml> {
        &mut (self.set)
    }

    /// Consumes this `EventLoop` and yields the `EventSet` contained within.
    pub fn into_inner(self) -> EventSet<'nvml> {
        self.set
    }
}

impl<'nvml> From<EventSet<'nvml>> for EventLoop<'nvml> {
    fn from(set: EventSet<'nvml>) -> Self {
        Self { set }
    }
}

/// Keeps track of whether an `EventLoop` is interrupted or not.
#[derive(Debug, Clone, Eq, PartialEq, Hash)]
#[cfg_attr(feature = "serde", derive(Serialize, Deserialize))]
pub struct EventLoopState {
    interrupted: bool,
}

impl EventLoopState {
    /// Call this to mark the loop as interrupted.
    pub fn interrupt(&mut self) {
        self.interrupted = true;
    }
}

/// Adds a method to obtain an `EventLoop` to the `Nvml` struct.
///
/// `use` it at your leisure.
pub trait EventLoopProvider {
    // Thanks to Thinkofname for lifetime help, again :)
    fn create_event_loop<'nvml>(
        &'nvml self,
        devices: Vec<&'nvml Device<'nvml>>,
    ) -> Result<EventLoop, NvmlErrorWithSource>;
}

impl EventLoopProvider for Nvml {
    /**
    Create an event loop that will register itself to recieve events for the given
    `Device`s.

    This function creates an event set and registers each devices' supported event
    types for it. The returned `EventLoop` struct then has methods that you can
    call to actually utilize it.

    # Errors

    * `Uninitialized`, if the library has not been successfully initialized
    * `GpuLost`, if any of the given `Device`s have fallen off the bus or are
    otherwise inaccessible
    * `Unknown`, on any unexpected error

    # Platform Support

    Only supports Linux.
    */
    fn create_event_loop<'nvml>(
        &'nvml self,
        devices: Vec<&Device<'nvml>>,
    ) -> Result<EventLoop, NvmlErrorWithSource> {
        let mut set = self.create_event_set()?;

        for d in devices {
            set = d.register_events(d.supported_event_types()?, set)?;
        }

        Ok(EventLoop { set })
    }
}
