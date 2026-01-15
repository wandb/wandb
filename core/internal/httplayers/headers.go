package httplayers

import (
	"maps"
	"net/http"
)

// ExtraHeaders copies the given headers to every request.
func ExtraHeaders(headers http.Header) HTTPWrapper {
	return extraHeaders{headers}
}

type extraHeaders struct {
	headers http.Header
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (h extraHeaders) WrapHTTP(send HTTPDoFunc) HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		maps.Copy(req.Header, h.headers)
		return send(req)
	}
}
