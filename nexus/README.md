# W&B Nexus: the new "bones" for the W&B SDK

## What is Nexus

Greetings, developers! Let's dive right in!

What is W&B Nexus? At the highest level, Nexus is the new "bones" for the W&B SDK.
Why would anyone care and want to use it? There are numerous reasons, but here are just two:
- It's faster. A lot faster. We're talking 10x faster for some operations.
- It enables clean multi-language support.

For those technical folks out there, `nexus` is a Golang reimplementation of the W&B SDK
internal process, `wandb service`, based on the lessons learned from the original implementation(s),
but starting from a clean slate.

## Installation


## Feature Parity Status

The following table shows the current status of feature parity between the current W&B SDK.

Status legend:
✅: Available: The feature is relatively stable and ready for use
🚧: In Development:: The feature is available, but might lack some functionality
📝: Todo:: The feature has not entered development yet.

| Category   | Feature   | Status   | Notes  |
|------------|-----------|----------|--------|
| Run        |           |          |        |
|            | init      | ✅        |        |
|            | log       | ✅        |        |
|            | config    | ✅        |        |
| Artifacts  |           |          |        |
| Public API |           |          |        |

## Contributing

Please read our [contributing guide](docs/contributing.md) to learn to set up
your development environment and how to contribute to the codebase.
