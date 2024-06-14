package filestream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
)

func TestMakeRequest_Empty_NoData(t *testing.T) {
	state := filestream.CollectorState{}

	data, hasData := state.MakeRequest(false)

	assert.False(t, hasData)
	assert.Zero(t, *data)
}

func TestMakeRequest_Done_SetsExitCode(t *testing.T) {
	intZero := int32(0)
	boolTrue := true
	state := filestream.CollectorState{
		ExitCode: &intZero,
		Complete: &boolTrue,
	}

	dataNotDone, hasDataNotDone := state.MakeRequest(false)
	dataFinal, hasDataFinal := state.MakeRequest(true)

	assert.False(t, hasDataNotDone)
	assert.Nil(t, dataNotDone.Exitcode)
	assert.Nil(t, dataNotDone.Complete)

	assert.True(t, hasDataFinal)
	assert.Equal(t, &intZero, dataFinal.Exitcode)
	assert.Equal(t, &boolTrue, dataFinal.Complete)
}

func TestMakeRequest_SetsLatestSummary(t *testing.T) {
	state := filestream.CollectorState{
		LatestSummary: "xyz",
	}

	data, hasData := state.MakeRequest(false)

	assert.True(t, hasData)
	assert.Equal(t,
		filestream.FsTransmitFileData{
			Offset:  0,
			Content: []string{"xyz"},
		},
		data.Files["wandb-summary.json"])
}
