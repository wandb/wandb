package httplayers

import "net/http"

// DefaultHeaders sets headers not present on a request to default values.
func DefaultHeaders(headers http.Header) HTTPWrapper {
	return defaultHeaders{headers}
}

type defaultHeaders struct {
	headers http.Header
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (h defaultHeaders) WrapHTTP(send HTTPDoFunc) HTTPDoFunc {
	if len(h.headers) == 0 {
		return send
	}

	return func(req *http.Request) (*http.Response, error) {
		if req.Header == nil {
			req.Header = make(http.Header)
		}

		for key, values := range h.headers {
			if _, isSet := req.Header[key]; !isSet {
				req.Header[key] = values
			}
		}

		return send(req)
	}
}
