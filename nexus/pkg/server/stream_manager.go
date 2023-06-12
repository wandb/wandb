package server

import (
	"context"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type StreamManager struct {
	streams map[string]*Stream
	mutex   sync.RWMutex
}

func NewStreamManager() *StreamManager {
	return &StreamManager{
		streams: make(map[string]*Stream),
	}
}

func (sm *StreamManager) addStream(streamId string, respondServerResponse func(context.Context, *service.ServerResponse),
	settings *Settings) *Stream {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()
	stream, ok := sm.streams[streamId]
	if !ok {
		stream = NewStream(respondServerResponse, settings)
		sm.streams[streamId] = stream
	}
	return stream
}

func (sm *StreamManager) getStream(streamId string) (*Stream, bool) {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()
	stream, ok := sm.streams[streamId]
	return stream, ok
}

func (sm *StreamManager) getStreams() map[string]*Stream {
	sm.mutex.RLock()
	defer sm.mutex.RUnlock()
	return sm.streams
}

var streamManager = NewStreamManager()
