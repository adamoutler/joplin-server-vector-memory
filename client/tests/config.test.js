const { JoplinSyncClient } = require('../src/sync');
const fs = require('fs');
const path = require('path');

describe('JoplinSyncClient Configuration Fallback', () => {
  let originalEnv;
  const testConfigPath = path.join(__dirname, 'test-config.json');

  beforeEach(() => {
    originalEnv = { ...process.env };
    process.env.CONFIG_PATH = testConfigPath;
    
    // Clear out env vars for these tests to test defaults and file
    delete process.env.OLLAMA_URL;
    delete process.env.EMBEDDING_MODEL;
    
    if (fs.existsSync(testConfigPath)) {
      fs.unlinkSync(testConfigPath);
    }
  });

  afterEach(() => {
    process.env = originalEnv;
    if (fs.existsSync(testConfigPath)) {
      fs.unlinkSync(testConfigPath);
    }
  });

  it('should fallback to default values when no config file and no env vars exist', async () => {
    const client = new JoplinSyncClient();
    const config = await client.getConfig();
    expect(config.ollamaUrl).toBe('http://localhost:11434');
    expect(config.embeddingModel).toBe('nomic-embed-text');
  });

  it('should use environment variables if set and no config file exists', async () => {
    process.env.OLLAMA_URL = 'http://env-ollama:11434';
    process.env.EMBEDDING_MODEL = 'env-model';
    
    const client = new JoplinSyncClient();
    const config = await client.getConfig();
    expect(config.ollamaUrl).toBe('http://env-ollama:11434');
    expect(config.embeddingModel).toBe('env-model');
  });

  it('should prefer config file over environment variables', async () => {
    process.env.OLLAMA_URL = 'http://env-ollama:11434';
    process.env.EMBEDDING_MODEL = 'env-model';
    
    const testConfig = {
      ollamaUrl: 'http://file-ollama:11434',
      embeddingModel: 'file-model'
    };
    fs.writeFileSync(testConfigPath, JSON.stringify(testConfig));
    
    const client = new JoplinSyncClient();
    const config = await client.getConfig();
    expect(config.ollamaUrl).toBe('http://file-ollama:11434');
    expect(config.embeddingModel).toBe('file-model');
  });
  
  it('should support uppercase keys in config file', async () => {
    const testConfig = {
      OLLAMA_URL: 'http://file-ollama-upper:11434',
      EMBEDDING_MODEL: 'file-model-upper'
    };
    fs.writeFileSync(testConfigPath, JSON.stringify(testConfig));
    
    const client = new JoplinSyncClient();
    const config = await client.getConfig();
    expect(config.ollamaUrl).toBe('http://file-ollama-upper:11434');
    expect(config.embeddingModel).toBe('file-model-upper');
  });
});