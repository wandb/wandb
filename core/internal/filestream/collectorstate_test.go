package filestream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
)

func TestMakeRequest_Empty(t *testing.T) {
	state := filestream.CollectorState{}

	data := state.PrepRequest(false)

	assert.Zero(t, data)
}

func TestMakeRequest_Done_SetsExitCode(t *testing.T) {
	intZero := int32(0)
	boolTrue := true
	state := filestream.CollectorState{
		ExitCode: &intZero,
		Complete: &boolTrue,
	}

	dataNotDone := state.PrepRequest(false)
	dataFinal := state.PrepRequest(true)

	assert.Nil(t, dataNotDone.Exitcode)
	assert.Nil(t, dataNotDone.Complete)

	assert.Equal(t, &intZero, dataFinal.Exitcode)
	assert.Equal(t, &boolTrue, dataFinal.Complete)
}

func TestMakeRequest_SetsLatestSummary(t *testing.T) {
	state := filestream.CollectorState{
		LatestSummary: "xyz",
	}

	data := state.PrepRequest(false)

	assert.Equal(t,
		filestream.FsTransmitFileData{
			Offset:  0,
			Content: []string{"xyz"},
		},
		data.Files["wandb-summary.json"])
}
