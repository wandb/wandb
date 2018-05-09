import React from 'react';
import {Message, Header, Icon, Container} from 'semantic-ui-react';
import {connect} from 'react-redux';
import {resetError, setFlash} from '../actions';
import _ from 'lodash';

const ErrorPage = ({error, history, dispatch}) => {
  // If production, auto-reload after 20s
  if (process.env.NODE_ENV === 'production') {
    setTimeout(() => window.location.reload(true), 20000);
  }

  let icon,
    title,
    message,
    knownError = true;
  //For now let's grab the first error from the GQL server
  //TODO: why is this sometimes an array?
  if (Array.isArray(error)) error = error[0];
  //TODO: not sure what the null error case is...
  error = error || {message: 'Unknown error'};
  const fatal = error.fatal;
  message = error.message || 'Fatal error';
  if (error.graphQLErrors && error.graphQLErrors.length > 0)
    error = error.graphQLErrors[0];
  //TODO: Temporary fix
  if (!error.code && message.indexOf('not found') >= 0) error.code = 404;
  window.ga('send', 'exception', {
    exDescription: error.message,
    exFatal: fatal === true,
  });
  if (message.match('is a reserved word')) {
    // this is a 400 when the name is on our banned list
    icon = 'frown';
    title = 'Bad name';
    message = "You've chosen a reserved word, please choose another name.";
  } else {
    switch (error.code) {
      case 0:
        icon = 'wifi';
        title = 'Offline';
        message = message;
        break;
      case 400:
        icon = 'ban';
        title = 'Invalid Record';
        message = message;
        window.Raven.captureException(error);
        break;
      case 403:
        icon = 'hide';
        title = 'Permission Denied';
        //For invite only signups
        if (error.error_description === 'Signup disabled') {
          message =
            'You must signup with the private invitation link provided in the slides.';
        } else {
          message =
            error.message ||
            'You do not have permission to access this resource.';
        }

        break;
      case 404:
        icon = 'stop circle outline';
        title = 'Not Found';
        message = "We couldn't find what you're looking for.";

        break;
      default:
        icon = 'bug';
        title = error.message || 'Application Error';
        message =
          "An application error occurred, close this notification to refresh the page.  We'll try reloading this page again shortly.";
        if (!window.error_dialog) {
          window.error_dialog = true;
          window.Raven.captureException(error);
          window.Raven.showReportDialog();
        }
    }
  }

  return (
    <Container text>
      <div style={{height: 100}} />
      <Message
        floating
        error={true}
        size="small"
        icon
        onDismiss={() => {
          dispatch(resetError());
          window.error_dialog = false;
          if (error.code > 400 && history) history.goBack();
        }}>
        <Icon name={icon} />
        <Message.Content>
          <Message.Header>{title}</Message.Header>
          <p>{message}</p>
        </Message.Content>
      </Message>
    </Container>
  );
};

export default connect()(ErrorPage);
