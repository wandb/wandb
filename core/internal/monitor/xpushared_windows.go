package monitor

import (
	"context"
	"errors"
)

func (m *XPUResourceManager) startSharedCollector(context.Context) error {
	return errors.New("a shared wandb-xpu is not supported on windows")
}
