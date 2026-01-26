package httplayers

import (
	"net/http"
	"net/url"
	"strings"
)

// LimitTo returns a wrapper that only applies to requests for sub-URLs
// of a given URL.
//
// If the given URL is nil, returns the wrapper.
//
// Requests must have the exact same scheme, hostname and port as the given
// URL. Request paths must be prefixed with the given URL's path.
func LimitTo(u *url.URL, wrapper HTTPWrapper) HTTPWrapper {
	if u == nil {
		return wrapper
	}

	return urlFilteredWrapper{u, wrapper}
}

type urlFilteredWrapper struct {
	url     *url.URL
	wrapper HTTPWrapper
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (w urlFilteredWrapper) WrapHTTP(send HTTPDoFunc) HTTPDoFunc {
	wrappedSend := w.wrapper.WrapHTTP(send)

	return func(req *http.Request) (*http.Response, error) {
		if req.URL.Scheme != w.url.Scheme ||
			req.URL.Host != w.url.Host ||
			!strings.HasPrefix(req.URL.Path, w.url.Path) {

			return send(req)
		}

		return wrappedSend(req)
	}
}
