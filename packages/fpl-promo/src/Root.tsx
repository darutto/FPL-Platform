import { Composition } from 'remotion';
import { Clip01, CLIP01_FRAMES } from './clip01/Clip01';

export const Root: React.FC = () => (
  <Composition id="Clip01" component={Clip01} durationInFrames={CLIP01_FRAMES} fps={30} width={1080} height={1920} />
);
