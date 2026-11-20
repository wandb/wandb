package uniseg

import "unicode/utf8"

// The states of the line break parser.
const (
	lbAny = iota
	lbBK
	lbCR
	lbLF
	lbNL
	lbSP
	lbZW
	lbZWSP
	lbWJ
	lbGL
	lbHH
	lbHY
	lbCL
	lbCP
	lbEX
	lbIS
	lbSY
	lbOP
	lbOPSP
	lbQU
	lbLB15a
	lbNS
	lbCLCPSP
	lbB2
	lbB2SP
	lbCB
	lbBB
	lbLB20a
	lbLB21a
	lbHL
	lbAL
	lbNU
	lbPR
	lbEB
	lbIDEM
	lbNUSY
	lbNUIS
	lbNUCL
	lbNUCP
	lbPO
	lbJL
	lbJV
	lbJT
	lbH2
	lbH3
	lbAP
	lbAKAS
	lbDottedCircle // Dotted Circle is prAL.
	lbAKCircleASVI
	lbOddRI
	lbEvenRI
	lbZWJBit                = 1 << 6
	lbEastAsianBit          = 1 << 7
	lbQUAfterNoEastAsianBit = 1 << 8
	lbExtPicCnBit           = 1 << 9
	lbPiPfBits              = 1<<10 | 1<<11
	lbIsPi                  = 0
	lbIsntPi                = 1 << 10
	lbIsPf                  = 2 << 10
	lbIsntPf                = 3 << 10
)

// These constants define whether a given text may be broken into the next line.
// If the break is optional (LineCanBreak), you may choose to break or not based
// on your own criteria, for example, if the text has reached the available
// width.
const (
	LineDontBreak = iota // You may not break the line here.
	LineCanBreak         // You may or may not break the line here.
	LineMustBreak        // You must break the line here.
)

