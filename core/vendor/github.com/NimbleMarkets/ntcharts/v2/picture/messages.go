package picture

// KittyFrameMsg carries the result of building a Kitty APC payload + grid for
// a specific generation of the Model. Update() ignores frames whose modelID
// (a per-Model atomic counter, unforgeable from outside the package) does not
// match the receiving Model's, or whose Seq does not match the Model's current
// seq (image/size/mode changed since dispatch). The modelID check is what
// prevents cross-talk when multiple Models share a tea.Program — every msg
// is forwarded to every Model — even if they happen to share a Kitty image ID.
type KittyFrameMsg struct {
	modelID uint64
	ID      int
	Seq     uint64
	APC     string
	Grid    string
}
