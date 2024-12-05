// package gowandb implements the go Weights & Biases SDK
package gowandb

import (
	"context"

	"github.com/wandb/wandb/experimental/client-go/pkg/settings"
)

type History map[string]interface{}

func NewSession(params SessionParams) (*Session, error) {
	sessSettings, err := settings.New()
	if err != nil {
		return nil, err
	}
	sessSettings.FromEnv()
	if params.Settings != nil {
		sessSettings.FromSettings(params.Settings)
	}
	session := &Session{
		ctx:        context.Background(),
		coreBinary: params.CoreBinary,
		address:    params.Address,
		settings:   sessSettings,
	}
	session.start()
	return session, nil
}
