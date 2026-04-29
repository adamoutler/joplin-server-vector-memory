 // eslint-disable-next-line no-unused-vars
const fs = require('fs');
 // eslint-disable-next-line no-unused-vars
const path = require('path');

// Mock syncClient module before requiring index.js
const mockSync = jest.fn().mockResolvedValue();
const mockDecrypt = jest.fn().mockResolvedValue();
const mockGenerateEmbeddings = jest.fn().mockResolvedValue();
const mockInit = jest.fn().mockResolvedValue();

jest.mock('../src/sync', () => {
    return {
        JoplinSyncClient: class {
            constructor() {}
            init = mockInit;
            sync = mockSync;
            decrypt = mockDecrypt;
            generateEmbeddings = mockGenerateEmbeddings;
            on() {}
        }
    };
});

const app = require('../src/index');

describe('Event-Based Polling Synchronization', () => {
    let originalFetch;
    let configObj;

    beforeEach(() => {
        originalFetch = global.fetch;
        
        mockSync.mockClear();
        mockDecrypt.mockClear();
        mockGenerateEmbeddings.mockClear();
        mockInit.mockClear();

        configObj = {
            joplinServerUrl: 'http://localhost:22300',
            joplinUsername: 'test',
            joplinPassword: 'password'
        };

        global.fetch = jest.fn();
        
        // Reset Express state
        app.syncState = { status: 'ready', progress: null };
        app.embeddingState = { status: 'ready', progress: null };
    });

    afterEach(() => {
        global.fetch = originalFetch;
        jest.clearAllMocks();
    });

    it('should run full sync if no cursor is present', async () => {
        // First call: session
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 'session-123' }) });
        // Second call: info.json (check permissions)
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
        // Third call: initial cursor fetch
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ cursor: 'cursor-456' }) });

        // Act
        await app.runSyncCycle(configObj);

        // Assert
        expect(mockSync).toHaveBeenCalled();
        expect(mockDecrypt).toHaveBeenCalled();
        expect(mockGenerateEmbeddings).toHaveBeenCalledWith(); // no specific ids passed
        expect(configObj.lastEventCursor).toBe('cursor-456');
    });

    it('should bypass sync and embedding if cursor exists but no note events', async () => {
        configObj.lastEventCursor = 'cursor-456';
        
        // First call: session
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 'session-123' }) });
        // Second call: info.json
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
        // Third call: /events?cursor=cursor-456
        global.fetch.mockResolvedValueOnce({
            ok: true, 
            json: async () => ({
                has_more: false,
                cursor: 'cursor-789',
                items: [
                    { item_type: 2, type: 1, item_id: 'folder1' } // Not a note (item_type=1)
                ]
            })
        });

        // Act
        await app.runSyncCycle(configObj);

        // Assert
        expect(mockSync).not.toHaveBeenCalled();
        expect(mockDecrypt).not.toHaveBeenCalled();
        expect(mockGenerateEmbeddings).not.toHaveBeenCalled();
        expect(configObj.lastEventCursor).toBe('cursor-789');
    });

    it('should perform targeted embeddings if note events are returned', async () => {
        configObj.lastEventCursor = 'cursor-456';
        
        // First call: session
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 'session-123' }) });
        // Second call: info.json
        global.fetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });
        // Third call: /events?cursor=cursor-456
        global.fetch.mockResolvedValueOnce({
            ok: true, 
            json: async () => ({
                has_more: false,
                cursor: 'cursor-789',
                items: [
                    { item_type: 1, type: 1, item_id: 'note1' }, // Created note
                    { item_type: 1, type: 3, item_id: 'note2' }  // Deleted note
                ]
            })
        });

        // Act
        await app.runSyncCycle(configObj);

        // Assert
        expect(mockSync).toHaveBeenCalled();
        expect(mockDecrypt).toHaveBeenCalled();
        
        // Verify targeted embedding called
        expect(mockGenerateEmbeddings).toHaveBeenCalledWith(['note1'], ['note2']);
        
        // Cursor advanced
        expect(configObj.lastEventCursor).toBe('cursor-789');
    });
});