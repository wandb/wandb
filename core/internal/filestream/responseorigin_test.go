package filestream

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/clients"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ---------------------------------------------------------------------------
// RetryPolicy unit tests
// ---------------------------------------------------------------------------

func response(status int, marked bool) *http.Response {
	resp := &http.Response{
		StatusCode: status,
		Header:     http.Header{},
		Body:       io.NopCloser(strings.NewReader("")),
	}
	if marked {
		resp.Header.Set(api.ServerHeader, api.ServerHeaderValue)
	}
	return resp
}

func withRule(t *testing.T, deadline time.Duration) context.Context {
	t.Helper()
	return withUnmarked404Retry(
		t.Context(),
		deadline,
		observabilitytest.NewTestLogger(t),
	)
}

// Without the rule, the filestream policy is exactly RetryMostFailures.
func TestRetryPolicy_WithoutRule_SameAsRetryMostFailures(t *testing.T) {
	for _, status := range []int{
		200, 300, 400, 401, 403, 404, 409, 410, 413, 415, 422, 429,
		500, 501, 502, 503, 504,
	} {
		for _, marked := range []bool{false, true} {
			resp := response(status, marked)

			got, gotErr := RetryPolicy(t.Context(), resp, nil)
			want, wantErr := clients.RetryMostFailures(t.Context(), resp, nil)

			assert.Equal(t, want, got, "status %d marked %v", status, marked)
			assert.Equal(t, wantErr, gotErr)
		}
	}
}

// Acceptance test 8: with the rule on, every response other than an unmarked
// 404 is handled as before, including 5xx and 429 retries.
func TestRetryPolicy_WithRule_OtherStatusesUnchanged(t *testing.T) {
	ctx := withRule(t, time.Hour)

	for _, status := range []int{
		200, 300, 400, 401, 403, 409, 410, 413, 415, 422, 429,
		500, 501, 502, 503, 504,
	} {
		for _, marked := range []bool{false, true} {
			resp := response(status, marked)

			got, _ := RetryPolicy(ctx, resp, nil)
			want, _ := clients.RetryMostFailures(ctx, resp, nil)

			assert.Equal(t, want, got, "status %d marked %v", status, marked)
		}
	}

	got, _ := RetryPolicy(ctx, response(404, true), nil)
	assert.False(t, got, "a marked 404 still stops")
}

func TestRetryPolicy_UnmarkedNotFound_RetriesUntilDeadline(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		ctx := withRule(t, time.Hour)

		first, _ := RetryPolicy(ctx, response(404, false), nil)
		time.Sleep(59 * time.Minute)
		beforeDeadline, _ := RetryPolicy(ctx, response(404, false), nil)
		time.Sleep(time.Minute)
		atDeadline, _ := RetryPolicy(ctx, response(404, false), nil)

		assert.True(t, first)
		assert.True(t, beforeDeadline)
		assert.False(t, atDeadline)
	})
}

func TestRetryPolicy_MarkedNotFoundStopsStreak(t *testing.T) {
	ctx := withRule(t, time.Hour)

	unmarked, _ := RetryPolicy(ctx, response(404, false), nil)
	marked, _ := RetryPolicy(ctx, response(404, true), nil)

	assert.True(t, unmarked)
	assert.False(t, marked)
}

// The deadline counts only an unbroken run of unmarked 404s. Time spent on
// other retried failures, like 503s, keeps their own budget.
func TestRetryPolicy_OtherResponseRestartsDeadline(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		ctx := withRule(t, time.Hour)

		_, _ = RetryPolicy(ctx, response(404, false), nil)
		time.Sleep(50 * time.Minute)
		retried503, _ := RetryPolicy(ctx, response(503, false), nil)
		time.Sleep(20 * time.Minute)
		afterGap, _ := RetryPolicy(ctx, response(404, false), nil)
		time.Sleep(59 * time.Minute)
		stillWithin, _ := RetryPolicy(ctx, response(404, false), nil)
		time.Sleep(time.Minute)
		past, _ := RetryPolicy(ctx, response(404, false), nil)

		assert.True(t, retried503)
		assert.True(t, afterGap)
		assert.True(t, stillWithin)
		assert.False(t, past)
	})
}

