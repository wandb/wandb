#[cfg(target_os = "linux")]
fn main() -> Result<(), nvml_wrapper::error::NvmlErrorWithSource> {
    use nvml_wrapper::error::NvmlError;
    use nvml_wrapper::Nvml;
    // Bringing this in allows us to use `Nvml.create_event_loop()`
    use nvml_wrapper::high_level::EventLoopProvider;
    // Bringing these in for brevity (Event::SomeEvent vs. SomeEvent)
    use nvml_wrapper::high_level::Event::*;

    let nvml = Nvml::init()?;
    let device = nvml.device_by_index(0)?;

    // Create an event loop, registering the single device we obtained above
    let mut event_loop = nvml.create_event_loop(vec![&device])?;

    // Start handling events
    event_loop.run_forever(|event, state| match event {
        // If there were no errors, extract the event
        Ok(event) => match event {
            ClockChange(device) => {
                if let Ok(uuid) = device.uuid() {
                    println!("ClockChange      event for device with UUID {:?}", uuid);
                } else {
                    // Your error-handling strategy here
                }
            }

            PowerStateChange(device) => {
                if let Ok(uuid) = device.uuid() {
                    println!("PowerStateChange event for device with UUID {:?}", uuid);
                } else {
                    // Your error-handling strategy here
                }
            }

            _ => println!("A different event occurred: {:?}", event),
        },

        // If there was an error, handle it
        Err(e) => match e {
            // If the error is `Unknown`, continue looping and hope for the best
            NvmlError::Unknown => {}
            // The other errors that can occur are almost guaranteed to mean that
            // further looping will never be successful (`GpuLost` and
            // `Uninitialized`), so we stop looping
            _ => state.interrupt(),
        },
    });

    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn main() {
    println!("NVML only supports events on linux :(");
}
