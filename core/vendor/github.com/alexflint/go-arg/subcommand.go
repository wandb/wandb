package arg

// Subcommand returns the user struct for the subcommand selected by
// the command line arguments most recently processed by the parser.
// The return value is always a pointer to a struct. If no subcommand
// was specified then it returns the top-level arguments struct. If
// no command line arguments have been processed by this parser then it
// returns nil.
func (p *Parser) Subcommand() interface{} {
	if p.lastCmd == nil || p.lastCmd.parent == nil {
		return nil
	}
	return p.val(p.lastCmd.dest).Interface()
}

// SubcommandNames returns the sequence of subcommands specified by the
// user. If no subcommands were given then it returns an empty slice.
func (p *Parser) SubcommandNames() []string {
	if p.lastCmd == nil {
		return nil
	}

	// make a list of ancestor commands
	var ancestors []string
	cur := p.lastCmd
	for cur.parent != nil { // we want to exclude the root
		ancestors = append(ancestors, cur.name)
		cur = cur.parent
	}

	// reverse the list
	out := make([]string, len(ancestors))
	for i := 0; i < len(ancestors); i++ {
		out[i] = ancestors[len(ancestors)-i-1]
	}
	return out
}
