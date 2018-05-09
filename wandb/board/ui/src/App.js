import 'whatwg-fetch';
import React, {Component} from 'react';
//import Nav from './components/Nav';
import {connect} from 'react-redux';
import {Container} from 'semantic-ui-react';
import AutoReload from './components/AutoReload';
import Loader from './components/Loader';
import Footer from './components/Footer';
import ErrorPage from './components/ErrorPage';
import './App.css';
import './react-autosuggest.css';
import './components/vis/ReactVis.css';
import {mouseListenersStart} from './util/mouse';
import pattern from './assets/wandb-pattern.svg';
import {Offline, Online} from 'react-detect-offline';
require('es6-symbol/implement');
const values = require('object.values');
const entries = require('object.entries');
if (!Object.values) {
  values.shim();
}
if (!Object.entries) {
  entries.shim();
}

let Nav;
try {
  Nav = require('Cloud/components/Nav').default;
} catch (err) {
  Nav = require('./components/Nav').default;
}

class App extends Component {
  state = {loading: false, error: null};

  componentDidCatch(error, info) {
    window.Raven.captureException(error, {extra: info});
    error.reported = true;
    //this.setState({error: error});
  }

  componentDidMount() {
    mouseListenersStart();
  }

  render() {
    return (
      <div className={this.props.fullScreen ? 'fullScreen' : ''}>
        <AutoReload setFlash={this.props.setFlash} />
        <Nav user={this.props.user} history={this.props.history} />
        <div className="main" style={{padding: '20px'}}>
          <Online>
            {this.props.error || this.state.error ? (
              <ErrorPage
                history={this.props.history}
                error={this.props.error || this.state.error}
              />
            ) : (
              this.props.children
            )}
          </Online>
          <Offline>
            <ErrorPage
              error={{message: 'Your browser is currently offline', code: 0}}
            />
          </Offline>
        </div>
        <Footer />
      </div>
    );
  }
}

function mapStateToProps(state, ownProps) {
  return {
    fullScreen: state.global.fullScreen,
  };
}

export default connect(mapStateToProps)(App);
