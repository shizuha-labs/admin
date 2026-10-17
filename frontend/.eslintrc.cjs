module.exports = {
  root: true,
  ignorePatterns: ['dist/'],
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  extends: ['eslint:recommended', 'plugin:react-hooks/recommended'],
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['react-refresh'],
  rules: {
    // The existing frontend contains a large amount of dormant UI code. Keep
    // the new baseline focused on executable correctness rather than folding
    // that unrelated cleanup into this dependency-security change.
    'no-unused-vars': 'off',
    'react-refresh/only-export-components': 'off',
  },
};
