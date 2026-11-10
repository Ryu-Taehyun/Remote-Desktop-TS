-- 자동 생성: 서버가 첫 요청 시 동일한 테이블을 자동 생성하므로 수동 실행은 선택 사항입니다.
CREATE TABLE users (
	id UUID NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	username VARCHAR(50) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE remote_sessions (
	id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	access_code VARCHAR(12) NOT NULL, 
	allow_control BOOLEAN NOT NULL, 
	active BOOLEAN NOT NULL, 
	last_seen TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_remote_sessions_owner_id ON remote_sessions (owner_id);
CREATE UNIQUE INDEX ix_remote_sessions_access_code ON remote_sessions (access_code);

CREATE TABLE frames (
	session_id UUID NOT NULL, 
	seq BIGINT NOT NULL, 
	width INTEGER NOT NULL, 
	height INTEGER NOT NULL, 
	mime VARCHAR(20) NOT NULL, 
	data BYTEA NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (session_id), 
	FOREIGN KEY(session_id) REFERENCES remote_sessions (id) ON DELETE CASCADE
);


CREATE TABLE input_events (
	id BIGSERIAL NOT NULL, 
	session_id UUID NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES remote_sessions (id) ON DELETE CASCADE
);

CREATE INDEX ix_input_events_session_id ON input_events (session_id);

CREATE TABLE session_viewers (
	id SERIAL NOT NULL, 
	session_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	joined_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (session_id, user_id), 
	FOREIGN KEY(session_id) REFERENCES remote_sessions (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_session_viewers_session_id ON session_viewers (session_id);

