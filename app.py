# ─── MUSCLE STATION 2026 - RAILWAY DEPLOYMENT TRIGGER ───
from flask import Flask, render_template, request, redirect, url_for, g, session, flash, make_response, send_from_directory
import sqlite3
import datetime
from functools import wraps
import os
import csv
import io
import sys
import re
import threading
import shutil
import webbrowser
from werkzeug.security import generate_password_hash, check_password_hash

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    EXE_DIR  = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    EXE_DIR  = BASE_DIR

# ─── تحميل ملف .env إن وجد ───
def _load_env():
    for d in [EXE_DIR, BASE_DIR, os.getcwd()]:
        env_path = os.path.join(d, '.env')
        if os.path.isfile(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass
            break

_load_env()

DATABASE_URL = os.environ.get("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.errorcodes
except ImportError:
    pass

DATABASE     = os.environ.get("CLINIC_DATABASE_PATH") or os.path.join(EXE_DIR, "database.db")
TEMPLATES_DIR = os.path.join(EXE_DIR, "templates") if os.path.isdir(os.path.join(EXE_DIR, "templates")) else os.path.join(BASE_DIR, "templates")
STATIC_DIR   = os.path.join(EXE_DIR, "static") if os.path.isdir(os.path.join(EXE_DIR, "static")) else os.path.join(BASE_DIR, "static")

app = Flask(__name__, template_folder=TEMPLATES_DIR, static_folder=STATIC_DIR)
app.secret_key = os.environ.get("CLINIC_SECRET_KEY") or "dev-only-change-me"


# ─── قاعدة البيانات ───

class _PGRow:
    def __init__(self, keys, values):
        self._keys = keys
        self._values = values
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        try:
            idx = self._keys.index(key)
            return self._values[idx]
        except (ValueError, IndexError):
            raise KeyError(key)
    def __contains__(self, key):
        return key in self._keys
    def __iter__(self):
        return iter(zip(self._keys, self._values))
    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default
    def keys(self):
        return self._keys

class _PGCursor:
    def __init__(self, cursor, wrapper=None):
        self._cur = cursor
        self._wrapper = wrapper
        self.description = cursor.description
        self.rowcount = cursor.rowcount
        self.lastrowid = None

    def execute(self, query, params=None):
        pg_query = query.replace('?', '%s')
        is_insert = pg_query.strip().upper().startswith('INSERT')
        if params:
            self._cur.execute(pg_query, params)
        else:
            self._cur.execute(pg_query)
        self.description = self._cur.description
        self.rowcount = self._cur.rowcount
        if is_insert and self._wrapper:
            try:
                rc = self._wrapper._conn.cursor()
                rc.execute("SELECT lastval()")
                r = rc.fetchone()
                self.lastrowid = r[0] if r else None
                rc.close()
            except Exception:
                self.lastrowid = None
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        keys = [d[0] for d in self.description] if self.description else list(range(len(row)))
        return _PGRow(keys, row)

    def fetchall(self):
        rows = self._cur.fetchall()
        keys = [d[0] for d in self.description] if self.description else []
        return [_PGRow(keys, r) for r in rows]

    def fetchmany(self, size=1):
        rows = self._cur.fetchmany(size)
        keys = [d[0] for d in self.description] if self.description else []
        return [_PGRow(keys, r) for r in rows]

class _PGWrapper:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, query, params=None):
        pg_query = query.replace('?', '%s')
        cur = self._conn.cursor()
        if params:
            cur.execute(pg_query, params)
        else:
            cur.execute(pg_query)
        return _PGCursor(cur, wrapper=self)

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db_url = os.environ.get("DATABASE_URL") or DATABASE_URL
        if db_url:
            raw = psycopg2.connect(db_url)
            raw.autocommit = False
            db = g._database = _PGWrapper(raw)
        else:
            db = g._database = sqlite3.connect(DATABASE)
            db.row_factory = sqlite3.Row
    return db

def db_execute(db, query, params=None):
    return db.execute(query, params)

def db_fetchone(db, query, params=None):
    r = db.execute(query, params)
    return r.fetchone()

def db_fetchall(db, query, params=None):
    r = db.execute(query, params)
    return r.fetchall()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# ─── سجل التتبع ───

def log_action(action, table_name, record_id=None, details=None):
    db = get_db()
    user_id = session.get('user_id')
    user_name = session.get('user_name', 'غير معروف')
    db.execute(
        "INSERT INTO audit_log (user_id, user_name, action, table_name, record_id, details) VALUES (?,?,?,?,?,?)",
        (user_id, user_name, action, table_name, record_id, details)
    )
    db.commit()


# ─── كلمات المرور ───

def _is_werkzeug_hash(value):
    return bool(value and ":" in value and len(value) > 20)

def verify_and_upgrade_password(stored_value, provided_password):
    """يتحقق من كلمة المرور ويرقّيها إن كانت نص عادي."""
    if not stored_value:
        return False, None
    if _is_werkzeug_hash(stored_value):
        return check_password_hash(stored_value, provided_password), None
    # توافق مع قواعد البيانات القديمة التي خزّنت النص الصريح
    if stored_value == provided_password:
        return True, generate_password_hash(provided_password)
    return False, None


# ─── تهيئة قاعدة البيانات ───

def _pg_table_exists(db, table_name):
    r = db_execute(db, "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name=%s)", (table_name,))
    return r.fetchone()[0]

def _pg_column_exists(db, table_name, col_name):
    r = db_execute(db, "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s)", (table_name, col_name))
    return r.fetchone()[0]

def _pg_add_column(db, table, col, defn):
    if not _pg_column_exists(db, table, col):
        db_execute(db, f'ALTER TABLE {table} ADD COLUMN {col} {defn}')
        db.commit()

def init_db():
    with app.app_context():
        db = get_db()

        if USE_POSTGRES:
            db_execute(db, """
                CREATE TABLE IF NOT EXISTS patients (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    phone2 TEXT,
                    age INTEGER,
                    address TEXT,
                    diagnosis TEXT,
                    gender TEXT DEFAULT 'ذكر',
                    chronic_diseases TEXT,
                    work_nature TEXT,
                    pain_area TEXT,
                    patient_code TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            _pg_add_column(db, 'patients', 'patient_code', 'TEXT')

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS visits (
                    id SERIAL PRIMARY KEY,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    cost REAL DEFAULT 0,
                    visit_date TEXT NOT NULL,
                    diagnosis TEXT,
                    symptoms TEXT,
                    examination TEXT,
                    notes TEXT,
                    payment_status TEXT DEFAULT 'مدفوع',
                    payment_method TEXT DEFAULT 'نقدي',
                    visit_type TEXT DEFAULT 'كشف',
                    paid_amount REAL DEFAULT 0,
                    remaining_amount REAL DEFAULT 0,
                    session_count INTEGER DEFAULT 1,
                    session_days TEXT,
                    session_time TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS packages (
                    id SERIAL PRIMARY KEY,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    package_name TEXT NOT NULL,
                    total_sessions INTEGER NOT NULL,
                    used_sessions INTEGER DEFAULT 0,
                    cost REAL NOT NULL,
                    purchase_date TEXT NOT NULL,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS prescriptions (
                    id SERIAL PRIMARY KEY,
                    visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    medication_name TEXT NOT NULL,
                    dosage TEXT,
                    frequency TEXT,
                    duration TEXT,
                    instructions TEXT,
                    category TEXT DEFAULT 'دواء',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS lab_tests (
                    id SERIAL PRIMARY KEY,
                    visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    test_name TEXT NOT NULL,
                    result TEXT,
                    normal_range TEXT,
                    status TEXT DEFAULT 'مطلوب',
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS medical_images (
                    id SERIAL PRIMARY KEY,
                    visit_id INTEGER REFERENCES visits(id) ON DELETE CASCADE,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    image_type TEXT NOT NULL,
                    description TEXT,
                    file_path TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    full_name TEXT,
                    email TEXT,
                    phone TEXT,
                    role TEXT DEFAULT 'doctor',
                    specialty TEXT,
                    is_active INTEGER DEFAULT 1,
                    last_login TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS settings (
                    id SERIAL PRIMARY KEY,
                    clinic_name TEXT DEFAULT 'عيادتي',
                    doctor_name TEXT,
                    clinic_address TEXT,
                    clinic_phone TEXT,
                    clinic_email TEXT,
                    currency TEXT DEFAULT 'ج.م',
                    visit_cost_default REAL DEFAULT 100,
                    logo_path TEXT,
                    backup_dir TEXT,
                    auto_backup_enabled INTEGER DEFAULT 1,
                    last_backup_time TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # مستخدم افتراضي
            r = db_fetchone(db, "SELECT COUNT(*) AS cnt FROM users")
            if r and r['cnt'] == 0:
                default_pw = os.environ.get("CLINIC_DEFAULT_ADMIN_PASSWORD") or "admin123"
                db_execute(db,
                    "INSERT INTO users (username, password, full_name, role, specialty) VALUES (%s,%s,%s,%s,%s)",
                    ("admin", generate_password_hash(default_pw), "د. معاذ", "admin", "باطنة عامة")
                )
            else:
                db_execute(db, "UPDATE users SET role='admin' WHERE username='admin' AND role!='admin'")
            db.commit()

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS pain_assessments (
                    id SERIAL PRIMARY KEY,
                    visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    pain_score INTEGER NOT NULL,
                    pain_location TEXT,
                    pain_type TEXT,
                    aggravating_factors TEXT,
                    relieving_factors TEXT,
                    assessed_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS exercise_protocols (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    targeted_muscles TEXT,
                    difficulty TEXT DEFAULT 'متوسط',
                    instructions TEXT,
                    precautions TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS exercise_prescriptions (
                    id SERIAL PRIMARY KEY,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    visit_id INTEGER REFERENCES visits(id) ON DELETE SET NULL,
                    protocol_id INTEGER REFERENCES exercise_protocols(id) ON DELETE SET NULL,
                    plan_id INTEGER,
                    custom_name TEXT,
                    sets TEXT,
                    reps TEXT,
                    frequency_per_week TEXT,
                    duration_weeks TEXT,
                    instructions TEXT,
                    status TEXT DEFAULT 'نشط',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS pt_sessions (
                    id SERIAL PRIMARY KEY,
                    visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    treatment_type TEXT,
                    treatment_area TEXT,
                    modalities_used TEXT,
                    manual_therapy TEXT,
                    therapeutic_exercise TEXT,
                    patient_response TEXT,
                    pain_before INTEGER,
                    pain_after INTEGER,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS treatment_plans (
                    id SERIAL PRIMARY KEY,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    plan_name TEXT NOT NULL,
                    goals TEXT,
                    recommended_sessions INTEGER,
                    sessions_per_week TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    status TEXT DEFAULT 'نشط',
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS rehab_protocols (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    target_condition TEXT,
                    description TEXT,
                    phases TEXT,
                    duration_weeks INTEGER,
                    contraindications TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS treasury (
                    id SERIAL PRIMARY KEY,
                    type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    reason TEXT,
                    related_to TEXT,
                    created_by INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db_execute(db, """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    user_name TEXT,
                    action TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    record_id INTEGER,
                    details TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # إعدادات افتراضية
            r = db_fetchone(db, "SELECT COUNT(*) AS cnt FROM settings")
            if r and r['cnt'] == 0:
                db_execute(db, "INSERT INTO settings (clinic_name, doctor_name) VALUES (%s,%s)", ("Muscle Station", "د. معاذ"))
                db.commit()

            # Indexes
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_visits_patient_id ON visits(patient_id)",
                "CREATE INDEX IF NOT EXISTS idx_visits_visit_date ON visits(visit_date)",
                "CREATE INDEX IF NOT EXISTS idx_visits_visit_type ON visits(visit_type)",
                "CREATE INDEX IF NOT EXISTS idx_prescriptions_visit_id ON prescriptions(visit_id)",
                "CREATE INDEX IF NOT EXISTS idx_prescriptions_patient_id ON prescriptions(patient_id)",
                "CREATE INDEX IF NOT EXISTS idx_lab_tests_visit_id ON lab_tests(visit_id)",
                "CREATE INDEX IF NOT EXISTS idx_lab_tests_patient_id ON lab_tests(patient_id)",
                "CREATE INDEX IF NOT EXISTS idx_pain_assessments_patient_id ON pain_assessments(patient_id)",
                "CREATE INDEX IF NOT EXISTS idx_pt_sessions_patient_id ON pt_sessions(patient_id)",
                "CREATE INDEX IF NOT EXISTS idx_treatment_plans_patient_id ON treatment_plans(patient_id)",
                "CREATE INDEX IF NOT EXISTS idx_exercise_prescriptions_patient_id ON exercise_prescriptions(patient_id)",
                "CREATE INDEX IF NOT EXISTS idx_audit_log_table ON audit_log(table_name, record_id)",
            ]:
                try:
                    db_execute(db, idx_sql)
                    db.commit()
                except Exception:
                    db.rollback()

        else:
            # ── SQLite ──
            c = db.cursor()

            c.execute("""
                CREATE TABLE IF NOT EXISTS patients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    phone2 TEXT,
                    age INTEGER,
                    address TEXT,
                    diagnosis TEXT,
                    gender TEXT DEFAULT 'ذكر',
                    chronic_diseases TEXT,
                    work_nature TEXT,
                    pain_area TEXT,
                    patient_code TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            try:
                c.execute("ALTER TABLE patients ADD COLUMN patient_code TEXT")
            except:
                pass

            missing = c.execute("SELECT id, created_at FROM patients WHERE patient_code IS NULL").fetchall()
            for row in missing:
                pid = row['id']
                created = row['created_at']
                if created:
                    dt = datetime.datetime.strptime(created[:10], '%Y-%m-%d')
                else:
                    dt = datetime.datetime.now()
                prefix = f"{dt.year % 100:02d}-{dt.month}-"
                existing = c.execute("SELECT patient_code FROM patients WHERE patient_code LIKE ?", (prefix + '%',)).fetchall()
                max_num = 0
                for r in existing:
                    try:
                        num = int(r['patient_code'].rsplit('-', 1)[-1])
                        if num > max_num:
                            max_num = num
                    except:
                        pass
                code = prefix + str(max_num + 1)
                c.execute("UPDATE patients SET patient_code=? WHERE id=?", (code, pid))
            db.commit()

            c.execute("""
                CREATE TABLE IF NOT EXISTS visits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL,
                    cost REAL DEFAULT 0,
                    visit_date TEXT NOT NULL,
                    diagnosis TEXT,
                    symptoms TEXT,
                    examination TEXT,
                    notes TEXT,
                    payment_status TEXT DEFAULT 'مدفوع',
                    payment_method TEXT DEFAULT 'نقدي',
                    visit_type TEXT DEFAULT 'كشف',
                    paid_amount REAL DEFAULT 0,
                    remaining_amount REAL DEFAULT 0,
                    session_time TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS packages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL,
                    package_name TEXT NOT NULL,
                    total_sessions INTEGER NOT NULL,
                    used_sessions INTEGER DEFAULT 0,
                    cost REAL NOT NULL,
                    purchase_date TEXT NOT NULL,
                    notes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS prescriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visit_id INTEGER NOT NULL,
                    patient_id INTEGER NOT NULL,
                    medication_name TEXT NOT NULL,
                    dosage TEXT,
                    frequency TEXT,
                    duration TEXT,
                    instructions TEXT,
                    category TEXT DEFAULT 'دواء',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (visit_id) REFERENCES visits (id) ON DELETE CASCADE,
                    FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS lab_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visit_id INTEGER NOT NULL,
                    patient_id INTEGER NOT NULL,
                    test_name TEXT NOT NULL,
                    result TEXT,
                    normal_range TEXT,
                    status TEXT DEFAULT 'مطلوب',
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (visit_id) REFERENCES visits (id) ON DELETE CASCADE,
                    FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS medical_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visit_id INTEGER,
                    patient_id INTEGER NOT NULL,
                    image_type TEXT NOT NULL,
                    description TEXT,
                    file_path TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (visit_id) REFERENCES visits (id) ON DELETE CASCADE,
                    FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    full_name TEXT,
                    email TEXT,
                    phone TEXT,
                    role TEXT DEFAULT 'doctor',
                    specialty TEXT,
                    is_active INTEGER DEFAULT 1,
                    last_login TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    clinic_name TEXT DEFAULT 'عيادتي',
                    doctor_name TEXT,
                    clinic_address TEXT,
                    clinic_phone TEXT,
                    clinic_email TEXT,
                    currency TEXT DEFAULT 'ج.م',
                    visit_cost_default REAL DEFAULT 100,
                    logo_path TEXT,
                    backup_dir TEXT,
                    auto_backup_enabled INTEGER DEFAULT 1,
                    last_backup_time TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # مستخدم افتراضي
            if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
                default_pw = os.environ.get("CLINIC_DEFAULT_ADMIN_PASSWORD") or "admin123"
                c.execute(
                    "INSERT INTO users (username, password, full_name, role, specialty) VALUES (?,?,?,?,?)",
                    ("admin", generate_password_hash(default_pw), "د. معاذ", "admin", "باطنة عامة")
                )
            else:
                c.execute("UPDATE users SET role='admin' WHERE username='admin' AND role!='admin'")

            c.execute("""
                CREATE TABLE IF NOT EXISTS pain_assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visit_id INTEGER NOT NULL,
                    patient_id INTEGER NOT NULL,
                    pain_score INTEGER NOT NULL,
                    pain_location TEXT,
                    pain_type TEXT,
                    aggravating_factors TEXT,
                    relieving_factors TEXT,
                    assessed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (visit_id) REFERENCES visits (id) ON DELETE CASCADE,
                    FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS exercise_protocols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    targeted_muscles TEXT,
                    difficulty TEXT DEFAULT 'متوسط',
                    instructions TEXT,
                    precautions TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS exercise_prescriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL,
                    visit_id INTEGER,
                    protocol_id INTEGER,
                    plan_id INTEGER,
                    custom_name TEXT,
                    sets TEXT,
                    reps TEXT,
                    frequency_per_week TEXT,
                    duration_weeks TEXT,
                    instructions TEXT,
                    status TEXT DEFAULT 'نشط',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE,
                    FOREIGN KEY (visit_id) REFERENCES visits (id) ON DELETE SET NULL,
                    FOREIGN KEY (protocol_id) REFERENCES exercise_protocols (id) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS pt_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visit_id INTEGER NOT NULL,
                    patient_id INTEGER NOT NULL,
                    treatment_type TEXT,
                    treatment_area TEXT,
                    modalities_used TEXT,
                    manual_therapy TEXT,
                    therapeutic_exercise TEXT,
                    patient_response TEXT,
                    pain_before INTEGER,
                    pain_after INTEGER,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (visit_id) REFERENCES visits (id) ON DELETE CASCADE,
                    FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS treatment_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL,
                    plan_name TEXT NOT NULL,
                    goals TEXT,
                    recommended_sessions INTEGER,
                    sessions_per_week TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    status TEXT DEFAULT 'نشط',
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (patient_id) REFERENCES patients (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS rehab_protocols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    target_condition TEXT,
                    description TEXT,
                    phases TEXT,
                    duration_weeks INTEGER,
                    contraindications TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS treasury (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    reason TEXT,
                    related_to TEXT,
                    created_by INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_name TEXT,
                    action TEXT NOT NULL,
                    table_name TEXT NOT NULL,
                    record_id INTEGER,
                    details TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # إعدادات افتراضية
            if c.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0:
                c.execute(
                    "INSERT INTO settings (clinic_name, doctor_name) VALUES (?,?)",
                    ("Muscle Station", "د. معاذ")
                )

            # Indexes for performance
            c.execute("CREATE INDEX IF NOT EXISTS idx_visits_patient_id ON visits(patient_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_visits_visit_date ON visits(visit_date)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_visits_visit_type ON visits(visit_type)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_prescriptions_visit_id ON prescriptions(visit_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_prescriptions_patient_id ON prescriptions(patient_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_lab_tests_visit_id ON lab_tests(visit_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_lab_tests_patient_id ON lab_tests(patient_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_pain_assessments_patient_id ON pain_assessments(patient_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_pt_sessions_patient_id ON pt_sessions(patient_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_treatment_plans_patient_id ON treatment_plans(patient_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_exercise_prescriptions_patient_id ON exercise_prescriptions(patient_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_table ON audit_log(table_name, record_id)")

        db.commit()


# ─── ترقية قاعدة البيانات (إضافة أعمدة مفقودة) ───

def migrate_db():
    if USE_POSTGRES:
        return
    db = get_db()
    c  = db.cursor()

    expected = {
        'patients': {
            'gender': "TEXT DEFAULT 'ذكر'",
            'phone2': 'TEXT', 'chronic_diseases': 'TEXT',
            'work_nature': 'TEXT', 'pain_area': 'TEXT',
            'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP", 'updated_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'visits': {
            'cost': 'REAL DEFAULT 0', 'diagnosis': 'TEXT', 'symptoms': 'TEXT',
            'examination': 'TEXT', 'notes': 'TEXT', 'payment_status': "TEXT DEFAULT 'مدفوع'",
            'payment_method': "TEXT DEFAULT 'نقدي'", 'visit_type': "TEXT DEFAULT 'جلسه علاج طبيعي'",
            'paid_amount': 'REAL DEFAULT 0', 'remaining_amount': 'REAL DEFAULT 0',
            'session_count': 'INTEGER DEFAULT 1', 'session_days': 'TEXT',
            'session_time': 'TEXT',
            'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'packages': {
            'used_sessions': 'INTEGER DEFAULT 0', 'notes': 'TEXT',
            'is_active': 'INTEGER DEFAULT 1', 'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'prescriptions': {
            'dosage': 'TEXT', 'frequency': 'TEXT', 'duration': 'TEXT',
            'instructions': 'TEXT', 'category': "TEXT DEFAULT 'دواء'",
            'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'lab_tests': {
            'result': 'TEXT', 'normal_range': 'TEXT', 'status': "TEXT DEFAULT 'مطلوب'",
            'notes': 'TEXT', 'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'medical_images': {
            'description': 'TEXT', 'file_path': 'TEXT',
            'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'users': {
            'full_name': 'TEXT', 'email': 'TEXT', 'phone': 'TEXT',
            'role': "TEXT DEFAULT 'doctor'", 'specialty': 'TEXT',
            'is_active': 'INTEGER DEFAULT 1', 'last_login': 'TEXT',
            'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'settings': {
            'clinic_address': 'TEXT', 'clinic_phone': 'TEXT', 'clinic_email': 'TEXT',
            'currency': "TEXT DEFAULT 'ج.م'", 'visit_cost_default': 'REAL DEFAULT 100',
            'logo_path': 'TEXT', 'updated_at': "TEXT DEFAULT CURRENT_TIMESTAMP",
            'backup_dir': 'TEXT', 'auto_backup_enabled': 'INTEGER DEFAULT 1',
            'last_backup_time': 'TEXT'
        },
        'pain_assessments': {
            'pain_score': 'INTEGER NOT NULL', 'pain_location': 'TEXT',
            'pain_type': 'TEXT', 'aggravating_factors': 'TEXT', 'relieving_factors': 'TEXT',
            'assessed_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'exercise_protocols': {
            'description': 'TEXT', 'targeted_muscles': 'TEXT', 'difficulty': "TEXT DEFAULT 'متوسط'",
            'instructions': 'TEXT', 'precautions': 'TEXT', 'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'exercise_prescriptions': {
            'custom_name': 'TEXT', 'sets': 'TEXT', 'reps': 'TEXT',
            'frequency_per_week': 'TEXT', 'duration_weeks': 'TEXT', 'instructions': 'TEXT',
            'status': "TEXT DEFAULT 'نشط'", 'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'pt_sessions': {
            'treatment_type': 'TEXT', 'treatment_area': 'TEXT', 'modalities_used': 'TEXT',
            'manual_therapy': 'TEXT', 'therapeutic_exercise': 'TEXT', 'patient_response': 'TEXT',
            'pain_before': 'INTEGER', 'pain_after': 'INTEGER', 'notes': 'TEXT',
            'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'treatment_plans': {
            'plan_name': 'TEXT NOT NULL', 'goals': 'TEXT', 'recommended_sessions': 'INTEGER',
            'sessions_per_week': 'TEXT', 'start_date': 'TEXT', 'end_date': 'TEXT',
            'status': "TEXT DEFAULT 'نشط'", 'notes': 'TEXT', 'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'rehab_protocols': {
            'target_condition': 'TEXT', 'description': 'TEXT', 'phases': 'TEXT',
            'duration_weeks': 'INTEGER', 'contraindications': 'TEXT', 'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'treasury': {
            'type': 'TEXT NOT NULL', 'amount': 'INTEGER NOT NULL',
            'reason': 'TEXT', 'related_to': 'TEXT', 'created_by': 'INTEGER',
            'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        },
        'audit_log': {
            'user_id': 'INTEGER', 'user_name': 'TEXT', 'action': 'TEXT NOT NULL',
            'table_name': 'TEXT NOT NULL', 'record_id': 'INTEGER', 'details': 'TEXT',
            'created_at': "TEXT DEFAULT CURRENT_TIMESTAMP"
        }
    }

    for table, columns in expected.items():
        if not c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            continue
        existing = {row['name'] for row in c.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, defn in columns.items():
            if col not in existing:
                try:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
                    db.commit()
                except Exception as e:
                    print(f"migrate: {table}.{col} — {e}")


init_db()
with app.app_context():
    migrate_db()


# ─── النسخ الاحتياطي ───

def _get_backup_dir(settings=None):
    if settings and settings['backup_dir']:
        return settings['backup_dir']
    return os.path.join(EXE_DIR, "backups")

def perform_backup(custom_dir=None):
    if USE_POSTGRES:
        return False, 'النسخ الاحتياطي للملفات غير متاح مع قاعدة البيانات السحابية'
    db = get_db()
    backup_dir = custom_dir or _get_backup_dir(
        db.execute("SELECT backup_dir FROM settings LIMIT 1").fetchone()
    )
    try:
        os.makedirs(backup_dir, exist_ok=True)
        test = os.path.join(backup_dir, ".write_test")
        with open(test, "w") as f:
            f.write("test")
        os.remove(test)
    except Exception as e:
        return False, f"المسار غير صالح أو غير قابل للكتابة: {e}"

    timestamp   = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup_file = os.path.join(backup_dir, f"backup_{timestamp}.db")
    try:
        shutil.copy2(DATABASE, backup_file)
        db.execute("UPDATE settings SET last_backup_time=? WHERE id=1", (timestamp,))
        db.commit()
        # الاحتفاظ بآخر 15 نسخة فقط
        files = sorted(
            [os.path.join(backup_dir, f) for f in os.listdir(backup_dir)
             if f.startswith("backup_") and f.endswith(".db")],
            key=os.path.getmtime
        )
        for old in files[:-15]:
            try:
                os.remove(old)
            except Exception:
                pass
        return True, backup_file
    except Exception as e:
        return False, str(e)

def auto_backup_on_startup():
    if USE_POSTGRES:
        return
    try:
        with app.app_context():
            db  = get_db()
            cfg = db.execute("SELECT auto_backup_enabled, last_backup_time, backup_dir FROM settings LIMIT 1").fetchone()
            if not cfg or not cfg['auto_backup_enabled']:
                return
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            if not cfg['last_backup_time'] or not cfg['last_backup_time'].startswith(today):
                ok, msg = perform_backup(cfg['backup_dir'])
                print(f"Auto backup: {'OK — ' + msg if ok else 'FAILED — ' + msg}")
    except Exception as e:
        print(f"Auto backup error: {e}")

auto_backup_on_startup()


# ─── دوال مساعدة ───

def get_settings():
    return get_db().execute("SELECT * FROM settings LIMIT 1").fetchone()

def find_logo():
    for ext in ['png', 'jpg', 'jpeg', 'svg', 'webp']:
        path = os.path.join(EXE_DIR, f'logo.{ext}')
        if os.path.exists(path):
            return path
    return None

@app.template_filter('to12h')
def to12h_filter(t):
    if not t:
        return '--:--'
    try:
        parts = t.split(':')
        h = int(parts[0])
        m = parts[1] if len(parts) > 1 else '00'
        if h == 0:
            return f'12:{m}'
        elif h <= 12:
            return f'{h}:{m}'
        else:
            return f'{h-12}:{m}'
    except:
        return t

@app.route('/logo')
def clinic_logo():
    path = find_logo()
    if path:
        return send_from_directory(os.path.dirname(path), os.path.basename(path))
    return '', 204

@app.context_processor
def inject_globals():
    try:
        return dict(settings=get_settings(), datetime=datetime, logo_exists=find_logo() is not None)
    except Exception:
        return dict(settings=None, datetime=datetime, logo_exists=False)


# ─── ديكورات الصلاحيات ───

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('user_role') not in roles:
                flash('غير مصرح لك بالوصول لهذه الصفحة', 'danger')
                if session.get('user_role') == 'receptionist':
                    return redirect(url_for('reception'))
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator

def admin_required(f):
    return role_required('admin')(f)


# ═══════════════════════════════════════════════
#  المسارات
# ═══════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        db   = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        ).fetchone()
        is_valid, upgraded_hash = False, None
        if user:
            is_valid, upgraded_hash = verify_and_upgrade_password(user['password'], password)
        if is_valid:
            if upgraded_hash:
                db.execute("UPDATE users SET password=? WHERE id=?", (upgraded_hash, user['id']))
            db.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user['id'],))
            db.commit()
            session['user_id']   = user['id']
            session['user_name'] = user['full_name']
            session['user_role'] = user['role']
            return redirect(url_for('reception' if user['role'] == 'receptionist' else 'dashboard'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    if session.get('user_role') == 'receptionist':
        return redirect(url_for('reception'))
    return redirect(url_for('dashboard'))


# ── لوحة التحكم ──

@app.route('/dashboard')
@role_required('admin', 'doctor')
def dashboard():
    db          = get_db()
    today       = datetime.date.today().strftime('%Y-%m-%d')
    month_start = datetime.date.today().replace(day=1).strftime('%Y-%m-%d')

    patients_count  = db.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
    row             = db.execute(
        "SELECT COUNT(*), SUM(COALESCE(paid_amount, cost)) FROM visits WHERE visit_date=?", (today,)
    ).fetchone()
    today_visits    = row[0] or 0
    today_income    = row[1] or 0
    monthly_income  = db.execute(
        "SELECT SUM(COALESCE(paid_amount, 0)) FROM visits WHERE visit_date>=?", (month_start,)
    ).fetchone()[0] or 0
    total_visits_all = db.execute("SELECT COUNT(*) FROM visits").fetchone()[0]
    unpaid_row       = db.execute(
        "SELECT COUNT(*), SUM(COALESCE(remaining_amount, cost)) FROM visits WHERE payment_status='غير مدفوع' AND visit_date>=?",
        (month_start,)
    ).fetchone()
    unpaid_count     = unpaid_row[0] or 0
    unpaid_amount    = unpaid_row[1] or 0
    new_patients     = db.execute(
        "SELECT COUNT(*) FROM patients WHERE created_at>=?", (month_start,)
    ).fetchone()[0]
    recent_visits = db.execute("""
        SELECT p.name, v.cost, v.visit_date, v.diagnosis, v.payment_status, p.gender
        FROM visits v JOIN patients p ON v.patient_id=p.id
        ORDER BY v.id DESC LIMIT 5
    """).fetchall()

    return render_template(
        'dashboard.html',
        patients_count   = patients_count,
        today_visits     = today_visits,
        today_income     = today_income,
        monthly_income   = monthly_income,
        total_visits_all = total_visits_all,
        unpaid_count     = unpaid_count,
        unpaid_amount    = unpaid_amount,
        recent_visits    = recent_visits,
        new_patients     = new_patients,
        user_name        = session.get('user_name', 'دكتور'),
        settings         = get_settings()
    )


# ── الاستقبال ──

@app.route('/reception')
@login_required
def reception():
    q         = request.args.get('q', '')
    sort_by   = request.args.get('sort', 'visit')
    page      = request.args.get('page', 1, type=int)
    per_page  = 5
    db        = get_db()

    # ── Base WHERE ──
    if q:
        where   = "WHERE name LIKE ? OR phone LIKE ? OR patient_code LIKE ?"
        params  = [f'%{q}%', f'%{q}%', f'%{q}%']
    else:
        where   = ""
        params  = []

    # ── Count total ──
    total = db.execute(f"SELECT COUNT(*) FROM patients {where}", params).fetchone()[0]

    # ── Sort & Paginate ──
    if sort_by == 'name':
        patients = db.execute(
            f"SELECT * FROM patients {where} ORDER BY name ASC LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page]
        ).fetchall()
    else:
        patients = db.execute(
            f"""SELECT p.*, COALESCE(lv.last_visit, '') AS last_visit_str
                FROM patients p
                LEFT JOIN (
                    SELECT patient_id, MAX(visit_date || 'T' || CAST(id AS TEXT)) AS last_visit
                    FROM visits GROUP BY patient_id
                ) lv ON lv.patient_id = p.id
                {where}
                ORDER BY lv.last_visit DESC NULLS LAST, p.id DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, (page - 1) * per_page]
        ).fetchall()

    patient_debts          = {}
    follow_up_counts       = {}
    package_session_counts = {}
    first_visit_types      = {}
    last_visits            = {}
    for p in patients:
        debt = db.execute(
            "SELECT COALESCE(SUM(remaining_amount), 0) FROM visits WHERE patient_id=? AND remaining_amount > 0", (p['id'],)
        ).fetchone()[0]
        first_unpaid = db.execute(
            "SELECT id FROM visits WHERE patient_id=? AND remaining_amount > 0 ORDER BY visit_date ASC, id ASC LIMIT 1", (p['id'],)
        ).fetchone()
        patient_debts[p['id']] = {
            'total_debt': debt,
            'first_unpaid_visit': first_unpaid['id'] if first_unpaid else None
        }
        fvt = db.execute(
            "SELECT visit_type FROM visits WHERE patient_id=? AND visit_type NOT IN ('متابعه','متابعة') ORDER BY visit_date ASC, id ASC LIMIT 1", (p['id'],)
        ).fetchone()
        first_visit_types[p['id']] = fvt['visit_type'] if fvt else ''
        pkg = db.execute(
            "SELECT id, session_count FROM visits WHERE patient_id=? AND visit_type='الباقات' ORDER BY id DESC LIMIT 1", (p['id'],)
        ).fetchone()
        if pkg:
            package_session_counts[p['id']] = pkg['session_count']
            follow_ups_since = db.execute(
                "SELECT COUNT(*) FROM visits WHERE patient_id=? AND visit_type='متابعه' AND id > ?", (p['id'], pkg['id'])
            ).fetchone()[0]
            follow_up_counts[p['id']] = follow_ups_since + 1
        else:
            rehab = db.execute(
                "SELECT id, session_count FROM visits WHERE patient_id=? AND visit_type='جلسه تأهيل' ORDER BY id DESC LIMIT 1", (p['id'],)
            ).fetchone()
            if rehab:
                package_session_counts[p['id']] = rehab['session_count']
            else:
                package_session_counts[p['id']] = 0
            follow_up_counts[p['id']] = db.execute(
                "SELECT COUNT(*) FROM visits WHERE patient_id=? AND visit_type='متابعه'", (p['id'],)
            ).fetchone()[0]
        if package_session_counts[p['id']] > 0 and follow_up_counts[p['id']] >= package_session_counts[p['id']]:
            package_session_counts[p['id']] = 0
            follow_up_counts[p['id']] = 0
        # آخر زيارة
        lv = db.execute(
            "SELECT visit_date, visit_type FROM visits WHERE patient_id=? ORDER BY visit_date DESC, id DESC LIMIT 1", (p['id'],)
        ).fetchone()
        last_visits[p['id']] = {'date': lv['visit_date'], 'type': lv['visit_type']} if lv else None

    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        'reception.html',
        patients=patients,
        patient_debts=patient_debts,
        follow_up_counts=follow_up_counts,
        package_session_counts=package_session_counts,
        first_visit_types=first_visit_types,
        last_visits=last_visits,
        page=page, total_pages=total_pages, sort_by=sort_by, q=q,
    )


