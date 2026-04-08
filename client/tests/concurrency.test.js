const request = require('supertest');
const app = require('../src/index');

describe('Concurrency Sequential Writes', () => {
  let server;
  beforeAll((done) => {
    // Prevent the default rate limiter from failing our tests
    app.set('trust proxy', 1);
    server = app.listen(0, done);
  });

  afterAll((done) => {
    server.close(done);
  });

  it('processes concurrent mutating requests sequentially', async () => {
    let activeRequests = 0;
    let maxActiveRequests = 0;
    
    // We mock the route handler temporarily to inject a delay and measure concurrency
    const originalPost = app._router.stack.find(
        (layer) => layer.route && layer.route.path === '/node-api/notes' && layer.route.methods.post
    );

    const originalHandle = originalPost.route.stack[0].handle;

    originalPost.route.stack[0].handle = async (req, res) => {
        activeRequests++;
        if (activeRequests > maxActiveRequests) {
            maxActiveRequests = activeRequests;
        }
        
        // Simulate a delay (e.g. database write)
        await new Promise(resolve => setTimeout(resolve, 50));
        
        activeRequests--;
        res.status(200).json({ id: 'test_id', parent_id: 'test_parent', status: 'success' });
    };

    // Send 5 concurrent requests
    const promises = [];
    for (let i = 0; i < 5; i++) {
      promises.push(
        request(server)
          .post('/node-api/notes')
          .send({ title: 'Test ' + i, body: 'Body ' + i, folder: 'Folder' })
      );
    }

    const results = await Promise.all(promises);

    // Restore original handler
    originalPost.route.stack[0].handle = originalHandle;

    results.forEach(res => {
      expect(res.status).toBe(200);
      expect(res.body.id).toBe('test_id');
    });

    // If they were processed sequentially, maxActiveRequests should be 1
    expect(maxActiveRequests).toBe(1);
  });
});
