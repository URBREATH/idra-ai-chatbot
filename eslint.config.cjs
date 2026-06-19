module.exports = {
  parser: '@python-eslint/parser',
  parserOptions: {
    ecmaVersion: 2020,
    sourceType: 'module',
    project: './tsconfig.json',
  },
  plugins: ['@python-eslint', 'prettier'],
  extends: [
    'eslint:recommended',
    'plugin:@python-eslint/recommended',
    'prettier',
  ],
  env: {
    node: true,
    es6: true,
  },
  files: ['app/**/*.ts'],
  rules: {
    'prettier/prettier': 'error',
  },
};
