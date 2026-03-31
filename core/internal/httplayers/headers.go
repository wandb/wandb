package httplayers

import "net/http"

// ExtraHeaders adds default headers to every request.
//
// Headers already present on the request are preserved.
func ExtraHeaders(headers http.Header) HTTPWrapper {
	return extraHeaders{headers}
}

type extraHeaders struct {
	headers http.Header
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (h extraHeaders) WrapHTTP(send HTTPDoFunc) HTTPDoFunc {
	if len(h.headers) == 0 {
		return send
	}

	return func(req *http.Request) (*http.Response, error) {
		if req.Header == nil {
			req.Header = make(http.Header)
		}
		for key, values := range h.headers {
			// Preserve request-specific headers over extra headers from user settings.
			if req.Header.Values(key) != nil {
				continue
			}

			for _, value := range values {
				req.Header.Add(key, value)
			}
		}

		return send(req)
	}
}
