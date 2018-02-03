import 'whatwg-fetch';
import React, {Component} from 'react';
//import Nav from './components/Nav';
import {Container, Loader} from 'semantic-ui-react';
import AutoReload from './components/AutoReload';
import Footer from './components/Footer';
import ErrorPage from './components/ErrorPage';
import './App.css';
import './react-autosuggest.css';
import './components/vis/ReactVis.css';
import {mouseListenersStart} from './util/mouse';

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
      <div>
        <AutoReload setFlash={this.props.setFlash} />
        <Nav user={this.props.user} history={this.props.history} />
        <Container className="main">
          {this.props.error || this.state.error ? (
            <ErrorPage history={this.props.history} error={this.props.error} />
          ) : (
            this.props.children
          )}
        </Container>
        <Footer />
      </div>
    );
  }
}

export default App;
