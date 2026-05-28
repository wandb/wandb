package clients

import (
	"net/http"
	"net/url"
)

// ProxyFn returns an http.Transport.Proxy function that routes requests
// through httpProxy or httpsProxy based on the request scheme, falling back
// to http.ProxyFromEnvironment when no custom proxy is configured.
//
// This lets callers proxy only W&B traffic; HTTP_PROXY/HTTPS_PROXY/NO_PROXY
// would otherwise route all traffic through the proxy.
func ProxyFn(httpProxy, httpsProxy string) func(req *http.Request) (*url.URL, error) {
	return func(req *http.Request) (*url.URL, error) {
		switch {
		case req.URL.Scheme == "http" && httpProxy != "":
			return url.Parse(httpProxy)
		case req.URL.Scheme == "https" && httpsProxy != "":
			return url.Parse(httpsProxy)
		default:
			return http.ProxyFromEnvironment(req)
		}
	}
}
