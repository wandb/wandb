package api

import (
	"net/http"
)

// NetworkPeeker allows a function to inspect requests and responses.
func NetworkPeeker(peeker Peeker) HTTPWrapper {
	return networkPeeker{peeker}
}

type Peeker interface {
	Peek(*http.Request, *http.Response)
}

type networkPeeker struct {
	peeker Peeker
}

func (p networkPeeker) WrapHTTP(send HTTPDoFunc) HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		resp, err := send(req)

		if p.peeker != nil {
			p.peeker.Peek(req, resp)
		}

		return resp, err
	}
}
