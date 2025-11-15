-- Schema for ulog storage in SQLite database

-- Static definitions (from ELF)
CREATE TABLE log_defs (
  log_id     SMALLINT PRIMARY KEY,   -- e.g. 0 to 255
  file       TEXT,
  line       INTEGER,
  level      SMALLINT,
  message_template TEXT
);

CREATE TABLE var_defs (
  var_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  log_id     INTEGER REFERENCES log_defs(log_id),
  name       TEXT,   -- Given at runtime, e.g. "roll", "pitch"
  trait      TEXT,   -- e.g. bool, u8, f32
  formatter  TEXT,   -- Given at runtime when watching, e.g. "%0.2f"
  position   INTEGER -- Order in the log message
);

-- Runtime logs
CREATE TABLE logs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         REAL,
  log_id     INTEGER REFERENCES log_defs(log_id),
  raw_payload BLOB
);

CREATE TABLE var_values (
  log_row    INTEGER REFERENCES logs(id),
  var_def_id INTEGER REFERENCES var_defs(var_id),
  value_blob BLOB,
  -- Optional: decoded columns for fast queries
  value_int  INTEGER,
  value_real REAL
);

-- Indexes for performance
CREATE INDEX idx_var_values_log_row ON var_values(log_row);
CREATE INDEX idx_var_values_var_def_id ON var_values(var_def_id);
CREATE INDEX idx_var_values_value_int ON var_values(value_int);
CREATE INDEX idx_var_values_value_real ON var_values(value_real);

CREATE INDEX idx_var_values_var_def_id_value_int ON var_values(var_def_id, value_int);
CREATE INDEX idx_var_values_var_def_id_value_real ON var_values(var_def_id, value_real);
CREATE INDEX idx_logs_ts ON logs(ts);
CREATE INDEX idx_logs_log_id ON logs(log_id);

CREATE INDEX idx_logs_log_id_ts ON logs(log_id, ts);
CREATE INDEX idx_logs_ts_log_id ON logs(ts, log_id);
CREATE INDEX idx_logs_log_id_ts_id ON logs(log_id, ts, id);
CREATE INDEX idx_logs_ts_log_id_id ON logs(ts, log_id, id);