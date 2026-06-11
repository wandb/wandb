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
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/NimbleMarkets/ntcharts/v2/picture"
	uv "github.com/charmbracelet/ultraviolet"
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

	// Kitty graphics image IDs live in a terminal-wide namespace. Media
	// thumbnail IDs are allocated from a process-wide counter starting well
	// above ntcharts' default ID so picture models never overwrite each
	// other, including across the workspace and single-run media panes.
	mediaKittyIDBase = 10_000
)

// mediaKittyIDCounter backs nextMediaKittyID.
var mediaKittyIDCounter atomic.Int64

func nextMediaKittyID() int {
	return mediaKittyIDBase + int(mediaKittyIDCounter.Add(1))
}

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
	// linkedScrub makes the scrub keys move all media series in sync by
	// driving a single shared cursor over the union X timeline.
	linkedScrub bool
	// linkedXIndex is the shared cursor's index into store.XValues().
	linkedXIndex int
	// linkedAutoFollow keeps the shared cursor pinned to the latest X value.
	linkedAutoFollow bool

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

	// renderKeys are the currently visible media placements, recorded at
	// render time and consumed by the Kitty prepare loop.
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

// Init starts the media pane's internal prepare loop and asks the terminal
// for what Kitty rendering needs: its cell pixel size (so images are encoded
// at the display's true resolution) and Kitty graphics support.
func (p *MediaPane) Init() tea.Cmd {
	return batchCmds(
		p.waitForPrepare(),
		picture.RequestCellSize(),
		picture.QueryKittySupport(),
	)
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

func (p *MediaPane) handlePictureMsg(msg tea.Msg) tea.Cmd {
	return p.renderer.Update(msg)
}

func (p *MediaPane) waitForPrepare() tea.Cmd {
	return func() tea.Msg {
		<-p.prepareCh
		return mediaPanePrepareMsg{pane: p}
	}
}

func (p *MediaPane) requestRenderedMediaPrepare() {
	if p.renderer.Mode() != picture.PictureKitty {
		return
	}
	select {
	case p.prepareCh <- struct{}{}:
	default:
	}
}

func (p *MediaPane) handlePrepareMsg() tea.Cmd {
	return batchCmds(p.renderer.PrepareVisible(p.renderKeys), p.waitForPrepare())
}

// Park releases rendered media for images that are not currently visible.
func (p *MediaPane) Park() {
	p.setRenderedMedia(nil)
}

func (p *MediaPane) setRenderedMedia(keys []mediaRenderKey) {
	p.renderer.Park(keys)

	if slices.Equal(p.renderKeys, keys) {
		return
	}
	p.renderKeys = append(p.renderKeys[:0], keys...)
	p.requestRenderedMediaPrepare()
}

// mediaPanePrepareMsg wakes the Kitty prepare loop. It carries the owning
// pane: the workspace and single-run media panes both see every message, and
// each must act on (and re-arm) only its own prepare loop.
type mediaPanePrepareMsg struct {
	pane *MediaPane
}

// MediaPaneViewState captures the navigable state of a MediaPane so it can
// be saved and restored across Run view transitions.
type MediaPaneViewState struct {
	SelectedIndex int
	XIndices      map[string]int
	AutoFollows   map[string]bool
	LinkedScrub   bool
	LinkedXIndex  int
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
		LinkedScrub:   p.linkedScrub,
		LinkedXIndex:  p.linkedXIndex,
	}
}

func (p *MediaPane) RestoreViewState(s MediaPaneViewState) {
	p.selectedIndex = s.SelectedIndex
	clear(p.xIndices)
	maps.Copy(p.xIndices, s.XIndices)
	clear(p.autoFollows)
	maps.Copy(p.autoFollows, s.AutoFollows)
	p.linkedScrub = s.LinkedScrub
	p.linkedXIndex = s.LinkedXIndex
	xs := p.unionXValues()
	p.linkedAutoFollow = len(xs) > 0 && s.LinkedXIndex >= len(xs)-1
	p.fullscreen = false
	p.syncState()
}

