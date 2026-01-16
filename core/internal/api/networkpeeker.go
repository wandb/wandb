package api

import (
	"net/http"

	"github.com/wandb/wandb/core/internal/httplayers"
)

// NetworkPeeker allows a function to inspect requests and responses.
func NetworkPeeker(peeker Peeker) httplayers.HTTPWrapper {
	return networkPeeker{peeker}
}

type Peeker interface {
	Peek(*http.Request, *http.Response)
}

type networkPeeker struct {
	peeker Peeker
}

// WrapHTTP implements HTTPWrapper.WrapHTTP.
func (p networkPeeker) WrapHTTP(send httplayers.HTTPDoFunc) httplayers.HTTPDoFunc {
	return func(req *http.Request) (*http.Response, error) {
		resp, err := send(req)

		if p.peeker != nil {
			p.peeker.Peek(req, resp)
		}

		return resp, err
	}
}
