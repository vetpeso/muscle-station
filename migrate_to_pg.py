import sqlite3
import psycopg2
import sys

sys.stdout.reconfigure(encoding='utf-8')

PG_URL = "postgresql://postgres:pDtobFiQWQWGDWTSLXtVpLThhRyWeNQE@altaria.proxy.rlwy.net:40519/railway"
SQLITE_PATH = r"C:\Users\Kyros\Downloads\Muscle Station\database.db"

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
    full_name TEXT, email TEXT, phone TEXT, role TEXT DEFAULT 'doctor',
    specialty TEXT, is_active INTEGER DEFAULT 1, last_login TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, phone2 TEXT,
    age INTEGER, address TEXT, diagnosis TEXT, gender TEXT DEFAULT 'ذكر',
    chronic_diseases TEXT, work_nature TEXT, pain_area TEXT, patient_code TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS visits (
    id SERIAL PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    cost REAL DEFAULT 0, visit_date TEXT NOT NULL, diagnosis TEXT, symptoms TEXT,
    examination TEXT, notes TEXT, payment_status TEXT DEFAULT 'مدفوع',
    payment_method TEXT DEFAULT 'نقدي', visit_type TEXT DEFAULT 'كشف',
    paid_amount REAL DEFAULT 0, remaining_amount REAL DEFAULT 0,
    session_count INTEGER DEFAULT 1, session_days TEXT, session_time TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS packages (
    id SERIAL PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    package_name TEXT NOT NULL, total_sessions INTEGER NOT NULL, used_sessions INTEGER DEFAULT 0,
    cost REAL NOT NULL, purchase_date TEXT NOT NULL, notes TEXT, is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS prescriptions (
    id SERIAL PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    medication_name TEXT NOT NULL, dosage TEXT, frequency TEXT, duration TEXT,
    instructions TEXT, category TEXT DEFAULT 'دواء', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS lab_tests (
    id SERIAL PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    test_name TEXT NOT NULL, result TEXT, normal_range TEXT, status TEXT DEFAULT 'مطلوب',
    notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS medical_images (
    id SERIAL PRIMARY KEY, visit_id INTEGER REFERENCES visits(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    image_type TEXT NOT NULL, description TEXT, file_path TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS settings (
    id SERIAL PRIMARY KEY, clinic_name TEXT DEFAULT 'عيادتي', doctor_name TEXT,
    clinic_address TEXT, clinic_phone TEXT, clinic_email TEXT, currency TEXT DEFAULT 'ج.م',
    visit_cost_default REAL DEFAULT 100, logo_path TEXT, backup_dir TEXT,
    auto_backup_enabled INTEGER DEFAULT 1, last_backup_time TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pain_assessments (
    id SERIAL PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    pain_score INTEGER NOT NULL, pain_location TEXT, pain_type TEXT,
    aggravating_factors TEXT, relieving_factors TEXT, assessed_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS exercise_protocols (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL, description TEXT, targeted_muscles TEXT,
    difficulty TEXT DEFAULT 'متوسط', instructions TEXT, precautions TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS exercise_prescriptions (
    id SERIAL PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    visit_id INTEGER REFERENCES visits(id) ON DELETE SET NULL,
    protocol_id INTEGER REFERENCES exercise_protocols(id) ON DELETE SET NULL,
    plan_id INTEGER, custom_name TEXT, sets TEXT, reps TEXT, frequency_per_week TEXT,
    duration_weeks TEXT, instructions TEXT, status TEXT DEFAULT 'نشط', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS pt_sessions (
    id SERIAL PRIMARY KEY, visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    treatment_type TEXT, treatment_area TEXT, modalities_used TEXT, manual_therapy TEXT,
    therapeutic_exercise TEXT, patient_response TEXT, pain_before INTEGER, pain_after INTEGER,
    notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS treatment_plans (
    id SERIAL PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    plan_name TEXT NOT NULL, goals TEXT, recommended_sessions INTEGER, sessions_per_week TEXT,
    start_date TEXT, end_date TEXT, status TEXT DEFAULT 'نشط', notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS rehab_protocols (
    id SERIAL PRIMARY KEY, name TEXT NOT NULL, target_condition TEXT, description TEXT,
    phases TEXT, duration_weeks INTEGER, contraindications TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS treasury (
    id SERIAL PRIMARY KEY, type TEXT NOT NULL, amount INTEGER NOT NULL,
    reason TEXT, related_to TEXT, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY, user_id INTEGER, user_name TEXT, action TEXT NOT NULL,
    table_name TEXT NOT NULL, record_id INTEGER, details TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

print("Connecting...")
pg = psycopg2.connect(PG_URL, sslmode='require', connect_timeout=15)
pg.autocommit = True
cur = pg.cursor()

print("Creating tables...")
cur.execute(CREATE_TABLES)
print("Tables created!")

src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row

TABLES = [
    'users', 'patients', 'visits', 'packages', 'prescriptions', 'lab_tests',
    'medical_images', 'settings', 'pain_assessments', 'exercise_protocols',
    'exercise_prescriptions', 'pt_sessions', 'treatment_plans', 'rehab_protocols',
    'treasury', 'audit_log'
]

pg.autocommit = False
total = 0
for table in TABLES:
    try:
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
    except Exception as e:
        print(f"  {table}: skip ({e})")
        continue
    if not rows:
        print(f"  {table}: empty")
        continue

    cols = rows[0].keys()
    col_names = ', '.join(cols)
    placeholders = ', '.join(['%s'] * len(cols))
    count = 0
    for row in rows:
        values = [row[c] for c in cols]
        try:
            cur.execute(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", values)
            count += 1
        except Exception as e:
            pg.rollback()
            if 'duplicate key' in str(e).lower():
                cur2 = pg.cursor()
                continue
            print(f"  {table} error: {e}")
            cur2 = pg.cursor()
            continue
    pg.commit()
    total += count
    print(f"  {table}: {count} records")

src.close()
pg.close()
print(f"\nDone! Total: {total} records imported")
