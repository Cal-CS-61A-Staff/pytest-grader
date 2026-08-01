"""
Logging that tracks a student's progress through an assignment.
"""

import sqlite3
import hashlib
import os


class SQLLogger:
    """Logs progress through an assignment to a SQLite database."""

    def __init__(self, db: str, conf: dict[str, str]):
        self.db_path = db
        self.conf = conf
        self.current_session = None
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._setup_db()

    def _setup_db(self):
        """Set up the database tables."""
        # Files table to store file contents, deduplicated by hash
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                sha1_hash TEXT NOT NULL UNIQUE
            )
        ''')

        # Sessions table to track each pytest invocation
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Snapshot files table to track the contents of each included file
        # at the start of each session
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS snapshot_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                filename TEXT NOT NULL,
                sha1_hash TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        ''')

        # Test cases table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                name TEXT NOT NULL,
                passed BOOLEAN NOT NULL,
                response TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        ''')

        # Unlock attempts table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS unlock_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                name TEXT NOT NULL,
                guess TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                response TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        ''')

        self.conn.commit()

    def _execute_and_commit(self, query, params=()):
        """Execute a query and commit the transaction."""
        self.cursor.execute(query, params)
        self.conn.commit()

    def start_session(self, command: str):
        """Record the start of a pytest session and its invoking command."""
        self._execute_and_commit('INSERT INTO sessions (command) VALUES (?)', (command,))
        self.current_session = self.cursor.lastrowid

    def snapshot(self):
        """Store the assignment code used for this session."""
        for filename in self.conf.get('included_files', []):
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()

                sha1_hash = hashlib.sha1(content.encode('utf-8')).hexdigest()

                # Store the file content unless this hash is already recorded
                self.cursor.execute('SELECT id FROM files WHERE sha1_hash = ?', (sha1_hash,))
                if not self.cursor.fetchone():
                    self._execute_and_commit('''
                        INSERT INTO files (content, sha1_hash)
                        VALUES (?, ?)
                    ''', (content, sha1_hash))

                # Always record which files were part of this session
                self._execute_and_commit('''
                    INSERT INTO snapshot_files (session_id, filename, sha1_hash)
                    VALUES (?, ?, ?)
                ''', (self.current_session, filename, sha1_hash))

    def test_case(self, name, passed: bool, response: str | None = None):
        """Store the AI response and result of a test case."""
        self._execute_and_commit('''
            INSERT INTO test_cases (session_id, name, passed, response)
            VALUES (?, ?, ?, ?)
        ''', (self.current_session, name, passed, response))

    def unlock_attempt(self, name, output_number, guess, success: bool, response: str | None = None):
        """Store the AI response and result of an attempt to unlock a test case."""
        self._execute_and_commit('''
            INSERT INTO unlock_attempts (session_id, name, guess, success, response)
            VALUES (?, ?, ?, ?, ?)
        ''', (self.current_session, f"{name}[{output_number}]", guess, success, response))
