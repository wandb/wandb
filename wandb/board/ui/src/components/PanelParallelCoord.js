import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import _ from 'lodash';
import {Form} from 'semantic-ui-react';
import {registerPanelClass} from '../util/registry.js';
import {filterKeyFromString, filtersForAxis} from '../util/runhelpers.js';
import {getRunValue, scatterPlotCandidates} from '../util/runhelpers.js';
import {batchActions} from 'redux-batched-actions';
import {addFilter, setHighlight} from '../actions/run';

import './PlotParCoor.css';

var d3 = window.d3;

function parcoor(
  node,
  data,
  reactEl,
  brushCallback,
  mouseOverCallback,
  mouseOutCallback,
) {
  var select = reactEl.props.select;

  let isBrushing = false;

  var d3node = d3.select(node).node(),
    computedWidth = 1070;
  if (d3node)
    computedWidth = Math.max(280, d3node.getBoundingClientRect().width);
  var margin = {top: 30, right: 10, bottom: 10, left: 10},
    width = computedWidth - margin.left - margin.right,
    height = 280 - margin.top - margin.bottom;

  var x = d3.scale.ordinal().rangePoints([0, width], 1),
    y = {},
    dragging = {};

  var line = d3.svg.line(),
    axis = d3.svg.axis().orient('left'),
    background,
    foreground;

  var svg = d3
    .select(node)
    .html('')
    .append('svg')
    .attr('width', width + margin.left + margin.right)
    .attr('height', height + margin.top + margin.bottom)
    .append('g')
    .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

  var dimensions;
  x.domain(
    (dimensions = d3
      .keys(data[0])
      .filter(d => d !== 'name')
      .filter(function(d) {
        return (
          _.isFinite(parseFloat(data[0][d])) &&
          (y[d] = d3.scale
            .linear()
            .domain(
              d3.extent(data, function(p) {
                return +parseFloat(p[d]);
              }),
            )
            .range([height, 0]))
        );
      })),
  );
  function position(d) {
    var v = dragging[d];
    return v == null ? x(d) : v;
  }

  function transition(g) {
    return g.transition().duration(500);
  }

  // Returns the path for a given data point.
  function path(d) {
    return line(
      dimensions.map(function(p) {
        return [position(p), y[p](d[p])];
      }),
    );
  }

  function brushstart() {
    isBrushing = true;
    if (d3.event.sourceEvent) {
      d3.event.sourceEvent.stopPropagation();
    }
  }

  function brush(axis) {
    var actives = dimensions.filter(function(p) {
        return y[p].brush && !y[p].brush.empty();
      }),
      extents = actives.map(function(p) {
        return y[p].brush.extent();
      });
    foreground.style('display', function(d) {
      return actives.every(function(p, i) {
        return extents[i][0] <= d[p] && d[p] <= extents[i][1];
      })
        ? null
        : 'none';
    });
  }

  function brushend(axis) {
    isBrushing = false;
    // This doesn't work well if we do it in brush, probably a feedback loop.
    // Doing it here for now, we can fix later.
    if (axis) {
      let [low, high] = y[axis].brush.extent();
      if (low === high) {
        low = null;
        high = null;
      }
      brushCallback(axis, low, high);
    }
  }

  // Add grey background lines for context.
  background = svg
    .append('g')
    .attr('class', 'background')
    .selectAll('path')
    .data(data)
    .enter()
    .append('path')
    .attr('d', path);

  // Add blue foreground lines for focus.
  foreground = svg
    .append('g')
    .attr('class', 'foreground')
    .selectAll('path')
    .data(data)
    .enter()
    .append('path')
    .attr('d', path);

  // Add wider transparent lines for hovering
  svg
    .append('g')
    .attr('class', 'hoverable')
    .attr('stroke-width', 5)
    .selectAll('path')
    .data(data)
    .enter()
    .append('path')
    .attr('d', path)
    .on('mouseover', (row, index) => mouseOverCallback(row, index))
    .on('mouseout', (row, index) => mouseOutCallback());

  // Add a group element for each dimension.
  var g = svg
    .selectAll('.dimension')
    .data(dimensions)
    .enter()
    .append('g')
    .attr('class', 'dimension')
    .attr('transform', function(d) {
      return 'translate(' + x(d) + ')';
    })
    .call(
      d3.behavior
        .drag()
        .origin(function(d) {
          return {x: x(d)};
        })
        .on('dragstart', function(d) {
          dragging[d] = x(d);
          background.attr('visibility', 'hidden');
        })
        .on('drag', function(d) {
          dragging[d] = Math.min(width, Math.max(0, d3.event.x));
          foreground.attr('d', path);
          dimensions.sort(function(a, b) {
            return position(a) - position(b);
          });
          x.domain(dimensions);
          g.attr('transform', function(d) {
            return 'translate(' + position(d) + ')';
          });
        })
        .on('dragend', function(d) {
          delete dragging[d];
          transition(d3.select(this)).attr(
            'transform',
            'translate(' + x(d) + ')',
          );
          transition(foreground).attr('d', path);
          background
            .attr('d', path)
            .transition()
            .delay(500)
            .duration(0)
            .attr('visibility', null);
        }),
    );

  // Add an axis and title.
  g
    .append('g')
    .attr('class', 'axis')
    .each(function(d) {
      d3.select(this).call(axis.scale(y[d]));
    })
    .append('text')
    .style('text-anchor', 'middle')
    .attr('y', -9)
    .text(function(d) {
      return d;
    });

  // Add and store a brush for each axis.
  g
    .append('g')
    .attr('class', 'brush')
    .each(function(d) {
      d3.select(this).call(obj => {
        let ourBrush = d3.svg
          .brush()
          .y(y[d])
          .on('brushstart', brushstart)
          .on('brush', brush)
          .on('brushend', brushend);
        y[d].brush = ourBrush;
        if (select[d] && (select[d].low || select[d].high)) {
          ourBrush.extent([
            select[d].low || y[d].domain()[0],
            select[d].high || y[d].domain()[1],
          ]);
        }
        ourBrush(obj);
      });
    })
    .selectAll('rect')
    .attr('x', -8)
    .attr('width', 16);

  brush();

  function handleHighlight(runData) {
    if (isBrushing) {
      return;
    }
    if (!runData) {
      svg.selectAll('g.hover').remove();
      //TODO: this calling of self and redefining handleHighlight is gross
      setTimeout(() => {
        reactEl.handleHighlight = parcoor(
          node,
          data,
          reactEl,
          brushCallback,
          mouseOverCallback,
          mouseOutCallback,
        );
      }, 0);
    } else {
      svg
        .insert('g', ':first-child')
        .attr('class', 'hover')
        .attr('stroke-width', 5)
        .selectAll('path')
        .data(runData)
        .enter()
        .append('path')
        .attr('d', path);
    }
  }

  return handleHighlight;
}