func (p *MediaPane) ResetViewState() {
	p.selectedIndex = 0
	clear(p.xIndices)
	clear(p.autoFollows)
	p.linkedScrub = false
	p.linkedXIndex = 0
	p.linkedAutoFollow = false
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

	// Maintain the shared linked cursor against the union timeline.
	switch xs := p.unionXValues(); {
	case len(xs) == 0:
		p.linkedXIndex = 0
	case p.linkedAutoFollow:
		p.linkedXIndex = len(xs) - 1
	default:
		p.linkedXIndex = clamp(p.linkedXIndex, 0, len(xs)-1)
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
	x, ok := p.scrubX(key)
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

	// Show the resolved sample's step; fall back to the scrub position when
	// the series has no sample there yet.
	x, hasX := p.scrubX(key)
	if ok {
		x, hasX = point.X, true
	}
	parts := []string{fmt.Sprintf("Media: %s", key)}
	if hasX {
		parts = append(parts, fmt.Sprintf("X=_step %s", formatMediaAxisValue(x)))
	}
	if ok && point.Caption != "" {
		parts = append(parts, truncateValue(point.Caption, 48))
	}
	if p.linkedScrub {
		parts = append(parts, "sync")
	}
	if p.fullscreen {
		parts = append(parts, "fullscreen")
	}
	return strings.Join(parts, " • ")
}

// HandleKey handles media-pane-local navigation. It returns whether the key
// was consumed and any command needed to render media.
//
//gocyclo:ignore
func (p *MediaPane) HandleKey(msg tea.KeyPressMsg) (bool, tea.Cmd) {
	if !p.active && !p.fullscreen {
		return false, nil
	}

	switch normalizeKey(msg.String()) {
	case "enter":
		if p.HasData() {
			p.ToggleFullscreen()
		}
		return true, nil
	case "esc":
		if p.fullscreen {
			p.ExitFullscreen()
			return true, nil
		}
		return false, nil
	case "k":
		var cmd tea.Cmd
		if p.HasData() {
			cmd = p.renderer.ToggleMode()
			p.requestRenderedMediaPrepare()
		}
		return true, cmd
	case "l":
		if p.HasData() {
			p.toggleLinkedScrub()
		}
		return true, nil
	case "left":
		p.Scrub(-1)
		return true, nil
	case "right":
		p.Scrub(1)
		return true, nil
	case "up":
		p.Scrub(-10)
		return true, nil
	case "down":
		p.Scrub(10)
		return true, nil
	case "home":
		p.ScrubToStart()
		return true, nil
	case "end":
		p.ScrubToEnd()
		return true, nil
	case "a":
		p.MoveSelection(-1, 0)
		return true, nil
	case "d":
		p.MoveSelection(1, 0)
		return true, nil
	case "w":
		p.MoveSelection(0, -1)
		return true, nil
	case "s":
		p.MoveSelection(0, 1)
		return true, nil
	case "pgup":
		p.NavigatePage(-1)
		return true, nil
	case "pgdown":
		p.NavigatePage(1)
		return true, nil
	default:
		return false, nil
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

// Scrub moves the scrub position by delta samples: the shared cursor over
// the union timeline when scrubbing is linked, the selected series otherwise.
func (p *MediaPane) Scrub(delta int) {
	if p.linkedScrub {
		xs := p.unionXValues()
		if len(xs) == 0 {
			return
		}
		p.linkedXIndex = clamp(p.linkedXIndex+delta, 0, len(xs)-1)
		p.linkedAutoFollow = p.linkedXIndex == len(xs)-1
		return
	}

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
	if p.linkedScrub {
		p.linkedXIndex = 0
		p.linkedAutoFollow = false
		return
	}

	key := p.selectedKey()
	if key == "" {
		return
	}
	p.xIndices[key] = 0
	p.autoFollows[key] = false
}

func (p *MediaPane) ScrubToEnd() {
	if p.linkedScrub {
		if xs := p.unionXValues(); len(xs) > 0 {
			p.linkedXIndex = len(xs) - 1
		}
		p.linkedAutoFollow = true
		return
	}

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

// toggleLinkedScrub switches between linked and per-series scrubbing.
//
// Linking starts the shared cursor at the most advanced series position so
// the view doesn't jump; unlinking writes the cursor back into each series'
// own scrub position so tiles keep showing the same samples.
func (p *MediaPane) toggleLinkedScrub() {
	if p.linkedScrub {
		if x, ok := p.linkedX(); ok {
			for _, key := range p.seriesKeys() {
				p.alignSeriesTo(key, x)
			}
		}
		p.linkedScrub = false
		return
	}

	union := p.unionXValues()
	cursor := 0
	for _, key := range p.seriesKeys() {
		if x, ok := p.currentXForSeries(key); ok {
			if idx, found := slices.BinarySearch(union, x); found {
				cursor = max(cursor, idx)
			}
		}
	}
	p.linkedXIndex = cursor
	p.linkedAutoFollow = cursor == len(union)-1
	p.linkedScrub = true
}

// alignSeriesTo moves a series' scrub position to its latest sample at or
// before x, or to its first sample when none exists yet.
func (p *MediaPane) alignSeriesTo(key string, x float64) {
	xs := p.seriesXValues(key)
	if len(xs) == 0 {
		return
	}
	idx, found := slices.BinarySearch(xs, x)
	if !found {
		idx = max(idx-1, 0)
	}
	p.xIndices[key] = idx
	p.autoFollows[key] = idx == len(xs)-1
}

func (p *MediaPane) unionXValues() []float64 {
	if p.store == nil {
		return nil
	}
	return p.store.XValues()
}

// linkedX returns the shared cursor's X value on the union timeline.
func (p *MediaPane) linkedX() (float64, bool) {
	xs := p.unionXValues()
	if len(xs) == 0 {
		return 0, false
	}
	return xs[clamp(p.linkedXIndex, 0, len(xs)-1)], true
}

// scrubX returns the X position a series' tile resolves against: the shared
// cursor when scrubbing is linked, the series' own position otherwise.
func (p *MediaPane) scrubX(key string) (float64, bool) {
	if p.linkedScrub {
		return p.linkedX()
	}
	return p.currentXForSeries(key)
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

	keys := p.seriesKeys()
	itemsPerPage := p.itemsPerPage()
	p.nav.UpdateTotalPages(len(keys), itemsPerPage)
	navInfo := ""
	if len(keys) > 0 {
		startIdx, endIdx := p.nav.PageBounds(len(keys), itemsPerPage)
		navInfo = mediaPaneSliderStyle.Render(
			fmt.Sprintf(" [%d-%d of %d]", startIdx+1, endIdx, len(keys)))
	}

	titleLabel := headerStyle.Render(title)
	left := titleLabel
	if runLabel != "" {
		sep := " • "
		maxRunWidth := width -
			lipgloss.Width(titleLabel) - lipgloss.Width(navInfo) - lipgloss.Width(sep)
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
	xs, idx := p.sliderPosition()
	if len(xs) == 0 {
		return mediaPaneSliderStyle.Width(width).Render("X: _step —")
	}

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
	if p.linkedScrub {
		text += "  [sync]"
	}
	return mediaPaneSliderStyle.Width(width).Render(truncateValue(text, width))
}

// sliderPosition returns the timeline and cursor index the slider displays:
// the union timeline when scrubbing is linked, the selected series otherwise.
func (p *MediaPane) sliderPosition() ([]float64, int) {
	if p.linkedScrub {
		xs := p.unionXValues()
		return xs, clamp(p.linkedXIndex, 0, max(len(xs)-1, 0))
	}
	key := p.selectedKey()
	if key == "" {
		return nil, 0
	}
	xs := p.seriesXValues(key)
	return xs, clamp(p.xIndices[key], 0, max(len(xs)-1, 0))
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
		x, hasX := p.scrubX(key)
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
	// Show the resolved sample's step; fall back to the scrub position when
	// the series has no sample there yet.
	x, hasX := p.scrubX(key)
	if ok {
		x, hasX = point.X, true
	}
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
	parts = append(parts, "X=_step "+formatMediaAxisValue(point.X))
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
	// cellPixelW/H are the terminal's cell pixel dimensions (its reply to
	// picture.RequestCellSize), used so Kitty images are encoded at the
	// display's true resolution. Zero until the reply arrives; the picture
	// package's defaults apply then.
	cellPixelW int
	cellPixelH int
	decoded    map[string]image.Image
	errors     map[string]mediaRenderError
	rendered   map[mediaRenderKey]string
	pictures   map[mediaRenderKey]*mediaPicture
}

func newMediaImageRenderer() *mediaImageRenderer {
	return &mediaImageRenderer{
		decoded:  make(map[string]image.Image),
		errors:   make(map[string]mediaRenderError),
		rendered: make(map[mediaRenderKey]string),
		pictures: make(map[mediaRenderKey]*mediaPicture),
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
		// Pictures are created lazily by PrepareVisible once the mode is
		// Kitty; in Glyph mode there are none to update.
		r.mode = picture.PictureKitty
		return nil
	}

	r.mode = picture.PictureGlyph
	cmds := make([]tea.Cmd, 0, len(r.pictures))
	for _, pic := range r.pictures {
		// Every model in pictures is in Kitty mode; Toggle emits the Kitty
		// delete sequence that frees the on-terminal image.
		if cmd := pic.model.Toggle(); cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	clear(r.pictures)
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

	// Remember the terminal's cell pixel size for pictures created later;
	// existing pictures pick it up through the forwarding loop below.
	if ev, ok := msg.(uv.CellSizeEvent); ok {
		r.cellPixelW, r.cellPixelH = ev.Width, ev.Height
	}

	cmds := make([]tea.Cmd, 0, 1)
	for _, pic := range r.pictures {
		if cmd := pic.model.Update(msg); cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	return batchCmds(cmds...)
}

func (r *mediaImageRenderer) PrepareVisible(keys []mediaRenderKey) tea.Cmd {
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
		pic := r.pictures[key]
		r.mu.RUnlock()
		// View mutates the model's render cache, so call it outside the lock.
		if pic != nil {
			if view := pic.model.View().Content; view != "" {
				return view
			}
		}
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
			KittyID:         nextMediaKittyID(),
			CellPixelWidth:  r.cellPixelW,
			CellPixelHeight: r.cellPixelH,
		})
		pic = &mediaPicture{model: model}
		r.pictures[key] = pic
		// New models start in Glyph mode and this only runs in Kitty mode,
		// so switch them over.
		if cmd := pic.model.Toggle(); cmd != nil {
			cmds = append(cmds, cmd)
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
