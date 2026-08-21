package wbapi

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	otellogapi "go.opentelemetry.io/otel/log"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type serverFeatureProviderFunc func(context.Context, spb.ServerFeature) bool

func (f serverFeatureProviderFunc) Enabled(
	ctx context.Context,
	feature spb.ServerFeature,
) bool {
	return f(ctx, feature)
}

func TestNewDoesNotBlockOnTelemetryFeatureLookup(t *testing.T) {
	featureRequestStarted := make(chan struct{})
	releaseFeatureRequest := make(chan struct{})
	var startOnce sync.Once
	var releaseOnce sync.Once
	var requestCount atomic.Int32
	release := func() { releaseOnce.Do(func() { close(releaseFeatureRequest) }) }

	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			requestCount.Add(1)
			startOnce.Do(func() { close(featureRequestStarted) })
			<-releaseFeatureRequest
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"data":{"serverInfo":{"features":[]}}}`))
		},
	))
	t.Cleanup(func() {
		release()
		server.Close()
	})

	wandbSettings := settings.From(&spb.Settings{
		BaseUrl: wrapperspb.String(server.URL),
		ApiKey:  wrapperspb.String("test-api-key"),
	})
	connectionProxy := analytics.NewOpenTelemetryProxy(
		t.Context(),
		wandbSettings,
		"wandb-core",
	)
	if connectionProxy == nil {
		t.Fatal("expected a connection telemetry proxy")
	}

	result := make(chan struct {
		api *WandbAPI
		err error
	}, 1)
	logger := observabilitytest.NewTestLogger(t)
	go func() {
		api, err := New(
			wandbSettings,
			"wandb-sdk",
			logger,
			connectionProxy,
		)
		result <- struct {
			api *WandbAPI
			err error
		}{api: api, err: err}
	}()

	var got struct {
		api *WandbAPI
		err error
	}
	select {
	case got = <-result:
	case <-time.After(250 * time.Millisecond):
		release()
		<-result
		t.Fatal("New blocked on the telemetry feature lookup")
	}
	if got.err != nil {
		t.Fatalf("New returned an error: %v", got.err)
	}

	select {
	case <-featureRequestStarted:
	case <-time.After(time.Second):
		t.Fatal("telemetry feature lookup did not start")
	}

	shutdownDone := make(chan struct{})
	go func() {
		defer close(shutdownDone)
		got.api.Shutdown(t.Context())
	}()
	select {
	case <-shutdownDone:
	case <-time.After(time.Second):
		t.Fatal("shutdown waited on the telemetry feature lookup")
	}
	if got := requestCount.Load(); got != 1 {
		t.Fatalf("expected one shared feature query for both proxies, got %d", got)
	}
	release()
}

func TestShutdownStartsTelemetryProxyCleanupConcurrently(t *testing.T) {
	proxyA, requestA, releaseA := newBlockingTelemetryProxy(t)
	proxyB, requestB, releaseB := newBlockingTelemetryProxy(t)
	recorderA := analytics.NewTelemetryRecorder(
		proxyA,
		analytics.NewTelemetryContext(),
	)
	recorderB := analytics.NewTelemetryRecorder(
		proxyB,
		analytics.NewTelemetryContext(),
	)
	recorderA.Log(t.Context(), "handler event", nil, otellogapi.SeverityInfo)
	recorderB.Log(t.Context(), "connection event", nil, otellogapi.SeverityInfo)

	api := &WandbAPI{
		logger: observabilitytest.NewTestLogger(t),
		opentelemetryHandler: &OpenTelemetryHandler{
			otelProvider:      proxyA,
			telemetryRecorder: recorderA,
		},
		connectionTelemetryProxy: proxyB,
	}
	shutdownDone := make(chan struct{})
	go func() {
		defer close(shutdownDone)
		api.Shutdown(t.Context())
	}()

	waitForRequest := func(request <-chan struct{}, name string) {
		t.Helper()
		select {
		case <-request:
		case <-time.After(time.Second):
			t.Fatalf("%s proxy did not begin shutdown", name)
		}
	}
	waitForRequest(requestA, "handler")
	waitForRequest(requestB, "connection")
	releaseA()
	releaseB()

	select {
	case <-shutdownDone:
	case <-time.After(time.Second):
		t.Fatal("concurrent telemetry shutdown did not finish")
	}
}

func newBlockingTelemetryProxy(
	t *testing.T,
) (*analytics.OpenTelemetryProxy, <-chan struct{}, func()) {
	t.Helper()

	requestStarted := make(chan struct{})
	releaseRequest := make(chan struct{})
	var requestOnce sync.Once
	var releaseOnce sync.Once
	release := func() { releaseOnce.Do(func() { close(releaseRequest) }) }
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			requestOnce.Do(func() { close(requestStarted) })
			<-releaseRequest
			w.WriteHeader(http.StatusOK)
		},
	))
	t.Cleanup(func() {
		release()
		server.Close()
	})

	proxy := analytics.NewOpenTelemetryProxy(
		t.Context(),
		settings.From(&spb.Settings{
			BaseUrl: wrapperspb.String(server.URL),
			ApiKey:  wrapperspb.String("test-api-key"),
		}),
		"wandb-core",
	)
	if proxy == nil {
		t.Fatal("expected a telemetry proxy")
	}
	proxy.EnableIfSupported(
		t.Context(),
		serverFeatureProviderFunc(
			func(context.Context, spb.ServerFeature) bool { return true },
		),
	)

	return proxy, requestStarted, release
}

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
