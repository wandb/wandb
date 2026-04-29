package leet_test

import (
	"image"
	"image/color"
	"image/png"
	"os"
	"strings"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

// --- helpers ---

func testMediaPane(t *testing.T) (*leet.MediaPane, *leet.MediaStore) {
	t.Helper()
	return testMediaPaneWithGrid(t, 2, 3)
}

func testMediaPaneWithGrid(t *testing.T, rows, cols int) (*leet.MediaPane, *leet.MediaStore) {
	t.Helper()
	anim := leet.NewAnimatedValue(true, 30)
	pane := leet.NewMediaPane(anim, func() (int, int) { return rows, cols })

	// Instantly expand so Height() > 0.
	anim.Toggle() // start → expanding
	time.Sleep(leet.AnimationDuration + 10*time.Millisecond)
	anim.Update(time.Now())

	store := leet.NewMediaStore()
	pane.SetStore(store)
	return pane, store
}

func mediaKeyMsg(t *testing.T, intent leet.MediaKeyIntent) tea.KeyPressMsg {
	t.Helper()
	keys := leet.MediaKeysFor(intent)
	require.NotEmpty(t, keys, "intent %d should have keys", intent)
	return mediaBindingMsg(t, keys[0])
}

func setKittyGraphicsEnv(t *testing.T, supported bool) {
	t.Helper()
	for _, key := range []string{
		"KITTY_WINDOW_ID",
		"WEZTERM_EXECUTABLE",
		"WEZTERM_PANE",
		"GHOSTTY_BIN_DIR",
		"GHOSTTY_RESOURCES_DIR",
		"TERM_PROGRAM",
	} {
		t.Setenv(key, "")
	}
	if supported {
		t.Setenv("TERM", "xterm-kitty")
	} else {
		t.Setenv("TERM", "xterm-256color")
	}
}

func feedImages(store *leet.MediaStore, key string, steps ...float64) {
	for _, step := range steps {
		store.ProcessHistory(leet.HistoryMsg{
			Media: map[string][]leet.MediaPoint{
				key: {{X: step, FilePath: "/img.png", Caption: "c"}},
			},
		})
	}
}

func writeTestImage(t *testing.T) string {
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

func writeBandTestImage(t *testing.T) string {
	t.Helper()
	path := t.TempDir() + "/bands.png"
	img := image.NewRGBA(image.Rect(0, 0, 16, 16))
	for y := range 16 {
		c := color.RGBA{R: 32, G: 32, B: 32, A: 255}
		switch {
		case y < 2:
			c = color.RGBA{R: 255, A: 255}
		case y >= 14:
			c = color.RGBA{B: 255, A: 255}
		}
		for x := range 16 {
			img.Set(x, y, c)
		}
	}
	img.Set(0, 2, color.RGBA{})
	img.Set(0, 3, color.RGBA{})
	img.Set(1, 4, color.RGBA{})
	img.Set(2, 7, color.RGBA{})

	f, err := os.Create(path)
	require.NoError(t, err)
	defer f.Close()

	require.NoError(t, png.Encode(f, img))
	return path
}

// --- MediaStore tests ---

func TestMediaStore_Empty(t *testing.T) {
	store := leet.NewMediaStore()
	require.True(t, store.Empty())
	require.Nil(t, store.SeriesKeys())
	require.Nil(t, store.XValues())
}

func TestMediaStore_SeriesKeysSorted(t *testing.T) {
	store := leet.NewMediaStore()
	feedImages(store, "zeta", 1)
	feedImages(store, "alpha", 1)
	feedImages(store, "mu", 1)

	require.Equal(t, []string{"alpha", "mu", "zeta"}, store.SeriesKeys())
	require.False(t, store.Empty())
}

func TestMediaStore_XValuesUnionAcrossSeries(t *testing.T) {
	store := leet.NewMediaStore()
	feedImages(store, "a", 1, 3, 5)
	feedImages(store, "b", 2, 3, 4)

	require.Equal(t, []float64{1, 2, 3, 4, 5}, store.XValues())
}

func TestMediaStore_SeriesXValues(t *testing.T) {
	store := leet.NewMediaStore()
	feedImages(store, "a", 3, 1, 2)

	require.Equal(t, []float64{1, 2, 3}, store.SeriesXValues("a"))
	require.Nil(t, store.SeriesXValues("nonexistent"))
}

func TestMediaStore_ResolveAt_EmptySeries(t *testing.T) {
	store := leet.NewMediaStore()
	_, ok := store.ResolveAt("a", 1)
	require.False(t, ok)
}

func TestMediaStore_ProcessHistory_EmptyMsg(t *testing.T) {
	store := leet.NewMediaStore()
	require.False(t, store.ProcessHistory(leet.HistoryMsg{}))
	require.True(t, store.Empty())
}

func TestMediaStore_ProcessHistory_EmptyKey(t *testing.T) {
	store := leet.NewMediaStore()
	changed := store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"": {{X: 1, FilePath: "/img.png"}},
		},
	})
	require.False(t, changed)
	require.True(t, store.Empty())
}

