package filestream

import (
	"compress/gzip"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"golang.org/x/time/rate"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type metricLimitHTTPFunc func(*retryablehttp.Request) (*http.Response, error)

func (fn metricLimitHTTPFunc) Do(r *retryablehttp.Request) (*http.Response, error) {
	return fn(r)
}

func newMetricLimitTestStream(t *testing.T, client api.RetryableClient) *fileStream {
	t.Helper()
	printer := observability.NewPrinter(20)
	t.Cleanup(printer.Close)
	factory := FileStreamFactory{
		BaseURL:         &url.URL{Scheme: "https", Host: "example.test"},
		FeatureProvider: featurechecker.NewPreloaded(nil),
		Logger:          observabilitytest.NewTestLogger(t),
		Operations:      wboperation.NewOperations(),
		Printer:         printer,
		Settings:        settings.New(),
	}
	return factory.New(client, t.Context(), time.Hour, rate.NewLimiter(rate.Inf, 1)).(*fileStream)
}

func metricLimitResponse(code int, body, errorCode string) *http.Response {
	response := &http.Response{
		StatusCode: code,
		Status:     http.StatusText(code),
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader(body)),
	}
	response.Header.Set("X-Wandb-Error-Code", errorCode)
	return response
}

func TestMetricLimitRejectionPreservesCompletion(t *testing.T) {
	for _, stopOnFatal := range []bool{false, true} {
		t.Run(
			map[bool]string{false: "continue training", true: "stop on fatal"}[stopOnFatal],
			func(t *testing.T) {
				var requests []FileStreamRequestJSON
				fs := newMetricLimitTestStream(
					t,
					metricLimitHTTPFunc(func(req *retryablehttp.Request) (*http.Response, error) {
						var data FileStreamRequestJSON
						body, err := req.BodyBytes()
						require.NoError(t, err)
						require.NoError(t, json.Unmarshal(body, &data))
						requests = append(requests, data)
						if len(requests) == 1 {
							return metricLimitResponse(400, `{}`, "run_metric_limit_exceeded"), nil
						}
						return metricLimitResponse(200, `{}`, ""), nil
					}),
				)
				fs.settings = settings.From(
					&spb.Settings{StopOnFatalError: wrapperspb.Bool(stopOnFatal)},
				)
				feedback := make(chan map[string]any, 4)
				data := &FileStreamRequestJSON{
					Files: map[string]OffsetAndContent{
						HistoryFileName: {Content: []string{`{"loss":1}`}},
					},
					Uploaded: []string{"weights"},
				}
				require.NoError(t, fs.send(data, feedback))
				require.NoError(t, fs.send(data, feedback))
				require.NoError(t, fs.send(&FileStreamRequestJSON{}, feedback))
				require.Len(t, requests, 1)
				require.False(t, fs.isDead())
				require.Equal(t, stopOnFatal, fs.IsStopped())

				complete, exitCode := true, int32(7)
				data.Complete, data.ExitCode, data.Preempting = &complete, &exitCode, &complete
				require.NoError(t, fs.send(data, feedback))
				require.Len(t, requests, 2)
				require.Equal(
					t,
					FileStreamRequestJSON{Complete: &complete, ExitCode: &exitCode},
					requests[1],
				)
				require.Len(t, data.Files, 1, "must not mutate the caller's request")
				require.Equal(t, []string{"weights"}, data.Uploaded)
				messages := fs.printer.Read()
				require.Len(t, messages, 1)
				require.Equal(t, observability.Error, messages[0].Severity)
				require.Contains(t, messages[0].Content, "Start a new run")
			},
		)
	}
}

func TestMetricLimitMixedCompletionRetriesOnce(t *testing.T) {
	for _, rejectCompletion := range []bool{false, true} {
		t.Run(
			map[bool]string{false: "completion accepted", true: "completion rejected"}[rejectCompletion],
			func(t *testing.T) {
				calls := 0
				fs := newMetricLimitTestStream(
					t,
					metricLimitHTTPFunc(func(req *retryablehttp.Request) (*http.Response, error) {
						calls++
						var data FileStreamRequestJSON
						body, err := req.BodyBytes()
						require.NoError(t, err)
						require.NoError(t, json.Unmarshal(body, &data))
						if calls == 2 {
							require.Empty(t, data.Files)
							require.Empty(t, data.Uploaded)
							require.Nil(t, data.Preempting)
							require.NotNil(t, data.Complete)
							require.True(t, *data.Complete)
						}
						if calls == 1 || rejectCompletion {
							return metricLimitResponse(400, `{}`, "run_metric_limit_exceeded"), nil
						}
						return metricLimitResponse(200, `{}`, ""), nil
					}),
				)
				complete := true
				err := fs.send(&FileStreamRequestJSON{
					Complete: &complete,
					Files:    map[string]OffsetAndContent{HistoryFileName: {}},
					Uploaded: []string{"weights"},
				}, make(chan map[string]any, 1))
				if rejectCompletion {
					require.Error(t, err)
				} else {
					require.NoError(t, err)
				}
				require.Equal(t, 2, calls)
				require.Len(t, fs.printer.Read(), 1)
			},
		)
	}
}

