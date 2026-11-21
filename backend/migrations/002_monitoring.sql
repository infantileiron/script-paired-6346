-- 持续监测模块 DDL（与 src/models/entities.py 中 ORM 定义对应）
CREATE TABLE public.monitors (
    id integer NOT NULL,
    adoption_id integer NOT NULL,
    evaluation_id integer NOT NULL,
    threshold double precision NOT NULL,
    baseline_after_mean double precision NOT NULL,
    baseline_before_mean double precision,
    frozen_scope json NOT NULL,
    state character varying(20) DEFAULT 'active',
    created character varying(40)
);
CREATE SEQUENCE public.monitors_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.monitors_id_seq OWNED BY public.monitors.id;
ALTER TABLE ONLY public.monitors ALTER COLUMN id SET DEFAULT nextval('public.monitors_id_seq');
ALTER TABLE ONLY public.monitors ADD CONSTRAINT monitors_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.monitors ADD CONSTRAINT monitors_adoption_id_key UNIQUE (adoption_id);
ALTER TABLE ONLY public.monitors ADD CONSTRAINT monitors_adoption_id_fkey FOREIGN KEY (adoption_id) REFERENCES public.adoptions(id);
ALTER TABLE ONLY public.monitors ADD CONSTRAINT monitors_evaluation_id_fkey FOREIGN KEY (evaluation_id) REFERENCES public.evaluations(id);

CREATE TABLE public.monitor_jobs (
    id integer NOT NULL,
    monitor_id integer NOT NULL,
    client_token character varying(80),
    state character varying(20) DEFAULT 'pending',
    error text DEFAULT '',
    payload json,
    created character varying(40),
    updated character varying(40)
);
CREATE SEQUENCE public.monitor_jobs_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.monitor_jobs_id_seq OWNED BY public.monitor_jobs.id;
ALTER TABLE ONLY public.monitor_jobs ALTER COLUMN id SET DEFAULT nextval('public.monitor_jobs_id_seq');
ALTER TABLE ONLY public.monitor_jobs ADD CONSTRAINT monitor_jobs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.monitor_jobs ADD CONSTRAINT monitor_jobs_token_uc UNIQUE (monitor_id, client_token);
CREATE INDEX monitor_jobs_state_idx ON public.monitor_jobs USING btree (state);
ALTER TABLE ONLY public.monitor_jobs ADD CONSTRAINT monitor_jobs_monitor_id_fkey FOREIGN KEY (monitor_id) REFERENCES public.monitors(id);

CREATE TABLE public.monitor_records (
    id integer NOT NULL,
    monitor_id integer NOT NULL,
    biz_date date NOT NULL,
    sample_no character varying(60) NOT NULL,
    code character varying(60) NOT NULL,
    version character varying(60) NOT NULL,
    score double precision NOT NULL,
    job_id integer NOT NULL,
    created character varying(40)
);
CREATE SEQUENCE public.monitor_records_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.monitor_records_id_seq OWNED BY public.monitor_records.id;
ALTER TABLE ONLY public.monitor_records ALTER COLUMN id SET DEFAULT nextval('public.monitor_records_id_seq');
ALTER TABLE ONLY public.monitor_records ADD CONSTRAINT monitor_records_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.monitor_records ADD CONSTRAINT monitor_records_no_uc UNIQUE (monitor_id, sample_no);
CREATE INDEX monitor_records_lookup_idx ON public.monitor_records USING btree (monitor_id, biz_date, code);
ALTER TABLE ONLY public.monitor_records ADD CONSTRAINT monitor_records_monitor_id_fkey FOREIGN KEY (monitor_id) REFERENCES public.monitors(id);
ALTER TABLE ONLY public.monitor_records ADD CONSTRAINT monitor_records_job_id_fkey FOREIGN KEY (job_id) REFERENCES public.monitor_jobs(id);

CREATE TABLE public.monitor_dailies (
    id integer NOT NULL,
    monitor_id integer NOT NULL,
    biz_date date NOT NULL,
    code character varying(60) NOT NULL,
    score double precision NOT NULL,
    delta double precision NOT NULL,
    day_mean double precision NOT NULL,
    improvement double precision NOT NULL,
    consultant_count integer NOT NULL
);
CREATE SEQUENCE public.monitor_dailies_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.monitor_dailies_id_seq OWNED BY public.monitor_dailies.id;
ALTER TABLE ONLY public.monitor_dailies ALTER COLUMN id SET DEFAULT nextval('public.monitor_dailies_id_seq');
ALTER TABLE ONLY public.monitor_dailies ADD CONSTRAINT monitor_dailies_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.monitor_dailies ADD CONSTRAINT monitor_dailies_uc UNIQUE (monitor_id, biz_date, code);
CREATE INDEX monitor_dailies_day_idx ON public.monitor_dailies USING btree (monitor_id, biz_date);
ALTER TABLE ONLY public.monitor_dailies ADD CONSTRAINT monitor_dailies_monitor_id_fkey FOREIGN KEY (monitor_id) REFERENCES public.monitors(id);

CREATE TABLE public.monitor_alerts (
    id integer NOT NULL,
    monitor_id integer NOT NULL,
    status character varying(20) DEFAULT 'active',
    start_date date NOT NULL,
    end_date date NOT NULL,
    trigger_date date NOT NULL,
    threshold double precision NOT NULL,
    basis json NOT NULL,
    basis_revision integer DEFAULT 0,
    confirmed_by character varying(100),
    confirmed_at character varying(40),
    revoked_by character varying(100),
    revoked_at character varying(40),
    revoke_reason text DEFAULT '',
    created character varying(40),
    updated character varying(40)
);
CREATE SEQUENCE public.monitor_alerts_id_seq AS integer START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
ALTER SEQUENCE public.monitor_alerts_id_seq OWNED BY public.monitor_alerts.id;
ALTER TABLE ONLY public.monitor_alerts ALTER COLUMN id SET DEFAULT nextval('public.monitor_alerts_id_seq');
ALTER TABLE ONLY public.monitor_alerts ADD CONSTRAINT monitor_alerts_pkey PRIMARY KEY (id);
CREATE INDEX monitor_alerts_monitor_idx ON public.monitor_alerts USING btree (monitor_id, status);
ALTER TABLE ONLY public.monitor_alerts ADD CONSTRAINT monitor_alerts_monitor_id_fkey FOREIGN KEY (monitor_id) REFERENCES public.monitors(id);
