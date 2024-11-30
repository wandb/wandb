// package gowandb implements the go Weights & Biases SDK
package gowandb

import (
	"context"

	"github.com/wandb/wandb/experimental/client-go/pkg/settings"
)

type History map[string]interface{}

func NewSession(params SessionParams) (*Session, error) {
	if params.Settings == nil {
		params.Settings = settings.NewSettings()
	}
	session := &Session{
		ctx:        context.Background(),
		coreBinary: params.CoreBinary,
		address:    params.Address,
		settings:   params.Settings,
	}
	session.start()
	return session, nil
}