func TestMetricLimitWarnings(t *testing.T) {
	for _, response := range []string{
		`{}`,
		`{"metric_limit":null}`,
		`{"metric_limit":"invalid"}`,
		`{"metric_limit":{"count":9,"limit":10,"warning":false}}`,
		`{"metric_limit":{"count":"9","limit":10,"warning":true}}`,
		`{"metric_limit":{"count":9,"limit":0,"warning":true}}`,
		`{"metric_limit":{"count":-1,"limit":10,"warning":true}}`,
		`{"metric_limit":{"count":9.5,"limit":10,"warning":true}}`,
	} {
		t.Run(response, func(t *testing.T) {
			body := response
			fs := newMetricLimitTestStream(
				t,
				metricLimitHTTPFunc(func(*retryablehttp.Request) (*http.Response, error) {
					return metricLimitResponse(200, body, ""), nil
				}),
			)
			feedback := make(chan map[string]any, 3)
			require.NoError(t, fs.send(&FileStreamRequestJSON{}, feedback))
			require.Empty(t, fs.printer.Read())
			body = `{"metric_limit":{"count":9,"limit":10,"warning":true},"stopped":true}`
			require.NoError(t, fs.send(&FileStreamRequestJSON{}, feedback))
			require.NoError(t, fs.send(&FileStreamRequestJSON{}, feedback))
			messages := fs.printer.Read()
			require.Len(t, messages, 1)
			require.Equal(t, observability.Warning, messages[0].Severity)
			require.Contains(t, messages[0].Content, "9 of 10")
			<-feedback
			require.Equal(t, true, (<-feedback)["stopped"])
		})
	}
}

func TestMetricLimitUnrelatedErrorsStillFail(t *testing.T) {
	for _, tc := range []struct {
		name   string
		code   int
		header string
	}{
		{"legacy bad request", 400, ""},
		{"other error code", 400, "invalid_request"},
		{"unauthorized", 401, "run_metric_limit_exceeded"},
		{"rate limited", 429, "run_metric_limit_exceeded"},
		{"server error", 500, "run_metric_limit_exceeded"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			fs := newMetricLimitTestStream(
				t,
				metricLimitHTTPFunc(func(*retryablehttp.Request) (*http.Response, error) {
					return metricLimitResponse(tc.code, `{}`, tc.header), nil
				}),
			)
			require.Error(t, fs.send(&FileStreamRequestJSON{}, make(chan map[string]any, 1)))
			require.False(t, fs.metricLimitBlocked)
			require.Empty(t, fs.printer.Read())
		})
	}
}

func TestMetricLimitFinishWithExit(t *testing.T) {
	for _, useGzip := range []bool{false, true} {
		t.Run(map[bool]string{false: "plain", true: "gzip"}[useGzip], func(t *testing.T) {
			requests := make(chan FileStreamRequestJSON, 10)
			server := httptest.NewServer(
				http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					var body io.Reader = r.Body
					if useGzip {
						assert.Equal(t, "gzip", r.Header.Get("Content-Encoding"))
						reader, err := gzip.NewReader(r.Body)
						if !assert.NoError(t, err) {
							http.Error(w, "invalid gzip", 400)
							return
						}
						defer reader.Close()
						body = reader
					}
					var data FileStreamRequestJSON
					if !assert.NoError(t, json.NewDecoder(body).Decode(&data)) {
						http.Error(w, "invalid JSON", 400)
						return
					}
					requests <- data
					if len(data.Files) > 0 || len(data.Uploaded) > 0 {
						w.Header().Set("X-Wandb-Error-Code", "run_metric_limit_exceeded")
						w.WriteHeader(http.StatusBadRequest)
					}
					_, _ = io.WriteString(w, `{}`)
				}),
			)
			defer server.Close()
			fs := newMetricLimitTestStream(t, api.NewClient(api.ClientOptions{RetryMax: 2}))
			fs.baseURL, _ = url.Parse(server.URL)
			fs.featureProvider = featurechecker.NewPreloaded(map[spb.ServerFeature]bool{
				spb.ServerFeature_FILESTREAM_GZIP: useGzip,
			})
			fs.Start("entity", "project", "run", nil)
			firstRow := runhistory.New()
			require.NoError(
				t,
				firstRow.SetFromRecord(&spb.HistoryItem{Key: "loss", ValueJson: "1"}),
			)
			fs.StreamUpdate(&HistoryUpdate{Row: firstRow})

			ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
			defer cancel()
			messages := fs.printer.ReadWait(ctx)
			require.Len(t, messages, 1)
			require.Equal(t, observability.Error, messages[0].Severity)
			nextRow := runhistory.New()
			require.NoError(
				t,
				nextRow.SetFromRecord(&spb.HistoryItem{Key: "another_metric", ValueJson: "2"}),
			)
			fs.StreamUpdate(&HistoryUpdate{Row: nextRow})
			done := make(chan struct{})
			go func() {
				fs.FinishWithExit(7)
				close(done)
			}()
			select {
			case <-done:
			case <-ctx.Done():
				t.Fatal("FinishWithExit did not complete")
			}
			require.Len(t, requests, 2)
			first, completion := <-requests, <-requests
			require.NotEmpty(t, first.Files)
			complete, exitCode := true, int32(7)
			require.Equal(
				t,
				FileStreamRequestJSON{Complete: &complete, ExitCode: &exitCode},
				completion,
			)
			require.False(t, fs.isDead())
			require.Empty(t, fs.printer.Read())
		})
	}
}
