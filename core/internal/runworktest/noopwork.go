package runworktest

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// NoopWork is Work helpful for testing.
//
// It does nothing and is represented as an empty Record proto.
type NoopWork struct {
	runwork.SimpleScheduleMixin
	runwork.AlwaysAcceptMixin
	runwork.NoopProcessMixin

	Value string
}

func (w *NoopWork) ToRecord() *spb.Record { return &spb.Record{} }
func (w *NoopWork) DebugInfo() string {
	return fmt.Sprintf("NoopWork{Value: %q}", w.Value)
}
