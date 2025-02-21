package runwork

import (
	"fmt"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// workSentinel is a Work item used for synchronization.
type workSentinel struct{ value any }

// NewSentinel returns a Work item holding the given sentinel value.
//
// The work item's methods are all no-ops, except that Sentinel() returns
// the given value.
func NewSentinel(value any) Work {
	return &workSentinel{value}
}

func (s *workSentinel) Accept(func(*spb.Record)) bool { return true }

func (s *workSentinel) Save(func(*spb.Record)) {}

func (s *workSentinel) BypassOfflineMode() bool { return true }

func (s *workSentinel) Process(func(*spb.Record)) {}

func (s *workSentinel) Sentinel() any { return s.value }

func (s *workSentinel) DebugInfo() string {
	return fmt.Sprintf("WorkSentinel(%v)", s.value)
}