# ── جدول المواعيد ──

@app.route('/appointments')
@role_required('admin', 'doctor', 'receptionist')
def appointments():
    db = get_db()
    
    # 1. تهيئة الأيام وتحديد اليوم المحدد مع حساب التواريخ للأسبوع الحالي
    ARABIC_WEEKDAYS = {
        0: 'الإثنين',
        1: 'الثلاثاء',
        2: 'الأربعاء',
        3: 'الخميس',
        4: 'الجمعه',
        5: 'السبت',
        6: 'الأحد'
    }
    
    def get_arabic_month_name(month_num):
        months = {
            1: 'يناير',
            2: 'فبراير',
            3: 'مارس',
            4: 'أبريل',
            5: 'مايو',
            6: 'يونيو',
            7: 'يوليو',
            8: 'أغسطس',
            9: 'سبتمبر',
            10: 'أكتوبر',
            11: 'نوفمبر',
            12: 'ديسمبر'
        }
        return months.get(month_num, '')
    
    today = datetime.date.today()
    today_weekday_idx = today.weekday()
    today_weekday_name = ARABIC_WEEKDAYS.get(today_weekday_idx, 'السبت')
    
    # حساب تاريخ يوم السبت في الأسبوع الحالي للبدء منه
    # Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    subtraction_map = {5: 0, 6: 1, 0: 2, 1: 3, 2: 4, 3: 5, 4: 6}
    days_to_subtract = subtraction_map.get(today_weekday_idx, 0)
    saturday_date = today - datetime.timedelta(days=days_to_subtract)
    
    weekdays_names = ['السبت', 'الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعه']
    weekdays_list = []
    for i, name in enumerate(weekdays_names):
        day_date = saturday_date + datetime.timedelta(days=i)
        weekdays_list.append({
            'name': name,
            'date_str': day_date.strftime('%Y-%m-%d'),
            'short_date': f"{day_date.day} {get_arabic_month_name(day_date.month)}"  # مثل 3 يونيو
        })
        
    selected_day = request.args.get('day', today_weekday_name)
    
    # تحديد تاريخ اليوم المختار
    selected_day_date = today.strftime('%Y-%m-%d')
    for day_info in weekdays_list:
        if day_info['name'] == selected_day:
            selected_day_date = day_info['date_str']
            break
            
    # 2. جلب جميع المرضى لتحديد أصحاب الباقات والاشتراكات النشطة
    patients = db.execute("SELECT id, name, phone, patient_code, chronic_diseases, pain_area FROM patients ORDER BY id DESC").fetchall()
    
    scheduled_patients = []
    other_active_patients = []
    
    for p in patients:
        active_items = []
        
        # 1. جلب آخر زيارة شراء باقة
        pkg = db.execute(
            "SELECT id, session_count, session_days, visit_date, session_time FROM visits WHERE patient_id=? AND visit_type='الباقات' ORDER BY id DESC LIMIT 1",
            (p['id'],)
        ).fetchone()
        
        if pkg:
            # حساب عدد جلسات المتابعة بعد تاريخ شراء الباقة
            follow_ups_since = db.execute(
                "SELECT COUNT(*) FROM visits WHERE patient_id=? AND visit_type='متابعه' AND id > ?",
                (p['id'], pkg['id'])
            ).fetchone()[0]
            
            total_sessions = pkg['session_count'] or 1
            completed_sessions = follow_ups_since + 1
            
            # الباقة نشطة طالما الجلسات المنجزة أقل من العدد الكلي للجلسات
            if completed_sessions < total_sessions:
                days_str = pkg['session_days'] or ''
                days_list = [d.strip() for d in days_str.split(',') if d.strip()]
                
                next_session_num = completed_sessions + 1
                progress_percent = int((completed_sessions / total_sessions) * 100)
                
                active_items.append({
                    'id': p['id'],
                    'name': p['name'],
                    'phone': p['phone'],
                    'patient_code': p['patient_code'],
                    'chronic_diseases': p['chronic_diseases'],
                    'pain_area': p['pain_area'],
                    'type': 'الباقات',
                    'total_sessions': total_sessions,
                    'completed_sessions': completed_sessions,
                    'progress_percent': progress_percent,
                    'session_days': days_list,
                    'package_date': pkg['visit_date'],
                    'next_session_num': next_session_num,
                    'session_time': pkg['session_time']
                })
                
        # 2. جلب آخر زيارة جلسة تأهيل
        rehab = db.execute(
            "SELECT id, session_days, visit_date, session_time, session_count FROM visits WHERE patient_id=? AND visit_type='جلسه تأهيل' ORDER BY id DESC LIMIT 1",
            (p['id'],)
        ).fetchone()
        
        if rehab:
            try:
                start_date = datetime.datetime.strptime(rehab['visit_date'], '%Y-%m-%d').date()
            except Exception:
                start_date = datetime.date.today()
                
            today_date = datetime.date.today()
            
            # عدد الجلسات الفعلية (أول زيارة تأهيل + كل زيارات المتابعه بعدها)
            actual_count = db.execute(
                "SELECT COUNT(*) FROM visits WHERE patient_id=? AND id >= ? AND (visit_type='جلسه تأهيل' OR visit_type='متابعه')",
                (p['id'], rehab['id'])
            ).fetchone()[0]
            
            total_sessions = rehab['session_count'] or 30
            completed_sessions = actual_count
            progress_percent = min(100, max(0, int((completed_sessions / total_sessions) * 100)))
            
            days_str = rehab['session_days'] or ''
            days_list = [d.strip() for d in days_str.split(',') if d.strip()]
            
            if completed_sessions < total_sessions:
                active_items.append({
                    'id': p['id'],
                    'name': p['name'],
                    'phone': p['phone'],
                    'patient_code': p['patient_code'],
                    'chronic_diseases': p['chronic_diseases'],
                    'pain_area': p['pain_area'],
                    'type': 'جلسه تأهيل',
                    'total_sessions': total_sessions,
                    'completed_sessions': completed_sessions,
                    'progress_percent': progress_percent,
                    'session_days': days_list,
                    'package_date': rehab['visit_date'],
                    'next_session_num': 'تأهيل',
                    'session_time': rehab['session_time']
                })
                
        # تصنيف العناصر النشطة وتصفيتها بناءً على تاريخ البداية مقارنة باليوم المختار
        for item in active_items:
            # يجب أن يكون تاريخ البداية (تاريخ الزيارة الأولى) أصغر من أو يساوي تاريخ اليوم المحدد
            if item['package_date'] <= selected_day_date:
                if selected_day in item['session_days']:
                    scheduled_patients.append(item)
                else:
                    other_active_patients.append(item)
                    
    # ترتيب الحالات حسب ميعاد الجلسة (الأصغر أولاً)
    scheduled_patients.sort(key=lambda x: x.get('session_time') or '99:99')

    # استبعاد المرضى المسجل لهم زيارة جلسة (حضور أو غياب) في اليوم المحدد
    patients_with_visit_today = set()
    for row in db.execute(
        "SELECT DISTINCT patient_id FROM visits WHERE visit_date=? AND visit_type IN ('متابعه','متابعة','غياب','جلسه تأهيل','الباقات','جلسه علاج طبيعي','جلسه علاج طبيعي خاص')", (selected_day_date,)
    ).fetchall():
        patients_with_visit_today.add(row['patient_id'])
    scheduled_patients = [p for p in scheduled_patients if p['id'] not in patients_with_visit_today]
    other_active_patients = [p for p in other_active_patients if p['id'] not in patients_with_visit_today]
    
    return render_template(
        'appointments.html',
        scheduled_patients=scheduled_patients,
        other_active_patients=other_active_patients,
        selected_day=selected_day,
        selected_day_date=selected_day_date,
        weekdays_list=weekdays_list,
        today_weekday_name=today_weekday_name,
    )


