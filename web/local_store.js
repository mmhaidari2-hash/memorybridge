/* MemoryBridge local manual records: IndexedDB runtime + JSON/SQLite export. */
(function (root) {
  const DB_NAME = "memorybridge-local";
  const STORE = "manual_records";
  const KIND = "memorybridge.manual_records";
  const SECRET_MARKERS = ["mbs_", "sk_live_", "sk_test_", "whsec_", "STRIPE_SECRET", "STRIPE_WEBHOOK"];

  function looksSecret(value) {
    const lowered = String(value || "").toLowerCase();
    return SECRET_MARKERS.some((marker) => lowered.includes(marker.toLowerCase()));
  }

  function normalizeRecord(raw) {
    const title = String(raw.title || "").trim();
    const body = String(raw.body || "").trim();
    const source = String(raw.source || "manual").trim() || "manual";
    const id = String(raw.id || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())));
    const created_at = String(raw.created_at || new Date().toISOString());
    if (!title || !body) throw new Error("Record title and body are required");
    if (source !== "manual" && source !== "extension" && source !== "cli") throw new Error("Record source is not allowed");
    [title, body, id, created_at, source].forEach((field) => {
      if (looksSecret(field)) throw new Error("Manual records cannot contain credentials");
    });
    return { id, created_at, title, body, source };
  }

  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE, { keyPath: "id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error("IndexedDB unavailable"));
    });
  }

  async function withStore(mode, fn) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const store = tx.objectStore(STORE);
      const result = fn(store);
      tx.oncomplete = () => {
        db.close();
        resolve(result);
      };
      tx.onerror = () => {
        db.close();
        reject(tx.error || new Error("IndexedDB transaction failed"));
      };
    });
  }

  async function listRecords() {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, "readonly");
      const req = tx.objectStore(STORE).getAll();
      req.onsuccess = () => {
        db.close();
        const rows = (req.result || []).slice().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
        resolve(rows);
      };
      req.onerror = () => {
        db.close();
        reject(req.error);
      };
    });
  }

  async function addRecord(raw) {
    const record = normalizeRecord(raw);
    await withStore("readwrite", (store) => store.put(record));
    return record;
  }

  function exportBundle(records) {
    return { version: 1, kind: KIND, records: records.map(normalizeRecord) };
  }

  function exportJson(records) {
    return JSON.stringify(exportBundle(records), null, 2);
  }

  function sqlEscape(value) {
    return String(value).replace(/'/g, "''");
  }

  function exportSqliteSql(records) {
    const rows = exportBundle(records).records.map((item) => (
      "INSERT INTO manual_records (id, created_at, title, body, source) VALUES (" +
      `'${sqlEscape(item.id)}', '${sqlEscape(item.created_at)}', '${sqlEscape(item.title)}', '${sqlEscape(item.body)}', '${sqlEscape(item.source)}');`
    ));
    return [
      "BEGIN TRANSACTION;",
      "CREATE TABLE IF NOT EXISTS manual_records (",
      "  id TEXT PRIMARY KEY,",
      "  created_at TEXT NOT NULL,",
      "  title TEXT NOT NULL,",
      "  body TEXT NOT NULL,",
      "  source TEXT NOT NULL",
      ");",
      ...rows,
      "COMMIT;",
      "",
    ].join("\n");
  }

  function importBundle(payload) {
    const data = typeof payload === "string" ? JSON.parse(payload) : payload;
    if (!data || data.kind !== KIND) throw new Error("Import bundle kind is not recognized");
    if (Number(data.version) !== 1) throw new Error("Import bundle version is not supported");
    if (!Array.isArray(data.records)) throw new Error("Import bundle records must be a list");
    return data.records.map(normalizeRecord);
  }

  function parseSqlValues(blob) {
    const values = [];
    let i = 0;
    while (i < blob.length) {
      if (" \t,".includes(blob[i])) { i += 1; continue; }
      if (blob[i] !== "'") throw new Error("SQLite import values must be quoted");
      i += 1;
      let current = "";
      while (i < blob.length) {
        if (blob[i] === "'" && blob[i + 1] === "'") { current += "'"; i += 2; continue; }
        if (blob[i] === "'") { i += 1; break; }
        current += blob[i];
        i += 1;
      }
      values.push(current);
    }
    return values;
  }

  function importSqliteSql(sql) {
    if (looksSecret(sql)) throw new Error("Manual records cannot contain credentials");
    const prefix = "insert into manual_records (id, created_at, title, body, source) values (";
    const records = [];
    String(sql).split(/\r?\n/).forEach((raw) => {
      const line = raw.trim();
      if (!line || line.startsWith("--")) return;
      const upper = line.toUpperCase();
      if (upper.startsWith("INSERT ")) {
        if (!line.toLowerCase().startsWith(prefix) || !line.endsWith(");")) {
          throw new Error("SQLite import only accepts manual_records inserts");
        }
        const values = parseSqlValues(line.slice(prefix.length, -2));
        if (values.length !== 5) throw new Error("SQLite import row is malformed");
        records.push(normalizeRecord({
          id: values[0], created_at: values[1], title: values[2], body: values[3], source: values[4],
        }));
      }
    });
    if (!records.length) throw new Error("SQLite import contained no manual records");
    return records;
  }

  async function importAndStore(text) {
    const trimmed = String(text || "").trim();
    const records = trimmed.startsWith("{") ? importBundle(trimmed) : importSqliteSql(trimmed);
    for (const record of records) {
      await withStore("readwrite", (store) => store.put(record));
    }
    return records;
  }

  root.MemoryBridgeLocal = {
    normalizeRecord,
    listRecords,
    addRecord,
    exportJson,
    exportSqliteSql,
    importBundle,
    importSqliteSql,
    importAndStore,
    looksSecret,
  };
})(window);
