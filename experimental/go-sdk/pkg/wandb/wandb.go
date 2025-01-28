// package wandb implements the go Weights & Biases SDK
package wandb

import (
	"github.com/wandb/wandb/experimental/go-sdk/pkg/runconfig"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/settings"
	wbSettings "github.com/wandb/wandb/experimental/go-sdk/pkg/settings"
)

type RunParams struct {
	Config   *runconfig.Config
	Settings *settings.Settings
}

type History = map[string]any

var session *Session

func Setup(params *SessionParams) (*Session, error) {
	if session != nil {
		return session, nil
	}

	sessSettings, err := wbSettings.New()
	if err != nil {
		return nil, err
	}
	sessSettings.FromEnv()
	sessSettings.FromSettings(params.Settings)

	session = newSession(
		&SessionParams{
			Settings: sessSettings,
		},
	)
	session.start()
	return session, nil
}

func Init(params *RunParams) (*Run, error) {
	if params == nil {
		params = &RunParams{}
	}
	session, err := Setup(&SessionParams{Settings: params.Settings})
	if err != nil {
		return nil, err
	}
	return session.Init(params)
}

func Teardown() {
	if session != nil {
		session.Close()
	}
}
