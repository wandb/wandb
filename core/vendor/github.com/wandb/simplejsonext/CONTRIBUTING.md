# Contributing
## Getting Started
1. Fork the repository on GitHub.
2. Clone the forked repository to your working environment.
3. Ensure you have a working go interpreter, preferably [of the newest release](https://go.dev/doc/install).

## How to Contribute
1. **Bug Reports**: If you find a bug, please open an issue on GitHub with a clear description of the problem, and include any relevant logs, screenshots, or code samples.
2. **Feature Requests**: If you have an idea for a new feature or improvement, please open an issue on GitHub with a detailed explanation of the feature, its benefits, and any proposed implementation details.
3. **Code Contributions**: If you'd like to contribute code directly, follow these steps:
   - Make sure you've set up the development environment as described above.
   - Create a new branch for your feature or bugfix. Use a descriptive branch name, such as `feature/new-feature` or `bugfix/issue-123`.
   - Make your changes, following the existing code style and conventions.
   - Add tests for your changes to ensure they work correctly and maintain compatibility with existing code.
   - Run tests and ensure they pass.
   - Update the documentation as necessary to reflect your changes.
   - Commit your changes with a clear and concise commit message.
   - Push your changes to your fork on GitHub.
   - Create a pull request from your fork to the main repository. In the pull request description, provide an overview of your changes, any relevant issue numbers, and a summary of the testing you've performed.
   - Address any feedback or requested changes from the project maintainers.

## Code standards
Tests are configured on github actions, but are easy to run locally. Here's a simple checklist we want to reach for pull requests and general contributions:
* Tests should pass!
* The [linter](https://golangci-lint.run/usage/install/) should pass (`golangci-lint run`)
* Ideally, we want to preserve the library with zero non-test dependencies outside the standard library.

We welcome feature requests and contributions for consideration, subject to the [code of conduct](/CODE_OF_CONDUCT.md).

## Code of Conduct
Please be respectful and considerate of other contributors. We are committed to fostering a welcoming and inclusive community. Harassment, discrimination, and offensive behavior will not be tolerated. By participating in this project, you agree to adhere to these principles. Refer also to the explicit code of conduct in [`CODE_OF_CONDUCT.md`](/CODE_OF_CONDUCT.md).

## Contact
If you have any questions, concerns, or need assistance, please reach out to the project maintainers through GitHub or the official communication channels.

Thank you for your interest in contributing!