func TestMediaStore_ProcessHistory_DuplicateNoChange(t *testing.T) {
	store := leet.NewMediaStore()
	point := leet.MediaPoint{X: 1, FilePath: "/img.png", Caption: "c"}
	store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{"a": {point}},
	})
	// Same exact point again → no change.
	changed := store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{"a": {point}},
	})
	require.False(t, changed)
}

// --- MediaPane scrubbing ---

func TestMediaPane_Scrub(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "s", 0, 1, 2, 3, 4)
	pane.SetStore(store)

	// Auto-follow puts us at the last step.
	require.Contains(t, pane.StatusLabel(), "X=_step 4")

	pane.Scrub(-2)
	require.Contains(t, pane.StatusLabel(), "X=_step 2")

	// Scrub past the beginning clamps to 0.
	pane.Scrub(-100)
	require.Contains(t, pane.StatusLabel(), "X=_step 0")

	pane.ScrubToEnd()
	require.Contains(t, pane.StatusLabel(), "X=_step 4")

	pane.ScrubToStart()
	require.Contains(t, pane.StatusLabel(), "X=_step 0")
}

func TestMediaPane_Scrub_EmptyStore(t *testing.T) {
	pane, _ := testMediaPane(t)
	// Should not panic on empty store.
	pane.Scrub(1)
	pane.ScrubToStart()
	pane.ScrubToEnd()
}

func TestMediaPane_HandleKeyScrubBindings(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "s", 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
	pane.SetStore(store)
	pane.SetActive(true)
	pane.ScrubToStart()

	handled, cmd := pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyScrubForward))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "X=_step 1")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyScrubJumpForward))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "X=_step 11")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyScrubBackward))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "X=_step 10")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyScrubJumpBackward))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "X=_step 0")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyScrubEnd))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "X=_step 11")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyScrubStart))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "X=_step 0")
}

// --- MediaPane view state save/restore ---

func TestMediaPane_ViewState_SaveRestore(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "a", 0, 1, 2, 3)
	feedImages(store, "b", 0, 1, 2)
	pane.SetStore(store)

	// Move selection to "b" and scrub to step 1.
	pane.MoveSelection(1, 0)
	pane.ScrubToStart()
	pane.Scrub(1)

	state := pane.SaveViewState()

	// Reset destroys position.
	pane.ResetViewState()
	require.Contains(t, pane.StatusLabel(), "X=_step 3")

	// Restore brings it back.
	pane.RestoreViewState(state)
	require.Contains(t, pane.StatusLabel(), "X=_step 1")
}

func TestMediaPane_ViewState_Reset(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "a", 0, 1, 2)
	pane.SetStore(store)

	pane.ScrubToStart()
	require.Contains(t, pane.StatusLabel(), "X=_step 0")

	pane.ResetViewState()
	// After reset, auto-follow → last step.
	require.Contains(t, pane.StatusLabel(), "X=_step 2")
}

// --- MediaPane fullscreen ---

func TestMediaPane_Fullscreen(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "s", 0)
	pane.SetStore(store)

	require.False(t, pane.IsFullscreen())
	pane.ToggleFullscreen()
	require.True(t, pane.IsFullscreen())
	require.True(t, pane.Active(), "fullscreen should activate pane")

	pane.ExitFullscreen()
	require.False(t, pane.IsFullscreen())
}

func TestMediaPane_HandleKeyToggleFullscreenBinding(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "s", 0)
	pane.SetStore(store)
	pane.SetActive(true)

	handled, cmd := pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyToggleFullscreen))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.True(t, pane.IsFullscreen())

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyToggleFullscreen))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.False(t, pane.IsFullscreen())
}