func TestRetryPolicy_CancelledContextStops(t *testing.T) {
	ctx, cancel := context.WithCancel(withRule(t, time.Hour))
	cancel()

	retry, err := RetryPolicy(ctx, response(404, false), nil)

	assert.False(t, retry)
	assert.ErrorIs(t, err, context.Canceled)
}

// ---------------------------------------------------------------------------
// End-to-end acceptance tests
// ---------------------------------------------------------------------------

type scriptedResponse struct {
	status int
	marked bool
}

var (
	markedOK         = scriptedResponse{http.StatusOK, true}
	unmarkedOK       = scriptedResponse{http.StatusOK, false}
	markedNotFound   = scriptedResponse{http.StatusNotFound, true}
	unmarkedNotFound = scriptedResponse{http.StatusNotFound, false}
)

// originTestServer is a filestream endpoint that replies from a script.
type originTestServer struct {
	mu sync.Mutex

	// script is the responses to give, in order.
	script []scriptedResponse

	// fallback is the response once the script is used up.
	fallback scriptedResponse

	// served is the status of every response given.
	served []int

	// steps is the _step of every history row accepted with a 2xx.
	steps []int64

	server *httptest.Server
}

func newOriginTestServer(t *testing.T, fallback scriptedResponse) *originTestServer {
	t.Helper()

	s := &originTestServer{fallback: fallback}
	s.server = httptest.NewServer(http.HandlerFunc(s.handle))
	t.Cleanup(s.server.Close)
	return s
}

func (s *originTestServer) handle(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	var request FileStreamRequestJSON
	_ = json.Unmarshal(body, &request)

	s.mu.Lock()
	next := s.fallback
	if len(s.script) > 0 {
		next, s.script = s.script[0], s.script[1:]
	}
	s.served = append(s.served, next.status)
	if next.status/100 == 2 {
		for _, line := range request.Files[HistoryFileName].Content {
			var row struct {
				Step int64 `json:"_step"`
			}
			_ = json.Unmarshal([]byte(line), &row)
			s.steps = append(s.steps, row.Step)
		}
	}
	s.mu.Unlock()

	if next.marked {
		w.Header().Set(api.ServerHeader, api.ServerHeaderValue)
	}
	w.WriteHeader(next.status)
	if next.status/100 == 2 {
		_, _ = w.Write([]byte("{}"))
	}
}

// then appends responses to the script.
func (s *originTestServer) then(responses ...scriptedResponse) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.script = append(s.script, responses...)
}

// count returns how many responses with the status were served.
func (s *originTestServer) count(status int) int {
	s.mu.Lock()
	defer s.mu.Unlock()

	n := 0
	for _, served := range s.served {
		if served == status {
			n++
		}
	}
	return n
}

func (s *originTestServer) acceptedSteps() []int64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]int64(nil), s.steps...)
}

type originTestOptions struct {
	// featureOn is whether the server lists RESPONSE_ORIGIN_HEADER as on.
	featureOn bool

	// deadline is the unmarked-404 deadline.
	deadline time.Duration

	// retryWait is the wait between retries.
	retryWait time.Duration
}

// startOriginTestFileStream starts a filestream that talks to the server
// through the same retry policy as real runs.
func startOriginTestFileStream(
	t *testing.T,
	ctx context.Context,
	s *originTestServer,
	opts originTestOptions,
) (*fileStream, *observability.Printer) {
	t.Helper()

	baseURL, err := url.Parse(s.server.URL)
	require.NoError(t, err)

	client := api.NewClient(api.ClientOptions{
		RetryPolicy:     RetryPolicy,
		RetryMax:        10000,
		RetryWaitMin:    opts.retryWait,
		RetryWaitMax:    opts.retryWait,
		NonRetryTimeout: 10 * time.Second,
	})

	features := map[spb.ServerFeature]bool{}
	if opts.featureOn {
		features[spb.ServerFeature_RESPONSE_ORIGIN_HEADER] = true
	}

	printer := observability.NewPrinter(10)
	factory := &FileStreamFactory{
		BaseURL:         baseURL,
		FeatureProvider: featurechecker.NewPreloaded(features),
		Logger:          observabilitytest.NewTestLogger(t),
		Printer:         printer,
		Settings:        settings.From(&spb.Settings{}),
	}

	fs := factory.New(
		client,
		ctx,
		time.Hour, // no heartbeats during the test
		rate.NewLimiter(rate.Inf, 1),
	).(*fileStream)
	fs.unmarked404RetryDeadline = opts.deadline
	fs.Start("entity", "project", "run", nil)

	return fs, printer
}

