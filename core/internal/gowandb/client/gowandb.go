// package gowandb implements the go Weights & Biases SDK
package gowandb

import "github.com/wandb/wandb/core/internal/gowandb/client/opts/sessionopts"

type History map[string]interface{}

func NewSession(opts ...sessionopts.SessionOption) (*Session, error) {
	session := &Session{}
	for _, opt := range opts {
		opt(&session.SessionParams)
	}
	session.start()
	return session, nil
}