class PlotParCoor extends React.Component {
  componentWillReceiveProps(props) {
    if (props.highlight !== this.props.highlight && this.handleHighlight) {
      // Kind of hacky, we're not actually going to re-render the react component when highlight
      // changes (see shouldComponentUpdate). Instead we call a callback into d3 world here.
      // This is an optimization attempt for when the user is scrubbing quickly over a bunch
      // of different runs. Although we do a linear search through the runs list to get the
      // values to highlight (could optimize by looking up directly in an object later).
      // Do we even need to do this or can d3 magically re-render everything?
      if (props.highlight === null) {
        this.handleHighlight(null);
      } else {
        let run = _.find(props.runs, run => run.name === props.highlight);
        if (!run) {
          this.handleHighlight(null);
        } else {
          let row = {};
          for (var col of this.props.cols) {
            row[col] = getRunValue(run, col);
          }
          this.handleHighlight([row]);
        }
      }
    }
  }

  componentDidMount() {
    this.resize = window.addEventListener('resize', () => {
      this.handleHighlight(null);
    });
  }

  componentWillUnmount() {
    window.removeEventListener('resize', this.resize);
  }

  shouldComponentUpdate(nextProps, nextState) {
    if (
      _.isEqual(nextProps.runs, this.props.runs) &&
      _.isEqual(nextProps.cols, this.props.cols) &&
      _.isEqual(nextProps.select, this.props.select)
    ) {
      return false;
    }
    return true;
  }

  render() {
    let cols = this.props.cols;
    let data = this.props.runs.map(run => {
      let row = {name: run.name};
      for (var col of cols) {
        row[col] = getRunValue(run, col);
      }
      return row;
    });
    data = data.filter(row => d3.values(row).every(val => val != null));
    return (
      <div
        ref={node => {
          this.handleHighlight = parcoor(
            node,
            data,
            this,
            (axis, low, high) => this.props.onBrushEvent(axis, low, high),
            (row, index) => this.props.onMouseOverEvent(data[index].name),
            () => this.props.onMouseOutEvent(),
          );
        }}
      />
    );
  }
}

