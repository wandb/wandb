package clients

import (
	"bufio"
	"bytes"
	"log/slog"
	"math"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

const (
	badPath  = "/bad/"
	goodPath = "/good/"
)

func TestClientResponseLogger(t *testing.T) {
	var buf bytes.Buffer
	bufWriter := bufio.NewWriter(&buf)
	slogger := slog.New(slog.NewTextHandler(bufWriter, nil))

	mux := http.NewServeMux()
	mux.HandleFunc(badPath, func(res http.ResponseWriter, req *http.Request) {
		res.WriteHeader(500)
		_, _ = res.Write([]byte("test_500_body"))
	})
	mux.HandleFunc(goodPath, func(res http.ResponseWriter, req *http.Request) {
		res.WriteHeader(200)
		_, _ = res.Write([]byte("happy"))
	})

	ts := httptest.NewServer(mux)
	defer ts.Close()

	client := NewRetryClient(
		WithRetryClientRetryMax(0),
		WithRetryClientResponseLogger(slogger, func(resp *http.Response) bool {
			return resp.StatusCode >= 400
		}),
	)
	client.Logger = slogger

	_, badErr := client.Get(ts.URL + badPath)
	assert.NotNil(t, badErr)
	_, goodErr := client.Get(ts.URL + goodPath)
	assert.Nil(t, goodErr)

	bufWriter.Flush()
	logBuffer := buf.String()
	assert.Contains(t, logBuffer, "test_500_body")
	assert.NotContains(t, logBuffer, "happy")
}

func TestExponentialBackoffWithJitter_NonHTTP429(t *testing.T) {
	min := 1 * time.Second
	max := 10 * time.Second
	attemptNum := 3

	backoff := ExponentialBackoffWithJitter(min, max, attemptNum, nil)

	// The expected range is between 2^3 * min and max.
	expectedMin := time.Duration(math.Pow(2, float64(attemptNum))) * min
	if expectedMin > max {
		expectedMin = max
	}

	assert.GreaterOrEqual(t, backoff, expectedMin, "Backoff should be greater than or equal to min")
	assert.LessOrEqual(t, backoff, max, "Backoff should be less than or equal to calculated max")
}

func TestExponentialBackoffWithJitter_HTTP429(t *testing.T) {
	min := 1 * time.Second
	max := 10 * time.Second
	retryAfter := 5 // seconds
	attemptNum := 1

	resp := &http.Response{
		StatusCode: http.StatusTooManyRequests,
		Header:     make(http.Header),
	}
	resp.Header.Set("Retry-After", strconv.Itoa(retryAfter))

	backoff := ExponentialBackoffWithJitter(min, max, attemptNum, resp)

	// The expected range is between retryAfter and retryAfter + jitter.
	expectedMin := time.Duration(retryAfter) * time.Second
	expectedMax := expectedMin + time.Duration(0.25*float64(expectedMin))

	assert.GreaterOrEqual(t, backoff, expectedMin, "Backoff should be greater than or equal to Retry-After")
	assert.LessOrEqual(t, backoff, expectedMax, "Backoff should be less than or equal to Retry-After plus jitter")
}

func TestExponentialBackoffWithJitter_MaxBackoffLimit(t *testing.T) {
	min := 1 * time.Second
	max := 10 * time.Second
	attemptNum := 10 // High enough to exceed max

	backoff := ExponentialBackoffWithJitter(min, max, attemptNum, nil)

	assert.LessOrEqual(t, backoff, max, "Backoff should not exceed max limit")
}
