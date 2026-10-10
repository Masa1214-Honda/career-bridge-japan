begin;

alter table public.candidates
  add column if not exists current_address text,
  add column if not exists preferred_work_location text;

comment on column public.candidates.current_address is
  'Candidate-entered current city/region/address';
comment on column public.candidates.preferred_work_location is
  'Candidate-entered desired work location or remote preference';

commit;
