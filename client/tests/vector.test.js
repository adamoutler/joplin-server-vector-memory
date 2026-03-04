const sqlite3 = require('sqlite3');
const sqliteVec = require('sqlite-vec');

describe('sqlite-vec functionality', () => {
  let db;

  beforeAll((done) => {
    db = new sqlite3.Database(':memory:', (err) => {
      if (err) return done(err);
      sqliteVec.load(db);
      db.serialize(() => {
        db.run(`CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(embedding float[3])`);
        db.run(`CREATE TABLE IF NOT EXISTS note_metadata (rowid INTEGER PRIMARY KEY, note_id TEXT UNIQUE, title TEXT, content TEXT)`, done);
      });
    });
  });

  afterAll((done) => {
    db.close(done);
  });

  it('should insert and query using vec_distance_cosine', (done) => {
    const e1 = JSON.stringify([0.1, 0.2, 0.3]);
    const e2 = JSON.stringify([0.1, 0.2, 0.4]);
    
    db.serialize(() => {
      db.run(`INSERT INTO note_metadata (note_id, title, content) VALUES ('test1', 'title1', 'text1')`, function(err) {
        if (err) return done(err);
        const id1 = this.lastID;
        db.run(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [id1, e1], (err) => {
          if (err) return done(err);
          
          db.run(`INSERT INTO note_metadata (note_id, title, content) VALUES ('test2', 'title2', 'text2')`, function(err) {
            if (err) return done(err);
            const id2 = this.lastID;
            db.run(`INSERT INTO vec_notes(rowid, embedding) VALUES (?, ?)`, [id2, e2], (err) => {
              if (err) return done(err);
              
              // Now query for distance
              db.all(`SELECT note_id, vec_distance_cosine(embedding, ?) as distance 
                      FROM vec_notes 
                      JOIN note_metadata ON note_metadata.rowid = vec_notes.rowid
                      ORDER BY distance LIMIT 2`, [e1], (err, rows) => {
                if (err) return done(err);
                
                expect(rows).toHaveLength(2);
                expect(rows[0].note_id).toBe('test1');
                expect(rows[0].distance).toBeCloseTo(0, 5); // Distance to itself is ~0
                expect(rows[1].note_id).toBe('test2');
                expect(rows[1].distance).toBeGreaterThan(0);
                done();
              });
            });
          });
        });
      });
    });
  });
});