# ── تسجيل الغياب ──

@app.route('/mark_absence/<int:patient_id>', methods=['POST'])
@login_required
def mark_absence(patient_id):
    db = get_db()
    today = datetime.date.today().strftime('%Y-%m-%d')
    visit_date = request.form.get('visit_date', today)
    existing = db.execute(
        "SELECT id FROM visits WHERE patient_id=? AND visit_date=? AND visit_type='غياب'",
        (patient_id, visit_date)
    ).fetchone()
    if existing:
        flash('تم تسجيل غياب هذا المريض بالفعل', 'warning')
    else:
        db.execute(
            "INSERT INTO visits (patient_id, cost, paid_amount, remaining_amount, visit_date, visit_type, payment_status, payment_method, created_at) VALUES (?,0,0,0,?,'غياب','مدفوع','نقدي',?)",
            (patient_id, visit_date, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        db.commit()
        pname = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
        flash(f'تم تسجيل غياب {pname["name"] if pname else ""}', 'info')
    return redirect(url_for('appointments', day=request.form.get('day', '')))


# ── التقارير ──

@app.route('/reports')
@login_required
def reports():
    start_date     = request.args.get('start_date')
    end_date       = request.args.get('end_date')
    payment_filter = request.args.get('payment_status', '')
    method_filter  = request.args.get('payment_method', '')
    type_filter    = request.args.get('visit_type', '')
    db = get_db()

    query      = "SELECT v.*, p.name, p.phone, p.id AS patient_id FROM visits v JOIN patients p ON v.patient_id=p.id"
    params     = []
    conditions = []

    if start_date and end_date:
        conditions.append("v.visit_date BETWEEN ? AND ?")
        params.extend([start_date, end_date])
    if payment_filter == 'غير مدفوع':
        conditions.append("COALESCE(v.remaining_amount,0) > 0")
    elif payment_filter:
        conditions.append("v.payment_status=?")
        params.append(payment_filter)
    if method_filter:
        conditions.append("v.payment_method=?")
        params.append(method_filter)
    if type_filter:
        conditions.append("COALESCE(v.visit_type,'كشف')=?")
        params.append(type_filter)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    report_data = db.execute(query + " ORDER BY v.visit_date DESC", params).fetchall()

    visits_count = len(report_data)
    total_cost  = sum(r['cost'] or 0 for r in report_data)
    total_income = total_cost
    avg_cost     = total_cost / visits_count if visits_count else 0

    paid_amount = sum(
        (r['paid_amount'] if r['paid_amount'] is not None else (r['cost'] or 0))
        for r in report_data if r['payment_status'] in ('مدفوع', 'خصم من الباقة')
    ) + sum(
        (r['paid_amount'] or 0)
        for r in report_data if r['payment_status'] == 'غير مدفوع'
    )
    unpaid_amount       = sum(r['remaining_amount'] or 0 for r in report_data)
    paid_visits_count   = sum(1 for r in report_data if r['payment_status'] == 'مدفوع')
    unpaid_visits_count = sum(1 for r in report_data if r['payment_status'] == 'غير مدفوع')
    pkg_visits_count    = sum(1 for r in report_data if r['payment_status'] == 'خصم من الباقة')

    if start_date and end_date:
        new_patients_count = db.execute(
            "SELECT COUNT(*) FROM patients WHERE created_at BETWEEN ? AND ?",
            (start_date, end_date + ' 23:59:59')
        ).fetchone()[0]
    else:
        new_patients_count = db.execute("SELECT COUNT(*) FROM patients").fetchone()[0]

    # توزيع طرق الدفع
    mq = "SELECT COALESCE(v.payment_method,'نقدي') AS method, COUNT(*) AS count, SUM(v.cost) AS total FROM visits v JOIN patients p ON v.patient_id=p.id"
    if conditions:
        mq += " WHERE " + " AND ".join(conditions)
    mq += " GROUP BY method ORDER BY total DESC"
    payment_methods = db.execute(mq, params).fetchall()

    # توزيع أنواع الزيارات
    vq = "SELECT COALESCE(v.visit_type,'كشف') AS type, COUNT(*) AS count, SUM(v.cost) AS total FROM visits v JOIN patients p ON v.patient_id=p.id"
    if conditions:
        vq += " WHERE " + " AND ".join(conditions)
    vq += " GROUP BY type ORDER BY count DESC"
    visit_types = db.execute(vq, params).fetchall()

    # تفصيل يومي
    daily_breakdown = []
    if start_date and end_date:
        dq = """
            SELECT v.visit_date AS date, COUNT(*) AS count, SUM(v.cost) AS total,
                   SUM(CASE WHEN v.payment_status='غير مدفوع' THEN COALESCE(v.remaining_amount,0) ELSE 0 END) AS unpaid,
                   SUM(CASE WHEN v.payment_status='مدفوع' THEN COALESCE(v.paid_amount, v.cost, 0)
                            WHEN v.payment_status='خصم من الباقة' THEN COALESCE(v.cost,0)
                            ELSE COALESCE(v.paid_amount,0) END) AS paid
            FROM visits v JOIN patients p ON v.patient_id=p.id
            WHERE v.visit_date BETWEEN ? AND ?
        """
        dp = [start_date, end_date]
        if payment_filter and payment_filter != 'غير مدفوع':
            dq += " AND v.payment_status=?"
            dp.append(payment_filter)
        if method_filter:
            dq += " AND v.payment_method=?"
            dp.append(method_filter)
        dq += " GROUP BY v.visit_date ORDER BY v.visit_date DESC"
        daily_breakdown = db.execute(dq, dp).fetchall()

    # المدينون
    debt_q = """
        SELECT p.id AS patient_id, p.name, p.phone, p.gender,
               COUNT(v.id) AS visit_count,
               SUM(COALESCE(v.remaining_amount,0)) AS total_debt,
               SUM(COALESCE(v.cost,0)) AS total_cost,
               SUM(COALESCE(v.paid_amount,0)) AS total_paid,
               MAX(v.visit_date) AS last_visit
        FROM visits v JOIN patients p ON v.patient_id=p.id
        WHERE COALESCE(v.remaining_amount,0) > 0
    """
    dp2 = []
    if start_date and end_date:
        debt_q += " AND v.visit_date BETWEEN ? AND ?"
        dp2.extend([start_date, end_date])
    debt_q += " GROUP BY p.id, p.name, p.phone HAVING total_debt>0 ORDER BY total_debt DESC"
    debtors = db.execute(debt_q, dp2).fetchall()

    return render_template(
        'reports.html',
        report_data         = report_data,
        visits_count        = visits_count,
        total_cost          = total_cost,
        total_income        = total_income,
        paid_amount         = paid_amount,
        unpaid_amount       = unpaid_amount,
        unpaid_visits_count = unpaid_visits_count,
        new_patients_count  = new_patients_count,
        debtors             = debtors,
        settings            = get_settings()
    )


# ── تسوية الديون ──

@app.route('/settle_debt/<int:patient_id>', methods=['POST'])
@login_required
def settle_debt(patient_id):
    db             = get_db()
    settle_type    = request.form.get('settle_type', 'full')
    payment_method = request.form.get('payment_method', 'نقدي')
    patient        = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    name           = patient['name'] if patient else 'المريض'

    if settle_type == 'full':
        total_remaining = db.execute("SELECT COALESCE(SUM(remaining_amount), 0) FROM visits WHERE patient_id=? AND COALESCE(remaining_amount,0) > 0", (patient_id,)).fetchone()[0]
        db.execute("""
            UPDATE visits SET paid_amount=cost, remaining_amount=0, payment_status='مدفوع', payment_method=?
            WHERE patient_id=? AND COALESCE(remaining_amount,0) > 0
        """, (payment_method, patient_id))
        db.commit()
        log_action('تسوية', 'visits', patient_id, f'تسوية كل مديونيات {name} (إجمالي {total_remaining:,.0f} ج.م)')
        # تسجيل الإيراد في الخزنة
        if total_remaining > 0:
            now_local = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            db.execute(
                "INSERT INTO treasury (type, amount, reason, related_to, created_by, created_at) VALUES ('ايراد', ?, ?, ?, ?, ?)",
                (int(total_remaining), f'تسوية كل المديونيات - {name}', f'patient:{patient_id}', session.get('user_id'), now_local)
            )
            db.commit()
        flash(f'تم تسوية جميع مديونيات {name} بنجاح ✓', 'success')

    elif settle_type == 'partial':
        amount = float(request.form.get('partial_amount') or 0)
        if amount <= 0:
            flash('يرجى إدخال مبلغ صحيح أكبر من صفر', 'danger')
            return redirect(request.referrer or url_for('reports'))

        unpaid_visits = db.execute("""
            SELECT id, cost, COALESCE(paid_amount,0) AS paid_amount,
                   COALESCE(remaining_amount, cost) AS remaining_amount
            FROM visits WHERE patient_id=? AND COALESCE(remaining_amount,0)>0
            ORDER BY visit_date ASC, id ASC
        """, (patient_id,)).fetchall()

        left = amount
        for v in unpaid_visits:
            if left <= 0:
                break
            rem = v['remaining_amount']
            if left >= rem:
                new_paid, new_rem, new_status = v['paid_amount'] + rem, 0, 'مدفوع'
                left -= rem
            else:
                new_paid, new_rem, new_status = v['paid_amount'] + left, rem - left, 'غير مدفوع'
                left = 0
            db.execute(
                "UPDATE visits SET paid_amount=?, remaining_amount=?, payment_status=?, payment_method=? WHERE id=?",
                (new_paid, new_rem, new_status, payment_method, v['id'])
            )
        db.commit()
        log_action('تسوية', 'visits', patient_id, f'دفعة {amount:,.0f} ج.م من مديونيات {name}')
        # تسجيل الإيراد في الخزنة
        now_local = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            "INSERT INTO treasury (type, amount, reason, related_to, created_by, created_at) VALUES ('ايراد', ?, ?, ?, ?, ?)",
            (int(amount), f'دفعة من المديونيات - {name}', f'patient:{patient_id}', session.get('user_id'), now_local)
        )
        db.commit()
        flash(f'تم تسجيل دفعة {amount:,.0f} ج.م من مديونيات {name} بنجاح ✓', 'success')

    return redirect(request.referrer or url_for('reports'))


# ── إدارة المرضى ──

@app.route('/add_patient', methods=['POST'])
@login_required
def add_patient():
    db        = get_db()
    phone     = request.form.get('phone', '')
    phone2    = request.form.get('phone2', '')
    if not phone.isdigit() or len(phone) != 11:
        flash('رقم الهاتف يجب أن يكون 11 رقماً', 'danger')
        return redirect(url_for('reception'))
    if phone2 and (not phone2.isdigit() or len(phone2) != 11):
        flash('رقم الهاتف الآخر يجب أن يكون 11 رقماً', 'danger')
        return redirect(url_for('reception'))
    pain_area = ", ".join(request.form.getlist('pain_area')) or None
    c = db.execute("""
        INSERT INTO patients (name, phone, phone2, age, address, diagnosis, gender,
            chronic_diseases, work_nature, pain_area)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        request.form.get('name'), phone, phone2 or None,
        request.form.get('age'),
        request.form.get('address'), request.form.get('diagnosis'),
        request.form.get('gender', 'ذكر'),
        request.form.get('chronic_diseases'),
        request.form.get('work_nature'), pain_area
    ))
    new_id = c.lastrowid
    now = datetime.datetime.now()
    prefix = f"{now.year % 100:02d}-{now.month}-"
    existing = db.execute("SELECT patient_code FROM patients WHERE patient_code LIKE ?", (prefix + '%',)).fetchall()
    max_num = 0
    for r in existing:
        try:
            num = int(r['patient_code'].rsplit('-', 1)[-1])
            if num > max_num:
                max_num = num
        except:
            pass
    free_num = max_num + 1
    code = prefix + str(free_num)
    db.execute("UPDATE patients SET patient_code=? WHERE id=?", (code, new_id))
    db.commit()
    log_action('إضافة', 'patients', new_id, f'مريض: {request.form.get("name")} — كود: {code}')
    flash('تم إضافة المريض بنجاح', 'success')
    return redirect(url_for('reception'))

@app.route('/edit_patient/<int:id>', methods=['POST'])
@login_required
def edit_patient(id):
    db        = get_db()
    phone     = request.form.get('phone', '')
    phone2    = request.form.get('phone2', '')
    if not phone.isdigit() or len(phone) != 11:
        flash('رقم الهاتف يجب أن يكون 11 رقماً', 'danger')
        return redirect(url_for('reception'))
    if phone2 and (not phone2.isdigit() or len(phone2) != 11):
        flash('رقم الهاتف الآخر يجب أن يكون 11 رقماً', 'danger')
        return redirect(url_for('reception'))
    old       = db.execute("SELECT * FROM patients WHERE id=?", (id,)).fetchone()
    pain_area = ", ".join(request.form.getlist('pain_area')) or None
    db.execute("""
        UPDATE patients SET name=?, phone=?, phone2=?, age=?, address=?, diagnosis=?, gender=?,
            chronic_diseases=?,
            work_nature=?, pain_area=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
    """, (
        request.form.get('name'), phone, phone2 or None,
        request.form.get('age'),
        request.form.get('address'), request.form.get('diagnosis'),
        request.form.get('gender', 'ذكر'),
        request.form.get('chronic_diseases'),
        request.form.get('work_nature'), pain_area, id
    ))
    db.commit()
    if old:
        changes = []
        fields = {
            'name': 'الاسم', 'phone': 'الهاتف', 'phone2': 'هاتف آخر',
            'age': 'السن', 'address': 'العنوان', 'diagnosis': 'التشخيص',
            'gender': 'النوع', 'chronic_diseases': 'أمراض مزمنة',
            'work_nature': 'طبيعة العمل', 'pain_area': 'مناطق الألم'
        }
        for key, label in fields.items():
            old_val = old[key]
            new_val = request.form.get(key) if key != 'pain_area' else pain_area
            if old_val != new_val:
                changes.append(f'{label}: {old_val or "فارغ"} ← {new_val or "فارغ"}')
        detail = ' | '.join(changes) if changes else 'تعديل بيانات'
    else:
        detail = f'مريض: {request.form.get("name")}'
    log_action('تعديل', 'patients', id, detail)
    flash('تم تحديث بيانات المريض بنجاح', 'success')
    return redirect(url_for('reception'))

@app.route('/delete_patient/<int:id>')
@login_required
def delete_patient(id):
    db = get_db()
    patient = db.execute("SELECT name FROM patients WHERE id=?", (id,)).fetchone()
    name = patient['name'] if patient else 'غير معروف'
    db.execute("DELETE FROM patients WHERE id=?", (id,))
    db.commit()
    log_action('حذف', 'patients', id, f'مريض: {name}')
    flash('تم حذف المريض بنجاح', 'success')
    return redirect(url_for('reception'))

@app.route('/patient/<int:id>')
@login_required
def patient_profile(id):
    db      = get_db()
    patient = db.execute("SELECT * FROM patients WHERE id=?", (id,)).fetchone()
    if not patient:
        flash('المريض غير موجود', 'danger')
        return redirect(url_for('reception'))

    visits = db.execute(
        "SELECT * FROM visits WHERE patient_id=? ORDER BY visit_date DESC, id DESC", (id,)
    ).fetchall()
    # Build parent-child grouping for display (follow-ups nested under their parent)
    visits_asc = sorted(visits, key=lambda v: (v['visit_date'] or '', v['id'] or 0))
    visit_groups = []
    current_parent = None
    for v in visits_asc:
        vt = (v['visit_type'] or '').strip()
        if vt not in ('متابعه', 'متابعة'):
            p = dict(v)
            p['children'] = []
            visit_groups.append(p)
            current_parent = p
        elif current_parent is not None:
            current_parent['children'].append(dict(v))
        else:
            p = dict(v)
            p['children'] = []
            visit_groups.append(p)
            current_parent = p
    visit_groups.reverse()
    prescriptions = db.execute("""
        SELECT pr.*, v.visit_date FROM prescriptions pr
        JOIN visits v ON pr.visit_id=v.id WHERE pr.patient_id=? ORDER BY v.visit_date DESC
    """, (id,)).fetchall()
    # Group prescriptions and lab_tests by visit_id to avoid Jinja2 scoping issues
    prescriptions_by_visit = {}
    for pr in prescriptions:
        prescriptions_by_visit.setdefault(pr['visit_id'], []).append(dict(pr))
    lab_tests = db.execute("""
        SELECT lt.*, v.visit_date FROM lab_tests lt
        JOIN visits v ON lt.visit_id=v.id WHERE lt.patient_id=? ORDER BY v.visit_date DESC
    """, (id,)).fetchall()
    lab_tests_by_visit = {}
    for lt in lab_tests:
        lab_tests_by_visit.setdefault(lt['visit_id'], []).append(dict(lt))

    pain_assessments = db.execute(
        "SELECT * FROM pain_assessments WHERE patient_id=? ORDER BY assessed_at DESC", (id,)
    ).fetchall()
    treatment_plans = db.execute(
        "SELECT * FROM treatment_plans WHERE patient_id=? ORDER BY created_at DESC", (id,)
    ).fetchall()

    first_visit_type_row = db.execute(
        "SELECT visit_type FROM visits WHERE patient_id=? AND visit_type NOT IN ('متابعه','متابعة') ORDER BY visit_date ASC, id ASC LIMIT 1", (id,)
    ).fetchone()
    first_visit_type = first_visit_type_row['visit_type'] if first_visit_type_row else ''

    total_debt = db.execute(
        "SELECT COALESCE(SUM(remaining_amount), 0) FROM visits WHERE patient_id=? AND remaining_amount > 0", (id,)
    ).fetchone()[0]
    first_unpaid = db.execute(
        "SELECT id FROM visits WHERE patient_id=? AND remaining_amount > 0 ORDER BY visit_date ASC, id ASC LIMIT 1", (id,)
    ).fetchone()
    first_unpaid_visit = first_unpaid['id'] if first_unpaid else None

    pkg = db.execute(
        "SELECT id, session_count FROM visits WHERE patient_id=? AND visit_type='الباقات' ORDER BY id DESC LIMIT 1", (id,)
    ).fetchone()
    if pkg:
        package_session_count = pkg['session_count']
        follow_ups_since = db.execute(
            "SELECT COUNT(*) FROM visits WHERE patient_id=? AND visit_type='متابعه' AND id > ?", (id, pkg['id'])
        ).fetchone()[0]
        follow_up_count = follow_ups_since + 1
    else:
        rehab = db.execute(
            "SELECT id, session_count FROM visits WHERE patient_id=? AND visit_type='جلسه تأهيل' ORDER BY id DESC LIMIT 1", (id,)
        ).fetchone()
        if rehab:
            package_session_count = rehab['session_count']
        else:
            package_session_count = 0
        follow_up_count = db.execute(
            "SELECT COUNT(*) FROM visits WHERE patient_id=? AND visit_type='متابعه'", (id,)
        ).fetchone()[0]
    if package_session_count > 0 and follow_up_count >= package_session_count:
        package_session_count = 0
        follow_up_count = 0

    rehab_protocols = db.execute(
        "SELECT * FROM rehab_protocols ORDER BY name"
    ).fetchall()
    exercise_protocols = db.execute(
        "SELECT * FROM exercise_protocols ORDER BY name"
    ).fetchall()

    # ── حساب رقم الجلسة لكل زيارة (الأب + متابعاتها) ──
    session_numbers = {}
    for grp in visit_groups:
        if grp.get('children'):
            parent_type = (grp.get('visit_type') or '').strip()
            if parent_type in ('الباقات', 'جلسه تأهيل'):
                seq = 1
                session_numbers[grp['id']] = seq
                for child in grp['children']:
                    seq += 1
                    session_numbers[child['id']] = seq

    return render_template(
        'patient_profile.html',
        patient=patient, visits=visits, visit_groups=visit_groups,
        prescriptions_by_visit=prescriptions_by_visit, lab_tests_by_visit=lab_tests_by_visit,
        pain_assessments=pain_assessments,
        treatment_plans=treatment_plans,
        total_debt=total_debt, first_unpaid_visit=first_unpaid_visit,
        follow_up_count=follow_up_count,
        package_session_count=package_session_count,
        first_visit_type=first_visit_type,
        session_numbers=session_numbers,
        rehab_protocols=rehab_protocols,
        exercise_protocols=exercise_protocols,
        settings=settings
    )


# ── إدارة الزيارات ──

@app.route('/add_visit', methods=['POST'])
@login_required
def add_visit():
    db         = get_db()
    patient_id = request.form.get('patient_id')
    visit_date = request.form.get('visit_date') or datetime.date.today().strftime('%Y-%m-%d')
    vtype      = request.form.get('visit_type', 'جلسه علاج طبيعي')

    if vtype == 'متابعه':
        cost       = 0.0
        paid       = 0.0
        remaining  = 0.0
        status     = 'مدفوع'
    else:
        cost       = float(request.form.get('cost') or 0)
        paid       = min(float(request.form.get('paid_amount') or 0), cost)
        remaining  = cost - paid
        status     = request.form.get('payment_status', 'مدفوع')

    if status == 'خصم من الباقة':
        pkg = db.execute(
            "SELECT * FROM packages WHERE patient_id=? AND is_active=1 ORDER BY id ASC LIMIT 1",
            (patient_id,)
        ).fetchone()
        if not pkg:
            flash('لا توجد باقة نشطة لهذا المريض', 'danger')
            return redirect(url_for('patient_profile', id=patient_id))
        new_used  = pkg['used_sessions'] + 1
        is_active = 1 if new_used < pkg['total_sessions'] else 0
        db.execute("UPDATE packages SET used_sessions=?, is_active=? WHERE id=?",
                   (new_used, is_active, pkg['id']))
        paid      = cost
        remaining = 0
    else:
        status = 'مدفوع' if remaining <= 0 else 'غير مدفوع'

    raw_session_count = request.form.get('session_count') or '1'
    if 'جلسة' in raw_session_count:
        try:
            session_count = int(raw_session_count.split(' ')[-1])
        except:
            session_count = 1
    else:
        session_count = int(raw_session_count)
    vtype = request.form.get('visit_type', 'جلسه علاج طبيعي')
    session_time = request.form.get('session_time') if vtype in ('جلسه تأهيل', 'الباقات') else None
    c = db.execute("""
        INSERT INTO visits
        (patient_id, cost, visit_date, diagnosis, symptoms, examination, notes,
         payment_status, payment_method, visit_type, paid_amount, remaining_amount,
         session_count, session_days, session_time)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        patient_id, cost, visit_date,
        request.form.get('diagnosis'), request.form.get('symptoms'),
        request.form.get('examination'), request.form.get('notes'),
        status, request.form.get('payment_method', 'نقدي'),
        vtype, paid, remaining,
        session_count,
        ','.join(request.form.getlist('session_days')),
        session_time
    ))
    new_id = c.lastrowid
    db.commit()
    pname = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    log_action('إضافة', 'visits', new_id, f'زيارة ({visit_date}) بقيمة {cost:,.0f} ج.م — للمريض: {pname["name"] if pname else f"ID {patient_id}"}')
    flash('تم تسجيل الزيارة بنجاح', 'success')
    return redirect(url_for('daily_cases'))

