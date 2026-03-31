package leet

import (
	"fmt"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"maps"
	"math"
	"os"
	"strings"
	"sync"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

const (
	// Golden ratio constants for visually pleasing layout proportions.
	GoldenRatio    = 1.618033988749895
	UpperTierRatio = GoldenRatio / (1 + GoldenRatio) // ≈ 0.618
	LowerTierRatio = 1.0 / (1 + GoldenRatio)         // ≈ 0.382

	// MediaPaneHeightRatio controls the fraction of total terminal height used
	// when the media pane is the only bottom pane visible.
	MediaPaneHeightRatio = ConsoleLogsPaneHeightRatio

	// BottomPaneHeightRatioThree is the per-pane fraction used when three
	// stacked bottom panes are visible at once.
	BottomPaneHeightRatioThree = 0.146

	mediaPaneHeader      = "Media"
	mediaPaneHeaderLines = 2
	mediaTileMinWidth    = 18
	mediaTileMinHeight   = 8
	mediaTileBorderLines = 2
	mediaTileTitleLines  = 1
	mediaTileFooterLines = 1
	mediaPaneMinHeight   = mediaPaneHeaderLines + mediaTileMinHeight
)

var (
	mediaPaneStyle = lipgloss.NewStyle().
			Padding(0, ContentPadding)

	mediaPaneHeaderStyle = lipgloss.NewStyle().
				Foreground(colorSubheading).
				Bold(true)

	mediaPaneActiveHeaderStyle = lipgloss.NewStyle().
					Foreground(colorLayoutHighlight).
					Bold(true)

	mediaPaneSliderStyle = lipgloss.NewStyle().
				Foreground(colorSubtle)

	mediaTileBorderStyle = lipgloss.NewStyle().
				Border(lipgloss.NormalBorder()).
				BorderForeground(colorLayout)

	mediaTileSelectedBorderStyle = lipgloss.NewStyle().
					Border(lipgloss.NormalBorder()).
					BorderForeground(colorLayoutHighlight)

	mediaTileTitleStyle = lipgloss.NewStyle().
				Foreground(colorText).
				Bold(true)

	mediaTileSelectedTitleStyle = lipgloss.NewStyle().
					Foreground(colorSubheading).
					Bold(true)

	mediaTileFooterStyle = lipgloss.NewStyle().
				Foreground(colorSubtle)

	mediaTilePlaceholderStyle = lipgloss.NewStyle().
					Foreground(colorSubtle)
)

// MediaPane is a collapsible, animated pane that renders wandb.Image media as
// ANSI thumbnails.
type MediaPane struct {
	animState  *AnimatedValue
	gridConfig func() (rows, cols int)
	renderer   *mediaImageRenderer

	store *MediaStore

	active     bool
	fullscreen bool

	selectedIndex int
	pageRows      int
	pageCols      int

	// Per-series X-axis state. Keys are series names.
	xIndices    map[string]int
	autoFollows map[string]bool

	nav GridNavigator
}

func NewMediaPane(animState *AnimatedValue, gridConfig func() (rows, cols int)) *MediaPane {
	return &MediaPane{
		animState:   animState,
		gridConfig:  gridConfig,
		renderer:    newMediaImageRenderer(),
		xIndices:    make(map[string]int),
		autoFollows: make(map[string]bool),
		pageRows:    1,
		pageCols:    1,
	}
}

func (p *MediaPane) Height() int             { return p.animState.Value() }
func (p *MediaPane) IsExpanded() bool        { return p.animState.IsExpanded() }
func (p *MediaPane) IsVisible() bool         { return p.animState.IsVisible() }
func (p *MediaPane) IsAnimating() bool       { return p.animState.IsAnimating() }
func (p *MediaPane) Active() bool            { return p.active }
func (p *MediaPane) IsFullscreen() bool      { return p.fullscreen }
func (p *MediaPane) SetActive(active bool)   { p.active = active }
func (p *MediaPane) Toggle()                 { p.animState.Toggle() }
func (p *MediaPane) Update(t time.Time) bool { return p.animState.Update(t) }

func (p *MediaPane) SetExpandedHeight(height int) {
	p.animState.SetExpanded(max(height, mediaPaneMinHeight))
}

func (p *MediaPane) UpdateExpandedHeight(maxTerminalHeight int) {
	maxHeight := int(float64(maxTerminalHeight) * MediaPaneHeightRatio)
	p.SetExpandedHeight(maxHeight)
}

func (p *MediaPane) SetStore(store *MediaStore) {
	if p.store == store {
		p.syncState()
		return
	}
	p.store = store
	p.syncState()
}

func (p *MediaPane) ToggleFullscreen() {
	p.fullscreen = !p.fullscreen
	if p.fullscreen {
		p.active = true
	}
}

// MediaPaneViewState captures the navigable state of a MediaPane so it can
// be saved and restored across Run view transitions.
type MediaPaneViewState struct {
	SelectedIndex int
	XIndices      map[string]int
	AutoFollows   map[string]bool
}

func (p *MediaPane) SaveViewState() MediaPaneViewState {
	xi := make(map[string]int, len(p.xIndices))
	maps.Copy(xi, p.xIndices)
	af := make(map[string]bool, len(p.autoFollows))
	maps.Copy(af, p.autoFollows)
	return MediaPaneViewState{
		SelectedIndex: p.selectedIndex,
		XIndices:      xi,
		AutoFollows:   af,
	}
}

func (p *MediaPane) RestoreViewState(s MediaPaneViewState) {
	p.selectedIndex = s.SelectedIndex
	clear(p.xIndices)
	maps.Copy(p.xIndices, s.XIndices)
	clear(p.autoFollows)
	maps.Copy(p.autoFollows, s.AutoFollows)
	p.fullscreen = false
	p.syncState()
}

func (p *MediaPane) ResetViewState() {
	p.selectedIndex = 0
	clear(p.xIndices)
	clear(p.autoFollows)
	p.nav.currentPage = 0
	p.fullscreen = false
	p.syncState()
}

func (p *MediaPane) ExitFullscreen() {
	p.fullscreen = false
}

func (p *MediaPane) syncState() {
	keys := p.seriesKeys()

	if len(keys) == 0 {
		p.selectedIndex = 0
		p.nav.UpdateTotalPages(0, 1)
		p.fullscreen = false
		return
	}

	p.selectedIndex = clamp(p.selectedIndex, 0, len(keys)-1)

	// Ensure per-series indices exist and are clamped.
	for _, key := range keys {
		xs := p.seriesXValues(key)
		if _, ok := p.autoFollows[key]; !ok {
			p.autoFollows[key] = true
		}
		switch {
		case len(xs) == 0:
			p.xIndices[key] = 0
		case p.autoFollows[key]:
			p.xIndices[key] = len(xs) - 1
		default:
			p.xIndices[key] = clamp(p.xIndices[key], 0, len(xs)-1)
		}
	}

	itemsPerPage := p.itemsPerPage()
	p.nav.UpdateTotalPages(len(keys), itemsPerPage)
	if itemsPerPage > 0 {
		page := p.selectedIndex / itemsPerPage
		if page >= 0 && page < p.nav.TotalPages() {
			p.nav.currentPage = page
		}
	}
}

func (p *MediaPane) seriesKeys() []string {
	if p.store == nil {
		return nil
	}
	return p.store.SeriesKeys()
}

func (p *MediaPane) paginationGrid() (rows, cols int) {
	rows = max(p.pageRows, 1)
	cols = max(p.pageCols, 1)
	return rows, cols
}

func (p *MediaPane) itemsPerPage() int {
	rows, cols := p.paginationGrid()
	return max(rows*cols, 1)
}

func (p *MediaPane) seriesXValues(key string) []float64 {
	if p.store == nil {
		return nil
	}
	return p.store.SeriesXValues(key)
}

func (p *MediaPane) currentXForSeries(key string) (float64, bool) {
	xs := p.seriesXValues(key)
	if len(xs) == 0 {
		return 0, false
	}
	idx := clamp(p.xIndices[key], 0, len(xs)-1)
	return xs[idx], true
}

func (p *MediaPane) currentSelection() (string, MediaPoint, bool) {
	keys := p.seriesKeys()
	if len(keys) == 0 {
		return "", MediaPoint{}, false
	}
	idx := clamp(p.selectedIndex, 0, len(keys)-1)
	key := keys[idx]
	x, ok := p.currentXForSeries(key)
	if !ok || p.store == nil {
		return key, MediaPoint{}, false
	}
	point, found := p.store.ResolveAt(key, x)
	return key, point, found
}

func (p *MediaPane) HasData() bool {
	return p.store != nil && !p.store.Empty()
}

func (p *MediaPane) StatusLabel() string {
	key, point, ok := p.currentSelection()
	if key == "" {
		return ""
	}

	x, hasX := p.currentXForSeries(key)
	parts := []string{fmt.Sprintf("Media: %s", key)}
	if hasX {
		parts = append(parts, fmt.Sprintf("X=_step %s", formatMediaAxisValue(x)))
	}
	if ok && point.Caption != "" {
		parts = append(parts, truncateValue(point.Caption, 48))
	}
	if p.fullscreen {
		parts = append(parts, "fullscreen")
	}
	return strings.Join(parts, " • ")
}

// HandleKey handles media-pane-local navigation. It returns true when the key
// was consumed.
func (p *MediaPane) HandleKey(msg tea.KeyPressMsg) bool {
	if !p.active && !p.fullscreen {
		return false
	}

	switch normalizeKey(msg.String()) {
	case "enter":
		if p.HasData() {
			p.ToggleFullscreen()
		}
		return true
	case "esc":
		if p.fullscreen {
			p.ExitFullscreen()
			return true
		}
		return false
	case "left":
		p.Scrub(-1)
		return true
	case "right":
		p.Scrub(1)
		return true
	case "up":
		p.Scrub(-10)
		return true
	case "down":
		p.Scrub(10)
		return true
	case "home":
		p.ScrubToStart()
		return true
	case "end":
		p.ScrubToEnd()
		return true
	case "a":
		p.MoveSelection(-1, 0)
		return true
	case "d":
		p.MoveSelection(1, 0)
		return true
	case "w":
		p.MoveSelection(0, -1)
		return true
	case "s":
		p.MoveSelection(0, 1)
		return true
	case "pgup":
		p.NavigatePage(-1)
		return true
	case "pgdown":
		p.NavigatePage(1)
		return true
	default:
		return false
	}
}

func (p *MediaPane) MoveSelection(dx, dy int) {
	keys := p.seriesKeys()
	if len(keys) == 0 {
		return
	}

	rows, cols := p.paginationGrid()
	itemsPerPage := p.itemsPerPage()
	p.nav.UpdateTotalPages(len(keys), itemsPerPage)

	startIdx, endIdx := p.nav.PageBounds(len(keys), itemsPerPage)
	if p.selectedIndex < startIdx || p.selectedIndex >= endIdx {
		p.nav.currentPage = p.selectedIndex / itemsPerPage
		startIdx, endIdx = p.nav.PageBounds(len(keys), itemsPerPage)
	}

	local := clamp(p.selectedIndex-startIdx, 0, max(endIdx-startIdx-1, 0))
	row := local / cols
	col := local % cols
	row = clamp(row+dy, 0, rows-1)
	col = clamp(col+dx, 0, cols-1)

	candidate := startIdx + row*cols + col
	if candidate >= endIdx {
		candidate = endIdx - 1
	}
	if candidate >= startIdx {
		p.selectedIndex = candidate
	}
}

func (p *MediaPane) NavigatePage(direction int) {
	keys := p.seriesKeys()
	if len(keys) == 0 {
		return
	}

	itemsPerPage := p.itemsPerPage()
	p.nav.UpdateTotalPages(len(keys), itemsPerPage)
	if !p.nav.Navigate(direction) {
		return
	}

	startIdx, endIdx := p.nav.PageBounds(len(keys), itemsPerPage)
	if p.selectedIndex < startIdx || p.selectedIndex >= endIdx {
		p.selectedIndex = startIdx
	}
}

// selectedKey returns the currently selected series key.
func (p *MediaPane) selectedKey() string {
	keys := p.seriesKeys()
	if len(keys) == 0 {
		return ""
	}
	return keys[clamp(p.selectedIndex, 0, len(keys)-1)]
}

func (p *MediaPane) Scrub(delta int) {
	key := p.selectedKey()
	if key == "" {
		return
	}
	xs := p.seriesXValues(key)
	if len(xs) == 0 {
		return
	}
	p.xIndices[key] = clamp(p.xIndices[key]+delta, 0, len(xs)-1)
	p.autoFollows[key] = p.xIndices[key] == len(xs)-1
}

func (p *MediaPane) ScrubToStart() {
	key := p.selectedKey()
	if key == "" {
		return
	}
	p.xIndices[key] = 0
	p.autoFollows[key] = false
}

func (p *MediaPane) ScrubToEnd() {
	key := p.selectedKey()
	if key == "" {
		return
	}
	xs := p.seriesXValues(key)
	if len(xs) == 0 {
		return
	}
	p.xIndices[key] = len(xs) - 1
	p.autoFollows[key] = true
}

func (p *MediaPane) syncGridLayoutForViewport(width, height int) {
	if p.fullscreen {
		return
	}

	innerW := max(width-ContentPaddingCols, 0)
	innerH := max(height, 0)
	if innerW == 0 || innerH == 0 {
		return
	}

	rows, cols, _, _ := p.effectiveGrid(innerW, max(innerH-mediaPaneHeaderLines, 1))
	if rows != p.pageRows || cols != p.pageCols {
		p.pageRows = rows
		p.pageCols = cols
		p.syncState()
	}
}

func (p *MediaPane) tileIndexAt(x, y, width, height int) (int, bool) {
	if width <= 0 || height < mediaPaneMinHeight || p.fullscreen {
		return 0, false
	}

	p.syncGridLayoutForViewport(width, height)
	keys := p.seriesKeys()
	if len(keys) == 0 {
		return 0, false
	}

	innerW := max(width-ContentPaddingCols, 0)
	gridH := max(height-mediaPaneHeaderLines, 0)
	gridX := x - ContentPadding
	gridY := y - mediaPaneHeaderLines
	if gridX < 0 || gridY < 0 || gridX >= innerW || gridY >= gridH {
		return 0, false
	}

	rows, cols, slotW, slotH := p.effectiveGrid(innerW, max(gridH, 1))
	row := gridY / slotH
	col := gridX / slotW
	if row < 0 || row >= rows || col < 0 || col >= cols {
		return 0, false
	}

	itemsPerPage := max(rows*cols, 1)
	p.nav.UpdateTotalPages(len(keys), itemsPerPage)
	startIdx, endIdx := p.nav.PageBounds(len(keys), itemsPerPage)
	idx := startIdx + row*cols + col
	if idx < startIdx || idx >= endIdx || idx >= len(keys) {
		return 0, false
	}

	return idx, true
}

// HandleMouseClick selects the clicked media tile.
func (p *MediaPane) HandleMouseClick(x, y, width, height int) bool {
	idx, ok := p.tileIndexAt(x, y, width, height)
	if !ok {
		return false
	}
	p.selectedIndex = idx
	return true
}

func (p *MediaPane) View(width, height int, runLabel, hint string) string {
	if width <= 0 || height < mediaPaneMinHeight {
		return ""
	}

	innerW := max(width-ContentPaddingCols, 0)
	innerH := max(height, 0)
	if innerW == 0 || innerH == 0 {
		return ""
	}
	p.syncGridLayoutForViewport(width, height)

	var body string
	if p.fullscreen {
		body = p.renderFullscreenBody(innerW, innerH, runLabel, hint)
	} else {
		body = p.renderGridBody(innerW, innerH, runLabel, hint)
	}

	body = lipgloss.Place(innerW, innerH, lipgloss.Left, lipgloss.Top, body)
	padded := mediaPaneStyle.Render(body)
	return lipgloss.Place(width, height, lipgloss.Left, lipgloss.Top, padded)
}

func (p *MediaPane) renderGridBody(width, height int, runLabel, hint string) string {
	gridHeight := max(height-mediaPaneHeaderLines, 0)
	head := p.renderHeader(width, runLabel, false)
	slider := p.renderSlider(width)
	grid := p.renderGrid(width, gridHeight, hint)
	return lipgloss.JoinVertical(lipgloss.Left, head, slider, grid)
}

func (p *MediaPane) renderFullscreenBody(width, height int, runLabel, hint string) string {
	key, point, ok := p.currentSelection()
	head := p.renderHeader(width, runLabel, true)
	slider := p.renderSlider(width)
	bodyHeight := max(height-mediaPaneHeaderLines, 0)
	if !ok {
		placeholder := renderMediaPlaceholder(width, bodyHeight, hintOrDefault(hint, "No media."))
		return lipgloss.JoinVertical(lipgloss.Left, head, slider, placeholder)
	}

	title := mediaTileSelectedTitleStyle.Width(width).Render(key)
	footer := mediaTileFooterStyle.Width(width).Render(p.fullscreenFooter(point, width))
	imageHeight := max(bodyHeight-2, 1)
	img := p.renderer.Render(point.FilePath, width, imageHeight)
	content := lipgloss.JoinVertical(lipgloss.Left, title, img, footer)
	content = lipgloss.Place(width, bodyHeight, lipgloss.Left, lipgloss.Top, content)
	return lipgloss.JoinVertical(lipgloss.Left, head, slider, content)
}

func (p *MediaPane) renderHeader(width int, runLabel string, fullscreen bool) string {
	title := mediaPaneHeader
	if fullscreen {
		title += " [fullscreen]"
	}
	headerStyle := mediaPaneHeaderStyle
	if p.active || p.fullscreen {
		headerStyle = mediaPaneActiveHeaderStyle
	}
	left := headerStyle.Render(title)
	if runLabel != "" {
		left = lipgloss.JoinHorizontal(
			lipgloss.Left,
			left,
			mediaPaneSliderStyle.Render(" • "+truncateValue(runLabel, max(width/3, 1))),
		)
	}

	keys := p.seriesKeys()
	itemsPerPage := p.itemsPerPage()
	p.nav.UpdateTotalPages(len(keys), itemsPerPage)
	startIdx, endIdx := p.nav.PageBounds(len(keys), itemsPerPage)
	info := ""
	if len(keys) > 0 {
		info = fmt.Sprintf("[%d-%d of %d]", startIdx+1, endIdx, len(keys))
	}
	if p.nav.TotalPages() > 1 {
		info = fmt.Sprintf("%s  p.%d/%d", info, p.nav.CurrentPage()+1, p.nav.TotalPages())
	}
	info = mediaPaneSliderStyle.Render(strings.TrimSpace(info))

	fillerWidth := max(width-lipgloss.Width(left)-lipgloss.Width(info), 0)
	return lipgloss.JoinHorizontal(lipgloss.Left, left, strings.Repeat(" ", fillerWidth), info)
}

func (p *MediaPane) renderSlider(width int) string {
	key := p.selectedKey()
	if key == "" {
		return mediaPaneSliderStyle.Width(width).Render("X: _step —")
	}
	xs := p.seriesXValues(key)
	if len(xs) == 0 {
		return mediaPaneSliderStyle.Width(width).Render("X: _step —")
	}

	idx := clamp(p.xIndices[key], 0, len(xs)-1)
	barWidth := clamp(width-24, 8, 48)
	pos := 0
	if len(xs) > 1 {
		pos = idx * (barWidth - 1) / (len(xs) - 1)
	}

	var b strings.Builder
	for i := 0; i < barWidth; i++ {
		switch {
		case i < pos:
			b.WriteRune('━')
		case i == pos:
			b.WriteRune('●')
		default:
			b.WriteRune('─')
		}
	}

	text := fmt.Sprintf(
		"X: _step %s  %s  %d/%d",
		formatMediaAxisValue(xs[idx]),
		b.String(),
		idx+1,
		len(xs),
	)
	return mediaPaneSliderStyle.Width(width).Render(truncateValue(text, width))
}

func (p *MediaPane) renderGrid(width, height int, hint string) string {
	keys := p.seriesKeys()
	if len(keys) == 0 {
		return renderMediaPlaceholder(width, height, hintOrDefault(hint, "No media."))
	}

	rows, cols, slotW, slotH := p.effectiveGrid(width, height)
	itemsPerPage := max(rows*cols, 1)
	p.nav.UpdateTotalPages(len(keys), itemsPerPage)
	startIdx, endIdx := p.nav.PageBounds(len(keys), itemsPerPage)
	if p.selectedIndex < startIdx || p.selectedIndex >= endIdx {
		p.selectedIndex = startIdx
	}

	showSelection := p.active || p.fullscreen
	cells := make([]string, 0, itemsPerPage)
	for idx := startIdx; idx < endIdx; idx++ {
		key := keys[idx]
		x, hasX := p.currentXForSeries(key)
		point, ok := MediaPoint{}, false
		if hasX && p.store != nil {
			point, ok = p.store.ResolveAt(key, x)
		}
		cells = append(
			cells,
			p.renderTile(key, point, ok, showSelection && idx == p.selectedIndex, slotW, slotH))

	}
	for len(cells) < itemsPerPage {
		cells = append(cells, lipgloss.NewStyle().Width(slotW).Height(slotH).Render(""))
	}

	var rowViews []string
	for row := range rows {
		start := row * cols
		end := min(start+cols, len(cells))
		if start >= end {
			break
		}
		rowViews = append(rowViews, lipgloss.JoinHorizontal(lipgloss.Top, cells[start:end]...))
	}

	grid := lipgloss.JoinVertical(lipgloss.Left, rowViews...)
	return lipgloss.Place(width, height, lipgloss.Left, lipgloss.Top, grid)
}

func (p *MediaPane) renderTile(
	key string,
	point MediaPoint,
	ok bool,
	selected bool,
	slotW int,
	slotH int,
) string {
	innerW := max(slotW-mediaTileBorderLines, 1)
	innerH := max(slotH-mediaTileBorderLines, 1)

	footerLines := 0
	if innerH >= mediaTileTitleLines+mediaTileFooterLines+2 {
		footerLines = mediaTileFooterLines
	}
	imageH := max(innerH-mediaTileTitleLines-footerLines, 1)

	titleStyle := mediaTileTitleStyle
	borderStyle := mediaTileBorderStyle
	if selected {
		titleStyle = mediaTileSelectedTitleStyle
		borderStyle = mediaTileSelectedBorderStyle
	}

	title := titleStyle.Width(innerW).Render(truncateValue(key, innerW))

	var imageView string
	if ok {
		imageView = p.renderer.Render(point.FilePath, innerW, imageH)
	} else {
		imageView = renderMediaPlaceholder(innerW, imageH, "No image at X")
	}

	parts := []string{title, imageView}
	if footerLines > 0 {
		parts = append(parts,
			mediaTileFooterStyle.Width(innerW).Render(p.tileFooter(key, point, ok, innerW)))
	}

	content := lipgloss.JoinVertical(lipgloss.Left, parts...)
	content = lipgloss.Place(innerW, innerH, lipgloss.Left, lipgloss.Top, content)
	return borderStyle.Width(slotW).Height(slotH).Render(content)
}

func (p *MediaPane) tileFooter(key string, point MediaPoint, ok bool, width int) string {
	x, hasX := p.currentXForSeries(key)
	stepLabel := ""
	if hasX {
		stepLabel = "X=_step " + formatMediaAxisValue(x)
	}
	if !ok {
		return truncateValue(stepLabel, width)
	}
	var parts []string
	if point.Caption != "" {
		parts = append(parts, point.Caption)
	}
	if stepLabel != "" {
		parts = append(parts, stepLabel)
	}
	if len(parts) == 0 {
		return truncateValue(
			fmt.Sprintf("%dx%d %s", point.Width, point.Height, strings.ToUpper(point.Format)),
			width,
		)
	}
	return truncateValue(strings.Join(parts, " • "), width)
}

func (p *MediaPane) fullscreenFooter(point MediaPoint, width int) string {
	var parts []string
	if point.Caption != "" {
		parts = append(parts, point.Caption)
	}
	if point.Width > 0 && point.Height > 0 {
		parts = append(parts, fmt.Sprintf("%dx%d", point.Width, point.Height))
	}
	if point.Format != "" {
		parts = append(parts, strings.ToUpper(point.Format))
	}
	if x, ok := p.currentXForSeries(p.selectedKey()); ok {
		parts = append(parts, "X=_step "+formatMediaAxisValue(x))
	}
	if len(parts) == 0 {
		return ""
	}
	return truncateValue(strings.Join(parts, " • "), width)
}

func (p *MediaPane) effectiveGrid(width, height int) (rows, cols, slotW, slotH int) {
	cfgRows, cfgCols := 1, 1
	if p.gridConfig != nil {
		cfgRows, cfgCols = p.gridConfig()
	}
	cfgRows = max(cfgRows, 1)
	cfgCols = max(cfgCols, 1)

	cols = min(cfgCols, max(width/mediaTileMinWidth, 1))
	rows = min(cfgRows, max(height/mediaTileMinHeight, 1))
	cols = max(cols, 1)
	rows = max(rows, 1)
	if width > 0 {
		slotW = max(width/cols, 1)
	} else {
		slotW = 1
	}
	if height > 0 {
		slotH = max(height/rows, 1)
	} else {
		slotH = 1
	}
	return rows, cols, slotW, slotH
}

func hintOrDefault(hint, fallback string) string {
	if hint != "" {
		return hint
	}
	return fallback
}

func formatMediaAxisValue(x float64) string {
	if math.Trunc(x) == x {
		return fmt.Sprintf("%.0f", x)
	}
	return fmt.Sprintf("%.3f", x)
}

func renderMediaPlaceholder(width, height int, msg string) string {
	if width <= 0 || height <= 0 {
		return ""
	}
	msg = truncateValue(msg, width)
	return lipgloss.Place(width, height, lipgloss.Center, lipgloss.Center,
		mediaTilePlaceholderStyle.Render(msg))
}

type mediaRenderKey struct {
	path   string
	width  int
	height int
}

type mediaImageRenderer struct {
	mu       sync.RWMutex
	decoded  map[string]image.Image
	errors   map[string]string
	rendered map[mediaRenderKey]string
}

func newMediaImageRenderer() *mediaImageRenderer {
	return &mediaImageRenderer{
		decoded:  make(map[string]image.Image),
		errors:   make(map[string]string),
		rendered: make(map[mediaRenderKey]string),
	}
}

func (r *mediaImageRenderer) Render(path string, width, height int) string {
	if width <= 0 || height <= 0 {
		return ""
	}
	if path == "" {
		return renderMediaPlaceholder(width, height, "Missing image path")
	}

	key := mediaRenderKey{path: path, width: width, height: height}
	r.mu.RLock()
	if rendered, ok := r.rendered[key]; ok {
		r.mu.RUnlock()
		return rendered
	}
	img := r.decoded[path]
	errText := r.errors[path]
	r.mu.RUnlock()

	if img == nil && errText == "" {
		loaded, err := loadMediaImage(path)
		r.mu.Lock()
		if err != nil {
			errText = err.Error()
			r.errors[path] = errText
		} else {
			img = loaded
			r.decoded[path] = img
		}
		r.mu.Unlock()
	}

	if img == nil {
		return renderMediaPlaceholder(width, height, truncateValue(errText, width))
	}

	rendered := renderANSIImage(img, width, height)
	r.mu.Lock()
	r.rendered[key] = rendered
	r.mu.Unlock()
	return rendered
}

func loadMediaImage(path string) (image.Image, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open image: %w", err)
	}
	defer f.Close()

	img, _, err := image.Decode(f)
	if err != nil {
		return nil, fmt.Errorf("decode image: %w", err)
	}
	return img, nil
}

