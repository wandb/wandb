package uniseg

// The states of the grapheme cluster parser.
const (
	grAny = iota
	grCR
	grControlLF
	grL
	grLVV
	grLVTT
	grPrepend
	grExtendedPictographic
	grExtendedPictographicZWJ
	grRIOdd
	grRIEven

	// We track Indic conjunct sequences (GB9c) using the grInCBLinkerExtend
	// state in its own bit because they are basically separate from the main
	// state machine.
	grInCBLinkerExtend = 1 << 4
)

// grTransitions implements the grapheme cluster parser's state transitions.
// Maps state and property to a new state, a breaking instruction, and rule
// number times ten (plus the sub-rule index), to facilitate rule
// prioritization. Also returns whether a specific transition was found. The
// breaking instruction always refers to the boundary between the last and next
// code point.
//
// This function should be used as follows:
//
//  1. Find specific state + specific property. Stop if found.
//  2. Find specific state + any property.
//  3. Find any state + specific property.
//  4. If only (2) or (3) (but not both) was found, stop.
//  5. If both (2) and (3) were found, use state from (3) and breaking instruction
//     from the transition with the lower rule number, prefer (3) if rule numbers
//     are equal. Stop.
//  6. Assume grAny and grBoundary.
//
// Unicode version 18.0.0.
func grTransitions(state, prop int) (found bool, newState int, isBoundary bool, ruleNum int) {
	state = max(state, 0) // Because state could be -1.

	defer func() {
		// Check transitions for Indic conjunct sequences (GB9c).
		switch prop & prInCBMask {
		case prInCBLinker:
			newState |= grInCBLinkerExtend
		case prInCBExtend:
			if state&grInCBLinkerExtend != 0 {
				newState |= grInCBLinkerExtend
			}
		case prInCBConsonant:
			if state&grInCBLinkerExtend != 0 && (ruleNum < 0 || ruleNum > 93) {
				// GB9c applies.
				found = true
				newState = grAny
				isBoundary = false
				ruleNum = 93
			}
		}
	}()

	// Check all rules except for GB9c. It turns out that using a big switch
	// statement is much faster than using a map.
	switch uint64(state)&^uint64(grInCBLinkerExtend) | (uint64(prop)&^uint64(prInCBMask))<<32 {
	// GB5
	case grAny | prCR<<32:
		return true, grCR, true, 50
	case grAny | prLF<<32:
		return true, grControlLF, true, 50
	case grAny | prControl<<32:
		return true, grControlLF, true, 50

	// GB4
	case grCR | prAny<<32:
		return true, grAny, true, 40
	case grControlLF | prAny<<32:
		return true, grAny, true, 40

	// GB3
	case grCR | prLF<<32:
		return true, grControlLF, false, 30

	// GB6
	case grAny | prL<<32:
		return true, grL, true, 9990
	case grL | prL<<32:
		return true, grL, false, 60
	case grL | prV<<32:
		return true, grLVV, false, 60
	case grL | prLV<<32:
		return true, grLVV, false, 60
	case grL | prLVT<<32:
		return true, grLVTT, false, 60

	// GB7
	case grAny | prLV<<32:
		return true, grLVV, true, 9990
	case grAny | prV<<32:
		return true, grLVV, true, 9990
	case grLVV | prV<<32:
		return true, grLVV, false, 70
	case grLVV | prT<<32:
		return true, grLVTT, false, 70

	// GB8
	case grAny | prLVT<<32:
		return true, grLVTT, true, 9990
	case grAny | prT<<32:
		return true, grLVTT, true, 9990
	case grLVTT | prT<<32:
		return true, grLVTT, false, 80

	// GB9
	case grAny | prExtend<<32:
		return true, grAny, false, 90
	case grAny | prZWJ<<32:
		return true, grAny, false, 90

	// GB9a
	case grAny | prSpacingMark<<32:
		return true, grAny, false, 91

	// GB9b
	case grAny | prPrepend<<32:
		return true, grPrepend, true, 9990
	case grPrepend | prAny<<32:
		return true, grAny, false, 92

	// GB9c see above.

	// GB11
	case grAny | prExtendedPictographic<<32:
		return true, grExtendedPictographic, true, 9990
	case grExtendedPictographic | prExtend<<32:
		return true, grExtendedPictographic, false, 110
	case grExtendedPictographic | prZWJ<<32:
		return true, grExtendedPictographicZWJ, false, 110
	case grExtendedPictographicZWJ | prExtendedPictographic<<32:
		return true, grExtendedPictographic, false, 110

	// GB12 / GB13
	case grAny | prRegionalIndicator<<32:
		return true, grRIOdd, true, 9990
	case grRIOdd | prRegionalIndicator<<32:
		return true, grRIEven, false, 120
	case grRIEven | prRegionalIndicator<<32:
		return true, grRIOdd, true, 120

	default:
		return false, grAny, true, 9990
	}
}

// transitionGraphemeState determines the new state of the grapheme cluster
// parser given the current state and the next code point. It also returns the
// code point's grapheme property and whether a cluster boundary was detected
// just before the given code point.
func transitionGraphemeState(state int, r rune) (newState, prop int, isBoundary bool) {
	// Determine the property of the next character.
	prop = propertyGraphemes(r)

	// Find the applicable transition.
	found, nextState, nextBoundary, _ := grTransitions(state, prop)
	if found {
		// We have a specific transition. We'll use it.
		return nextState, prop, nextBoundary
	}

	// No specific transition found. Try the less specific ones.
	foundAnyProp, anyPropState, anyPropBoundary, anyPropRule := grTransitions(state, prAny)
	foundAnyState, anyStateState, anyStateBoundary, anyStateRule := grTransitions(grAny, prop)
	if foundAnyProp && foundAnyState {
		// Both apply. We'll use a mix (see comments for grTransitions).
		newState = anyStateState
		isBoundary = anyStateBoundary
		if anyPropRule < anyStateRule {
			isBoundary = anyPropBoundary
		}
		return
	}

	if foundAnyProp {
		// We only have a specific state.
		return anyPropState, prop, anyPropBoundary
		// This branch will probably never be reached because okAnyState will
		// always be true given the current transition map. But we keep it here
		// for future modifications to the transition map where this may not be
		// true anymore.
	}

	if foundAnyState {
		// We only have a specific property.
		return anyStateState, prop, anyStateBoundary
	}

	// No known transition. GB999: Any ÷ Any.
	return nextState, prop, nextBoundary
}
