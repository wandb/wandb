import React from 'react';
import {Container, Segment, Grid, List} from 'semantic-ui-react';
import logo from '../assets/wandb-new.svg';

const Footer = () => (
  <Segment className="footer" vertical>
    <Container textAlign="center">
      <Grid columns={3} stackable>
        <Grid.Column textAlign="left" style={{paddingTop: 35}}>
          <List link horizontal>
            <List.Item as="a" target="_blank" href="http://docs.wandb.com">
              Documentation
            </List.Item>
          </List>
        </Grid.Column>
        <Grid.Column>
          <img
            src={logo}
            style={{opacity: 0.7}}
            className="logo"
            alt="Weights & Biases"
          />
        </Grid.Column>
        <Grid.Column textAlign="right" style={{paddingTop: 35}}>
          &copy; 2018 Weights & Biases
        </Grid.Column>
      </Grid>
    </Container>
  </Segment>
);
export default Footer;
