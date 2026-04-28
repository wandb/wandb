package picture

// KittyFrameMsg carries the result of building a Kitty APC payload + grid for
// a specific generation of the Model. Update() ignores frames whose id (the
// Kitty image ID) does not match the Model's, or whose seq does not match the
// Model's current seq (image/size/mode changed since dispatch). The id check
// matters when multiple Models share a tea.Program — every msg is forwarded
// to every Model, so without it one Model's frame can clobber another's.
type KittyFrameMsg struct {
	ID   int
	Seq  uint64
	APC  string
	Grid string
}