@app.route('/edit_visit/<int:id>', methods=['POST'])
@login_required
def edit_visit(id):
    db        = get_db()
    old       = db.execute("SELECT * FROM visits WHERE id=?", (id,)).fetchone()
    vtype     = request.form.get('visit_type')

    if vtype == 'متابعه':
        cost      = 0.0
        paid      = 0.0
        remaining = 0.0
        status    = 'مدفوع'
    else:
        cost      = float(request.form.get('cost') or 0)
        paid      = min(float(request.form.get('paid_amount') or 0), cost)
        remaining = cost - paid
        status    = 'مدفوع' if remaining <= 0 else 'غير مدفوع'

    raw_session_count = request.form.get('session_count') or '1'
    if 'جلسة' in raw_session_count:
        try:
            session_count = int(raw_session_count.split(' ')[-1])
        except:
            session_count = 1
    else:
        session_count = int(raw_session_count)
    session_time = request.form.get('session_time') if vtype in ('جلسه تأهيل', 'الباقات') else None
    db.execute("""
        UPDATE visits SET cost=?, visit_date=?, diagnosis=?, symptoms=?, notes=?,
        payment_status=?, payment_method=?, visit_type=?, paid_amount=?, remaining_amount=?,
        session_count=?, session_days=?, session_time=?
        WHERE id=?
    """, (
        cost, request.form.get('visit_date'), request.form.get('diagnosis'),
        request.form.get('symptoms'), request.form.get('notes'),
        status, request.form.get('payment_method'),
        vtype, paid, remaining,
        session_count,
        ','.join(request.form.getlist('session_days')),
        session_time,
        id
    ))
    db.commit()
    if old:
        changes = []
        vfields = {'cost': 'التكلفة', 'visit_date': 'التاريخ', 'notes': 'ملاحظات', 'payment_method': 'طريقة الدفع', 'visit_type': 'نوع الزيارة', 'session_count': 'عدد الجلسات', 'session_days': 'أيام الجلسة'}
        for key, label in vfields.items():
            ov = old[key]
            nv = request.form.get(key)
            if str(ov) != str(nv):
                changes.append(f'{label}: {ov or "فارغ"} ← {nv or "فارغ"}')
        if old['paid_amount'] != paid:
            changes.append(f'المدفوع: {old["paid_amount"]} ← {paid}')
        detail = ' | '.join(changes) if changes else 'تعديل زيارة'
    else:
        detail = f'زيارة ID {id}'
    log_action('تعديل', 'visits', id, detail)
    flash('تم تحديث الزيارة بنجاح', 'success')
    return redirect(url_for('patient_profile', id=request.form.get('patient_id')))

