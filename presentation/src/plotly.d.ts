declare module "plotly.js-cartesian-dist-min" {
  const plotly: {
    react: (node: HTMLElement, data: object[], layout: object, config: object) => Promise<HTMLElement>;
    purge: (node: HTMLElement) => void;
  };
  export default plotly;
}
