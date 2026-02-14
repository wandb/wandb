package leet

import (
	"strings"
	"time"

	"github.com/charmbracelet/lipgloss"
)

// Bottom bar constants.
const (
	// BottomBarHeightRatio is the fraction of content height allocated to the
	// bottom panel. Derived from the golden ratio: 1 − 1/φ ≈ 0.382.
	BottomBarHeightRatio = SidebarWidthRatio // 0.382

	// BottomBarMinHeight is the minimum usable height for the panel.
	BottomBarMinHeight = 2

	// bottomBarHeader is the default title rendered in the panel header.
	bottomBarHeader = "Console Logs"

	// bottomBarBorderLines accounts for the top-border decoration.
	bottomBarBorderLines = 1

	// bottomBarHeaderLines accounts for the header row inside the panel.
	bottomBarHeaderLines = 1
)

// BottomBar represents a collapsible bottom panel for console logs.
//
// It reuses [AnimationState] to animate the panel height, mirroring how
// sidebars animate their width.
type BottomBar struct {
	animState *AnimationState
}

// NewBottomBar creates a new collapsed bottom bar.
func NewBottomBar() *BottomBar {
	return &BottomBar{
		animState: NewAnimationState(false, BottomBarMinHeight),
	}
}

// Toggle toggles between expanded and collapsed states.
func (b *BottomBar) Toggle() {
	b.animState.Toggle()
}

// Height returns the current animated height (0 when fully collapsed).
func (b *BottomBar) Height() int {
	return b.animState.Width()
}

// IsVisible reports whether the panel occupies any vertical space.
func (b *BottomBar) IsVisible() bool {
	return b.animState.IsVisible()
}

// IsAnimating reports whether the panel is mid-animation.
func (b *BottomBar) IsAnimating() bool {
	return b.animState.IsAnimating()
}

// Update advances the animation; returns true when complete.
func (b *BottomBar) Update(now time.Time) bool {
	return b.animState.Update(now)
}

// SetExpandedHeight updates the target expanded height, typically called
// on window resize so the panel tracks the golden-ratio proportion.
func (b *BottomBar) SetExpandedHeight(h int) {
	b.animState.SetExpandedWidth(max(h, BottomBarMinHeight))
}

// UpdateExpandedHeight recalculates the expanded height from the total
// content height (the area above the status bar).
func (b *BottomBar) UpdateExpandedHeight(totalContentHeight int) {
	h := int(float64(totalContentHeight) * BottomBarHeightRatio)
	b.SetExpandedHeight(h)
}

// View renders the bottom bar panel.
func (b *BottomBar) View(width int) string {
	h := b.Height()
	if h <= 0 || width <= 0 {
		return ""
	}

	innerH := h - bottomBarBorderLines

	if innerH <= BottomBarMinHeight {
		return ""
	}

	header := bottomBarHeaderStyle.Render(bottomBarHeader)

	contentLines := innerH - bottomBarHeaderLines
	placeholder := bottomBarContentStyle.Render(
		strings.Repeat("\n", max(contentLines-1, 0)),
	)
	content := lipgloss.JoinVertical(lipgloss.Left, header, placeholder)

	rendered := bottomBarBorderStyle.
		Width(width).
		MaxWidth(width).
		Render(content)

	// Force exact dimensions: clips overflow (small h) and pads
	// underflow (border/content height mismatch) so the caller can
	// rely on Height() for arithmetic without visual surprises.
	return lipgloss.Place(width, h, lipgloss.Left, lipgloss.Top, rendered)
}