@app.route('/settle_visit/<int:id>', methods=['POST'])
@login_required
def settle_visit(id):
    db = get_db()
    paid = float(request.form.get('paid_amount') or 0)
    method = request.form.get('payment_method', 'نقدي')
    visit = db.execute("SELECT * FROM visits WHERE id=?", (id,)).fetchone()
    if not visit:
        flash('الزيارة غير موجودة', 'danger')
        return redirect(url_for('reception'))
    remaining_before = (visit['cost'] or 0) - (visit['paid_amount'] or 0)
    paid = min(paid, remaining_before)
    new_paid = (visit['paid_amount'] or 0) + paid
    remaining = visit['cost'] - new_paid
    status = 'مدفوع' if remaining <= 0 else 'غير مدفوع'
    db.execute(
        "UPDATE visits SET paid_amount=?, remaining_amount=?, payment_status=?, payment_method=? WHERE id=?",
        (new_paid, remaining, status, method, id)
    )
    db.commit()
    patient_id = request.form.get('patient_id')
    pname = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    log_action('تسوية', 'visits', id, f'تسوية زيارة بقيمة {paid:,.0f} ج.م | إجمالي المدفوع: {new_paid:,.0f} | المتبقي: {remaining:,.0f} — للمريض: {pname["name"] if pname else f"ID {patient_id}"}')
    # تسجيل الإيراد في الخزنة
    if paid > 0:
        now_local = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            "INSERT INTO treasury (type, amount, reason, related_to, created_by, created_at) VALUES ('ايراد', ?, ?, ?, ?, ?)",
            (int(paid), f'تسوية زيارة - {pname["name"] if pname else f"مريض {patient_id}"}', f'visit:{id}', session.get('user_id'), now_local)
        )
        db.commit()
    flash('تم تسوية المديونية بنجاح', 'success')
    return redirect(url_for('patient_profile', id=patient_id))



@app.route('/delete_visit/<int:id>')
@login_required
def delete_visit(id):
    db  = get_db()
    row = db.execute("SELECT v.visit_date, v.cost, v.diagnosis, v.patient_id, p.name AS patient_name FROM visits v LEFT JOIN patients p ON v.patient_id=p.id WHERE v.id=?", (id,)).fetchone()
    db.execute("DELETE FROM visits WHERE id=?", (id,))
    db.commit()
    if row:
        detail = f'حذف زيارة ({row["visit_date"]}) | تشخيص: {row["diagnosis"] or "بدون"} | التكلفة: {row["cost"]:,.0f} ج.م — للمريض: {row["patient_name"]}'
    else:
        detail = f'حذف زيارة ID {id}'
    log_action('حذف', 'visits', id, detail)
    flash('تم حذف الزيارة بنجاح', 'success')
    referrer = request.referrer
    if referrer and '/daily_cases' in referrer:
        return redirect(referrer)
    return redirect(url_for('patient_profile', id=row['patient_id'] if row else 0))


# ── الحالات اليومية ──

@app.route('/daily_cases')
@login_required
def daily_cases():
    db      = get_db()
    today   = datetime.date.today().strftime('%Y-%m-%d')
    start   = request.args.get('start_date', today)
    end     = request.args.get('end_date', today)
    pfilter = request.args.get('payment_filter', '')

    query  = """
        SELECT v.*, p.name AS patient_name, p.phone, p.phone2, p.age, p.patient_code, p.gender,
               (SELECT COUNT(*) FROM visits v2 WHERE v2.patient_id=v.patient_id) AS visit_count
        FROM visits v JOIN patients p ON v.patient_id=p.id
        WHERE v.visit_date BETWEEN ? AND ?
    """
    params = [start, end]
    if pfilter:
        query += " AND v.payment_status=?"
        params.append(pfilter)
    query += " ORDER BY v.visit_date DESC, v.id DESC"

    raw    = db.execute(query, params).fetchall()
    visits = []
    for v in raw:
        d = dict(v)
        d['is_new_patient'] = (d['visit_count'] == 1)
        d.setdefault('visit_type', 'كشف')
        visits.append(d)

    total_income       = sum(v['paid_amount'] or 0 for v in visits)
    unpaid_count       = sum(1 for v in visits if v['payment_status'] == 'غير مدفوع')
    new_patients_today = sum(1 for v in visits if v['is_new_patient'])
    patients           = db.execute("SELECT id, name, phone, phone2, patient_code FROM patients ORDER BY name").fetchall()

    follow_up_counts = {}
    package_session_counts = {}
    for v in visits:
        pid = v['patient_id']
        if pid not in follow_up_counts or pid not in package_session_counts:
            pkg = db.execute(
                "SELECT id, session_count FROM visits WHERE patient_id=? AND visit_type='الباقات' ORDER BY id DESC LIMIT 1", (pid,)
            ).fetchone()
            if pkg:
                package_session_counts[pid] = pkg['session_count']
                follow_ups_since = db.execute(
                    "SELECT COUNT(*) FROM visits WHERE patient_id=? AND visit_type='متابعه' AND id > ?", (pid, pkg['id'])
                ).fetchone()[0]
                follow_up_counts[pid] = follow_ups_since + 1
            else:
                package_session_counts[pid] = 0
                follow_up_counts[pid] = db.execute(
                    "SELECT COUNT(*) FROM visits WHERE patient_id=? AND visit_type='متابعه'", (pid,)
                ).fetchone()[0]

    return render_template(
        'daily_cases.html',
        visits             = visits,
        start_date         = start,
        end_date           = end,
        payment_filter     = pfilter,
        patients           = patients,
        follow_up_counts   = follow_up_counts,
        package_session_counts = package_session_counts,
        settings           = get_settings()
    )


# ── الخزنة ──

