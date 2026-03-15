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
    
    window.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ready', config: { token: 'initial-token' } })
    });
  });

  test('Clicking copy button copies token and gives visual feedback', async () => {
    document.dispatchEvent(new window.Event('DOMContentLoaded'));
    await new Promise(resolve => setTimeout(resolve, 50));

    const tokenInput = document.getElementById('token');
    const copyBtn = document.getElementById('copy-btn');
    
    tokenInput.value = 'test-token-123';
    copyBtn.click();
    
    await new Promise(resolve => setTimeout(resolve, 10));

    expect(window.navigator.clipboard.writeText).toHaveBeenCalledWith('test-token-123');
    expect(copyBtn.innerText).toBe('✅');
  });
});
