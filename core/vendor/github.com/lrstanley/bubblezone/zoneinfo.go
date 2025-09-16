// Copyright (c) Liam Stanley <liam@liam.sh>. All rights reserved. Use of
// this source code is governed by the MIT license that can be found in
// the LICENSE file.

package zone

import tea "github.com/charmbracelet/bubbletea"

// ZoneInfo holds information about the start and end positions of a zone.
type ZoneInfo struct { // nolint:revive
	id        string // rid of the zone.
	iteration int    // The iteration of the zone, used for cleaning up old zones.

	StartX int // StartX is the x coordinate of the top left cell of the zone (with 0 basis).
	StartY int // StartY is the y coordinate of the top left cell of the zone (with 0 basis).

	EndX int // EndX is the x coordinate of the bottom right cell of the zone (with 0 basis).
	EndY int // EndY is the y coordinate of the bottom right cell of the zone (with 0 basis).
}

// IsZero returns true if the zone isn't known yet (is nil).
func (z *ZoneInfo) IsZero() bool {
	if z == nil {
		return true
	}
	return z.id == ""
}

// InBounds returns true if the mouse event was in the bounds of the zones
// coordinates. If the zone is not known, it returns false. It calculates this
// using a box between the start and end coordinates. If you're looking to check
// for abnormal shapes (e.g. something that might wrap a line, but can't be
// determined using a box), you'll likely have to implement this yourself.
func (z *ZoneInfo) InBounds(e tea.MouseMsg) bool {
	if z.IsZero() {
		return false
	}

	if z.StartX > z.EndX || z.StartY > z.EndY {
		return false
	}

	if e.X < z.StartX || e.Y < z.StartY {
		return false
	}

	if e.X > z.EndX || e.Y > z.EndY {
		return false
	}

	return true
}

// Pos returns the coordinates of the mouse event relative to the zone, with a
// basis of (0, 0) being the top left cell of the zone. If the zone is not known,
// or the mouse event is not in the bounds of the zone, this will return (-1, -1).
func (z *ZoneInfo) Pos(msg tea.MouseMsg) (x, y int) {
	if z.IsZero() || !z.InBounds(msg) {
		return -1, -1
	}

	return msg.X - z.StartX, msg.Y - z.StartY
}