@app.route('/treasury', methods=['GET', 'POST'])
@login_required
def treasury():
    db = get_db()
    today = datetime.date.today().strftime('%Y-%m-%d')
    date_filter = request.args.get('date', today)

    if request.method == 'POST':
        amount = int(request.form.get('amount') or 0)
        reason = request.form.get('reason', '').strip()
        if amount <= 0:
            flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
        elif not reason:
            flash('يرجى كتابة سبب الصرف', 'danger')
        else:
            now_local = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            db.execute(
                "INSERT INTO treasury (type, amount, reason, created_by, created_at) VALUES ('صرف', ?, ?, ?, ?)",
                (amount, reason, session.get('user_id'), now_local)
            )
            db.commit()
            log_action('إضافة', 'treasury', None, f'صرف {amount:,.0f} ج.م — سبب: {reason}')
            flash('تم تسجيل الصرف بنجاح', 'success')
        return redirect(url_for('treasury', date=date_filter))

    # إيرادات اليوم من الزيارات
    income_rows = db.execute(
        "SELECT v.id, v.cost, v.paid_amount, v.visit_date, v.payment_method, v.payment_status, p.name AS patient_name, p.patient_code "
        "FROM visits v JOIN patients p ON v.patient_id=p.id WHERE v.visit_date=?", (date_filter,)
    ).fetchall()
    # إيرادات الخزنة من التسويات
    treasury_income_rows = db.execute(
        "SELECT amount, reason, created_at FROM treasury WHERE type='ايراد' AND created_at LIKE ? ORDER BY id DESC",
        (f"{date_filter}%",)
    ).fetchall()
    today_income = sum(r['paid_amount'] or 0 for r in income_rows)
    # إيرادات الخزنة من التسويات والمدفوعات القديمة
    treasury_income = 0
    for r in treasury_income_rows:
        treasury_income += r['amount'] or 0
    today_income += treasury_income

    # توزيع الإيرادات حسب طريقة الدفع
    payment_breakdown = db.execute(
        "SELECT COALESCE(v.payment_method,'نقدي') AS method, SUM(COALESCE(v.paid_amount, 0)) AS total, COUNT(*) AS count "
        "FROM visits v JOIN patients p ON v.patient_id=p.id WHERE v.visit_date=? GROUP BY method ORDER BY total DESC",
        (date_filter,)
    ).fetchall()

    # مصروفات اليوم
    expense_rows = db.execute(
        "SELECT * FROM treasury WHERE type='صرف' AND created_at LIKE ? ORDER BY id DESC",
        (f"{date_filter}%",)
    ).fetchall()
    today_expenses = sum(r['amount'] for r in expense_rows)

    # إيرادات ومصروفات الشهر للحساب الشهري
    month_prefix = date_filter[:7] # YYYY-MM
    
    # إيرادات الشهر
    month_income_rows = db.execute(
        "SELECT SUM(COALESCE(paid_amount, 0)) FROM visits WHERE visit_date LIKE ?",
        (f"{month_prefix}%",)
    ).fetchone()
    month_income = month_income_rows[0] or 0
    # إيرادات الخزنة الشهرية من التسويات
    month_treasury_income = db.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM treasury WHERE type='ايراد' AND created_at LIKE ?",
        (f"{month_prefix}%",)
    ).fetchone()[0]
    month_income += month_treasury_income
    
    # مصروفات الشهر
    month_expense_rows = db.execute(
        "SELECT SUM(amount) FROM treasury WHERE type='صرف' AND created_at LIKE ?",
        (f"{month_prefix}%",)
    ).fetchone()
    month_expenses = month_expense_rows[0] or 0
    
    month_net = month_income - month_expenses
    
    # اسم الشهر باللغة العربية
    try:
        month_num = int(date_filter.split('-')[1])
        year_num = date_filter.split('-')[0]
    except:
        month_num = datetime.date.today().month
        year_num = datetime.date.today().year
        
    months_ar = {
        1: 'يناير', 2: 'فبراير', 3: 'مارس', 4: 'أبريل',
        5: 'مايو', 6: 'يونيو', 7: 'يوليو', 8: 'أغسطس',
        9: 'سبتمبر', 10: 'أكتوبر', 11: 'نوفمبر', 12: 'ديسمبر'
    }
    month_name = f"{months_ar.get(month_num, '')} {year_num}"

    return render_template(
        'treasury.html',
        date_filter=date_filter,
        income_rows=income_rows,
        treasury_income_rows=treasury_income_rows,
        today_income=today_income,
        payment_breakdown=payment_breakdown,
        expense_rows=expense_rows,
        today_expenses=today_expenses,
        net_total=today_income - today_expenses,
        month_net=month_net,
        month_name=month_name,
        is_admin=(session.get('user_role') == 'admin'),
    )


@app.route('/edit_expense/<int:id>', methods=['POST'])
@login_required
def edit_expense(id):
    db = get_db()
    old = db.execute("SELECT * FROM treasury WHERE id=?", (id,)).fetchone()
    if not old:
        flash('مصروف غير موجود', 'danger')
        return redirect(url_for('treasury'))
    amount = int(request.form.get('amount') or 0)
    reason = request.form.get('reason', '').strip()
    if amount <= 0:
        flash('المبلغ يجب أن يكون أكبر من صفر', 'danger')
    elif not reason:
        flash('يرجى كتابة سبب الصرف', 'danger')
    else:
        db.execute("UPDATE treasury SET amount=?, reason=? WHERE id=?", (amount, reason, id))
        db.commit()
        log_action('تعديل', 'treasury', id, f'تعديل صرف: {old["amount"]} ← {amount} ج.م | سبب: {old["reason"]} ← {reason}')
        flash('تم تعديل المصروف بنجاح', 'success')
    return redirect(url_for('treasury', date=request.args.get('date', '')))


@app.route('/delete_expense/<int:id>')
@login_required
def delete_expense(id):
    db = get_db()
    row = db.execute("SELECT * FROM treasury WHERE id=?", (id,)).fetchone()
    if row:
        db.execute("DELETE FROM treasury WHERE id=?", (id,))
        db.commit()
        log_action('حذف', 'treasury', id, f'حذف صرف: {row["amount"]:,.0f} ج.م — سبب: {row["reason"]}')
        flash('تم حذف المصروف بنجاح', 'success')
    return redirect(url_for('treasury', date=request.args.get('date', '')))


# ── الروشتات ──

@app.route('/add_prescription', methods=['POST'])
@login_required
def add_prescription():
    db = get_db()
    patient_id = request.form.get('patient_id')
    visit_id = request.form.get('visit_id')
    patient_name = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    pname = patient_name['name'] if patient_name else f'ID {patient_id}'
    names = request.form.getlist('medication_name')
    if not names or not names[0].strip():
        flash('الرجاء إدخال اسم الدواء', 'danger')
        return redirect(url_for('patient_profile', id=patient_id))
    dosages = request.form.getlist('dosage')
    freqs = request.form.getlist('frequency')
    durs = request.form.getlist('duration')
    insts = request.form.getlist('instructions')
    count = 0
    for i, name in enumerate(names):
        name = name.strip()
        if not name:
            continue
        dosage = dosages[i] if i < len(dosages) else ''
        freq = freqs[i] if i < len(freqs) else ''
        dur = durs[i] if i < len(durs) else ''
        inst = insts[i] if i < len(insts) else ''
        c = db.execute("""
            INSERT INTO prescriptions
            (visit_id, patient_id, medication_name, dosage, frequency, duration, instructions, category)
            VALUES (?,?,?,?,?,?,?,?)
        """, (visit_id, patient_id, name, dosage, freq, dur, inst, 'دواء'))
        new_id = c.lastrowid
        detail = f'إضافة دواء "{name}" | جرعة: {dosage or "غير محدد"} | تكرار: {freq or "غير محدد"} | مدة: {dur or "غير محدد"} — للمريض: {pname}'
        log_action('إضافة', 'prescriptions', new_id, detail)
        count += 1
    db.commit()
    flash(f'تم إضافة {count} روشتة بنجاح', 'success')
    return redirect(url_for('patient_profile', id=patient_id))


@app.route('/edit_visit_prescriptions/<int:visit_id>', methods=['POST'])
@login_required
def edit_visit_prescriptions(visit_id):
    db = get_db()
    visit = db.execute("SELECT v.patient_id, p.name AS patient_name FROM visits v JOIN patients p ON v.patient_id=p.id WHERE v.id=?", (visit_id,)).fetchone()
    if not visit:
        flash('الزيارة غير موجودة', 'danger')
        return redirect(url_for('reception'))
    patient_id = visit['patient_id']
    names = request.form.getlist('medication_name')
    if not names or not names[0].strip():
        flash('الرجاء إدخال اسم الدواء على الأقل', 'danger')
        return redirect(url_for('patient_profile', id=patient_id))
    dosages = request.form.getlist('dosage')
    freqs = request.form.getlist('frequency')
    durs = request.form.getlist('duration')
    # Delete old prescriptions for this visit
    old_meds = db.execute("SELECT id, medication_name FROM prescriptions WHERE visit_id=?", (visit_id,)).fetchall()
    db.execute("DELETE FROM prescriptions WHERE visit_id=?", (visit_id,))
    # Insert new ones
    count = 0
    for i, name in enumerate(names):
        name = name.strip()
        if not name:
            continue
        dosage = dosages[i] if i < len(dosages) else ''
        freq = freqs[i] if i < len(freqs) else ''
        dur = durs[i] if i < len(durs) else ''
        c = db.execute("""
            INSERT INTO prescriptions
            (visit_id, patient_id, medication_name, dosage, frequency, duration, instructions, category)
            VALUES (?,?,?,?,?,?,?,?)
        """, (visit_id, patient_id, name, dosage, freq, dur, '', 'دواء'))
        count += 1
    db.commit()
    detail = f'تعديل الروشتة (زيارة {visit_id}): {len(old_meds)} أدوية قديمة ← {count} أدوية جديدة — للمريض: {visit["patient_name"]}'
    log_action('تعديل', 'prescriptions', visit_id, detail)
    flash(f'تم تعديل الروشتة بنجاح ({count} دواء)', 'success')
    return redirect(url_for('patient_profile', id=patient_id))


@app.route('/delete_visit_prescriptions/<int:visit_id>')
@login_required
def delete_visit_prescriptions(visit_id):
    db = get_db()
    visit = db.execute("SELECT v.patient_id, p.name AS patient_name FROM visits v JOIN patients p ON v.patient_id=p.id WHERE v.id=?", (visit_id,)).fetchone()
    if not visit:
        flash('الزيارة غير موجودة', 'danger')
        return redirect(url_for('reception'))
    meds = db.execute("SELECT medication_name, dosage, frequency, duration FROM prescriptions WHERE visit_id=?", (visit_id,)).fetchall()
    meds_list = ' | '.join([f'{m["medication_name"]} (جرعة: {m["dosage"] or "?"}, تكرار: {m["frequency"] or "?"}, مدة: {m["duration"] or "?"})' for m in meds]) if meds else '(فارغة)'
    db.execute("DELETE FROM prescriptions WHERE visit_id=?", (visit_id,))
    db.commit()
    detail = f'حذف الروشتة كاملة: {meds_list} — للمريض: {visit["patient_name"]}'
    log_action('حذف', 'prescriptions', visit_id, detail)
    flash('تم حذف الروشتة بالكامل', 'success')
    return redirect(url_for('patient_profile', id=visit['patient_id']))


# ── الباقات ──

@app.route('/add_package', methods=['POST'])
@login_required
def add_package():
    db         = get_db()
    patient_id = request.form.get('patient_id')
    c = db.execute("""
        INSERT INTO packages (patient_id, package_name, total_sessions, cost, purchase_date, notes)
        VALUES (?,?,?,?,?,?)
    """, (
        patient_id, request.form.get('package_name'),
        request.form.get('total_sessions'), request.form.get('cost'),
        request.form.get('purchase_date') or datetime.date.today().strftime('%Y-%m-%d'),
        request.form.get('notes')
    ))
    new_id = c.lastrowid
    db.commit()
    pname = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    pkg_name = request.form.get('package_name', '')
    sessions = request.form.get('total_sessions', '')
    cost_pkg = request.form.get('cost', '')
    log_action('إضافة', 'packages', new_id, f'إضافة باقة "{pkg_name}" | جلسات: {sessions} | التكلفة: {cost_pkg} ج.م — للمريض: {pname["name"] if pname else f"ID {patient_id}"}')
    flash('تم إضافة الباقة بنجاح', 'success')
    return redirect(url_for('patient_profile', id=patient_id))


# ── الفحوصات ──

@app.route('/add_lab_test', methods=['POST'])
@login_required
def add_lab_test():
    db = get_db()
    c = db.execute("""
        INSERT INTO lab_tests (visit_id, patient_id, test_name, normal_range, notes)
        VALUES (?,?,?,?,?)
    """, (
        request.form.get('visit_id'), request.form.get('patient_id'),
        request.form.get('test_name'), request.form.get('normal_range'),
        request.form.get('notes')
    ))
    new_id = c.lastrowid
    patient_id = request.form.get('patient_id')
    db.commit()
    pname = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    test_name = request.form.get('test_name', '')
    log_action('إضافة', 'lab_tests', new_id, f'إضافة فحص "{test_name}" — للمريض: {pname["name"] if pname else f"ID {patient_id}"}')
    flash('تم إضافة الفحص بنجاح', 'success')
    return redirect(url_for('patient_profile', id=patient_id))


# ── الإعدادات ──

@app.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    db = get_db()
    if request.method == 'POST':
        old = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
        db.execute("""
            UPDATE settings SET
            clinic_name=?, doctor_name=?, clinic_address=?, clinic_phone=?,
            clinic_email=?, currency=?, visit_cost_default=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=1
        """, (
            request.form.get('clinic_name'), request.form.get('doctor_name'),
            request.form.get('clinic_address'), request.form.get('clinic_phone'),
            request.form.get('clinic_email'), request.form.get('currency'),
            request.form.get('visit_cost_default')
        ))
        db.commit()
        if old:
            changes = []
            sfields = {'clinic_name': 'اسم العيادة', 'doctor_name': 'اسم الطبيب', 'clinic_address': 'العنوان', 'clinic_phone': 'الهاتف', 'clinic_email': 'البريد', 'currency': 'العملة', 'visit_cost_default': 'التكلفة الافتراضية'}
            for key, label in sfields.items():
                ov = old[key]
                nv = request.form.get(key)
                if str(ov) != str(nv):
                    changes.append(f'{label}: {ov or "فارغ"} ← {nv or "فارغ"}')
            detail = ' | '.join(changes) if changes else 'تحديث إعدادات النظام'
        else:
            detail = 'تحديث إعدادات النظام'
        log_action('تعديل', 'settings', 1, detail)
        flash('تم حفظ الإعدادات بنجاح', 'success')
        return redirect(url_for('settings'))

    cfg   = db.execute("SELECT * FROM settings LIMIT 1").fetchone()
    users = db.execute("SELECT * FROM users").fetchall()

    backup_dir   = _get_backup_dir(cfg)
    backups_list = []
    if not USE_POSTGRES and os.path.isdir(backup_dir):
        try:
            for f in os.listdir(backup_dir):
                if f.startswith("backup_") and f.endswith(".db"):
                    fp   = os.path.join(backup_dir, f)
                    stat = os.stat(fp)
                    kb   = stat.st_size / 1024
                    backups_list.append({
                        'filename': f,
                        'size': f"{kb:.1f} KB" if kb < 1024 else f"{kb/1024:.2f} MB",
                        'time': datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                    })
            backups_list.sort(key=lambda x: x['time'], reverse=True)
        except Exception:
            pass

    return render_template('settings.html', settings=cfg, users=users, backups=backups_list)

