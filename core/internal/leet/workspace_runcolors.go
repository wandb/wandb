package leet

import (
	"fmt"
	"image/color"
	"math"
	"strings"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
)

const (
	workspaceRunColorVariantPhases  = 6
	workspaceRunColorHueStep        = 17.0
	workspaceRunColorLightnessStep  = 0.035
	workspaceRunColorSaturationStep = 0.05
	maxWorkspaceRunColorVariants    = 256
)

// workspaceRunColors assigns stable, non-colliding colors to workspace runs.
//
// Each run path is anchored to its original hashed palette color. Collisions are
// resolved by generating nearby color variants that stay visually close to the
// palette while remaining unique within the current workspace.
//
// The workspace owns this allocator on the Bubble Tea update goroutine, so it
// does not require internal locking.
type workspaceRunColors struct {
	palette  []compat.AdaptiveColor
	assigned map[string]compat.AdaptiveColor // run path -> color
	used     map[string]string               // serialized color -> run path
}

func newWorkspaceRunColors(palette []compat.AdaptiveColor) *workspaceRunColors {
	if len(palette) == 0 {
		palette = GraphColors(DefaultColorScheme)
	}
	return &workspaceRunColors{
		palette:  append([]compat.AdaptiveColor(nil), palette...),
		assigned: make(map[string]compat.AdaptiveColor),
		used:     make(map[string]string),
	}
}

// Assign returns the stable color for runPath, allocating one if needed.
func (a *workspaceRunColors) Assign(runPath string) compat.AdaptiveColor {
	if c, ok := a.assigned[runPath]; ok {
		return c
	}

	c := a.pickColor(runPath)
	a.assigned[runPath] = c
	a.used[workspaceRunColorKey(c)] = runPath
	return c
}

// Release forgets the color assignment for runPath so the color can be reused.
func (a *workspaceRunColors) Release(runPath string) {
	c, ok := a.assigned[runPath]
	if !ok {
		return
	}
	delete(a.assigned, runPath)

	key := workspaceRunColorKey(c)
	if owner, ok := a.used[key]; ok && owner == runPath {
		delete(a.used, key)
	}
}

func (a *workspaceRunColors) pickColor(runPath string) compat.AdaptiveColor {
	base := a.palette[colorIndex(runPath, len(a.palette))]
	if a.isAvailable(base, runPath) {
		return base
	}

	for step := 1; step <= maxWorkspaceRunColorVariants; step++ {
		candidate := workspaceRunColorVariant(base, step)
		if a.isAvailable(candidate, runPath) {
			return candidate
		}
	}

	return base
}

func (a *workspaceRunColors) isAvailable(
	c compat.AdaptiveColor,
	runPath string,
) bool {
	owner, ok := a.used[workspaceRunColorKey(c)]
	return !ok || owner == runPath
}

func workspaceRunColorKey(c compat.AdaptiveColor) string {
	return normalizeWorkspaceRunColorComponent(c.Light) +
		"|" +
		normalizeWorkspaceRunColorComponent(c.Dark)
}

func normalizeWorkspaceRunColorComponent(component any) string {
	componentText := fmt.Sprint(component)
	if r, g, b, ok := parseHexColor(componentText); ok {
		return fmt.Sprintf("#%02X%02X%02X", r, g, b)
	}
	return strings.ToLower(componentText)
}

func workspaceRunColorVariant(base compat.AdaptiveColor, step int) compat.AdaptiveColor {
	if step <= 0 {
		return base
	}

	ring := 1 + (step-1)/workspaceRunColorVariantPhases
	phase := (step - 1) % workspaceRunColorVariantPhases

	hueShift := float64(ring) * workspaceRunColorHueStep
	if phase%2 == 1 {
		hueShift = -hueShift
	}

	lightnessDelta := 0.0
	saturationDelta := 0.0
	magnitude := float64(ring)

	switch phase {
	case 0:
		lightnessDelta = workspaceRunColorLightnessStep * magnitude
	case 1:
		lightnessDelta = -workspaceRunColorLightnessStep * magnitude
	case 2:
		saturationDelta = workspaceRunColorSaturationStep * magnitude
	case 3:
		saturationDelta = -workspaceRunColorSaturationStep * magnitude
	case 4:
		lightnessDelta = 0.5 * workspaceRunColorLightnessStep * magnitude
		saturationDelta = 0.5 * workspaceRunColorSaturationStep * magnitude
	case 5:
		lightnessDelta = -0.5 * workspaceRunColorLightnessStep * magnitude
		saturationDelta = -0.5 * workspaceRunColorSaturationStep * magnitude
	}

	return compat.AdaptiveColor{
		Light: adjustWorkspaceRunColor(base.Light, hueShift, saturationDelta, lightnessDelta),
		Dark:  adjustWorkspaceRunColor(base.Dark, hueShift, saturationDelta, lightnessDelta),
	}
}

func adjustWorkspaceRunColor(
	base any,
	hueShift, saturationDelta, lightnessDelta float64,
) color.Color {
	r, g, b, ok := parseHexColor(fmt.Sprint(base))
	if !ok {
		return lipgloss.Color(fmt.Sprint(base))
	}

	h, s, l := rgbToHSL(r, g, b)
	h = wrapHue(h + hueShift)
	s = clamp01(s + saturationDelta)
	l = clamp01(l + lightnessDelta)

	r2, g2, b2 := hslToRGB(h, s, l)
	return lipgloss.Color(fmt.Sprintf("#%02X%02X%02X", r2, g2, b2))
}

func rgbToHSL(r, g, b uint8) (h, s, l float64) {
	rf := float64(r) / 255.0
	gf := float64(g) / 255.0
	bf := float64(b) / 255.0

	maxC := max(rf, max(gf, bf))
	minC := min(rf, min(gf, bf))
	l = (maxC + minC) / 2

	if maxC == minC {
		return 0, 0, l
	}

	delta := maxC - minC
	if l > 0.5 {
		s = delta / (2 - maxC - minC)
	} else {
		s = delta / (maxC + minC)
	}

	switch maxC {
	case rf:
		h = (gf - bf) / delta
		if gf < bf {
			h += 6
		}
	case gf:
		h = (bf-rf)/delta + 2
	default:
		h = (rf-gf)/delta + 4
	}

	h *= 60
	return h, s, l
}

func hslToRGB(h, s, l float64) (uint8, uint8, uint8) {
	h = wrapHue(h) / 360.0
	if s == 0 {
		gray := uint8(math.Round(l * 255.0))
		return gray, gray, gray
	}

	var q float64
	if l < 0.5 {
		q = l * (1 + s)
	} else {
		q = l + s - l*s
	}
	p := 2*l - q

	r := hueToRGB(p, q, h+1.0/3.0)
	g := hueToRGB(p, q, h)
	b := hueToRGB(p, q, h-1.0/3.0)

	return uint8(math.Round(r * 255.0)),
		uint8(math.Round(g * 255.0)),
		uint8(math.Round(b * 255.0))
}

func hueToRGB(p, q, t float64) float64 {
	for t < 0 {
		t += 1
	}
	for t > 1 {
		t -= 1
	}

	switch {
	case t < 1.0/6.0:
		return p + (q-p)*6*t
	case t < 1.0/2.0:
		return q
	case t < 2.0/3.0:
		return p + (q-p)*(2.0/3.0-t)*6
	default:
		return p
	}
}

func wrapHue(h float64) float64 {
	h = math.Mod(h, 360)
	if h < 0 {
		h += 360
	}
	return h
}

func clamp01(v float64) float64 {
	return min(max(v, 0), 1)
}
