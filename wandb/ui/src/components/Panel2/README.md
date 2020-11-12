## Next generation panels

This directory contains work in progress for artifact visualization, including dataset and prediction visualization.

We use the unifying concept of a "panel", which is a generic interface for visualization and control components. Panels may render other panels inside of themselves.

The panel interface consists of
- context: a globally shared type, that stores information about the page state.
  - parts of context are selectively overridden by parent panels, to control how children render
  - panels may update the context. In this way, panels can interact with eachother.
  - there is typically some query in the context, which panels may modify and use to fetch data
- config: a panel's internal state, typed specifically for each panel
  - panel configs are usually user editable via UI that the panel renders
  - panel configs should be independent of context. E.g. a panel config should not store individual data ids (like artifact ids). this way a panel can be configured once and work as the context changes.
- update functions to update the context and config

A panel spec consists of three items:
- type: a unique string for this panel type
- available: a function that should return whether the panel is available for a given context
- Comp: a react component that implements the panel interface

This is the same interface that we use in panels.tsx in our main app. It's reproduced (and simplified) here to speed iteration. We'll merge this with the main codebase once stable.