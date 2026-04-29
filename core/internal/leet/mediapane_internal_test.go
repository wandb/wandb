package leet

import (
	"image"
	"image/color"
	"image/png"
	"os"
	"strings"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/NimbleMarkets/ntcharts/v2/picture"
	"github.com/stretchr/testify/require"
)

func testInternalMediaPane(t *testing.T) (*MediaPane, *MediaStore) {
	t.Helper()
	anim := NewAnimatedValue(true, 30)
	pane := NewMediaPane(anim, func() (int, int) { return 1, 1 })

	anim.Toggle()
	time.Sleep(AnimationDuration + 10*time.Millisecond)
	anim.Update(time.Now())

	store := NewMediaStore()
	pane.SetStore(store)
	return pane, store
}

func writeInternalTestImage(t *testing.T) string {
	t.Helper()
	path := t.TempDir() + "/img.png"
	img := image.NewRGBA(image.Rect(0, 0, 4, 4))
	for y := range 4 {
		for x := range 4 {
			img.Set(x, y, color.RGBA{R: uint8(64 * x), G: uint8(64 * y), B: 200, A: 255})
		}
	}

	f, err := os.Create(path)
	require.NoError(t, err)
	defer f.Close()

	require.NoError(t, png.Encode(f, img))
	return path
}

func testRGBAImage() image.Image {
	img := image.NewRGBA(image.Rect(0, 0, 4, 4))
	for y := range 4 {
		for x := range 4 {
			img.Set(x, y, color.RGBA{R: uint8(64 * x), G: uint8(64 * y), B: 200, A: 255})
		}
	}
	return img
}

func TestMediaPane_KittyModePreparesAndAppliesFrame(t *testing.T) {
	pane, store := testInternalMediaPane(t)
	path := writeInternalTestImage(t)
	store.ProcessHistory(HistoryMsg{
		Media: map[string][]MediaPoint{
			"s": {{X: 0, FilePath: path}},
		},
	})
	pane.SetStore(store)
	pane.SetActive(true)

	handled, toggleCmd := pane.HandleKey(tea.KeyPressMsg{Code: 'k', Text: "k"})
	require.True(t, handled)
	require.Nil(t, toggleCmd)

	view := pane.View(80, 20, "", "")
	require.NotEmpty(t, view)

	prepareCmd := pane.prepareRenderedMedia()
	require.NotNil(t, prepareCmd)
	frame := prepareCmd()
	kittyFrame, ok := frame.(picture.KittyFrameMsg)
	require.True(t, ok)
	rawCmd := pane.handleKittyFrame(kittyFrame)
	require.NotNil(t, rawCmd)
	require.IsType(t, tea.RawMsg{}, rawCmd())

	view = pane.View(80, 20, "", "")
	require.NotEmpty(t, view)
}

func TestMediaPane_HandleKeyEscapeOnlyConsumesFullscreen(t *testing.T) {
	pane, _ := testInternalMediaPane(t)
	pane.SetActive(true)

	handled, cmd := pane.HandleKey(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.False(t, handled)
	require.Nil(t, cmd)

	pane.ToggleFullscreen()
	handled, cmd = pane.HandleKey(tea.KeyPressMsg{Code: tea.KeyEsc})
	require.True(t, handled)
	require.Nil(t, cmd)
	require.False(t, pane.IsFullscreen())
}

func TestRenderPictureGlyphUpscalesToRequestedCells(t *testing.T) {
	img := testRGBAImage()

	scaled := scaleImageToFitCells(img, 20, 10)
	require.Equal(t, image.Rect(0, 0, 20, 20), scaled.Bounds())

	view := renderPictureGlyph(img, 20, 10)
	require.Equal(t, 10, lipgloss.Height(view))
	require.False(t, strings.HasSuffix(view, "\n"))
}

func TestMediaPane_RenderedMediaUsesActualViewDimensions(t *testing.T) {
	pane, store := testInternalMediaPane(t)
	path := writeInternalTestImage(t)
	store.ProcessHistory(HistoryMsg{
		Media: map[string][]MediaPoint{
			"s": {{X: 0, FilePath: path}},
		},
	})
	pane.SetStore(store)

	_ = pane.View(80, 20, "", "")
	require.Equal(t, []mediaRenderKey{{
		path:   path,
		width:  76,
		height: 14,
	}}, pane.renderedMedia())

	pane.ToggleFullscreen()
	_ = pane.View(80, 20, "", "")
	require.Equal(t, []mediaRenderKey{{
		path:   path,
		width:  78,
		height: 16,
	}}, pane.renderedMedia())
}

func TestMediaPane_ViewParksImagesOutsideCurrentPage(t *testing.T) {
	anim := NewAnimatedValue(true, 30)
	pane := NewMediaPane(anim, func() (int, int) { return 1, 1 })
	anim.Toggle()
	time.Sleep(AnimationDuration + 10*time.Millisecond)
	anim.Update(time.Now())

	store := NewMediaStore()
	path1 := writeInternalTestImage(t)
	path2 := writeInternalTestImage(t)
	store.ProcessHistory(HistoryMsg{
		Media: map[string][]MediaPoint{
			"a": {{X: 0, FilePath: path1}},
			"b": {{X: 0, FilePath: path2}},
		},
	})
	pane.SetStore(store)

	require.NotEmpty(t, pane.View(80, 20, "", ""))
	require.Contains(t, pane.renderer.decoded, path1)
	require.NotContains(t, pane.renderer.decoded, path2)

	pane.NavigatePage(1)
	require.NotEmpty(t, pane.View(80, 20, "", ""))
	require.NotContains(t, pane.renderer.decoded, path1)
	require.Contains(t, pane.renderer.decoded, path2)
}

func TestMediaImageRenderer_KittyToggleDoesNotPrepareCachedGlyphs(t *testing.T) {
	path := writeInternalTestImage(t)
	r := newMediaImageRenderer()

	glyphView := r.Render(path, 12, 6)
	require.NotEmpty(t, glyphView)
	require.Empty(t, r.pictures)

	require.Nil(t, r.ToggleMode())
	require.Empty(t, r.pictures)
}

func TestMediaImageRenderer_KittyPendingFallsBackToGlyph(t *testing.T) {
	path := writeInternalTestImage(t)
	r := newMediaImageRenderer()

	glyphView := r.Render(path, 12, 6)
	require.NotEmpty(t, glyphView)

	require.Nil(t, r.ToggleMode())
	pendingView := r.Render(path, 12, 6)
	require.Equal(t, glyphView, pendingView)
}

func TestMediaImageRenderer_PrepareVisiblePrunesStaleKittyImages(t *testing.T) {
	path1 := writeInternalTestImage(t)
	path2 := writeInternalTestImage(t)
	r := newMediaImageRenderer()
	require.Nil(t, r.ToggleMode())

	key1 := mediaRenderKey{path: path1, width: 10, height: 5}
	key2 := mediaRenderKey{path: path2, width: 12, height: 6}
	require.NotNil(t, r.PrepareVisible([]mediaRenderKey{key1}))
	require.Contains(t, r.pictures, key1)
	require.Contains(t, r.decoded, path1)

	require.NotNil(t, r.PrepareVisible([]mediaRenderKey{key2}))
	require.NotContains(t, r.pictures, key1)
	require.Contains(t, r.pictures, key2)
	require.NotContains(t, r.decoded, path1)
	require.Contains(t, r.decoded, path2)
}