func logStep(fs *fileStream, step int64) {
	row := runhistory.New()
	row.SetInt(pathtree.PathOf("_step"), step)
	fs.StreamUpdate(&HistoryUpdate{Row: row})
}

// startWithMarkedSuccess starts a filestream and waits until its first
// request succeeds, so that it has seen the server's header.
func startWithMarkedSuccess(
	t *testing.T,
	ctx context.Context,
	s *originTestServer,
	opts originTestOptions,
) (*fileStream, *observability.Printer) {
	t.Helper()

	s.then(markedOK)
	fs, printer := startOriginTestFileStream(t, ctx, s, opts)
	logStep(fs, 0)
	require.Eventually(t,
		func() bool { return len(s.acceptedSteps()) == 1 },
		5*time.Second, time.Millisecond)

	return fs, printer
}

func defaultOriginOptions() originTestOptions {
	return originTestOptions{
		featureOn: true,
		deadline:  time.Hour,
		retryWait: time.Millisecond,
	}
}

func requireDead(t *testing.T, fs *fileStream) {
	t.Helper()
	require.Eventually(t, fs.isDead, 5*time.Second, time.Millisecond)
}

// Acceptance test 1: header-less 404s, then a success: uploads resume and
// every history row arrives.
func TestResponseOrigin_UnmarkedNotFoundThenSuccess_Resumes(t *testing.T) {
	s := newOriginTestServer(t, markedOK)
	fs, _ := startWithMarkedSuccess(t, t.Context(), s, defaultOriginOptions())

	s.then(unmarkedNotFound, unmarkedNotFound, unmarkedNotFound)
	for step := int64(1); step < 10; step++ {
		logStep(fs, step)
	}
	fs.FinishWithoutExit()

	assert.False(t, fs.isDead())
	assert.Equal(t, 3, s.count(http.StatusNotFound))
	assert.ElementsMatch(t,
		[]int64{0, 1, 2, 3, 4, 5, 6, 7, 8, 9},
		s.acceptedSteps())
}

// Acceptance test 2: a marked 404 stops uploads at once.
func TestResponseOrigin_MarkedNotFound_StopsAtOnce(t *testing.T) {
	s := newOriginTestServer(t, markedOK)
	fs, printer := startWithMarkedSuccess(t, t.Context(), s, defaultOriginOptions())

	s.then(markedNotFound)
	logStep(fs, 1)
	requireDead(t, fs)
	fs.FinishWithoutExit()

	assert.Equal(t, 1, s.count(http.StatusNotFound))
	assert.Equal(t, []int64{0}, s.acceptedSteps())
	assertFatalErrorPrinted(t, printer)
}

// Acceptance test 3: header-less 404s past the deadline: retries stop and the
// SDK reports the failure. Unsent data stays in the run's .wandb file, which
// the filestream never deletes.
func TestResponseOrigin_UnmarkedNotFoundPastDeadline_Stops(t *testing.T) {
	s := newOriginTestServer(t, unmarkedNotFound)
	opts := defaultOriginOptions()
	opts.deadline = 100 * time.Millisecond
	fs, printer := startWithMarkedSuccess(t, t.Context(), s, opts)

	start := time.Now()
	logStep(fs, 1)
	requireDead(t, fs)
	fs.FinishWithoutExit()

	assert.GreaterOrEqual(t, time.Since(start), opts.deadline)
	assert.Greater(t, s.count(http.StatusNotFound), 1)
	assert.Equal(t, []int64{0}, s.acceptedSteps())
	assertFatalErrorPrinted(t, printer)
}