func TestMediaPane_EscapeOnlyConsumesFullscreen(t *testing.T) {
	pane, _ := testMediaPane(t)
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

func TestMediaPane_ViewFullscreenRendersCurrentImage(t *testing.T) {
	pane, store := testMediaPaneWithGrid(t, 1, 1)
	path := writeTestImage(t)
	store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"s": {{X: 0, FilePath: path}},
		},
	})
	pane.SetStore(store)
	pane.ToggleFullscreen()

	view := pane.View(80, 20, "run", "")
	require.Contains(t, view, "Media [fullscreen]")
	require.Contains(t, view, "[ansi]")
	require.Contains(t, view, "X=_step 0")
	require.NotContains(t, view, "No media.")
}

// --- MediaPane navigation ---

func TestMediaPane_MoveSelection(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "a", 0)
	feedImages(store, "b", 0)
	feedImages(store, "c", 0)
	pane.SetStore(store)

	// Trigger grid layout so MoveSelection knows the page geometry.
	_ = pane.View(120, 20, "", "")

	// Start on "a".
	require.Contains(t, pane.StatusLabel(), "Media: a")

	pane.MoveSelection(1, 0)
	require.Contains(t, pane.StatusLabel(), "Media: b")

	pane.MoveSelection(1, 0)
	require.Contains(t, pane.StatusLabel(), "Media: c")

	// Clamped at boundary.
	pane.MoveSelection(1, 0)
	require.Contains(t, pane.StatusLabel(), "Media: c")

	pane.MoveSelection(-1, 0)
	require.Contains(t, pane.StatusLabel(), "Media: b")
}

func TestMediaPane_HandleKeySelectionAndPageBindings(t *testing.T) {
	pane, store := testMediaPaneWithGrid(t, 2, 2)
	path := writeTestImage(t)
	store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"a": {{X: 0, FilePath: path}},
			"b": {{X: 0, FilePath: path}},
			"c": {{X: 0, FilePath: path}},
			"d": {{X: 0, FilePath: path}},
			"e": {{X: 0, FilePath: path}},
		},
	})
	pane.SetStore(store)
	pane.SetActive(true)
	_ = pane.View(90, 22, "", "")

	handled, cmd := pane.HandleKey(mediaKeyMsg(t, leet.MediaKeySelectionRight))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "Media: b")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeySelectionDown))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "Media: d")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeySelectionLeft))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "Media: c")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeySelectionUp))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "Media: a")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyPageNext))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "Media: e")

	handled, cmd = pane.HandleKey(mediaKeyMsg(t, leet.MediaKeyPagePrevious))
	require.True(t, handled)
	require.Nil(t, cmd)
	require.Contains(t, pane.StatusLabel(), "Media: a")
}

// --- MediaPane auto-follow ---

func TestMediaPane_AutoFollow(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "s", 0, 1)
	pane.SetStore(store)

	// Auto-follow → last step.
	require.Contains(t, pane.StatusLabel(), "X=_step 1")

	// New data arrives → auto-follow tracks it.
	feedImages(store, "s", 2)
	pane.SetStore(store)
	require.Contains(t, pane.StatusLabel(), "X=_step 2")

	// Scrub away disables auto-follow.
	pane.ScrubToStart()
	require.Contains(t, pane.StatusLabel(), "X=_step 0")

	// New data arrives → position stays pinned.
	feedImages(store, "s", 3)
	pane.SetStore(store)
	require.Contains(t, pane.StatusLabel(), "X=_step 0")
}

// --- MediaPane SetStore ---

func TestMediaPane_SetStore_Nil(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "s", 0)
	pane.SetStore(store)
	require.True(t, pane.HasData())

	pane.SetStore(nil)
	require.False(t, pane.HasData())
	require.Equal(t, "", pane.StatusLabel())
}

// --- MediaPane View ---

func TestMediaPane_View_EmptyStore(t *testing.T) {
	pane, _ := testMediaPane(t)
	// Should not panic and should render something.
	v := pane.View(80, 20, "", "No media.")
	require.Contains(t, v, "No media.")
}

func TestMediaPane_View_TooSmall(t *testing.T) {
	pane, store := testMediaPane(t)
	feedImages(store, "s", 0)
	pane.SetStore(store)

	require.Empty(t, pane.View(0, 20, "", ""))
	require.Empty(t, pane.View(80, 0, "", ""))
	require.Empty(t, pane.View(80, 5, "", "")) // below mediaPaneMinHeight
}

