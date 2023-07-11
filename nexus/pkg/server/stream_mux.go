package server

import (
	"fmt"
	"sync"

	"golang.org/x/exp/slog"
)

// StreamMux is a multiplexer for streams.
// It is thread-safe and is used to ensure that
// only one stream exists for a given streamId so that
// we can safely add responders to streams.
type StreamMux struct {
	mux   map[string]*Stream
	mutex sync.RWMutex
}

func NewStreamMux() *StreamMux {
	return &StreamMux{
		mux: make(map[string]*Stream),
	}
}

// AddStream adds a stream to the mux if it doesn't already exist.
func (sm *StreamMux) AddStream(streamId string, stream *Stream) error {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()
	if _, ok := sm.mux[streamId]; !ok {
		sm.mux[streamId] = stream
		return nil
	} else {
		return fmt.Errorf("stream already exists")
	}
}

func (sm *StreamMux) GetStream(streamId string) (*Stream, error) {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()
	if stream, ok := sm.mux[streamId]; !ok {
		return nil, fmt.Errorf("stream not found")
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

// CloseAllStreams closes all streams in the mux.
func (sm *StreamMux) CloseAllStreams(force bool) {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()

	wg := sync.WaitGroup{}
	for streamId, stream := range sm.mux {
		wg.Add(1)
		go func(stream *Stream) {
			stream.Close(force)
			wg.Done()
		}(stream)
		// delete all streams from mux
		delete(sm.mux, streamId)
	}
	wg.Wait()
	slog.Debug("all streams were closed")
}

// StreamMux is a singleton.
var streamMux = NewStreamMux()
