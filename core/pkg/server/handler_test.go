package server_test

import (
	"context"

	"github.com/wandb/wandb/core/pkg/observability"
	server "github.com/wandb/wandb/core/pkg/server"
	"github.com/wandb/wandb/core/pkg/service"
)

func makeHandler(
	inChan, fwdChan chan *service.Record,
	outChan chan *service.Result,
) *server.Handler {
	h := server.NewHandler(
		context.Background(),
		&server.HandlerParams{
			Logger:     observability.NewNoOpLogger(),
			Settings:   &service.Settings{},
			FwdChannel: fwdChan,
			OutChannel: outChan,
		},
	)

	go h.Do(inChan)

	return h
}
