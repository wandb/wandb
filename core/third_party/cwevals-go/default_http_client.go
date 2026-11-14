// File generated from our OpenAPI spec by Stainless.

package cwevals

import (
	"net/http"
	"time"
)

// defaultResponseHeaderTimeout bounds the time between a fully written request
// and the server's response headers. It does not apply to the response body,
// so long-running streams are unaffected. Without this, a server that accepts
// the connection but never responds would hang the request indefinitely.
const defaultResponseHeaderTimeout = 10 * time.Minute

// defaultHTTPClient returns an [*http.Client] used when the caller does not
// supply one via [option.WithHTTPClient]. When [http.DefaultTransport] is the
// stdlib [*http.Transport], it is cloned and a [http.Transport.ResponseHeaderTimeout]
// is set so stuck connections fail fast instead of compounding across retries.
// If [http.DefaultTransport] has been wrapped (for example by otelhttp for
// distributed tracing), the wrapping is preserved and the header timeout is
// skipped.
func defaultHTTPClient() *http.Client {
	if t, ok := http.DefaultTransport.(*http.Transport); ok {
		t = t.Clone()
		t.ResponseHeaderTimeout = defaultResponseHeaderTimeout
		return &http.Client{Transport: t}
	}
	return &http.Client{Transport: http.DefaultTransport}
}
