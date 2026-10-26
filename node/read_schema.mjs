// Reads the table list through the oktografx CLI. Node 20+, no packages.
// Usage: node node/read_schema.mjs STORE_PATH PYTHON_EXECUTABLE
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const run = promisify(execFile);

export async function readSchema(storePath, python, { timeoutMs = 30000, maxBytes = 4 * 1024 * 1024 } = {}) {
  // No shell: arguments go in as an array.
  const { stdout } = await run(
    python,
    ['-m', 'okto_grafx.cli', 'schema', storePath, '--json', '--limit', '100'],
    { timeout: timeoutMs, maxBuffer: maxBytes },
  );
  const doc = JSON.parse(stdout);
  if (doc.exit_code !== 0 || doc.result !== 'ok') throw new Error(`schema command failed: ${doc.result}`);
  if (doc.truncated) throw new Error('schema output was truncated');
  return doc;
}

const [, , storePath, python] = process.argv;
if (storePath && python) {
  const doc = await readSchema(storePath, python);
  const tables = doc.tables.map((t) => ({ name: t.name, kind: t.kind, columns: t.columns.map((c) => c.name) }));
  console.log(JSON.stringify({ returned_tables: doc.returned_tables, returned_spaces: doc.returned_spaces, tables }, null, 1));
}
