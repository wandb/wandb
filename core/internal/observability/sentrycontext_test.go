package observability_test

import (
	"testing"

	"github.com/getsentry/sentry-go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
)

// newTestHub returns a Sentry hub using a MockTransport for testing outputs.
func newTestHub(t *testing.T) (*sentry.Hub, *sentry.MockTransport) {
	transport := &sentry.MockTransport{}

	client, err := sentry.NewClient(sentry.ClientOptions{Transport: transport})
	require.NoError(t, err)

	hub := sentry.NewHub(client, sentry.NewScope())
	return hub, transport
}

func TestSentryContextTags(t *testing.T) {
	hub, transport := newTestHub(t)
	sc := observability.NewSentryContext(hub)

	sc.AddTags(map[string]string{"base1": "tag1"})
	sc.WithScope(func(h *sentry.Hub) {
		h.Scope().SetTag("scoped1", "value1")
		h.CaptureMessage("scoped message")
	})
	sc.AddTags(map[string]string{"base2": "tag2"})
	sc.WithScope(func(h *sentry.Hub) {
		h.Scope().SetTag("scoped2", "value2")
		h.CaptureMessage("scoped message")
	})

	events := transport.Events()
	require.Len(t, events, 2)

	assert.Equal(t, map[string]string{
		"base1":   "tag1",
		"scoped1": "value1",
	}, events[0].Tags)
	assert.Equal(t, map[string]string{
		"base1":   "tag1",
		"base2":   "tag2",
		"scoped2": "value2",
	}, events[1].Tags)
}
