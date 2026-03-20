module.exports = { 
  extends: ['@commitlint/config-conventional'],
  rules: {
    'header-max-length': [0, 'always', 100] // 0 means disabled
  }
};