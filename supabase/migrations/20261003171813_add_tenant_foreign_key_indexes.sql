set lock_timeout = '5s';

create index if not exists presentation_study_tenant_fk_idx
  on public.presentation_states(study_id, institution);

create index if not exists jobs_study_tenant_fk_idx
  on public.analysis_jobs(study_id, institution);

create index if not exists results_study_tenant_fk_idx
  on public.analysis_results(study_id, institution);

create index if not exists draft_history_study_tenant_fk_idx
  on public.report_draft_history(study_id, institution);
