package server_test

import (
	"context"
	"testing"

	"github.com/wandb/wandb/core/pkg/observability"
	server "github.com/wandb/wandb/core/pkg/server"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestNewWriter(t *testing.T) {
	ctx := context.Background()
	settings := &service.Settings{}
	logger := &observability.CoreLogger{}

	writer := server.NewWriter(ctx, settings, logger)

	if writer == nil {
		t.Error("Expected non-nil Writer, got nil")
	}
}

// func TestWriterStartStore(t *testing.T) {
// 	ctx := context.Background()
// 	settings := &service.Settings{}
// 	logger := &observability.CoreLogger{}

// 	writer := server.NewWriter(ctx, settings, logger)

// 	inChan := make(chan *service.Record, 1)
// 	writer.Write(inChan)

// 	// if writer.StoreChan == nil {
// 	// 	t.Error("Expected non-nil StoreChan, got nil")
// 	// }
// }
