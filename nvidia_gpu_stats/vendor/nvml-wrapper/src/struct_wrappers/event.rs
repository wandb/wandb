use crate::device::Device;
use crate::enums::event::XidError;
use crate::ffi::bindings::*;
use crate::{bitmasks::event::EventTypes, Nvml};

/// Information about an event that has occurred.
// Checked against local
#[derive(Debug)]
pub struct EventData<'nvml> {
    /**
    Device where the event occurred.

    See `Device.uuid()` for a way to compare this `Device` to another `Device`
    and find out if they represent the same physical device.
    */
    pub device: Device<'nvml>,
    /// Information about what specific event occurred.
    pub event_type: EventTypes,
    /**
    Stores the last XID error for the device for the
    nvmlEventTypeXidCriticalError event.

    `None` in the case of any other event type.
    */
    pub event_data: Option<XidError>,
}

impl<'nvml> EventData<'nvml> {
    /**
    Create a new `EventData` wrapper.

    The `event_type` bitmask is created via the `EventTypes::from_bits_truncate`
    method, meaning that any bits that don't correspond to flags present in this
    version of the wrapper will be dropped.

    # Safety

    It is your responsibility to ensure that the given `nvmlEventdata_t` pointer
    is valid.
    */
    // Clippy bug, see https://github.com/rust-lang/rust-clippy/issues/5593
    #[allow(clippy::missing_safety_doc)]
    pub unsafe fn new(event_data: nvmlEventData_t, nvml: &'nvml Nvml) -> Self {
        let event_type = EventTypes::from_bits_truncate(event_data.eventType);

        EventData {
            // SAFETY: it is the callers responsibility to ensure that `event_data`
            // is a valid pointer (meaning its contents will be valid)
            device: Device::new(event_data.device, nvml),
            event_type,
            event_data: if event_type.contains(EventTypes::CRITICAL_XID_ERROR) {
                Some(match event_data.eventData {
                    999 => XidError::Unknown,
                    v => XidError::Value(v),
                })
            } else {
                None
            },
        }
    }
}
