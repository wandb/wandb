# Weights and Biases Frontend!

The frontend uses [Create React App (CRA)](https://github.com/facebookincubator/create-react-app) to make sound stack choices for us.  It uses [Apollo Client](http://dev.apollodata.com) for GraphQL server communication, Redux for state management, and Auth0 for authentication.

## Customization

CRA makes it easy for us to stay up to date with React best practices, however sometimes we want the latest hotness.  To accomplish this we use [react-app-rewired](https://github.com/timarney/react-app-rewired) to make modifications to our webpack config.  The primary customizations we've made are generating build stats and using the AutoDLL plugin to increase compilation speed and split our bundles into ones that rarely change and one that changes often.

### Theming

We use the buildable version of sematic-ui which is in the `semantic` directory.  This directory is automatically symlinked into `node_modules` so we can require the generated CSS.  Custom themes are specified via `semantic/src/theme.config`, and potential changes are made to themes, for instance `semantic/src/themes/timeline/views/feed.overrides` was heavily customized.  It's easy to override global variables like colors and fonts at `semantic/src/site/globals`.  If changes are made the following build script should be run.

```shell
yarn global add gulp
cd semantic
gulp build
```

## Testing

Make sure you have the latest version of watchman

```shell
brew install watchman
```

## Deployment

Firebase is used for frontend hosting, `yarn deploy` away!
