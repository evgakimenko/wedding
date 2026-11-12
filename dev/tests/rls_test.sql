\set ON_ERROR_STOP 0
create temp table r(name text, ok bool);
grant all on r to authenticated;
-- Женя создаёт свадьбу
set role authenticated;
set request.jwt.claim.sub = '11111111-1111-1111-1111-111111111111';
select public.create_wedding('p1') as w \gset
insert into docs(wedding_id,coll,id,data) values (:'w','tasks','t1','{"title":"x"}');
select (select count(*) from docs)=1 as ok \gset
insert into r values ('Женя пишет и читает', :'ok');
select edit_code, view_code from public.invite_codes(:'w') \gset
insert into r values ('Женя видит коды', length(:'edit_code')=6 and :'edit_code' <> :'view_code');
-- Катя по коду редактора → p2
set request.jwt.claim.sub = '22222222-2222-2222-2222-222222222222';
select (select count(*) from docs)=0 as ok \gset
insert into r values ('Катя до входа ничего не видит', :'ok');
select public.join_wedding(lower(:'edit_code')) = :'w' as ok \gset
insert into r values ('Катя присоединилась (код без учёта регистра)', :'ok');
select (select role from members where user_id=auth.uid())='p2' as ok \gset
insert into r values ('Катя получила роль p2', :'ok');
update docs set data='{"title":"y"}' where id='t1';
select (select data->>'title' from docs where id='t1')='y' as ok \gset
insert into r values ('Катя редактирует', :'ok');
-- Координатор по коду просмотра
set request.jwt.claim.sub = '33333333-3333-3333-3333-333333333333';
select public.join_wedding(:'view_code') = :'w' as ok \gset
insert into r values ('Координатор присоединился', :'ok');
select (select count(*) from docs)=1 as ok \gset
insert into r values ('Координатор читает', :'ok');
update docs set data='{"title":"hack"}' where id='t1';
delete from docs where id='t1';
insert into docs(wedding_id,coll,id,data) values (:'w','tasks','t2','{}');
reset role; select (select data->>'title' from docs where id='t1')='y' and (select count(*) from docs)=1 as ok \gset
set role authenticated; set request.jwt.claim.sub = '33333333-3333-3333-3333-333333333333';
insert into r values ('Координатор НЕ может менять/удалять/создавать', :'ok');
select count(*)=0 as ok from public.invite_codes(:'w') \gset
insert into r values ('Координатор не видит коды', :'ok');
-- Посторонний
set request.jwt.claim.sub = '44444444-4444-4444-4444-444444444444';
select (select count(*) from docs)=0 and (select count(*) from members)=0 as ok \gset
insert into r values ('Посторонний ничего не видит', :'ok');
insert into docs(wedding_id,coll,id,data) values (:'w','tasks','t3','{}');
select public.join_wedding('ZZZZZZ');
select public.join_wedding(:'edit_code');
reset role; select (select count(*) from members where wedding_id=:'w')=3 and (select count(*) from docs)=1 as ok \gset
insert into r values ('Посторонний не пишет; неверный код и «полная» свадьба отклонены', :'ok');
-- аноним
set role anon; reset request.jwt.claim.sub;
select public.create_wedding('p1');
reset role;
select name, ok from r order by ctid;