// Acceptance test 4: shutdown or cancellation during the retry wait ends it.
func TestResponseOrigin_CancelDuringRetryWait_EndsWait(t *testing.T) {
	s := newOriginTestServer(t, unmarkedNotFound)
	ctx, cancel := context.WithCancel(t.Context())
	opts := defaultOriginOptions()
	opts.retryWait = time.Hour // the only way out is cancellation
	fs, _ := startWithMarkedSuccess(t, ctx, s, opts)

	logStep(fs, 1)
	require.Eventually(t,
		func() bool { return s.count(http.StatusNotFound) == 1 },
		5*time.Second, time.Millisecond)
	cancel()

	finished := make(chan struct{})
	go func() {
		fs.FinishWithoutExit()
		close(finished)
	}()
	select {
	case <-finished:
	case <-time.After(5 * time.Second):
		t.Fatal("filestream did not stop after cancellation")
	}
	assert.Equal(t, 1, s.count(http.StatusNotFound))
}

// Acceptance test 5: mixed releases (marked success, header-less 404, marked
// 404): retries stop at the marked 404.
func TestResponseOrigin_MixedReleases_StopAtMarkedNotFound(t *testing.T) {
	s := newOriginTestServer(t, markedOK)
	fs, _ := startWithMarkedSuccess(t, t.Context(), s, defaultOriginOptions())

	s.then(unmarkedNotFound, unmarkedNotFound, markedNotFound)
	logStep(fs, 1)
	requireDead(t, fs)
	fs.FinishWithoutExit()

	assert.Equal(t, 3, s.count(http.StatusNotFound))
	assert.Equal(t, []int64{0}, s.acceptedSteps())
}

// Acceptance test 6: a proxy strips the header everywhere: today's behavior.
func TestResponseOrigin_HeaderStripped_StopsOnNotFound(t *testing.T) {
	s := newOriginTestServer(t, unmarkedOK)
	s.then(unmarkedOK)
	fs, _ := startOriginTestFileStream(t, t.Context(), s, defaultOriginOptions())
	logStep(fs, 0)
	require.Eventually(t,
		func() bool { return len(s.acceptedSteps()) == 1 },
		5*time.Second, time.Millisecond)

	s.then(unmarkedNotFound)
	logStep(fs, 1)
	requireDead(t, fs)
	fs.FinishWithoutExit()

	assert.Equal(t, 1, s.count(http.StatusNotFound))
}

// Acceptance test 7: an old server without the feature: today's behavior.
func TestResponseOrigin_FeatureOff_StopsOnNotFound(t *testing.T) {
	s := newOriginTestServer(t, markedOK)
	opts := defaultOriginOptions()
	opts.featureOn = false
	fs, _ := startWithMarkedSuccess(t, t.Context(), s, opts)

	s.then(unmarkedNotFound)
	logStep(fs, 1)
	requireDead(t, fs)
	fs.FinishWithoutExit()

	assert.Equal(t, 1, s.count(http.StatusNotFound))
}

// A run whose first request gets a header-less 404 has never seen the header,
// so it stops as before.
func TestResponseOrigin_NoSuccessYet_StopsOnNotFound(t *testing.T) {
	s := newOriginTestServer(t, unmarkedNotFound)
	fs, _ := startOriginTestFileStream(t, t.Context(), s, defaultOriginOptions())

	logStep(fs, 0)
	requireDead(t, fs)
	fs.FinishWithoutExit()

	assert.Equal(t, 1, s.count(http.StatusNotFound))
}

// Acceptance test 8 (end to end): 5xx retries are unchanged with the rule on.
func TestResponseOrigin_ServerErrorsStillRetried(t *testing.T) {
	s := newOriginTestServer(t, markedOK)
	fs, _ := startWithMarkedSuccess(t, t.Context(), s, defaultOriginOptions())

	s.then(
		scriptedResponse{http.StatusServiceUnavailable, false},
		scriptedResponse{http.StatusBadGateway, true},
		scriptedResponse{http.StatusTooManyRequests, true},
	)
	logStep(fs, 1)
	fs.FinishWithoutExit()

	assert.False(t, fs.isDead())
	assert.ElementsMatch(t, []int64{0, 1}, s.acceptedSteps())
}

func assertFatalErrorPrinted(t *testing.T, printer *observability.Printer) {
	t.Helper()

	var contents []string
	for _, msg := range printer.Read() {
		contents = append(contents, msg.Content)
	}
	assert.Contains(t,
		strings.Join(contents, "\n"),
		"Fatal error while uploading data")
}
