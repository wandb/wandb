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
	anim := leet.NewAnimatedValue(true, 30)
	pane := leet.NewMediaPane(anim, func() (int, int) { return 2, 3 })

	// Instantly expand so Height() > 0.
	anim.Toggle() // start → expanding
	time.Sleep(leet.AnimationDuration + 10*time.Millisecond)
	anim.Update(time.Now())

	store := leet.NewMediaStore()
	pane.SetStore(store)
	return pane, store
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

func TestMediaPane_ToggleRendererModeTitle(t *testing.T) {
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
