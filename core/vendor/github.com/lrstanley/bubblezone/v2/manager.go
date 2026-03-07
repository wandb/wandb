// Copyright (c) Liam Stanley <liam@liam.sh>. All rights reserved. Use of
// this source code is governed by the MIT license that can be found in
// the LICENSE file.

package zone

import (
	"context"
	"strconv"
	"sync"
	"sync/atomic"
	"time"
)

const (
	// Have to use ansi escape codes to ensure lipgloss doesn't consider ID's as
	// part of the width of the view.
	identStart   = '\x1B' // ANSI escape code.
	identBracket = '['
	// The escape terminator.
	//
	// Refs:
	//  - https://en.wikipedia.org/wiki/ANSI_escape_code#CSI_(Control_Sequence_Introducer)_sequences
	//    > A subset of arrangements was declared "private" so that terminal manufacturers could insert
	//    > their own sequences without conflicting with the standard. Sequences containing the parameter
	//    > bytes <=>? or the final bytes 0x70-0x7E (p-z{|}~) are private.
	identEnd = 'z'
)

var (
	markerCounter int64 = 1000 // Protected by atomic operations.
	prefixCounter int64 = 0    // Protected by atomic operations.
)

// New creates a new (non-global) zone manager. The zone manager is responsible for
// parsing zone information from the output of a component, and storing it for
// later retrieval/bounds checks.
//
// The zone manager is enabled by default, and can be toggled by calling
// SetEnabled().
func New() (m *Manager) {
	m = &Manager{
		setChan: make(chan *ZoneInfo, 200),
		zones:   make(map[string]*ZoneInfo),
		ids:     make(map[string]string),
		rids:    make(map[string]string),
	}

	m.ctx, m.cancel = context.WithCancel(context.Background())
	m.enabled.Store(true)
	go m.zoneWorker()

	return m
}

// Manager holds the state of the zone manager, including ID zones and
// zones of components.
type Manager struct {
	ctx     context.Context
	cancel  func()
	enabled atomic.Bool

	setChan chan *ZoneInfo

	zoneMu sync.RWMutex
	zones  map[string]*ZoneInfo

	idMu sync.RWMutex
	ids  map[string]string // user ID -> generated control sequence ID.
	rids map[string]string // generated control sequence ID -> user ID.
}

func (m *Manager) checkInitialized() {
	if m == nil {
		panic("manager not initialized")
	}
}

// Close stops the manager worker.
func (m *Manager) Close() {
	m.cancel()
}

// SetEnabled enables or disables the zone manager. When disabled, the zone manager
// will still parse zone information, however it will immediately drop it and remove
// zone markers from the resulting output.
//
// The zone manager is enabled by default.
func (m *Manager) SetEnabled(enabled bool) {
	m.enabled.Store(enabled)

	if !enabled {
		// Tell the worker to clear all zones if we're disabling the manager.
		iteration := time.Now().Nanosecond()
		m.setChan <- &ZoneInfo{iteration: iteration}
	}
}

// Enabled returns whether the zone manager is enabled or not. When disabled,
// the zone manager will still parse zone information, however it will immediately
// drop it and remove zone markers from the resulting output.
//
// The zone manager is enabled by default.
func (m *Manager) Enabled() bool {
	return m.enabled.Load()
}

// NewPrefix generates a zone marker ID prefix, which can help prevent overlapping
// zone markers between multiple components. Each call to NewPrefix() returns a
// new unique prefix.
//
// Usage example:
//
//	func NewModel() tea.Model {
//		return &model{
//			id: zone.NewPrefix(),
//		}
//	}
//
//	type model struct {
//		id     string
//		active int
//		items  []string
//	}
//
//	func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
//		switch msg := msg.(type) {
//		// [...]
//		case tea.MouseMsg:
//			// [...]
//			for i, item := range m.items {
//				if zone.Get(m.id + item.name).InBounds(msg) {
//					m.active = i
//					break
//				}
//			}
//		}
//		return m, nil
//	}
//
//	func (m model) View() string {
//		return zone.Mark(m.id+"some-other-id", "rendered stuff here")
//	}
func (m *Manager) NewPrefix() string {
	return "zone_" + strconv.FormatInt(atomic.AddInt64(&prefixCounter, 1), 10) + "__"
}

// Mark returns v wrapped with a start and end ANSI sequence to allow the zone
// manager to determine where the zone is, including its window offsets. The ANSI
// sequences used should be ignored by lipgloss width methods, to prevent incorrect
// width calculations.
//
// When the zone manager is disabled, Mark() will return v without any changes.
func (m *Manager) Mark(id, v string) string {
	if !m.Enabled() {
		return v
	}

	if id == "" || v == "" {
		return v
	}

	m.idMu.RLock()
	gid := m.ids[id]
	m.idMu.RUnlock()

	if gid != "" {
		return gid + v + gid
	}

	m.idMu.Lock()
	gid = string(identStart) + string(identBracket) + strconv.FormatInt(atomic.AddInt64(&markerCounter, 1), 10) + string(identEnd)
	m.ids[id] = gid
	m.rids[gid] = id
	m.idMu.Unlock()

	return gid + v + gid
}

// Clear removes any stored zones for the given ID.
func (m *Manager) Clear(id string) {
	m.zoneMu.Lock()
	delete(m.zones, id)
	m.zoneMu.Unlock()
}

// Get returns the zone info of the given ID. If the ID is not known (yet),
// Get() returns nil.
func (m *Manager) Get(id string) (zone *ZoneInfo) {
	m.zoneMu.RLock()
	zone = m.zones[id]
	m.zoneMu.RUnlock()
	return zone
}

// getReverse returns the component ID from a generated ID (that includes ANSI
// escape codes).
func (m *Manager) getReverse(id string) (resolved string) {
	m.idMu.RLock()
	resolved = m.rids[id]
	m.idMu.RUnlock()
	return resolved
}

func (m *Manager) zoneWorker() {
	for {
		select {
		case <-m.ctx.Done():
			return
		case xy := <-m.setChan:
			m.zoneMu.Lock()
			if xy.id != "" {
				m.zones[m.getReverse(xy.id)] = xy
			} else {
				// Assume previous iterations are cleared.
				for k := range m.zones {
					if m.zones[k].iteration != xy.iteration {
						delete(m.zones, k)
					}
				}
			}
			m.zoneMu.Unlock()
		}
	}
}

// Scan will scan the view output, searching for zone markers, returning the
// original view output with the zone markers stripped. Scan() should be used
// by the outer most model/component of your application, and not inside of a
// model/component child.
//
// Scan buffers the zone info to be stored, so an immediate call to Get(id) may
// not return the correct information. Thus it's recommended to primarily use
// Get(id) for actions like mouse events, which don't occur immediately after a
// view shift (where the previously stored zone info might be different).
//
// When the zone manager is disabled (via SetEnabled(false)), Scan() will return
// the original view output with all zone markers stripped. It will still parse
// the input for zone markers, as some users may cache generated views. In most
// situations when the zone manager is disabled (and thus Mark() returns input
// unchanged), Scan() will not need to do any work.
func (m *Manager) Scan(v string) string {
	iteration := time.Now().Nanosecond()
	s := newScanner(m, v, iteration)
	s.run()
	m.setChan <- &ZoneInfo{iteration: iteration}
	return s.input
}
