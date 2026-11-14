# Mock host for the LEET panel

`mockhost.html` renders `../panel.html` the way an MCP host that supports apps does, fed from recorded results: `view.json` is the structuredContent of a `leet_view` call with keys `train/loss` and `val/loss` and `history-<run key>.json` the structuredContent of `leet_history` with those keys and 20 bins for the three runs the panel charts first (any other run key falls back to the first recording). Serve this directory's parent and open the page: `cd core/internal/leetmcp && python3 -m http.server 8765`, then http://localhost:8765/testdata/mockhost.html.
