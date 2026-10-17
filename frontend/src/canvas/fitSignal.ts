// Set by the toolbar; FlowCanvas fits the whole graph once the next layout lands.
let pending = false;
export const requestFitAfterLayout = () => {
  pending = true;
};
export const takeFitRequest = (): boolean => {
  const p = pending;
  pending = false;
  return p;
};
