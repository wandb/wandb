package wberrors_test

import (
	"io"
	"log/slog"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/observability/wberrors"
)

func TestNewfFormat(t *testing.T) {
	assert.Equal(t,
		"the number is 3",
		wberrors.Newf("the number is %d", 3).Error())
}

func TestWrapNil_Panics(t *testing.T) {
	// Wrapping a nil error should panic early because calling Error() on
	// a nil error seems to hang, at least in tests. Better a panic than
	// a hang.

	t.Run("Enrichf", func(t *testing.T) {
		assert.Panics(t, func() {
			_ = wberrors.Enrichf(nil, "text")
		})
	})

	t.Run("Bubblef", func(t *testing.T) {
		assert.Panics(t, func() {
			_ = wberrors.Bubblef(nil, "text")
		})
	})
}

func TestEnrichfFormat(t *testing.T) {
	t.Run("no message", func(t *testing.T) {
		assert.Equal(t,
			"EOF",
			wberrors.Enrichf(io.EOF, "").Error())
	})

	t.Run("with format", func(t *testing.T) {
		assert.Equal(t,
			"failed (123): EOF",
			wberrors.Enrichf(io.EOF, "failed (%d)", 123).Error())
	})
}

func TestBubblefFormat(t *testing.T) {
	t.Run("no message", func(t *testing.T) {
		assert.Equal(t,
			"EOF",
			wberrors.Bubblef(io.EOF, "").Error())
	})

	t.Run("with format", func(t *testing.T) {
		assert.Equal(t,
			"failed (123): EOF",
			wberrors.Bubblef(io.EOF, "failed (%d)", 123).Error())
	})
}

func TestEnrichfDoesNotWrap(t *testing.T) {
	assert.NotErrorIs(t,
		wberrors.Enrichf(io.EOF, ""),
		io.EOF)
}

func TestBubblefWraps(t *testing.T) {
	assert.ErrorIs(t,
		wberrors.Bubblef(io.EOF, ""),
		io.EOF)
}

func TestAttrs(t *testing.T) {
	t.Run("none if not enriched", func(t *testing.T) {
		assert.Empty(t, wberrors.Attrs(io.EOF))
	})

	t.Run("none by default", func(t *testing.T) {
		assert.Empty(t, wberrors.Attrs(wberrors.Newf("")))
	})

	t.Run("copies when wrapping", func(t *testing.T) {
		err1 := wberrors.Newf("").
			Attr(slog.String("key1", "value1")).
			Attr(slog.String("key2", "value2"))

		err2 := wberrors.Enrichf(err1, "").
			Attr(slog.String("key2", "overwritten")).
			Attr(slog.String("key3", "value3"))

		// Original error not mutated.
		assert.ElementsMatch(t,
			[]slog.Attr{
				slog.String("key1", "value1"),
				slog.String("key2", "value2"),
			},
			wberrors.Attrs(err1))
		// Wrapped error copies attrs; new values take precedence.
		assert.ElementsMatch(t,
			[]slog.Attr{
				slog.String("key1", "value1"),
				slog.String("key2", "overwritten"),
				slog.String("key3", "value3"),
			},
			wberrors.Attrs(err2))
	})
}

func TestTags(t *testing.T) {
	t.Run("none if not enriched", func(t *testing.T) {
		assert.Empty(t, wberrors.Tags(io.EOF))
	})

	t.Run("none by default", func(t *testing.T) {
		assert.Empty(t, wberrors.Tags(wberrors.Newf("")))
	})

	t.Run("copies when wrapping", func(t *testing.T) {
		err1 := wberrors.Newf("").
			Attr(slog.String("key1", "value1")).
			Attr(slog.String("key2", "value2"))

		err2 := wberrors.Enrichf(err1, "").
			Attr(slog.String("key2", "overwritten")).
			Attr(slog.String("key3", "value3"))

		// Original error not mutated.
		assert.Equal(t,
			map[string]string{
				"key1": "value1",
				"key2": "value2",
			},
			wberrors.Tags(err1))
		// Wrapped error copies tags; new values take precedence.
		assert.Equal(t,
			map[string]string{
				"key1": "value1",
				"key2": "overwritten",
				"key3": "value3",
			},
			wberrors.Tags(err2))
	})
}

func TestSkipSentryIf(t *testing.T) {
	testCases := []struct {
		name     string
		err      error
		expected bool
	}{
		{"false if not enriched", io.EOF, false},
		{"false by default", wberrors.Newf(""), false},
		{"true if set", wberrors.Newf("").SkipSentryIf(true), true},

		{"true if inherited",
			wberrors.Enrichf(
				wberrors.Newf("").SkipSentryIf(true), "",
			),
			true},

		{"not clearable",
			wberrors.Enrichf(
				wberrors.Newf("").SkipSentryIf(true), "",
			).SkipSentryIf(false),
			true},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			assert.Equal(t, tc.expected, wberrors.SkipSentry(tc.err))
		})
	}
}

func TestFingerprint(t *testing.T) {
	t.Run("none if not enriched", func(t *testing.T) {
		assert.Empty(t, wberrors.ExtraFingerprint(io.EOF))
	})

	t.Run("none by default", func(t *testing.T) {
		assert.Empty(t, wberrors.ExtraFingerprint(wberrors.Newf("")))
	})

	t.Run("copies when wrapping", func(t *testing.T) {
		err1 := wberrors.Newf("").Fingerprint("one")
		err2 := wberrors.Enrichf(err1, "").Fingerprint("two")

		assert.Equal(t, []string{"one"}, wberrors.ExtraFingerprint(err1))
		assert.Equal(t, []string{"one", "two"}, wberrors.ExtraFingerprint(err2))
	})
}
