package filestream

import (
	"golang.org/x/time/rate"
)

// CollectLoop batches changes together to make filestream requests.
//
// This batches all incoming requests while waiting for transmissions
// to go through.
type CollectLoop struct {
	TransmitRateLimit   *rate.Limiter
	MaxRequestSizeBytes int
}

// Start ingests requests and outputs rate-limited, batched requests.
func (cl CollectLoop) Start(
	requests <-chan *FileStreamRequest,
) <-chan *FileStreamRequestReader {
	transmissions := make(chan *FileStreamRequestReader)

	go func() {
		buffer := &FileStreamRequest{}
		isDone := false

		for request := range requests {
			buffer.Merge(request)
			buffer, isDone = cl.transmit(buffer, requests, transmissions)
		}

		for !isDone {
			reader, _ := NewRequestReader(buffer, cl.MaxRequestSizeBytes)
			transmissions <- reader
			buffer, isDone = reader.Next()
		}

		close(transmissions)
	}()

	return transmissions
}

// transmit accumulates incoming requests until a transmission goes through.
func (cl CollectLoop) transmit(
	buffer *FileStreamRequest,
	requests <-chan *FileStreamRequest,
	transmissions chan<- *FileStreamRequestReader,
) (*FileStreamRequest, bool) {
	for {
		reader, _ := NewRequestReader(buffer, cl.MaxRequestSizeBytes)

		select {
		case transmissions <- reader:
			return reader.Next()

		case request, ok := <-requests:
			if !ok {
				return buffer, false
			}

			buffer.Merge(request)
		}
	}
}
