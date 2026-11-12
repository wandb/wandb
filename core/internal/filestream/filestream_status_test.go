package filestream_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"golang.org/x/time/rate"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// historyLine is an Update that adds one history line to a request.
type historyLine string

func (h historyLine) Apply(ctx filestream.UpdateContext) error {
	ctx.MakeRequest(&filestream.FileStreamRequest{
		HistoryLines: []string{string(h)},
	})
	return nil
}

// uploadWithStatus sends one history line to a server that answers every
// request with the given status, and returns the printed messages.
func uploadWithStatus(t *testing.T, status int, syncDir string) []string {
	t.Helper()
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, _ *http.Request) {
			requests.Add(1)
			w.WriteHeader(status)
		}))
	t.Cleanup(server.Close)
	baseURL, err := url.Parse(server.URL)
	require.NoError(t, err)

	logger := observabilitytest.NewTestLogger(t)
	printer := observability.NewPrinter(10)
	factory := &filestream.FileStreamFactory{
		BaseURL:         api.WBBaseURL(baseURL),
		FeatureProvider: featurechecker.New(nil, logger),
		Logger:          logger,
		Printer:         printer,
		Settings: settings.From(&spb.Settings{
			SyncDir: wrapperspb.String(syncDir),
		}),
	}
	fs := factory.New(
		api.NewClient(api.ClientOptions{
			RetryPolicy:     clients.RetryMostFailures,
			NonRetryTimeout: 10 * time.Second,
		}),
		context.Background(),
		time.Hour,
		rate.NewLimiter(rate.Inf, 1),
	)
	fs.Start("entity", "project", "run", nil)
	fs.StreamUpdate(historyLine(`{"_step":0}`))
	fs.FinishWithExit(0)
	require.Positive(t, requests.Load())

	var messages []string
	for _, m := range printer.Read() {
		messages = append(messages, m.Content)
	}
	return messages
}

func TestSend_300IsNotSuccess(t *testing.T) {
	messages := uploadWithStatus(t, http.StatusMultipleChoices, "/runs/run-x")

	require.Len(t, messages, 1, "a 300 response must stop the upload")
	assert.Contains(t, messages[0], "Fatal error while uploading data")
}

func TestSend_200IsSuccess(t *testing.T) {
	messages := uploadWithStatus(t, http.StatusOK, "/runs/run-x")

	assert.Empty(t, messages)
}

func TestFatalError_SyncAdviceIncludesOnlineRuns(t *testing.T) {
	messages := uploadWithStatus(t, http.StatusBadRequest, "/runs/run-x")

	require.Len(t, messages, 1)
	assert.Contains(t, messages[0],
		"`wandb sync --include-online /runs/run-x`")
}

func TestFatalError_SyncAdviceWithoutRunDir(t *testing.T) {
	messages := uploadWithStatus(t, http.StatusBadRequest, "")

	require.Len(t, messages, 1)
	assert.Contains(t, messages[0],
		"`wandb sync --include-online <run directory>`")
}
