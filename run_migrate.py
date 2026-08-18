import sqlite3, psycopg2, sys
sys.stdout.reconfigure(encoding='utf-8')

PG_URL = 'postgresql://postgres:pDtobFiQWQWGDWTSLXtVpLThhRyWeNQE@altaria.proxy.rlwy.net:40519/railway'
SQLITE_PATH = r'C:\Users\Kyros\Downloads\Muscle Station\database.db'

pg = psycopg2.connect(PG_URL, sslmode='require', connect_timeout=15)
pg.autocommit = True
cur = pg.cursor()

# Drop and recreate patients and visits with correct columns
cur.execute('DROP TABLE IF EXISTS audit_log CASCADE')
cur.execute('DROP TABLE IF EXISTS treasury CASCADE')
cur.execute('DROP TABLE IF EXISTS rehab_protocols CASCADE')
cur.execute('DROP TABLE IF EXISTS treatment_plans CASCADE')
cur.execute('DROP TABLE IF EXISTS pt_sessions CASCADE')
cur.execute('DROP TABLE IF EXISTS exercise_prescriptions CASCADE')
cur.execute('DROP TABLE IF EXISTS exercise_protocols CASCADE')
cur.execute('DROP TABLE IF EXISTS pain_assessments CASCADE')
cur.execute('DROP TABLE IF EXISTS settings CASCADE')
cur.execute('DROP TABLE IF EXISTS medical_images CASCADE')
cur.execute('DROP TABLE IF EXISTS lab_tests CASCADE')
cur.execute('DROP TABLE IF EXISTS prescriptions CASCADE')
cur.execute('DROP TABLE IF EXISTS packages CASCADE')
cur.execute('DROP TABLE IF EXISTS visits CASCADE')
cur.execute('DROP TABLE IF EXISTS patients CASCADE')
cur.execute('DROP TABLE IF EXISTS users CASCADE')
print('All tables dropped')

