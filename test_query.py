import psycopg2, sys
sys.stdout.reconfigure(encoding='utf-8')
pg = psycopg2.connect('postgresql://postgres:pDtobFiQWQWGDWTSLXtVpLThhRyWeNQE@altaria.proxy.rlwy.net:40519/railway', sslmode='require', connect_timeout=15)
cur = pg.cursor()
try:
    cur.execute("SELECT MAX(visit_date || 'T' || id) AS last_visit FROM visits GROUP BY patient_id LIMIT 1")
    print('Result:', cur.fetchone())
except Exception as e:
    print('ERROR:', e)

try:
    cur.execute("SELECT MAX(visit_date || 'T' || CAST(id AS TEXT)) AS last_visit FROM visits GROUP BY patient_id LIMIT 1")
    print('Fixed result:', cur.fetchone())
except Exception as e:
    print('ERROR 2:', e)

pg.close()
