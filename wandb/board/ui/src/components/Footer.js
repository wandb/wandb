import React from 'react';
import {Container, Segment, Grid, List} from 'semantic-ui-react';
import logo from '../assets/wandb-long.svg';
import whitelogo from '../assets/wandb-long-white.svg';

const Footer = () => (
  <Segment className="footer" vertical>
    <Container>
      <Grid columns={2} stackable>
        <Grid.Column textAlign="left" verticalAlign="middle">
          <List link horizontal>
            <List.Item as="a" target="_blank" href="http://docs.wandb.com">
              Documentation
            </List.Item>
            <List.Item as="a" target="_blank" href="http://wandb.com">
              Company
            </List.Item>
          </List>
        </Grid.Column>
        <Grid.Column textAlign="right" verticalAlign="bottom">
          <img
            src={document.body.style.background === '#55565B' ? white : logo}
            style={{opacity: 0.7, height: '3em'}}
            className="logo"
            alt="Weights & Biases"
          />
        </Grid.Column>
      </Grid>
    </Container>
  </Segment>
);
export default Footer;
