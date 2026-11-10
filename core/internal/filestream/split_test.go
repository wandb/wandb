package filestream

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
)

func ptr[T any](v T) *T { return &v }

func TestSplitRequest_SplitsOffOneFile(t *testing.T) {
	r := &FileStreamRequestJSON{
		Files: map[string]OffsetAndContent{
			OutputFileName:  {Offset: 3, Content: []string{"out"}},
			HistoryFileName: {Offset: 5, Content: []string{"h1"}},
		},
		Uploaded: []string{"file.txt"},
		Complete: ptr(true),
		ExitCode: ptr(int32(1)),
	}

	first, second, ok := splitRequest(r)

	require.True(t, ok)
	assert.Equal(t, map[string]OffsetAndContent{
		HistoryFileName: {Offset: 5, Content: []string{"h1"}},
	}, first.Files)
	assert.Nil(t, first.Complete)
	assert.Empty(t, first.Uploaded)
	assert.Equal(t, map[string]OffsetAndContent{
		OutputFileName: {Offset: 3, Content: []string{"out"}},
	}, second.Files)
	assert.Equal(t, []string{"file.txt"}, second.Uploaded)
	assert.True(t, *second.Complete)
	assert.EqualValues(t, 1, *second.ExitCode)
	assert.Len(t, r.Files, 2, "the original request is unchanged")
}

func TestSplitRequest_SplitsLinesKeepingOffsets(t *testing.T) {
	r := &FileStreamRequestJSON{
		Files: map[string]OffsetAndContent{
			HistoryFileName: {Offset: 10, Content: []string{"a", "b", "c", "d", "e"}},
		},
		Preempting: ptr(true),
		Complete:   ptr(true),
		ExitCode:   ptr(int32(0)),
	}

	first, second, ok := splitRequest(r)

	require.True(t, ok)
	assert.Equal(t,
		OffsetAndContent{Offset: 10, Content: []string{"a", "b"}},
		first.Files[HistoryFileName])
	assert.Nil(t, first.Complete)
	assert.Nil(t, first.Preempting)
	assert.Equal(t,
		OffsetAndContent{Offset: 12, Content: []string{"c", "d", "e"}},
		second.Files[HistoryFileName])
	assert.True(t, *second.Complete)
	assert.True(t, *second.Preempting)
}

func TestSplitRequest_SeparatesSingleLineFromExitState(t *testing.T) {
	r := &FileStreamRequestJSON{
		Files: map[string]OffsetAndContent{
			SummaryFileName: {Offset: 0, Content: []string{"{}"}},
		},
		Complete: ptr(true),
		ExitCode: ptr(int32(0)),
	}

	first, second, ok := splitRequest(r)

	require.True(t, ok)
	assert.Equal(t, r.Files, first.Files)
	assert.Nil(t, first.Complete)
	assert.Empty(t, second.Files)
	assert.True(t, *second.Complete)
}

func TestSplitRequest_SingleLineCannotBeSplit(t *testing.T) {
	r := &FileStreamRequestJSON{
		Files: map[string]OffsetAndContent{
			HistoryFileName: {Offset: 0, Content: []string{"a"}},
		},
	}

	_, _, ok := splitRequest(r)

	assert.False(t, ok)
}

func TestRequestSizeLimit_OnlyDecreases(t *testing.T) {
	var nilLimit *RequestSizeLimit
	assert.Equal(t, 100, nilLimit.Apply(100))

	limit := &RequestSizeLimit{}
	assert.Equal(t, 100, limit.Apply(100))

	limit.Lower(50)
	assert.Equal(t, 50, limit.Apply(100))
	assert.Equal(t, 30, limit.Apply(30))

	limit.Lower(80)
	assert.Equal(t, 50, limit.Apply(100))
}

func TestPop_LimitsRequestByJSONSize(t *testing.T) {
	// Lines made of quotes double in size when escaped.
	line := strings.Repeat(`"`, 1000)
	request := &FileStreamRequest{}
	for range 100 {
		request.HistoryLines = append(request.HistoryLines, line)
	}
	state := &FileStreamState{MaxRequestSizeBytes: 50_000}

	json1, hasMore := state.Pop(
		request,
		observability.NewNoOpLogger(),
		observability.NewPrinter(0),
	)

	require.True(t, hasMore)
	body, err := json.Marshal(json1)
	require.NoError(t, err)
	assert.LessOrEqual(t, len(body), 50_000+100, "only a small envelope overhead")
	assert.Greater(t, len(body), 40_000)
}

func TestSettingOrDefault(t *testing.T) {
	assert.Equal(t, 10, settingOrDefault(0, 10))
	assert.Equal(t, 10, settingOrDefault(-1, 10))
	assert.Equal(t, 3, settingOrDefault(3, 10), "a setting can lower the default")
	assert.Equal(t, 30, settingOrDefault(30, 10))
}
