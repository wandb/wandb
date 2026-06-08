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
	"github.com/NimbleMarkets/ntcharts/v2/picture"
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

	// Kitty graphics image IDs live in a terminal-wide namespace. Start media
	// thumbnails well above ntcharts' default ID so independently-created
	// picture models do not overwrite each other.
	mediaKittyIDBase = 10_000
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

// MediaPane is a collapsible, animated pane that renders wandb.Image media.
type MediaPane struct {
	// animState controls the pane's animated height and visibility.
	animState *AnimatedValue
	// gridConfig returns the requested media grid shape from the surrounding UI.
	gridConfig func() (rows, cols int)
	// renderer owns image decoding plus ANSI/Kitty rendering caches.
	renderer *mediaImageRenderer

	// store provides the media series and points rendered by this pane.
	store *MediaStore

	// active allows the pane to consume media navigation keys.
	active bool
	// fullscreen expands the selected image inside the pane and keeps keys local.
	fullscreen bool

	// selectedIndex is the selected series index within store.SeriesKeys().
	selectedIndex int
	// pageRows/pageCols are the effective grid dimensions for the last viewport.
	pageRows int
	pageCols int

	// xIndices stores the selected X-value index for each media series.
	xIndices map[string]int
	// autoFollows records which series should stay pinned to their latest X value.
	autoFollows map[string]bool

	// nav tracks paged movement through the media grid.
	nav GridNavigator
	// keyMap dispatches normalized key names to handlers defined in keybindings.go.
	keyMap map[string]func(*MediaPane, tea.KeyPressMsg) tea.Cmd

	// renderMu guards renderKeys because Kitty image preparation runs async.
	renderMu sync.RWMutex
	// renderKeys are the currently visible media placements prepared for Kitty.
	renderKeys []mediaRenderKey
	// prepareCh wakes the Bubble Tea command that prepares visible Kitty images.
	prepareCh chan struct{}
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
		keyMap:      buildKeyMap(MediaPaneKeyBindings()),
		prepareCh:   make(chan struct{}, 1),
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

// Init starts the media pane's internal prepare loop.
func (p *MediaPane) Init() tea.Cmd {
	return batchCmds(p.waitForPrepare(), picture.QueryKittySupport())
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

func (p *MediaPane) togglePictureMode() tea.Cmd {
	return p.renderer.ToggleMode()
}

func (p *MediaPane) handlePictureMsg(msg tea.Msg) tea.Cmd {
	return p.renderer.Update(msg)
}

func (p *MediaPane) waitForPrepare() tea.Cmd {
	if p.prepareCh == nil {
		return nil
	}
	return func() tea.Msg {
		<-p.prepareCh
		return mediaPanePrepareMsg{}
	}
}

func (p *MediaPane) requestRenderedMediaPrepare() {
	if p.renderer.Mode() != picture.PictureKitty || p.prepareCh == nil {
		return
	}
	select {
	case p.prepareCh <- struct{}{}:
	default:
	}
}

func (p *MediaPane) handlePrepareMsg() tea.Cmd {
	return batchCmds(p.prepareRenderedMedia(), p.waitForPrepare())
}

func (p *MediaPane) prepareRenderedMedia() tea.Cmd {
	return p.renderer.PrepareVisible(p.renderedMedia())
}

// Park releases rendered media for images that are not currently visible.
func (p *MediaPane) Park() {
	p.setRenderedMedia(nil)
}

func (p *MediaPane) setRenderedMedia(keys []mediaRenderKey) {
	p.renderer.Park(keys)

	p.renderMu.Lock()
	changed := len(p.renderKeys) != len(keys)
	if !changed {
		for i := range keys {
			if p.renderKeys[i] != keys[i] {
				changed = true
				break
			}
		}
	}

	p.renderKeys = append(p.renderKeys[:0], keys...)
	p.renderMu.Unlock()

	if changed {
		p.requestRenderedMediaPrepare()
	}
}

func (p *MediaPane) renderedMedia() []mediaRenderKey {
	p.renderMu.RLock()
	defer p.renderMu.RUnlock()

	keys := make([]mediaRenderKey, len(p.renderKeys))
	copy(keys, p.renderKeys)
	return keys
}

type mediaPanePrepareMsg struct{}

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

// HandleKey handles media-pane-local navigation. It returns whether the key was
// consumed and any command needed to render media.
func (p *MediaPane) HandleKey(msg tea.KeyPressMsg) (bool, tea.Cmd) {
	if !p.active && !p.fullscreen {
		return false, nil
	}

	key := normalizeKey(msg.String())
	if key == "esc" {
		if !p.fullscreen {
			return false, nil
		}
	}

	handler, ok := p.keyMap[key]
	if !ok {
		return false, nil
	}
	return true, handler(p, msg)
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
		p.setRenderedMedia(nil)
		return ""
	}

	innerW := max(width-ContentPaddingCols, 0)
	innerH := max(height, 0)
	if innerW == 0 || innerH == 0 {
		p.setRenderedMedia(nil)
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
		p.setRenderedMedia(nil)
		placeholder := renderMediaPlaceholder(width, bodyHeight, hintOrDefault(hint, "No media."))
		return lipgloss.JoinVertical(lipgloss.Left, head, slider, placeholder)
	}

	title := p.renderTitle(key, width, true)
	footer := mediaTileFooterStyle.Width(width).Render(p.fullscreenFooter(point, width))
	imageHeight := max(bodyHeight-2, 1)
	p.setRenderedMedia([]mediaRenderKey{{
		path:   point.FilePath,
		width:  width,
		height: imageHeight,
	}})
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
	titleLabel := headerStyle.Render(title)

	keys := p.seriesKeys()
	itemsPerPage := p.itemsPerPage()
	p.nav.UpdateTotalPages(len(keys), itemsPerPage)
	navInfo := ""
	if len(keys) > 0 {
		startIdx, endIdx := p.nav.PageBounds(len(keys), itemsPerPage)
		navInfo = mediaPaneSliderStyle.Render(
			fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, len(keys)))
	}

	left := titleLabel
	if runLabel != "" {
		sep := " • "
		maxRunWidth := width - lipgloss.Width(titleLabel) - lipgloss.Width(navInfo) - len(sep)
		if maxRunWidth > 0 {
			left = lipgloss.JoinHorizontal(
				lipgloss.Left,
				titleLabel,
				mediaPaneSliderStyle.Render(sep+truncateValue(runLabel, maxRunWidth)),
			)
		}
	}

	fillerWidth := width - lipgloss.Width(left) - lipgloss.Width(navInfo)
	filler := strings.Repeat(" ", max(fillerWidth, 0))
	return lipgloss.JoinHorizontal(lipgloss.Left, left, filler, navInfo)
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
	for i := range barWidth {
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
		p.setRenderedMedia(nil)
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
	innerW, _, imageH, _ := mediaTileLayout(slotW, slotH)
	renderKeys := make([]mediaRenderKey, 0, endIdx-startIdx)
	for idx := startIdx; idx < endIdx; idx++ {
		key := keys[idx]
		x, hasX := p.currentXForSeries(key)
		point, ok := MediaPoint{}, false
		if hasX && p.store != nil {
			point, ok = p.store.ResolveAt(key, x)
		}
		if ok {
			renderKeys = append(renderKeys, mediaRenderKey{
				path:   point.FilePath,
				width:  innerW,
				height: imageH,
			})
		}
		cells = append(
			cells,
			p.renderTile(key, point, ok, showSelection && idx == p.selectedIndex, slotW, slotH))

	}
	p.setRenderedMedia(renderKeys)
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
	innerW, innerH, imageH, footerLines := mediaTileLayout(slotW, slotH)

	borderStyle := mediaTileBorderStyle
	if selected {
		borderStyle = mediaTileSelectedBorderStyle
	}

	title := p.renderTitle(key, innerW, selected)

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

func (p *MediaPane) renderTitle(key string, width int, selected bool) string {
	if width <= 0 {
		return ""
	}

	titleStyle := mediaTileTitleStyle
	if selected {
		titleStyle = mediaTileSelectedTitleStyle
	}

	suffix := p.rendererModeTitleSuffix()
	suffixWidth := lipgloss.Width(suffix)
	if width <= suffixWidth+1 {
		return titleStyle.Width(width).Render(truncateValue(key, width))
	}

	label := titleStyle.Render(truncateValue(key, width-suffixWidth))
	suffixLabel := navInfoStyle.Render(suffix)
	line := label + suffixLabel
	if padding := width - lipgloss.Width(line); padding > 0 {
		line += strings.Repeat(" ", padding)
	}
	return line
}

func (p *MediaPane) rendererModeTitleSuffix() string {
	if p.renderer.Mode() == picture.PictureKitty {
		return " [full-res]"
	}
	return " [ansi]"
}

func mediaTileLayout(slotW, slotH int) (innerW, innerH, imageH, footerLines int) {
	innerW = max(slotW-mediaTileBorderLines, 1)
	innerH = max(slotH-mediaTileBorderLines, 1)
	if innerH >= mediaTileTitleLines+mediaTileFooterLines+2 {
		footerLines = mediaTileFooterLines
	}
	imageH = max(innerH-mediaTileTitleLines-footerLines, 1)
	return innerW, innerH, imageH, footerLines
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

const mediaErrorRetryAfter = time.Second

type mediaRenderError struct {
	text string
	at   time.Time
}

type mediaPicture struct {
	model picture.Model
	img   image.Image
}

type mediaImageRenderer struct {
	mu   sync.RWMutex
	mode picture.PictureMode
	// Kitty image IDs share the terminal namespace. Allocate one per visible
	// placement so multiple thumbnails do not overwrite each other.
	nextKittyID int
	decoded     map[string]image.Image
	errors      map[string]mediaRenderError
	rendered    map[mediaRenderKey]string
	pictures    map[mediaRenderKey]*mediaPicture
}

func newMediaImageRenderer() *mediaImageRenderer {
	return &mediaImageRenderer{
		nextKittyID: mediaKittyIDBase,
		decoded:     make(map[string]image.Image),
		errors:      make(map[string]mediaRenderError),
		rendered:    make(map[mediaRenderKey]string),
		pictures:    make(map[mediaRenderKey]*mediaPicture),
	}
}

func (r *mediaImageRenderer) Mode() picture.PictureMode {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.mode
}

func (r *mediaImageRenderer) ToggleMode() tea.Cmd {
	r.mu.Lock()
	defer r.mu.Unlock()

	if r.mode == picture.PictureGlyph {
		if !ensureKittyGraphicsEnabled() {
			return nil
		}
		r.mode = picture.PictureKitty
		cmds := make([]tea.Cmd, 0, len(r.pictures))
		for _, pic := range r.pictures {
			if pic.model.Mode() == picture.PictureKitty {
				continue
			}
			if cmd := pic.model.Toggle(); cmd != nil {
				cmds = append(cmds, cmd)
			}
		}
		return batchCmds(cmds...)
	}

	r.mode = picture.PictureGlyph
	cmds := make([]tea.Cmd, 0, len(r.pictures))
	for key, pic := range r.pictures {
		var cmd tea.Cmd
		if pic.model.Mode() == picture.PictureKitty {
			cmd = pic.model.Toggle()
		} else {
			cmd = pic.model.SetImage(nil)
		}
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
		delete(r.pictures, key)
	}
	return batchCmds(cmds...)
}

func ensureKittyGraphicsEnabled() bool {
	if picture.KittySupported() == picture.KittyCapabilitySupported {
		return true
	}
	if !terminalSignalsKittyGraphics() {
		return false
	}
	picture.ForceKittyCapability(picture.KittyCapabilitySupported)
	return true
}

func terminalSignalsKittyGraphics() bool {
	if os.Getenv("KITTY_WINDOW_ID") != "" ||
		os.Getenv("KITTY_INSTALLATION_DIR") != "" ||
		os.Getenv("WEZTERM_EXECUTABLE") != "" ||
		os.Getenv("WEZTERM_PANE") != "" ||
		os.Getenv("GHOSTTY_BIN_DIR") != "" ||
		os.Getenv("GHOSTTY_RESOURCES_DIR") != "" {
		return true
	}

	switch strings.ToLower(os.Getenv("TERM_PROGRAM")) {
	case "ghostty", "iterm.app", "kitty", "wezterm":
		return true
	}

	switch strings.ToLower(os.Getenv("TERM")) {
	case "xterm-ghostty", "xterm-kitty":
		return true
	}
	return false
}

func (r *mediaImageRenderer) Update(msg tea.Msg) tea.Cmd {
	r.mu.Lock()
	defer r.mu.Unlock()

	cmds := make([]tea.Cmd, 0, 1)
	for _, pic := range r.pictures {
		if cmd := pic.model.Update(msg); cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	return batchCmds(cmds...)
}

func (r *mediaImageRenderer) PrepareVisible(keys []mediaRenderKey) tea.Cmd {
	r.Park(keys)

	r.mu.RLock()
	mode := r.mode
	r.mu.RUnlock()
	if mode != picture.PictureKitty {
		return nil
	}

	visible := make(map[mediaRenderKey]bool, len(keys))
	cmds := make([]tea.Cmd, 0, len(keys))
	for _, key := range keys {
		if key.path == "" || key.width <= 0 || key.height <= 0 {
			continue
		}
		visible[key] = true

		img, _ := r.image(key.path)
		if img == nil {
			continue
		}

		r.mu.Lock()
		if cmd := r.preparePictureLocked(key, img); cmd != nil {
			cmds = append(cmds, cmd)
		}
		r.mu.Unlock()
	}

	r.mu.Lock()
	for key, pic := range r.pictures {
		if visible[key] {
			continue
		}
		if cmd := pic.model.SetImage(nil); cmd != nil {
			cmds = append(cmds, cmd)
		}
		delete(r.pictures, key)
	}
	r.mu.Unlock()

	return batchCmds(cmds...)
}

func (r *mediaImageRenderer) Park(keys []mediaRenderKey) {
	visibleKeys := make(map[mediaRenderKey]struct{}, len(keys))
	visiblePaths := make(map[string]struct{}, len(keys))
	for _, key := range keys {
		if key.path == "" || key.width <= 0 || key.height <= 0 {
			continue
		}
		visibleKeys[key] = struct{}{}
		visiblePaths[key.path] = struct{}{}
	}

	r.mu.Lock()
	defer r.mu.Unlock()

	for path := range r.decoded {
		if _, ok := visiblePaths[path]; !ok {
			delete(r.decoded, path)
		}
	}
	for path := range r.errors {
		if _, ok := visiblePaths[path]; !ok {
			delete(r.errors, path)
		}
	}
	for key := range r.rendered {
		if _, ok := visibleKeys[key]; !ok {
			delete(r.rendered, key)
		}
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
	if r.mode == picture.PictureKitty {
		if pic := r.pictures[key]; pic != nil {
			if view := pic.model.View().Content; view != "" {
				r.mu.RUnlock()
				return view
			}
		}
		r.mu.RUnlock()
		return r.renderGlyph(path, width, height)
	}

	if rendered, ok := r.rendered[key]; ok {
		r.mu.RUnlock()
		return rendered
	}
	r.mu.RUnlock()

	return r.renderGlyph(path, width, height)
}

func (r *mediaImageRenderer) image(path string) (image.Image, mediaRenderError) {
	r.mu.RLock()
	img := r.decoded[path]
	errEntry, hasErr := r.errors[path]
	r.mu.RUnlock()

	if img != nil {
		return img, mediaRenderError{}
	}
	if hasErr && time.Since(errEntry.at) < mediaErrorRetryAfter {
		return nil, errEntry
	}

	loaded, err := loadMediaImage(path)
	r.mu.Lock()
	defer r.mu.Unlock()
	if err != nil {
		errEntry = mediaRenderError{text: err.Error(), at: time.Now()}
		r.errors[path] = errEntry
		return nil, errEntry
	}
	r.decoded[path] = loaded
	delete(r.errors, path)
	return loaded, mediaRenderError{}
}

func (r *mediaImageRenderer) renderGlyph(path string, width, height int) string {
	img, errEntry := r.image(path)
	if img == nil {
		return renderMediaPlaceholder(width, height, truncateValue(errEntry.text, width))
	}

	key := mediaRenderKey{path: path, width: width, height: height}
	rendered := renderPictureGlyph(img, width, height)
	r.mu.Lock()
	r.rendered[key] = rendered
	r.mu.Unlock()
	return rendered
}

func (r *mediaImageRenderer) preparePictureLocked(key mediaRenderKey, img image.Image) tea.Cmd {
	var cmds []tea.Cmd

	pic := r.pictures[key]
	if pic == nil {
		model := picture.NewWithConfig(picture.Config{
			KittyID: r.nextKittyID,
		})
		r.nextKittyID++
		pic = &mediaPicture{model: model}
		r.pictures[key] = pic
		if r.mode == picture.PictureKitty {
			if cmd := pic.model.Toggle(); cmd != nil {
				cmds = append(cmds, cmd)
			}
		}
	}

	if cmd := pic.model.SetSize(key.width, key.height); cmd != nil {
		cmds = append(cmds, cmd)
	}
	if pic.img != img {
		pic.img = img
		if cmd := pic.model.SetImage(img); cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	return batchCmds(cmds...)
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

func renderPictureGlyph(img image.Image, width, height int) string {
	if width <= 0 || height <= 0 {
		return ""
	}
	if img.Bounds().Empty() {
		return renderMediaPlaceholder(width, height, "Empty image")
	}

	model := picture.New()
	model.SetSize(width, height)
	model.SetImage(img)
	view := model.View().Content
	if view == "" {
		return renderMediaPlaceholder(width, height, "Empty image")
	}
	return view
}
