import sqlite3, psycopg2, sys
sys.stdout.reconfigure(encoding='utf-8')

PG_URL = 'postgresql://postgres:pDtobFiQWQWGDWTSLXtVpLThhRyWeNQE@altaria.proxy.rlwy.net:40519/railway'
SQLITE_PATH = r'C:\Users\Kyros\Downloads\Muscle Station\database.db'

src = sqlite3.connect(SQLITE_PATH)
pg = psycopg2.connect(PG_URL, sslmode='require', connect_timeout=15)
cur = pg.cursor()

TABLES = ['users','patients','visits','packages','prescriptions','lab_tests','medical_images','settings','pain_assessments','exercise_protocols','exercise_prescriptions','pt_sessions','treatment_plans','rehab_protocols','treasury','audit_log']

print(f'{"Table":<22} {"SQLite":>8} {"Postgres":>8} {"Match":>7}')
print('-' * 48)
for t in TABLES:
    try:
        sqlite_count = src.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    except:
        sqlite_count = 0
    try:
        cur.execute(f'SELECT COUNT(*) FROM {t}')
        pg_count = cur.fetchone()[0]
    except:
        pg_count = 0
    match = 'OK' if sqlite_count == pg_count else 'DIFF'
    print(f'{t:<22} {sqlite_count:>8} {pg_count:>8} {match:>7}')

src.close()
pg.close()
