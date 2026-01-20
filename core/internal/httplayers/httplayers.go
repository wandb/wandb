// Package httplayers defines abstractions for adding higher-level functionality
// to an HTTP client.
package httplayers

import "net/http"

// HTTPDoFunc is a wrapped http.Client.Do function.
//
// It sends a request and returns a response. The request body (if any) will
// be closed by the underlying Transport, possibly asynchronously after Do
// returns.
//
// Unlike http.Client.Do, this may process the response and return an error even
// if a response was received.
//
// Errors should be of type *url.Error.
type HTTPDoFunc = func(req *http.Request) (*http.Response, error)

// HTTPWrapper modifies an HTTP client's behavior.
type HTTPWrapper interface {
	// WrapHTTP wraps the given 'send' function to perform an HTTP request.
	WrapHTTP(send HTTPDoFunc) HTTPDoFunc
}

// Concat returns a wrapper that applies layers in order.
//
// The layers are specified inner-first, so that
//
//	Concat(wrapper1, wrapper2, wrapper3).WrapHTTP(send)
//
// is equal to
//
//	wrapper3.WrapHTTP(wrapper2.WrapHTTP(wrapper1.WrapHTTP(send)))
//
// Note how modifications done to a Request happen outside-to-inside,
// and response processing happens inside-to-outside:
//
//	Request -> wrapper3 -> wrapper2 -> wrapper1 -> send
//	Response -> send -> wrapper1 -> wrapper2 -> wrapper3
func Concat(wrappers ...HTTPWrapper) HTTPWrapper {
	return wrapperList{wrappers}
}

type wrapperList struct {
	wrappers []HTTPWrapper
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (l wrapperList) WrapHTTP(send HTTPDoFunc) HTTPDoFunc {
	for _, wrapper := range l.wrappers {
		send = wrapper.WrapHTTP(send)
	}

	return send
}
