<!-- template:define:options
{
  "nodescription": true
}
-->
<img title="Logo" src="./examples/_images/logo.png" width="961">

<!-- template:begin:header -->
<!-- do not edit anything in this "template" block, its auto-generated -->

<p align="center">
  <a href="https://github.com/lrstanley/bubblezone/tags">
    <img title="Latest Semver Tag" src="https://img.shields.io/github/v/tag/lrstanley/bubblezone?style=flat-square">
  </a>
  <a href="https://github.com/lrstanley/bubblezone/commits/master">
    <img title="Last commit" src="https://img.shields.io/github/last-commit/lrstanley/bubblezone?style=flat-square">
  </a>



  <a href="https://github.com/lrstanley/bubblezone/actions?query=workflow%3Atest+event%3Apush">
    <img title="GitHub Workflow Status (test @ master)" src="https://img.shields.io/github/actions/workflow/status/lrstanley/bubblezone/test.yml?branch=master&label=test&style=flat-square">
  </a>



  <a href="https://codecov.io/gh/lrstanley/bubblezone">
    <img title="Code Coverage" src="https://img.shields.io/codecov/c/github/lrstanley/bubblezone/master?style=flat-square">
  </a>

  <a href="https://pkg.go.dev/github.com/lrstanley/bubblezone">
    <img title="Go Documentation" src="https://pkg.go.dev/badge/github.com/lrstanley/bubblezone?style=flat-square">
  </a>
  <a href="https://goreportcard.com/report/github.com/lrstanley/bubblezone">
    <img title="Go Report Card" src="https://goreportcard.com/badge/github.com/lrstanley/bubblezone?style=flat-square">
  </a>
</p>
<p align="center">
  <a href="https://github.com/lrstanley/bubblezone/issues?q=is:open+is:issue+label:bug">
    <img title="Bug reports" src="https://img.shields.io/github/issues/lrstanley/bubblezone/bug?label=issues&style=flat-square">
  </a>
  <a href="https://github.com/lrstanley/bubblezone/issues?q=is:open+is:issue+label:enhancement">
    <img title="Feature requests" src="https://img.shields.io/github/issues/lrstanley/bubblezone/enhancement?label=feature%20requests&style=flat-square">
  </a>
  <a href="https://github.com/lrstanley/bubblezone/pulls">
    <img title="Open Pull Requests" src="https://img.shields.io/github/issues-pr/lrstanley/bubblezone?label=prs&style=flat-square">
  </a>
  <a href="https://github.com/lrstanley/bubblezone/discussions/new?category=q-a">
    <img title="Ask a Question" src="https://img.shields.io/badge/support-ask_a_question!-blue?style=flat-square">
  </a>
  <a href="https://liam.sh/chat"><img src="https://img.shields.io/badge/discord-bytecord-blue.svg?style=flat-square" title="Discord Chat"></a>
</p>
<!-- template:end:header -->

