package api

import "net/http"

type HTTPDoFunc = func(req *http.Request) (*http.Response, error)

// HTTPWrapper modifies an HTTP client's behavior.
type HTTPWrapper interface {
	// WrapHTTP wraps the given 'send' function to perform an HTTP request.
	WrapHTTP(send HTTPDoFunc) HTTPDoFunc
}

// WrapRoundTripper applies a list of HTTPWrappers to a RoundTripper.
//
// This is not technically correct: the RoundTripper contract specifies that
// it doesn't inspect responses but HTTPWrappers are allowed to do so, among
// other things.
//
// This exists because the only way to inject functionality into the
// retryablehttp.Client is to modify its Transport.
//
// The layers are specified inside-to-outside, so that
//
//	WrapRoundTripper(baseRT, Wrapper1, Wrapper2).RoundTrip
//
// is equal to
//
//	Wrapper2.WrapHTTP(Wrapper1.WrapHTTP(baseRT.RoundTrip))
func WrapRoundTripper(
	rt http.RoundTripper,
	wrappers ...HTTPWrapper,
) http.RoundTripper {
	doFunc := rt.RoundTrip

	for _, wrapper := range wrappers {
		doFunc = wrapper.WrapHTTP(doFunc)
	}

	return &wrappedRoundTripper{doFunc}
}

type wrappedRoundTripper struct {
	fn HTTPDoFunc
}

func (rt *wrappedRoundTripper) RoundTrip(
	req *http.Request,
) (*http.Response, error) {
	return rt.fn(req)
}
