set lock_timeout = '5s';

create table if not exists public.studies (
  id text primary key,
  institution text not null,
  study_uid text not null,
  patient_name text not null,
  patient_id text not null,
  birth_date text,
  sex text,
  accession text,
  study_date text,
  description text,
  modalities text not null,
  status text not null default 'unread',
  created_at double precision not null,
  unique (institution, study_uid),
  unique (id, institution)
);

create table if not exists public.series (
  id text primary key,
  study_id text not null references public.studies(id),
  series_uid text not null,
  modality text not null,
  series_number integer,
  description text,
  laterality text,
  rows integer,
  columns integer,
  created_at double precision not null,
  unique (study_id, series_uid)
);

create table if not exists public.instances (
  id text primary key,
  series_id text not null references public.series(id),
  sop_uid text not null,
  instance_number integer,
  frame_count integer not null,
  transfer_syntax text,
  object_path text not null,
  sha256 text not null,
  metadata_json text not null default '{}',
  created_at double precision not null,
  unique (series_id, sop_uid)
);

create table if not exists public.presentation_states (
  study_id text not null,
  user_id text not null,
  institution text not null,
  state_json text not null,
  updated_at double precision not null,
  version integer not null default 0,
  primary key (study_id, user_id, institution),
  foreign key (study_id, institution) references public.studies(id, institution)
);

create table if not exists public.reports (
  study_id text not null,
  institution text not null,
  status text not null,
  text text not null,
  updated_at double precision not null,
  primary key (study_id, institution),
  foreign key (study_id, institution) references public.studies(id, institution)
);

create table if not exists public.model_registry (
  id text primary key,
  display_name text not null,
  version text not null,
  status text not null,
  intended_use text not null,
  required_sequences_json text not null,
  jurisdictions_json text not null,
  license text not null,
  checksum text,
  enabled integer not null default 0,
  updated_at double precision not null
);

create table if not exists public.analysis_jobs (
  id text primary key,
  institution text not null,
  study_id text not null,
  profile text not null,
  prior_study_id text,
  idempotency_key text not null,
  state text not null,
  manifest_json text not null,
  modules_json text not null,
  message text not null,
  requested_by text not null,
  created_at double precision not null,
  updated_at double precision not null,
  unique (institution, idempotency_key),
  foreign key (study_id, institution) references public.studies(id, institution)
);

create table if not exists public.analysis_results (
  id text primary key,
  institution text not null,
  study_id text not null,
  job_id text not null references public.analysis_jobs(id),
  result_json text not null,
  created_at double precision not null,
  foreign key (study_id, institution) references public.studies(id, institution)
);

create table if not exists public.report_drafts (
  study_id text not null,
  institution text not null,
  version integer not null,
  status text not null,
  findings_text text not null,
  impression_text text not null,
  updated_by text not null,
  updated_at double precision not null,
  primary key (study_id, institution),
  foreign key (study_id, institution) references public.studies(id, institution)
);

create table if not exists public.report_draft_history (
  id text primary key,
  study_id text not null,
  institution text not null,
  version integer not null,
  state_json text not null,
  changed_by text not null,
  changed_at double precision not null,
  foreign key (study_id, institution) references public.studies(id, institution)
);

create table if not exists public.audit_events (
  id bigserial primary key,
  timestamp double precision not null,
  institution text not null,
  user_id text not null,
  role text not null,
  action text not null,
  resource_type text not null,
  resource_id text,
  outcome text not null,
  details_json text not null
);

create table if not exists public.schema_migrations (
  version text primary key,
  applied_at double precision not null
);

create table if not exists public.alembic_version (
  version_num varchar(32) primary key
);

create index if not exists series_study_idx on public.series(study_id);
create index if not exists instances_series_idx on public.instances(series_id);
create index if not exists studies_institution_created_idx on public.studies(institution, created_at desc);
create index if not exists presentation_institution_study_idx on public.presentation_states(institution, study_id);
create index if not exists jobs_institution_study_idx on public.analysis_jobs(institution, study_id, created_at desc);
create index if not exists results_institution_study_idx on public.analysis_results(institution, study_id, created_at desc);
create index if not exists results_job_idx on public.analysis_results(job_id);
create index if not exists draft_history_institution_study_idx on public.report_draft_history(institution, study_id, version desc);
create index if not exists audit_institution_id_idx on public.audit_events(institution, id desc);

create or replace function public.reject_audit_event_mutation()
returns trigger
language plpgsql
set search_path = pg_catalog
as $$
begin
  raise exception 'audit events are immutable';
end;
$$;

revoke all on function public.reject_audit_event_mutation() from public, anon, authenticated;

drop trigger if exists audit_events_no_update on public.audit_events;
create trigger audit_events_no_update
before update on public.audit_events
for each row execute function public.reject_audit_event_mutation();

drop trigger if exists audit_events_no_delete on public.audit_events;
create trigger audit_events_no_delete
before delete on public.audit_events
for each row execute function public.reject_audit_event_mutation();

insert into public.schema_migrations(version, applied_at) values
  ('001-clinical-baseline', extract(epoch from clock_timestamp())),
  ('002-instance-provenance-and-audit-guards', extract(epoch from clock_timestamp())),
  ('003-presentation-version', extract(epoch from clock_timestamp()))
on conflict (version) do nothing;

insert into public.alembic_version(version_num)
values ('20260930_001')
on conflict (version_num) do nothing;

insert into public.model_registry
  (id, display_name, version, status, intended_use, required_sequences_json,
   jurisdictions_json, license, checksum, enabled, updated_at)
values
  ('autorg-brain-rgv2', 'AutoRG-Brain RGv2', 'research', 'candidate',
   'Offline grounded brain MRI report-generation challenger',
   '["T1","T1C","T2","FLAIR","DWI","ADC"]', '[]',
   'research-only; verify upstream terms', null, 0, extract(epoch from clock_timestamp())),
  ('monai-brats', 'MONAI BraTS segmentation', 'pinned-at-deployment', 'candidate',
   'Research baseline for brain-tumor segmentation',
   '["T1","T1C","T2","FLAIR"]', '[]',
   'Apache-2.0 code; verify bundle/data terms', null, 0, extract(epoch from clock_timestamp())),
  ('siemens-airad-brain-mr', 'AI-Rad Companion Brain MR', 'K253057', 'candidate',
   'Commercial morphometry and white-matter-hyperintensity candidate within labeled use',
   '["T1_MPRAGE","FLAIR"]', '["US"]',
   'commercial', null, 0, extract(epoch from clock_timestamp()))
on conflict (id) do nothing;

-- Voxura uses a server-side PostgreSQL connection. Browser clients must not access
-- clinical tables through Supabase Data API roles. RLS without policies is deny-all.
alter table public.studies enable row level security;
alter table public.series enable row level security;
alter table public.instances enable row level security;
alter table public.presentation_states enable row level security;
alter table public.reports enable row level security;
alter table public.model_registry enable row level security;
alter table public.analysis_jobs enable row level security;
alter table public.analysis_results enable row level security;
alter table public.report_drafts enable row level security;
alter table public.report_draft_history enable row level security;
alter table public.audit_events enable row level security;
alter table public.schema_migrations enable row level security;
alter table public.alembic_version enable row level security;

revoke all privileges on all tables in schema public from anon, authenticated;
revoke all privileges on all sequences in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke all on sequences from anon, authenticated;
alter default privileges in schema public revoke execute on functions from anon, authenticated;
