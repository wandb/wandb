package leet_test

import (
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func mediaBindingMsg(t *testing.T, key string) tea.KeyPressMsg {
	t.Helper()

	switch key {
	case "enter":
		return tea.KeyPressMsg{Code: tea.KeyEnter}
	case "esc":
		return tea.KeyPressMsg{Code: tea.KeyEsc}
	default:
		return navBindingMsg(t, key)
	}
}

func TestDecodeMediaKey_MatchesDeclaredBindings(t *testing.T) {
	intents := []leet.MediaKeyIntent{
		leet.MediaKeyToggleFullscreen,
		leet.MediaKeyExitFullscreen,
		leet.MediaKeyToggleRenderer,
		leet.MediaKeyScrubBackward,
		leet.MediaKeyScrubForward,
		leet.MediaKeyScrubJumpBackward,
		leet.MediaKeyScrubJumpForward,
		leet.MediaKeyScrubStart,
		leet.MediaKeyScrubEnd,
		leet.MediaKeySelectionLeft,
		leet.MediaKeySelectionRight,
		leet.MediaKeySelectionUp,
		leet.MediaKeySelectionDown,
		leet.MediaKeyPagePrevious,
		leet.MediaKeyPageNext,
	}

	for _, intent := range intents {
		keys := leet.MediaKeysFor(intent)
		require.NotEmpty(t, keys, "intent %d should have keys", intent)
		for _, key := range keys {
			require.Equalf(t, intent, leet.DecodeMediaKey(mediaBindingMsg(t, key)),
				"binding %q should decode to intent %d", key, intent)
		}
	}

	require.Equal(t, leet.MediaKeyNone, leet.DecodeMediaKey(tea.KeyPressMsg{Code: 'q', Text: "q"}))
	require.Nil(t, leet.MediaKeysFor(leet.MediaKeyNone))
}
