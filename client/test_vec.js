const sqlite3 = require('sqlite3');
const sqliteVec = require('sqlite-vec');

const db = new sqlite3.Database(':memory:');
sqliteVec.load(db);

db.serialize(() => {
  db.run(`CREATE VIRTUAL TABLE vec_notes USING vec0(embedding float[3])`);
  db.run(`CREATE TABLE note_metadata (rowid INTEGER PRIMARY KEY, note_id TEXT UNIQUE, text TEXT)`);

  const embedding = [0.1, 0.2, 0.3];
  db.run(`INSERT INTO note_metadata (note_id, text) VALUES (?, ?)`, ['note1', 'hello world'], function(err) {
    if (err) throw err;
    const rowid = this.lastID;
    const eStr = JSON.stringify(embedding);
    db.run(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [rowid, eStr], function(err) {
      if (err) throw err;
      db.all(`SELECT rowid, vec_to_json(embedding) as e FROM vec_notes`, (err, rows) => {
        console.log("Inserted:", rows);
        
        // test cosine distance
        db.all(`SELECT rowid, vec_distance_cosine(embedding, ?) as distance FROM vec_notes`, [eStr], (err, distRows) => {
          console.log("Distance:", distRows);
        });
      });
    });
  });
});
