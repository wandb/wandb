const defaults = require('lodash.defaults');
const AutoDllPlugin = require('autodll-webpack-plugin');
const BundleAnalyzerPlugin = require('webpack-bundle-analyzer')
  .BundleAnalyzerPlugin;
const webpack = require('webpack');

const fs = require('fs');
const appDirectory = fs.realpathSync(process.cwd());

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
      'markdown-it',
      'redux',
      'auth0-lock',
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
  if (process.env.REACT_APP_SERVER === 'board') {
    config.plugins[htmlIdx].options.template =
      appDirectory + '/public/board.html';
    console.log('Using board template');
  }
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
