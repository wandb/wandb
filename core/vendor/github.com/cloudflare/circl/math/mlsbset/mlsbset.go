// Package mlsbset provides a constant-time exponentiation method with precomputation.
//
// References: "Efficient and secure algorithms for GLV-based scalar
// multiplication and their implementation on GLV–GLS curves" by (Faz-Hernandez et al.)
//   - https://doi.org/10.1007/s13389-014-0085-7
//   - https://eprint.iacr.org/2013/158
package mlsbset

import (
	"errors"
	"fmt"
)

// EltG is a group element.
type EltG interface{}

// EltP is a precomputed group element.
type EltP interface{}

// Group defines the operations required by MLSBSet exponentiation method.
type Group interface {
	Identity() EltG                    // Returns the identity of the group.
	Sqr(x EltG)                        // Calculates x = x^2.
	Mul(x EltG, y EltP)                // Calculates x = x*y.
	NewEltP() EltP                     // Returns an arbitrary precomputed element.
	ExtendedEltP() EltP                // Returns the precomputed element x^(2^(w*d)).
	Lookup(a EltP, v uint, s, u int32) // Sets a = s*T[v][u].
}

// Params contains the parameters of the encoding.
type Params struct {
	T uint // T is the maximum size (in bits) of exponents.
	V uint // V is the number of tables.
	W uint // W is the window size.
	E uint // E is the number of digits per table.
	D uint // D is the number of digits in total.
	L uint // L is the length of the code.
}

// Encoder allows to convert integers into valid powers.
type Encoder struct{ p Params }

// New produces an encoder of the MLSBSet algorithm.
func New(t, v, w uint) (Encoder, error) {
	if !(t > 1 && v >= 1 && w >= 2) {
		return Encoder{}, errors.New("t>1, v>=1, w>=2")
	}
	e := (t + w*v - 1) / (w * v)
	d := e * v
	l := d * w
	return Encoder{Params{t, v, w, e, d, l}}, nil
}

// Encode converts an odd integer k into a valid power for exponentiation.
func (m Encoder) Encode(k []byte) (*Power, error) {
	if len(k) == 0 {
		return nil, errors.New("empty slice")
	}
	if !(len(k) <= int(m.p.L+7)>>3) {
		return nil, errors.New("k too big")
	}
	if k[0]%2 == 0 {
		return nil, errors.New("k must be odd")
	}
	ap := int((m.p.L+7)/8) - len(k)
	k = append(k, make([]byte, ap)...)
	s := m.signs(k)
	b := make([]int32, m.p.L-m.p.D)

	// Original algorithm starts with c := k >> D, then computes
	//
	//	  b_(i-D) = s_(i%D) * lsb(c)
	//	  c = [ (c>>1)+1   if b_(i-D) = -1
	//		  [ c>>1       otherwise
	//
	// To prevent keeping a large k around, we note that at any step i we have
	//
	//	  c = (k >> i) + t		for t in {0,1}
	//
	// Base case is obvious. For induction, write kbit for the i-th bit of k.
	// Note lsb(c) = kbit ^ t. From that we can compute b_(i-D). Now we need
	// to compute the next t.
	//
	// Consider c >> 1 = (k >> i) + t) >> 1. This equals k >> (i+1)
	// unless t = 1 = kbit.
	//
	// If b_(i-D) is negative, then we must have had 1=lsb(c)=kbit^t, and so
	// c >> 1 = k >> (i+1), as desired with new t equal to 1.
	// For the other case assume b_(i-D) isn't negative. Now it is possible
	// that t = 1 = kbit, and only in that case the new t is equal to 1.
	var t uint64
	for i := m.p.D; i < m.p.L; i++ {
		si := s[i%m.p.D]
		kbit := uint64(k[i>>3]>>(i&7)) & 1
		lsbc := kbit ^ t
		neg := uint64(si>>31) & 1 // 1 iff si == -1
		b[i-m.p.D] = si * int32(lsbc)
		t = (kbit & t) | (lsbc & neg)
	}
	// carry = (k >> L) + t: any bits of k at positions >= L (present when L is
	// not a multiple of 8) plus the final carry, matching the original.
	carry := int(t)
	for pos := m.p.L; int(pos>>3) < len(k); pos++ {
		carry += int((k[pos>>3]>>(pos&7))&1) << (pos - m.p.L)
	}
	return &Power{m, s, b, carry}, nil
}

// signs calculates the set of signs.
func (m Encoder) signs(k []byte) []int32 {
	s := make([]int32, m.p.D)
	s[m.p.D-1] = 1
	for i := uint(1); i < m.p.D; i++ {
		ki := int32((k[i>>3] >> (i & 0x7)) & 0x1)
		s[i-1] = 2*ki - 1
	}
	return s
}

// GetParams returns the complementary parameters of the encoding.
func (m Encoder) GetParams() Params { return m.p }

// tableSize returns the size of each table.
func (m Encoder) tableSize() uint { return 1 << (m.p.W - 1) }

// Elts returns the total number of elements that must be precomputed.
func (m Encoder) Elts() uint { return m.p.V * m.tableSize() }

// IsExtended returns true if the element x^(2^(wd)) must be calculated.
func (m Encoder) IsExtended() bool { q := m.p.T / (m.p.V * m.p.W); return m.p.T == q*m.p.V*m.p.W }

// Ops returns the number of squares and multiplications executed during an exponentiation.
func (m Encoder) Ops() (S uint, M uint) {
	S = m.p.E
	M = m.p.E * m.p.V
	if m.IsExtended() {
		M++
	}
	return
}

func (m Encoder) String() string {
	return fmt.Sprintf("T: %v W: %v V: %v e: %v d: %v l: %v wv|t: %v",
		m.p.T, m.p.W, m.p.V, m.p.E, m.p.D, m.p.L, m.IsExtended())
}
