// Copyright (c) Liam Stanley <liam@liam.sh>. All rights reserved. Use of
// this source code is governed by the MIT license that can be found in
// the LICENSE file.

package zone

import (
	"sort"

	tea "github.com/charmbracelet/bubbletea"
)

// MsgZoneInBounds is a message sent when the manager detects that a zone is within
// bounds of a mouse event.
type MsgZoneInBounds struct {
	Zone *ZoneInfo // The zone that is in bounds.

	Event tea.MouseMsg // The mouse event that caused the zone to be in bounds.
}

func (m *Manager) findInBounds(mouse tea.MouseMsg) []*ZoneInfo {
	var zones []*ZoneInfo

	m.zoneMu.RLock()
	defer m.zoneMu.RUnlock()

	keys := make([]string, 0, len(m.zones))
	for k := range m.zones {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	for _, k := range keys {
		zone := m.zones[k]
		if zone.InBounds(mouse) {
			zones = append(zones, zone)
		}
	}

	return zones
}

// AnyInBoundsAndUpdate is the same as AnyInBounds; except the results of the calls
// to Update() are carried through and returned.
//
// The tea.Cmd's that comd off the calls to Update() are wrapped in tea.Batch().
func (m *Manager) AnyInBoundsAndUpdate(model tea.Model, mouse tea.MouseMsg) (tea.Model, tea.Cmd) {
	zones := m.findInBounds(mouse)

	cmds := make([]tea.Cmd, len(zones))
	for i, zone := range zones {
		model, cmds[i] = model.Update(MsgZoneInBounds{Zone: zone, Event: mouse})
	}

	return model, tea.Batch(cmds...)
}

// AnyInBounds sends a MsgZoneInBounds message to the provided model for each zone
// that is in the bounds of the provided mouse event. The results of the call to
// Update() are discarded.
//
// Note that if multiple zones are within bounds, each one will be sent as an event
// in alphabetical sorted order of the ID.
func (m *Manager) AnyInBounds(model tea.Model, mouse tea.MouseMsg) {
	zones := m.findInBounds(mouse)

	for _, zone := range zones {
		_, _ = model.Update(MsgZoneInBounds{Zone: zone, Event: mouse})
	}
}
