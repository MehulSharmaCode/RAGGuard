/**
 * First-run explanation of the pipeline. Purely illustrative: a fixed structure,
 * no numbers, no labels that could be read as data, and captioned as an illustration.
 */

import { computeLayout, type SceneInput } from "./layout";
import { SceneView, useSceneMode } from "./SceneView";

const ILLUSTRATION: SceneInput = {
  documents: [
    {
      totalPages: 8,
      chunkCount: 14,
      retrieved: [
        { key: "a", page: 2, chunkIndex: 3 },
        { key: "b", page: 5, chunkIndex: 8 },
        { key: "c", page: 6, chunkIndex: 10 },
      ],
    },
  ],
  evidence: [
    { key: "a", documentIndex: 0, cited: true, strength: 0.85 },
    { key: "b", documentIndex: 0, cited: true, strength: 0.7 },
    { key: "c", documentIndex: 0, cited: false, strength: 0.5 },
  ],
};

const LAYOUT = computeLayout(ILLUSTRATION);
const CAPTIONS = ["Document pages", "Overlapping chunks", "Retrieved evidence", "Cited answer"];

export function FirstRunIllustration() {
  const { mode } = useSceneMode();
  return (
    <figure className="w-full">
      <div className="h-44 md:h-52">
        <SceneView mode={mode} layout={LAYOUT} selectedKey={null} activeStage={null} />
      </div>
      <ol className="grid grid-cols-4 gap-2 text-center text-12 text-ink-500">
        {CAPTIONS.map((caption) => (
          <li key={caption}>{caption}</li>
        ))}
      </ol>
      <figcaption className="mt-2 text-center text-12 text-ink-500">
        Illustration of what happens to an uploaded file — not data from your documents.
      </figcaption>
    </figure>
  );
}
