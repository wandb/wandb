import React, {Component} from 'react';
import {connect} from 'react-redux';
import {NavLink, Link} from 'react-router-dom';
import {
  Menu,
  Container,
  Dropdown,
  Image,
  Message,
  Transition,
} from 'semantic-ui-react';
import logo from '../assets/logo.svg';
import '../components/Nav.css';

class Nav extends Component {
  state = {showFlash: false};

  componentDidMount() {
    if (this.props.flash) {
      this.setState({showFlash: true});
    }
  }

  componentWillReceiveProps(nextProps) {
    if (nextProps.flash && nextProps.flash !== this.props.flash) {
      this.setState({showFlash: true});
    }
  }

  render() {
    const {user} = this.props;
    const {params} = this.props;
    const flash = this.props.flash || {};

    return (
      <Menu fixed="top" borderless>
        <Container style={{position: 'relative'}}>
          <NavLink exact to="/" className="item">
            <img src={logo} className="logo" alt="Weights & Biases" />
          </NavLink>
          {
            <NavLink to={`/`} className="item">
              Runs
            </NavLink>
          }
          <Menu.Menu position="right" />
          <Transition
            animation="fly down"
            duration={1000}
            visible={this.state.showFlash}
            onComplete={() => {
              if (!flash.sticky)
                setTimeout(() => this.setState({showFlash: false}), 5000);
            }}>
            <Message
              floating
              color={flash.color || 'orange'}
              onDismiss={() => this.setState({showFlash: false})}
              compact
              style={{
                position: 'absolute',
                right: 0,
                top: 50,
                paddingRight: 30,
              }}>
              {flash.message}
            </Message>
          </Transition>
        </Container>
      </Menu>
    );
  }
}

function mapStateToProps(state, ownProps) {
  return {
    flash: state.global.flash,
    params: state.location.params || {},
  };
}

export default connect(mapStateToProps)(Nav);
