package httplayers

import (
	"net/http"
	"net/url"
	"strings"
)

// PrefixPath returns a wrapper that moves requests for the given URL's
// scheme and host under its path, if they are not already there.
//
// If the given URL is nil, returns a no-op wrapper.
func PrefixPath(u *url.URL) HTTPWrapper {
	if u == nil {
		return Concat()
	}

	return pathPrefixWrapper{u}
}

type pathPrefixWrapper struct {
	url *url.URL
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (w pathPrefixWrapper) WrapHTTP(send HTTPDoFunc) HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		if req.URL.Scheme != w.url.Scheme ||
			req.URL.Host != w.url.Host ||
			strings.HasPrefix(req.URL.Path, w.url.Path) {

			return send(req)
		}

		u := w.url.JoinPath(req.URL.EscapedPath())
		u.RawQuery = req.URL.RawQuery

		req = req.Clone(req.Context())
		req.URL = u
		return send(req)
	}
}