// lbTransitions implements the line break parser's state transitions. It's
// anologous to [grTransitions], see comments there for details.
//
// Unicode version 18.0.0.
func lbTransitions(state, prop int) (newState, lineBreak, rule int) {
	switch uint64(state)&uint64(1<<32-1) | uint64(prop)<<32 {
	// LB4.
	case lbBK | prAny<<32:
		return lbAny, LineMustBreak, 40

	// LB5.
	case lbCR | prLF<<32:
		return lbLF, LineDontBreak, 50
	case lbCR | prAny<<32:
		return lbAny, LineMustBreak, 50
	case lbLF | prAny<<32:
		return lbAny, LineMustBreak, 50
	case lbNL | prAny<<32:
		return lbAny, LineMustBreak, 50

	// LB6.
	case lbAny | prBK<<32:
		return lbBK, LineDontBreak, 60
	case lbAny | prCR<<32:
		return lbCR, LineDontBreak, 60
	case lbAny | prLF<<32:
		return lbLF, LineDontBreak, 60
	case lbAny | prNL<<32:
		return lbNL, LineDontBreak, 60

	// LB7.
	case lbAny | prSP<<32:
		return lbSP, LineDontBreak, 70
	case lbAny | prZW<<32:
		return lbZW, LineDontBreak, 70

	// LB8.
	case lbZW | prSP<<32:
		return lbZWSP, LineDontBreak, 70
	case lbZW | prAny<<32:
		return lbAny, LineCanBreak, 80
	case lbZWSP | prSP<<32:
		return lbZWSP, LineDontBreak, 70
	case lbZWSP | prAny<<32:
		return lbAny, LineCanBreak, 80

	// LB11.
	case lbAny | prWJ<<32:
		return lbWJ, LineDontBreak, 110
	case lbWJ | prAny<<32:
		return lbAny, LineDontBreak, 110

	// LB12.
	case lbAny | prGL<<32:
		return lbGL, LineCanBreak, 310
	case lbGL | prAny<<32:
		return lbAny, LineDontBreak, 120

	// LB13 (simple transitions).
	case lbAny | prCL<<32:
		return lbCL, LineDontBreak, 130
	case lbAny | prCP<<32:
		return lbCP, LineDontBreak, 130
	case lbAny | prEX<<32:
		return lbEX, LineDontBreak, 130
	case lbAny | prSY<<32:
		return lbSY, LineDontBreak, 130

	// LB14.
	case lbAny | prOP<<32:
		return lbOP, LineCanBreak, 310
	case lbOP | prSP<<32:
		return lbOPSP, LineDontBreak, 70
	case lbOP | prAny<<32:
		return lbAny, LineDontBreak, 140
	case lbOPSP | prSP<<32:
		return lbOPSP, LineDontBreak, 70
	case lbOPSP | prAny<<32:
		return lbAny, LineDontBreak, 140

	// LB15d.
	case lbAny | prIS<<32:
		return lbIS, LineDontBreak, 154

	// LB16.
	case lbCL | prSP<<32:
		return lbCLCPSP, LineDontBreak, 70
	case lbNUCL | prSP<<32:
		return lbCLCPSP, LineDontBreak, 70
	case lbCP | prSP<<32:
		return lbCLCPSP, LineDontBreak, 70
	case lbNUCP | prSP<<32:
		return lbCLCPSP, LineDontBreak, 70
	case lbCL | prNS<<32:
		return lbNS, LineDontBreak, 160
	case lbNUCL | prNS<<32:
		return lbNS, LineDontBreak, 160
	case lbCP | prNS<<32:
		return lbNS, LineDontBreak, 160
	case lbNUCP | prNS<<32:
		return lbNS, LineDontBreak, 160
	case lbCLCPSP | prNS<<32:
		return lbNS, LineDontBreak, 160

	// LB17.
	case lbAny | prB2<<32:
		return lbB2, LineCanBreak, 310
	case lbB2 | prSP<<32:
		return lbB2SP, LineDontBreak, 70
	case lbB2 | prB2<<32:
		return lbB2, LineDontBreak, 170
	case lbB2SP | prB2<<32:
		return lbB2, LineDontBreak, 170

	// LB18.
	case lbSP | prAny<<32:
		return lbAny, LineCanBreak, 180
	case lbCLCPSP | prAny<<32:
		return lbAny, LineCanBreak, 180
	case lbB2SP | prAny<<32:
		return lbAny, LineCanBreak, 180

	// LB20.
	case lbAny | prCB<<32:
		return lbCB, LineCanBreak, 200
	case lbCB | prAny<<32:
		return lbAny, LineCanBreak, 200

	// LB21.
	case lbAny | prBA<<32:
		return lbAny, LineDontBreak, 210
	case lbAny | prHH<<32:
		return lbHH, LineDontBreak, 210
	case lbAny | prHY<<32:
		return lbHY, LineDontBreak, 210
	case lbAny | prNS<<32:
		return lbNS, LineDontBreak, 210
	case lbAny | prBB<<32:
		return lbBB, LineCanBreak, 310
	case lbBB | prAny<<32:
		return lbAny, LineDontBreak, 210

	// LB21a (simple transitions).
	case lbAny | prHL<<32:
		return lbHL, LineCanBreak, 310

	// LB21b.
	case lbSY | prHL<<32:
		return lbHL, LineDontBreak, 212
	case lbNUSY | prHL<<32:
		return lbHL, LineDontBreak, 212

	// LB22.
	case lbAny | prIN<<32:
		return lbAny, LineDontBreak, 220

	// LB23.
	case lbAny | prAL<<32:
		return lbAL, LineCanBreak, 310
	case lbAny | prNU<<32:
		return lbNU, LineCanBreak, 310
	case lbAL | prNU<<32:
		return lbNU, LineDontBreak, 230
	case lbDottedCircle | prNU<<32:
		return lbNU, LineDontBreak, 230
	case lbHL | prNU<<32:
		return lbNU, LineDontBreak, 230
	case lbNU | prAL<<32:
		return lbAL, LineDontBreak, 230
	case lbNU | prHL<<32:
		return lbHL, LineDontBreak, 230

	// LB23a.
	case lbAny | prPR<<32:
		return lbPR, LineCanBreak, 310
	case lbAny | prID<<32:
		return lbIDEM, LineCanBreak, 310
	case lbAny | prEB<<32:
		return lbEB, LineCanBreak, 310
	case lbAny | prEM<<32:
		return lbIDEM, LineCanBreak, 310
	case lbPR | prID<<32:
		return lbIDEM, LineDontBreak, 231
	case lbPR | prEB<<32:
		return lbEB, LineDontBreak, 231
	case lbPR | prEM<<32:
		return lbIDEM, LineDontBreak, 231
	case lbIDEM | prPO<<32:
		return lbPO, LineDontBreak, 231
	case lbEB | prPO<<32:
		return lbPO, LineDontBreak, 231

	// LB24.
	case lbAny | prPO<<32:
		return lbPO, LineCanBreak, 310
	case lbPR | prAL<<32:
		return lbAL, LineDontBreak, 240
	case lbPR | prHL<<32:
		return lbHL, LineDontBreak, 240
	case lbPO | prAL<<32:
		return lbAL, LineDontBreak, 240
	case lbPO | prHL<<32:
		return lbHL, LineDontBreak, 240
	case lbAL | prPR<<32:
		return lbPR, LineDontBreak, 240
	case lbAL | prPO<<32:
		return lbPO, LineDontBreak, 240
	case lbDottedCircle | prPR<<32:
		return lbPR, LineDontBreak, 240
	case lbDottedCircle | prPO<<32:
		return lbPO, LineDontBreak, 240
	case lbHL | prPR<<32:
		return lbPR, LineDontBreak, 240
	case lbHL | prPO<<32:
		return lbPO, LineDontBreak, 240

	// LB25 (simple transitions).
	case lbNU | prSY<<32:
		return lbNUSY, LineDontBreak, 130
	case lbNU | prIS<<32:
		return lbNUIS, LineDontBreak, 154
	case lbNU | prCL<<32:
		return lbNUCL, LineDontBreak, 130
	case lbNUSY | prCL<<32:
		return lbNUCL, LineDontBreak, 130
	case lbNUIS | prCL<<32:
		return lbNUCL, LineDontBreak, 130
	case lbNUCL | prPO<<32:
		return lbPO, LineDontBreak, 250
	case lbNU | prCP<<32:
		return lbNUCP, LineDontBreak, 130
	case lbNUSY | prCP<<32:
		return lbNUCP, LineDontBreak, 130
	case lbNUIS | prCP<<32:
		return lbNUCP, LineDontBreak, 130
	case lbNUCP | prPO<<32:
		return lbPO, LineDontBreak, 250
	case lbNUCL | prPR<<32:
		return lbPR, LineDontBreak, 250
	case lbNUCP | prPR<<32:
		return lbPR, LineDontBreak, 250
	case lbNU | prPO<<32:
		return lbPO, LineDontBreak, 250
	case lbNUSY | prPO<<32:
		return lbPO, LineDontBreak, 250
	case lbNUIS | prPO<<32:
		return lbPO, LineDontBreak, 250
	case lbNU | prPR<<32:
		return lbPR, LineDontBreak, 250
	case lbNUSY | prPR<<32:
		return lbPR, LineDontBreak, 250
	case lbNUIS | prPR<<32:
		return lbPR, LineDontBreak, 250
	case lbPO | prNU<<32:
		return lbNU, LineDontBreak, 250
	case lbPR | prNU<<32:
		return lbNU, LineDontBreak, 250
	case lbHY | prNU<<32:
		return lbNU, LineDontBreak, 250
	case lbIS | prNU<<32:
		return lbNU, LineDontBreak, 250
	case lbNU | prNU<<32:
		return lbNU, LineDontBreak, 250
	case lbNUSY | prNU<<32:
		return lbNU, LineDontBreak, 250
	case lbNUIS | prNU<<32:
		return lbNU, LineDontBreak, 250

	// LB26.
	case lbAny | prJL<<32:
		return lbJL, LineCanBreak, 310
	case lbAny | prJV<<32:
		return lbJV, LineCanBreak, 310
	case lbAny | prJT<<32:
		return lbJT, LineCanBreak, 310
	case lbAny | prH2<<32:
		return lbH2, LineCanBreak, 310
	case lbAny | prH3<<32:
		return lbH3, LineCanBreak, 310
	case lbJL | prJL<<32:
		return lbJL, LineDontBreak, 260
	case lbJL | prJV<<32:
		return lbJV, LineDontBreak, 260
	case lbJL | prH2<<32:
		return lbH2, LineDontBreak, 260
	case lbJL | prH3<<32:
		return lbH3, LineDontBreak, 260
	case lbJV | prJV<<32:
		return lbJV, LineDontBreak, 260
	case lbJV | prJT<<32:
		return lbJT, LineDontBreak, 260
	case lbH2 | prJV<<32:
		return lbJV, LineDontBreak, 260
	case lbH2 | prJT<<32:
		return lbJT, LineDontBreak, 260
	case lbJT | prJT<<32:
		return lbJT, LineDontBreak, 260
	case lbH3 | prJT<<32:
		return lbJT, LineDontBreak, 260

	// LB27.
	case lbJL | prPO<<32:
		return lbPO, LineDontBreak, 270
	case lbJV | prPO<<32:
		return lbPO, LineDontBreak, 270
	case lbJT | prPO<<32:
		return lbPO, LineDontBreak, 270
	case lbH2 | prPO<<32:
		return lbPO, LineDontBreak, 270
	case lbH3 | prPO<<32:
		return lbPO, LineDontBreak, 270
	case lbPR | prJL<<32:
		return lbJL, LineDontBreak, 270
	case lbPR | prJV<<32:
		return lbJV, LineDontBreak, 270
	case lbPR | prJT<<32:
		return lbJT, LineDontBreak, 270
	case lbPR | prH2<<32:
		return lbH2, LineDontBreak, 270
	case lbPR | prH3<<32:
		return lbH3, LineDontBreak, 270

	// LB28.
	case lbAL | prAL<<32:
		return lbAL, LineDontBreak, 280
	case lbAL | prHL<<32:
		return lbHL, LineDontBreak, 280
	case lbHL | prAL<<32:
		return lbAL, LineDontBreak, 280
	case lbHL | prHL<<32:
		return lbHL, LineDontBreak, 280
	case lbDottedCircle | prAL<<32:
		return lbAL, LineDontBreak, 280
	case lbDottedCircle | prHL<<32:
		return lbHL, LineDontBreak, 280

	// LB28a (simple transitions).
	case lbAny | prAP<<32:
		return lbAP, LineCanBreak, 310
	case lbAny | prAK<<32:
		return lbAKAS, LineCanBreak, 310
	case lbAny | prAS<<32:
		return lbAKAS, LineCanBreak, 310
	case lbAP | prAK<<32:
		return lbAKAS, LineDontBreak, 281
	case lbAP | prAS<<32:
		return lbAKAS, LineDontBreak, 281
	case lbAKAS | prVF<<32:
		return lbAny, LineDontBreak, 281
	case lbAKAS | prVI<<32:
		return lbAKCircleASVI, LineDontBreak, 281
	case lbAKCircleASVI | prAK<<32:
		return lbAKAS, LineDontBreak, 281

	// LB29.
	case lbIS | prAL<<32:
		return lbAL, LineDontBreak, 290
	case lbIS | prHL<<32:
		return lbHL, LineDontBreak, 290
	case lbNUIS | prAL<<32:
		return lbAL, LineDontBreak, 290
	case lbNUIS | prHL<<32:
		return lbHL, LineDontBreak, 290

	// Transition into QU.
	case lbAny | prQU<<32:
		return lbQU, LineCanBreak, 310

	default:
		return -1, -1, -1
	}
}

