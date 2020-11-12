// Generic parameters:
// Globals
//   X: context
//   T: libtypes type
// Panel specific
//   I: input type

interface PanelPropsInternal<I, C, X> {
  input: I;
  loading: boolean;
  context: X;
  config: C;
  configMode: boolean;
  updateContext(partialContetx: Partial<X>): void;
  updateConfig(partialConfig: Partial<C>): void;
}

export type PanelProps<I, C, X> = PanelPropsInternal<I, C, X>;

type PanelPropsAnyInput<X> = PanelPropsInternal<any, any, X>;

export interface PanelSpec<X, T> {
  id: string;
  displayName?: string;
  ConfigComponent?: React.ComponentType<PanelPropsAnyInput<X>>;
  Component: React.ComponentType<PanelPropsAnyInput<X>>;

  inputType: T;
}

export type PanelConverterProps<X, T> = PanelPropsAnyInput<X> & {
  child: any;
  inputType: T;
};

export interface PanelConvertSpec<X, T> {
  id: string;
  displayName?: string;
  ConfigComponent?: React.ComponentType<PanelConverterProps<X, T>>;
  Component: React.ComponentType<PanelConverterProps<X, T>>;
  convert(inputType: T): T | null;
}

export type PanelConvertWithChildSpec<X, T> = PanelConvertSpec<X, T> & {
  child: any;
  inputType: T;
  convert(inputType: T): T | null;
};

export type PanelSpecNode<X, T> =
  | PanelSpec<X, T>
  | PanelConvertWithChildSpec<X, T>;

export function isWithChild<X, T>(
  spec: PanelSpecNode<X, T>
): spec is PanelConvertWithChildSpec<X, T> {
  return (spec as any).child != null;
}

function getDisplayName<X, T>(panel: PanelSpecNode<X, T>): string {
  if (panel.displayName != null) {
    return panel.displayName;
  }
  const words = panel.id.split('-');
  return words.map(w => w.charAt(0).toUpperCase() + w.slice(1)).join('');
}
export function getStackIdAndName<X, T>(
  panel: PanelSpecNode<X, T>
): {id: string; displayName: string} {
  if (isWithChild(panel)) {
    const {id, displayName} = getStackIdAndName(panel.child);
    return {
      id: panel.id + '.' + id,
      displayName: getDisplayName(panel) + ' -> ' + displayName,
    };
  }
  return {id: panel.id, displayName: getDisplayName(panel)};
}
