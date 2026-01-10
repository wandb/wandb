package httplayers

import (
	"net/http"
	"net/url"
)

// URLError wraps an error in a *url.Error for a request.
//
// Neither the request nor the error may be nil.
//
// If the given error is already a *url.Error, it is returned.
// Otherwise, the request's method and URL are used for the returned Op and URL.
func URLError(req *http.Request, err error) *url.Error {
	if urlErr, ok := err.(*url.Error); ok {
		return urlErr
	}

	return &url.Error{
		Op:  req.Method,
		URL: req.URL.String(),
		Err: err,
	}
}
