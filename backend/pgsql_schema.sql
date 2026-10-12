-- ==============================================================================

-- File        : dbmgmt_schema_final.sql

-- Purpose     : Verified schema-only CREATE script for the Database

--               Management Console's PostgreSQL repository database.

-- Source      : pg_dump --schema-only --no-owner --no-privileges, run

--               directly on the lab server (dblablinuxsrv01), PG 16.14.

-- Author      : Madhan U (Associate Cloud DBA)

-- Verified On : 2026-09-29 -- counts cross-checked: 17 tables, 12 sequences,

--               17 primary keys, 5 unique constraints, 19 foreign keys,

--               4 indexes. No data, no DROP statements, no owner/grants.

-- Usage       : Connect as the app's dedicated role (dbmgmt_svc) to an

--               EMPTY database so every object is owned by that role

--               automatically, then run this file top to bottom (order

--               matters -- tables/sequences, then defaults, then keys,

--               then indexes, then foreign keys last).

--

--   psql -h 127.0.0.1 -U dbmgmt_svc -d dbmgmt_db -f dbmgmt_schema_final.sql

--

-- Or paste statements one at a time into an interactive psql session,

-- in the order they appear below.

-- ==============================================================================
 
--

-- PostgreSQL database dump

--
 
SET statement_timeout = 0;

SET lock_timeout = 0;

SET idle_in_transaction_session_timeout = 0;

SET client_encoding = 'UTF8';

SET standard_conforming_strings = on;

SELECT pg_catalog.set_config('search_path', '', false);

SET check_function_bodies = false;

SET xmloption = content;

SET client_min_messages = warning;

SET row_security = off;
 
SET default_tablespace = '';
 
SET default_table_access_method = heap;
 
CREATE TABLE public.alembic_version (

    version_num character varying(32) NOT NULL

);
 
CREATE TABLE public.alert_poll_state (

    id integer NOT NULL,

    last_audit_id integer NOT NULL,

    last_run_at timestamp without time zone

);
 
CREATE SEQUENCE public.alert_poll_state_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.alert_poll_state_id_seq OWNED BY public.alert_poll_state.id;
 
CREATE TABLE public.alerts (

    id integer NOT NULL,

    audit_log_id integer NOT NULL,

    ts timestamp without time zone NOT NULL,

    rule_code character varying(80) NOT NULL,

    severity character varying(10) NOT NULL,

    title character varying(200) NOT NULL,

    message text,

    action character varying(80),

    actor_username character varying(80),

    target_type character varying(40),

    target_id character varying(40),

    status character varying(10) NOT NULL,

    channel character varying(20),

    attempts integer NOT NULL,

    error_message text,

    created_at timestamp without time zone NOT NULL,

    sent_at timestamp without time zone

);
 
CREATE SEQUENCE public.alerts_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.alerts_id_seq OWNED BY public.alerts.id;
 
CREATE TABLE public.audit_logs (

    id integer NOT NULL,

    ts timestamp without time zone,

    actor_user_id integer,

    actor_username character varying(80),

    action character varying(80) NOT NULL,

    target_type character varying(40),

    target_id character varying(40),

    detail json,

    source_ip character varying(45)

);
 
CREATE SEQUENCE public.audit_logs_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;
 
CREATE TABLE public.index_recommendations (

    id integer NOT NULL,

    server_id integer NOT NULL,

    namespace character varying(120) NOT NULL,

    rec_type character varying(20) NOT NULL,

    index_name character varying(120),

    index_keys json NOT NULL,

    reason text,

    estimated_impact character varying(255),

    created_at timestamp without time zone,

    updated_at timestamp without time zone

);
 
CREATE SEQUENCE public.index_recommendations_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.index_recommendations_id_seq OWNED BY public.index_recommendations.id;
 
CREATE TABLE public.operation_logs (

    id integer NOT NULL,

    operation_id uuid NOT NULL,

    ts timestamp without time zone,

    level character varying(10),

    message text

);
 
CREATE SEQUENCE public.operation_logs_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.operation_logs_id_seq OWNED BY public.operation_logs.id;
 
CREATE TABLE public.operations (

    id uuid NOT NULL,

    operation_type character varying(60) NOT NULL,

    server_id integer NOT NULL,

    requested_by integer NOT NULL,

    approved_by integer,

    status character varying(30) NOT NULL,

    current_step character varying(120),

    progress_pct integer,

    params json,

    precheck_results json,

    postcheck_results json,

    result character varying(20),

    error_message text,

    started_at timestamp without time zone,

    completed_at timestamp without time zone,

    created_at timestamp without time zone,

    steps json,

    triggered_by_schedule_id integer

);
 
CREATE TABLE public.permissions (

    id integer NOT NULL,

    code character varying(80) NOT NULL,

    description character varying(255)

);
 
CREATE SEQUENCE public.permissions_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.permissions_id_seq OWNED BY public.permissions.id;
 
CREATE TABLE public.role_permissions (

    role_id integer NOT NULL,

    permission_id integer NOT NULL

);
 
CREATE TABLE public.roles (

    id integer NOT NULL,

    name character varying(64) NOT NULL,

    description character varying(255)

);
 
