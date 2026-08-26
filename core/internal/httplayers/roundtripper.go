package httplayers

import (
	"net/http"
	"net/url"
)

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
	resp, err := rt.fn(req)

	// Unwrap url.Error, since http.Client.Do() will wrap this in a url.Error.
	//
	// HTTPDoFunc is meant to act like http.Client.Do(), so it's documented
	// to return url.Error, but we're using it as a RoundTripper here, which
	// isn't expected to return url.Error. Without unwrapping, errors look like:
	//
	// 	Post "https://api.wandb.ai/graphql": POST "https://api.wandb.ai/graphql": ...
	if urlErr, ok := err.(*url.Error); ok {
		err = urlErr.Err
	}

	return resp, err
}
