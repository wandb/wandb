package filestream_test

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
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

// sizeLimitedServer is a filestream backend behind a proxy that rejects
// request bodies over a size limit with 413, like nginx's
// client_max_body_size.
type sizeLimitedServer struct {
	mu sync.Mutex

	limit      int
	rejectAll  bool
	rejections int
	accepted   []filestream.FileStreamRequestJSON
}

func (s *sizeLimitedServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		w.WriteHeader(http.StatusBadRequest)
		return
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if s.rejectAll || len(body) > s.limit {
		s.rejections++
		w.WriteHeader(http.StatusRequestEntityTooLarge)
		_, _ = w.Write([]byte("<html>413 Request Entity Too Large</html>"))
		return
	}

	var request filestream.FileStreamRequestJSON
	if err := json.Unmarshal(body, &request); err != nil {
		w.WriteHeader(http.StatusBadRequest)
		return
	}
	s.accepted = append(s.accepted, request)
	_, _ = w.Write([]byte("{}"))
}

// historyLines is an Update that adds raw history lines to a request.
type historyLines []string

func (h historyLines) Apply(ctx filestream.UpdateContext) error {
	ctx.MakeRequest(&filestream.FileStreamRequest{HistoryLines: h})
	return nil
}

func makeHistoryLines(n, size int) []string {
	lines := make([]string, n)
	for i := range lines {
		// Quotes in the padding are escaped in the request, like the quotes
		// in real history JSON.
		padding := strings.Repeat(`"x`, size/2)
		lines[i] = fmt.Sprintf(`{"_step":%d,"pad":%q}`, i, padding)
	}
	return lines
}

