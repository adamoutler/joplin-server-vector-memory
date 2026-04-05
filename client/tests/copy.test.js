const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

describe('Frontend token copy functionality', () => {
  let dom;
  let document;
  let window;

  beforeEach(() => {
    const html = fs.readFileSync(path.join(__dirname, '../public/index.html'), 'utf8');
    dom = new JSDOM(html, { runScripts: 'dangerously' });
    window = dom.window;
    document = window.document;

    Object.assign(window.navigator, {
      clipboard: {
        writeText: jest.fn().mockResolvedValue()
      }
    });
    window.isSecureContext = true;
    
    window.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ 
        syncState: { status: 'ready' },
        config: { 
          api_keys: [{ key: 'test-token-123', annotation: 'Test Key', id: '123' }]
        }
      })
    });
    
    // Call fetchStatus again now that fetch is mocked
    window.fetchStatus(true);
  });

  test('Clicking copy button copies token and gives visual feedback', async () => {
    // Wait for the initial fetchStatus to run
    await new Promise(resolve => setTimeout(resolve, 100));

    // The API keys list should be populated
    const listEl = document.getElementById('api-keys-list');
    const items = listEl.querySelectorAll('div');
    expect(items.length).toBe(1);

    const copyBtn = items[0].querySelectorAll('button')[0]; // First button is Copy
    
    copyBtn.click();
    
    await new Promise(resolve => setTimeout(resolve, 10));

    expect(window.navigator.clipboard.writeText).toHaveBeenCalledWith('test-token-123');
    expect(copyBtn.innerText).toBe('Copied!');
  });
});