class ParCoordPanel extends React.Component {
  static type = 'Parallel Coordinates Plot';
  static options = {
    width: 16,
  };

  static validForData(data) {
    return !_.isNil(data.filtered);
  }

  constructor(props) {
    super(props);
    this.select = {};
  }

  _setup(props, nextProps) {
    let {dimensions} = nextProps.config;
    if (dimensions && nextProps.selections !== props.selections) {
      this.select = {};
      for (var dim of dimensions) {
        this.select[dim] = filtersForAxis(nextProps.selections, dim);
      }
    }
  }

  componentWillMount() {
    this._setup({}, this.props);
  }

  componentWillReceiveProps(nextProps) {
    //for (var prop of _.keys(nextProps)) {
    //  console.log('prop equal?', prop, this.props[prop] === nextProps[prop]);
    //}
    this._setup(this.props, nextProps);
  }

  _plotOptions() {
    let configs = this.props.data.filtered.map((run, i) => run.config);
    let summaryMetrics = this.props.data.filtered.map((run, i) => run.summary);

    let names = scatterPlotCandidates(configs, summaryMetrics);
    return names.map((name, i) => ({
      text: name,
      key: name,
      value: name,
    }));
  }

  renderConfig() {
    let axisOptions = this._plotOptions();
    return (
      <div>
        {(!axisOptions || axisOptions.length == 0) &&
          (this.props.data.filtered.length == 0 ? (
            <div class="ui negative message">
              <div class="header">No Runs</div>
              This project doesn't have any runs yet, or you have filtered all
              of the runs. To create a run, check out the getting started
              documentation.
              <a href="http://docs.wandb.com/#getting-started">
                http://docs.wandb.com/#getting-started
              </a>.
            </div>
          ) : (
            <div class="ui negative message">
              <div class="header">
                No useful configuration or summary metrics for plotting.
              </div>
              Parallel coordinates plot needs numeric configuration or summary
              metrics with more than one value. You don't have any of those yet.
              To learn more about collecting summary metrics check out our
              documentation at
              <a href="http://docs.wandb.com/#summary">
                http://docs.wandb.com/#summary
              </a>.
            </div>
          ))}
        <Form>
          <Form.Dropdown
            label="Dimensions"
            placeholder="Dimensions"
            fluid
            multiple
            search
            selection
            options={this.axisOptions}
            value={this.props.config.dimensions}
            onChange={(e, {value}) =>
              this.props.updateConfig({
                ...this.props.config,
                dimensions: value,
              })
            }
          />
        </Form>
      </div>
    );
  }

  renderNormal() {
    let {dimensions} = this.props.config;
    if (this.props.data.filtered && dimensions) {
      return (
        <PlotParCoor
          cols={dimensions}
          runs={this.props.data.filtered}
          select={this.select}
          highlight={this.props.highlight}
          onBrushEvent={(axis, low, high) => {
            this.props.batchActions([
              addFilter('select', filterKeyFromString(axis), '>', low),
              addFilter('select', filterKeyFromString(axis), '<', high),
            ]);
          }}
          onMouseOverEvent={runName => {
            this.props.setHighlight(runName);
          }}
          onMouseOutEvent={() => this.props.setHighlight(null)}
        />
      );
    } else {
      return <p>Please configure dimensions first</p>;
    }
  }

  render() {
    if (this.props.configMode) {
      return (
        <div>
          {this.renderNormal()}
          {this.renderConfig()}
        </div>
      );
    } else {
      return this.renderNormal();
    }
  }
}

function mapStateToProps(state, ownProps) {
  return {
    selections: state.runs.filters.select,
    highlight: state.runs.highlight,
  };
}

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators({batchActions, setHighlight}, dispatch);
};

let ConnectParCoordPanel = connect(mapStateToProps, mapDispatchToProps)(
  ParCoordPanel,
);
ConnectParCoordPanel.type = ParCoordPanel.type;
ConnectParCoordPanel.options = ParCoordPanel.options;
ConnectParCoordPanel.validForData = ParCoordPanel.validForData;

registerPanelClass(ConnectParCoordPanel);
