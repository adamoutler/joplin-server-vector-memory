const { JoplinSyncClient } = require('./src/sync.js');
const Note = require('@joplin/lib/models/Note').default;

async function main() {
  const client = new JoplinSyncClient({ profileDir: '/tmp/test-profile' });
  await client.init();
  try {
    const notes = await Note.modelSelectAll('SELECT * FROM notes WHERE encryption_applied = 0');
    console.log("Notes count:", notes.length);
  } catch (e) {
    console.error(e);
  }
}
main();
