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
	transitions []*FsmTransition[T, C]
}

type FsmStateInterface[T any, C any] interface {
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
	f.state.OnCheck(record)
}

func (s *FsmState[T, C]) AddTransition(condition func(T) bool, state FsmStateInterface[T, C], action func(T)) {
	s.transitions = append(s.transitions,
		&FsmTransition[T, C]{
			Condition: condition,
			State:     state,
			Action:    action,
		})
}
