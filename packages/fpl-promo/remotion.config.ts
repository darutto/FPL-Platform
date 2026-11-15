import { Config } from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(95);
Config.setCodec('h264');
Config.setCrf(16);

// Real captures and the official logo live in docs/marketing (clip-01/captures, assets).
Config.setPublicDir('../../docs/marketing');
