import type { Config } from 'jest';

const config: Config = {
  preset: 'ts-jest',
  testEnvironment: './jest-env.js',
  // Only collect files explicitly named *.test.ts — prevents fixture/helper
  // files in __tests__/ from being treated as test suites.
  testMatch: ['**/__tests__/**/*.test.ts', '**/__tests__/**/*.test.tsx'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/$1',
  },
  transform: {
    '^.+\\.tsx?$': ['ts-jest', { tsconfig: { module: 'commonjs', jsx: 'react-jsx' } }],
  },
};

export default config;
