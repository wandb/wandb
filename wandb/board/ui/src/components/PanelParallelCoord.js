import React from 'react';
import {connect} from 'react-redux';
import {bindActionCreators} from 'redux';
import _ from 'lodash';
import {Form} from 'semantic-ui-react';
import {registerPanelClass} from '../util/registry.js';
import {filterKeyFromString, filtersForAxis} from '../util/runhelpers.js';
import {getRunValue} from '../util/runhelpers.js';
import {batchActions} from 'redux-batched-actions';
import {addFilter, setHighlight} from '../actions/run';

import './PlotParCoor.css';
import * as d3 from 'd3';

function parcoor(node, data, reactEl, brushCallback, mouseOverCallback, mouseOutCallback) {
  const isBrushing = false;
  let computedWidth = 1070;

  const d3node = d3.select(node).node();

  if (d3node) computedWidth = Math.max(280, d3node.getBoundingClientRect().width);
  const margin = {top: 30, right: 10, bottom: 10, left: 10},
    width = computedWidth - margin.left - margin.right,
    height = 280 - margin.top - margin.bottom;

  const x = d3
      .scaleBand()
      .rangeRound([0, width])
      .padding(1),
    y = {},
    dragging = {};

  const line = d3.line();

  const svg = d3
    .select(node)
    .html('')
    .append('svg')
    .attr('width', width + margin.left + margin.right)
    .attr('height', height + margin.top + margin.bottom)
    .append('g')
    .attr('transform', `translate(${margin.left},${margin.top})`);

  const dimensions = d3
    .keys(data[0])
    .filter(d => d !== 'name')
    .filter(
      d =>
        _.isFinite(parseFloat(data[0][d])) &&
        (y[d] = d3
          .scaleLinear()
          .domain(d3.extent(data, p => +parseFloat(p[d])))
          .range([height, 0])),
    );
  x.domain(dimensions);

  const extents = dimensions.map(p => [0, 0]);

  // Add grey background lines for context.
  const background = svg
    .append('g')
    .attr('class', 'background')
    .selectAll('path')
    .data(data)
    .enter()
    .append('path')
    .attr('d', path);

  // Add blue foreground lines for focus.
  const foreground = svg
    .append('g')
    .attr('class', 'foreground')
    .selectAll('path')
    .data(data)
    .enter()
    .append('path')
    .attr('d', path);

  // Add a group element for each dimension.
  const g = svg
    .selectAll('.dimension')
    .data(dimensions)
    .enter()
    .append('g')
    .attr('class', 'dimension')
    .attr('transform', d => `translate(${x(d)})`)
    .call(
      d3
        .drag()
        .subject(d => ({x: x(d)}))
        .on('start', d => {
          dragging[d] = x(d);
          background.attr('visibility', 'hidden');
        })
        .on('drag', d => {
          dragging[d] = Math.min(width, Math.max(0, d3.event.x));
          foreground.attr('d', path);
          dimensions.sort((a, b) => position(a) - position(b));
          x.domain(dimensions);
          g.attr('transform', d => `translate(${position(d)})`);
        })
        .on('end', function(d) {
          delete dragging[d];
          transition(d3.select(this)).attr('transform', `translate(${x(d)})`);
          transition(foreground).attr('d', path);
          background
            .attr('d', path)
            .transition()
            .delay(500)
            .duration(0)
            .attr('visibility', null);
          addHover();
        }),
    );
  // Add an axis and title.
  g
    .append('g')
    .attr('class', 'axis')
    .each(function(d) {
      d3.select(this).call(d3.axisLeft(y[d]));
    })
    //text does not show up because previous line breaks somehow
    .append('text')
    .attr('fill', 'black')
    .style('text-anchor', 'middle')
    .attr('y', -9)
    .text(d => d);

  // Add and store a brush for each axis.
  g
    .append('g')
    .attr('class', 'brush')
    .each(function(d) {
      d3.select(this).call(
        (y[d].brush = d3
          .brushY()
          .extent([[-8, 0], [8, height]])
          .on('brush start', brushstart)
          .on('brush', brush)),
      );
    })
    .selectAll('rect')
    .attr('x', -8)
    .attr('width', 16);

  // Add wider transparent lines for hovering (reusable function)
  function addHover() {
    // Remove any previously added lines
    svg.selectAll('g.hoverable').remove();
    // Add new lines based on latest data
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
  }
  addHover();

  function position(d) {
    const v = dragging[d];
    return v == null ? x(d) : v;
  }

  function transition(g) {
    return g.transition().duration(500);
  }

  // Returns the path for a given data point.
  function path(d) {
    return line(dimensions.map(p => [position(p), y[p](d[p])]));
  }

  function brushstart() {
    d3.event.sourceEvent.stopPropagation();
  }

  // Handles a brush event, toggling the display of foreground lines.
  function brush() {
    for (let i = 0; i < dimensions.length; ++i) {
      if (d3.event.target == y[dimensions[i]].brush) {
        extents[i] = d3.event.selection.map(y[dimensions[i]].invert, y[dimensions[i]]);
      }
    }

    foreground.style(
      'display',
      d =>
        dimensions.every((p, i) => {
          if (extents[i][0] == 0 && extents[i][0] == 0) {
            return true;
          }
          return extents[i][1] <= d[p] && d[p] <= extents[i][0];
        })
          ? null
          : 'none',
    );
  }

  function handleHighlight(runData) {
    if (isBrushing) {
      return;
    }
    if (!runData) {
      svg.selectAll('g.hover').remove();
      // FIXME: Why should we need this ?
      //TODO: this calling of self and redefining handleHighlight is gross
      // setTimeout(() => {
      //   reactEl.handleHighlight = parcoor(
      //     node,
      //     data,
      //     reactEl,
      //     brushCallback,
      //     mouseOverCallback,
      //     mouseOutCallback,
      //   );
      // }, 0);
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
        const run = _.find(props.runs, run => run.name === props.highlight);
        if (!run) {
          this.handleHighlight(null);
        } else {
          const row = {};
          for (const col of this.props.cols) {
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
    const cols = this.props.cols;
    let data = this.props.runs.map(run => {
      const row = {name: run.name};
      for (const col of cols) {
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
    const {dimensions} = nextProps.config;
    if (dimensions && nextProps.selections !== props.selections) {
      this.select = {};
      for (const dim of dimensions) {
        this.select[dim] = filtersForAxis(nextProps.selections, dim);
      }
    }
  }

  componentWillMount() {
    this._setup({}, this.props);
  }

  componentWillReceiveProps(nextProps) {
    this._setup(this.props, nextProps);
  }

  renderConfig() {
    const {axisOptions} = this.props.data;
    return (
      <Form>
        <Form.Dropdown
          label="Dimensions"
          placeholder="Dimensions"
          fluid
          multiple
          search
          selection
          options={axisOptions}
          value={this.props.config.dimensions}
          onChange={(e, {value}) =>
            this.props.updateConfig({
              ...this.props.config,
              dimensions: value,
            })
          }
        />
      </Form>
    );
  }

  renderNormal() {
    const {dimensions} = this.props.config;
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

const mapDispatchToProps = (dispatch, ownProps) =>
  bindActionCreators({batchActions, setHighlight}, dispatch);

const ConnectParCoordPanel = connect(mapStateToProps, mapDispatchToProps)(ParCoordPanel);
ConnectParCoordPanel.type = ParCoordPanel.type;
ConnectParCoordPanel.options = ParCoordPanel.options;
ConnectParCoordPanel.validForData = ParCoordPanel.validForData;

registerPanelClass(ConnectParCoordPanel);
