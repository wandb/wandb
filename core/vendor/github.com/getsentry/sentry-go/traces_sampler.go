package sentry

// A SamplingContext is passed to a TracesSampler to determine a sampling
// decision.
//
// TODO(tracing): possibly expand SamplingContext to include custom /
// user-provided data.
type SamplingContext struct {
	Span   *Span // The current span, always non-nil.
	Parent *Span // The local parent span, non-nil only when the parent exists in the same process.
	// ParentSampled is the sampling decision of the parent span.
	//
	// For a remote span, Parent is nil but ParentSampled reflects the upstream decision.
	// For a local span, ParentSampled mirrors Parent.Sampled.
	ParentSampled Sampled
	// ParentSampleRate is the sample rate used by the parent transaction.
	ParentSampleRate *float64
}

// The TracesSample type is an adapter to allow the use of ordinary
// functions as a TracesSampler.
type TracesSampler func(ctx SamplingContext) float64

func (f TracesSampler) Sample(ctx SamplingContext) float64 {
	return f(ctx)
}
