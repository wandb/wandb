package runworktest

import (
	"context"
	"testing"

	"github.com/wandb/wandb/core/internal/runwork"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// SimpleRequest creates a request for testing.
//
// The request's context is cancelled at the end of the test.
// The output channel is 1-buffered, so that responding to the request does
// not block.
func SimpleRequest(
	t *testing.T,
	id string,
) (*runwork.Request, <-chan *spb.ServerResponse) {
	t.Helper()

	// t.Context() is cancelled at the end of the test, so invoking cancel()
	// in t.Cleanup() is not required.
	ctx, cancel := context.WithCancel(t.Context())
	outputs := make(chan *spb.ServerResponse, 1)

	return runwork.NewRequest(id, ctx, cancel, outputs), outputs
}