// startFileStream starts uploading to the server.
func startFileStream(
	t *testing.T,
	server *sizeLimitedServer,
	settingsProto *spb.Settings,
) filestream.FileStream {
	t.Helper()
	httpServer := httptest.NewServer(server)
	t.Cleanup(httpServer.Close)
	baseURL, err := url.Parse(httpServer.URL)
	require.NoError(t, err)

	logger := observabilitytest.NewTestLogger(t)
	factory := &filestream.FileStreamFactory{
		BaseURL:         api.WBBaseURL(baseURL),
		FeatureProvider: featurechecker.New(nil, logger),
		Logger:          logger,
		Printer:         observability.NewPrinter(0),
		Settings:        settings.From(settingsProto),
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
	return fs
}

// finishFileStream finishes the run and waits for uploads to end.
func finishFileStream(t *testing.T, fs filestream.FileStream) {
	t.Helper()
	done := make(chan struct{})
	go func() {
		defer close(done)
		fs.FinishWithExit(0)
	}()
	select {
	case <-done:
	case <-time.After(30 * time.Second):
		t.Fatal("filestream did not finish")
	}
}

// runFileStream uploads the updates to the server and finishes the run.
func runFileStream(
	t *testing.T,
	server *sizeLimitedServer,
	updates ...filestream.Update,
) {
	t.Helper()
	runFileStreamWithSettings(t, server, &spb.Settings{}, updates...)
}

// runFileStreamWithSettings is runFileStream with the given settings.
func runFileStreamWithSettings(
	t *testing.T,
	server *sizeLimitedServer,
	settingsProto *spb.Settings,
	updates ...filestream.Update,
) {
	t.Helper()
	fs := startFileStream(t, server, settingsProto)
	for _, update := range updates {
		fs.StreamUpdate(update)
	}
	finishFileStream(t, fs)
}

// acceptedHistory returns the accepted history lines by offset.
func acceptedHistory(t *testing.T, s *sizeLimitedServer) map[int]string {
	t.Helper()
	lines := make(map[int]string)
	for _, request := range s.accepted {
		chunk, ok := request.Files[filestream.HistoryFileName]
		if !ok {
			continue
		}
		for i, line := range chunk.Content {
			_, duplicate := lines[chunk.Offset+i]
			require.False(t, duplicate, "offset %d sent twice", chunk.Offset+i)
			lines[chunk.Offset+i] = line
		}
	}
	return lines
}

// requireCompleteOnlyLast checks that only the final request marks the run
// complete, so no data arrives after the run is finished.
func requireCompleteOnlyLast(t *testing.T, s *sizeLimitedServer) {
	t.Helper()
	require.NotEmpty(t, s.accepted)
	for i, request := range s.accepted {
		isLast := i == len(s.accepted)-1
		require.Equal(t, isLast, request.Complete != nil && *request.Complete,
			"request %d of %d", i+1, len(s.accepted))
	}
}

// requireNeverComplete checks that no accepted request marks the run complete.
func requireNeverComplete(t *testing.T, s *sizeLimitedServer) {
	t.Helper()
	for i, request := range s.accepted {
		require.Nil(t, request.Complete, "request %d marks the run complete", i)
	}
}

func TestFileStream_SplitsRequestsRejectedAsTooLarge(t *testing.T) {
	server := &sizeLimitedServer{limit: 300 << 10}
	lines := makeHistoryLines(400, 4<<10) // about 3.2 MB of JSON

	runFileStream(t, server, historyLines(lines))

	got := acceptedHistory(t, server)
	require.Len(t, got, len(lines))
	for i, line := range lines {
		require.Equal(t, line, got[i], "offset %d", i)
	}
	requireCompleteOnlyLast(t, server)
	for i, request := range server.accepted {
		body, err := json.Marshal(request)
		require.NoError(t, err)
		require.LessOrEqual(t, len(body), server.limit, "request %d", i)
	}
}

func TestFileStream_LowersSizeCapAfterRejection(t *testing.T) {
	server := &sizeLimitedServer{limit: 300 << 10}
	fs := startFileStream(t, server, &spb.Settings{})

	first := makeHistoryLines(400, 4<<10)
	fs.StreamUpdate(historyLines(first))
	require.Eventually(t, func() bool {
		server.mu.Lock()
		defer server.mu.Unlock()
		return len(acceptedHistory(t, server)) == len(first)
	}, 30*time.Second, 10*time.Millisecond)
	server.mu.Lock()
	rejectionsBefore := server.rejections
	server.mu.Unlock()
	require.Positive(t, rejectionsBefore, "control: the first batch is too large")

	// Later requests are built under the lowered cap, so none are rejected.
	fs.StreamUpdate(historyLines(makeHistoryLines(400, 4<<10)))
	finishFileStream(t, fs)

	assert.Equal(t, rejectionsBefore, server.rejections)
	assert.Len(t, acceptedHistory(t, server), 800)
	requireCompleteOnlyLast(t, server)
}

func TestFileStream_SingleLineRejectedAsTooLargeIsFatal(t *testing.T) {
	server := &sizeLimitedServer{limit: 100 << 10}
	lines := makeHistoryLines(20, 1<<10)
	lines[10] = makeHistoryLines(1, 200<<10)[0] // too large for the proxy

	runFileStream(t, server, historyLines(lines))

	// Lines before the oversized one are delivered at their offsets. The
	// oversized line cannot be split, which stops the uploader: nothing
	// after it is sent, and the run is never marked complete.
	got := acceptedHistory(t, server)
	for offset, line := range got {
		require.Less(t, offset, 10, "nothing at or after the oversized line")
		require.Equal(t, lines[offset], line)
	}
	require.NotEmpty(t, got, "control: earlier parts are still delivered")
	requireNeverComplete(t, server)
}

func TestFileStream_SmallRequestRejectedAsTooLargeIsFatal(t *testing.T) {
	// A 413 for a small request is not about its size, so the uploader
	// must stop instead of splitting the run down to nothing.
	server := &sizeLimitedServer{rejectAll: true}

	runFileStream(t, server, historyLines(makeHistoryLines(20, 1<<10)))

	assert.Empty(t, server.accepted)
	assert.Equal(t, 1, server.rejections)
}

func makeUploadedNames(n int) []string {
	names := make([]string, n)
	for i := range names {
		names[i] = fmt.Sprintf("media/images/sample_%06d_%s.png", i, strings.Repeat("x", 16))
	}
	return names
}

// uploadedFiles is an Update that reports uploaded run files.
type uploadedFiles []string

func (u uploadedFiles) Apply(ctx filestream.UpdateContext) error {
	files := make(map[string]struct{}, len(u))
	for _, name := range u {
		files[name] = struct{}{}
	}
	ctx.MakeRequest(&filestream.FileStreamRequest{UploadedFiles: files})
	return nil
}

func TestFileStream_UploadedFileNamesRespectSizeCap(t *testing.T) {
	// With the cap under the proxy's limit, a long list of uploaded file
	// names is spread over several requests instead of being rejected.
	server := &sizeLimitedServer{limit: 100 << 10}
	names := makeUploadedNames(4000)

	runFileStreamWithSettings(t, server,
		&spb.Settings{XFileStreamMaxBytes: wrapperspb.Int32(90 << 10)},
		uploadedFiles(names))

	var got []string
	for _, request := range server.accepted {
		got = append(got, request.Uploaded...)
	}
	assert.ElementsMatch(t, names, got)
	assert.Zero(t, server.rejections)
	requireCompleteOnlyLast(t, server)
}

func TestFileStream_UploadedFileNamesOverProxyLimitAreFatal(t *testing.T) {
	// Known limitation: uploaded file names are limited by the SDK's cap,
	// not split after a 413. If the proxy's limit is below the cap, the
	// request fails, uploads stop and the run is never marked complete.
	server := &sizeLimitedServer{limit: 100 << 10}

	runFileStream(t, server, uploadedFiles(makeUploadedNames(4000)))

	assert.Empty(t, server.accepted)
	requireNeverComplete(t, server)
}

// requireDeliveredWhileOpen waits for the server to accept everything
// without the run finishing, then finishes it.
func requireDeliveredWhileOpen(
	t *testing.T,
	server *sizeLimitedServer,
	fs filestream.FileStream,
	delivered func() bool,
) {
	t.Helper()
	require.Eventually(t, func() bool {
		server.mu.Lock()
		defer server.mu.Unlock()
		return delivered()
	}, 10*time.Second, 10*time.Millisecond,
		"leftover data must be sent without another update or finish()")
	finishFileStream(t, fs)
}

func TestFileStream_SendsLeftoverUploadedNamesWhileRunIsOpen(t *testing.T) {
	server := &sizeLimitedServer{limit: 100 << 10}
	fs := startFileStream(t, server,
		&spb.Settings{XFileStreamMaxBytes: wrapperspb.Int32(90 << 10)})
	names := makeUploadedNames(4000)

	fs.StreamUpdate(uploadedFiles(names))

	requireDeliveredWhileOpen(t, server, fs, func() bool {
		n := 0
		for _, request := range server.accepted {
			n += len(request.Uploaded)
		}
		return n == len(names)
	})
}

func TestFileStream_SendsLeftoverHistoryWhileRunIsOpen(t *testing.T) {
	server := &sizeLimitedServer{limit: 1 << 20}
	fs := startFileStream(t, server,
		&spb.Settings{XFileStreamMaxBytes: wrapperspb.Int32(90 << 10)})
	lines := makeHistoryLines(200, 4<<10) // about 1.6 MB of JSON

	fs.StreamUpdate(historyLines(lines))

	requireDeliveredWhileOpen(t, server, fs, func() bool {
		return len(acceptedHistory(t, server)) == len(lines)
	})
}
