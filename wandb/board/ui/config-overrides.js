const defaults = require('lodash.defaults');
const AutoDllPlugin = require('autodll-webpack-plugin');
const BundleAnalyzerPlugin = require('webpack-bundle-analyzer')
  .BundleAnalyzerPlugin;
const webpack = require('webpack');
const rewireTypescript = require('react-app-rewire-typescript');

const fs = require('fs');
const appDirectory = fs.realpathSync(process.cwd());
const path = require('path');

// ruleChildren through addBeforeRule taken from react-app-rewire-typescript

const ruleChildren = rule =>
  rule.use || rule.oneOf || (Array.isArray(rule.loader) && rule.loader) || [];

const findIndexAndRules = (rulesSource, ruleMatcher) => {
  let result;
  const rules = Array.isArray(rulesSource)
    ? rulesSource
    : ruleChildren(rulesSource);
  rules.some(
    (rule, index) =>
      (result = ruleMatcher(rule)
        ? {index, rules}
        : findIndexAndRules(ruleChildren(rule), ruleMatcher)),
  );
  return result;
};

/**
 * Given a rule, return if it uses a specific loader.
 */
const createLoaderMatcher = loader => rule =>
  rule.loader && rule.loader.indexOf(`${path.sep}${loader}${path.sep}`) !== -1;

/**
 * Add one rule before another in the list of rules.
 */
const addBeforeRule = (rulesSource, ruleMatcher, value) => {
  const {index, rules} = findIndexAndRules(rulesSource, ruleMatcher);
  rules.splice(index, 0, value);
};

//Taken primarily from: https://github.com/facebookincubator/create-react-app/pull/2710/files
function rewire(config, env) {
  //Vendor the common stuff
  const vendor = [
      'react',
      'react-dom',
      'react-router',
      'react-router-dom',
      'react-redux',
      'react-apollo',
      'react-table',
      'react-virtualized',
      'react-vis',
      'd3',
      'markdown-it',
      'redux',
      'semantic-ui-react',
      'lodash',
    ],
    polyfill = config.entry[0];
  if (!polyfill.match(/polyfill/))
    throw 'The first webpack entry is no longer polyfill';

  config.plugins.unshift(
    new BundleAnalyzerPlugin({openAnalyzer: false, analyzerMode: 'static'}),
  );
  const uglyIdx = config.plugins.findIndex(
    p => p.constructor.name === 'UglifyJsPlugin',
  );
  const htmlIdx = config.plugins.findIndex(
    p => p.constructor.name === 'HtmlWebpackPlugin',
  );
  const defineIdx = config.plugins.findIndex(
    p => p.constructor.name === 'DefinePlugin',
  );
  if (env === 'production') {
    config.plugins.splice(
      htmlIdx + 1,
      0,
      new AutoDllPlugin({
        context: appDirectory,
        path: './static/js',
        filename: '[name].[hash:8].js',
        inject: true,
        entry: defaults(
          {vendor},
          {
            polyfills: [polyfill],
          },
        ),
        plugins: [config.plugins[defineIdx], config.plugins[uglyIdx]],
      }),
    );
  }

  config = rewireTypescript(config, env);

  addBeforeRule(config.module.rules, createLoaderMatcher('babel-loader'), {
    test: /\.worker\.js$/,
    use: {loader: 'worker-loader'},
  });

  return config;
}

module.exports = {
  webpack: rewire,
  devServer: function(configFunction) {
    return function(proxy, allowedHost) {
      const config = configFunction(proxy, allowedHost);
      config.proxy = {'/graphql': 'http://localhost:7177'};
      return config;
    };
  },
};
