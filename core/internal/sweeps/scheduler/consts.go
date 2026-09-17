package scheduler

const (
	// warmStartPageSize bounds the batch of prior runs the optimizer
	// ingests at a time.
	warmStartPageSize = 100

	// historySampleCount is how many rows each run's metric history is
	// sampled down to.
	historySampleCount = 20

	// stepKey is the history key requested alongside the metric so the
	// optimizer can plot it against the run's step.
	stepKey = "_step"
)
