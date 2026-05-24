CREATE TABLE research_session (
    id UUID PRIMARY KEY,
    topic TEXT NOT NULL,
    plan JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    status TEXT NOT NULL
);

CREATE TABLE evidence (
    id UUID PRIMARY KEY,
    research_id UUID REFERENCES research_session(id),
    sub_question_id TEXT NOT NULL,
    claim TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_title TEXT NOT NULL,
    source_pub_date DATE,
    extract_text TEXT NOT NULL,
    extract_offset_start INT DEFAULT 0,
    confidence FLOAT,
    extracted_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_claim_research ON evidence(research_id, claim_type);
CREATE INDEX idx_claim_text ON evidence USING gin(to_tsvector('english', claim));

CREATE TABLE evaluation_result (
    research_id UUID PRIMARY KEY REFERENCES research_session(id),
    task_success_rate FLOAT NOT NULL,
    citation_accuracy FLOAT NOT NULL,
    critic_catch_rate FLOAT NOT NULL,
    answer_relevance FLOAT NOT NULL,
    faithfulness FLOAT NOT NULL,
    latency_seconds FLOAT NOT NULL,
    cost_usd FLOAT NOT NULL,
    token_used INT NOT NULL,
    bad_case_categories JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

