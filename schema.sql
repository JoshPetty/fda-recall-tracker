CREATE TABLE recalls (
    recall_id TEXT PRIMARY KEY,
    event_id TEXT,
    status TEXT,
    classification TEXT,
    product_type TEXT,
    recalling_firm TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    product_description TEXT,
    reason_for_recall TEXT,
    distribution_pattern TEXT,
    voluntary_mandated TEXT,
    recall_initiation_date DATE,
    report_date DATE,
    source_agency TEXT DEFAULT 'FDA',
    raw_payload JSONB,
    last_seen_at TIMESTAMP DEFAULT now()
);


CREATE TABLE poller_state (
    id INT PRIMARY KEY DEFAULT 1,
    last_polled_at TIMESTAMP,
    CHECK (id = 1)
);

INSERT INTO poller_state (id, last_polled_at) VALUES (1, NULL);