import type { SceneLayout } from "./layout";

export interface SceneProps {
  layout: SceneLayout;
  /** Evidence key (source ID) currently selected, if any. */
  selectedKey: string | null;
  /** Station to emphasise (0 documents … 3 answer); null shows all equally. */
  activeStage: number | null;
  onSelect?: (key: string) => void;
}

export const DIM = 0.5;
