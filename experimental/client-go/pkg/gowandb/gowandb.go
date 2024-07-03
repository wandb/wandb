// package gowandb implements the go Weights & Biases SDK
package gowandb

import (
	"github.com/wandb/wandb/experimental/client-go/pkg/opts/sessionopts"
)

type History map[string]interface{}

func NewSession(opts ...sessionopts.SessionOption) (*Session, error) {
	session := &Session{}
	for _, opt := range opts {
		opt(&session.SessionParams)
	}
	session.start()
	return session, nil
}
