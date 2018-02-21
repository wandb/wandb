import React from 'react';
import Autosuggest from 'react-autosuggest';

class RunFieldSelector extends React.Component {
  constructor(props) {
    super(props);
    this.state = {filteredSuggestions: []};
  }

  filterKeySuggestions(value) {
    let regex = new RegExp(value.value, 'i');
    this.setState({
      filteredSuggestions: this.props.options
        .map(section => ({
          title: section.title,
          suggestions: section.suggestions.filter(suggestion =>
            (suggestion.section + ':' + suggestion.value).match(regex),
          ),
        }))
        .filter(section => section.suggestions.length > 0),
    });
  }

  render() {
    return (
      <Autosuggest
        multiSection={true}
        suggestions={this.state.filteredSuggestions}
        onSuggestionsFetchRequested={value => {
          this.filterKeySuggestions(value);
        }}
        onSuggestionsClearRequested={value => {
          this.setState({filteredSuggestions: []});
        }}
        onSuggestionSelected={(e, {suggestion}) => {
          this.props.onSelected(suggestion);
        }}
        getSuggestionValue={suggestion => suggestion.value}
        renderSuggestion={suggestion => <span>{suggestion.value}</span>}
        renderSectionTitle={section => <strong>{section.title}</strong>}
        getSectionSuggestions={section => section.suggestions}
        shouldRenderSuggestions={() => true}
        inputProps={this.props.inputProps}
      />
    );
  }
}

export default RunFieldSelector;
