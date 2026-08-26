package leet_test

import (
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

// drainCmds executes a command tree synchronously, feeding the resulting
// messages back into the model until no commands remain.
func drainCmds(m *leet.Model, cmd tea.Cmd) {
	queue := []tea.Cmd{cmd}
	for len(queue) > 0 {
		next := queue[0]
		queue = queue[1:]
		if next == nil {
			continue
		}

		msg := next()
		if msg == nil {
			continue
		}
		if batch, ok := msg.(tea.BatchMsg); ok {
			queue = append(queue, batch...)
			continue
		}

		_, cmd := m.Update(msg)
		queue = append(queue, cmd)
	}
}

func TestModel_InspectFromRunView(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	path := writeWandbFile(t, inspectorTestRecords()...)

	m := leet.NewModel(leet.ModelParams{
		RunParams: &leet.RunParams{RunFile: path},
		Config:    cfg,
		Logger:    logger,
	})
	defer m.Cleanup()

	_, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 30})

	// "i" opens the record inspector for the run's .wandb file.
	_, cmd := m.Update(tea.KeyPressMsg{Code: 'i', Text: "i"})
	drainCmds(m, cmd)

	view := m.View().Content
	assert.Contains(t, view, "record 1: run")
	assert.Contains(t, view, "abc123")
	assert.Contains(t, view, "[5 records]")

	// Help reflects the inspector mode.
	_, _ = m.Update(tea.KeyPressMsg{Code: 'h', Text: "h"})
	assert.Contains(t, m.View().Content, "record inspector")
	_, _ = m.Update(tea.KeyPressMsg{Code: 'h', Text: "h"})

	// Esc returns to the single-run view.
	_, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	assert.NotContains(t, m.View().Content, "record 1: run")
}
