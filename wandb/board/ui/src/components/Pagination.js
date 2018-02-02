import React, {Component} from 'react';
import {connect} from 'react-redux';
import {Icon, Menu} from 'semantic-ui-react';
import {bindActionCreators} from 'redux';
import * as Actions from '../actions/run';

class Pagination extends Component {
  componentWillReceiveProps(nextProps) {
    // when total is change, e.g. filter is changed
    if (nextProps.total !== this.props.total) {
      this.firstPage();
    }
  }

  totalPages() {
    return Math.ceil(this.props.total / this.props.limit) || 1;
  }

  firstPage() {
    this.props.currentPage(this.props.id, 1);
  }

  prevPage() {
    if (this.props.current > 1) {
      this.props.currentPage(this.props.id, this.props.current - 1);
      this.scrollToTop();
    }
  }

  nextPage() {
    if (this.props.current < this.totalPages()) {
      this.props.currentPage(this.props.id, this.props.current + 1);
      this.scrollToTop();
    }
  }

  scrollToTop() {
    // when current page is changed, jump to top of the page, if scroll option is enabled
    if (this.props.scroll) {
      window.scrollTo(0, 0);
    }
  }

  render() {
    return (
      <Menu floated="right" pagination>
        <Menu.Item
          as="a"
          icon
          onClick={() => this.prevPage()}
          disabled={this.props.current === 1}>
          <Icon name="left chevron" />
        </Menu.Item>
        <Menu.Item disabled>
          {this.props.current} of {this.totalPages()}
        </Menu.Item>
        <Menu.Item
          as="a"
          icon
          onClick={() => this.nextPage()}
          disabled={this.props.current >= this.totalPages()}>
          <Icon name="right chevron" />
        </Menu.Item>
      </Menu>
    );
  }
}

function mapStateToProps(state, ownProps) {
  const id = ownProps.id;
  return {
    current: state.runs.pages[id] ? state.runs.pages[id].current : 1,
  };
}

const mapDispatchToProps = (dispatch, ownProps) => {
  return bindActionCreators(Actions, dispatch);
};

export default connect(mapStateToProps, mapDispatchToProps)(Pagination);
