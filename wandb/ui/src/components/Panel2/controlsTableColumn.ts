export interface TableColumn {
  name: string;
  inputCol: string;
  type: string;
  config: any;
  updateConfig?(newConfig: any): void;
}
