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
    this.props.stream(
      this.props.client,
      this.props.match.params,
      this.props.bucket,
      this.updateCallback,
    );
    //TODO: This is rather unfortunate
    if (this.state.autoScroll) {
      setTimeout(() => {
        if (this.list) this.list.scrollToRow(this.props.logLines.edges.length);
      }, 500);
    }
  }

  componentWillReceiveProps(nextProps) {
    if (nextProps.logLines && this.props.logLines !== nextProps.logLines) {
      //TODO: WTF
      if (this.props.updateLoss) {
        this.props.updateLoss(
          this.props.run,
          this.parseLoss(nextProps.logLines.edges),
        );
      }
      //TODO: This is rather unfortunate
      if (this.state.autoScroll) {
        setTimeout(() => {
          if (this.list)
            this.list.scrollToRow(this.props.logLines.edges.length);
        }, 500);
      }
    }
  }

  checkAutoScroll = () => {
    this.scrolls = this.scrolls || 0;
    this.scrolls += 1;
    setTimeout(() => (this.scrolls = 0), 100);
    if (this.scrolls > 5) {
      this.setState({autoScroll: false});
    }
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
    let rowCount = this.props.logLines.edges.length;
    return (
      <Segment inverted className="logs" attached style={{height: 400}}>
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
