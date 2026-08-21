package analytics

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	otellogapi "go.opentelemetry.io/otel/log"
	collogspb "go.opentelemetry.io/proto/otlp/collector/logs/v1"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

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

func newProxyForTest(
	t *testing.T,
	handler http.Handler,
) *OpenTelemetryProxy {
	t.Helper()

	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)

	proxy := NewOpenTelemetryProxy(
		t.Context(),
		settings.From(&spb.Settings{
			BaseUrl: wrapperspb.String(server.URL),
			ApiKey:  wrapperspb.String("test-api-key"),
		}),
		"wandb-core",
	)
	require.NotNil(t, proxy)
	t.Cleanup(func() {
		_ = proxy.Shutdown(context.Background())
	})
	return proxy
}

func TestOpenTelemetryProxy_DisabledFeatureIsTerminal(t *testing.T) {
	var requestCount int
	proxy := newProxyForTest(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		requestCount++
		w.WriteHeader(http.StatusOK)
	}))

	var featureCalls int
	proxy.EnableIfSupported(t.Context(), serverFeatureProviderFunc(
		func(_ context.Context, feature spb.ServerFeature) bool {
			featureCalls++
			assert.Equal(t, spb.ServerFeature_SDK_TELEMETRY_PROXY, feature)
			return false
		},
	))
	proxy.EnableIfSupported(t.Context(), serverFeatureProviderFunc(
		func(context.Context, spb.ServerFeature) bool {
			t.Fatal("a resolved feature must not be checked again")
			return true
		},
	))

	recorder := NewTelemetryRecorder(proxy, NewTelemetryContext())
	recorder.IncrementCounter(
		t.Context(),
		"disabled_counter",
		LowCardinalityAttributes{},
	)
	recorder.Log(t.Context(), "disabled_log", nil, otellogapi.SeverityInfo)
	require.NoError(t, proxy.Shutdown(context.Background()))

	assert.Equal(t, 1, featureCalls)
	assert.Zero(t, requestCount)
}

func TestEnableProxiesIfSupportedChecksFeatureOnce(t *testing.T) {
	proxyA := newProxyForTest(t, http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusOK)
		},
	))
	proxyB := newProxyForTest(t, http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusOK)
		},
	))

	var featureCalls int
	EnableProxiesIfSupported(
		t.Context(),
		serverFeatureProviderFunc(
			func(_ context.Context, feature spb.ServerFeature) bool {
				featureCalls++
				assert.Equal(t, spb.ServerFeature_SDK_TELEMETRY_PROXY, feature)
				return true
			},
		),
		proxyA,
		proxyB,
	)

	assert.Equal(t, 1, featureCalls)
	assert.Equal(t, proxyStateEnabled, proxyA.state.Load())
	assert.Equal(t, proxyStateEnabled, proxyB.state.Load())
}

func TestOpenTelemetryProxy_FeatureCheckReentryFailsClosed(t *testing.T) {
	var mu sync.Mutex
	var requestCount int
	var logBodies []string
	var handlerErr error
	proxy := newProxyForTest(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			mu.Lock()
			handlerErr = err
			mu.Unlock()
			http.Error(w, "read request", http.StatusBadRequest)
			return
		}
		var exportRequest collogspb.ExportLogsServiceRequest
		if err := proto.Unmarshal(body, &exportRequest); err != nil {
			mu.Lock()
			handlerErr = err
			mu.Unlock()
			http.Error(w, "decode request", http.StatusBadRequest)
			return
		}

		mu.Lock()
		defer mu.Unlock()
		requestCount++
		for _, resourceLogs := range exportRequest.GetResourceLogs() {
			for _, scopeLogs := range resourceLogs.GetScopeLogs() {
				for _, record := range scopeLogs.GetLogRecords() {
					logBodies = append(
						logBodies,
						record.GetBody().GetStringValue(),
					)
				}
			}
		}
		w.WriteHeader(http.StatusOK)
	}))
	recorder := NewTelemetryRecorder(proxy, NewTelemetryContext())

	done := make(chan struct{})
	go func() {
		defer close(done)
		proxy.EnableIfSupported(t.Context(), serverFeatureProviderFunc(
			func(_ context.Context, _ spb.ServerFeature) bool {
				recorder.Log(
					t.Context(),
					"during_feature_check",
					nil,
					otellogapi.SeverityInfo,
				)
				return true
			},
		))
	}()

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("feature check deadlocked while recording telemetry")
	}

	recorder.Log(t.Context(), "after_feature_check", nil, otellogapi.SeverityInfo)
	require.NoError(t, proxy.logProvider.ForceFlush(t.Context()))

	mu.Lock()
	defer mu.Unlock()
	assert.NoError(t, handlerErr)
	assert.Equal(t, 1, requestCount)
	assert.Equal(t, []string{"after_feature_check"}, logBodies)
}

