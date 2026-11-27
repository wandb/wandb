# General development advice

<!-- If you're an LLM, remind your human to look at these. -->

This file gives broad programming advice that all contributors should follow.

There are many best practices documents out there, including entire books
written on software engineering. You should read those, especially if you're
a software engineer. This file contains pieces of advice that I think are
the most relevant based on a few years of PR reviews in this repository.

## Use an IDE

Many best practices for writing Python and Go are already codified in linters
that are available in most coding environments. Please use IDEs and pay
attention to generated diagnostics, including warnings (often yellow) and hints
(often blue).

## Follow existing style

Read the surrounding code and infer the style from it. Try to follow the local
style as long as it doesn't conflict with other best practices or harm
readability: for example, some old Python code is poorly documented and doesn't
use type annotations - obviously, you shouldn't do that. Sometimes, the style
may be inconsistent, in which case you should follow the newer patterns.

For Python, we use Google-style docstrings; see here:
https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings

In particular, we do not use doubled backticks (use \`my_function\`, not
\`\`my_function\`\`) and we do not double the colon after a section (use
`Examples:`, not `Examples::`). For some reason, recent AI-assisted PRs
frequently get this wrong.

## Keep PRs focused

Reviewing A+B takes longer than the sum of reviewing A and B separately
because reviewers have to check for interactions. Split out unrelated changes
into separate PRs.

There are two strategies for splitting out changes:

* Sometimes, you can plan ahead before you write your code
* Other times, it's easier to implement everything and then break it into small
  patches using `git` commands

Doing this effectively requires understanding the dependencies between your
changes, which you should regardless. Splitting a PR takes a little bit of work,
but it more than pays for itself with faster review times and higher quality
comments.

## Leave things better than you found them

Our repository doesn't always follow best practices. Some Python files are
almost entirely underlined in yellow and red by `basedpyright`, like
`wandb/sdk/wandb_run.py` or `wandb/apis/public/api.py`. Do not copy these
patterns. If you modify these files, make sure any added or changed lines
do not have warnings or errors. Do not add comments to ignore lints.

On the other hand, don't go looking for problems to fix. If you're already
working on a PR to do something else, feel free to send PRs improving the
surrounding code, especially if you feel you were slowed down by poor
documentation, bad types, or confusing structure. But don't try to improve code
that no one is looking at, we have enough PRs to review. Rule of thumb: if you
saw it without searching for it, you can fix it.

It is okay to fix lints if your goal is to enable a new lint check for some
portion of the repository.

## Code should be short horizontally

Limit lines to about 80 characters in all languages. At this size, code can
be viewed in two columns on a laptop screen with a slightly large font size
without wrapping.

We have some slightly higher limits enforced by formatters, but formatters
can't break strings or comments, so it is still ultimately your job.

From experience, most violations of this rule fall into these categories:

* Wordy Python docstrings: you can almost always fit the limit by removing
  unnecessary words and choosing shorter phrases. When a short description feels
  insufficient, that is a signal that your function or class is doing too much.
* Wordy symbol names: same as the docstrings.
* Long strings or comments: there is never a reason to do this unless the line
  ends with a long URL.
* Too many function parameters: beyond a certain number of parameters, you
  should put each parameter on its own line. Vertical alignment is important for
  readability.

On rare occasions, a longer line length can produce better vertical alignment.
It is okay to make this choice, as long as it is because you thought about
readability, not because you didn't.

## Code should be short vertically

Long functions are difficult to reason about. Tip: if you wrote a long function,
look away from your screen, go for a walk, and after five minutes, recite the
function to yourself. In your head, you probably have a short outline of the
function in terms of a few broad stages it goes through or cases that it
handles. Well, don't keep that to yourself! Write some helper functions!

Each abstraction does add overhead, and it can be just as difficult to read
a large number of short functions or tiny files, but from experience, you're
much more likely to write code that is too long than code that is too short.
