package wbapi

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestHandleRequestUnknownTypeIsError(t *testing.T) {
	// A newer client attached to an older wandb-core sends request types
	// this version doesn't know; they must get an error response instead
	// of no response (which would make the client wait until its timeout).
	api := &WandbAPI{
		semaphore: make(chan struct{}, 1),
	}

	response := api.HandleRequest(
		context.Background(),
		"request-id",
		&spb.ApiRequest{},
	)

	apiError := response.GetApiErrorResponse()
	if apiError == nil {
		t.Fatal("expected API error response")
	}
	if !strings.Contains(apiError.GetMessage(), "unsupported API request") {
		t.Fatalf("expected unsupported request error, got %q", apiError.GetMessage())
	}
}

func TestRunHistoryClientUsesFileTransferConfiguration(t *testing.T) {
	var mu sync.Mutex
	var requestCount int
	var extraHeader string

	// The first request fails, so only a retrying client sees a success.
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			mu.Lock()
			requestCount++
			attempt := requestCount
			extraHeader = r.Header.Get("X-Test-Header")
			mu.Unlock()

			if attempt == 1 {
				w.Header().Set("Retry-After", "0")
				w.WriteHeader(http.StatusInternalServerError)
			}
		},
	))
	defer server.Close()

	// The x_file_transfer_* settings are unset, as they are by default.
	wandbAPI, err := New(
		settings.From(&spb.Settings{
			BaseUrl: wrapperspb.String("https://api.wandb.test"),
			XExtraHttpHeaders: &spb.MapStringKeyStringValue{
				Value: map[string]string{"X-Test-Header": "test-value"},
			},
		}),
		observability.NewNoOpLogger(),
	)
	if err != nil {
		t.Fatalf("error creating WandbAPI: %v", err)
	}

	request, err := retryablehttp.NewRequest(http.MethodGet, server.URL, nil)
	if err != nil {
		t.Fatalf("error creating request: %v", err)
	}
	response, err := wandbAPI.runHistoryApiHandler.httpClient.Do(request)
	if err != nil {
		t.Fatalf("error making request: %v", err)
	}
	defer func() { _ = response.Body.Close() }()

	mu.Lock()
	defer mu.Unlock()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("expected request to succeed, got status %d", response.StatusCode)
	}
	if requestCount != 2 {
		t.Errorf("expected the failed request to be retried once, got %d requests", requestCount)
	}
	if extraHeader != "test-value" {
		t.Errorf("expected configured extra header, got %q", extraHeader)
	}
}

func TestHandleRequestReturnsWhenCancelledWaitingForConcurrency(t *testing.T) {
	api := &WandbAPI{
		semaphore: make(chan struct{}, 1),
	}
	api.semaphore <- struct{}{}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan *spb.ApiResponse, 1)
	go func() {
		done <- api.HandleRequest(ctx, "request-id", &spb.ApiRequest{})
	}()

	cancel()

	select {
	case response := <-done:
		apiError := response.GetApiErrorResponse()
		if apiError == nil {
			t.Fatal("expected API error response")
		}
		if !strings.Contains(apiError.GetMessage(), "context canceled") {
			t.Fatalf("expected context cancellation error, got %q", apiError.GetMessage())
		}
	case <-time.After(time.Second):
		t.Fatal("HandleRequest did not return after context cancellation")
	}
}
