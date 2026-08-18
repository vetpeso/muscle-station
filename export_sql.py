import sqlite3
import os

SQLITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.db")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "import.sql")

TABLES = [
    'users', 'patients', 'visits', 'packages', 'prescriptions', 'lab_tests',
    'medical_images', 'settings', 'pain_assessments', 'exercise_protocols',
    'exercise_prescriptions', 'pt_sessions', 'treatment_plans', 'rehab_protocols',
    'treasury', 'audit_log'
]

def main():
    src = sqlite3.connect(SQLITE_PATH)
    src.row_factory = sqlite3.Row

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write("-- Muscle Station Data Import\n")
        f.write("-- Copy paste this into Railway PostgreSQL Query\n\n")

        for table in TABLES:
            try:
                rows = src.execute(f"SELECT * FROM {table}").fetchall()
            except Exception as e:
                f.write(f"-- {table}: error {e}\n\n")
                continue

            if not rows:
                f.write(f"-- {table}: empty\n\n")
                continue

            cols = rows[0].keys()
            col_names = ', '.join(cols)

            f.write(f"-- {table}: {len(rows)} records\n")

            for row in rows:
                values = []
                for c in cols:
                    v = row[c]
                    if v is None:
                        values.append('NULL')
                    elif isinstance(v, (int, float)):
                        values.append(str(v))
                    else:
                        escaped = str(v).replace("'", "''")
                        values.append(f"'{escaped}'")
                f.write(f"INSERT INTO {table} ({col_names}) VALUES ({', '.join(values)});\n")
            f.write("\n")

    src.close()
    print(f"Done! File saved: {OUTPUT_PATH}")
    print(f"Total size: {os.path.getsize(OUTPUT_PATH) / 1024:.1f} KB")

if __name__ == '__main__':
    main()
