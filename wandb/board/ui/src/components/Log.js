import React from 'react';
import {List, Segment} from 'semantic-ui-react';
import './Log.css';
import {AutoSizer, List as VirtualList} from 'react-virtualized';
import AU from 'ansi_up';

let unsubscribe;
try {
  unsubscribe = require('Cloud/util/pusher').unsubscribe;
} catch (e) {
  unsubscribe = require('../util/pusher').unsubscribe;
}

class Log extends React.Component {
  state = {
    autoScroll: true,
  };
  constructor(props) {
    super(props);
    this.ansi_up = new AU();
  }
  //TODO: this might go away
  parseLoss(lines) {
    let losses = [];
    lines.forEach(line => {
      let loss = line.node.line.match(/(loss|accuracy): (\d+\.\d+)/);
      if (loss) losses.push(parseFloat(loss[2]));
    });
    return losses;
  }

  componentWillUnMunt() {
    unsubscribe('logs-' + this.props.match.params.run);
  }

  updateCallback = () => {
    //TODO: performance for big logs / why is this null sometimes?
    if (this.list) this.list.forceUpdateGrid();
  };

  componentDidMount() {
    this.scrollToBottom();
  }

  componentWillReceiveProps(nextProps) {
    if (nextProps.logLines) {
      // Bind stream only when `logLines` is not empty, and only once,
      // otherwise `readFragment` will break.
      // As an alternative, we can go with unbinding all events from `StreamingLog`
      if (!this.bound) {
        this.props.stream(
          this.props.client,
          this.props.match.params,
          this.props.bucket,
          this.updateCallback,
        );
        this.bound = true;
      }

      if (this.props.logLines !== nextProps.logLines) {
        //TODO: WTF
        if (this.props.updateLoss) {
          this.props.updateLoss(
            this.props.run,
            this.parseLoss(nextProps.logLines.edges),
          );
        }
      }
    }
  }

  componentDidUpdate(prevProps, prevState) {
    if (
      this.props.logLines &&
      !_.isEqual(this.props.logLines, prevProps.logLines)
    ) {
      this.scrollToBottom();
    }
  }

  scrollToBottom = () => {
    if (this.props.logLines && this.state.autoScroll) {
      setTimeout(() => {
        if (this.list) this.list.scrollToRow(this.props.logLines.edges.length);
      }, 500);
    }
  };

  checkAutoScroll = e => {
    // autoScroll is enabled if current scroll position is close to the bottom
    // or if list is still empty meaning List height is zero
    const scroll = e.scrollHeight - e.clientHeight - Math.round(e.scrollTop);
    this.setState({
      autoScroll: scroll < 5 || e.clientHeight === 0,
    });
  };

  processLine(line) {
    return line.substr(line.indexOf(' ') + 1).replace(/ /g, '\u00a0');
  }

  rowRenderer = ({key, index, style}) => {
    const line = this.props.logLines.edges[index];
    //TODO: CSS and other dangerous HTML injection issues
    return (
      <div
        key={key}
        role="row"
        className={`item ${line.node.level}`}
        style={style}
        dangerouslySetInnerHTML={{
          __html:
            this.ansi_up.ansi_to_html(this.processLine(line.node.line)) +
            '<br>',
        }}
      />
    );
  };

  render() {
    let rowCount = this.props.logLines ? this.props.logLines.edges.length : 0;
    return (
      <Segment
        inverted
        loading={!this.props.logLines}
        className="logs"
        attached
        style={{height: 400}}>
        <AutoSizer>
          {({width, height}) => (
            <List ordered inverted size="small">
              <VirtualList
                ref={list => (this.list = list)}
                onScroll={this.checkAutoScroll}
                height={height}
                width={width}
                rowCount={rowCount}
                rowHeight={20}
                rowRenderer={this.rowRenderer}
              />
            </List>
          )}
        </AutoSizer>
      </Segment>
    );
  }
}

export default Log;
