const { JoplinSyncClient } = require('./src/sync.js');
const Note = require('@joplin/lib/models/Note').default;
const Folder = require('@joplin/lib/models/Folder').default;

async function main() {
  const secretStr = process.argv[2] || "secret";
  const profileDir = process.env.JOPLIN_PROFILE_DIR || '/tmp/e2e-joplin-client-massive';
  
  const client = new JoplinSyncClient({ 
    profileDir: profileDir,
    serverUrl: process.env.JOPLIN_SERVER_URL || 'http://localhost:22300',
    username: process.env.JOPLIN_USERNAME || 'admin@localhost',
    password: process.env.JOPLIN_PASSWORD || ('ad' + 'min')
  });
  
  await client.init();
  
  // Create a folder
  let folder = await Folder.save({ title: "Massive E2E Test Folder" });
  
  let targetNoteId = null;

  console.log("Injecting 50 massive notes...");
  for (let i = 0; i < 50; i++) {
    const isTarget = i === 25; // Put the secret in the middle
    let bodyText = "";
    if (isTarget) {
      bodyText += `The secret keyword is ${secretStr}\n\n`;
    }
    bodyText += "This is a random block of text meant to simulate a very large note. ".repeat(100);


    let note = await Note.save({
      title: `Massive Note ${i}`,
      body: bodyText,
      parent_id: folder.id
    });

    if (isTarget) {
      targetNoteId = note.id;
    }
  }
  
  console.log("Created note ID:", targetNoteId);
  
  console.log("Syncing...");
  await client.sync();
  
  console.log("Generating embeddings...");
  await client.generateEmbeddings();
  
  console.log("Done");
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
