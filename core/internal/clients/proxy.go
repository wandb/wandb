package clients

import (
	"net/http"
	"net/url"
)

// ProxyFn returns a function that returns a proxy URL for a given http.Request.
//
// The function first checks if there's a custom proxy setting for the request
// URL scheme. If not, it falls back to the default environment proxy settings.
// If there is, it returns the custom proxy URL.
//
// This is useful if the user only want to proxy traffic to W&B, but not other traffic,
// as the standard environment proxy settings would potentially proxy all traffic.
//
// The custom proxy URLs are passed as arguments to the function.
//
// The default environment proxy settings are read from the environment variables
// HTTP_PROXY, HTTPS_PROXY, and NO_PROXY.
func ProxyFn(httpProxy, httpsProxy string) func(req *http.Request) (*url.URL, error) {
	return func(req *http.Request) (*url.URL, error) {
		if req.URL.Scheme == "http" && httpProxy != "" {
			proxyURLParsed, err := url.Parse(httpProxy)
			if err != nil {
				return nil, err
			}
			return proxyURLParsed, nil
		} else if req.URL.Scheme == "https" && httpsProxy != "" {
			proxyURLParsed, err := url.Parse(httpsProxy)
			if err != nil {
				return nil, err
			}
			return proxyURLParsed, nil
		}

		// Fall back to the default environment proxy settings
		return http.ProxyFromEnvironment(req)
	}
}
