package filestream

// CollectLoop batches changes together to make filestream requests.
//
// This batches all incoming requests while waiting for transmissions
// to go through.
type CollectLoop struct{}

// Start ingests updates and outputs the resulting requests.
func (cl CollectLoop) Start(
	stateUpdates <-chan CollectorStateUpdate,
	initialOffsets FileStreamOffsetMap,
) <-chan FsTransmitData {
	transmissions := make(chan FsTransmitData)

	go func() {
		state := NewCollectorState(initialOffsets)

		for firstUpdate := range stateUpdates {
			firstUpdate.Apply(&state)

		batchingLoop:
			for {
				select {
				case transmissions <- state.PrepRequest(false /*isDone*/):
					state.RequestSent()
					break batchingLoop

				case update, ok := <-stateUpdates:
					if !ok {
						// The accumulated data is sent with the final request.
						break batchingLoop
					}

					update.Apply(&state)
				}
			}
		}

		// Send final transmission.
		transmissions <- state.PrepRequest(true)
		state.RequestSent()
		close(transmissions)
	}()

	return transmissions
}
