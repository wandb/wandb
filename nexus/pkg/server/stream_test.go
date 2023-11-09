package server

import (
	"context"
	"testing"

	"github.com/wandb/wandb/nexus/pkg/service"
)

func TestStreamHandleRecord(t *testing.T) {
	ctx := context.Background()
	settings := &service.Settings{} // fill in settings as required
	stream := NewStream(ctx, settings, "test-stream-id")

	mockHandler := NewMockHandlerInterface(t)
	// mockHandler.On(
	// 	"SetInboundChannels",
	// 	mock.AnythingOfType("<-chan *service.Record"),
	// 	mock.AnythingOfType("<-chan *service.Record"),
	// 	mock.AnythingOfType("chan *service.Record"),
	// ).Return()
	// mockHandler.On("SetOutboundChannels", mock.Anything, mock.Anything).Return()
	// mockHandler.On("Handle").Return()
	stream.SetHandler(mockHandler)

	// TODO: convert writer, sender, and dispatcher to interfaces and mock them
	// stream.Start()

	// record := &service.Record{}
	// stream.HandleRecord(record)

	// stream.wg.Wait()

	// mockHandler.AssertCalled(t, "Handle")
}
