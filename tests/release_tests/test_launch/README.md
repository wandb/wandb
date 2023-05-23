# Launch Release Tests

These tests are intended to be run before any release of Launch, to ensure common use cases haven't regressed. The tests shouldn't mock anything related to the wandb server, and should make actual API calls the same way a user would.

To run these tests, you need to be logged into a Weights & Biases account that has access to  the entity `launch-release-testing`. To request access, contact Tim Hays.