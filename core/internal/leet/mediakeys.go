package leet

import tea "charm.land/bubbletea/v2"

// MediaKeyIntent identifies media-pane-local key actions. Media keeps its own
// table because arrows scrub the X-axis slider instead of moving grid focus.
type MediaKeyIntent int

const (
	MediaKeyNone MediaKeyIntent = iota
	MediaKeyToggleFullscreen
	MediaKeyExitFullscreen
	MediaKeyToggleRenderer
	MediaKeyScrubBackward
	MediaKeyScrubForward
	MediaKeyScrubJumpBackward
	MediaKeyScrubJumpForward
	MediaKeyScrubStart
	MediaKeyScrubEnd
	MediaKeySelectionLeft
	MediaKeySelectionRight
	MediaKeySelectionUp
	MediaKeySelectionDown
	MediaKeyPagePrevious
	MediaKeyPageNext
)

var mediaKeys = []struct {
	Intent MediaKeyIntent
	Keys   []string
}{
	{MediaKeyToggleFullscreen, []string{"enter"}},
	{MediaKeyExitFullscreen, []string{"esc"}},
	{MediaKeyToggleRenderer, []string{"k"}},
	{MediaKeyScrubBackward, []string{"left"}},
	{MediaKeyScrubForward, []string{"right"}},
	{MediaKeyScrubJumpBackward, []string{"up"}},
	{MediaKeyScrubJumpForward, []string{"down"}},
	{MediaKeyScrubStart, []string{"home"}},
	{MediaKeyScrubEnd, []string{"end"}},
	{MediaKeySelectionLeft, []string{"a"}},
	{MediaKeySelectionRight, []string{"d"}},
	{MediaKeySelectionUp, []string{"w"}},
	{MediaKeySelectionDown, []string{"s"}},
	{MediaKeyPagePrevious, []string{"pgup"}},
	{MediaKeyPageNext, []string{"pgdown"}},
}

var keyToMediaIntent = func() map[string]MediaKeyIntent {
	m := make(map[string]MediaKeyIntent, len(mediaKeys))
	for _, entry := range mediaKeys {
		for _, key := range entry.Keys {
			m[normalizeKey(key)] = entry.Intent
		}
	}
	return m
}()

// DecodeMediaKey returns the media-pane intent for a key press.
func DecodeMediaKey(msg tea.KeyPressMsg) MediaKeyIntent {
	return keyToMediaIntent[normalizeKey(msg.String())]
}

// MediaKeysFor returns the canonical key strings bound to an intent. The
// slice is shared; callers must not mutate it.
func MediaKeysFor(intent MediaKeyIntent) []string {
	for _, entry := range mediaKeys {
		if entry.Intent == intent {
			return entry.Keys
		}
	}
	return nil
}
