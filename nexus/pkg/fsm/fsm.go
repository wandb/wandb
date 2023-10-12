package fsm

type Fsm[K any] struct {
	state FsmStateInterface[K]
}

type FsmTransition[K any] struct {
	Condition func(K) bool
	State     FsmStateInterface[K]
	Action    func(K)
}

type FsmState[K any] struct {
	transitions []*FsmTransition[K]
}

type FsmStateInterface[K any] interface {
	OnCheck(arg K)
}

func NewFsm[K any]() *Fsm[K] {
	return &Fsm[K]{}
}

func (f *Fsm[K]) AddState(state FsmStateInterface[K]) {
	if f.state == nil {
		f.state = state
	}
}

func (f *Fsm[K]) Input(record K) {
	if f.state == nil {
		return
	}
	f.state.OnCheck(record)
}

func (s *FsmState[K]) AddTransition(condition func(K) bool, state FsmStateInterface[K], action func(K)) {
	s.transitions = append(s.transitions,
		&FsmTransition[K]{
			Condition: condition,
			State:     state,
			Action:    action,
		})
}