// transitionLineBreakState determines the new state of the line break parser
// given the current state and the next code point. It also returns the type of
// line break: LineDontBreak, LineCanBreak, or LineMustBreak. If more than one
// code point is needed to determine the new state, the byte slice or the string
// starting after rune "r" can be used (whichever is not nil or empty) for
// further lookups.
func transitionLineBreakState(state int, r rune, b []byte, str string) (newState int, lineBreak int) {
	// Determine the property of the next character.
	nextProperty, generalCategory := propertyLineBreak(r)

	// Prepare.
	const allBits = lbEastAsianBit | lbZWJBit | lbQUAfterNoEastAsianBit | lbExtPicCnBit | lbPiPfBits
	originalBits := state & allBits
	if state < 0 {
		originalBits = 0
	} else {
		state &^= allBits
	}
	isEastAsian := originalBits&lbEastAsianBit != 0 // Used in LB19a and LB30.
	forceNoBreak := originalBits&lbZWJBit != 0      // LB8a.
	quAfterNoEastAsian := originalBits&lbQUAfterNoEastAsianBit != 0
	extPicCn := originalBits&lbExtPicCnBit != 0
	piPf := originalBits & lbPiPfBits
	isEastAsianProperty := func(r rune) bool {
		ea := propertyEastAsianWidth(r)
		return ea == prF || ea == prW || ea == prH
	}
	nextIsEastAsian := isEastAsianProperty(r)

	// LB1.
	lb1 := func(pr int) int {
		switch pr {
		case prAI, prSG, prXX:
			return prAL
		case prSA:
			if generalCategory == gcMn || generalCategory == gcMc {
				return prCM
			} else {
				return prAL
			}
		case prCJ:
			return prNS
		}
		return pr
	}
	nextProperty = lb1(nextProperty)

	// Lookahead helper function. Returns a slice of properties and their runes
	// for up to "max" code points from the beginning of b or str.
	lookahead := func(max int) ([]int, []rune) {
		strCopy := str
		bCopy := b
		props := make([]int, 0, max)
		runes := make([]rune, 0, max)
		for i := 0; i < max; i++ {
			var (
				r    rune
				size int
			)
			if bCopy != nil {
				r, size = utf8.DecodeRune(bCopy)
			} else {
				r, size = utf8.DecodeRuneInString(strCopy)
			}
			if r == utf8.RuneError {
				break
			}
			pr, _ := propertyLineBreak(r)
			if bCopy != nil {
				bCopy = bCopy[size:]
			} else {
				strCopy = strCopy[size:]
			}
			if pr == prCM || pr == prZWJ {
				max++
				continue // LB9.
			}
			props = append(props, lb1(pr))
			runes = append(runes, r)
		}
		return props, runes
	}

	// Combining marks.
	if nextProperty == prCM || nextProperty == prZWJ {
		var bit int
		if nextProperty == prZWJ {
			bit = lbZWJBit
		}
		bit |= originalBits &^ lbZWJBit
		mustBreakState := state < 0 || state == lbBK || state == lbCR || state == lbLF || state == lbNL
		if !mustBreakState &&
			state != lbSP && state != lbZW && state != lbCLCPSP && state != lbB2SP && state != lbZWSP {
			// LB9.
			return state | bit, LineDontBreak
		} else {
			// LB10.
			if mustBreakState {
				return lbAL | bit, LineMustBreak
			}
			return lbAL | bit, LineCanBreak
		}
	}

	defer func() {
		// Determine if the character is East Asian.
		if nextIsEastAsian {
			newState |= lbEastAsianBit
		}

		// Override break.
		if forceNoBreak {
			lineBreak = LineDontBreak
		}

		// Set Pi/Pf flags.
		switch generalCategory {
		case gcPi:
			newState |= lbIsPi
		case gcPf:
			newState |= lbIsPf
		default:
			if generalCategory != gcPf {
				newState |= lbIsntPf
			} else if generalCategory != gcPi {
				newState |= lbIsntPi
			}
		}
	}()

	// Find the applicable transition in the table.
	var rule int
	newState, lineBreak, rule = lbTransitions(state, nextProperty)
	if newState < 0 {
		// No specific transition found. Try the less specific ones.
		anyPropNewState, anyPropLineBreak, anyPropRule := lbTransitions(state, prAny)
		anyStateNewState, anyStateLineBreak, anyStateRule := lbTransitions(lbAny, nextProperty)
		if anyPropNewState >= 0 && anyStateNewState >= 0 {
			// Both apply. We'll use a mix (see comments for grTransitions).
			newState, lineBreak, rule = anyStateNewState, anyStateLineBreak, anyStateRule
			if anyPropRule < anyStateRule {
				lineBreak, rule = anyPropLineBreak, anyPropRule
			}
		} else if anyPropNewState >= 0 {
			// We only have a specific state.
			newState, lineBreak, rule = anyPropNewState, anyPropLineBreak, anyPropRule
			// This branch will probably never be reached because okAnyState will
			// always be true given the current transition map. But we keep it here
			// for future modifications to the transition map where this may not be
			// true anymore.
		} else if anyStateNewState >= 0 {
			// We only have a specific property.
			newState, lineBreak, rule = anyStateNewState, anyStateLineBreak, anyStateRule
		} else {
			// No known transition. LB31: ALL ÷ ALL.
			newState, lineBreak, rule = lbAny, LineCanBreak, 310
		}
	}

	// LB12a.
	if rule > 121 &&
		nextProperty == prGL &&
		(state != lbSP &&
			state != lbHY &&
			state != lbHH &&
			state != lbLB21a &&
			state != lbCLCPSP &&
			state != lbB2SP) {
		return lbGL, LineDontBreak
	}

	// LB13.
	if rule > 130 && state != lbNU {
		switch nextProperty {
		case prCL:
			return lbCL, LineDontBreak
		case prCP:
			return lbCP, LineDontBreak
		case prSY:
			return lbSY, LineDontBreak
		}
	}

	// LB15a.
	if nextProperty == prQU &&
		generalCategory == gcPi {
		// Part 1.
		newSt := lbLB15a | lbIsPi
		if state < 0 {
			return newSt | lbQUAfterNoEastAsianBit, LineDontBreak // LB2.
		} else if !isEastAsian {
			newSt |= lbQUAfterNoEastAsianBit
		}
		switch state {
		case lbBK, lbCR, lbLF, lbNL:
			return newSt, LineMustBreak // LB4, LB5.
		case lbOP, lbOPSP, lbGL:
			return newSt, LineDontBreak // LB14, LB12.
		case lbQU:
			if isEastAsian {
				return newSt, LineCanBreak // LB31.
			}
			return newSt, LineDontBreak // LB19a.
		case lbSP, lbZWSP, lbZW:
			return newSt, LineCanBreak // LB18, LB8.
		}
	} else if state == lbLB15a {
		if nextProperty == prSP {
			// Part 2.
			return lbLB15a, LineDontBreak // LB7.
		} else {
			// Part 3.
			return newState, LineDontBreak
		}
	}

	// LB15b.
	if rule > 152 && nextProperty == prQU && generalCategory == gcPf {
		applies := len(b) == 0 && str == ""
		if !applies {
			if la, _ := lookahead(1); len(la) > 0 {
				after := la[0]
				applies = after == prSP ||
					after == prGL ||
					after == prWJ ||
					after == prCL ||
					after == prQU ||
					after == prCP ||
					after == prEX ||
					after == prIS ||
					after == prSY ||
					after == prBK ||
					after == prCR ||
					after == prLF ||
					after == prNL ||
					after == prZW
			}
		}
		if applies {
			newState = lbQU
			if state < 0 || !isEastAsian {
				newState |= lbQUAfterNoEastAsianBit
			}
			return newState, LineDontBreak
		}
	}

	// LB15c.
	if rule > 153 && (state == lbSP || state == lbZWSP || state == lbOPSP) && nextProperty == prIS {
		if la, _ := lookahead(1); len(la) > 0 {
			after := la[0]
			if after == prNU {
				return lbIS, LineCanBreak
			}
		}
	}

	// LB19.
	if rule > 190 {
		// First rule.
		if nextProperty == prQU && generalCategory != gcPi {
			newState = lbQU
			if state < 0 || !isEastAsian {
				newState |= lbQUAfterNoEastAsianBit
			}
			return newState, LineDontBreak
		}
		// Second rule.
		if state == lbQU && (piPf == lbIsPi || piPf == lbIsntPf) {
			return newState, LineDontBreak
		}
	}

	// LB19a.
	if rule > 191 {
		if nextProperty == prQU {
			// First rule.
			if state < 0 || !isEastAsian {
				return lbQU | lbQUAfterNoEastAsianBit, LineDontBreak
			}
			// Second rule (eot).
			if len(b) == 0 && str == "" {
				return lbQU, LineDontBreak
			}
			if _, la := lookahead(1); len(la) > 0 {
				// Second rule (not EastAsian).
				if !isEastAsianProperty(la[0]) {
					return lbQU, LineDontBreak
				}
			}
		}
		// Third and fourth rule.
		if state == lbQU && (!nextIsEastAsian || quAfterNoEastAsian) {
			return newState, LineDontBreak
		}
	}

	// LB20a.
	if state == lbLB20a {
		return newState, LineDontBreak
	} else if nextProperty == prHY || nextProperty == prHH {
		if la, _ := lookahead(1); len(la) > 0 {
			after := la[0]
			if after == prAL || after == prHL {
				if state < 0 {
					return lbLB20a, LineDontBreak // LB2.
				}
				switch state {
				case lbBK, lbCR, lbLF, lbNL:
					return lbLB20a, LineMustBreak // LB4, LB5.
				case lbSP, lbZWSP, lbOPSP:
					return lbLB20a, lineBreak // LB8, LB14, LB18.
				case lbZW, lbCB:
					return lbLB20a, LineCanBreak // LB8, LB20.
				case lbGL:
					return lbLB20a, LineDontBreak // LB12.
				}
			}
		}
	}

	// LB21a.
	if state == lbLB21a {
		return newState, LineDontBreak
	}
	if state == lbHL && (nextProperty == prHY || nextProperty == prHH) {
		if la, _ := lookahead(1); len(la) > 0 {
			if la[0] != prHL {
				return lbLB21a, LineDontBreak // LB21.
			}
		}
	}

	// LB25.
	if rule > 250 &&
		(state == lbPR || state == lbPO) &&
		nextProperty == prOP {
		la, _ := lookahead(2)
		if len(la) > 0 {
			switch la[0] {
			case prNU:
				return lbOP, LineDontBreak
			case prIS:
				if len(la) > 1 && la[1] == prNU {
					return lbOP, LineDontBreak
				}
			}
		}
	}

	// LB28a.
	if rule > 281 {
		const dottedCircle = '\u25cc'
		if (state == lbAP || state == lbAKCircleASVI) && r == dottedCircle {
			return lbDottedCircle, LineDontBreak
		}
		if state == lbDottedCircle {
			if nextProperty == prVF {
				return lbAny, LineDontBreak
			}
			if nextProperty == prVI {
				return lbAKCircleASVI, LineDontBreak
			}
		}
		if (state == lbAKAS || state == lbDottedCircle) &&
			(nextProperty == prAK || r == dottedCircle || nextProperty == prAS) {
			if la, _ := lookahead(1); len(la) > 0 {
				if la[0] == prVF {
					if r == dottedCircle {
						return lbDottedCircle, LineDontBreak
					} else {
						return lbAKAS, LineDontBreak
					}
				}
			}
		}
		if r == dottedCircle {
			newState, rule = lbDottedCircle, 310
		}
	}

	// LB30 (part one).
	if rule > 300 {
		if (state == lbAL || state == lbDottedCircle || state == lbHL || state == lbNU) &&
			nextProperty == prOP && !nextIsEastAsian {
			return lbOP, LineDontBreak
		}
		if (state == lbCP || state == lbNUCP) && !isEastAsian {
			switch nextProperty {
			case prAL:
				return lbAL, LineDontBreak
			case prHL:
				return lbHL, LineDontBreak
			case prNU:
				return lbNU, LineDontBreak
			}
		}
	}

	// LB30a.
	if newState == lbAny && nextProperty == prRI {
		if state != lbOddRI && state != lbEvenRI { // Includes state == -1.
			// Transition into the first RI.
			return lbOddRI, lineBreak
		}
		if state == lbOddRI {
			// Don't break pairs of Regional Indicators.
			return lbEvenRI, LineDontBreak
		}
		return lbOddRI, lineBreak
	}

	// LB30b.
	if rule > 302 {
		if nextProperty == prEM {
			if state == lbEB || extPicCn {
				return lbAny, LineDontBreak
			}
		}
		graphemeProperty := propertyGraphemes(r)
		if graphemeProperty == prExtendedPictographic && generalCategory == gcCn {
			return newState | lbExtPicCnBit, LineCanBreak
		}
	}

	return
}
