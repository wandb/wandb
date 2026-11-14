// File generated from our OpenAPI spec by Stainless.

package option

import (
	"log"
	"net/http"
	"net/http/httputil"
)

// sensitiveLogHeaders are redacted before request and response content is
// written to the debug logger.
var sensitiveLogHeaders = []string{"authorization", "api-key", "x-api-key", "cookie", "set-cookie"}

// WithDebugLog logs the HTTP request and response content.
// If the logger parameter is nil, it uses the default logger.
//
// WithDebugLog is for debugging and development purposes only.
// It should not be used in production code. The behavior and interface
// of WithDebugLog is not guaranteed to be stable.
func WithDebugLog(logger *log.Logger) RequestOption {
	return WithMiddleware(func(req *http.Request, nxt MiddlewareNext) (*http.Response, error) {
		if logger == nil {
			logger = log.Default()
		}

		if reqBytes, err := dumpRedactedRequest(req); err == nil {
			logger.Printf("Request Content:\n%s\n", reqBytes)
		}

		resp, err := nxt(req)
		if err != nil {
			return resp, err
		}

		if respBytes, err := dumpRedactedResponse(resp); err == nil {
			logger.Printf("Response Content:\n%s\n", respBytes)
		}

		return resp, err
	})
}

// dumpRedactedRequest dumps req with sensitive headers replaced. The
// original headers are restored via defer so a panic in DumpRequest cannot
// leak the placeholder map into the live request sent downstream.
func dumpRedactedRequest(req *http.Request) ([]byte, error) {
	origHeaders := req.Header
	req.Header = redactDebugHeaders(origHeaders)
	defer func() { req.Header = origHeaders }()
	return httputil.DumpRequest(req, true)
}

func dumpRedactedResponse(resp *http.Response) ([]byte, error) {
	origHeaders := resp.Header
	resp.Header = redactDebugHeaders(origHeaders)
	defer func() { resp.Header = origHeaders }()
	return httputil.DumpResponse(resp, true)
}

func redactDebugHeaders(headers http.Header) http.Header {
	var redacted http.Header
	for _, name := range sensitiveLogHeaders {
		values := headers.Values(name)
		if len(values) == 0 {
			continue
		}
		if redacted == nil {
			redacted = headers.Clone()
		}
		redacted.Del(name)
		for range values {
			redacted.Add(name, "***")
		}
	}
	if redacted == nil {
		return headers
	}
	return redacted
}