CREATE SEQUENCE public.roles_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.roles_id_seq OWNED BY public.roles.id;
 
CREATE TABLE public.scheduled_operations (

    id integer NOT NULL,

    operation_type character varying(40) NOT NULL,

    server_id integer NOT NULL,

    params json,

    schedule_type character varying(20) NOT NULL,

    run_at timestamp without time zone,

    day_of_week integer,

    time_of_day time without time zone,

    is_active boolean NOT NULL,

    last_triggered_at timestamp without time zone,

    created_by integer NOT NULL,

    created_at timestamp without time zone,

    updated_by integer,

    updated_at timestamp without time zone,

    cancelled_at timestamp without time zone,

    resulting_operation_id uuid,

    interval_minutes integer

);
 
CREATE SEQUENCE public.scheduled_operations_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.scheduled_operations_id_seq OWNED BY public.scheduled_operations.id;
 
CREATE TABLE public.server_health (

    id integer NOT NULL,

    server_id integer NOT NULL,

    checked_at timestamp without time zone,

    reachable_ssh boolean,

    reachable_mongo boolean,

    replica_state character varying(20),

    replication_lag_seconds numeric(10,2),

    cpu_pct numeric(5,2),

    memory_pct numeric(5,2),

    disk_pct numeric(5,2),

    connections_current integer,

    status character varying(20),

    detail text

);
 
CREATE SEQUENCE public.server_health_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.server_health_id_seq OWNED BY public.server_health.id;
 
CREATE TABLE public.servers (

    id integer NOT NULL,

    hostname character varying(120) NOT NULL,

    fqdn character varying(255),

    ip_address character varying(45) NOT NULL,

    environment character varying(20),

    cluster_name character varying(120),

    replica_set_name character varying(120),

    node_role character varying(20),

    port integer,

    mongo_version character varying(20),

    mongo_edition character varying(40),

    os_version character varying(120),

    data_directory character varying(255),

    config_file_path character varying(255),

    cpu_cores integer,

    memory_gb numeric(10,2),

    disk_gb numeric(10,2),

    owner character varying(120),

    application_name character varying(120),

    criticality character varying(10),

    monitoring_enabled boolean,

    backup_status character varying(20),

    maintenance_window character varying(120),

    ssh_credential_ref character varying(40),

    mongo_credential_ref character varying(40),

    is_active boolean,

    static_collected_at timestamp without time zone,

    static_collection_error text,

    created_at timestamp without time zone,

    updated_at timestamp without time zone

);
 
CREATE SEQUENCE public.servers_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.servers_id_seq OWNED BY public.servers.id;
 
CREATE TABLE public.slow_query_logs (

    id integer NOT NULL,

    server_id integer NOT NULL,

    ts timestamp without time zone NOT NULL,

    query_hash character varying(64) NOT NULL,

    namespace character varying(120) NOT NULL,

    operation character varying(20),

    duration_ms integer,

    docs_scanned integer,

    docs_returned integer,

    query_shape json,

    raw_log json

);
 
CREATE SEQUENCE public.slow_query_logs_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.slow_query_logs_id_seq OWNED BY public.slow_query_logs.id;
 
CREATE TABLE public.system_settings (

    key character varying(80) NOT NULL,

    value json NOT NULL,

    updated_by integer,

    updated_at timestamp without time zone

);
 
CREATE TABLE public.user_roles (

    user_id integer NOT NULL,

    role_id integer NOT NULL

);
 
CREATE TABLE public.users (

    id integer NOT NULL,

    username character varying(80) NOT NULL,

    email character varying(120) NOT NULL,

    password_hash character varying(255) NOT NULL,

    full_name character varying(120),

    is_active boolean NOT NULL,

    created_at timestamp without time zone,

    last_login_at timestamp without time zone

);
 
CREATE SEQUENCE public.users_id_seq

    AS integer

    START WITH 1

    INCREMENT BY 1

    NO MINVALUE

    NO MAXVALUE

    CACHE 1;
 
ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;
 
ALTER TABLE ONLY public.alert_poll_state ALTER COLUMN id SET DEFAULT nextval('public.alert_poll_state_id_seq'::regclass);
 
ALTER TABLE ONLY public.alerts ALTER COLUMN id SET DEFAULT nextval('public.alerts_id_seq'::regclass);
 
ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);
 
ALTER TABLE ONLY public.index_recommendations ALTER COLUMN id SET DEFAULT nextval('public.index_recommendations_id_seq'::regclass);
 
ALTER TABLE ONLY public.operation_logs ALTER COLUMN id SET DEFAULT nextval('public.operation_logs_id_seq'::regclass);
 
ALTER TABLE ONLY public.permissions ALTER COLUMN id SET DEFAULT nextval('public.permissions_id_seq'::regclass);
 
ALTER TABLE ONLY public.roles ALTER COLUMN id SET DEFAULT nextval('public.roles_id_seq'::regclass);
 
ALTER TABLE ONLY public.scheduled_operations ALTER COLUMN id SET DEFAULT nextval('public.scheduled_operations_id_seq'::regclass);
 
