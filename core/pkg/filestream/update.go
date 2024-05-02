package filestream

import "github.com/wandb/wandb/core/pkg/service"

// Update is unprocessed data that the filestream operates on.
type Update struct {
	// Updates to the run's history (i.e. `run.log()`).
	HistoryRecord *service.HistoryRecord

	// Updates to the run's summary.
	SummaryRecord *service.SummaryRecord

	// System metrics for the run, e.g. memory and processor usage.
	StatsRecord *service.StatsRecord

	// The run's console output.
	LogsRecord *service.OutputRawRecord

	// Information about the run's completion.
	ExitRecord *service.RunExitRecord

	// Information about when a run is preempted.
	//
	// "Preemptible runs and sweeps" were added in
	// https://github.com/wandb/wandb/pull/2142
	//
	// This is a mechanism to tell the backend that the run will be unable to
	// even send heartbeats for some time, and to be more lenient with
	// deciding if the run crashed.
	PreemptRecord *service.RunPreemptingRecord

	// Path to a run file whose contents were successfully uploaded.
	//
	// The path is relative to the run's files directory.
	//
	// This is used in some deployments where the backend is not notified when
	// files finish uploading.
	UploadedFile string
}
