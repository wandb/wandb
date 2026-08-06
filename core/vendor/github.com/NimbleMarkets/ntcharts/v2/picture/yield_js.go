//go:build js

package picture

import "time"

// yieldToJS gives the JavaScript event loop a slice so pending fetch
// promise resolutions and DOM events can drain between CPU-heavy steps
// in the Kitty render goroutine (CatmullRom scale + PNG encode). On Go
// WASM (GOOS=js), time.Sleep with a positive duration schedules a
// setTimeout that returns control to JS until the timer fires; 1ms is
// the minimum reliably-effective resolution (sub-ms durations may round
// down to 0 and short-circuit without yielding).
func yieldToJS() { time.Sleep(time.Millisecond) }
