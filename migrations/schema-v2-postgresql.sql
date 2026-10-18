-- Generated DDL reference for authoritative schema revision 2.

-- Apply migrations with: python -m mirage migrate

-- The runner records revisions 1 (initial tables) and 2 (retention-safe sequences).

-- Native gateway registry tables are intentionally separate.

CREATE TABLE audit_log (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	sequence INTEGER NOT NULL, 
	actor_id VARCHAR(200) NOT NULL, 
	action VARCHAR(100) NOT NULL, 
	object_id VARCHAR(200) NOT NULL, 
	details JSON NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	previous_digest VARCHAR(64) NOT NULL, 
	integrity_digest VARCHAR(64) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	UNIQUE (tenant_id, sequence)
);

CREATE TABLE idempotency (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	principal_id VARCHAR(200) NOT NULL, 
	route VARCHAR(300) NOT NULL, 
	key VARCHAR(200) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	response JSON NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	UNIQUE (tenant_id, principal_id, route, key)
);

CREATE TABLE imports (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	source VARCHAR(100) NOT NULL, 
	version VARCHAR(100) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	observations JSON NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (tenant_id, id)
);

CREATE TABLE policy_versions (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	version VARCHAR(100) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	document JSON NOT NULL, 
	created_by VARCHAR(200) NOT NULL, 
	reviewed_by VARCHAR(200), 
	tested BOOLEAN NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	UNIQUE (tenant_id, version)
);

CREATE TABLE principals (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	roles JSON NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	scopes JSON NOT NULL, 
	parent_id VARCHAR(200), 
	root_id VARCHAR(200) NOT NULL, 
	depth INTEGER NOT NULL, 
	expires_at VARCHAR(40) NOT NULL, 
	identity_epoch INTEGER NOT NULL, 
	owner VARCHAR(200) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id, parent_id) REFERENCES principals (tenant_id, id)
);

CREATE TABLE rate_limits (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	"window" INTEGER NOT NULL, 
	count INTEGER NOT NULL, 
	PRIMARY KEY (tenant_id, id)
);

CREATE TABLE runtime (
	tenant_id VARCHAR(200) NOT NULL, 
	active_policy_id VARCHAR(200) NOT NULL, 
	engagements_enabled BOOLEAN NOT NULL, 
	model_calls INTEGER NOT NULL, 
	model_tokens INTEGER NOT NULL, 
	PRIMARY KEY (tenant_id)
);

CREATE TABLE schema_versions (
	version SERIAL NOT NULL, 
	applied_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (version)
);

CREATE TABLE sequence_counters (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	value INTEGER NOT NULL, 
	PRIMARY KEY (tenant_id, id)
);

CREATE TABLE tenants (
	id VARCHAR(200) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE credentials (
	token_hash VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(200) NOT NULL, 
	principal_id VARCHAR(200) NOT NULL, 
	source VARCHAR(30), 
	expires_at VARCHAR(40) NOT NULL, 
	csrf VARCHAR(100), 
	kind VARCHAR(30) NOT NULL, 
	PRIMARY KEY (token_hash), 
	FOREIGN KEY(tenant_id, principal_id) REFERENCES principals (tenant_id, id)
);

CREATE TABLE sessions (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	principal_id VARCHAR(200) NOT NULL, 
	caller_class VARCHAR(30) NOT NULL, 
	route_mode VARCHAR(30) NOT NULL, 
	route_version INTEGER NOT NULL, 
	decoy_id VARCHAR(200), 
	origin VARCHAR(30) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	expires_at VARCHAR(40) NOT NULL, 
	history JSON NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id, principal_id) REFERENCES principals (tenant_id, id)
);

CREATE TABLE approvals (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	requester_id VARCHAR(200) NOT NULL, 
	principal_id VARCHAR(200) NOT NULL, 
	session_id VARCHAR(200) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	policy_version VARCHAR(100) NOT NULL, 
	invocation JSON NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	approver_id VARCHAR(200), 
	expires_at VARCHAR(40) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id, session_id) REFERENCES sessions (tenant_id, id)
);

CREATE TABLE decoys (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	session_id VARCHAR(200) NOT NULL, 
	template_id VARCHAR(100) NOT NULL, 
	template_version VARCHAR(50) NOT NULL, 
	state VARCHAR(30) NOT NULL, 
	synthetic_state JSON NOT NULL, 
	requests INTEGER NOT NULL, 
	model_tokens INTEGER NOT NULL, 
	expires_at VARCHAR(40) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	attestation JSON NOT NULL, 
	cleanup_state VARCHAR(30) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id, session_id) REFERENCES sessions (tenant_id, id), 
	UNIQUE (tenant_id, session_id)
);

CREATE TABLE events (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	sequence INTEGER NOT NULL, 
	session_id VARCHAR(200) NOT NULL, 
	source VARCHAR(30) NOT NULL, 
	event_type VARCHAR(50) NOT NULL, 
	outcome VARCHAR(30) NOT NULL, 
	received_at VARCHAR(40) NOT NULL, 
	occurred_at VARCHAR(40) NOT NULL, 
	body_digest VARCHAR(64) NOT NULL, 
	body JSON NOT NULL, 
	trusted BOOLEAN NOT NULL, 
	origin VARCHAR(30) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id, session_id) REFERENCES sessions (tenant_id, id), 
	UNIQUE (tenant_id, sequence)
);

CREATE INDEX events_correlation ON events (tenant_id, session_id, received_at);

CREATE TABLE executions (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	principal_id VARCHAR(200) NOT NULL, 
	session_id VARCHAR(200) NOT NULL, 
	idempotency_key VARCHAR(200) NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	state VARCHAR(30) NOT NULL, 
	decision JSON NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id, session_id) REFERENCES sessions (tenant_id, id), 
	UNIQUE (tenant_id, principal_id, session_id, idempotency_key)
);

CREATE TABLE incidents (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	number VARCHAR(30) NOT NULL, 
	session_id VARCHAR(200) NOT NULL, 
	principal_id VARCHAR(200) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	summary VARCHAR(2000) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	confidence VARCHAR(20) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	version INTEGER NOT NULL, 
	rules JSON NOT NULL, 
	source VARCHAR(30) NOT NULL, 
	origin VARCHAR(30) NOT NULL, 
	investigation JSON, 
	model_error VARCHAR(200), 
	model_calls INTEGER NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	updated_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id, session_id) REFERENCES sessions (tenant_id, id), 
	UNIQUE (tenant_id, session_id)
);

CREATE TABLE incident_events (
	tenant_id VARCHAR(200) NOT NULL, 
	incident_id VARCHAR(200) NOT NULL, 
	event_id VARCHAR(200) NOT NULL, 
	PRIMARY KEY (tenant_id, incident_id, event_id), 
	FOREIGN KEY(tenant_id, incident_id) REFERENCES incidents (tenant_id, id), 
	FOREIGN KEY(tenant_id, event_id) REFERENCES events (tenant_id, id)
);

CREATE TABLE notes (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	incident_id VARCHAR(200) NOT NULL, 
	actor_id VARCHAR(200) NOT NULL, 
	text VARCHAR(2000) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id, incident_id) REFERENCES incidents (tenant_id, id)
);

CREATE TABLE outbox (
	tenant_id VARCHAR(200) NOT NULL, 
	id VARCHAR(200) NOT NULL, 
	event_id VARCHAR(200) NOT NULL, 
	processed_at VARCHAR(40), 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (tenant_id, id), 
	FOREIGN KEY(tenant_id, event_id) REFERENCES events (tenant_id, id)
);
