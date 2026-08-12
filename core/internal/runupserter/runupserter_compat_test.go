package runupserter_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// TestResume_FalseIntentAutoExistingRun is the acceptance test for R2: `auto`
// is a documented resume mode and must behave like `allow` for a log written
// before offline resume (ResumeMode == false) that's resumed at sync time.
//
// It currently doesn't: InitRun's resume gate only recognizes "allow" and
// "must", so `auto` silently falls through as if no resume were requested at
// all, and the run is recreated from scratch instead of resumed -- losing
// config, summary, and tags. This fails today; compare with the sibling
// TestResume_FalseIntentAllowExistingRun, which passes.
func TestResume_FalseIntentAutoExistingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "auto")
	runupsertertest.StubRunResumeStatusExistingRun(t, mockClient)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{RunId: "run"}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	assert.True(t, mockClient.AllStubsUsed(),
		"auto should query RunResumeStatus and resume the existing run")
}

// TestResume_FalseIntentUnexpectedExistingRun generalizes R2: an unrecognized
// resume string behaves exactly like an unset one, and exactly like `auto` --
// it silently skips resume entirely rather than treating an existing run as
// an error or a resume target. Same root cause and same failure as
// TestResume_FalseIntentAutoExistingRun above.
func TestResume_FalseIntentUnexpectedExistingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "unexpected")
	runupsertertest.StubRunResumeStatusExistingRun(t, mockClient)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(runRecord(&spb.RunRecord{RunId: "run"}), params)
	require.NoError(t, err)
	defer upserter.Finish()

	assert.True(t, mockClient.AllStubsUsed(),
		"an unrecognized resume setting should still query and resume an existing run")
}

// TestResume_FromRunRecordDegradesMustIntentOnMissingRunWithEmptySetting
// pins R5: RunRecord.ResumeMode only records *whether* to resume, not *how*.
// A run recorded with intent to `must` resume, synced with no explicit
// setting (as `wandb beta sync` does), silently degrades to `allow`
// semantics instead of erroring when the run turns out to be missing.
func TestResume_FromRunRecordDegradesMustIntentOnMissingRunWithEmptySetting(t *testing.T) {
	mockClient, params := setupResumeTest(t, "")
	mockClient.StubMatchOnce(gqlmock.WithOpName("RunResumeStatus"), `{}`)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(
		runRecord(&spb.RunRecord{RunId: "run", ResumeMode: true}),
		params,
	)

	// Would be an error if `must` survived the round trip through the log's
	// single ResumeMode bit; instead this creates a new run with no warning.
	require.NoError(t, err)
	defer upserter.Finish()
	assert.True(t, mockClient.AllStubsUsed())
}

// TestResume_FromRunRecordWithUnexpectedSettingResumesExistingRun pins a
// correction to an earlier version of the resume plan: allowResume() used to
// whitelist {allow, auto, must, ""} and reject anything else with
// ErrorInfo_USAGE. It was simplified to "!= never", so an unrecognized
// resume setting on a log that itself carries resume intent (ResumeMode ==
// true) is no longer a hard error -- it's treated like `allow`.
func TestResume_FromRunRecordWithUnexpectedSettingResumesExistingRun(t *testing.T) {
	mockClient, params := setupResumeTest(t, "unexpected")
	runupsertertest.StubRunResumeStatusExistingRun(t, mockClient)
	runupsertertest.StubUpsertBucket(t, mockClient)

	upserter, err := runupserter.InitRun(
		runRecord(&spb.RunRecord{RunId: "run", ResumeMode: true}),
		params,
	)
	require.NoError(t, err)
	defer upserter.Finish()

	assert.True(t, mockClient.AllStubsUsed())
}
