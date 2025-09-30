package work

import (
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type ApiWork interface {
	Process() *spb.ApiResponse
}
type NoopWork struct {
	Record *spb.Record
}

var _ ApiWork = &NoopWork{}

func (w *NoopWork) Process() *spb.ApiResponse {
	return &spb.ApiResponse{}
}