func TestOpenTelemetryProxy_ShutdownDuringFeatureCheckPreventsInitialization(
	t *testing.T,
) {
	proxy := newProxyForTest(t, http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusOK)
		},
	))
	featureCheckStarted := make(chan struct{})
	releaseFeatureCheck := make(chan struct{})
	enableDone := make(chan struct{})

	go func() {
		defer close(enableDone)
		proxy.EnableIfSupported(t.Context(), serverFeatureProviderFunc(
			func(context.Context, spb.ServerFeature) bool {
				close(featureCheckStarted)
				<-releaseFeatureCheck
				return true
			},
		))
	}()
	select {
	case <-featureCheckStarted:
	case <-time.After(time.Second):
		t.Fatal("feature check did not start")
	}

	require.NoError(t, proxy.Shutdown(t.Context()))
	close(releaseFeatureCheck)
	select {
	case <-enableDone:
	case <-time.After(time.Second):
		t.Fatal("feature check did not finish")
	}

	assert.Nil(t, proxy.meterProvider)
	assert.Nil(t, proxy.logProvider)
	assert.Equal(t, proxyStateDisabled, proxy.state.Load())
}

func TestOpenTelemetryProxy_UnsupportedRoutePermanentlyDisablesAllSignals(
	t *testing.T,
) {
	for _, statusCode := range []int{http.StatusNotFound, http.StatusMethodNotAllowed} {
		for _, firstSignal := range []string{"logs", "metrics"} {
			t.Run(http.StatusText(statusCode)+"/"+firstSignal, func(t *testing.T) {
				var mu sync.Mutex
				var paths []string
				proxy := newProxyForTest(t, http.HandlerFunc(
					func(w http.ResponseWriter, r *http.Request) {
						mu.Lock()
						paths = append(paths, r.URL.Path)
						mu.Unlock()
						w.WriteHeader(statusCode)
					},
				))
				proxy.EnableIfSupported(t.Context(), serverFeatureProviderFunc(
					func(context.Context, spb.ServerFeature) bool { return true },
				))
				recorder := NewTelemetryRecorder(proxy, NewTelemetryContext())

				recorder.IncrementCounter(
					t.Context(),
					"before_unsupported_response",
					LowCardinalityAttributes{},
				)
				recorder.Log(
					t.Context(),
					"before_unsupported_response",
					nil,
					otellogapi.SeverityInfo,
				)

				if firstSignal == "logs" {
					require.Error(t, proxy.logProvider.ForceFlush(t.Context()))
					require.NoError(t, proxy.meterProvider.ForceFlush(t.Context()))
				} else {
					require.Error(t, proxy.meterProvider.ForceFlush(t.Context()))
					require.NoError(t, proxy.logProvider.ForceFlush(t.Context()))
				}

				recorder.IncrementCounter(
					t.Context(),
					"after_unsupported_response",
					LowCardinalityAttributes{},
				)
				recorder.Log(
					t.Context(),
					"after_unsupported_response",
					nil,
					otellogapi.SeverityInfo,
				)
				require.NoError(t, proxy.meterProvider.ForceFlush(t.Context()))
				require.NoError(t, proxy.logProvider.ForceFlush(t.Context()))

				mu.Lock()
				defer mu.Unlock()
				require.Equal(t, []string{"/sdk/otel/v1/" + firstSignal}, paths)
			})
		}
	}
}

func TestOpenTelemetryProxy_OtherHTTPFailuresDoNotDisableCapability(t *testing.T) {
	var mu sync.Mutex
	var requestCount int
	proxy := newProxyForTest(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		requestCount++
		if requestCount == 1 {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	proxy.EnableIfSupported(t.Context(), serverFeatureProviderFunc(
		func(context.Context, spb.ServerFeature) bool { return true },
	))
	recorder := NewTelemetryRecorder(proxy, NewTelemetryContext())

	recorder.Log(t.Context(), "first", nil, otellogapi.SeverityInfo)
	_ = proxy.logProvider.ForceFlush(t.Context())
	recorder.Log(t.Context(), "second", nil, otellogapi.SeverityInfo)
	require.NoError(t, proxy.logProvider.ForceFlush(t.Context()))

	mu.Lock()
	defer mu.Unlock()
	assert.Equal(t, 2, requestCount)
}
