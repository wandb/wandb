package stream

import (
	"fmt"
	"log/slog"
	"maps"
	"slices"
	"sync"
)

// StreamMux is a multiplexer for streams.
// It is thread-safe and is used to ensure that
// only one stream exists for a given streamId so that
// we can safely add responders to streams.
type StreamMux struct {
	mux   map[string]*Stream
	mutex sync.RWMutex
}

// NewStreamMux creates a new stream mux.
func NewStreamMux() *StreamMux {
	return &StreamMux{
		mux: make(map[string]*Stream),
	}
}

// AddStream adds a stream to the mux if it doesn't already exist.
func (sm *StreamMux) AddStream(streamId string, stream *Stream) error {
	sm.mutex.Lock()
	defer sm.mutex.Unlock()
	if _, ok := sm.mux[streamId]; !ok {
		sm.mux[streamId] = stream
		return nil
	} else {
		return fmt.Errorf("run ID %s is in use", streamId)
	}
}

// GetStream gets a stream from the mux.
func (sm *StreamMux) GetStream(streamId string) (*Stream, error) {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()
	if stream, ok := sm.mux[streamId]; !ok {
		return nil, fmt.Errorf("stream %s not found", streamId)
	} else {
		return stream, nil
	}
}

// RemoveStream removes a stream from the mux.
func (sm *StreamMux) RemoveStream(streamId string) (*Stream, error) {
	sm.mutex.Lock()
	defer sm.mutex.Unlock()
	if stream, ok := sm.mux[streamId]; !ok {
		return nil, fmt.Errorf("stream not found %s", streamId)
	} else {
		delete(sm.mux, streamId)
		return stream, nil
	}
}

// popAllStreams removes all streams from the mux and returns them.
func (sm *StreamMux) popAllStreams() []*Stream {
	sm.mutex.Lock()
	defer sm.mutex.Unlock()

	streams := slices.Collect(maps.Values(sm.mux))
	clear(sm.mux)
	return streams
}

// FinishAndCloseAllStreams closes all streams in the mux.
//
// Blocks until all streams are done.
func (sm *StreamMux) FinishAndCloseAllStreams(exitCode int32) {
	wg := sync.WaitGroup{}
	for _, stream := range sm.popAllStreams() {
		wg.Go(func() {
			stream.FinishAndClose(exitCode)
		})
	}
	wg.Wait()
	slog.Debug("all streams were closed")
}
