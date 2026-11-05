package filestream

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/wboperation"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestFatalResultPreservesFirstFailure(t *testing.T) {
	fs := &fileStream{
		settings:     settings.From(&spb.Settings{}),
		logger:       observability.NewNoOpLogger(),
		printer:      observability.NewPrinter(10),
		deadChan:     make(chan struct{}),
		deadChanOnce: &sync.Once{},
	}
	require.NoError(t, fs.Err())
	first := errors.New("upload rejected")
	fs.logFatalAndStopWorking(first)
	require.ErrorIs(t, fs.Err(), first)
	require.True(t, fs.isDead())
	// Failed follow-up work must not hide the original failure.
	fs.logFatalAndStopWorking(errors.New("already stopped"))
	require.ErrorIs(t, fs.Err(), first)
}

func TestFatalResultConcurrentReaders(t *testing.T) {
	fs := &fileStream{
		settings:     settings.From(&spb.Settings{}),
		logger:       observability.NewNoOpLogger(),
		printer:      observability.NewPrinter(10),
		deadChan:     make(chan struct{}),
		deadChanOnce: &sync.Once{},
	}
	var wg sync.WaitGroup
	for range 10 {
		wg.Go(func() {
			for range 100 {
				_ = fs.Err()
			}
		})
	}
	failure := errors.New("upload failed")
	fs.logFatalAndStopWorking(failure)
	wg.Wait()
	require.ErrorIs(t, fs.Err(), failure)
}

func TestUploadResultAfterHTTPFailures(t *testing.T) {
	for _, scenario := range []string{"success", "429_then_success", "lost_response", "terminal", "exhausted"} {
		t.Run(scenario, func(t *testing.T) {
			var attempts atomic.Int32
			server := httptest.NewServer(
				http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					n := attempts.Add(1)
					switch {
					case scenario == "terminal":
						w.WriteHeader(403)
						return
					case scenario == "exhausted":
						w.WriteHeader(500)
						return
					case scenario == "429_then_success" && n == 1:
						w.WriteHeader(429)
						return
					case scenario == "lost_response" && n == 1:
						conn, _, err := w.(http.Hijacker).Hijack()
						if err == nil {
							_ = conn.Close()
						}
						return
					}
					_, _ = io.WriteString(w, `{}`)
				}),
			)
			defer server.Close()
			baseURL, err := url.Parse(server.URL)
			require.NoError(t, err)
			logger := observability.NewNoOpLogger()
			factory := FileStreamFactory{
				BaseURL: baseURL,
				Logger:  logger,
				FeatureProvider: featurechecker.New(
					nil,
					logger,
				),
				Printer:    observability.NewPrinter(10),
				Settings:   settings.From(&spb.Settings{}),
				Operations: wboperation.NewOperations(),
			}
			client := api.NewClient(
				api.ClientOptions{RetryMax: 1, RetryPolicy: clients.RetryMostFailures},
			)
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			fs := factory.New(client, ctx, time.Minute, rate.NewLimiter(rate.Inf, 1))
			fs.Start("entity", "project", "run", nil)
			fs.FinishWithExit(0)
			if scenario == "terminal" || scenario == "exhausted" {
				require.Error(t, fs.Err())
			} else {
				require.NoError(t, fs.Err())
			}
			expected := int32(2)
			if scenario == "terminal" || scenario == "success" {
				expected = 1
			}
			require.Equal(t, expected, attempts.Load())
		})
	}
}