<!-- template:begin:toc -->
<!-- do not edit anything in this "template" block, its auto-generated -->
## :link: Table of Contents

  - [Problem](#x-problem)
  - [Solution](#heavy_check_mark-solution)
  - [Features](#sparkles-features)
  - [Usage](#gear-usage)
  - [Examples](#clap-examples)
    - [List example](#list-example)
    - [Lipgloss full example](#lipgloss-full-example)
  - [Tips](#memo-tips)
    - [Overlapping markers](#overlapping-markers)
    - [Use lipgloss.Width](#use-lipglosswidth)
    - [MaxHeight and MaxWidth](#maxheight-and-maxwidth)
    - [Only scan at the root model](#only-scan-at-the-root-model)
    - [Organic shapes](#organic-shapes)
  - [Support &amp; Assistance](#raising_hand_man-support--assistance)
  - [Contributing](#handshake-contributing)
  - [License](#balance_scale-license)
<!-- template:end:toc -->

## :x: Problem

[BubbleTea](https://github.com/charmbracelet/bubbletea) and [lipgloss](https://github.com/charmbracelet/lipgloss)
allow you to build extremely fast terminal interfaces, in a semantic and scalable
way. Through abstracting layout, colors, events, and more, it's very easy to build
a user-friendly application. BubbleTea also supports mouse events, either through
the "basic" mouse events, like `MouseButtonLeft`, `MouseButtonRight`, `MouseButtonWheelUp` and
`MouseButtonWheelDown` ([and more](https://github.com/charmbracelet/bubbletea/blob/0a0182e55a30e85640a53b8e01dc9ef06824cce5/mouse.go#L38-L48)),
or through full motion tracking, allowing hover and mouse movement tracking.

This works great for a single-component application, where the state is managed in one
location. However, when you start expanding your application, where components have
various children, and those children have children, calculating mouse events like
`MouseButtonLeft` and `MouseButtonRight` and determining which component was clicked
becomes complicated, and rather tedious.

## :heavy_check_mark: Solution

**BubbleZone** is one solution to this problem. BubbleZone allows you to wrap your
components in **zero-printable-width** (to not impact `lipgloss.Width()` calculations)
identifiers. Additionally, there is a scan method that wraps the entire application,
stores the offsets of those identifiers as `zones`, and then removes them from
the resulting output.

Any time there is a mouse event, pass it down to all children, thus allowing you
to easily check if the event is within the bounds of the components `zone`. This
makes it very simple to do things like focusing on various components, clicking
"buttons", and more. Take a look at this example, where I didn't have to calculate
where the mouse was being clicked, and which component was under the mouse:

![bubblezone example](https://cdn.liam.sh/share/2022/07/WindowsTerminal_XxiuWQ2hVL.gif)

## :sparkles: Features

- :heavy_check_mark: It's **_fast_** -- given it has to process this information for every render, I
  tried to focus on performance where possible. If you see where improvements can
  be made, let me know!
- :heavy_check_mark: It doesn't impact width calculations when using `lipgloss.Width()` (if you're
  using `len()` it will).
- :heavy_check_mark: It's simple -- easily determine offset or if an event was within the bounds of
  a zone.
- :heavy_check_mark: Want the mouse event position relative to the component? Easy!
- :heavy_check_mark: Provides an _optional_ global manager, when you have full access to all components,
  so you don't have to inject it as a dependency to all components.

---

## :gear: Usage

<!-- template:begin:goget -->
<!-- do not edit anything in this "template" block, its auto-generated -->
```console
go get -u github.com/lrstanley/bubblezone@latest
```
<!-- template:end:goget -->

BubbleZone supports either a global zone manager (initialized via `NewGlobal()`),
or non-global (via `New()`). Using the global zone manager, simply use `zone.<method>`.
The below examples will use the global manager.

Initialize the zone manager:

```go
package main

import (
	// [...]
	zone "github.com/lrstanley/bubblezone"
)


func main() {
	// [...]
	zone.NewGlobal()
	// If the UI will be closed at some point and the application will still run,
	// use zone.Close() to stop all background workers:
	// defer zone.Close()
	//
	// [...]
	//
	// Initialize your application here.
}
```

Ensure the mouse is enabled and the program is running in alt screen mode (i.e. full window mode).

```go
func main() {
	// [...]
	p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())
	// [...]
}
```

In your root model, wrap your `View()` output in `zone.Scan()`, which will register
and monitor all zones, including stripping the ANSI sequences injected by `zone.Mark()`.

```go
func (r app) View() string {
	// [...]
	return zone.Scan(r.someStyle.Render(generatedChildViews))
}
```

In your children models `View()` method, use `zone.Mark()` to wrap the area you want
to mark as a zone. Make sure you give the zone a unique ID (see also: [tips: overlapping markers](#overlapping-markers)):

```go
func (m model) View() string {
	// [...]
	buttons := lipgloss.JoinHorizontal(
		lipgloss.Top,
		zone.Mark("confirm", okButton),
		zone.Mark("cancel", cancelButton),
	)
	return m.someStyle.Render(buttons)
}
```

In your children models `Update()` method, use `zone.Get(<id>).InBounds(mouseMsg)` to
check if the mouse event was in the bounds of the zone:

```go
func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	// [...]
	case tea.MouseMsg:
		if msg.Action != tea.MouseActionRelease || msg.Button != tea.MouseButtonLeft {
			return m, nil
		}

		if zone.Get("confirm").InBounds(msg) {
			// Do something if it's in bounds, e.g. toggling a model flag to let
			// View() know to change its highlight colors.
			m.active = "confirm"
		} else if zone.Get("cancel").InBounds(msg) {
			m.active = "cancel"
		}

		// x, y := zone.Get("confirm").Pos() can be used to get the relative
		// coordinates within the zone. Useful if you need to move a cursor in a
		// input box as an example.

		return m, nil
	}
	return m, nil
}
```

... and that's it!

---

## :clap: Examples

### List example

- All titles are marked as a unique zone, and upon left click, that item is focused.
- [Example source](./examples/list-default/main.go).

![list-default example](https://cdn.liam.sh/share/2022/07/WindowsTerminal_SelC1Vzdas.gif)

### Lipgloss full example

- All items are marked as a unique zone (uses `NewPrefix()` as well).
- Child models are used, and the resulting mouse events are passed down to each
  model.
- [Example source](./examples/full-lipgloss).

![full-lipgloss example](https://cdn.liam.sh/share/2022/07/WindowsTerminal_tirP0rGZ2z.gif)

---

## :memo: Tips

Below are a couple of tips to ensure you have the best experience using BubbleZone.

### Overlapping markers

To prevent overlapping marker ID's in child components, use `NewPrefix()` which
will generate a guaranteed-unique prefix you can use in combination with your
regular IDs.

### Use lipgloss.Width

Use `lipgloss.Width()` for width measurements, rather than `len()` or similar.
BubbleZone has been specifically designed so that markers will be ignored by
`lipgloss.Width()` (in addition to this being the recommended width checking
method even if you're not using BubbleZone, as `len()` breaks with fg/bg colors,
and other control characters).

### MaxHeight and MaxWidth

`MaxHeight()` and `MaxWidth()` do a hard-trim of characters to enforce a specific
height and width. As such, if a child component is wrapped in a zone, and overlaps
the maximum height/width, the zone will break, and standard bounds checks
**will not work**. Due to this, it is recommended to ensure `MaxHeight` and
`MaxWidth()` are only enforcing limits that should already be set by normal
height/width limits on your components (i.e. just don't exceed the max viewport
dimensions 😅).

### Only scan at the root model

Make sure `zone.Scan()` is only used at the root level model, it will likely not
work as you intend it in any other situation.

### Organic shapes

BubbleZones `InBounds()` checks calculate bounds based on a box region. For
example, if you have a model that generates a large circle, make sure the zone
is properly padded (e.g. `lipgloss.Place()` or similar), to capture the entire
circle. Though note that because it checks for the entire box, a mouse event
will still be considered in bounds if the outer corners outside of the circle
are clicked.

Example:

![bounding box](https://cdn.liam.sh/share/2022/07/dxehJb52R5.png)

---

<!-- template:begin:support -->
<!-- do not edit anything in this "template" block, its auto-generated -->
## :raising_hand_man: Support & Assistance

* :heart: Please review the [Code of Conduct](.github/CODE_OF_CONDUCT.md) for
     guidelines on ensuring everyone has the best experience interacting with
     the community.
* :raising_hand_man: Take a look at the [support](.github/SUPPORT.md) document on
     guidelines for tips on how to ask the right questions.
* :lady_beetle: For all features/bugs/issues/questions/etc, [head over here](https://github.com/lrstanley/bubblezone/issues/new/choose).
<!-- template:end:support -->

<!-- template:begin:contributing -->
<!-- do not edit anything in this "template" block, its auto-generated -->
## :handshake: Contributing

* :heart: Please review the [Code of Conduct](.github/CODE_OF_CONDUCT.md) for guidelines
     on ensuring everyone has the best experience interacting with the
    community.
* :clipboard: Please review the [contributing](.github/CONTRIBUTING.md) doc for submitting
     issues/a guide on submitting pull requests and helping out.
* :old_key: For anything security related, please review this repositories [security policy](https://github.com/lrstanley/bubblezone/security/policy).
<!-- template:end:contributing -->

<!-- template:begin:license -->
<!-- do not edit anything in this "template" block, its auto-generated -->
## :balance_scale: License

```
MIT License

Copyright (c) 2022 Liam Stanley <liam@liam.sh>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

_Also located [here](LICENSE)_
<!-- template:end:license -->
