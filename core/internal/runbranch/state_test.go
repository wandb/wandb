package runbranch_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

func assertProtoEqual(t *testing.T, expected proto.Message, actual proto.Message) {
	assert.True(t,
		proto.Equal(expected, actual),
		"Value is\n\t%v\nbut expected\n\t%v", actual, expected)
}

func TestRecreatesProto(t *testing.T) {
	run := &spb.RunRecord{
		StorageId: "storage ID",

		Entity:  "entity",
		Project: "project",
		RunId:   "run ID",

		RunGroup:    "run group",
		DisplayName: "display name",
		Notes:       "notes",

		Git: &spb.GitRepoRecord{
			Commit:    "commit",
			RemoteUrl: "remote URL",
		},

		// Program comes from settings, not the record.
		Host:    "host",
		JobType: "job type",
		SweepId: "sweep ID",

		StartingStep: 123,
		Runtime:      987,

		Tags: []string{"tag1", "tag2"},

		// Summary is set to an empty value on the result (rather than unset).
		Summary: &spb.SummaryRecord{},

		Resumed: true,
		Forked:  true,

		StartTime: timestamppb.New(time.Now()),
	}

	params := runbranch.NewRunParams(run, settings.New())

	updatedProto := &spb.RunRecord{}
	params.SetOnProto(updatedProto)
	assertProtoEqual(t, run, updatedProto)
}

func TestNoHostIfMachineInfoDisabled(t *testing.T) {
	params := runbranch.NewRunParams(
		&spb.RunRecord{Host: "host"},
		settings.From(&spb.Settings{XDisableMachineInfo: wrapperspb.Bool(true)}),
	)

	assert.Empty(t, params.Host)
}

func TestReadsProgramFromSettings(t *testing.T) {
	params := runbranch.NewRunParams(
		&spb.RunRecord{},
		settings.From(&spb.Settings{Program: wrapperspb.String("program")}),
	)

	assert.Equal(t, "program", params.Program)
}

func TestSetsSummary(t *testing.T) {
	params := runbranch.NewRunParams(&spb.RunRecord{}, settings.New())
	params.Summary = map[string]any{"x": 123}

	updatedProto := &spb.RunRecord{}
	params.SetOnProto(updatedProto)

	assertProtoEqual(t,
		&spb.SummaryRecord{
			Update: []*spb.SummaryItem{
				{
					Key:       "x",
					ValueJson: "123",
				},
			},
		},
		updatedProto.Summary)
}
