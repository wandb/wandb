package history

type DefineKeys[N any] struct {
	dm *KeySet[N]
	gm *KeySet[N]
}

func NewDefineKeys[N any](opts ...DefineKeysOptions[N]) *DefineKeys[N] {
	m := &DefineKeys[N]{}
	for _, opt := range opts {
		opt(m)
	}
	return m
}

type DefineKeysOptions[N any] func(*DefineKeys[N])

func WithDefinedMetricKeySet[N any](dm *KeySet[N]) DefineKeysOptions[N] {
	return func(m *DefineKeys[N]) {
		m.dm = dm
	}
}

func WithGlobMetricKeySet[N any](gm *KeySet[N]) DefineKeysOptions[N] {
	return func(m *DefineKeys[N]) {
		m.gm = gm
	}
}

func (m *DefineKeys[N]) GetDefinedMetricKeySet() *KeySet[N] {
	return m.dm
}

func (m *DefineKeys[N]) GetGlobMetricKeySet() *KeySet[N] {
	return m.gm
}
