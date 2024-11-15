package agent

func WithMetadata(metadata map[string]string) func(*Agent) {
	return func(a *Agent) {
		a.metadata = metadata
	}
}

func WithHeader(key string, value string) func(*Agent) {
	return func(a *Agent) {
		a.headers.Set(key, value)
	}
}


func WithAssociatedResources(resources []string) func(*Agent) {
	return func(a *Agent) {
		a.associatedResources = resources
	}
}
