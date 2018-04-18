import 'whatwg-fetch';
import React, {Component} from 'react';
//import Nav from './components/Nav';
import {connect} from 'react-redux';
import {Container, Loader} from 'semantic-ui-react';
import AutoReload from './components/AutoReload';
import Footer from './components/Footer';
import ErrorPage from './components/ErrorPage';
import './App.css';
import './react-autosuggest.css';
import './components/vis/ReactVis.css';
import {mouseListenersStart} from './util/mouse';
import pattern from './assets/wandb-pattern.svg';

let Nav;
try {
  Nav = require('Cloud/components/Nav').default;
} catch (err) {
  Nav = require('./components/Nav').default;
}

class App extends Component {
  state = {loading: false, error: null};

  componentDidCatch(error, info) {
    this.setState({error: error});
  }

  componentDidMount() {
    mouseListenersStart();
  }

  render() {
    return this.state.loading ? (
      <div>
        <Loader size="massive">Initializing...</Loader>
      </div>
    ) : (
      <div className={this.props.fullScreen ? 'fullScreen' : ''}>
        <AutoReload setFlash={this.props.setFlash} />
        <Nav user={this.props.user} history={this.props.history} />
        <ErrorPage {...this.props}>
          <Container className="main" fluid style={{backgroundImage: pattern}}>
            {this.props.children}
          </Container>
        </ErrorPage>
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