func TestMediaPane_View_RendersImageWithPictureGlyph(t *testing.T) {
	pane, store := testMediaPane(t)
	path := writeTestImage(t)
	store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"s": {{X: 0, FilePath: path}},
		},
	})
	pane.SetStore(store)

	view := pane.View(80, 20, "", "")
	require.NotContains(t, view, "open image")
	require.NotContains(t, view, "No image at X")
}

func TestMediaPane_ViewANSIKeepsTopAndBottomRows(t *testing.T) {
	pane, store := testMediaPaneWithGrid(t, 1, 1)
	path := writeBandTestImage(t)
	store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"s": {{X: 0, FilePath: path}},
		},
	})
	pane.SetStore(store)

	view := pane.View(40, 14, "", "")
	require.Contains(t, view, "255;0;0", "top row color should be rendered")
	require.Contains(t, view, "0;0;255", "bottom row color should be rendered")

	lines := strings.Split(stripANSI(view), "\n")
	footerIdx := -1
	for i, line := range lines {
		if strings.Contains(line, "│") && strings.Contains(line, "X=_step 0") {
			footerIdx = i
			break
		}
	}
	require.NotEqual(t, -1, footerIdx, "expected media tile footer")
	require.Greater(t, footerIdx, 0)
	require.NotEmpty(t, strings.Trim(lines[footerIdx-1], " │"))
}

func TestMediaPane_ToggleRendererModeTitle(t *testing.T) {
	setKittyGraphicsEnv(t, true)

	pane, store := testMediaPane(t)
	path := writeTestImage(t)
	store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"s": {{X: 0, FilePath: path}},
		},
	})
	pane.SetStore(store)
	pane.SetActive(true)

	view := pane.View(80, 20, "", "")
	require.Contains(t, view, "[ansi]")
	require.NotContains(t, pane.StatusLabel(), "kitty")

	handled, toggleCmd := pane.HandleKey(tea.KeyPressMsg{Code: 'k', Text: "k"})
	require.True(t, handled)
	require.Nil(t, toggleCmd)
	view = pane.View(80, 20, "", "")
	require.Contains(t, view, "[full-res]")
	require.NotContains(t, pane.StatusLabel(), "kitty")

	handled, toggleCmd = pane.HandleKey(tea.KeyPressMsg{Code: 'k', Text: "k"})
	require.True(t, handled)
	require.Nil(t, toggleCmd)
	view = pane.View(80, 20, "", "")
	require.Contains(t, view, "[ansi]")
	require.NotContains(t, pane.StatusLabel(), "kitty")
}

func TestMediaPane_ToggleRendererModeUnsupportedTerminalStaysANSI(t *testing.T) {
	setKittyGraphicsEnv(t, false)

	pane, store := testMediaPane(t)
	path := writeTestImage(t)
	store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"s": {{X: 0, FilePath: path}},
		},
	})
	pane.SetStore(store)
	pane.SetActive(true)

	handled, toggleCmd := pane.HandleKey(tea.KeyPressMsg{Code: 'k', Text: "k"})
	require.True(t, handled)
	require.Nil(t, toggleCmd)

	view := pane.View(80, 20, "", "")
	require.Contains(t, view, "[ansi]")
	require.NotContains(t, view, "[full-res]")
	require.NotContains(t, view, "\x1b_G")
}

func TestMediaPane_HeaderShowsRangeWithoutPageNumber(t *testing.T) {
	pane, store := testMediaPane(t)
	path := writeTestImage(t)
	store.ProcessHistory(leet.HistoryMsg{
		Media: map[string][]leet.MediaPoint{
			"a": {{X: 0, FilePath: path}},
			"b": {{X: 0, FilePath: path}},
			"c": {{X: 0, FilePath: path}},
			"d": {{X: 0, FilePath: path}},
			"e": {{X: 0, FilePath: path}},
			"f": {{X: 0, FilePath: path}},
			"g": {{X: 0, FilePath: path}},
		},
	})
	pane.SetStore(store)

	view := pane.View(80, 20, "", "")
	require.Contains(t, view, "[1-6 of 7]")
	require.NotContains(t, view, "p.1/2")

	header := strings.Split(stripANSI(view), "\n")[0]
	require.True(t, strings.HasSuffix(strings.TrimRight(header, " "), "[1-6 of 7]"))
}
