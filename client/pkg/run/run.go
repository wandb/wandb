package run

import (
	"github.com/wandb/wandb/client/internal/connection"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunParams struct {
	Conn     *connection.Connection
	Settings *service.Settings
}

type Run struct {
	conn     *connection.Connection
	settings *service.Settings
}

func New(params *RunParams) *Run {
	return &Run{
		conn:     params.Conn,
		settings: params.Settings,
	}
}

func (r *Run) Init() error {
	return nil
}
