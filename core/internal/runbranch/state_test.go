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

func TestRunPath_URL(t *testing.T) {
	t.Run("produces clean escaped URL", func(t *testing.T) {
		path := runbranch.RunPath{
			Entity:  "entity with space",
			Project: "project?",
			// Common special characters people include in run IDs.
			// Just the forward slash should be URL-escaped.
			RunID: "me@machine/x=1&y=+$2",
		}

		url, err := path.URL("https://my-web-ui///")

		assert.NoError(t, err)
		assert.Equal(t,
			"https://my-web-ui/entity%20with%20space/project%3F/runs/me@machine%2Fx=1&y=+$2",
			url)
	})

	t.Run("no entity", func(t *testing.T) {
		path := runbranch.RunPath{Project: "project", RunID: "id"}

		_, err := path.URL("https://wandb.ai")

		assert.ErrorContains(t, err, "no entity")
	})

	t.Run("no project", func(t *testing.T) {
		path := runbranch.RunPath{Entity: "entity", RunID: "id"}

		_, err := path.URL("https://wandb.ai")

		assert.ErrorContains(t, err, "no project")
	})

	t.Run("no ID", func(t *testing.T) {
		path := runbranch.RunPath{Entity: "entity", Project: "project"}

		_, err := path.URL("https://wandb.ai")

		assert.ErrorContains(t, err, "no run ID")
	})
}