# Recreate with correct columns matching SQLite exactly
cur.execute("""CREATE TABLE users (
    id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
    full_name TEXT, email TEXT, phone TEXT, role TEXT DEFAULT 'doctor',
    specialty TEXT, is_active INTEGER DEFAULT 1, last_login TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE patients (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT,
    age INTEGER, address TEXT, diagnosis TEXT, gender TEXT DEFAULT 'ذكر',
    blood_type TEXT, chronic_diseases TEXT, allergies TEXT, medications TEXT,
    surgeries TEXT, family_history TEXT, social_history TEXT, notes TEXT,
    emergency_contact_name TEXT, emergency_contact_phone TEXT,
    insurance_company TEXT, insurance_number TEXT, national_id TEXT,
    occupation TEXT, work_nature TEXT, pain_area TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    phone2 TEXT, patient_code TEXT
)""")
cur.execute("""CREATE TABLE visits (
    id SERIAL PRIMARY KEY, patient_id INTEGER, cost REAL DEFAULT 0,
    visit_date TEXT, diagnosis TEXT, symptoms TEXT, examination TEXT, notes TEXT,
    payment_status TEXT, payment_method TEXT, visit_type TEXT,
    paid_amount REAL DEFAULT 0, remaining_amount REAL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, session_count INTEGER DEFAULT 1,
    session_days TEXT, subscription_type TEXT, session_time TEXT
)""")
cur.execute("""CREATE TABLE packages (
    id SERIAL PRIMARY KEY, patient_id INTEGER, package_name TEXT,
    total_sessions INTEGER, used_sessions INTEGER DEFAULT 0, cost REAL,
    purchase_date TEXT, notes TEXT, is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE prescriptions (
    id SERIAL PRIMARY KEY, visit_id INTEGER, patient_id INTEGER,
    medication_name TEXT, dosage TEXT, frequency TEXT, duration TEXT,
    instructions TEXT, category TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE lab_tests (
    id SERIAL PRIMARY KEY, visit_id INTEGER, patient_id INTEGER,
    test_name TEXT, result TEXT, normal_range TEXT, status TEXT, notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE medical_images (
    id SERIAL PRIMARY KEY, visit_id INTEGER, patient_id INTEGER,
    image_type TEXT, description TEXT, file_path TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE settings (
    id SERIAL PRIMARY KEY, clinic_name TEXT, doctor_name TEXT,
    clinic_address TEXT, clinic_phone TEXT, clinic_email TEXT, currency TEXT,
    visit_cost_default REAL, logo_path TEXT, backup_dir TEXT,
    auto_backup_enabled INTEGER, last_backup_time TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE pain_assessments (
    id SERIAL PRIMARY KEY, visit_id INTEGER, patient_id INTEGER,
    pain_score INTEGER, pain_location TEXT, pain_type TEXT,
    aggravating_factors TEXT, relieving_factors TEXT, assessed_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE exercise_protocols (
    id SERIAL PRIMARY KEY, name TEXT, description TEXT, targeted_muscles TEXT,
    difficulty TEXT, instructions TEXT, precautions TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE exercise_prescriptions (
    id SERIAL PRIMARY KEY, patient_id INTEGER, visit_id INTEGER,
    protocol_id INTEGER, plan_id INTEGER, custom_name TEXT, sets TEXT, reps TEXT,
    frequency_per_week TEXT, duration_weeks TEXT, instructions TEXT, status TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE pt_sessions (
    id SERIAL PRIMARY KEY, visit_id INTEGER, patient_id INTEGER,
    treatment_type TEXT, treatment_area TEXT, modalities_used TEXT, manual_therapy TEXT,
    therapeutic_exercise TEXT, patient_response TEXT, pain_before INTEGER, pain_after INTEGER,
    notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE treatment_plans (
    id SERIAL PRIMARY KEY, patient_id INTEGER, plan_name TEXT, goals TEXT,
    recommended_sessions INTEGER, sessions_per_week TEXT, start_date TEXT, end_date TEXT,
    status TEXT, notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE rehab_protocols (
    id SERIAL PRIMARY KEY, name TEXT, target_condition TEXT, description TEXT,
    phases TEXT, duration_weeks INTEGER, contraindications TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE treasury (
    id SERIAL PRIMARY KEY, type TEXT, amount INTEGER, reason TEXT,
    related_to TEXT, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
cur.execute("""CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY, user_id INTEGER, user_name TEXT, action TEXT,
    table_name TEXT, record_id INTEGER, details TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
print('All tables recreated with correct columns')

# Now migrate data
src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row

TABLES = ['users','patients','visits','packages','prescriptions','lab_tests','medical_images','settings','pain_assessments','exercise_protocols','exercise_prescriptions','pt_sessions','treatment_plans','rehab_protocols','treasury','audit_log']
pg.autocommit = False
total = 0
for table in TABLES:
    try:
        rows = src.execute(f'SELECT * FROM {table}').fetchall()
    except:
        print(f'{table}: skip')
        continue
    if not rows:
        print(f'{table}: empty')
        continue
    cols = [d[0] for d in src.execute(f'SELECT * FROM {table}').description]
    ph = ','.join(['%s'] * len(cols))
    cn = ','.join(cols)
    count = 0
    for r in rows:
        vals = [r[c] for c in cols]
        try:
            cur.execute(f'INSERT INTO {table} ({cn}) VALUES ({ph})', vals)
            count += 1
        except Exception as e:
            pg.rollback()
            cur = pg.cursor()
            print(f'{table} ERR: {e}')
            break
    if count > 0:
        pg.commit()
        total += count
        print(f'{table}: {count}')

# Reset sequences
for t in TABLES:
    try:
        pg.autocommit = True
        cur.execute(f"SELECT setval('{t}_id_seq', (SELECT COALESCE(MAX(id),1) FROM {t}))")
        pg.autocommit = False
    except:
        pass

pg.commit()
src.close()
pg.close()
print(f'\nTOTAL: {total} records imported!')
