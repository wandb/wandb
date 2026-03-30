package runwork_test

import (
	"context"
	"sync"
	"testing"
	"testing/synctest"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func newRequestForTests(t *testing.T, id string) (
	*runwork.Request,
	chan *spb.ServerResponse,
	context.CancelFunc,
) {
	responses := make(chan *spb.ServerResponse)
	ctx, cancelCtx := context.WithCancel(context.Background())

	t.Cleanup(cancelCtx)

	return runwork.NewRequest(id, ctx, cancelCtx, responses), responses, cancelCtx
}

func TestNilRequest(t *testing.T) {
	var request *runwork.Request

	assert.Panics(t, func() { request.Context() })
	assert.NotPanics(t, func() { request.Respond(nil) })
	assert.NotPanics(t, func() { request.WillNotRespond() })
}

func TestRespond_SetsID(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		request, responses, _ := newRequestForTests(t, "test ID")

		go request.Respond(&spb.ServerResponse{})
		response := <-responses

		assert.Equal(t, "test ID", response.RequestId)
	})
}

func TestRespond_CancelsCtx(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		request, responses, _ := newRequestForTests(t, "test ID")

		go request.Respond(&spb.ServerResponse{})
		<-responses

		// synctest fails the test if this blocks.
		<-request.Context().Done()
	})
}

func TestRespond_OnlyOnce(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		request, responses, _ := newRequestForTests(t, "test ID")

		// Respond in several goroutines simultaneously.
		for range 10 {
			go request.Respond(&spb.ServerResponse{})
		}

		// Only a single response should go through.
		// Any extra goroutines attempting to write on the channel will
		// panic once it closes, failing the test.
		<-responses
		close(responses)
	})
}

func TestRespond_GivesUpOnceCancelled(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		request, _, cancel := newRequestForTests(t, "test ID")

		// Wait until Respond() blocks on writing to the channel.
		wg := &sync.WaitGroup{}
		wg.Go(func() { request.Respond(&spb.ServerResponse{}) })
		synctest.Wait()

		cancel()  // cancelling should release the goroutine
		wg.Wait() // synctest panics if this deadlocks
	})
}
