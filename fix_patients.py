import sqlite3, psycopg2, sys
sys.stdout.reconfigure(encoding='utf-8')

PG_URL = 'postgresql://postgres:pDtobFiQWQWGDWTSLXtVpLThhRyWeNQE@altaria.proxy.rlwy.net:40519/railway'
SQLITE_PATH = r'C:\Users\Kyros\Downloads\Muscle Station\database.db'

src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row
pg = psycopg2.connect(PG_URL, sslmode='require', connect_timeout=15)
cur = pg.cursor()

# Get IDs already in PG
cur.execute('SELECT id FROM patients')
existing = {r[0] for r in cur.fetchall()}

rows = src.execute('SELECT * FROM patients').fetchall()
cols = [d[0] for d in src.execute('SELECT * FROM patients').description]

# Clean values: convert empty strings to None for integer columns
int_cols = {'age'}
ph = ','.join(['%s'] * len(cols))
cn = ','.join(cols)
count = 0
skipped = 0
for r in rows:
    if r['id'] in existing:
        skipped += 1
        continue
    vals = []
    for c in cols:
        v = r[c]
        if c in int_cols and v == '':
            v = None
        vals.append(v)
    try:
        cur.execute(f'INSERT INTO patients ({cn}) VALUES ({ph})', vals)
        count += 1
    except Exception as e:
        pg.rollback()
        cur = pg.cursor()
        print(f'Patient {r["id"]} ERR: {e}')
        continue

pg.commit()
pg.autocommit = True
cur.execute("SELECT setval('patients_id_seq', (SELECT COALESCE(MAX(id),1) FROM patients))")
src.close()
pg.close()
print(f'Imported: {count}, Skipped (already exists): {skipped}')
