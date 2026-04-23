package leet

import (
	tea "charm.land/bubbletea/v2"
)

// NavIntent identifies a pane-navigation action (up/down, page, boundary).
//
// Intents are the shared vocabulary between the help/key-binding table in
// keybindings.go and the per-pane key decoders in panelgrid.go and
// pagedlist.go. The single canonical table is navKeys below — both the
// bindings and the runtime decoders read from it, so a new or changed
// key only needs to be updated in one place.
type NavIntent int

const (
	NavIntentNone NavIntent = iota
	NavIntentUp
	NavIntentDown
	NavIntentLeft
	NavIntentRight
	NavIntentPageUp
	NavIntentPageDown
	NavIntentHome
	NavIntentEnd
)

// navKeys is the single source of truth mapping intents to the key strings
// that trigger them. The order here is the order shown in the help screen.
var navKeys = []struct {
	Intent NavIntent
	Keys   []string
}{
	{NavIntentUp, []string{"w", "up"}},
	{NavIntentDown, []string{"s", "down"}},
	{NavIntentLeft, []string{"a", "left"}},
	{NavIntentRight, []string{"d", "right"}},
	{NavIntentPageUp, []string{"N", "pgup"}},
	{NavIntentPageDown, []string{"n", "pgdown"}},
	{NavIntentHome, []string{"home"}},
	{NavIntentEnd, []string{"end"}},
}

// keyToIntent is the inverse lookup built once at package init.
var keyToIntent = func() map[string]NavIntent {
	m := make(map[string]NavIntent, len(navKeys)*2)
	for _, entry := range navKeys {
		for _, key := range entry.Keys {
			m[normalizeKey(key)] = entry.Intent
		}
	}
	return m
}()

// DecodeNav returns the NavIntent a key press represents, or NavIntentNone
// when the key is not a navigation key.
func DecodeNav(msg tea.KeyPressMsg) NavIntent {
	return keyToIntent[normalizeKey(msg.String())]
}

// NavKeysFor returns the canonical key strings bound to an intent. The
// slice is shared; callers must not mutate it.
func NavKeysFor(intent NavIntent) []string {
	for _, entry := range navKeys {
		if entry.Intent == intent {
			return entry.Keys
		}
	}
	return nil
}

// concatKeys joins multiple key-lists into one slice for binding entries
// that handle several intents with a single handler.
func concatKeys(lists ...[]string) []string {
	n := 0
	for _, l := range lists {
		n += len(l)
	}
	out := make([]string, 0, n)
	for _, l := range lists {
		out = append(out, l...)
	}
	return out
}
