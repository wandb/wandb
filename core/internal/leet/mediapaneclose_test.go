package leet

import (
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
)

// Close must unblock the prepare command and be idempotent.
func TestMediaPaneCloseUnblocksPrepare(t *testing.T) {
	p := NewMediaPane(NewAnimatedValue(true, mediaPaneMinHeight), func() (int, int) { return 1, 1 })

	done := make(chan tea.Msg, 1)
	go func() { done <- p.waitForPrepare()() }()

	p.Close()
	p.Close() // idempotent

	select {
	case msg := <-done:
		if msg != nil {
			t.Fatalf("expected nil msg from closed prepare wait, got %T", msg)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("waitForPrepare still blocked after Close")
	}
}
