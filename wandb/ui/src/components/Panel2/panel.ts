import * as Controls from './controlsImage';
import * as PanelLib from './panellib/libpanel';
import * as Types from './types';

export interface PanelContext {
  classSets?: Controls.ClassSetControls;

  // TODO: Get rid of path. It's use by PanelDir. Should we have an "updateInput" ?
  path?: string[];
}

export type UpdateContext = (partialContext: Partial<PanelContext>) => void;
export type PanelProps<I, C = undefined> = PanelLib.PanelProps<
  Types.TypeToTSType<I>,
  C,
  PanelContext
>;

export type PanelSpec = PanelLib.PanelSpec<PanelContext, Types.Type>;

export type PanelConverterProps = PanelLib.PanelConverterProps<
  PanelContext,
  Types.Type
>;
export type PanelConvertSpec = PanelLib.PanelConvertSpec<
  PanelContext,
  Types.Type
>;

export type PanelConvertWithChildSpec = PanelLib.PanelConvertWithChildSpec<
  PanelContext,
  Types.Type
>;

export type PanelSpecNode = PanelLib.PanelSpecNode<PanelContext, Types.Type>;