func renderANSIImage(img image.Image, width, height int) string {
	if width <= 0 || height <= 0 {
		return ""
	}

	bounds := img.Bounds()
	if bounds.Empty() {
		return renderMediaPlaceholder(width, height, "Empty image")
	}

	targetPixW := max(width, 1)
	targetPixH := max(height*2, 1)
	srcW := float64(bounds.Dx())
	srcH := float64(bounds.Dy())
	if srcW <= 0 || srcH <= 0 {
		return renderMediaPlaceholder(width, height, "Empty image")
	}

	scale := math.Min(float64(targetPixW)/srcW, float64(targetPixH)/srcH)
	drawW := max(int(math.Round(srcW*scale)), 1)
	drawH := max(int(math.Round(srcH*scale)), 1)
	xOff := max((targetPixW-drawW)/2, 0)
	yOff := max((targetPixH-drawH)/2, 0)

	sample := func(tx, ty int) (r, g, b uint8, ok bool) {
		if tx < xOff || tx >= xOff+drawW || ty < yOff || ty >= yOff+drawH {
			return 0, 0, 0, false
		}

		ux := float64(tx-xOff) + 0.5
		uy := float64(ty-yOff) + 0.5
		sx := bounds.Min.X + int(ux*srcW/float64(drawW))
		sy := bounds.Min.Y + int(uy*srcH/float64(drawH))
		if sx >= bounds.Max.X {
			sx = bounds.Max.X - 1
		}
		if sy >= bounds.Max.Y {
			sy = bounds.Max.Y - 1
		}

		r32, g32, b32, a32 := img.At(sx, sy).RGBA()
		if a32 == 0 {
			return 0, 0, 0, false
		}
		return uint8(r32 >> 8), uint8(g32 >> 8), uint8(b32 >> 8), true
	}

	var out strings.Builder
	for row := 0; row < height; row++ {
		upperY := row * 2
		lowerY := upperY + 1
		for col := 0; col < width; col++ {
			ur, ug, ub, upperOK := sample(col, upperY)
			lr, lg, lb, lowerOK := sample(col, lowerY)
			switch {
			case upperOK && lowerOK:
				fmt.Fprintf(
					&out,
					"\x1b[38;2;%d;%d;%dm\x1b[48;2;%d;%d;%dm▀",
					ur, ug, ub, lr, lg, lb,
				)
			case upperOK:
				fmt.Fprintf(&out, "\x1b[0m\x1b[38;2;%d;%d;%dm▀", ur, ug, ub)
			case lowerOK:
				fmt.Fprintf(&out, "\x1b[0m\x1b[38;2;%d;%d;%dm▄", lr, lg, lb)
			default:
				out.WriteString("\x1b[0m ")
			}
		}
		out.WriteString("\x1b[0m")
		if row+1 < height {
			out.WriteByte('\n')
		}
	}
	return out.String()
}