ALTER TABLE ONLY public.server_health ALTER COLUMN id SET DEFAULT nextval('public.server_health_id_seq'::regclass);
 
ALTER TABLE ONLY public.servers ALTER COLUMN id SET DEFAULT nextval('public.servers_id_seq'::regclass);
 
ALTER TABLE ONLY public.slow_query_logs ALTER COLUMN id SET DEFAULT nextval('public.slow_query_logs_id_seq'::regclass);
 
ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);
 
ALTER TABLE ONLY public.alembic_version

    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);
 
ALTER TABLE ONLY public.alert_poll_state

    ADD CONSTRAINT alert_poll_state_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.alerts

    ADD CONSTRAINT alerts_audit_log_id_key UNIQUE (audit_log_id);
 
ALTER TABLE ONLY public.alerts

    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.audit_logs

    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.index_recommendations

    ADD CONSTRAINT index_recommendations_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.operation_logs

    ADD CONSTRAINT operation_logs_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.operations

    ADD CONSTRAINT operations_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.permissions

    ADD CONSTRAINT permissions_code_key UNIQUE (code);
 
ALTER TABLE ONLY public.permissions

    ADD CONSTRAINT permissions_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.role_permissions

    ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (role_id, permission_id);
 
ALTER TABLE ONLY public.roles

    ADD CONSTRAINT roles_name_key UNIQUE (name);
 
ALTER TABLE ONLY public.roles

    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.scheduled_operations

    ADD CONSTRAINT scheduled_operations_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.server_health

    ADD CONSTRAINT server_health_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.servers

    ADD CONSTRAINT servers_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.slow_query_logs

    ADD CONSTRAINT slow_query_logs_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.system_settings

    ADD CONSTRAINT system_settings_pkey PRIMARY KEY (key);
 
ALTER TABLE ONLY public.user_roles

    ADD CONSTRAINT user_roles_pkey PRIMARY KEY (user_id, role_id);
 
ALTER TABLE ONLY public.users

    ADD CONSTRAINT users_email_key UNIQUE (email);
 
ALTER TABLE ONLY public.users

    ADD CONSTRAINT users_pkey PRIMARY KEY (id);
 
ALTER TABLE ONLY public.users

    ADD CONSTRAINT users_username_key UNIQUE (username);
 
CREATE INDEX ix_index_recommendations_server_id ON public.index_recommendations USING btree (server_id);
 
CREATE INDEX ix_slow_query_logs_query_hash ON public.slow_query_logs USING btree (query_hash);
 
CREATE INDEX ix_slow_query_logs_server_id ON public.slow_query_logs USING btree (server_id);
 
CREATE INDEX ix_slow_query_logs_ts ON public.slow_query_logs USING btree (ts);
 
ALTER TABLE ONLY public.alerts

    ADD CONSTRAINT alerts_audit_log_id_fkey FOREIGN KEY (audit_log_id) REFERENCES public.audit_logs(id);
 
ALTER TABLE ONLY public.audit_logs

    ADD CONSTRAINT audit_logs_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id);
 
ALTER TABLE ONLY public.index_recommendations

    ADD CONSTRAINT index_recommendations_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);
 
ALTER TABLE ONLY public.operation_logs

    ADD CONSTRAINT operation_logs_operation_id_fkey FOREIGN KEY (operation_id) REFERENCES public.operations(id);
 
ALTER TABLE ONLY public.operations

    ADD CONSTRAINT operations_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES public.users(id);
 
ALTER TABLE ONLY public.operations

    ADD CONSTRAINT operations_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id);
 
ALTER TABLE ONLY public.operations

    ADD CONSTRAINT operations_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);
 
ALTER TABLE ONLY public.operations

    ADD CONSTRAINT operations_triggered_by_schedule_id_fkey FOREIGN KEY (triggered_by_schedule_id) REFERENCES public.scheduled_operations(id);
 
ALTER TABLE ONLY public.role_permissions

    ADD CONSTRAINT role_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permissions(id);
 
ALTER TABLE ONLY public.role_permissions

    ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id);
 
ALTER TABLE ONLY public.scheduled_operations

    ADD CONSTRAINT scheduled_operations_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);
 
ALTER TABLE ONLY public.scheduled_operations

    ADD CONSTRAINT scheduled_operations_resulting_operation_id_fkey FOREIGN KEY (resulting_operation_id) REFERENCES public.operations(id);
 
ALTER TABLE ONLY public.scheduled_operations

    ADD CONSTRAINT scheduled_operations_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);
 
ALTER TABLE ONLY public.scheduled_operations

    ADD CONSTRAINT scheduled_operations_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);
 
ALTER TABLE ONLY public.server_health

    ADD CONSTRAINT server_health_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);
 
ALTER TABLE ONLY public.slow_query_logs

    ADD CONSTRAINT slow_query_logs_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id);
 
ALTER TABLE ONLY public.system_settings

    ADD CONSTRAINT system_settings_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(id);
 
ALTER TABLE ONLY public.user_roles

    ADD CONSTRAINT user_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id);
 
ALTER TABLE ONLY public.user_roles

    ADD CONSTRAINT user_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
