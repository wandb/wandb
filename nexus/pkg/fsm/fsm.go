package fsm

type Fsm[T, C any] struct {
	state FsmStateInterface[T, C]
}

type FsmTransition[T, C any] struct {
	Condition func(T) bool
	State     FsmStateInterface[T, C]
	Action    func(T)
}

type FsmState[T, C any] struct {
	Transitions []*FsmTransition[T, C]
}

type FsmStateInterface[T any, C any] interface {
	Input(arg T, state FsmStateInterface[T, C], changeState func(state FsmStateInterface[T,C]))
	OnCheck(arg T)
	OnEnter(arg T, context C)
	OnExit(arg T) C
}

func NewFsm[T any, C any]() *Fsm[T, C] {
	return &Fsm[T, C]{}
}

func (f *Fsm[T, C]) SetDefaultState(state FsmStateInterface[T, C]) {
	if f.state != nil {
		return
	}
	f.state = state
}

func (f *Fsm[T, C]) AddState(state FsmStateInterface[T, C]) {
	f.SetDefaultState(state)
}

func (f *Fsm[T, C]) Input(record T) {
	if f.state == nil {
		return
	}
	f.state.Input(record, f.state, f.changeState)
}

func (f *Fsm[T, C]) changeState(state FsmStateInterface[T, C]) {
	f.state = state
}

func (s *FsmState[T, C]) Input(record T, state FsmStateInterface[T, C], changeState func(state FsmStateInterface[T,C])) {
	state.OnCheck(record)
	for _, transition := range s.Transitions {
		if transition.Condition(record) {
			transition.Action(record)
			newState := transition.State
			if state == newState {
				return
			}
			context := state.OnExit(record)
			changeState(newState)
			newState.OnEnter(record, context)
			return
		}
	}
}

func (s *FsmState[T, C]) AddTransition(condition func(T) bool, state FsmStateInterface[T, C], action func(T)) {
	s.Transitions = append(s.Transitions,
		&FsmTransition[T, C]{
			Condition: condition,
			State:     state,
			Action:    action,
		})
}
