const { JoplinSyncClient } = require('./src/sync.js');
const Note = require('@joplin/lib/models/Note').default;
const Folder = require('@joplin/lib/models/Folder').default;

async function main() {
  const secretStr = process.argv[2] || "secret";
  const profileDir = process.env.JOPLIN_PROFILE_DIR || '/tmp/e2e-joplin-client';
  
  const client = new JoplinSyncClient({ 
    profileDir: profileDir,
    serverUrl: process.env.JOPLIN_SERVER_URL || 'http://localhost:22300',
    username: process.env.JOPLIN_USERNAME || 'admin@localhost',
    password: process.env.JOPLIN_PASSWORD || 'admin'
  });
  
  await client.init();
  
  // Create a folder
  let folder = await Folder.save({ title: "E2E Test Folder" });
  
  // Generate random padding text
  const generateRandomWord = () => Math.random().toString(36).substring(2, 8);
  const randomTextChunk = Array.from({ length: 500 }, generateRandomWord).join(" ");
  const randomTextChunk2 = Array.from({ length: 500 }, generateRandomWord).join(" ");

  // Create a note with large random text to test token size limits
  let note = await Note.save({
    title: "E2E Secret Note with Large Token Size",
    body: `${randomTextChunk}\n\nthe secret number is ${secretStr}\n\n${randomTextChunk2}`,
    parent_id: folder.id
  });
  
  console.log("Created note ID:", note.id);
  
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
