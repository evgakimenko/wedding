-- Свадебный планер: схема базы для Supabase.
-- Запустите целиком один раз: Supabase → SQL Editor → New query → вставить → Run.

create extension if not exists pgcrypto;

-- Свадьба (одна пара = одна запись) и два кода приглашения
create table if not exists public.weddings (
  id          uuid primary key default gen_random_uuid(),
  edit_code   text unique not null default upper(substr(encode(gen_random_bytes(8), 'hex'), 1, 6)),
  view_code   text unique not null default upper(substr(encode(gen_random_bytes(8), 'hex'), 1, 6)),
  created_by  uuid not null default auth.uid(),
  created_at  timestamptz not null default now()
);

-- Участники: p1 — жених, p2 — невеста, viewer — только просмотр
create table if not exists public.members (
  wedding_id  uuid not null references public.weddings(id) on delete cascade,
  user_id     uuid not null,
  role        text not null check (role in ('p1', 'p2', 'viewer')),
  created_at  timestamptz not null default now(),
  primary key (wedding_id, user_id)
);

-- Все данные планера: категории, подрядчики, платежи, задачи, гости и т. д.
create table if not exists public.docs (
  wedding_id  uuid not null references public.weddings(id) on delete cascade,
  coll        text not null,
  id          text not null,
  data        jsonb not null default '{}'::jsonb,
  updated_by  uuid default auth.uid(),
  updated_at  timestamptz not null default now(),
  primary key (wedding_id, coll, id)
);

alter table public.weddings enable row level security;
alter table public.members  enable row level security;
alter table public.docs     enable row level security;

create or replace function public.is_member(w uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from members where wedding_id = w and user_id = auth.uid());
$$;

create or replace function public.can_edit(w uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from members where wedding_id = w and user_id = auth.uid() and role in ('p1', 'p2'));
$$;

drop policy if exists "weddings read"  on public.weddings;
drop policy if exists "members read"   on public.members;
drop policy if exists "docs read"      on public.docs;
drop policy if exists "docs insert"    on public.docs;
drop policy if exists "docs update"    on public.docs;
drop policy if exists "docs delete"    on public.docs;

create policy "weddings read" on public.weddings for select using (public.is_member(id));
create policy "members read"  on public.members  for select using (public.is_member(wedding_id));
create policy "docs read"     on public.docs     for select using (public.is_member(wedding_id));
create policy "docs insert"   on public.docs     for insert with check (public.can_edit(wedding_id));
create policy "docs update"   on public.docs     for update using (public.can_edit(wedding_id)) with check (public.can_edit(wedding_id));
create policy "docs delete"   on public.docs     for delete using (public.can_edit(wedding_id));

-- Коды приглашения видят только жених и невеста
revoke select on public.weddings from anon, authenticated;
grant select (id, created_by, created_at) on public.weddings to authenticated;

-- Создать свадьбу: текущий пользователь становится женихом (p1) или невестой (p2)
create or replace function public.create_wedding(my_role text) returns uuid
language plpgsql security definer set search_path = public as $$
declare w uuid;
begin
  if auth.uid() is null then raise exception 'not authenticated'; end if;
  if my_role not in ('p1', 'p2') then raise exception 'bad role'; end if;
  insert into weddings (created_by) values (auth.uid()) returning id into w;
  insert into members (wedding_id, user_id, role) values (w, auth.uid(), my_role);
  return w;
end $$;

-- Присоединиться по коду: код редактора даёт свободную роль p1/p2, код зрителя — просмотр
create or replace function public.join_wedding(code text) returns uuid
language plpgsql security definer set search_path = public as $$
declare w weddings; r text; taken text[];
begin
  if auth.uid() is null then raise exception 'not authenticated'; end if;
  select * into w from weddings where edit_code = upper(trim(code)) or view_code = upper(trim(code));
  if not found then raise exception 'invalid code'; end if;
  if exists (select 1 from members where wedding_id = w.id and user_id = auth.uid()) then return w.id; end if;
  if w.view_code = upper(trim(code)) then r := 'viewer';
  else
    select array_agg(role) into taken from members where wedding_id = w.id;
    if not ('p1' = any(coalesce(taken, '{}'))) then r := 'p1';
    elsif not ('p2' = any(coalesce(taken, '{}'))) then r := 'p2';
    else raise exception 'wedding is full';
    end if;
  end if;
  insert into members (wedding_id, user_id, role) values (w.id, auth.uid(), r);
  return w.id;
end $$;

-- Коды приглашения (только для жениха и невесты)
create or replace function public.invite_codes(w uuid) returns table (edit_code text, view_code text)
language sql stable security definer set search_path = public as $$
  select edit_code, view_code from weddings where id = w and public.can_edit(w);
$$;

-- Выйти из свадьбы (например, убрать координатора) — только жених/невеста
create or replace function public.remove_member(w uuid, uid uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if not public.can_edit(w) then raise exception 'forbidden'; end if;
  delete from members where wedding_id = w and user_id = uid and role = 'viewer';
end $$;

revoke all on function public.create_wedding(text), public.join_wedding(text), public.invite_codes(uuid), public.remove_member(uuid, uuid) from public, anon;
grant execute on function public.create_wedding(text), public.join_wedding(text), public.invite_codes(uuid), public.remove_member(uuid, uuid) to authenticated;
grant select, insert, update, delete on public.docs to authenticated;
grant select on public.members to authenticated;

-- Живая синхронизация между телефонами
alter table public.docs replica identity full;
do $$ begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    begin
      alter publication supabase_realtime add table public.docs;
    exception when duplicate_object then null;
    end;
  end if;
end $$;