@app.route('/settings/backup/create')
@admin_required
def create_backup():
    ok, msg = perform_backup()
    flash(f'تم إنشاء النسخة الاحتياطية في: {msg}' if ok else f'فشل إنشاء النسخة: {msg}',
          'success' if ok else 'danger')
    return redirect(url_for('settings'))

@app.route('/settings/backup/save_config', methods=['POST'])
@admin_required
def save_backup_config():
    db                  = get_db()
    backup_dir          = request.form.get('backup_dir', '').strip()
    auto_backup_enabled = 1 if request.form.get('auto_backup_enabled') == '1' else 0

    if backup_dir:
        try:
            os.makedirs(backup_dir, exist_ok=True)
            test = os.path.join(backup_dir, ".write_test")
            with open(test, "w") as f:
                f.write("test")
            os.remove(test)
        except Exception as e:
            flash(f'المسار غير صالح أو غير قابل للكتابة: {e}', 'danger')
            return redirect(url_for('settings'))

    db.execute(
        "UPDATE settings SET backup_dir=?, auto_backup_enabled=? WHERE id=1",
        (backup_dir or None, auto_backup_enabled)
    )
    db.commit()
    log_action('تعديل', 'settings', 1, 'تحديث إعدادات النسخ الاحتياطي')
    flash('تم حفظ إعدادات النسخ الاحتياطي بنجاح', 'success')
    return redirect(url_for('settings'))

@app.route('/settings/backup/download/<filename>')
@admin_required
def download_backup(filename):
    if not filename.startswith("backup_") or not filename.endswith(".db") or ".." in filename:
        flash('اسم ملف غير صالح!', 'danger')
        return redirect(url_for('settings'))
    db  = get_db()
    cfg = db.execute("SELECT backup_dir FROM settings LIMIT 1").fetchone()
    return send_from_directory(_get_backup_dir(cfg), filename, as_attachment=True)

@app.route('/settings/backup/delete/<filename>')
@admin_required
def delete_backup(filename):
    if not filename.startswith("backup_") or not filename.endswith(".db") or ".." in filename:
        flash('اسم ملف غير صالح!', 'danger')
        return redirect(url_for('settings'))
    db   = get_db()
    cfg  = db.execute("SELECT backup_dir FROM settings LIMIT 1").fetchone()
    path = os.path.join(_get_backup_dir(cfg), filename)
    try:
        if os.path.exists(path):
            os.remove(path)
            flash('تم حذف النسخة الاحتياطية بنجاح', 'success')
        else:
            flash('الملف غير موجود', 'warning')
    except Exception as e:
        flash(f'خطأ أثناء الحذف: {e}', 'danger')
    return redirect(url_for('settings'))

@app.route('/settings/add_user', methods=['POST'])
@admin_required
def add_user():
    db        = get_db()
    full_name = request.form.get('full_name')
    username  = request.form.get('username')
    password  = request.form.get('password')
    role      = request.form.get('role', 'doctor')
    specialty = request.form.get('specialty') if role == 'doctor' else None
    phone     = request.form.get('phone')
    email     = request.form.get('email')

    if not username or not password or not full_name:
        flash('يرجى ملء الحقول المطلوبة', 'danger')
        return redirect(url_for('settings'))

    try:
        c = db.execute("""
            INSERT INTO users (username, password, full_name, role, specialty, phone, email, is_active)
            VALUES (?,?,?,?,?,?,?,1)
        """, (username, generate_password_hash(password), full_name, role, specialty, phone, email))
        db.commit()
        log_action('إضافة', 'users', c.lastrowid, f'مستخدم: {full_name} ({username})')
        flash('تم إضافة المستخدم بنجاح', 'success')
    except Exception as e:
        if 'unique' in str(e).lower() or 'UNIQUE' in str(e):
            flash('اسم المستخدم موجود بالفعل!', 'danger')
        else:
            flash(f'خطأ: {e}', 'danger')
    return redirect(url_for('settings'))

@app.route('/settings/edit_user/<int:id>', methods=['POST'])
@admin_required
def edit_user(id):
    db        = get_db()
    full_name = request.form.get('full_name')
    role      = request.form.get('role')
    specialty = request.form.get('specialty') if role == 'doctor' else None
    phone     = request.form.get('phone')
    email     = request.form.get('email')
    is_active = 1 if request.form.get('is_active') == '1' else 0
    password  = request.form.get('password')

    if id == session.get('user_id') and is_active == 0:
        flash('لا يمكنك إلغاء تفعيل حسابك الشخصي!', 'danger')
        return redirect(url_for('settings'))
    if not full_name or not role:
        flash('يرجى ملء الحقول المطلوبة', 'danger')
        return redirect(url_for('settings'))

    try:
        old = db.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone()
        if password:
            db.execute("""
                UPDATE users SET full_name=?, role=?, specialty=?, phone=?, email=?, is_active=?, password=?
                WHERE id=?
            """, (full_name, role, specialty, phone, email, is_active, generate_password_hash(password), id))
        else:
            db.execute("""
                UPDATE users SET full_name=?, role=?, specialty=?, phone=?, email=?, is_active=?
                WHERE id=?
            """, (full_name, role, specialty, phone, email, is_active, id))
        db.commit()
        if old:
            changes = []
            ufields = {'full_name': 'الاسم', 'role': 'الدور', 'specialty': 'التخصص', 'phone': 'الهاتف', 'email': 'البريد', 'is_active': 'نشط'}
            for key, label in ufields.items():
                ov = old[key]
                nv = locals()[key]
                if str(ov) != str(nv):
                    changes.append(f'{label}: {ov or "فارغ"} ← {nv or "فارغ"}')
            if password:
                changes.append('كلمة المرور: تم التغيير')
            detail = ' | '.join(changes) if changes else f'تحديث مستخدم {full_name}'
        else:
            detail = f'تحديث مستخدم {full_name}'
        log_action('تعديل', 'users', id, detail)
        if id == session.get('user_id'):
            session['user_name'] = full_name
            session['user_role'] = role
        flash('تم تحديث بيانات المستخدم بنجاح', 'success')
    except Exception as e:
        flash(f'خطأ: {e}', 'danger')
    return redirect(url_for('settings'))

@app.route('/settings/delete_user/<int:id>')
@admin_required
def delete_user(id):
    db = get_db()
    if id == session.get('user_id'):
        flash('لا يمكنك حذف حسابك الشخصي!', 'danger')
        return redirect(url_for('settings'))
    try:
        user = db.execute("SELECT full_name FROM users WHERE id=?", (id,)).fetchone()
        name = user['full_name'] if user else 'غير معروف'
        db.execute("DELETE FROM users WHERE id=?", (id,))
        db.commit()
        log_action('حذف', 'users', id, f'مستخدم: {name}')
        flash('تم حذف المستخدم بنجاح', 'success')
    except Exception as e:
        flash(f'خطأ: {e}', 'danger')
    return redirect(url_for('settings'))



# ── التصدير والطباعة ──

@app.route('/export/reports')
@login_required
def export_reports():
    start_date     = request.args.get('start_date')
    end_date       = request.args.get('end_date')
    payment_filter = request.args.get('payment_status', '')
    db = get_db()

    query, params, conditions = (
        "SELECT v.*, p.name, p.phone FROM visits v JOIN patients p ON v.patient_id=p.id",
        [], []
    )
    if start_date and end_date:
        conditions.append("v.visit_date BETWEEN ? AND ?")
        params.extend([start_date, end_date])
    if payment_filter:
        conditions.append("v.payment_status=?")
        params.append(payment_filter)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    rows = db.execute(query + " ORDER BY v.visit_date DESC", params).fetchall()

    si = io.StringIO()
    si.write('\ufeff')
    w  = csv.writer(si)
    w.writerow(['رقم الزيارة', 'تاريخ الزيارة', 'اسم المريض', 'الهاتف', 'التشخيص', 'التكلفة', 'طريقة الدفع', 'حالة الدفع'])
    for r in rows:
        w.writerow([r['id'], r['visit_date'], r['name'], r['phone'],
                    r['diagnosis'] or '---', r['cost'],
                    r['payment_method'] or 'نقدي', r['payment_status']])

    resp = make_response(si.getvalue())
    resp.headers['Content-Disposition'] = f'attachment; filename=report_{start_date or "all"}_to_{end_date or "all"}.csv'
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return resp

@app.route('/export/daily_cases')
@login_required
def export_daily_cases():
    db      = get_db()
    today   = datetime.date.today().strftime('%Y-%m-%d')
    start   = request.args.get('start_date', today)
    end     = request.args.get('end_date', today)
    pfilter = request.args.get('payment_filter', '')

    query  = """
        SELECT v.*, p.name AS patient_name, p.phone, p.age, p.patient_code,
               (SELECT COUNT(*) FROM visits v2 WHERE v2.patient_id=v.patient_id) AS visit_count
        FROM visits v JOIN patients p ON v.patient_id=p.id
        WHERE v.visit_date BETWEEN ? AND ?
    """
    params = [start, end]
    if pfilter:
        query += " AND v.payment_status=?"
        params.append(pfilter)
    rows = db.execute(query + " ORDER BY v.visit_date DESC, v.id DESC", params).fetchall()

    si = io.StringIO()
    si.write('\ufeff')
    w  = csv.writer(si)
    w.writerow(['مسلسل', 'كود المريض', 'تاريخ الزيارة', 'اسم المريض', 'الهاتف', 'السن',
                'نوع الزيارة', 'نوع المريض', 'حالة الدفع', 'طريقة الدفع', 'التكلفة', 'التشخيص', 'الأعراض'])
    for i, r in enumerate(rows, 1):
        w.writerow([
            i, r['patient_code'] or '---', r['visit_date'], r['patient_name'], r['phone'],
            f"{r['age']} سنة" if r['age'] else '---',
            r['visit_type'] or 'كشف',
            'جديد' if r['visit_count'] == 1 else 'متابع',
            r['payment_status'], r['payment_method'] or 'نقدي',
            r['cost'] or 0, r['diagnosis'] or '---', r['symptoms'] or '---'
        ])

    resp = make_response(si.getvalue())
    resp.headers['Content-Disposition'] = f'attachment; filename=daily_cases_{start}_to_{end}.csv'
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    return resp

# ── العلاج الطبيعي: تقييم الألم ──

@app.route('/add_pain_assessment', methods=['POST'])
@login_required
def add_pain_assessment():
    db = get_db()
    c = db.execute("""
        INSERT INTO pain_assessments (visit_id, patient_id, pain_score, pain_location, pain_type,
                                      aggravating_factors, relieving_factors)
        VALUES (?,?,?,?,?,?,?)
    """, (
        request.form.get('visit_id'), request.form.get('patient_id'),
        request.form.get('pain_score'), request.form.get('pain_location'),
        request.form.get('pain_type'), request.form.get('aggravating_factors'),
        request.form.get('relieving_factors')
    ))
    new_id = c.lastrowid
    patient_id = request.form.get('patient_id')
    db.commit()
    pname = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    pain_score = request.form.get('pain_score', '')
    log_action('إضافة', 'pain_assessments', new_id, f'تقييم ألم (شدة {pain_score}/10) — للمريض: {pname["name"] if pname else f"ID {patient_id}"}')
    flash('تم تسجيل تقييم الألم', 'success')
    return redirect(url_for('patient_profile', id=patient_id))


# ── العلاج الطبيعي: مكتبة التمارين ──

@app.route('/add_exercise_protocol', methods=['POST'])
@login_required
def add_exercise_protocol():
    db = get_db()
    c = db.execute("""
        INSERT INTO exercise_protocols (name, description, targeted_muscles, difficulty, instructions, precautions)
        VALUES (?,?,?,?,?,?)
    """, (
        request.form.get('name'), request.form.get('description'),
        request.form.get('targeted_muscles'), request.form.get('difficulty', 'متوسط'),
        request.form.get('instructions'), request.form.get('precautions')
    ))
    new_id = c.lastrowid
    db.commit()
    log_action('إضافة', 'exercise_protocols', new_id, f'تمرين: {request.form.get("name")}')
    flash('تم إضافة التمرين للمكتبة', 'success')
    return redirect(request.referrer or url_for('reception'))

@app.route('/edit_exercise_protocol/<int:id>', methods=['POST'])
@login_required
def edit_exercise_protocol(id):
    db  = get_db()
    old = db.execute("SELECT * FROM exercise_protocols WHERE id=?", (id,)).fetchone()
    db.execute("""
        UPDATE exercise_protocols SET name=?, description=?, targeted_muscles=?, difficulty=?, instructions=?, precautions=?
        WHERE id=?
    """, (
        request.form.get('name'), request.form.get('description'),
        request.form.get('targeted_muscles'), request.form.get('difficulty'),
        request.form.get('instructions'), request.form.get('precautions'), id
    ))
    db.commit()
    if old:
        changes = []
        efields = {'name': 'الاسم', 'description': 'الوصف', 'targeted_muscles': 'العضلات', 'difficulty': 'الصعوبة', 'instructions': 'التعليمات', 'precautions': 'التحذيرات'}
        for key, label in efields.items():
            ov = old[key]
            nv = request.form.get(key)
            if str(ov) != str(nv):
                changes.append(f'{label}: {ov or "فارغ"} ← {nv or "فارغ"}')
        detail = ' | '.join(changes) if changes else f'تحديث تمرين {old["name"]}'
    else:
        detail = f'تحديث تمرين ID {id}'
    log_action('تعديل', 'exercise_protocols', id, detail)
    flash('تم تحديث التمرين', 'success')
    return redirect(request.referrer or url_for('reception'))

@app.route('/delete_exercise_protocol/<int:id>')
@login_required
def delete_exercise_protocol(id):
    db = get_db()
    db.execute("DELETE FROM exercise_protocols WHERE id=?", (id,))
    db.commit()
    log_action('حذف', 'exercise_protocols', id, f'تمرين ID {id}')
    flash('تم حذف التمرين', 'success')
    return redirect(request.referrer or url_for('reception'))


# ── العلاج الطبيعي: وصف التمارين للمريض ──

