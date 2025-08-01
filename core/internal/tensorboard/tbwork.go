package tensorboard

import (
	"fmt"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TBWork makes the TensorBoard integration watch a TB logging directory.
type TBWork struct {
	runwork.AlwaysAcceptMixin
	runwork.NoopProcessMixin

	Record *spb.Record

	Logger    *observability.CoreLogger
	TBHandler *TBHandler
}

// Schedule implements Work.Schedule.
//
// TensorBoard is special: we handle its records at Schedule time rather than
// at Accept (in the Handler) or Process (in the Sender). This is because of
// its interaction with the Exit record, which calls TBHandler.Finish()
// during Schedule.
//
// The right way to think about the TensorBoard integration is to pretend it
// exists entirely in the client: the Schedule step can be viewed as something
// that happens in the client itself.
func (w *TBWork) Schedule(wg *sync.WaitGroup, proceed func()) {
	err := w.TBHandler.Handle(w.Record.GetTbrecord())
	if err != nil {
		w.Logger.CaptureError(err)
	}
	proceed()
}

// ToRecord implements Work.ToRecord.
func (w *TBWork) ToRecord() *spb.Record { return w.Record }

// DebugInfo implements Work.DebugInfo
func (w *TBWork) DebugInfo() string {
	return fmt.Sprintf(
		"TBWork(log_dir=%q, root_dir=%q, save=%t)",
		w.Record.GetTbrecord().GetLogDir(),
		w.Record.GetTbrecord().GetRootDir(),
		w.Record.GetTbrecord().GetSave(),
	)
}
