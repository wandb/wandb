//go:build cloud_http

package filetransfer

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

type cloudHTTPDoerFunc func(*http.Request) (*http.Response, error)

func (f cloudHTTPDoerFunc) Do(req *http.Request) (*http.Response, error) { return f(req) }

type cloudTrackedBody struct {
	io.Reader
	closed bool
}

func (b *cloudTrackedBody) Close() error { b.closed = true; return nil }

func TestCloudHTTPReplayAndAuthorize(t *testing.T) {
	req, err := http.NewRequest(
		http.MethodPut,
		"https://storage.example/object",
		strings.NewReader("payload"),
	)
	if err != nil {
		t.Fatal(err)
	}
	var attempts, signatures int
	failedBody := &cloudTrackedBody{Reader: strings.NewReader("busy")}
	client := &cloudHTTPClient{
		authorize: func(r *http.Request) error {
			signatures++
			r.Header.Set("Authorization", fmt.Sprint(signatures))
			return nil
		},
		retryDelay: func(int, *http.Response) time.Duration { return 0 },
		client: cloudHTTPDoerFunc(func(r *http.Request) (*http.Response, error) {
			attempts++
			body, err := io.ReadAll(r.Body)
			_ = r.Body.Close()
			if err != nil || string(body) != "payload" ||
				r.Header.Get("Authorization") != fmt.Sprint(attempts) {
				t.Fatalf("attempt %d: body=%q err=%v headers=%v", attempts, body, err, r.Header)
			}
			if attempts == 1 {
				return &http.Response{StatusCode: 503, Body: failedBody}, nil
			}
			return &http.Response{StatusCode: 200, Body: http.NoBody}, nil
		}),
	}
	resp, err := client.Do(req)
	if err != nil || resp.StatusCode != 200 || attempts != 2 || !failedBody.closed {
		t.Fatalf("resp=%v err=%v attempts=%d closed=%v", resp, err, attempts, failedBody.closed)
	}
	if req.Header.Get("Authorization") != "" {
		t.Fatal("authorization mutated the original request")
	}
}

func TestCloudHTTPDoesNotReplayStreamingBody(t *testing.T) {
	body := &cloudTrackedBody{Reader: strings.NewReader("stream")}
	req, _ := http.NewRequest(http.MethodPut, "https://storage.example/object", body)
	attempts := 0
	client := &cloudHTTPClient{
		client: cloudHTTPDoerFunc(func(r *http.Request) (*http.Response, error) {
			attempts++
			_, _ = io.Copy(io.Discard, r.Body)
			_ = r.Body.Close()
			return &http.Response{StatusCode: 503, Body: http.NoBody}, nil
		}),
	}
	resp, err := client.Do(req)
	if err != nil || resp.StatusCode != 503 || attempts != 1 || !body.closed {
		t.Fatalf("resp=%v err=%v attempts=%d closed=%v", resp, err, attempts, body.closed)
	}
}

func TestCloudHTTPCancellationDuringBackoff(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	req, _ := http.NewRequestWithContext(
		ctx,
		http.MethodGet,
		"https://storage.example/object",
		http.NoBody,
	)
	body := &cloudTrackedBody{Reader: strings.NewReader("busy")}
	client := &cloudHTTPClient{
		client: cloudHTTPDoerFunc(func(*http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 503, Body: body}, nil
		}),
		retryDelay: func(int, *http.Response) time.Duration {
			cancel()
			return time.Hour
		},
	}
	_, err := client.Do(req)
	if !errors.Is(err, context.Canceled) || !body.closed {
		t.Fatalf("err=%v closed=%v", err, body.closed)
	}
}

func TestCloudHTTPPermanentStatusAndAttemptLimit(t *testing.T) {
	for _, tc := range []struct{ status, attempts int }{{403, 1}, {429, 3}, {408, 3}, {503, 3}} {
		t.Run(fmt.Sprint(tc.status), func(t *testing.T) {
			attempts := 0
			client := &cloudHTTPClient{
				maxAttempts: 3,
				retryDelay:  func(int, *http.Response) time.Duration { return 0 },
				client: cloudHTTPDoerFunc(func(*http.Request) (*http.Response, error) {
					attempts++
					return &http.Response{StatusCode: tc.status, Body: http.NoBody}, nil
				}),
			}
			req, _ := http.NewRequest(http.MethodGet, "https://storage.example/object", http.NoBody)
			resp, err := client.Do(req)
			if err != nil || resp.StatusCode != tc.status || attempts != tc.attempts {
				t.Fatalf("resp=%v err=%v attempts=%d", resp, err, attempts)
			}
		})
	}
}
