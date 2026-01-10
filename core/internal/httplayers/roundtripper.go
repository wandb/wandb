package httplayers

import "net/http"

// WrapRoundTripper applies an HTTPWrapper to a RoundTripper.
//
// This is not technically correct: the RoundTripper contract specifies that
// it doesn't inspect responses but HTTPWrappers are allowed to do so, among
// other things.
//
// This exists because the only way to inject functionality into the
// retryablehttp.Client is to modify its Transport.
func WrapRoundTripper(
	rt http.RoundTripper,
	wrapper HTTPWrapper,
) http.RoundTripper {
	return wrappedRoundTripper{wrapper.WrapHTTP(rt.RoundTrip)}
}

type wrappedRoundTripper struct {
	fn HTTPDoFunc
}

// RoundTrip implements http.RoundTripper.RoundTrip.
func (rt wrappedRoundTripper) RoundTrip(
	req *http.Request,
) (*http.Response, error) {
	return rt.fn(req)
}
