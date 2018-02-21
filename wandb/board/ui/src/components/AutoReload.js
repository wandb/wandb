import React, {Component} from 'react';
import timer from 'battery-friendly-timer';
import {Message} from 'semantic-ui-react';

class AutoReload extends Component {
  constructor(props) {
    super(props);
    this.previousHash = null;
    this.fetchSource = this.fetchSource.bind(this);
  }

  componentDidMount() {
    const {tryDelay, forceDelay} = this.props;
    this.fetchSource();
    this.interval = timer.setInterval(this.fetchSource, tryDelay, forceDelay);
  }

  componentWillUnmount() {
    timer.clearInterval(this.interval);
  }

  fetchSource() {
    return fetch(this.props.url)
      .then(response => {
        if (response.status !== 200) {
          throw new Error('offline');
        }
        return response.text();
      })
      .then(html => {
        const hash = this.hash(html);
        if (!this.previousHash) {
          this.previousHash = hash;
          return;
        }
        if (this.previousHash !== hash) {
          this.previousHash = hash;
          this.props.setFlash({
            sticky: true,
            color: 'blue',
            message: (
              <Message.Content>
                <Message.Header>A new version is available!</Message.Header>
                <p>
                  <a href="/" onClick={this.reloadApp}>
                    Click to reload
                  </a>
                </p>
              </Message.Content>
            ),
          });
        }
      })
      .catch(() => {
        /* do nothing */
      });
  }

  /**
   * Java-like hashCode function for strings
   *
   * taken from http://stackoverflow.com/questions/7616461/generate-a-hash-from-string-in-javascript-jquery/7616484#7616484
   */
  hash(str) {
    const len = str.length;
    let hash = 0;
    if (len === 0) return hash;
    let i;
    for (i = 0; i < len; i++) {
      hash = (hash << 5) - hash + str.charCodeAt(i);
      hash |= 0; // Convert to 32bit integer
    }
    return hash;
  }

  reloadApp(e) {
    window.location.reload(true);
    e.preventDefault();
  }

  render() {
    return null;
  }
}

AutoReload.defaultProps = {
  url: '/',
  tryDelay: 5 * 60 * 1000, // 5 minutes
  forceDelay: 24 * 60 * 60 * 1000, // 1 day
};

export default AutoReload;
