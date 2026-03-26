const sqlite3 = require('./client/node_modules/sqlite3').verbose();
const db = new sqlite3.Database(':memory:');
db.loadExtension('client/node_modules/sqlite-vec/build/Release/sqlite_vec.node');

db.serialize(() => {
  db.run("CREATE VIRTUAL TABLE vec_notes USING vec0(embedding float[3])");
  
  const embedding = [1.0, 2.0, 3.0];
  const eStr = new Float32Array(embedding); // BUG! This will fail if not Buffer

  db.run("INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)", [318, eStr], function(err) {
    if (err) console.error("Error inserting:", err);
    console.log("Insert 1 lastID:", this.lastID);
    
    db.all("SELECT rowid FROM vec_notes", (err, rows) => {
      console.log("Rows:", rows);
    });
  });
});