@app.route('/prescribe_exercise', methods=['POST'])
@login_required
def prescribe_exercise():
    db = get_db()
    c = db.execute("""
        INSERT INTO exercise_prescriptions (patient_id, visit_id, protocol_id, custom_name,
                                            sets, reps, frequency_per_week, duration_weeks, instructions, status)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        request.form.get('patient_id'), request.form.get('visit_id'),
        request.form.get('protocol_id'), request.form.get('custom_name'),
        request.form.get('sets'), request.form.get('reps'),
        request.form.get('frequency_per_week'), request.form.get('duration_weeks'),
        request.form.get('instructions'), 'نشط'
    ))
    new_id = c.lastrowid
    patient_id = request.form.get('patient_id')
    db.commit()
    pname = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    proto_id = request.form.get('protocol_id')
    ex_name = request.form.get('custom_name') or ''
    if not ex_name and proto_id:
        proto = db.execute("SELECT name FROM exercise_protocols WHERE id=?", (proto_id,)).fetchone()
        ex_name = proto['name'] if proto else ''
    sets = request.form.get('sets', '')
    reps = request.form.get('reps', '')
    freq = request.form.get('frequency_per_week', '')
    dur_w = request.form.get('duration_weeks', '')
    ex_detail = f'وصف تمرين "{ex_name}" | {sets}×{reps} | {freq} مرات/أسبوع | {dur_w} أسابيع'
    ex_detail += f' — للمريض: {pname["name"] if pname else f"ID {patient_id}"}'
    log_action('إضافة', 'exercise_prescriptions', new_id, ex_detail)
    flash('تم وصف التمرين للمريض', 'success')
    return redirect(url_for('patient_profile', id=patient_id))

@app.route('/delete_exercise_prescription/<int:id>')
@login_required
def delete_exercise_prescription(id):
    db = get_db()
    row = db.execute("SELECT ep.*, p.name AS patient_name, epr.name AS proto_name FROM exercise_prescriptions ep LEFT JOIN patients p ON ep.patient_id=p.id LEFT JOIN exercise_protocols epr ON ep.protocol_id=epr.id WHERE ep.id=?", (id,)).fetchone()
    if row:
        db.execute("DELETE FROM exercise_prescriptions WHERE id=?", (id,))
        db.commit()
        ex_name = row['custom_name'] or row['proto_name'] or 'تمرين'
        ex_detail = f'حذف "{ex_name}" | {row["sets"] or "?"}×{row["reps"] or "?"} | {row["frequency_per_week"] or "?"} مرات/أسبوع | {row["duration_weeks"] or "?"} أسابيع'
        ex_detail += f' — للمريض: {row["patient_name"]}'
        log_action('حذف', 'exercise_prescriptions', id, ex_detail)
    return redirect(url_for('patient_profile', id=row['patient_id']))

@app.route('/toggle_exercise_status/<int:id>')
@login_required
def toggle_exercise_status(id):
    db = get_db()
    row = db.execute("SELECT ep.id, ep.status, ep.patient_id, ep.custom_name, COALESCE(epr.name, '') AS proto_name FROM exercise_prescriptions ep LEFT JOIN exercise_protocols epr ON ep.protocol_id=epr.id WHERE ep.id=?", (id,)).fetchone()
    if row:
        ex_name = row['custom_name'] or row['proto_name'] or 'تمرين'
        new_status = 'منتهي' if row['status'] == 'نشط' else 'نشط'
        db.execute("UPDATE exercise_prescriptions SET status=? WHERE id=?", (new_status, id))
        db.commit()
        log_action('تعديل', 'exercise_prescriptions', id, f'تغيير حالة "{ex_name}" إلى {new_status}')
    return redirect(url_for('patient_profile', id=row['patient_id']))


# ── العلاج الطبيعي: تسجيل الجلسة العلاجية ──

@app.route('/add_pt_session', methods=['POST'])
@login_required
def add_pt_session():
    db = get_db()
    c = db.execute("""
        INSERT INTO pt_sessions (visit_id, patient_id, treatment_type, treatment_area,
                                 modalities_used, manual_therapy, therapeutic_exercise,
                                 patient_response, pain_before, pain_after, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        request.form.get('visit_id'), request.form.get('patient_id'),
        request.form.get('treatment_type'), request.form.get('treatment_area'),
        ', '.join(request.form.getlist('modalities_used')) if request.form.getlist('modalities_used') else '', request.form.get('manual_therapy'),
        request.form.get('therapeutic_exercise'), request.form.get('patient_response'),
        request.form.get('pain_before'), request.form.get('pain_after'),
        request.form.get('notes')
    ))
    new_id = c.lastrowid
    patient_id = request.form.get('patient_id')
    db.commit()
    pname = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    tx_type = request.form.get('treatment_type', '')
    area = request.form.get('treatment_area', '')
    pain_before = request.form.get('pain_before', '')
    pain_after = request.form.get('pain_after', '')
    modalities = ', '.join(request.form.getlist('modalities_used')) if request.form.getlist('modalities_used') else ''
    detail_parts = [f'نوع: {tx_type}']
    if area: detail_parts.append(f'منطقة: {area}')
    if pain_before or pain_after: detail_parts.append(f'ألم: {pain_before or "?"}←{pain_after or "?"}')
    if modalities: detail_parts.append(f'وسائل: {modalities}')
    detail_parts.append(f'للمريض: {pname["name"] if pname else f"ID {patient_id}"}')
    log_action('إضافة', 'pt_sessions', new_id, ' | '.join(detail_parts))
    flash('تم تسجيل جلسة العلاج الطبيعي', 'success')
    return redirect(url_for('patient_profile', id=patient_id))


# ── خطط العلاج ──

@app.route('/add_treatment_plan', methods=['POST'])
@login_required
def add_treatment_plan():
    db = get_db()
    c = db.execute("""
        INSERT INTO treatment_plans (patient_id, plan_name, goals, recommended_sessions,
                                     sessions_per_week, start_date, end_date, notes)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        request.form.get('patient_id'), request.form.get('plan_name'),
        request.form.get('goals'), request.form.get('recommended_sessions'),
        request.form.get('sessions_per_week'), request.form.get('start_date'),
        request.form.get('end_date'), request.form.get('notes')
    ))
    new_id = c.lastrowid
    patient_id = request.form.get('patient_id')
    db.commit()
    pname = db.execute("SELECT name FROM patients WHERE id=?", (patient_id,)).fetchone()
    plan_name = request.form.get('plan_name', '')
    log_action('إضافة', 'treatment_plans', new_id, f'إضافة خطة "{plan_name}" — للمريض: {pname["name"] if pname else f"ID {patient_id}"}')
    flash('تم إضافة خطة العلاج', 'success')
    return redirect(url_for('patient_profile', id=patient_id))

@app.route('/update_treatment_plan/<int:id>', methods=['POST'])
@login_required
def update_treatment_plan(id):
    db  = get_db()
    old = db.execute("SELECT * FROM treatment_plans WHERE id=?", (id,)).fetchone()
    db.execute("""
        UPDATE treatment_plans SET plan_name=?, goals=?, recommended_sessions=?,
                                   sessions_per_week=?, start_date=?, end_date=?, status=?, notes=?
        WHERE id=?
    """, (
        request.form.get('plan_name'), request.form.get('goals'),
        request.form.get('recommended_sessions'), request.form.get('sessions_per_week'),
        request.form.get('start_date'), request.form.get('end_date'),
        request.form.get('status', 'نشط'), request.form.get('notes'), id
    ))
    db.commit()
    if old:
        changes = []
        tfields = {'plan_name': 'اسم الخطة', 'goals': 'الأهداف', 'recommended_sessions': 'الجلسات', 'sessions_per_week': 'جلسات/أسبوع', 'start_date': 'تاريخ البداية', 'end_date': 'تاريخ النهاية', 'status': 'الحالة', 'notes': 'ملاحظات'}
        for key, label in tfields.items():
            ov = old[key]
            nv = request.form.get(key)
            if str(ov) != str(nv):
                changes.append(f'{label}: {ov or "فارغ"} ← {nv or "فارغ"}')
        detail = ' | '.join(changes) if changes else f'تحديث خطة {old["plan_name"]}'
    else:
        detail = f'تحديث خطة علاج ID {id}'
    log_action('تعديل', 'treatment_plans', id, detail)
    flash('تم تحديث خطة العلاج', 'success')
    return redirect(url_for('patient_profile', id=request.form.get('patient_id')))

@app.route('/delete_treatment_plan/<int:id>')
@login_required
def delete_treatment_plan(id):
    db = get_db()
    row = db.execute("SELECT tp.plan_name, tp.patient_id, p.name AS patient_name FROM treatment_plans tp LEFT JOIN patients p ON tp.patient_id=p.id WHERE tp.id=?", (id,)).fetchone()
    if row:
        db.execute("DELETE FROM treatment_plans WHERE id=?", (id,))
        db.commit()
        log_action('حذف', 'treatment_plans', id, f'حذف خطة "{row["plan_name"]}" — للمريض: {row["patient_name"] or f"ID {row["patient_id"]}"}')
    return redirect(url_for('patient_profile', id=row['patient_id']))


# ── برامج التأهيل الجاهزة ──

@app.route('/add_rehab_protocol', methods=['POST'])
@login_required
def add_rehab_protocol():
    db = get_db()
    c = db.execute("""
        INSERT INTO rehab_protocols (name, target_condition, description, phases, duration_weeks, contraindications)
        VALUES (?,?,?,?,?,?)
    """, (
        request.form.get('name'), request.form.get('target_condition'),
        request.form.get('description'), request.form.get('phases'),
        request.form.get('duration_weeks'), request.form.get('contraindications')
    ))
    new_id = c.lastrowid
    db.commit()
    log_action('إضافة', 'rehab_protocols', new_id, f'بروتوكول تأهيل: {request.form.get("name")}')
    flash('تم إضافة بروتوكول التأهيل', 'success')
    return redirect(request.referrer or url_for('reception'))

@app.route('/delete_rehab_protocol/<int:id>')
@login_required
def delete_rehab_protocol(id):
    db = get_db()
    db.execute("DELETE FROM rehab_protocols WHERE id=?", (id,))
    db.commit()
    log_action('حذف', 'rehab_protocols', id, f'بروتوكول تأهيل ID {id}')
    flash('تم حذف بروتوكول التأهيل', 'success')
    return redirect(request.referrer or url_for('reception'))


# ── سجل التتبع ──

@app.route('/audit_log')
@admin_required
def audit_log():
    db = get_db()
    page     = request.args.get('page', 1, type=int)
    per_page = 50
    offset   = (page - 1) * per_page
    total    = db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    logs     = db.execute(
        "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (per_page, offset)
    ).fetchall()
    logs = [dict(log) for log in logs]
    for log in logs:
        d = (log.get('details') or '').strip()
        log['_patient'] = None
        log['_changes'] = d
        m = re.search(r'مريض:\s*(.*?)(?:\s*[—\-]|$)', d)
        if m:
            log['_patient'] = m.group(1).strip()
            changes = d.replace(m.group(0), '').strip()
            changes = re.sub(r'\s*[—\-]\s*ل*$', '', changes).strip()
            changes = re.sub(r'^\s*ل?\s*', '', changes).strip()
            log['_changes'] = changes or None
        else:
            m = re.search(r'للمريض:\s*(.*?)(?:\s*بقيمة|$)', d)
            if m:
                log['_patient'] = m.group(1).strip()
                changes = d.replace(m.group(0), '').strip()
                log['_changes'] = changes or None
            else:
                m = re.search(r'مديونيات\s*(.*?)$', d)
                if m:
                    log['_patient'] = m.group(1).strip()
                    log['_changes'] = 'تسوية كل المديونيات'
        if not log['_changes']:
            log['_changes'] = d
    pages = (total + per_page - 1) // per_page
    return render_template('audit_log.html', logs=logs, page=page, pages=pages, total=total)


# ─── استيراد البيانات ───

@app.route('/import_data', methods=['GET', 'POST'])
@admin_required
def import_data():
    if not USE_POSTGRES:
        flash('هذه الأداة متاحة فقط عند استخدام قاعدة بيانات سحابية', 'warning')
        return redirect(url_for('settings'))

    if request.method == 'POST':
        file = request.files.get('db_file')
        if not file or not file.filename.endswith('.db'):
            flash('يرجى رفع ملف .db صالح', 'danger')
            return redirect(url_for('import_data'))

        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        file.save(tmp.name)
        tmp.close()

        try:
            src = sqlite3.connect(tmp.name)
            src.row_factory = sqlite3.Row
            db = get_db()

            TABLES = [
                'users', 'patients', 'visits', 'packages', 'prescriptions',
                'lab_tests', 'medical_images', 'settings', 'pain_assessments',
                'exercise_protocols', 'exercise_prescriptions', 'pt_sessions',
                'treatment_plans', 'rehab_protocols', 'treasury', 'audit_log'
            ]

            imported = {}
            for table in TABLES:
                try:
                    rows = src.execute(f"SELECT * FROM {table}").fetchall()
                except Exception:
                    continue
                if not rows:
                    imported[table] = 0
                    continue

                cols = rows[0].keys()
                col_names = ','.join(cols)
                placeholders = ','.join(['%s'] * len(cols))

                count = 0
                for row in rows:
                    values = [row[c] for c in cols]
                    try:
                        db.execute(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", values)
                        count += 1
                    except Exception:
                        db.rollback()
                        continue
                db.commit()
                imported[table] = count

            src.close()
            os.unlink(tmp.name)

            total = sum(imported.values())
            flash(f'تم استيراد {total} سجل بنجاح!', 'success')
            return redirect(url_for('dashboard'))

        except Exception as e:
            os.unlink(tmp.name)
            flash(f'خطأ أثناء الاستيراد: {e}', 'danger')
            return redirect(url_for('import_data'))

    return '''
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.rtl.min.css" rel="stylesheet">
    <style>body{background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;min-height:100vh;font-family:sans-serif}
    .card{background:#16213e;border:1px solid #0f3460;border-radius:16px;padding:40px;max-width:450px;width:100%}
    .form-control{background:#0f3460;border:1px solid #e94560;color:#fff}
    .btn-import{background:#e94560;border:none;color:#fff;padding:12px 30px;border-radius:10px;font-size:18px;width:100%}
    .btn-import:hover{background:#c73e54}</style></head>
    <body>
    <div class="card text-center">
        <h3 style="color:#e94560">استيراد البيانات</h3>
        <p class="text-muted mt-3">ارفع ملف database.db من الكمبيوتر</p>
        <form method="POST" enctype="multipart/form-data" class="mt-4">
            <input type="file" name="db_file" accept=".db" class="form-control mb-3">
            <button type="submit" class="btn-import">استيراد</button>
        </form>
        <a href="/settings" class="text-muted mt-3 d-block">العودة للإعدادات</a>
    </div>
    </body></html>
    '''


@app.route('/_diag')
def _diag():
    info = {
        'USE_POSTGRES': USE_POSTGRES,
        'DATABASE_URL_set': bool(DATABASE_URL),
    }
    try:
        db = get_db()
        info['db_type'] = 'postgres' if USE_POSTGRES else 'sqlite'
        r = db.execute("SELECT COUNT(*) FROM patients").fetchone()
        info['patients'] = r[0]
        r = db.execute("SELECT COUNT(*) FROM visits").fetchone()
        info['visits'] = r[0]
        r = db.execute("SELECT COUNT(*) FROM users").fetchone()
        info['users'] = r[0]
    except Exception as e:
        info['error'] = str(e)
    import json
    return json.dumps(info, ensure_ascii=False)


# ─── تشغيل التطبيق ───

if __name__ == '__main__':

    def open_browser():
        webbrowser.open("http://127.0.0.1:3000/")

    is_frozen = getattr(sys, 'frozen', False)
    debug     = not is_frozen and (
        os.environ.get("FLASK_DEBUG") == "1" or os.environ.get("CLINIC_DEBUG") == "1"
    )

    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Timer(1.2, open_browser).start()

    app.run(host="0.0.0.0", port=3000, debug=debug)