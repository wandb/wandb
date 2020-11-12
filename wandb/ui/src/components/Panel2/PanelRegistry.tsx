import {Spec as NumberSpec} from './PanelNumber';
import {Spec as StringSpec} from './PanelString';
import {Spec as StringCompareSpec} from './PanelStringCompare';
import {Spec as StringHistogramSpec} from './PanelStringHistogram';
import {Spec as MultiStringHistogramSpec} from './PanelMultiStringHistogram';
import {Spec as BarChartSpec} from './PanelBarChart';
import {Spec as HistogramSpec} from './PanelHistogram';
import {Spec as MultiHistogramSpec} from './PanelMultiHistogram';
import {Spec as ImageSpec} from './PanelImage';
import {Spec as ImageCompareSpec} from './PanelImageCompare';

// converters
import {Spec as MultiContainerSpec} from './PanelMultiContainer';
import {Spec as SplitCompareSpec} from './PanelSplitCompare';
// import {Spec as SplitIndependentSpec} from './PanelSplitIndependent';
import {Spec as WBObjectSpec} from './PanelWBObject';

// files
import {Spec as FileTextSpec} from './PanelFileText';
import {Spec as FileTextDiffSpec} from './PanelFileTextDiff';
import {Spec as FileMarkdownSpec} from './PanelFileMarkdown';
import {Spec as FileRawImageSpec} from './PanelFileRawImage';
import {Spec as FileJupyterSpec} from './PanelFileJupyter';
import {Spec as DirSpec} from './PanelDir';
import {Spec as NetronSpec} from './PanelNetron';
import {Spec as WebVizSpec} from './PanelWebViz';

import {Spec as WBTableFileSpec} from './PanelWBTableFile';
import {Spec as WBJoinedTableFileSpec} from './PanelWBJoinedTableFile';

// TODO: Wrap Panel components with makeSpec calls

// Note, order matters here! This is the default order in which panels
// will be recommended to the user.
export const PanelSpecs = [
  StringSpec,
  StringHistogramSpec,
  MultiStringHistogramSpec,
  StringCompareSpec,
  NumberSpec,
  BarChartSpec,
  HistogramSpec,
  MultiHistogramSpec,
  ImageSpec,
  ImageCompareSpec,
  FileJupyterSpec,
  FileRawImageSpec,
  FileMarkdownSpec,
  FileTextDiffSpec,
  FileTextSpec,
  NetronSpec,
  WebVizSpec,
  DirSpec,

  // Not enabled, it shows up too early in the list, and its not
  // that useful at the moment, since the user can't easily load
  // files with different types.
  // SplitIndependentSpec,

  WBTableFileSpec,
  WBJoinedTableFileSpec,
];

export const ConverterSpecs = [
  MultiContainerSpec,
  SplitCompareSpec,
  WBObjectSpec,
];
