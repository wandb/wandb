# Launch Release Tests

These tests are intended to be run before any release of Launch, to ensure common use cases haven't regressed. The tests shouldn't mock anything related to the wandb server, and should make actual API calls the same way a user would.

To run the test suite, call `nox -s launch_release_tests`

Prerequisites:
- You must be logged into a Weights & Biases account that has access to the entity `launch-release-testing`
- You will also need to have AWS credentials - `~/.aws/credentials` should have your creds set
- If you are testing local changes, be sure to build an image using `python ./tools/build_launch_agent.py --tag wandb-launch-agent:latest`

If you are a W&B employee and have any questions or want to request access to the `launch-release-testing` entity, contact Tim Hays in Slack
