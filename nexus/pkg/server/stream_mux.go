package server

import (
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

func NewStreamMux() *StreamMux {
	return &StreamMux{
		mux: make(map[string]*Stream),
	}
}

// addStream adds a stream to the mux if it doesn't already exist.
func (sm *StreamMux) addStream(streamId string, settings *Settings) *Stream {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()
	stream, ok := sm.mux[streamId]
	if !ok {
		stream = NewStream(settings)
		sm.mux[streamId] = stream
	}
	return stream
}

func (sm *StreamMux) getStream(streamId string) (*Stream, bool) {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()
	stream, ok := sm.mux[streamId]
	return stream, ok
}

// todo: add this when we have a way to remove mux
// func (sm *StreamMux) removeStream(streamId string) {
//  	sm.mutex.Lock()
//  	defer sm.mutex.Unlock()
//  	delete(sm.mux, streamId)
// }

// Close closes all streams in the mux.
func (sm *StreamMux) Close() {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()

	wg := sync.WaitGroup{}
	for _, stream := range sm.mux {
		wg.Add(1)
		go stream.Close(&wg) // test this
	}
	wg.Wait()
}

// StreamMux is a singleton.
var streamMux = NewStreamMux()
