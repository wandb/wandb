package filestream

import (
	"context"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"testing"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runencodestats"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// fakeSendClient records the body of each request and always succeeds.
//
// It reads the body through BodyBytes because retryablehttp only populates
// the embedded http.Request.Body when it prepares an attempt.
type fakeSendClient struct {
	bodies [][]byte
}

var _ api.RetryableClient = &fakeSendClient{}

func (c *fakeSendClient) Do(req *retryablehttp.Request) (*http.Response, error) {
	body, err := req.BodyBytes()
	if err != nil {
		return nil, err
	}
	c.bodies = append(c.bodies, body)

	return &http.Response{
		StatusCode: 200,
		Status:     "200 TEST",
		Body:       io.NopCloser(strings.NewReader("{}")),
	}, nil
}

// newSendTestFileStream returns a fileStream for exercising send().
//
// Gzip is disabled so that send() short-circuits before consulting the
// feature provider, which would need a GraphQL client we do not have here.
func newSendTestFileStream(
	t *testing.T,
	stats *runencodestats.Stats,
) (*fileStream, *fakeSendClient) {
	t.Helper()

	baseURL, err := url.Parse("http://test.wandb.ai")
	require.NoError(t, err)

	client := &fakeSendClient{}

	return &fileStream{
		path:            "files/test/test/test/file_stream",
		beforeRunEndCtx: context.Background(),
		settings: settings.From(&spb.Settings{
			XFileStreamNoGzip: wrapperspb.Bool(true),
		}),
		logger:      observabilitytest.NewTestLogger(t),
		operations:  wboperation.NewOperations(),
		apiClient:   client,
		baseURL:     baseURL,
		encodeStats: stats,
	}, client
}

func historyRequestJSON(line string) *FileStreamRequestJSON {
	return &FileStreamRequestJSON{
		Files: map[string]OffsetAndContent{
			HistoryFileName: {Offset: 0, Content: []string{line}},
		},
	}
}

func TestSend_RecordsRequestBytes(t *testing.T) {
	stats := runencodestats.New()
	fs, client := newSendTestFileStream(t, stats)

	feedback := make(chan map[string]any, 1)
	require.NoError(t, fs.send(historyRequestJSON(`{"loss":1}`), feedback))

	attrs := stats.Attributes()
	require.NotNil(t, attrs)
	assert.Equal(t, "1", attrs["requests"])
	assert.Equal(t, "0", attrs["heartbeats"])
	assert.Equal(t, "0", attrs["gzip_requests"])

	// The counted bytes must be the bytes actually sent. Without gzip the
	// compressed and uncompressed sizes agree.
	require.Len(t, client.bodies, 1)
	sent := strconv.Itoa(len(client.bodies[0]))
	assert.Equal(t, sent, attrs["uncompressed_bytes"])
	assert.Equal(t, sent, attrs["compressed_bytes"])
}

func TestSend_HeartbeatIsNotCountedAsRequest(t *testing.T) {
	stats := runencodestats.New()
	fs, _ := newSendTestFileStream(t, stats)

	data := &FileStreamRequestJSON{}
	require.True(t, data.IsHeartbeat())

	feedback := make(chan map[string]any, 1)
	require.NoError(t, fs.send(data, feedback))

	attrs := stats.Attributes()
	require.NotNil(t, attrs)
	assert.Equal(t, "0", attrs["requests"])
	assert.Equal(t, "1", attrs["heartbeats"])
	assert.Equal(t, "0", attrs["uncompressed_bytes"])
}

func TestSend_AccumulatesAcrossRequests(t *testing.T) {
	stats := runencodestats.New()
	fs, client := newSendTestFileStream(t, stats)

	feedback := make(chan map[string]any, 3)
	require.NoError(t, fs.send(historyRequestJSON(`{"a":1}`), feedback))
	require.NoError(t, fs.send(historyRequestJSON(`{"b":2}`), feedback))
	require.NoError(t, fs.send(&FileStreamRequestJSON{}, feedback))

	attrs := stats.Attributes()
	require.NotNil(t, attrs)
	assert.Equal(t, "2", attrs["requests"])
	assert.Equal(t, "1", attrs["heartbeats"])

	total := len(client.bodies[0]) + len(client.bodies[1])
	assert.Equal(t, strconv.Itoa(total), attrs["uncompressed_bytes"])
}

func TestSend_NilStatsIsNoOp(t *testing.T) {
	fs, _ := newSendTestFileStream(t, nil)

	feedback := make(chan map[string]any, 1)
	assert.NotPanics(t, func() {
		require.NoError(t, fs.send(historyRequestJSON(`{"loss":1}`), feedback))
	})
}
